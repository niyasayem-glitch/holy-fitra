#!/usr/bin/env python3
"""HyperC Tensor-Effect HyperIR prototype.

This module is intentionally small but concrete. It is the first unified
contract shared by tensor compilation, quantization manifests, cache effects,
and AI safety policies.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class HyperIRError(ValueError):
    pass


class EvidenceKind(str, Enum):
    PREDICTION = "prediction"
    CLAIM = "claim"
    FACT = "fact"


@dataclass(frozen=True)
class TensorType:
    shape: tuple[int | str, ...]
    dtype: str = "f32"
    device: str = "cpu"
    layout: str = "row_major"

    def __post_init__(self) -> None:
        if not self.shape or any(isinstance(dim, int) and dim <= 0 for dim in self.shape):
            raise HyperIRError(f"invalid tensor shape: {self.shape}")
        if self.dtype not in {"f32", "f16", "bf16", "int8", "int4"}:
            raise HyperIRError(f"unsupported dtype: {self.dtype}")
        if self.device not in {"cpu", "android.arm64", "neon", "gpu", "npu"}:
            raise HyperIRError(f"unsupported device: {self.device}")

    def compatible(self, other: "TensorType") -> bool:
        if len(self.shape) != len(other.shape):
            return False
        for left, right in zip(self.shape, other.shape):
            if isinstance(left, int) and isinstance(right, int) and left != right:
                return False
        return self.device == other.device and self.layout == other.layout

    def jsonable(self) -> dict[str, Any]:
        return {"shape": list(self.shape), "dtype": self.dtype, "device": self.device, "layout": self.layout}


@dataclass(frozen=True)
class EvidenceType:
    kind: EvidenceKind
    payload_type: str
    confidence: float | None = None
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise HyperIRError("confidence must be between 0 and 1")
        if self.kind is EvidenceKind.FACT and not self.sources:
            raise HyperIRError("a Fact requires at least one source")

    def can_flow_to(self, target: "EvidenceType") -> bool:
        order = {EvidenceKind.PREDICTION: 0, EvidenceKind.CLAIM: 1, EvidenceKind.FACT: 2}
        return self.payload_type == target.payload_type and order[self.kind] >= order[target.kind]


@dataclass(frozen=True)
class Capability:
    resource: str
    operation: str
    scope: str = "*"

    def allows(self, requested: "Capability") -> bool:
        if self.resource != requested.resource or self.operation != requested.operation:
            return False
        if self.scope == "*":
            return True
        return requested.scope == self.scope or requested.scope.startswith(self.scope.rstrip("*") )


@dataclass
class CapabilityPolicy:
    allow: list[Capability] = field(default_factory=list)
    deny: list[Capability] = field(default_factory=list)

    def authorize(self, requested: Capability) -> bool:
        if any(rule.allows(requested) for rule in self.deny):
            return False
        return any(rule.allows(requested) for rule in self.allow)


@dataclass(frozen=True)
class Value:
    name: str
    type_name: str
    tensor: TensorType | None = None
    evidence: EvidenceType | None = None
    resource: str | None = None


@dataclass
class Operation:
    op: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    attrs: dict[str, Any] = field(default_factory=dict)
    effects: frozenset[str] = frozenset()


@dataclass
class QuantizationProof:
    model: str
    calibration_sha256: str
    precision: str
    group_size: int
    layer_error: float
    task_score: float | None
    baseline_task_score: float | None
    max_layer_error: float
    minimum_task_score: float | None
    kernel: str
    device: str
    verified: bool = False

    def verify(self) -> bool:
        if self.precision not in {"int4", "int8", "f16", "f32"}:
            raise HyperIRError(f"unsupported proof precision: {self.precision}")
        if self.group_size <= 0:
            raise HyperIRError("group_size must be positive")
        if self.layer_error > self.max_layer_error:
            self.verified = False
            return False
        if self.minimum_task_score is not None:
            if self.task_score is None or self.task_score < self.minimum_task_score:
                self.verified = False
                return False
        self.verified = True
        return True


@dataclass
class HyperIR:
    name: str
    values: dict[str, Value] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)
    policies: dict[str, CapabilityPolicy] = field(default_factory=dict)
    quantization_proofs: list[QuantizationProof] = field(default_factory=list)

    def add_value(self, value: Value) -> None:
        if value.name in self.values:
            raise HyperIRError(f"duplicate value: {value.name}")
        self.values[value.name] = value

    def add_operation(self, operation: Operation) -> None:
        for name in operation.inputs:
            if name not in self.values:
                raise HyperIRError(f"unknown input {name} for {operation.op}")
        for name in operation.outputs:
            if name in self.values:
                raise HyperIRError(f"duplicate output {name} for {operation.op}")
        self.operations.append(operation)
        # Output contracts are added by add_output_value, keeping the graph
        # construction explicit and preventing implicit type invention.

    def add_output_value(self, operation: Operation, value: Value) -> None:
        if value.name not in operation.outputs:
            raise HyperIRError(f"{value.name} is not an output of {operation.op}")
        if value.name not in self.values:
            self.add_value(value)

    def verify(self) -> list[str]:
        errors: list[str] = []
        cache_state: dict[str, str] = {}
        for index, operation in enumerate(self.operations):
            try:
                inputs = [self.values[name] for name in operation.inputs]
                outputs = [self.values[name] for name in operation.outputs]
                self._verify_operation(operation, inputs, outputs, cache_state)
            except HyperIRError as exc:
                errors.append(f"op {index} ({operation.op}): {exc}")
        for proof in self.quantization_proofs:
            if not proof.verify():
                errors.append(f"quantization proof failed: {proof.model}")
        return errors

    def _verify_operation(self, op: Operation, inputs: list[Value], outputs: list[Value], cache_state: dict[str, str]) -> None:
        if op.op in {"matmul", "linear"}:
            if len(inputs) != 2 or len(outputs) != 1 or not inputs[0].tensor or not inputs[1].tensor or not outputs[0].tensor:
                raise HyperIRError("matmul requires two tensor inputs and one tensor output")
            left, right, result = inputs[0].tensor, inputs[1].tensor, outputs[0].tensor
            if len(left.shape) != 2 or len(right.shape) != 2 or left.shape[1] != right.shape[0]:
                raise HyperIRError(f"incompatible matmul shapes: {left.shape} x {right.shape}")
            expected = (left.shape[0], right.shape[1])
            if result.shape != expected:
                raise HyperIRError(f"matmul output {result.shape} != {expected}")
            if left.device != right.device or result.device != left.device:
                raise HyperIRError("matmul tensors must share a device")
            return
        if op.op == "add":
            if len(inputs) != 2 or len(outputs) != 1 or not inputs[0].tensor or not inputs[1].tensor or not outputs[0].tensor:
                raise HyperIRError("add requires tensor inputs and output")
            if not inputs[0].tensor.compatible(inputs[1].tensor) or not inputs[0].tensor.compatible(outputs[0].tensor):
                raise HyperIRError("add tensor contracts are incompatible")
            return
        if op.op == "attention":
            if len(inputs) != 3 or len(outputs) != 1 or any(value.tensor is None for value in inputs + outputs):
                raise HyperIRError("attention requires q, k, v tensors and one output")
            q, k, v, result = [value.tensor for value in inputs + outputs]
            if len(q.shape) != 4 or len(k.shape) != 4 or len(v.shape) != 4 or len(result.shape) != 4:
                raise HyperIRError("attention tensors must be rank-4")
            if q.shape[0] != k.shape[0] or q.shape[1] != k.shape[1] or k.shape[2] != v.shape[2] or k.shape[3] != v.shape[3]:
                raise HyperIRError("attention head and sequence dimensions disagree")
            if result.shape != q.shape:
                raise HyperIRError(f"attention output {result.shape} != q shape {q.shape}")
            return
        if op.op == "cache_begin":
            cache_id = str(op.attrs.get("cache_id", ""))
            if not cache_id or cache_state.get(cache_id) not in (None, "committed"):
                raise HyperIRError("cache begin requires an inactive or committed cache")
            cache_state[cache_id] = "open"
            return
        if op.op == "cache_append":
            cache_id = str(op.attrs.get("cache_id", ""))
            if cache_state.get(cache_id) != "open":
                raise HyperIRError("cache append requires an open transaction")
            if "cache.write" not in op.effects:
                raise HyperIRError("cache append must declare cache.write effect")
            return
        if op.op in {"cache_commit", "cache_rollback"}:
            cache_id = str(op.attrs.get("cache_id", ""))
            if cache_state.get(cache_id) != "open":
                raise HyperIRError(f"{op.op} requires an open transaction")
            cache_state[cache_id] = "committed" if op.op == "cache_commit" else "rolled_back"
            return
        if op.op == "tool_propose":
            if len(outputs) != 1 or outputs[0].evidence is None or outputs[0].evidence.kind is not EvidenceKind.PREDICTION:
                raise HyperIRError("tool proposal must output Prediction evidence")
            if "tool.propose" not in op.effects:
                raise HyperIRError("tool proposal must declare tool.propose effect")
            policy_name = str(op.attrs.get("policy", ""))
            requested = Capability(str(op.attrs.get("resource", "")), str(op.attrs.get("operation", "")), str(op.attrs.get("scope", "*")))
            policy = self.policies.get(policy_name)
            if policy is None or not policy.authorize(requested):
                raise HyperIRError("tool proposal is not authorized")
            return
        if op.op == "verify_evidence":
            if len(inputs) != 1 or len(outputs) != 1 or inputs[0].evidence is None or outputs[0].evidence is None:
                raise HyperIRError("evidence verification requires evidence input and output")
            if not inputs[0].evidence.can_flow_to(outputs[0].evidence):
                raise HyperIRError("evidence cannot be upgraded without a valid verifier")
            if outputs[0].evidence.kind is not EvidenceKind.FACT:
                raise HyperIRError("verification must produce Fact evidence")
            return
        raise HyperIRError(f"unknown operation: {op.op}")

    def lower_plan(self) -> list[dict[str, Any]]:
        plan = []
        for operation in self.operations:
            kernel = operation.op
            if operation.op in {"matmul", "linear"}:
                output = self.values[operation.outputs[0]].tensor
                precision = output.dtype if output else "f32"
                device = output.device if output else "cpu"
                if precision == "int4" and device == "neon":
                    kernel = "neon.nibble_dot"
                elif precision in {"f16", "bf16"} and device == "neon":
                    kernel = "neon.f16_matmul"
                elif device == "npu":
                    kernel = "npu.delegate"
            plan.append({"op": operation.op, "kernel": kernel, "inputs": list(operation.inputs), "outputs": list(operation.outputs), "effects": sorted(operation.effects), "attrs": operation.attrs})
        return plan

    def digest(self) -> str:
        payload = json.dumps(self.to_jsonable(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_jsonable(self) -> dict[str, Any]:
        def value_json(value: Value) -> dict[str, Any]:
            data = {"name": value.name, "type_name": value.type_name, "resource": value.resource}
            data["tensor"] = value.tensor.jsonable() if value.tensor else None
            data["evidence"] = asdict(value.evidence) if value.evidence else None
            return data
        return {
            "name": self.name,
            "values": {name: value_json(value) for name, value in self.values.items()},
            "operations": [{"op": op.op, "inputs": list(op.inputs), "outputs": list(op.outputs), "attrs": op.attrs, "effects": sorted(op.effects)} for op in self.operations],
            "lowered_plan": self.lower_plan(),
            "quantization_proofs": [asdict(proof) for proof in self.quantization_proofs],
        }

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_jsonable(), indent=2, sort_keys=True, default=str))


def demo_ir() -> HyperIR:
    ir = HyperIR("mobile_decoder")
    ir.add_value(Value("x", "Tensor", TensorType((1, 64), "f16", "neon", "row_major")))
    ir.add_value(Value("w", "Weight", TensorType((64, 64), "int4", "neon", "row_major")))
    y = Value("y", "Tensor", TensorType((1, 64), "int4", "neon", "row_major"))
    matmul = Operation("matmul", ("x", "w"), ("y",), {"group_size": 4}, frozenset())
    ir.add_operation(matmul)
    ir.add_output_value(matmul, y)
    ir.policies["public_reader"] = CapabilityPolicy([Capability("files", "read", "/data/public/")], [Capability("files", "write", "*")])
    proposal = Value("proposal", "Prediction", evidence=EvidenceType(EvidenceKind.PREDICTION, "String", confidence=0.7))
    tool = Operation("tool_propose", (), ("proposal",), {"policy": "public_reader", "resource": "files", "operation": "read", "scope": "/data/public/report.txt"}, frozenset({"tool.propose"}))
    ir.add_operation(tool)
    ir.add_output_value(tool, proposal)
    ir.quantization_proofs.append(QuantizationProof("mobile_decoder", "calibration-demo", "int4", 4, 0.01, 0.95, 0.96, 0.02, 0.94, "neon.nibble_dot", "android.arm64"))
    return ir


if __name__ == "__main__":
    demo = demo_ir()
    print(json.dumps({"errors": demo.verify(), "digest": demo.digest(), "plan": demo.lower_plan()}, indent=2, sort_keys=True))
