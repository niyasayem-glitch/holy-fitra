#!/usr/bin/env python3
"""Quality-gated mixed int4/int8 transformer quantization.

The robust production policy is not to force every layer into int4. It uses
calibration to keep layers in int4 only when their local reconstruction error
passes a gate, and promotes sensitive projections to int8 otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np

from hyperc_android_transformer import AndroidBuffers
from hyperc_awq import calibrate_matrix
from holyfitra_quant_utils import calibration_mse
from hyperc_quantized_transformer import QuantizedAndroidMHA, QuantizedFeedForward, QuantizedMatrix
from hyperc_transformer import FeedForward, KVCache, MultiHeadSelfAttention, TransformerSpec, gelu


class Float16Matrix:
    def __init__(self, weight: np.ndarray):
        self.weight = np.ascontiguousarray(weight, dtype=np.float16)
        self._float32_weight = np.ascontiguousarray(self.weight, dtype=np.float32)

    @property
    def storage_bytes(self) -> int:
        return int(self.weight.nbytes)

    @property
    def raw_weight_bytes(self) -> int:
        return int(self.weight.size * 4)

    @property
    def compression_ratio(self) -> float:
        return self.raw_weight_bytes / self.storage_bytes

    def matvec(self, vector: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
        result = np.asarray(vector, dtype=np.float32) @ self._float32_weight
        if out is not None:
            out[...] = result
            return out
        return result

    def matmat(self, matrix: np.ndarray) -> np.ndarray:
        matrix = np.ascontiguousarray(matrix, dtype=np.float32)
        return matrix @ self._float32_weight


def gated_matrix(weight: np.ndarray, calibration: np.ndarray, group_size: int, threshold: float):
    calibrated = calibrate_matrix(weight, calibration, 4, group_size, sidecar_fraction=0.10)
    if calibrated.calibration_mse <= threshold:
        return calibrated, "int4_awq"
    int8 = QuantizedMatrix.quantize(weight, 8, weight.shape[0])
    int8_mse = calibration_mse(weight, calibration, int8)
    if int8_mse <= threshold:
        return int8, "int8_fallback"
    return Float16Matrix(weight), "float16_fallback"


class HybridMHA(QuantizedAndroidMHA):
    def __init__(self, attention: MultiHeadSelfAttention, calibration: np.ndarray, max_tokens: int, group_size: int, threshold: float):
        self.attention = attention
        self.spec = attention.spec
        self.head_dim = attention.head_dim
        self.scale = np.float32(1.0 / math.sqrt(self.head_dim))
        self.bits = 4
        self.group_size = group_size
        self.buffers = AndroidBuffers(max_tokens, self.spec.heads, self.head_dim, self.spec.d_model)
        self.wq, q_mode = gated_matrix(attention.wq, calibration, group_size, threshold)
        self.wk, k_mode = gated_matrix(attention.wk, calibration, group_size, threshold)
        self.wv, v_mode = gated_matrix(attention.wv, calibration, group_size, threshold)
        # Output projection error is amplified by the residual path; use the same gate.
        self.wo, o_mode = gated_matrix(attention.wo, calibration, group_size, threshold)
        self.weights = (self.wq, self.wk, self.wv, self.wo)
        self.modes = {"q": q_mode, "k": k_mode, "v": v_mode, "o": o_mode}

    @property
    def weight_memory_bytes(self) -> int:
        return sum(weight.storage_bytes for weight in self.weights)

    @property
    def float_weight_memory_bytes(self) -> int:
        return sum(weight.raw_weight_bytes for weight in self.weights)


class HybridFFN(QuantizedFeedForward):
    def __init__(self, feed_forward: FeedForward, calibration: np.ndarray, group_size: int, threshold: float):
        self.w1, mode1 = gated_matrix(feed_forward.w1, calibration, group_size, threshold)
        hidden = gelu(calibration @ feed_forward.w1 + feed_forward.b1).astype(np.float32)
        self.w2, mode2 = gated_matrix(feed_forward.w2, hidden, group_size, threshold)
        self.b1 = np.asarray(feed_forward.b1, dtype=np.float32)
        self.b2 = np.asarray(feed_forward.b2, dtype=np.float32)
        self.modes = {"w1": mode1, "w2": mode2}

    @property
    def weight_memory_bytes(self) -> int:
        return self.w1.storage_bytes + self.w2.storage_bytes

    @property
    def float_weight_memory_bytes(self) -> int:
        return self.w1.raw_weight_bytes + self.w2.raw_weight_bytes

    def forward(self, x: np.ndarray) -> np.ndarray:
        return self.w2.matvec(gelu(self.w1.matvec(x) + self.b1)) + self.b2


def run_decode(model, inputs):
    model.reset()
    out = None
    for token in inputs:
        out = model.decode_one(token)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=int, default=128)
    parser.add_argument("--calibration-samples", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.006)
    args = parser.parse_args()
    spec = TransformerSpec(d_model=64, heads=8, d_ff=256, causal=True)
    attention = MultiHeadSelfAttention(spec, seed=7)
    feed_forward = FeedForward(spec, seed=11)
    rng = np.random.default_rng(9)
    inputs = rng.standard_normal((args.tokens, spec.d_model), dtype=np.float32)
    calibration = rng.standard_normal((args.calibration_samples, spec.d_model), dtype=np.float32)
    base_cache = KVCache.empty(spec.heads, spec.d_model // spec.heads)
    base_final = None
    for token in inputs:
        base_final, base_cache = attention.decode_one(token.reshape(1, 1, spec.d_model), base_cache)
    naive = QuantizedAndroidMHA(attention, args.tokens, 4, 16)
    naive_ffn = QuantizedFeedForward(feed_forward, 4, 16)
    hybrid = HybridMHA(attention, calibration, args.tokens, 16, args.threshold)
    hybrid_ffn = HybridFFN(feed_forward, calibration, 16, args.threshold)
    results = {"threshold": args.threshold, "modes": {}}
    for label, model, ffn in (("naive_int4", naive, naive_ffn), ("quality_gated", hybrid, hybrid_ffn)):
        run_decode(model, inputs)
        start = time.perf_counter()
        for _ in range(args.repeats):
            run_decode(model, inputs)
        elapsed_ms = (time.perf_counter() - start) * 1000 / args.repeats
        final = run_decode(model, inputs)
        sample = rng.standard_normal(spec.d_model, dtype=np.float32)
        ffn_error = float(np.max(np.abs(feed_forward(sample) - ffn.forward(sample))))
        results["modes"][label] = {
            "decode_ms": elapsed_ms,
            "attention_max_abs_error": float(np.max(np.abs(base_final - final))),
            "ffn_max_abs_error": ffn_error,
            "weight_bytes": model.weight_memory_bytes + ffn.weight_memory_bytes,
            "total_with_buffers": model.weight_memory_bytes + ffn.weight_memory_bytes + model.buffers.memory_bytes,
            "attention_precision": getattr(model, "modes", None),
            "ffn_precision": getattr(ffn, "modes", None),
        }
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
