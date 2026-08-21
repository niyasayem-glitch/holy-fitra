#!/usr/bin/env python3
"""Content-addressed tensor sharing for Holy Fitra inference and training."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import numpy as np

from holyfitra_memory import ArenaView, UnifiedMemoryArena


@dataclass(frozen=True)
class PoolStats:
    entries: int
    handles: int
    physical_bytes: int
    logical_bytes: int
    deduplicated_bytes: int


@dataclass
class _Entry:
    key: str
    view: ArenaView
    handles: int = 0


class SharedTensor:
    """Read-only shared view with explicit copy-on-write materialization."""

    def __init__(self, pool: "SharedTensorPool", key: str, view: ArenaView):
        self._pool = pool
        self.key = key
        self._view = view
        self._released = False

    @property
    def shape(self) -> tuple[int, ...]:
        return self._view.shape

    @property
    def dtype(self) -> np.dtype:
        return self._view.dtype

    @property
    def nbytes(self) -> int:
        return self._view.nbytes

    @property
    def released(self) -> bool:
        return self._released

    def numpy(self) -> np.ndarray:
        if self._released:
            raise RuntimeError("shared tensor handle is released")
        return self._view.numpy()

    def materialize_for_training(self) -> np.ndarray:
        """Return an isolated writable copy; shared inference bytes stay immutable."""
        if self._released:
            raise RuntimeError("shared tensor handle is released")
        return np.ascontiguousarray(self._view.numpy(), dtype=self.dtype).copy()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._pool.release(self)

    def __enter__(self) -> "SharedTensor":
        if self._released:
            raise RuntimeError("shared tensor handle is released")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class SharedTensorPool:
    """Deduplicate identical immutable tensors in one reusable memory arena."""

    def __init__(self, capacity_bytes: int, *, alignment: int = 64):
        self.arena = UnifiedMemoryArena(capacity_bytes, alignment=alignment)
        self._entries: dict[str, _Entry] = {}
        self._handles = 0

    @staticmethod
    def _key(array: np.ndarray) -> str:
        digest = hashlib.sha256()
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(repr(tuple(array.shape)).encode("ascii"))
        digest.update(array.tobytes(order="C"))
        return digest.hexdigest()

    def intern(self, data: np.ndarray, *, key: str | None = None) -> SharedTensor:
        array = np.ascontiguousarray(np.asarray(data))
        if array.ndim == 0 or array.dtype.hasobject:
            raise ValueError("shared tensor must be a non-scalar numeric array")
        digest = key or self._key(array)
        entry = self._entries.get(digest)
        if entry is not None:
            if entry.view.shape != array.shape or entry.view.dtype != array.dtype or not np.array_equal(entry.view.numpy(), array):
                raise ValueError("explicit shared tensor key collides with different data")
            handle_view = entry.view.alias(readonly=True)
        else:
            master = self.arena.allocate(array.shape, dtype=array.dtype, readonly=False)
            master.numpy(writable=True)[:] = array
            master._block.readonly = True
            entry = _Entry(digest, master, 0)
            self._entries[digest] = entry
            handle_view = master.alias(readonly=True)
        entry.handles += 1
        self._handles += 1
        return SharedTensor(self, digest, handle_view)

    def release(self, tensor: SharedTensor) -> None:
        entry = self._entries.get(tensor.key)
        if entry is None:
            raise RuntimeError("shared tensor is not owned by this pool")
        tensor._view.release()
        entry.handles -= 1
        self._handles -= 1
        if entry.handles == 0:
            entry.view.release()
            self._entries.pop(tensor.key)

    @property
    def stats(self) -> PoolStats:
        physical = sum(entry.view.nbytes for entry in self._entries.values())
        logical = sum(entry.view.nbytes * entry.handles for entry in self._entries.values())
        return PoolStats(len(self._entries), self._handles, physical, logical, max(0, logical - physical))

    def clear(self) -> None:
        for entry in self._entries.values():
            entry.view.release()
        self._entries.clear()
        self._handles = 0
        self.arena.clear()


__all__ = ["PoolStats", "SharedTensor", "SharedTensorPool"]
