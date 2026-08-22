#!/usr/bin/env python3
"""Deterministic streaming datasets and batching for Holy Fitra.

The pipeline is intentionally NumPy-only and bounded-memory. A source is either
an iterable of ``(input, target)`` samples or a zero-argument factory that can
reopen the source for every epoch. Shuffling uses a bounded buffer rather than
materializing the complete dataset.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Any

import numpy as np

Sample = tuple[np.ndarray, np.ndarray]
Source = Callable[[], Iterable[tuple[Any, Any]]] | Iterable[tuple[Any, Any]]


@dataclass(frozen=True)
class Batch:
    inputs: np.ndarray
    targets: np.ndarray
    indices: np.ndarray
    epoch: int
    step: int

    def __post_init__(self) -> None:
        if self.inputs.ndim != 2 or self.targets.ndim != 2 or self.inputs.shape[0] == 0 or self.inputs.shape[0] != self.targets.shape[0]:
            raise ValueError("batch arrays must be non-empty two-dimensional arrays with equal row counts")
        if self.indices.ndim != 1 or self.indices.shape[0] != self.inputs.shape[0]:
            raise ValueError("batch indices must match batch row count")
        if self.inputs.dtype != np.float32 or self.targets.dtype != np.float32 or not np.all(np.isfinite(self.inputs)) or not np.all(np.isfinite(self.targets)):
            raise ValueError("batch arrays must use finite float32 values")

    @property
    def size(self) -> int:
        return int(self.inputs.shape[0])


@dataclass(frozen=True)
class DatasetSplit:
    train: "StreamingDataset"
    validation: "StreamingDataset"
    train_fraction: float
    seed: int


class StreamingDataset:
    """A repeatable, validated stream of fixed-shape supervised samples."""

    def __init__(self, source: Source, *, input_shape: tuple[int, ...], target_shape: tuple[int, ...], seed: int = 0, name: str = "dataset", cardinality: int | None = None):
        if not input_shape or not target_shape or any(not isinstance(d, int) or isinstance(d, bool) or d <= 0 for d in input_shape + target_shape):
            raise ValueError("dataset shapes must contain positive integer dimensions")
        if cardinality is not None and (not isinstance(cardinality, int) or isinstance(cardinality, bool) or cardinality < 0):
            raise ValueError("cardinality must be non-negative")
        self.input_shape = tuple(int(d) for d in input_shape)
        self.target_shape = tuple(int(d) for d in target_shape)
        self.seed = int(seed)
        self.name = str(name)
        self.cardinality = None if cardinality is None else int(cardinality)
        if callable(source):
            self._source_factory = source
        else:
            iterator = iter(source)
            if iterator is source:
                raise ValueError("one-shot iterators require a zero-argument source factory")
            self._source_factory = lambda source=source: iter(source)

    @classmethod
    def from_arrays(cls, inputs: np.ndarray, targets: np.ndarray, *, seed: int = 0, name: str = "array_dataset") -> "StreamingDataset":
        x = np.ascontiguousarray(np.asarray(inputs, dtype=np.float32))
        y = np.ascontiguousarray(np.asarray(targets, dtype=np.float32))
        if x.ndim != 2 or y.ndim != 2 or x.shape[0] == 0 or x.shape[0] != y.shape[0] or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("array dataset requires non-empty finite 2D arrays with equal row counts")
        def source() -> Iterator[Sample]:
            for index in range(x.shape[0]):
                yield x[index], y[index]
        return cls(source, input_shape=(x.shape[1],), target_shape=(y.shape[1],), seed=seed, name=name, cardinality=x.shape[0])

    def _validate_sample(self, sample: tuple[Any, Any], index: int) -> Sample:
        if not isinstance(sample, (tuple, list)) or len(sample) != 2:
            raise ValueError(f"sample {index} must be a (input, target) pair")
        x = np.ascontiguousarray(np.asarray(sample[0], dtype=np.float32))
        y = np.ascontiguousarray(np.asarray(sample[1], dtype=np.float32))
        if x.shape != self.input_shape or y.shape != self.target_shape:
            raise ValueError(f"sample {index} shape mismatch: expected {self.input_shape}/{self.target_shape}, got {x.shape}/{y.shape}")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError(f"sample {index} contains non-finite values")
        return x, y

    def _indexed_samples(self) -> Iterator[tuple[int, Sample]]:
        for index, sample in enumerate(self._source_factory()):
            yield index, self._validate_sample(sample, index)

    def iter_samples(self) -> Iterator[Sample]:
        for _, sample in self._indexed_samples():
            yield sample

    def count(self) -> int:
        if self.cardinality is not None:
            return self.cardinality
        return sum(1 for _ in self._indexed_samples())

    def take(self, count: int) -> list[Sample]:
        if count < 0:
            raise ValueError("count must be non-negative")
        result: list[Sample] = []
        for sample in self.iter_samples():
            if len(result) >= count:
                break
            result.append((sample[0].copy(), sample[1].copy()))
        return result

    def split(self, train_fraction: float = 0.9, *, seed: int | None = None) -> DatasetSplit:
        if not 0.0 < train_fraction < 1.0:
            raise ValueError("train_fraction must be strictly between 0 and 1")
        split_seed = self.seed if seed is None else int(seed)

        def make_view(want_train: bool) -> Callable[[], Iterator[Sample]]:
            def source() -> Iterator[Sample]:
                for index, sample in self._indexed_samples():
                    is_train = _partition_value(split_seed, index) < train_fraction
                    if is_train == want_train:
                        yield sample
            return source

        return DatasetSplit(
            train=StreamingDataset(make_view(True), input_shape=self.input_shape, target_shape=self.target_shape, seed=self.seed, name=f"{self.name}.train"),
            validation=StreamingDataset(make_view(False), input_shape=self.input_shape, target_shape=self.target_shape, seed=self.seed, name=f"{self.name}.validation"),
            train_fraction=float(train_fraction),
            seed=split_seed,
        )

    def iter_batches(self, batch_size: int, *, epoch: int = 0, shuffle: bool = False, shuffle_buffer: int | None = None, drop_last: bool = False) -> Iterator[Batch]:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not isinstance(epoch, int) or isinstance(epoch, bool) or batch_size <= 0 or epoch < 0:
            raise ValueError("batch_size and epoch must be valid integers")
        if shuffle_buffer is None:
            shuffle_buffer = max(batch_size * 4, batch_size)
        if not isinstance(shuffle_buffer, int) or isinstance(shuffle_buffer, bool) or shuffle_buffer <= 0:
            raise ValueError("shuffle_buffer must be a positive integer")
        rows: Iterable[tuple[int, Sample]] = self._indexed_samples()
        if shuffle:
            rows = _buffer_shuffle(rows, max(batch_size, int(shuffle_buffer)), _epoch_rng(self.seed, epoch))
        inputs: list[np.ndarray] = []
        targets: list[np.ndarray] = []
        indices: list[int] = []
        step = 0
        for index, (x, y) in rows:
            inputs.append(x)
            targets.append(y)
            indices.append(index)
            if len(inputs) == batch_size:
                yield _make_batch(inputs, targets, indices, epoch, step)
                step += 1
                inputs, targets, indices = [], [], []
        if inputs and not drop_last:
            yield _make_batch(inputs, targets, indices, epoch, step)

    def to_arrays(self, *, max_samples: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        if max_samples is not None and max_samples < 0:
            raise ValueError("max_samples must be non-negative")
        inputs: list[np.ndarray] = []
        targets: list[np.ndarray] = []
        for index, (x, y) in self._indexed_samples():
            if max_samples is not None and index >= max_samples:
                break
            inputs.append(x)
            targets.append(y)
        if not inputs:
            return np.empty((0,) + self.input_shape, dtype=np.float32), np.empty((0,) + self.target_shape, dtype=np.float32)
        return np.stack(inputs).astype(np.float32, copy=False), np.stack(targets).astype(np.float32, copy=False)


def _make_batch(inputs: list[np.ndarray], targets: list[np.ndarray], indices: list[int], epoch: int, step: int) -> Batch:
    return Batch(np.stack(inputs).astype(np.float32, copy=False), np.stack(targets).astype(np.float32, copy=False), np.asarray(indices, dtype=np.int64), int(epoch), int(step))


def _epoch_rng(seed: int, epoch: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF, int(epoch) & 0xFFFFFFFF]))


def _partition_value(seed: int, index: int) -> float:
    digest = hashlib.blake2b(f"holyfitra-split:{int(seed)}:{int(index)}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") / float(1 << 64)


def _buffer_shuffle(rows: Iterable[tuple[int, Sample]], buffer_size: int, rng: np.random.Generator) -> Iterator[tuple[int, Sample]]:
    iterator = iter(rows)
    buffer: list[tuple[int, Sample]] = []
    for row in iterator:
        if len(buffer) < buffer_size:
            buffer.append(row)
            continue
        slot = int(rng.integers(0, len(buffer)))
        yield buffer[slot]
        buffer[slot] = row
    rng.shuffle(buffer)
    yield from buffer


__all__ = ["Batch", "DatasetSplit", "StreamingDataset"]
