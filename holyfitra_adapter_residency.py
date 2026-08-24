"""Fail-closed residency contracts for compact adapter payloads.

The module manages authenticated adapter metadata and residency decisions. It
does not apply adapters to a model, execute JNI code, or make device claims.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any


MAX_ADAPTER_BYTES = 64 * 1024 * 1024
MAX_ADAPTERS = 1_024
MAX_ADAPTER_DIMENSION = 1_048_576
MAX_ADAPTER_AGE_STEPS = 1_000_000_000


class AdapterResidencyError(ValueError):
    """An adapter identity, policy, catalog, or residency action is invalid."""


class AdapterMode(str, Enum):
    LOW_RANK = "low_rank"
    BIAS = "bias"
    PROMPT = "prompt"


@dataclass(frozen=True)
class AdapterArtifact:
    adapter_id: str
    base_deployment_digest: str
    payload_digest: str
    payload_bytes: int
    input_dim: int
    output_dim: int
    rank: int
    alpha: float
    mode: AdapterMode
    protected: bool = False

    def verify(self) -> None:
        if not _valid_id(self.adapter_id):
            raise AdapterResidencyError("adapter ID is invalid")
        if not _is_digest(self.base_deployment_digest) or not _is_digest(self.payload_digest):
            raise AdapterResidencyError("adapter digest is invalid")
        if not _positive_int(self.payload_bytes) or self.payload_bytes > MAX_ADAPTER_BYTES:
            raise AdapterResidencyError("adapter payload byte count is invalid")
        if not _positive_int(self.input_dim) or not _positive_int(self.output_dim) or not _positive_int(self.rank):
            raise AdapterResidencyError("adapter dimensions are invalid")
        if max(self.input_dim, self.output_dim, self.rank) > MAX_ADAPTER_DIMENSION or self.rank > min(self.input_dim, self.output_dim):
            raise AdapterResidencyError("adapter dimensions exceed the configured bound")
        if not isinstance(self.mode, AdapterMode) or not isinstance(self.protected, bool):
            raise AdapterResidencyError("adapter mode or protection is invalid")
        if not _finite_positive(self.alpha):
            raise AdapterResidencyError("adapter alpha is invalid")

    def verify_payload(self, payload: bytes) -> None:
        self.verify()
        if not isinstance(payload, bytes) or len(payload) != self.payload_bytes:
            raise AdapterResidencyError("adapter payload byte count does not match catalog")
        if hashlib.sha256(payload).hexdigest() != self.payload_digest:
            raise AdapterResidencyError("adapter payload digest does not match catalog")

    def body(self) -> dict[str, Any]:
        self.verify()
        return {
            "adapter_id": self.adapter_id,
            "base_deployment_digest": self.base_deployment_digest,
            "payload_digest": self.payload_digest,
            "payload_bytes": self.payload_bytes,
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
            "rank": self.rank,
            "alpha": self.alpha,
            "mode": self.mode.value,
            "protected": self.protected,
        }

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "AdapterArtifact":
        if not isinstance(body, dict):
            raise AdapterResidencyError("adapter artifact body is invalid")
        try:
            artifact = cls(
                adapter_id=body["adapter_id"],
                base_deployment_digest=body["base_deployment_digest"],
                payload_digest=body["payload_digest"],
                payload_bytes=body["payload_bytes"],
                input_dim=body["input_dim"],
                output_dim=body["output_dim"],
                rank=body["rank"],
                alpha=body["alpha"],
                mode=AdapterMode(body["mode"]),
                protected=body.get("protected", False),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterResidencyError("adapter artifact fields are invalid") from error
        artifact.verify()
        if artifact.body() != body:
            raise AdapterResidencyError("adapter artifact body has unsupported fields or non-canonical values")
        return artifact


@dataclass(frozen=True)
class AdapterResidencyPolicy:
    base_deployment_digest: str
    max_resident_bytes: int
    max_adapters: int
    max_active_lanes: int
    max_age_steps: int
    allowed_modes: tuple[AdapterMode, ...]

    def verify(self) -> None:
        if not _is_digest(self.base_deployment_digest):
            raise AdapterResidencyError("adapter policy base deployment digest is invalid")
        if not _positive_int(self.max_resident_bytes) or self.max_resident_bytes > MAX_ADAPTER_BYTES:
            raise AdapterResidencyError("adapter policy resident byte budget is invalid")
        if not _positive_int(self.max_adapters) or self.max_adapters > MAX_ADAPTERS:
            raise AdapterResidencyError("adapter policy adapter limit is invalid")
        if not _positive_int(self.max_active_lanes) or self.max_active_lanes > self.max_adapters:
            raise AdapterResidencyError("adapter policy active lane limit is invalid")
        if not _positive_int(self.max_age_steps) or self.max_age_steps > MAX_ADAPTER_AGE_STEPS:
            raise AdapterResidencyError("adapter policy age bound is invalid")
        if not isinstance(self.allowed_modes, tuple) or not self.allowed_modes or len(self.allowed_modes) != len(set(self.allowed_modes)):
            raise AdapterResidencyError("adapter policy mode set is invalid")
        if any(not isinstance(mode, AdapterMode) for mode in self.allowed_modes):
            raise AdapterResidencyError("adapter policy mode is invalid")

    def body(self) -> dict[str, Any]:
        self.verify()
        return {
            "schema": "holyfitra.adapter-residency-policy/v1",
            "base_deployment_digest": self.base_deployment_digest,
            "max_resident_bytes": self.max_resident_bytes,
            "max_adapters": self.max_adapters,
            "max_active_lanes": self.max_active_lanes,
            "max_age_steps": self.max_age_steps,
            "allowed_modes": [mode.value for mode in self.allowed_modes],
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def policy_id(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "AdapterResidencyPolicy":
        if not isinstance(body, dict) or body.get("schema") != "holyfitra.adapter-residency-policy/v1":
            raise AdapterResidencyError("adapter policy schema is invalid")
        try:
            policy = cls(
                base_deployment_digest=body["base_deployment_digest"],
                max_resident_bytes=body["max_resident_bytes"],
                max_adapters=body["max_adapters"],
                max_active_lanes=body["max_active_lanes"],
                max_age_steps=body["max_age_steps"],
                allowed_modes=tuple(AdapterMode(value) for value in body["allowed_modes"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterResidencyError("adapter policy fields are invalid") from error
        policy.verify()
        if policy.body() != body:
            raise AdapterResidencyError("adapter policy body has unsupported fields or non-canonical values")
        return policy


@dataclass(frozen=True)
class AdapterCatalog:
    policy_id: str
    base_deployment_digest: str
    adapters: tuple[AdapterArtifact, ...]

    def verify(self) -> None:
        if not _is_digest(self.policy_id) or not _is_digest(self.base_deployment_digest):
            raise AdapterResidencyError("adapter catalog identity is invalid")
        if not isinstance(self.adapters, tuple) or len(self.adapters) > MAX_ADAPTERS:
            raise AdapterResidencyError("adapter catalog is invalid")
        adapter_ids = tuple(artifact.adapter_id for artifact in self.adapters)
        if adapter_ids != tuple(sorted(adapter_ids)) or len(adapter_ids) != len(set(adapter_ids)):
            raise AdapterResidencyError("adapter catalog ordering is invalid")
        for artifact in self.adapters:
            if not isinstance(artifact, AdapterArtifact):
                raise AdapterResidencyError("adapter catalog artifact is invalid")
            artifact.verify()
            if artifact.base_deployment_digest != self.base_deployment_digest:
                raise AdapterResidencyError("adapter catalog artifact targets a different base deployment")

    def body(self) -> dict[str, Any]:
        self.verify()
        return {
            "schema": "holyfitra.adapter-catalog/v1",
            "policy_id": self.policy_id,
            "base_deployment_digest": self.base_deployment_digest,
            "adapters": [artifact.body() for artifact in self.adapters],
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "AdapterCatalog":
        if not isinstance(body, dict) or body.get("schema") != "holyfitra.adapter-catalog/v1":
            raise AdapterResidencyError("adapter catalog schema is invalid")
        try:
            catalog = cls(
                policy_id=body["policy_id"],
                base_deployment_digest=body["base_deployment_digest"],
                adapters=tuple(AdapterArtifact.from_body(item) for item in body["adapters"]),
            )
        except (KeyError, TypeError, ValueError, AdapterResidencyError) as error:
            raise AdapterResidencyError("adapter catalog fields are invalid") from error
        catalog.verify()
        if catalog.body() != body:
            raise AdapterResidencyError("adapter catalog body has unsupported fields or non-canonical values")
        return catalog


@dataclass(frozen=True)
class AdapterActivationSnapshot:
    policy_id: str
    active_lanes: tuple[str, ...]

    def verify(self) -> None:
        if not _is_digest(self.policy_id) or not isinstance(self.active_lanes, tuple) or len(self.active_lanes) > MAX_ADAPTERS:
            raise AdapterResidencyError("adapter activation snapshot is invalid")
        if any(not _valid_id(adapter_id) for adapter_id in self.active_lanes) or len(self.active_lanes) != len(set(self.active_lanes)):
            raise AdapterResidencyError("adapter activation snapshot lanes are invalid")


@dataclass(frozen=True)
class AdapterResidencyDecision:
    action: str
    reason: str
    adapter_id: str
    evicted: tuple[str, ...]
    active_lanes: tuple[str, ...]
    resident_bytes: int
    resident_adapters: int
    policy_id: str

    def body(self) -> dict[str, Any]:
        return {
            "schema": "holyfitra.adapter-residency-decision/v1",
            "action": self.action,
            "reason": self.reason,
            "adapter_id": self.adapter_id,
            "evicted": list(self.evicted),
            "active_lanes": list(self.active_lanes),
            "resident_bytes": self.resident_bytes,
            "resident_adapters": self.resident_adapters,
            "policy_id": self.policy_id,
        }


@dataclass(frozen=True)
class _ResidentAdapter:
    artifact: AdapterArtifact
    last_access_step: int


class AdapterResidencyLedger:
    """A bounded LRU ledger that preserves active/protected adapter lanes."""

    def __init__(self, policy: AdapterResidencyPolicy):
        policy.verify()
        self.policy = policy
        self._entries: OrderedDict[str, _ResidentAdapter] = OrderedDict()
        self._active_lanes: tuple[str, ...] = ()
        self._resident_bytes = 0

    @property
    def resident_bytes(self) -> int:
        return self._resident_bytes

    @property
    def resident_adapters(self) -> int:
        return len(self._entries)

    @property
    def active_lanes(self) -> tuple[str, ...]:
        return self._active_lanes

    def admit(self, artifact: AdapterArtifact, *, step: int) -> AdapterResidencyDecision:
        artifact.verify()
        _verify_step(step)
        expired = self._evict_expired(step)
        if artifact.base_deployment_digest != self.policy.base_deployment_digest:
            return self._decision("reject", "base_deployment_mismatch", artifact.adapter_id, expired)
        if artifact.mode not in self.policy.allowed_modes:
            return self._decision("reject", "mode_not_allowed", artifact.adapter_id, expired)
        existing = self._entries.get(artifact.adapter_id)
        if existing is not None:
            if existing.artifact != artifact:
                return self._decision("reject", "duplicate_adapter_conflict", artifact.adapter_id, expired)
            self._touch(artifact.adapter_id, step)
            return self._decision("touch", "already_resident", artifact.adapter_id, expired)
        if artifact.payload_bytes > self.policy.max_resident_bytes:
            return self._decision("reject", "adapter_exceeds_budget", artifact.adapter_id, expired)
        evicted = list(expired)
        while self._resident_bytes + artifact.payload_bytes > self.policy.max_resident_bytes or len(self._entries) + 1 > self.policy.max_adapters:
            candidate = self._oldest_evictable()
            if candidate is None:
                return self._decision("reject", "protected_or_active_adapters_block_admission", artifact.adapter_id, tuple(evicted))
            evicted.append(candidate)
            self._remove(candidate)
        self._entries[artifact.adapter_id] = _ResidentAdapter(artifact, step)
        self._resident_bytes += artifact.payload_bytes
        return self._decision("admit", "within_budget", artifact.adapter_id, tuple(evicted))

    def activate(self, adapter_id: str, *, step: int) -> AdapterResidencyDecision:
        _verify_step(step)
        expired = self._evict_expired(step)
        if adapter_id not in self._entries:
            return self._decision("reject", "not_resident", adapter_id, expired)
        if adapter_id in self._active_lanes:
            self._touch(adapter_id, step)
            return self._decision("touch", "already_active", adapter_id, expired)
        if len(self._active_lanes) >= self.policy.max_active_lanes:
            return self._decision("reject", "active_lane_limit", adapter_id, expired)
        self._active_lanes = (*self._active_lanes, adapter_id)
        self._touch(adapter_id, step)
        return self._decision("activate", "resident", adapter_id, expired)

    def deactivate(self, adapter_id: str, *, step: int) -> AdapterResidencyDecision:
        _verify_step(step)
        expired = self._evict_expired(step)
        if adapter_id not in self._active_lanes:
            return self._decision("reject", "not_active", adapter_id, expired)
        self._active_lanes = tuple(value for value in self._active_lanes if value != adapter_id)
        if adapter_id in self._entries:
            self._touch(adapter_id, step)
        return self._decision("deactivate", "removed_from_active_lanes", adapter_id, expired)

    def snapshot(self) -> AdapterActivationSnapshot:
        snapshot = AdapterActivationSnapshot(self.policy.policy_id, self._active_lanes)
        snapshot.verify()
        return snapshot

    def rollback(self, snapshot: AdapterActivationSnapshot, *, step: int) -> AdapterResidencyDecision:
        _verify_step(step)
        snapshot.verify()
        expired = self._evict_expired(step)
        if snapshot.policy_id != self.policy.policy_id:
            return self._decision("reject", "snapshot_policy_mismatch", "", expired)
        if len(snapshot.active_lanes) > self.policy.max_active_lanes:
            return self._decision("reject", "snapshot_exceeds_active_lane_limit", "", expired)
        if any(adapter_id not in self._entries for adapter_id in snapshot.active_lanes):
            return self._decision("reject", "snapshot_adapter_not_resident", "", expired)
        self._active_lanes = snapshot.active_lanes
        for adapter_id in self._active_lanes:
            self._touch(adapter_id, step)
        return self._decision("rollback", "snapshot_restored", "", expired)

    def receipt(self) -> dict[str, Any]:
        entries = [
            {"artifact": entry.artifact.body(), "last_access_step": entry.last_access_step}
            for entry in self._entries.values()
        ]
        body = {
            "schema": "holyfitra.adapter-residency-receipt/v1",
            "policy_id": self.policy.policy_id,
            "resident_bytes": self._resident_bytes,
            "resident_adapters": len(entries),
            "active_lanes": list(self._active_lanes),
            "entries": entries,
        }
        body["receipt_id"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
        return body

    def _evict_expired(self, step: int) -> tuple[str, ...]:
        evicted: list[str] = []
        for adapter_id, entry in tuple(self._entries.items()):
            if adapter_id not in self._active_lanes and not entry.artifact.protected and step - entry.last_access_step > self.policy.max_age_steps:
                evicted.append(adapter_id)
                self._remove(adapter_id)
        return tuple(evicted)

    def _oldest_evictable(self) -> str | None:
        for adapter_id, entry in self._entries.items():
            if adapter_id not in self._active_lanes and not entry.artifact.protected:
                return adapter_id
        return None

    def _touch(self, adapter_id: str, step: int) -> None:
        entry = self._entries[adapter_id]
        self._entries[adapter_id] = _ResidentAdapter(entry.artifact, step)
        self._entries.move_to_end(adapter_id)

    def _remove(self, adapter_id: str) -> None:
        entry = self._entries.pop(adapter_id)
        self._resident_bytes -= entry.artifact.payload_bytes
        self._active_lanes = tuple(value for value in self._active_lanes if value != adapter_id)

    def _decision(self, action: str, reason: str, adapter_id: str, evicted: tuple[str, ...] | list[str]) -> AdapterResidencyDecision:
        return AdapterResidencyDecision(action, reason, adapter_id, tuple(evicted), self._active_lanes, self._resident_bytes, len(self._entries), self.policy.policy_id)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and value[0].isalnum() and value.isascii() and all(character.isalnum() or character in "._-" for character in value)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0.0


def _verify_step(step: int) -> None:
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= MAX_ADAPTER_AGE_STEPS:
        raise AdapterResidencyError("adapter ledger step is invalid")
