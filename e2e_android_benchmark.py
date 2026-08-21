#!/usr/bin/env python3
"""Matched autoregressive transformer benchmark for a simulated Android CPU.

The process is intended to run pinned to one host core with one thread. It is
not a substitute for a physical ARM64 phone benchmark. PyTorch and ONNX use a
fixed-shape one-token decoder step with preallocated KV tensors; HyperC uses
its corresponding float32/int8/int4 cache paths.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import psutil
import torch
import torch.nn as nn

from hyperc_android_transformer import AndroidMHA
from hyperc_quantized_transformer import QuantizedAndroidMHA
from hyperc_transformer import MultiHeadSelfAttention, TransformerSpec


class TorchStepAttention(nn.Module):
    def __init__(self, attention: MultiHeadSelfAttention, max_tokens: int):
        super().__init__()
        self.d_model = attention.spec.d_model
        self.heads = attention.spec.heads
        self.head_dim = attention.head_dim
        self.max_tokens = max_tokens
        self.q = nn.Linear(self.d_model, self.d_model, bias=False)
        self.k = nn.Linear(self.d_model, self.d_model, bias=False)
        self.v = nn.Linear(self.d_model, self.d_model, bias=False)
        self.o = nn.Linear(self.d_model, self.d_model, bias=False)
        with torch.no_grad():
            self.q.weight.copy_(torch.from_numpy(attention.wq.T))
            self.k.weight.copy_(torch.from_numpy(attention.wk.T))
            self.v.weight.copy_(torch.from_numpy(attention.wv.T))
            self.o.weight.copy_(torch.from_numpy(attention.wo.T))

    def forward(self, token, past_k, past_v, past_len):
        q = self.q(token).view(1, 1, self.heads, self.head_dim).transpose(1, 2)
        k_new = self.k(token).view(1, 1, self.heads, self.head_dim).transpose(1, 2)
        v_new = self.v(token).view(1, 1, self.heads, self.head_dim).transpose(1, 2)
        index = past_len.to(torch.int64).reshape(())
        marker = torch.nn.functional.one_hot(index, num_classes=self.max_tokens).to(token.dtype).reshape(1, 1, self.max_tokens, 1)
        present_k = past_k * (1.0 - marker) + k_new * marker
        present_v = past_v * (1.0 - marker) + v_new * marker
        scores = torch.matmul(q, present_k.transpose(-1, -2)) / (self.head_dim ** 0.5)
        positions = torch.arange(self.max_tokens, device=token.device).reshape(1, 1, 1, self.max_tokens)
        mask = positions <= past_len.reshape(1, 1, 1, 1)
        scores = scores.masked_fill(~mask, -1e9)
        weights = torch.softmax(scores, dim=-1)
        context = torch.matmul(weights, present_v).transpose(1, 2).reshape(1, 1, self.d_model)
        return self.o(context), present_k, present_v


def export_onnx(model: TorchStepAttention, path: Path, max_tokens: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    token = torch.zeros((1, 1, model.d_model), dtype=torch.float32)
    past_k = torch.zeros((1, model.heads, max_tokens, model.head_dim), dtype=torch.float32)
    past_v = torch.zeros_like(past_k)
    past_len = torch.zeros((), dtype=torch.int64)
    with torch.no_grad():
        torch.onnx.export(
            model,
            (token, past_k, past_v, past_len),
            str(path),
            input_names=["token", "past_k", "past_v", "past_len"],
            output_names=["output", "present_k", "present_v"],
            opset_version=17,
            do_constant_folding=True,
        )


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), p))


def traffic_bytes(weight_bytes: int, heads: int, head_dim: int, tokens: int, kv_bytes: int = 4) -> int:
    # Per decode step, read the prior K and V prefix. This is an estimate, not
    # a hardware counter; it excludes cache reuse and kernel-specific tiling.
    kv_prefix_reads = 2 * heads * head_dim * kv_bytes * sum(range(tokens))
    return int(weight_bytes + kv_prefix_reads)


def stats_for(name: str, durations_ms: list[float], tokens: int, weight_bytes: int, heads: int, head_dim: int, rss_delta: float, model_bytes: int) -> dict[str, object]:
    median_ms = float(statistics.median(durations_ms))
    estimated = traffic_bytes(weight_bytes, heads, head_dim, tokens)
    return {
        "name": name,
        "runs": len(durations_ms),
        "median_sequence_ms": median_ms,
        "p50_sequence_ms": percentile(durations_ms, 50),
        "p95_sequence_ms": percentile(durations_ms, 95),
        "tokens_per_second": tokens / (median_ms / 1000.0),
        "estimated_traffic_bytes_per_sequence": estimated,
        "estimated_traffic_mib_per_sequence": estimated / (1024 * 1024),
        "estimated_effective_bandwidth_gib_per_second": (estimated / (median_ms / 1000.0)) / (1024 ** 3),
        "model_weight_bytes": int(weight_bytes),
        "model_storage_bytes": int(model_bytes),
        "rss_delta_mb": float(rss_delta),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=int, default=64)
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("e2e_android_benchmark"))
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    np.random.seed(17)
    spec = TransformerSpec(d_model=64, heads=8, d_ff=256, causal=True)
    reference = MultiHeadSelfAttention(spec, seed=7)
    rng = np.random.default_rng(123)
    inputs = rng.standard_normal((args.tokens, spec.d_model), dtype=np.float32)
    results: dict[str, object] = {
        "conditions": {
            "host_arch": os.uname().machine,
            "simulated_target": "Android ARM64 single-core, one-thread approximation",
            "tokens": args.tokens,
            "d_model": spec.d_model,
            "heads": spec.heads,
            "head_dim": spec.d_model // spec.heads,
            "runs": args.runs,
            "warmup": args.warmup,
            "note": "sandbox x86-64 measurements; no physical ARM64 execution",
        },
        "results": [],
        "accuracy": {},
    }

    # HyperC float and quantized decode paths.
    hyperc_float = MultiHeadSelfAttention(spec, seed=7)
    hyperc_int8 = QuantizedAndroidMHA(reference, args.tokens, 8, spec.d_model)
    hyperc_int4 = QuantizedAndroidMHA(reference, args.tokens, 4, 16)
    hyperc_modes = [
        ("hyperc_float32", hyperc_float, sum(w.nbytes for w in (reference.wq, reference.wk, reference.wv, reference.wo)), "float"),
        ("hyperc_int8", hyperc_int8, hyperc_int8.weight_memory_bytes, "quant"),
        ("hyperc_int4", hyperc_int4, hyperc_int4.weight_memory_bytes, "quant"),
    ]
    float_cache = __import__("hyperc_transformer").KVCache.empty(spec.heads, spec.d_model // spec.heads)
    float_final = None
    for token in inputs:
        float_final, float_cache = hyperc_float.decode_one(token.reshape(1, 1, spec.d_model), float_cache)
    for name, model, weight_bytes, kind in hyperc_modes:
        before = rss_mb()
        durations = []
        for _ in range(args.warmup):
            model.reset() if hasattr(model, "reset") else None
            warm_cache = __import__("hyperc_transformer").KVCache.empty(spec.heads, spec.d_model // spec.heads) if kind == "float" else None
            for token in inputs:
                if kind == "float":
                    model.decode_one(token.reshape(1, 1, spec.d_model), warm_cache)
                else:
                    model.decode_one(token)
        after_load = rss_mb()
        for _ in range(args.runs):
            cache = __import__("hyperc_transformer").KVCache.empty(spec.heads, spec.d_model // spec.heads) if kind == "float" else None
            if hasattr(model, "reset"):
                model.reset()
            start = time.perf_counter()
            final = None
            for token in inputs:
                final = model.decode_one(token.reshape(1, 1, spec.d_model), cache) if kind == "float" else model.decode_one(token)
            durations.append((time.perf_counter() - start) * 1000)
        error = float(np.max(np.abs(float_final - final))) if name != "hyperc_float32" else 0.0
        results["accuracy"][name] = {"final_token_max_abs_error_vs_hyperc_float32": error}
        model_storage = weight_bytes + (hyperc_int4.buffers.memory_bytes if kind == "quant" else 2 * args.tokens * spec.heads * (spec.d_model // spec.heads) * 4)
        results["results"].append(stats_for(name, durations, args.tokens, weight_bytes, spec.heads, spec.d_model // spec.heads, after_load - before, model_storage))

    # PyTorch reference.
    torch_model = TorchStepAttention(reference, args.tokens).eval()
    before = rss_mb()
    torch_model = torch_model.eval()
    after_load = rss_mb()
    torch_past_k = torch.zeros((1, spec.heads, args.tokens, spec.d_model // spec.heads), dtype=torch.float32)
    torch_past_v = torch.zeros_like(torch_past_k)
    token_tensor = torch.from_numpy(inputs)
    with torch.no_grad():
        for _ in range(args.warmup):
            pk, pv = torch_past_k.clone(), torch_past_v.clone()
            for idx in range(args.tokens):
                _, pk, pv = torch_model(token_tensor[idx:idx + 1].reshape(1, 1, -1), pk, pv, torch.tensor(idx))
        durations = []
        torch_final = None
        for _ in range(args.runs):
            pk, pv = torch_past_k.clone(), torch_past_v.clone()
            start = time.perf_counter()
            for idx in range(args.tokens):
                torch_final, pk, pv = torch_model(token_tensor[idx:idx + 1].reshape(1, 1, -1), pk, pv, torch.tensor(idx))
            durations.append((time.perf_counter() - start) * 1000)
    torch_error = float(np.max(np.abs(float_final - torch_final.numpy())))
    torch_weight_bytes = 4 * spec.d_model * spec.d_model * 4
    results["accuracy"]["pytorch_float32"] = {"final_token_max_abs_error_vs_hyperc_float32": torch_error}
    results["results"].append(stats_for("pytorch_float32", durations, args.tokens, torch_weight_bytes, spec.heads, spec.d_model // spec.heads, after_load - before, torch_weight_bytes + 2 * args.tokens * spec.heads * (spec.d_model // spec.heads) * 4))

    # ONNX export and runtime.
    args.output.mkdir(parents=True, exist_ok=True)
    onnx_path = args.output / "transformer_step.onnx"
    export_onnx(torch_model, onnx_path, args.tokens)
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"], sess_options=ort.SessionOptions())
    session.set_providers(["CPUExecutionProvider"])
    before = rss_mb()
    after_load = rss_mb()
    onnx_pk = np.zeros((1, spec.heads, args.tokens, spec.d_model // spec.heads), dtype=np.float32)
    onnx_pv = np.zeros_like(onnx_pk)
    for _ in range(args.warmup):
        pk, pv = onnx_pk.copy(), onnx_pv.copy()
        for idx in range(args.tokens):
            out, pk, pv = session.run(None, {"token": inputs[idx:idx + 1].reshape(1, 1, -1), "past_k": pk, "past_v": pv, "past_len": np.asarray(idx, dtype=np.int64)})
    durations = []
    onnx_final = None
    for _ in range(args.runs):
        pk, pv = onnx_pk.copy(), onnx_pv.copy()
        start = time.perf_counter()
        for idx in range(args.tokens):
            onnx_final, pk, pv = session.run(None, {"token": inputs[idx:idx + 1].reshape(1, 1, -1), "past_k": pk, "past_v": pv, "past_len": np.asarray(idx, dtype=np.int64)})
        durations.append((time.perf_counter() - start) * 1000)
    onnx_error = float(np.max(np.abs(float_final - onnx_final)))
    results["accuracy"]["onnxruntime_float32"] = {"final_token_max_abs_error_vs_hyperc_float32": onnx_error}
    results["results"].append(stats_for("onnxruntime_float32", durations, args.tokens, torch_weight_bytes, spec.heads, spec.d_model // spec.heads, after_load - before, torch_weight_bytes + 2 * args.tokens * spec.heads * (spec.d_model // spec.heads) * 4))
    results["artifacts"] = {"onnx_model": str(onnx_path), "onnx_bytes": onnx_path.stat().st_size}
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
