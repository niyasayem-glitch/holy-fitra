#!/usr/bin/env python3
"""Typed runtime contracts shared by Holy Fitra compiler and AI layers.

This module intentionally contains no hidden threads, network access, or model
execution. It is a small, deterministic contract layer that can be lowered to
HyperIR/native ABI objects later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, Iterable, Sequence, TypeVar
import hashlib
import json

T = TypeVar("T")
E = TypeVar("E")


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Option(Generic[T]):
    value: T | None = None

    @property
    def is_some(self) -> bool:
        return self.value is not None

    def unwrap(self) -> T:
        if self.value is None:
            raise ContractError("attempted to unwrap None")
        return self.value

    @staticmethod
    def some(value: T) -> "Option[T]":
        if value is None:
            raise ContractError("Option.some cannot contain None")
        return Option(value)

    @staticmethod
    def none() -> "Option[T]":
        return Option(None)


@dataclass(frozen=True)
class Result(Generic[T, E]):
    value: T | None = None
    error: E | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.error is None):
            raise ContractError("Result must contain exactly one of value or error")

    @property
    def is_ok(self) -> bool:
        return self.error is None

    def unwrap(self) -> T:
        if self.error is not None:
            raise ContractError(f"attempted to unwrap Err: {self.error}")
        return self.value  # type: ignore[return-value]

    @staticmethod
    def ok(value: T) -> "Result[T, E]":
        if value is None:
            raise ContractError("Result.ok cannot contain None")
        return Result(value=value)

    @staticmethod
    def err(error: E) -> "Result[T, E]":
        if error is None:
            raise ContractError("Result.err cannot contain None")
        return Result(error=error)


class EvidenceKind(str, Enum):
    PREDICTION = "prediction"
    CLAIM = "claim"
    FACT = "fact"


@dataclass(frozen=True)
class Evidence(Generic[T]):
    value: T
    kind: EvidenceKind
    confidence: float
    provenance: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ContractError("evidence confidence must be between 0 and 1")
        if not self.provenance:
            raise ContractError("evidence provenance is required")

    def can_promote_to(self, target: EvidenceKind) -> bool:
        order = {EvidenceKind.PREDICTION: 0, EvidenceKind.CLAIM: 1, EvidenceKind.FACT: 2}
        return order[target] <= order[self.kind]


class OwnershipMode(str, Enum):
    OWNED = "owned"
    BORROW = "borrow"
    BORROW_MUT = "borrow_mut"
    SHARED = "shared"


@dataclass(frozen=True)
class OwnershipContract:
    name: str
    mode: OwnershipMode = OwnershipMode.OWNED
    generation: int = 0

    def validate_transition(self, next_mode: OwnershipMode) -> None:
        if self.mode == OwnershipMode.BORROW_MUT and next_mode in {OwnershipMode.BORROW, OwnershipMode.SHARED, OwnershipMode.BORROW_MUT}:
            raise ContractError(f"mutable borrow of {self.name} remains active")
        if self.mode == OwnershipMode.OWNED and next_mode == OwnershipMode.BORROW_MUT and self.generation < 0:
            raise ContractError("ownership generation cannot be negative")

    def moved(self) -> "OwnershipContract":
        if self.mode != OwnershipMode.OWNED:
            raise ContractError(f"only owned values can move: {self.name}:{self.mode.value}")
        return OwnershipContract(self.name, OwnershipMode.OWNED, self.generation + 1)


@dataclass(frozen=True)
class TaskSpec:
    name: str
    parent: str | None = None
    priority: int = 0
    deadline_ms: int | None = None
    capacity: int = 1
    cancelable: bool = True
    effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ContractError("task capacity must be positive")
        if self.deadline_ms is not None and self.deadline_ms <= 0:
            raise ContractError("task deadline must be positive")
        if len(set(self.effects)) != len(self.effects):
            raise ContractError("task effects must be unique")


class RestartPolicy(str, Enum):
    NEVER = "never"
    ONCE = "once"
    ALWAYS = "always"


class TaskScope:
    def __init__(self, name: str, parent: "TaskScope | None" = None):
        self.name = name
        self.parent = parent
        self.children: list[TaskSpec] = []
        self.cancelled = False
        self.closed = False

    def spawn(self, task: TaskSpec) -> None:
        if self.closed:
            raise ContractError("cannot spawn in a closed task scope")
        if self.cancelled:
            raise ContractError("cannot spawn in a cancelled task scope")
        if task.parent not in {None, self.name}:
            raise ContractError(f"task {task.name} has parent {task.parent}, expected {self.name}")
        if any(existing.name == task.name for existing in self.children):
            raise ContractError(f"duplicate task in scope: {task.name}")
        self.children.append(task)

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> tuple[str, ...]:
        if self.closed:
            return tuple(child.name for child in self.children)
        self.closed = True
        return tuple(child.name for child in self.children)


@dataclass(frozen=True)
class SupervisorSpec:
    name: str
    children: tuple[TaskSpec, ...]
    restart: RestartPolicy = RestartPolicy.ONCE
    max_restarts: int = 1
    fallback: str = "safe"

    def __post_init__(self) -> None:
        if self.max_restarts < 0:
            raise ContractError("max_restarts cannot be negative")
        names = [child.name for child in self.children]
        if len(names) != len(set(names)):
            raise ContractError("supervisor child names must be unique")


@dataclass(frozen=True)
class KernelSpecializationKey:
    operation: str
    dtype: str
    device: str
    layout: str
    shape: tuple[int, ...] = ()
    quantization_proof: str | None = None
    fallback_precision: str = "f16"

    def digest(self) -> str:
        payload = {
            "operation": self.operation,
            "dtype": self.dtype,
            "device": self.device,
            "layout": self.layout,
            "shape": list(self.shape),
            "quantization_proof": self.quantization_proof,
            "fallback_precision": self.fallback_precision,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KernelContract:
    name: str
    dtype: str
    device: str
    layout: str
    quantization_proof: str | None = None
    memory_bytes: int | None = None
    energy_budget_mj: float | None = None
    fallbacks: tuple[str, ...] = ("f16",)
    required_effects: tuple[str, ...] = ()

    def specialization_key(self, shape: Sequence[int] = ()) -> KernelSpecializationKey:
        fallback = self.fallbacks[0] if self.fallbacks else "f16"
        return KernelSpecializationKey(self.name, self.dtype, self.device, self.layout, tuple(int(value) for value in shape), self.quantization_proof, fallback)

    def verify(self, *, available_memory: int | None = None, allowed_effects: Iterable[str] = ()) -> Result["KernelContract", str]:
        if self.memory_bytes is not None and self.memory_bytes < 0:
            return Result.err("kernel memory_bytes cannot be negative")
        if available_memory is not None and self.memory_bytes is not None and self.memory_bytes > available_memory:
            return Result.err("kernel exceeds available memory")
        allowed = set(allowed_effects)
        missing = sorted(set(self.required_effects) - allowed)
        if missing:
            return Result.err("missing kernel effects: " + ", ".join(missing))
        if self.dtype == "int4" and not self.quantization_proof:
            return Result.err("int4 kernel requires a quantization proof")
        return Result.ok(self)


def demo() -> dict[str, object]:
    task = TaskSpec("decode", priority=5, deadline_ms=50, capacity=4, effects=("model", "memory"))
    supervisor = SupervisorSpec("inference", (task,), fallback="int8")
    kernel = KernelContract("qkv", "int4", "neon", "row_major", "proof:demo", 4096, 2.0, ("int8", "f16"), ("model",))
    verified = kernel.verify(available_memory=8192, allowed_effects=("model", "memory"))
    scope = TaskScope("inference")
    scope.spawn(task)
    evidence = Evidence("token", EvidenceKind.PREDICTION, 0.7, "draft:model")
    return {"option": Option.some("prediction").is_some, "result": Result.ok(7).is_ok, "supervisor": supervisor.name, "kernel_verified": verified.is_ok, "specialization": kernel.specialization_key((1, 64)).digest(), "task_scope": scope.close(), "evidence_kind": evidence.kind.value}


if __name__ == "__main__":
    import json
    print(json.dumps(demo(), indent=2, sort_keys=True))
