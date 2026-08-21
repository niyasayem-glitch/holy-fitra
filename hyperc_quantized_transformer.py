#!/usr/bin/env python3
"""Calibration-friendly quantized transformer reference implementations."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nibbleflow import PackedNibbleFlow, quantize_weight


@dataclass
class QuantizedMatrix:
    packed: PackedNibbleFlow
    bits: int
    _raw_shape: tuple[int, int]

    @classmethod
    def quantize(cls, weight: np.ndarray, bits: int, group_size: int) -> "QuantizedMatrix":
        weight = np.asarray(weight, dtype=np.float32)
        if weight.ndim != 2:
            raise ValueError("weight must be rank-2 [in, out]")
        if bits not in {4, 8}:
            raise ValueError("only int4 and int8 are supported")
        if bits == 4:
            packed = quantize_weight(weight.T, group_size=group_size)
        else:
            # Keep the same matrix-vector orientation as NibbleFlow while using
            # signed int8 values and one scale per output row.
            out_dim, in_dim = weight.shape[1], weight.shape[0]
            values = weight.T
            scales = np.max(np.abs(values), axis=1, keepdims=True).astype(np.float32) / 127.0
            scales[scales == 0] = 1.0
            quantized = np.clip(np.rint(values / scales), -128, 127).astype(np.int8)
            packed = _PackedInt8(values.shape[1], values.shape[0], quantized, scales.reshape(-1))
        return cls(packed, bits, tuple(weight.shape))

    @property
    def storage_bytes(self) -> int:
        if hasattr(self.packed, "storage_bytes"):
            return int(self.packed.storage_bytes)
        return int(self.packed.packed.nbytes + self.packed.scales.nbytes)

    @property
    def raw_weight_bytes(self) -> int:
        return int(np.prod(self._raw_shape) * 4)

    @property
    def compression_ratio(self) -> float:
        return self.raw_weight_bytes / max(1, self.storage_bytes)

    def matvec(self, vector: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
        if hasattr(self.packed, "matvec_reference"):
            result = self.packed.matvec_reference(vector)
        else:
            result = self.packed.matvec(vector)
        if out is not None:
            out[...] = result
            return out
        return result


class _PackedInt8:
    def __init__(self, in_dim: int, out_dim: int, values: np.ndarray, scales: np.ndarray):
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.values = np.ascontiguousarray(values, dtype=np.int8)
        self.scales = np.ascontiguousarray(scales, dtype=np.float32)

    @property
    def storage_bytes(self) -> int:
        return int(self.values.nbytes + self.scales.nbytes)

    def matvec(self, vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != self.in_dim:
            raise ValueError("vector dimension mismatch")
        return (vector @ self.values.astype(np.float32).T * self.scales).astype(np.float32)


class QuantizedAndroidMHA:
    def __init__(self, attention, max_tokens: int, bits: int = 4, group_size: int = 16):
        from hyperc_android_transformer import AndroidBuffers

        self.attention = attention
        self.spec = attention.spec
        self.head_dim = attention.head_dim
        self.scale = np.float32(1.0 / math.sqrt(self.head_dim))
        self.bits = bits
        self.group_size = group_size
        self.buffers = AndroidBuffers(max_tokens, self.spec.heads, self.head_dim, self.spec.d_model)
        self.wq = QuantizedMatrix.quantize(attention.wq, bits, group_size)
        self.wk = QuantizedMatrix.quantize(attention.wk, bits, group_size)
        self.wv = QuantizedMatrix.quantize(attention.wv, bits, group_size)
        self.wo = QuantizedMatrix.quantize(attention.wo, bits, group_size)
        self.weights = (self.wq, self.wk, self.wv, self.wo)

    @property
    def weight_memory_bytes(self) -> int:
        return sum(weight.storage_bytes for weight in self.weights)

    @property
    def float_weight_memory_bytes(self) -> int:
        return sum(weight.raw_weight_bytes for weight in self.weights)

    def reset(self) -> None:
        self.buffers.reset()

    def decode_one(self, token: np.ndarray) -> np.ndarray:
        token = np.asarray(token, dtype=np.float32).reshape(-1)
        if token.size != self.spec.d_model:
            raise ValueError("token dimension mismatch")
        query = self.wq.matvec(token).reshape(self.spec.heads, self.head_dim)
        key = self.wk.matvec(token).reshape(self.spec.heads, self.head_dim)
        value = self.wv.matvec(token).reshape(self.spec.heads, self.head_dim)
        self.buffers.append(key, value)
        length = self.buffers.length
        scores = np.einsum("hd,thd->ht", query, self.buffers.keys[:length]) * self.scale
        causal_scores = scores[:, :length]
        causal_scores -= causal_scores.max(axis=1, keepdims=True)
        probabilities = np.exp(causal_scores)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        attended = np.einsum("ht,thd->hd", probabilities, self.buffers.values[:length]).reshape(-1)
        return self.wo.matvec(attended)


class QuantizedFeedForward:
    def __init__(self, feed_forward, bits: int = 4, group_size: int = 16):
        self.w1 = QuantizedMatrix.quantize(feed_forward.w1, bits, group_size)
        self.w2 = QuantizedMatrix.quantize(feed_forward.w2, bits, group_size)
        self.b1 = np.asarray(feed_forward.b1, dtype=np.float32)
        self.b2 = np.asarray(feed_forward.b2, dtype=np.float32)

    @property
    def weight_memory_bytes(self) -> int:
        return self.w1.storage_bytes + self.w2.storage_bytes

    @property
    def float_weight_memory_bytes(self) -> int:
        return self.w1.raw_weight_bytes + self.w2.raw_weight_bytes

    def forward(self, x: np.ndarray) -> np.ndarray:
        from hyperc_transformer import gelu

        return self.w2.matvec(gelu(self.w1.matvec(x) + self.b1)) + self.b2
