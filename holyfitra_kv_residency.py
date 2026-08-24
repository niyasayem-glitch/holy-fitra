"""Deterministic, fail-closed contracts for future mobile KV-cache residency.

This module does not execute transformer attention or make device-performance
claims. It governs the metadata, bounded residency, and precision decisions a
future streamed runtime must honor before allocating KV state.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any


MAX_KV_ENTRIES = 4_096
MAX_KV_BYTES = 512 * 1024 * 1024
MAX_KV_DIMENSION = 1_048_576
MAX_KV_AGE_STEPS = 1_000_000_000


class KVResidencyError(ValueError):
    """A KV residency policy, block, or decision is outside the safe contract."""


class KVPrecision(str, Enum):
    FP16 = "fp16"
    INT8 = "int8"
    INT4 = "int4"
    INT2 = "int2"

    @property
    def bits(self) -> int:
        return {KVPrecision.FP16: 16, KVPrecision.INT8: 8, KVPrecision.INT4: 4, KVPrecision.INT2: 2}[self]


@dataclass(frozen=True)
class KVBlock:
    key: str
    digest: str
    layer: int
    tokens: int
    head_dim: int
    precision: KVPrecision
    protected: bool = False

    def verify(self) -> None:
        if not isinstance(self.key, str) or not 1 <= len(self.key) <= 128 or not self.key.isascii() or any(char.isspace() for char in self.key):
            raise KVResidencyError("KV block key is invalid")
        if not _is_digest(self.digest):
            raise KVResidencyError("KV block digest is invalid")
        if not _positive_int(self.layer) or not _positive_int(self.tokens) or not _positive_int(self.head_dim):
            raise KVResidencyError("KV block dimensions are invalid")
        if self.layer > MAX_KV_DIMENSION or self.tokens > MAX_KV_DIMENSION or self.head_dim > MAX_KV_DIMENSION:
            raise KVResidencyError("KV block dimensions exceed the configured bound")
        if not isinstance(self.precision, KVPrecision) or not isinstance(self.protected, bool):
            raise KVResidencyError("KV block precision or protection is invalid")
        if self.logical_bytes > MAX_KV_BYTES:
            raise KVResidencyError("KV block exceeds the configured byte budget")

    @property
    def logical_elements(self) -> int:
        return _checked_multiply(_checked_multiply(self.tokens, self.head_dim), 2)

    @property
    def logical_bytes(self) -> int:
        bits = _checked_multiply(self.logical_elements, self.precision.bits)
        return (bits + 7) // 8

    def body(self) -> dict[str, Any]:
        self.verify()
        return {
            "key": self.key,
            "digest": self.digest,
            "layer": self.layer,
            "tokens": self.tokens,
            "head_dim": self.head_dim,
            "precision": self.precision.value,
            "protected": self.protected,
            "logical_bytes": self.logical_bytes,
        }

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "KVBlock":
        if not isinstance(body, dict):
            raise KVResidencyError("KV block body is invalid")
        try:
            block = cls(
                key=body["key"],
                digest=body["digest"],
                layer=body["layer"],
                tokens=body["tokens"],
                head_dim=body["head_dim"],
                precision=KVPrecision(body["precision"]),
                protected=body.get("protected", False),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise KVResidencyError("KV block body fields are invalid") from error
        block.verify()
        if body.get("logical_bytes") != block.logical_bytes:
            raise KVResidencyError("KV block logical byte count is invalid")
        return block


@dataclass(frozen=True)
class KVResidencyPolicy:
    max_bytes: int
    max_entries: int
    max_age_steps: int
    allowed_precisions: tuple[KVPrecision, ...]
    min_quality_score: float
    max_normalized_error: float

    def verify(self) -> None:
        if not _positive_int(self.max_bytes) or self.max_bytes > MAX_KV_BYTES:
            raise KVResidencyError("KV policy byte budget is invalid")
        if not _positive_int(self.max_entries) or self.max_entries > MAX_KV_ENTRIES:
            raise KVResidencyError("KV policy entry budget is invalid")
        if not _positive_int(self.max_age_steps) or self.max_age_steps > MAX_KV_AGE_STEPS:
            raise KVResidencyError("KV policy age bound is invalid")
        if not isinstance(self.allowed_precisions, tuple) or not self.allowed_precisions or len(self.allowed_precisions) != len(set(self.allowed_precisions)):
            raise KVResidencyError("KV policy precision ladder is invalid")
        if any(not isinstance(precision, KVPrecision) for precision in self.allowed_precisions) or KVPrecision.FP16 not in self.allowed_precisions:
            raise KVResidencyError("KV policy must include a conservative FP16 fallback")
        if not _finite_unit_interval(self.min_quality_score) or not _finite_nonnegative(self.max_normalized_error):
            raise KVResidencyError("KV policy quality thresholds are invalid")

    def body(self) -> dict[str, Any]:
        self.verify()
        return {
            "schema": "holyfitra.kv-residency-policy/v1",
            "max_bytes": self.max_bytes,
            "max_entries": self.max_entries,
            "max_age_steps": self.max_age_steps,
            "allowed_precisions": [precision.value for precision in self.allowed_precisions],
            "min_quality_score": self.min_quality_score,
            "max_normalized_error": self.max_normalized_error,
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def policy_id(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "KVResidencyPolicy":
        if not isinstance(body, dict) or body.get("schema") != "holyfitra.kv-residency-policy/v1":
            raise KVResidencyError("KV policy schema is invalid")
        try:
            policy = cls(
                max_bytes=body["max_bytes"],
                max_entries=body["max_entries"],
                max_age_steps=body["max_age_steps"],
                allowed_precisions=tuple(KVPrecision(value) for value in body["allowed_precisions"]),
                min_quality_score=body["min_quality_score"],
                max_normalized_error=body["max_normalized_error"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise KVResidencyError("KV policy fields are invalid") from error
        policy.verify()
        if policy.body() != body:
            raise KVResidencyError("KV policy body has unsupported fields or non-canonical values")
        return policy


@dataclass(frozen=True)
class KVPrecisionDecision:
    requested: KVPrecision
    selected: KVPrecision | None
    action: str
    reason: str
    policy_id: str

    def body(self) -> dict[str, Any]:
        return {
            "schema": "holyfitra.kv-precision-decision/v1",
            "requested": self.requested.value,
            "selected": self.selected.value if self.selected is not None else None,
            "action": self.action,
            "reason": self.reason,
            "policy_id": self.policy_id,
        }


class KVPrecisionGovernor:
    """Static, auditable precision selection with a conservative fallback."""

    def __init__(self, policy: KVResidencyPolicy):
        policy.verify()
        self.policy = policy

    def decide(self, requested: KVPrecision, *, quality_score: float | None, normalized_error: float | None) -> KVPrecisionDecision:
        if not isinstance(requested, KVPrecision):
            raise KVResidencyError("requested KV precision is invalid")
        if requested not in self.policy.allowed_precisions:
            return KVPrecisionDecision(requested, None, "reject", "precision_not_allowed", self.policy.policy_id)
        if requested == KVPrecision.FP16:
            return KVPrecisionDecision(requested, KVPrecision.FP16, "accept", "conservative_precision", self.policy.policy_id)
        if quality_score is None or normalized_error is None:
            return KVPrecisionDecision(requested, KVPrecision.FP16, "fallback", "missing_quality_evidence", self.policy.policy_id)
        if not _finite_unit_interval(quality_score) or not _finite_nonnegative(normalized_error):
            return KVPrecisionDecision(requested, None, "reject", "invalid_quality_evidence", self.policy.policy_id)
        if quality_score < self.policy.min_quality_score:
            return KVPrecisionDecision(requested, KVPrecision.FP16, "fallback", "quality_below_threshold", self.policy.policy_id)
        if normalized_error > self.policy.max_normalized_error:
            return KVPrecisionDecision(requested, KVPrecision.FP16, "fallback", "error_above_threshold", self.policy.policy_id)
        return KVPrecisionDecision(requested, requested, "accept", "quality_gate_passed", self.policy.policy_id)


@dataclass(frozen=True)
class KVResidencyDecision:
    action: str
    reason: str
    key: str
    evicted: tuple[str, ...]
    resident_bytes: int
    resident_entries: int
    policy_id: str

    def body(self) -> dict[str, Any]:
        return {
            "schema": "holyfitra.kv-residency-decision/v1",
            "action": self.action,
            "reason": self.reason,
            "key": self.key,
            "evicted": list(self.evicted),
            "resident_bytes": self.resident_bytes,
            "resident_entries": self.resident_entries,
            "policy_id": self.policy_id,
        }


@dataclass(frozen=True)
class _ResidentEntry:
    block: KVBlock
    last_access_step: int


class KVResidencyLedger:
    """Bounded LRU-style ledger with explicit protection and expiry semantics."""

    def __init__(self, policy: KVResidencyPolicy):
        policy.verify()
        self.policy = policy
        self._entries: OrderedDict[str, _ResidentEntry] = OrderedDict()
        self._resident_bytes = 0

    @property
    def resident_bytes(self) -> int:
        return self._resident_bytes

    @property
    def resident_entries(self) -> int:
        return len(self._entries)

    def admit(self, block: KVBlock, *, step: int) -> KVResidencyDecision:
        block.verify()
        _verify_step(step)
        expired = self._evict_expired(step)
        existing = self._entries.get(block.key)
        if existing is not None:
            if existing.block != block:
                return self._decision("reject", "duplicate_key_conflict", block.key, expired)
            self._entries[block.key] = _ResidentEntry(block, step)
            self._entries.move_to_end(block.key)
            return self._decision("touch", "already_resident", block.key, expired)
        if block.precision not in self.policy.allowed_precisions:
            return self._decision("reject", "precision_not_allowed", block.key, expired)
        if block.logical_bytes > self.policy.max_bytes:
            return self._decision("reject", "block_exceeds_budget", block.key, expired)
        evicted = list(expired)
        while self._resident_bytes + block.logical_bytes > self.policy.max_bytes or len(self._entries) + 1 > self.policy.max_entries:
            candidate = self._oldest_evictable()
            if candidate is None:
                return self._decision("reject", "protected_entries_block_admission", block.key, tuple(evicted))
            evicted.append(candidate)
            self._remove(candidate)
        self._entries[block.key] = _ResidentEntry(block, step)
        self._resident_bytes += block.logical_bytes
        return self._decision("admit", "within_budget", block.key, tuple(evicted))

    def access(self, key: str, *, step: int) -> KVResidencyDecision:
        _verify_step(step)
        expired = self._evict_expired(step)
        entry = self._entries.get(key)
        if entry is None:
            return self._decision("reject", "not_resident", key, expired)
        self._entries[key] = _ResidentEntry(entry.block, step)
        self._entries.move_to_end(key)
        return self._decision("touch", "resident", key, expired)

    def receipt(self) -> dict[str, Any]:
        entries = [
            {"block": entry.block.body(), "last_access_step": entry.last_access_step}
            for entry in self._entries.values()
        ]
        body = {
            "schema": "holyfitra.kv-residency-receipt/v1",
            "policy_id": self.policy.policy_id,
            "resident_bytes": self._resident_bytes,
            "resident_entries": len(entries),
            "entries": entries,
        }
        body["receipt_id"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
        return body

    def _evict_expired(self, step: int) -> tuple[str, ...]:
        evicted: list[str] = []
        for key, entry in tuple(self._entries.items()):
            if not entry.block.protected and step - entry.last_access_step > self.policy.max_age_steps:
                evicted.append(key)
                self._remove(key)
        return tuple(evicted)

    def _oldest_evictable(self) -> str | None:
        for key, entry in self._entries.items():
            if not entry.block.protected:
                return key
        return None

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key)
        self._resident_bytes -= entry.block.logical_bytes

    def _decision(self, action: str, reason: str, key: str, evicted: tuple[str, ...] | list[str]) -> KVResidencyDecision:
        return KVResidencyDecision(action, reason, key, tuple(evicted), self._resident_bytes, len(self._entries), self.policy.policy_id)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_unit_interval(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0


def _finite_nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0.0


def _checked_multiply(left: int, right: int) -> int:
    value = left * right
    if value > MAX_KV_BYTES * 8:
        raise KVResidencyError("KV logical byte calculation exceeds the configured bound")
    return value


def _verify_step(step: int) -> None:
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= MAX_KV_AGE_STEPS:
        raise KVResidencyError("KV ledger step is invalid")
