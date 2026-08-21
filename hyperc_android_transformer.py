#!/usr/bin/env python3
"""Preallocated host reference for the Android transformer buffer ABI."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class AndroidBuffers:
    max_tokens: int
    heads: int
    head_dim: int
    d_model: int

    def __post_init__(self) -> None:
        if min(self.max_tokens, self.heads, self.head_dim, self.d_model) <= 0:
            raise ValueError("Android buffer dimensions must be positive")
        self.keys = np.zeros((self.max_tokens, self.heads, self.head_dim), dtype=np.float32)
        self.values = np.zeros_like(self.keys)
        self.output = np.zeros((self.d_model,), dtype=np.float32)
        self.length = 0

    @property
    def memory_bytes(self) -> int:
        return int(self.keys.nbytes + self.values.nbytes + self.output.nbytes)

    def reset(self) -> None:
        self.length = 0

    def append(self, keys: np.ndarray, values: np.ndarray) -> None:
        if self.length >= self.max_tokens:
            raise ValueError("Android KV buffer capacity exceeded")
        key = np.asarray(keys, dtype=np.float32).reshape(self.heads, self.head_dim)
        value = np.asarray(values, dtype=np.float32).reshape(self.heads, self.head_dim)
        self.keys[self.length] = key
        self.values[self.length] = value
        self.length += 1
