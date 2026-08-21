#!/usr/bin/env python3
"""Tiered software residency management for Android-oriented Holy Fitra memory."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from holyfitra_tensor_pool import SharedTensor, SharedTensorPool


class ResidencyTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    EVICTED = "evicted"


@dataclass(frozen=True)
class ResidencyStats:
    records: int
    hot: int
    warm: int
    cold: int
    pinned: int
    active_leases: int
    evicted: int
    physical_bytes: int
    pressure: float
    thermal_hint: str


@dataclass
class _Record:
    key: str
    tensor: SharedTensor
    priority: int
    pinned: bool
    last_access_ns: int
    access_count: int = 0
    active_leases: int = 0
    tier: ResidencyTier = ResidencyTier.COLD
    evicted: bool = False


class ResidencyLease:
    """A scoped lease that prevents eviction while a tensor is in use."""

    def __init__(self, manager: "TieredResidencyManager", record: _Record):
        self._manager = manager
        self._record = record
        self._closed = False

    def numpy(self) -> np.ndarray:
        if self._closed:
            raise RuntimeError("residency lease is closed")
        self._manager._validate_record(self._record)
        return self._record.tensor.numpy()

    @property
    def key(self) -> str:
        return self._record.key

    def __enter__(self) -> "ResidencyLease":
        if self._closed:
            raise RuntimeError("residency lease is closed")
        self._manager._validate_record(self._record)
        return self

    def __exit__(self, *_exc: object) -> None:
        if not self._closed:
            self._closed = True
            self._record.active_leases = max(0, self._record.active_leases - 1)


class ResidencyHandle:
    """Manager-owned handle; consumers should use a lease for active work."""

    def __init__(self, manager: "TieredResidencyManager", record: _Record):
        self._manager = manager
        self._record = record

    @property
    def key(self) -> str:
        return self._record.key

    @property
    def tier(self) -> ResidencyTier:
        return self._record.tier

    @property
    def pinned(self) -> bool:
        return self._record.pinned

    def lease(self, *, timestamp_ns: int | None = None) -> ResidencyLease:
        self._manager._touch(self._record, timestamp_ns)
        self._manager._validate_record(self._record)
        self._record.active_leases += 1
        return ResidencyLease(self._manager, self._record)

    def pin(self) -> None:
        self._manager._validate_record(self._record)
        self._record.pinned = True
        self._record.priority = max(self._record.priority, 100)

    def unpin(self) -> None:
        self._manager._validate_record(self._record)
        self._record.pinned = False


class TieredResidencyManager:
    """Pressure-aware, hysteretic residency over a shared tensor pool.

    `pressure` is an explicit host/device hint in [0, 1]. `thermal_hint` is a
    caller-provided label such as nominal, warm, or critical. No device sensor
    is assumed or queried by this reference implementation.
    """

    def __init__(self, pool: SharedTensorPool, *, cold_after_ns: int = 10_000_000, pressure_start: float = 0.65, pressure_critical: float = 0.9):
        if cold_after_ns <= 0 or not 0.0 < pressure_start < pressure_critical <= 1.0:
            raise ValueError("invalid residency thresholds")
        self.pool = pool
        self.cold_after_ns = int(cold_after_ns)
        self.pressure_start = float(pressure_start)
        self.pressure_critical = float(pressure_critical)
        self.pressure = 0.0
        self.thermal_hint = "nominal"
        self._records: dict[str, _Record] = {}

    def admit(self, data: np.ndarray, *, priority: int = 0, pinned: bool = False, timestamp_ns: int = 0) -> ResidencyHandle:
        if priority < 0:
            raise ValueError("priority must be non-negative")
        shared = self.pool.intern(data)
        existing = self._records.get(shared.key)
        if existing is not None and not existing.evicted:
            shared.release()
            existing.priority = max(existing.priority, int(priority))
            existing.pinned = existing.pinned or bool(pinned)
            self._touch(existing, timestamp_ns)
            return ResidencyHandle(self, existing)
        record = _Record(shared.key, shared, int(priority), bool(pinned), int(timestamp_ns), access_count=1, tier=ResidencyTier.WARM)
        if record.pinned:
            record.priority = max(record.priority, 100)
        self._records[record.key] = record
        return ResidencyHandle(self, record)

    def _validate_record(self, record: _Record) -> None:
        if record.evicted or record.tier == ResidencyTier.EVICTED:
            raise RuntimeError("residency handle was evicted; reacquire it from the source pool")

    def _touch(self, record: _Record, timestamp_ns: int | None) -> None:
        self._validate_record(record)
        now = record.last_access_ns if timestamp_ns is None else int(timestamp_ns)
        if now < record.last_access_ns:
            raise ValueError("residency timestamps must be monotonic per handle")
        record.last_access_ns = now
        record.access_count += 1
        record.tier = ResidencyTier.HOT if record.pinned or record.access_count >= 3 else ResidencyTier.WARM

    def set_hints(self, *, pressure: float, thermal_hint: str = "nominal") -> None:
        if not 0.0 <= pressure <= 1.0 or thermal_hint not in {"nominal", "warm", "critical"}:
            raise ValueError("invalid residency hint")
        self.pressure = float(pressure)
        self.thermal_hint = thermal_hint

    def rebalance(self, *, now_ns: int, max_evictions: int | None = None) -> tuple[str, ...]:
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        should_reclaim = self.pressure >= self.pressure_start or self.thermal_hint in {"warm", "critical"}
        if not should_reclaim:
            return ()
        candidates: list[tuple[float, _Record]] = []
        for record in self._records.values():
            if record.evicted or record.pinned or record.active_leases or record.tier == ResidencyTier.HOT:
                continue
            age = max(0, now_ns - record.last_access_ns)
            if age < self.cold_after_ns and self.pressure < self.pressure_critical:
                continue
            record.tier = ResidencyTier.COLD
            score = (age / max(1, self.cold_after_ns)) - record.priority * 0.01 - record.access_count * 0.001
            candidates.append((score, record))
        candidates.sort(key=lambda item: (-item[0], item[1].key))
        limit = len(candidates) if max_evictions is None else max(0, int(max_evictions))
        evicted: list[str] = []
        for _, record in candidates[:limit]:
            record.tensor.release()
            record.evicted = True
            record.tier = ResidencyTier.EVICTED
            evicted.append(record.key)
        return tuple(evicted)

    def snapshot(self) -> dict[str, Any]:
        return {key: {"tier": record.tier.value, "priority": record.priority, "pinned": record.pinned, "last_access_ns": record.last_access_ns, "access_count": record.access_count, "active_leases": record.active_leases, "evicted": record.evicted} for key, record in sorted(self._records.items())}

    @property
    def stats(self) -> ResidencyStats:
        records = tuple(self._records.values())
        return ResidencyStats(len(records), sum(record.tier == ResidencyTier.HOT for record in records), sum(record.tier == ResidencyTier.WARM for record in records), sum(record.tier == ResidencyTier.COLD for record in records), sum(record.pinned for record in records), sum(record.active_leases for record in records), sum(record.evicted for record in records), self.pool.stats.physical_bytes, self.pressure, self.thermal_hint)


__all__ = ["ResidencyHandle", "ResidencyLease", "ResidencyStats", "ResidencyTier", "TieredResidencyManager"]
