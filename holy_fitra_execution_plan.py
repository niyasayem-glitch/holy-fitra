#!/usr/bin/env python3
"""Holy Fitra proof-carrying execution plans.

This module makes performance decisions first-class, deterministic, and
verifiable. A plan binds model identity, kernel ABI, precision, quality proof,
core policy, thermal state, memory budget, deadline, and fallback lineage.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class PlanError(RuntimeError):
    pass


class Precision(str, Enum):
    INT4 = "int4"
    INT8 = "int8"
    F16 = "f16"


class Thermal(str, Enum):
    NORMAL = "normal"
    WARM = "warm"
    HOT = "hot"
    CRITICAL = "critical"


class CorePolicy(str, Enum):
    ANY = "any"
    BIG_ONLY = "big_only"
    LITTLE_ONLY = "little_only"
    BIG_PREFERRED = "big_preferred"
    LITTLE_PREFERRED = "little_preferred"


class Priority(str, Enum):
    BACKGROUND = "background"
    THROUGHPUT = "throughput"
    LATENCY = "latency"
    INTERACTIVE = "interactive"


@dataclass(frozen=True)
class KernelCandidate:
    name: str
    precision: Precision
    abi_version: int
    calibration_mse: float
    max_mse: float
    memory_bytes: int
    estimated_energy: float
    supported_cores: tuple[CorePolicy, ...] = (CorePolicy.ANY, CorePolicy.BIG_PREFERRED, CorePolicy.LITTLE_PREFERRED)
    proof_hash: str = ""

    def passes_quality_gate(self) -> bool:
        return self.calibration_mse <= self.max_mse and bool(self.proof_hash)


@dataclass(frozen=True)
class PlanConstraints:
    max_mse: float
    memory_budget_bytes: int
    energy_budget: float
    thermal: Thermal = Thermal.NORMAL
    priority: Priority = Priority.INTERACTIVE
    deadline_ns: int = 0
    required_abi: int = 1
    allowed_cores: tuple[CorePolicy, ...] = (CorePolicy.ANY, CorePolicy.BIG_PREFERRED, CorePolicy.LITTLE_PREFERRED)
    allow_precision_fallback: bool = True


@dataclass(frozen=True)
class ExecutionPlan:
    schema: str
    plan_id: str
    model_hash: str
    kernel_name: str
    precision: Precision
    kernel_abi: int
    proof_hash: str
    calibration_mse: float
    memory_bytes: int
    estimated_energy: float
    core_policy: CorePolicy
    priority: Priority
    thermal: Thermal
    deadline_ns: int
    fallbacks: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "model_hash": self.model_hash,
            "kernel_name": self.kernel_name,
            "precision": self.precision.value,
            "kernel_abi": self.kernel_abi,
            "proof_hash": self.proof_hash,
            "calibration_mse": self.calibration_mse,
            "memory_bytes": self.memory_bytes,
            "estimated_energy": self.estimated_energy,
            "core_policy": self.core_policy.value,
            "priority": self.priority.value,
            "thermal": self.thermal.value,
            "deadline_ns": self.deadline_ns,
            "fallbacks": list(self.fallbacks),
            "metadata": self.metadata,
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"), default=str)

    def recompute_id(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    def verify(self, *, now_ns: int | None = None) -> None:
        if not hmac.compare_digest(self.plan_id, self.recompute_id()):
            raise PlanError("execution plan digest mismatch")
        if self.kernel_abi <= 0 or not self.kernel_name or not self.model_hash or not self.proof_hash:
            raise PlanError("execution plan is missing identity or proof fields")
        if self.memory_bytes < 0 or self.estimated_energy < 0 or self.calibration_mse < 0:
            raise PlanError("execution plan contains negative resource or quality values")
        if self.deadline_ns and (now_ns if now_ns is not None else time.monotonic_ns()) > self.deadline_ns:
            raise PlanError("execution plan deadline has expired")
        if self.thermal is Thermal.CRITICAL and self.core_policy is CorePolicy.BIG_ONLY:
            raise PlanError("critical thermal state forbids big-only execution")

    def to_json(self) -> str:
        self.verify()
        return json.dumps({**self.body(), "plan_id": self.plan_id}, sort_keys=True, indent=2)

    def native_request_fields(self) -> dict[str, int]:
        core_ids = {CorePolicy.ANY: 0, CorePolicy.BIG_ONLY: 1, CorePolicy.LITTLE_ONLY: 2, CorePolicy.BIG_PREFERRED: 3, CorePolicy.LITTLE_PREFERRED: 4}
        priority_ids = {Priority.BACKGROUND: 0, Priority.THROUGHPUT: 1, Priority.LATENCY: 2, Priority.INTERACTIVE: 3}
        return {"core_class": core_ids[self.core_policy], "priority": priority_ids[self.priority], "deadline_ns": self.deadline_ns}

    def same_selected_execution(self, other: "ExecutionPlan") -> bool:
        return self.model_hash == other.model_hash and self.kernel_name == other.kernel_name and self.precision is other.precision and self.kernel_abi == other.kernel_abi and self.proof_hash == other.proof_hash and self.calibration_mse == other.calibration_mse and self.memory_bytes == other.memory_bytes and self.estimated_energy == other.estimated_energy and self.core_policy is other.core_policy and self.priority is other.priority and self.thermal is other.thermal


@dataclass(frozen=True)
class ExecutionReceipt:
    plan_id: str
    model_hash: str
    selected_kernel: str
    selected_precision: Precision
    selected_core: CorePolicy
    measured_mse: float
    measured_memory_bytes: int
    measured_energy: float
    success: bool
    timestamp_ns: int

    def verify_against(self, plan: ExecutionPlan) -> None:
        plan.verify(now_ns=self.timestamp_ns)
        if self.plan_id != plan.plan_id or self.model_hash != plan.model_hash:
            raise PlanError("receipt is bound to a different plan or model")
        if self.selected_kernel != plan.kernel_name or self.selected_precision is not plan.precision:
            raise PlanError("receipt selected kernel does not match plan")
        if self.selected_core not in {plan.core_policy, CorePolicy.ANY}:
            raise PlanError("receipt violated core policy")
        if self.measured_mse > plan.calibration_mse + 1e-12:
            raise PlanError("observed quality is worse than the proof bound")
        if self.measured_memory_bytes > plan.memory_bytes:
            raise PlanError("observed memory exceeded the plan bound")
        if self.measured_energy > plan.estimated_energy + 1e-12:
            raise PlanError("observed energy exceeded the plan bound")


class PlanCompiler:
    def __init__(self, *, kernel_abi: int = 1):
        self.kernel_abi = kernel_abi

    @staticmethod
    def choose_core(priority: Priority, thermal: Thermal, allowed: tuple[CorePolicy, ...]) -> CorePolicy:
        if thermal is Thermal.CRITICAL:
            preferred = CorePolicy.LITTLE_PREFERRED
        elif priority is Priority.INTERACTIVE or priority is Priority.LATENCY:
            preferred = CorePolicy.BIG_PREFERRED
        else:
            preferred = CorePolicy.LITTLE_PREFERRED
        if preferred in allowed:
            return preferred
        if CorePolicy.ANY in allowed:
            return CorePolicy.ANY
        raise PlanError("no core policy is compatible with constraints")

    def compile(self, *, model_hash: str, candidates: Iterable[KernelCandidate], constraints: PlanConstraints, metadata: dict[str, Any] | None = None) -> ExecutionPlan:
        if not model_hash:
            raise PlanError("model hash is required")
        if constraints.required_abi != self.kernel_abi:
            raise PlanError("requested ABI is not supported by this compiler")
        if constraints.memory_budget_bytes <= 0 or constraints.energy_budget < 0:
            raise PlanError("resource constraints are invalid")
        core = self.choose_core(constraints.priority, constraints.thermal, constraints.allowed_cores)
        ordered = list(candidates)
        accepted: list[KernelCandidate] = []
        for candidate in ordered:
            if candidate.abi_version != self.kernel_abi:
                continue
            if candidate.calibration_mse > constraints.max_mse or not candidate.passes_quality_gate():
                continue
            if candidate.memory_bytes > constraints.memory_budget_bytes or candidate.estimated_energy > constraints.energy_budget:
                continue
            if core not in candidate.supported_cores and CorePolicy.ANY not in candidate.supported_cores:
                continue
            if constraints.thermal is Thermal.CRITICAL and CorePolicy.BIG_ONLY in candidate.supported_cores and CorePolicy.LITTLE_PREFERRED not in candidate.supported_cores:
                continue
            accepted.append(candidate)
        if not accepted:
            raise PlanError("no kernel candidate satisfies quality, resource, ABI, and thermal gates")
        selected = accepted[0]
        if not constraints.allow_precision_fallback and selected.precision is not Precision.INT4:
            raise PlanError("requested precision fallback but selected candidate is not int4")
        fallback_names = tuple(candidate.name for candidate in accepted[1:])
        plan_body = {
            "schema": "holy-fitra.execution-plan/v1",
            "model_hash": model_hash,
            "kernel_name": selected.name,
            "precision": selected.precision.value,
            "kernel_abi": selected.abi_version,
            "proof_hash": selected.proof_hash,
            "calibration_mse": selected.calibration_mse,
            "memory_bytes": selected.memory_bytes,
            "estimated_energy": selected.estimated_energy,
            "core_policy": core.value,
            "priority": constraints.priority.value,
            "thermal": constraints.thermal.value,
            "deadline_ns": constraints.deadline_ns,
            "fallbacks": list(fallback_names),
            "metadata": metadata or {},
        }
        canonical = json.dumps(plan_body, sort_keys=True, separators=(",", ":"), default=str)
        plan_id = hashlib.sha256(canonical.encode()).hexdigest()
        plan = ExecutionPlan(
            schema=plan_body["schema"], plan_id=plan_id, model_hash=model_hash,
            kernel_name=selected.name, precision=selected.precision, kernel_abi=selected.abi_version,
            proof_hash=selected.proof_hash, calibration_mse=selected.calibration_mse,
            memory_bytes=selected.memory_bytes, estimated_energy=selected.estimated_energy,
            core_policy=core, priority=constraints.priority, thermal=constraints.thermal,
            deadline_ns=constraints.deadline_ns, fallbacks=fallback_names, metadata=metadata or {},
        )
        plan.verify()
        return plan


class VerifiedPlanCache:
    def __init__(self) -> None:
        self._plans: dict[str, ExecutionPlan] = {}

    def put(self, plan: ExecutionPlan) -> str:
        plan.verify()
        key = plan.plan_id
        existing = self._plans.get(key)
        if existing is not None and existing.canonical() != plan.canonical():
            raise PlanError("plan identity collision")
        self._plans[key] = plan
        return key

    def get(self, plan_id: str) -> ExecutionPlan:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise PlanError("execution plan is not cached")
        plan.verify()
        return plan


def demo() -> dict[str, Any]:
    candidates = [
        KernelCandidate("nibbleflow.int4.neon", Precision.INT4, 1, 0.058, 0.05, 12288, 0.8, proof_hash="proof-int4"),
        KernelCandidate("nibbleflow.int8.neon", Precision.INT8, 1, 0.006, 0.05, 17408, 1.2, proof_hash="proof-int8"),
        KernelCandidate("nibbleflow.f16.neon", Precision.F16, 1, 0.0, 0.05, 65536, 2.4, proof_hash="proof-f16"),
    ]
    compiler = PlanCompiler()
    plan = compiler.compile(model_hash="model-demo", candidates=candidates, constraints=PlanConstraints(max_mse=0.05, memory_budget_bytes=20000, energy_budget=2.0), metadata={"shape": [4096, 4096], "group_size": 32})
    cache = VerifiedPlanCache()
    cache.put(plan)
    receipt = ExecutionReceipt(plan.plan_id, plan.model_hash, plan.kernel_name, plan.precision, plan.core_policy, 0.006, plan.memory_bytes, 1.1, True, time.monotonic_ns())
    receipt.verify_against(plan)
    return {"plan_id": plan.plan_id, "precision": plan.precision.value, "kernel": plan.kernel_name, "core_policy": plan.core_policy.value, "native_request": plan.native_request_fields(), "fallbacks": list(plan.fallbacks), "cache_verified": cache.get(plan.plan_id).plan_id == plan.plan_id, "receipt_verified": True}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, sort_keys=True))
