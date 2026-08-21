#!/usr/bin/env python3
"""Small, deterministic transformer reference implementation."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TransformerSpec:
    d_model: int
    heads: int
    d_ff: int
    causal: bool = True

    def __post_init__(self) -> None:
        if self.d_model <= 0 or self.heads <= 0 or self.d_ff <= 0 or self.d_model % self.heads:
            raise ValueError("d_model must be positive and divisible by heads")


@dataclass
class KVCache:
    keys: np.ndarray
    values: np.ndarray

    @classmethod
    def empty(cls, heads: int, head_dim: int) -> "KVCache":
        return cls(np.zeros((0, heads, head_dim), dtype=np.float32), np.zeros((0, heads, head_dim), dtype=np.float32))

    def append(self, key: np.ndarray, value: np.ndarray) -> "KVCache":
        key = np.asarray(key, dtype=np.float32).reshape(1, self.keys.shape[1], self.keys.shape[2])
        value = np.asarray(value, dtype=np.float32).reshape(1, self.values.shape[1], self.values.shape[2])
        return KVCache(np.concatenate((self.keys, key), axis=0), np.concatenate((self.values, value), axis=0))

    @property
    def length(self) -> int:
        return int(self.keys.shape[0])


def gelu(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return 0.5 * values * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (values + 0.044715 * values**3)))


def reference_identity_attention(inputs: np.ndarray) -> np.ndarray:
    """Reference self-attention with Q=K=V equal to the input tensor."""
    inputs = np.asarray(inputs, dtype=np.float32)
    if inputs.ndim != 3 or inputs.shape[0] != 1:
        raise ValueError("identity attention expects shape [1, tokens, d_model]")
    dimension = inputs.shape[-1]
    scores = np.matmul(inputs, np.swapaxes(inputs, -1, -2)) / np.float32(math.sqrt(dimension))
    scores -= scores.max(axis=-1, keepdims=True)
    probabilities = np.exp(scores)
    probabilities /= probabilities.sum(axis=-1, keepdims=True)
    return np.matmul(probabilities, inputs).astype(np.float32)


class MultiHeadSelfAttention:
    def __init__(self, spec: TransformerSpec, seed: int = 0):
        self.spec = spec
        self.head_dim = spec.d_model // spec.heads
        rng = np.random.default_rng(seed)
        scale = np.float32(1.0 / math.sqrt(spec.d_model))
        self.wq = rng.normal(0.0, scale, (spec.d_model, spec.d_model)).astype(np.float32)
        self.wk = rng.normal(0.0, scale, (spec.d_model, spec.d_model)).astype(np.float32)
        self.wv = rng.normal(0.0, scale, (spec.d_model, spec.d_model)).astype(np.float32)
        self.wo = rng.normal(0.0, scale, (spec.d_model, spec.d_model)).astype(np.float32)

    def _project(self, inputs: np.ndarray, weight: np.ndarray) -> np.ndarray:
        projected = np.asarray(inputs, dtype=np.float32) @ weight
        return projected.reshape(projected.shape[0], self.spec.heads, self.head_dim)

    def decode_one(self, inputs: np.ndarray, cache: KVCache) -> tuple[np.ndarray, KVCache]:
        inputs = np.asarray(inputs, dtype=np.float32).reshape(-1, self.spec.d_model)
        if inputs.shape[0] != 1:
            raise ValueError("decode_one accepts exactly one token")
        query = self._project(inputs, self.wq)[0]
        key = self._project(inputs, self.wk)[0]
        value = self._project(inputs, self.wv)[0]
        cache = cache.append(key, value)
        scores = np.einsum("hd,thd->ht", query, cache.keys) / np.float32(math.sqrt(self.head_dim))
        scores -= scores.max(axis=1, keepdims=True)
        probabilities = np.exp(scores)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        attended = np.einsum("ht,thd->hd", probabilities, cache.values).reshape(1, self.spec.d_model)
        return (attended @ self.wo).reshape(1, 1, self.spec.d_model), cache

    def __call__(self, inputs: np.ndarray) -> np.ndarray:
        inputs = np.asarray(inputs, dtype=np.float32).reshape(-1, self.spec.d_model)
        cache = KVCache.empty(self.spec.heads, self.head_dim)
        outputs = []
        for token in inputs:
            output, cache = self.decode_one(token.reshape(1, 1, self.spec.d_model), cache)
            outputs.append(output.reshape(self.spec.d_model))
        return np.stack(outputs).reshape(np.asarray(inputs).shape)


class FeedForward:
    def __init__(self, spec: TransformerSpec, seed: int = 1):
        self.spec = spec
        rng = np.random.default_rng(seed)
        scale = np.float32(1.0 / math.sqrt(spec.d_model))
        self.w1 = rng.normal(0.0, scale, (spec.d_model, spec.d_ff)).astype(np.float32)
        self.w2 = rng.normal(0.0, scale, (spec.d_ff, spec.d_model)).astype(np.float32)
        self.b1 = np.zeros(spec.d_ff, dtype=np.float32)
        self.b2 = np.zeros(spec.d_model, dtype=np.float32)

    def forward(self, inputs: np.ndarray) -> np.ndarray:
        inputs = np.asarray(inputs, dtype=np.float32)
        return gelu(inputs @ self.w1 + self.b1) @ self.w2 + self.b2

    __call__ = forward
