#!/usr/bin/env python3
"""Software unified-memory primitives for Holy Fitra.

This is a reference-runtime analogue of unified memory: one aligned backing
arena can expose zero-copy typed views to training, inference, and bridge code.
It does not claim hardware-coherent RAM or physical device unification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class MemoryStats:
    capacity_bytes: int
    live_bytes: int
    free_bytes: int
    high_water_bytes: int
    allocations: int
    releases: int
    reused_bytes: int


@dataclass
class _Block:
    offset: int
    nbytes: int
    shape: tuple[int, ...]
    dtype: np.dtype
    readonly: bool
    released: bool = False


class ArenaView:
    """A typed zero-copy view into a :class:`UnifiedMemoryArena`."""

    def __init__(self, arena: "UnifiedMemoryArena", block: _Block):
        self._arena = arena
        self._block = block

    @property
    def shape(self) -> tuple[int, ...]:
        return self._block.shape

    @property
    def dtype(self) -> np.dtype:
        return self._block.dtype

    @property
    def nbytes(self) -> int:
        return self._block.nbytes

    @property
    def readonly(self) -> bool:
        return self._block.readonly

    @property
    def offset(self) -> int:
        return self._block.offset

    @property
    def released(self) -> bool:
        return self._block.released

    def numpy(self, *, writable: bool = False) -> np.ndarray:
        self._arena._validate_live(self._block)
        if writable and self._block.readonly:
            raise PermissionError("read-only arena view cannot be made writable")
        array = np.ndarray(self._block.shape, dtype=self._block.dtype, buffer=self._arena._storage, offset=self._block.offset)
        if self._block.readonly or not writable:
            array.setflags(write=False)
        return array

    def alias(self, *, readonly: bool | None = None) -> "ArenaView":
        self._arena._validate_live(self._block)
        next_readonly = self._block.readonly if readonly is None else bool(readonly)
        if self._block.readonly and not next_readonly:
            raise PermissionError("read-only view cannot create writable alias")
        alias_block = _Block(self._block.offset, self._block.nbytes, self._block.shape, self._block.dtype, next_readonly)
        self._arena._blocks.append(alias_block)
        self._arena._refs[self._block.offset] = self._arena._refs.get(self._block.offset, 0) + 1
        return ArenaView(self._arena, alias_block)

    def release(self) -> None:
        if self._block.released:
            return
        self._arena._release(self._block)

    def __enter__(self) -> "ArenaView":
        self._arena._validate_live(self._block)
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class UnifiedMemoryArena:
    """Aligned reusable backing storage shared by host-side tensor views."""

    def __init__(self, capacity_bytes: int, *, alignment: int = 64):
        if not isinstance(capacity_bytes, int) or isinstance(capacity_bytes, bool) or not isinstance(alignment, int) or isinstance(alignment, bool) or capacity_bytes <= 0 or alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("capacity must be positive and alignment must be a power of two")
        self.capacity_bytes = int(capacity_bytes)
        self.alignment = int(alignment)
        self._storage = bytearray(self.capacity_bytes + self.alignment)
        self._free: list[tuple[int, int]] = [(0, self.capacity_bytes)]
        self._blocks: list[_Block] = []
        self._refs: dict[int, int] = {}
        self._live_bytes = 0
        self._high_water_bytes = 0
        self._allocations = 0
        self._releases = 0
        self._reused_bytes = 0

    @staticmethod
    def _aligned(value: int, alignment: int) -> int:
        return (value + alignment - 1) & ~(alignment - 1)

    @property
    def stats(self) -> MemoryStats:
        return MemoryStats(self.capacity_bytes, self._live_bytes, self.capacity_bytes - self._live_bytes, self._high_water_bytes, self._allocations, self._releases, self._reused_bytes)

    @property
    def live_views(self) -> tuple[ArenaView, ...]:
        return tuple(ArenaView(self, block) for block in self._blocks if not block.released)

    def allocate(self, shape: tuple[int, ...] | list[int], *, dtype: str | np.dtype = np.float32, readonly: bool = False) -> ArenaView:
        try:
            raw_shape = tuple(shape)
        except TypeError as error:
            raise ValueError("arena shape must be an iterable of dimensions") from error
        if not raw_shape or any(not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0 for dimension in raw_shape):
            raise ValueError("arena shape must contain positive integer dimensions")
        normalized_shape = tuple(raw_shape)
        normalized_dtype = np.dtype(dtype)
        if normalized_dtype.hasobject:
            raise TypeError("object dtypes are not supported")
        elements = math.prod(normalized_shape)
        nbytes = elements * normalized_dtype.itemsize
        if nbytes <= 0:
            raise ValueError("arena allocation size overflowed")
        for index, (start, size) in enumerate(self._free):
            offset = self._aligned(start, self.alignment)
            padding = offset - start
            if size - padding < nbytes:
                continue
            tail_start = offset + nbytes
            tail_size = size - padding - nbytes
            replacement: list[tuple[int, int]] = []
            if padding:
                replacement.append((start, padding))
            if tail_size:
                replacement.append((tail_start, tail_size))
            self._free[index:index + 1] = replacement
            block = _Block(offset, nbytes, normalized_shape, normalized_dtype, bool(readonly))
            self._blocks.append(block)
            self._refs[offset] = 1
            self._live_bytes += nbytes
            self._high_water_bytes = max(self._high_water_bytes, self._live_bytes)
            self._allocations += 1
            if self._releases:
                self._reused_bytes += nbytes
            return ArenaView(self, block)
        raise MemoryError(f"unified arena exhausted: requested {nbytes} bytes")

    def _validate_live(self, block: _Block) -> None:
        if block.released or block not in self._blocks:
            raise RuntimeError("arena view is released or does not belong to this arena")

    def _release(self, block: _Block) -> None:
        self._validate_live(block)
        block.released = True
        self._releases += 1
        refs = self._refs.get(block.offset, 0) - 1
        if refs < 0:
            raise RuntimeError("arena reference count underflow")
        if refs == 0:
            self._refs.pop(block.offset, None)
            self._live_bytes -= block.nbytes
            self._free.append((block.offset, block.nbytes))
            self._coalesce()
        else:
            self._refs[block.offset] = refs

    def _coalesce(self) -> None:
        merged: list[tuple[int, int]] = []
        for start, size in sorted(self._free):
            if merged and merged[-1][0] + merged[-1][1] >= start:
                previous_start, previous_size = merged[-1]
                merged[-1] = (previous_start, max(previous_start + previous_size, start + size) - previous_start)
            else:
                merged.append((start, size))
        self._free = merged

    def clear(self) -> None:
        for block in self._blocks:
            block.released = True
        self._free = [(0, self.capacity_bytes)]
        self._refs.clear()
        self._live_bytes = 0

    def __enter__(self) -> "UnifiedMemoryArena":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.clear()


__all__ = ["ArenaView", "MemoryStats", "UnifiedMemoryArena"]
