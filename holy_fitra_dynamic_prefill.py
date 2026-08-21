#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


class PrefillError(RuntimeError):
    pass


@dataclass
class SequenceRequest:
    request_id: str
    tokens: np.ndarray  # [length, d_model], already embedded or projected
    deadline_ns: int = 0
    priority: int = 1
    cancelled: bool = False

    @property
    def length(self) -> int:
        if self.tokens.ndim != 2 or self.tokens.shape[0] <= 0:
            raise PrefillError(f"request {self.request_id} has invalid token shape")
        return int(self.tokens.shape[0])


@dataclass(frozen=True)
class KVLease:
    request_id: str
    start: int
    length: int
    generation: int


class KVPagePool:
    def __init__(self, capacity_tokens: int):
        if capacity_tokens <= 0:
            raise ValueError("capacity_tokens must be positive")
        self.capacity = capacity_tokens
        self._used = 0
        self._generation = 0
        self._leases: dict[str, KVLease] = {}

    def reserve(self, request_id: str, length: int) -> KVLease:
        if request_id in self._leases:
            raise PrefillError("request already owns a KV lease")
        if length <= 0 or self._used + length > self.capacity:
            raise PrefillError("KV page pool exhausted")
        lease = KVLease(request_id, self._used, length, self._generation)
        self._leases[request_id] = lease
        self._used += length
        return lease

    def release(self, request_id: str) -> None:
        if request_id not in self._leases:
            raise PrefillError("unknown KV lease")
        del self._leases[request_id]
        if not self._leases:
            self._used = 0
            self._generation += 1

    def lease(self, request_id: str) -> KVLease:
        if request_id not in self._leases:
            raise PrefillError("unknown KV lease")
        return self._leases[request_id]


@dataclass
class PackedMicroBatch:
    requests: list[SequenceRequest]
    tokens: np.ndarray
    offsets: np.ndarray
    lengths: np.ndarray
    padded_length: int
    bucket_id: int
    deadline_ns: int
    digest: str
    kv_leases: tuple[KVLease, ...] = ()

    @property
    def batch_size(self) -> int:
        return len(self.requests)

    @property
    def token_count(self) -> int:
        return int(self.tokens.shape[0])


@dataclass(frozen=True)
class PrefillCostProfile:
    scalar_launch_cost: float = 2048.0
    fused_launch_cost: float = 4096.0
    max_padding_ratio: float = 1.25
    min_fused_sequences: int = 4


class AdaptivePrefillPolicy:
    def __init__(self, profile: PrefillCostProfile | None = None):
        self.profile = profile or PrefillCostProfile()

    def choose(self, batch: PackedMicroBatch) -> str:
        if batch.batch_size < self.profile.min_fused_sequences:
            return "scalar"
        padding_ratio = (batch.batch_size * batch.padded_length) / max(1, batch.token_count)
        if padding_ratio > self.profile.max_padding_ratio:
            return "scalar"
        scalar_work = sum(int(length) * int(length) for length in batch.lengths) + self.profile.scalar_launch_cost * batch.batch_size
        fused_work = batch.batch_size * batch.padded_length * batch.padded_length + self.profile.fused_launch_cost
        return "fused" if fused_work < scalar_work else "scalar"


class DynamicPrefillPacker:
    def __init__(self, *, bucket_width: int = 8, max_tokens: int = 2048, max_sequences: int = 32):
        if bucket_width <= 0 or max_tokens <= 0 or max_sequences <= 0:
            raise ValueError("bucket_width, max_tokens, and max_sequences must be positive")
        self.bucket_width = bucket_width
        self.max_tokens = max_tokens
        self.max_sequences = max_sequences

    def bucket_for(self, length: int) -> int:
        return (length + self.bucket_width - 1) // self.bucket_width

    def _validate(self, request: SequenceRequest, now_ns: int) -> None:
        _ = request.length
        if request.tokens.dtype not in (np.float16, np.float32):
            raise PrefillError("tokens must be float16 or float32")
        if request.cancelled:
            raise PrefillError("request cancelled")
        if request.deadline_ns and request.deadline_ns < now_ns:
            raise PrefillError("request deadline expired")

    def pack(self, requests: Iterable[SequenceRequest], *, now_ns: int | None = None, kv_pool: KVPagePool | None = None) -> list[PackedMicroBatch]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        valid: list[SequenceRequest] = []
        for request in requests:
            self._validate(request, now)
            valid.append(request)
        valid.sort(key=lambda request: (self.bucket_for(request.length), -request.priority, request.deadline_ns or (1 << 63)))
        batches: list[PackedMicroBatch] = []
        current: list[SequenceRequest] = []
        current_bucket: int | None = None
        current_tokens = 0

        def flush() -> None:
            nonlocal current, current_bucket, current_tokens
            if not current:
                return
            lengths = np.asarray([request.length for request in current], dtype=np.int32)
            offsets = np.zeros(len(current) + 1, dtype=np.int32)
            offsets[1:] = np.cumsum(lengths, dtype=np.int32)
            tokens = np.concatenate([request.tokens.astype(np.float32, copy=False) for request in current], axis=0)
            padded_length = max(lengths.tolist())
            deadline_values = [request.deadline_ns for request in current if request.deadline_ns]
            deadline = min(deadline_values) if deadline_values else 0
            digest_input = b"".join(request.request_id.encode() + request.tokens.tobytes() for request in current)
            digest = hashlib.sha256(digest_input).hexdigest()
            leases: list[KVLease] = []
            if kv_pool is not None:
                for request in current:
                    leases.append(kv_pool.reserve(request.request_id, request.length))
            batches.append(PackedMicroBatch(list(current), tokens, offsets, lengths, padded_length, int(current_bucket), deadline, digest, tuple(leases)))
            current = []
            current_bucket = None
            current_tokens = 0

        for request in valid:
            bucket = self.bucket_for(request.length)
            if current and (bucket != current_bucket or len(current) >= self.max_sequences or current_tokens + request.length > self.max_tokens):
                flush()
            current.append(request)
            current_bucket = bucket
            current_tokens += request.length
        flush()
        return batches


class ToyCausalPrefill:
    """Reference causal attention with a padded batched implementation."""

    def __init__(self, d_model: int, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.d_model = d_model
        scale = 1.0 / math.sqrt(d_model)
        self.wq = (rng.standard_normal((d_model, d_model)) * scale).astype(np.float32)
        self.wk = (rng.standard_normal((d_model, d_model)) * scale).astype(np.float32)
        self.wv = (rng.standard_normal((d_model, d_model)) * scale).astype(np.float32)
        self.wo = (rng.standard_normal((d_model, d_model)) * scale).astype(np.float32)

    def single(self, tokens: np.ndarray) -> np.ndarray:
        q = tokens @ self.wq
        k = tokens @ self.wk
        v = tokens @ self.wv
        scores = (q @ k.T) / math.sqrt(self.d_model)
        mask = np.triu(np.ones(scores.shape, dtype=bool), k=1)
        scores = np.where(mask, -np.inf, scores)
        scores -= np.max(scores, axis=-1, keepdims=True)
        weights = np.exp(scores)
        weights /= np.sum(weights, axis=-1, keepdims=True)
        return (weights @ v) @ self.wo

    def packed_bucket(self, batch: PackedMicroBatch) -> dict[str, np.ndarray]:
        bsz = batch.batch_size
        length = batch.padded_length
        padded = np.zeros((bsz, length, self.d_model), dtype=np.float32)
        valid = np.zeros((bsz, length), dtype=bool)
        for row, request in enumerate(batch.requests):
            padded[row, : request.length] = request.tokens
            valid[row, : request.length] = True
        q = padded @ self.wq
        k = padded @ self.wk
        v = padded @ self.wv
        scores = np.einsum("bld,bmd->blm", q, k) / math.sqrt(self.d_model)
        causal = np.triu(np.ones((length, length), dtype=bool), k=1)
        invalid_keys = ~valid[:, None, :]
        scores = np.where(causal[None, :, :] | invalid_keys, -np.inf, scores)
        scores = np.where(valid[:, :, None], scores, -np.inf)
        finite_scores = np.where(np.isfinite(scores), scores, -1e30)
        scores = np.where(np.isfinite(scores), finite_scores - np.max(finite_scores, axis=-1, keepdims=True), -1e30)
        weights = np.exp(scores)
        weights = np.divide(weights, np.sum(weights, axis=-1, keepdims=True), out=np.zeros_like(weights), where=np.sum(weights, axis=-1, keepdims=True) > 0)
        output = (np.einsum("blm,bmd->bld", weights, v) @ self.wo)
        return {request.request_id: output[row, : request.length].copy() for row, request in enumerate(batch.requests)}


def demo() -> dict[str, object]:
    rng = np.random.default_rng(11)
    requests = [SequenceRequest(f"req-{i}", rng.standard_normal((length, 8)).astype(np.float32), priority=i % 3) for i, length in enumerate([3, 7, 9, 14, 15, 23])]
    pool = KVPagePool(128)
    packer = DynamicPrefillPacker(bucket_width=8, max_tokens=32, max_sequences=4)
    batches = packer.pack(requests, kv_pool=pool)
    model = ToyCausalPrefill(8)
    outputs: dict[str, np.ndarray] = {}
    for batch in batches:
        outputs.update(model.packed_bucket(batch))
    max_error = max(float(np.max(np.abs(outputs[request.request_id] - model.single(request.tokens)))) for request in requests)
    return {"batches": len(batches), "batch_sizes": [batch.batch_size for batch in batches], "padded_lengths": [batch.padded_length for batch in batches], "max_error": max_error, "kv_used": pool._used}


if __name__ == "__main__":
    print(demo())
