#!/usr/bin/env python3
"""Canonical tensor and resource contracts shared by compiler-facing AI layers."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from holy_fitra_execution_plan import ExecutionPlan


class TensorContractError(ValueError):
    """A tensor or execution-resource contract is malformed or unsatisfied."""


_DTYPE_BITS = {"f16": 16, "f32": 32, "int4": 4, "int8": 8}
_LAYOUTS = {"contiguous", "ragged"}
_DEVICES = {"host", "neon"}
_OWNERSHIP = {"unique", "shared", "borrowed"}


@dataclass(frozen=True)
class TensorContract:
    name: str
    shape: tuple[int, ...]
    dtype: str
    layout: str = "contiguous"
    device: str = "host"
    ownership: str = "unique"

    def __post_init__(self) -> None:
        if not self.name.isascii() or not self.name or not self.shape or any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in self.shape) or self.dtype not in _DTYPE_BITS or self.layout not in _LAYOUTS or self.device not in _DEVICES or self.ownership not in _OWNERSHIP:
            raise TensorContractError("tensor contract is invalid")

    @property
    def storage_bytes(self) -> int:
        elements = math.prod(self.shape)
        return (elements * _DTYPE_BITS[self.dtype] + 7) // 8

    def body(self) -> dict[str, object]:
        return {"name": self.name, "shape": list(self.shape), "dtype": self.dtype, "layout": self.layout, "device": self.device, "ownership": self.ownership, "storage_bytes": self.storage_bytes}


@dataclass(frozen=True)
class TensorResourceContract:
    tensors: tuple[TensorContract, ...]
    memory_budget_bytes: int
    max_latency_ns: int = 0
    max_energy: float = 0.0
    required_kernel_abi: int = 1

    def __post_init__(self) -> None:
        if not self.tensors or len({item.name for item in self.tensors}) != len(self.tensors) or not isinstance(self.memory_budget_bytes, int) or self.memory_budget_bytes <= 0 or not isinstance(self.max_latency_ns, int) or self.max_latency_ns < 0 or not math.isfinite(self.max_energy) or self.max_energy < 0.0 or not isinstance(self.required_kernel_abi, int) or self.required_kernel_abi <= 0:
            raise TensorContractError("tensor resource contract is invalid")
        if self.storage_bytes > self.memory_budget_bytes:
            raise TensorContractError("tensor contract storage exceeds its memory budget")

    @property
    def storage_bytes(self) -> int:
        return sum(item.storage_bytes for item in self.tensors)

    def body(self) -> dict[str, object]:
        return {"schema": "holyfitra.tensor-resource-contract/v1", "tensors": [item.body() for item in self.tensors], "memory_budget_bytes": self.memory_budget_bytes, "max_latency_ns": self.max_latency_ns, "max_energy": self.max_energy, "required_kernel_abi": self.required_kernel_abi}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def verify_plan(self, plan: ExecutionPlan) -> None:
        plan.verify()
        if plan.kernel_abi != self.required_kernel_abi or plan.memory_bytes > self.memory_budget_bytes:
            raise TensorContractError("execution plan violates tensor memory or ABI contract")
        if self.max_latency_ns and (plan.deadline_ns == 0 or plan.deadline_ns > self.max_latency_ns):
            raise TensorContractError("execution plan violates tensor latency contract")
        if self.max_energy and plan.estimated_energy > self.max_energy:
            raise TensorContractError("execution plan violates tensor energy contract")


__all__ = ["TensorContract", "TensorContractError", "TensorResourceContract"]
