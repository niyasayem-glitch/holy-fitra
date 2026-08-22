#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import hashlib
import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np


class RaggedAttentionError(ValueError):
    pass


@dataclass(frozen=True)
class RaggedBatch:
    q: np.ndarray
    k: np.ndarray
    v: np.ndarray
    offsets: np.ndarray
    sequence_count: int
    d_model: int
    digest: str

    @property
    def total_tokens(self) -> int:
        return int(self.q.shape[0])

    def validate(self) -> None:
        if not isinstance(self.sequence_count, int) or isinstance(self.sequence_count, bool) or self.sequence_count <= 0 or not isinstance(self.d_model, int) or isinstance(self.d_model, bool) or self.d_model <= 0:
            raise RaggedAttentionError("sequence_count and d_model must be positive integers")
        if self.q.ndim != 2 or self.k.ndim != 2 or self.v.ndim != 2:
            raise RaggedAttentionError("q, k, and v must be rank-2 packed arrays")
        if self.q.shape != self.k.shape or self.q.shape != self.v.shape:
            raise RaggedAttentionError("q, k, and v shapes must match")
        if self.q.dtype != np.dtype(np.float32) or self.k.dtype != np.dtype(np.float32) or self.v.dtype != np.dtype(np.float32) or not np.all(np.isfinite(self.q)) or not np.all(np.isfinite(self.k)) or not np.all(np.isfinite(self.v)) or self.q.shape[1] != self.d_model or self.offsets.dtype.kind not in "iu":
            raise RaggedAttentionError("invalid dtype, finite state, dimension, or offsets dtype")
        if self.offsets.shape != (self.sequence_count + 1,) or int(self.offsets[0]) != 0 or int(self.offsets[-1]) != self.total_tokens:
            raise RaggedAttentionError("offsets must cover exactly the packed token range")
        if np.any(np.diff(self.offsets) <= 0):
            raise RaggedAttentionError("every ragged sequence must contain at least one token")
        if np.any(self.offsets < 0) or np.any(self.offsets > self.total_tokens):
            raise RaggedAttentionError("offset out of range")
        expected_digest = hashlib.sha256(self.q.tobytes() + self.k.tobytes() + self.v.tobytes() + self.offsets.tobytes()).hexdigest()
        if self.digest != expected_digest:
            raise RaggedAttentionError("ragged batch digest does not match payload")


def pack_sequences(sequences: Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> RaggedBatch:
    rows = list(sequences)
    if not rows:
        raise RaggedAttentionError("at least one sequence is required")
    if rows[0][0].ndim != 2:
        raise RaggedAttentionError("q must be rank-2")
    d_model = int(rows[0][0].shape[1])
    for q, k, v in rows:
        if q.ndim != 2 or k.shape != q.shape or v.shape != q.shape or q.shape[1] != d_model or q.shape[0] <= 0 or not np.all(np.isfinite(q)) or not np.all(np.isfinite(k)) or not np.all(np.isfinite(v)):
            raise RaggedAttentionError("all q/k/v sequence shapes must match and be non-empty")
    q = np.concatenate([row[0].astype(np.float32, copy=False) for row in rows], axis=0)
    k = np.concatenate([row[1].astype(np.float32, copy=False) for row in rows], axis=0)
    v = np.concatenate([row[2].astype(np.float32, copy=False) for row in rows], axis=0)
    lengths = np.asarray([row[0].shape[0] for row in rows], dtype=np.int64)
    offsets = np.zeros(len(rows) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(lengths, dtype=np.int64)
    digest = hashlib.sha256(q.tobytes() + k.tobytes() + v.tobytes() + offsets.tobytes()).hexdigest()
    batch = RaggedBatch(q, k, v, offsets, len(rows), d_model, digest)
    batch.validate()
    return batch


def ragged_attention_reference(batch: RaggedBatch) -> np.ndarray:
    batch.validate()
    output = np.empty_like(batch.q)
    scale = 1.0 / math.sqrt(batch.d_model)
    for sequence in range(batch.sequence_count):
        start = int(batch.offsets[sequence])
        end = int(batch.offsets[sequence + 1])
        q = batch.q[start:end]
        k = batch.k[start:end]
        v = batch.v[start:end]
        for row in range(end - start):
            scores = (q[row] @ k[: row + 1].T) * scale
            scores -= np.max(scores)
            weights = np.exp(scores)
            weights /= np.sum(weights)
            output[start + row] = weights @ v[: row + 1]
    return output


def padded_attention_reference(batch: RaggedBatch) -> np.ndarray:
    batch.validate()
    output = np.empty_like(batch.q)
    scale = 1.0 / math.sqrt(batch.d_model)
    for sequence in range(batch.sequence_count):
        start = int(batch.offsets[sequence])
        end = int(batch.offsets[sequence + 1])
        length = end - start
        scores = (batch.q[start:end] @ batch.k[start:end].T) * scale
        mask = np.triu(np.ones((length, length), dtype=bool), k=1)
        scores = np.where(mask, -np.inf, scores)
        scores -= np.max(scores, axis=-1, keepdims=True)
        weights = np.exp(scores)
        weights /= np.sum(weights, axis=-1, keepdims=True)
        output[start:end] = weights @ batch.v[start:end]
    return output


def ragged_work(batch: RaggedBatch) -> int:
    batch.validate()
    lengths = [int(value) for value in np.diff(batch.offsets.astype(np.int64))]
    return sum(length * length * int(batch.d_model) for length in lengths)


class RaggedKernelDispatch:
    """Dispatch policy for scalar, NEON, and SVE kernel symbols."""

    def __init__(self, *, has_neon: bool = False, has_sve: bool = False):
        if not isinstance(has_neon, bool) or not isinstance(has_sve, bool):
            raise ValueError("dispatch feature flags must be boolean")
        self.has_neon = has_neon
        self.has_sve = has_sve

    def kernel_name(self, d_model: int) -> str:
        if self.has_sve and d_model % 4 == 0:
            return "holy_fitra_ragged_attention_sve"
        if self.has_neon and d_model % 4 == 0:
            return "holy_fitra_ragged_attention_neon"
        return "holy_fitra_ragged_attention_scalar"


def demo() -> dict[str, object]:
    rng = np.random.default_rng(33)
    rows = []
    for length in [1, 3, 7, 8, 13]:
        rows.append(tuple((rng.standard_normal((length, 8)).astype(np.float32) for _ in range(3))))
    batch = pack_sequences(rows)
    ragged = ragged_attention_reference(batch)
    padded = padded_attention_reference(batch)
    return {
        "sequence_count": batch.sequence_count,
        "total_tokens": batch.total_tokens,
        "offsets": batch.offsets.tolist(),
        "ragged_work": ragged_work(batch),
        "max_error": float(np.max(np.abs(ragged - padded))),
        "kernel_scalar": RaggedKernelDispatch().kernel_name(batch.d_model),
        "digest": batch.digest[:16],
    }


if __name__ == "__main__":
    print(demo())
