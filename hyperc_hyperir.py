#!/usr/bin/env python3
"""HyperC Tensor-Effect HyperIR prototype.

This module is intentionally small but concrete. It is the first unified
contract shared by tensor compilation, quantization manifests, cache effects,
and AI safety policies.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class HyperIRError(ValueError):
    pass


HYPERIR_TEXT_FORMAT = "holyfitra.hyperir"
HYPERIR_TEXT_VERSION = 1
_VERIFY_CACHE_LIMIT = 64
_VERIFY_CACHE: OrderedDict[str, tuple[tuple[str, ...], tuple[bool, ...]]] = OrderedDict()
_VERIFY_CACHE_HITS = 0
_VERIFY_CACHE_MISSES = 0


def clear_verifier_cache() -> None:
    global _VERIFY_CACHE_HITS, _VERIFY_CACHE_MISSES
    _VERIFY_CACHE.clear()
    _VERIFY_CACHE_HITS = 0
    _VERIFY_CACHE_MISSES = 0


def verifier_cache_info() -> dict[str, int]:
    return {"size": len(_VERIFY_CACHE), "limit": _VERIFY_CACHE_LIMIT, "hits": _VERIFY_CACHE_HITS, "misses": _VERIFY_CACHE_MISSES}


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
        if not self.shape or any((not isinstance(dim, (int, str)) or isinstance(dim, bool) or (isinstance(dim, int) and dim <= 0) or (isinstance(dim, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dim) is None)) for dim in self.shape):
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
        return self.dtype == other.dtype and self.device == other.device and self.layout == other.layout

    def jsonable(self) -> dict[str, Any]:
        return {"shape": list(self.shape), "dtype": self.dtype, "device": self.device, "layout": self.layout}


@dataclass(frozen=True)
class EvidenceType:
    kind: EvidenceKind
    payload_type: str
    confidence: float | None = None
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.payload_type or (self.confidence is not None and (not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0)):
            raise HyperIRError("invalid evidence type")
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

    def __post_init__(self) -> None:
        if not self.resource or not self.operation or not self.scope or "\x00" in self.resource + self.operation + self.scope:
            raise HyperIRError("invalid capability")

    def allows(self, requested: "Capability") -> bool:
        if self.resource != requested.resource or self.operation != requested.operation:
            return False
        if self.scope == "*":
            return True
        if self.scope.endswith("*"):
            prefix = self.scope[:-1]
            return requested.scope.startswith(prefix)
        if self.scope.endswith("/"):
            return requested.scope.startswith(self.scope)
        return requested.scope == self.scope


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

    def __post_init__(self) -> None:
        if not self.model or not self.calibration_sha256 or not self.kernel or not self.device or self.precision not in {"int4", "int8", "f16", "f32"}:
            raise HyperIRError("invalid quantization proof identity")
        if not isinstance(self.group_size, int) or isinstance(self.group_size, bool) or self.group_size <= 0:
            raise HyperIRError("group_size must be a positive integer")
        numeric_values = (self.layer_error, self.max_layer_error, self.task_score, self.baseline_task_score, self.minimum_task_score)
        if any(value is not None and (not math.isfinite(value) or value < 0.0) for value in numeric_values):
            raise HyperIRError("quantization proof metrics must be finite and non-negative")

    def verify(self) -> bool:
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
        global _VERIFY_CACHE_HITS, _VERIFY_CACHE_MISSES
        digest = self.digest()
        cached = _VERIFY_CACHE.get(digest)
        if cached is not None:
            _VERIFY_CACHE.move_to_end(digest)
            _VERIFY_CACHE_HITS += 1
            errors, proof_states = cached
            for proof, verified in zip(self.quantization_proofs, proof_states):
                proof.verified = verified
            return list(errors)
        _VERIFY_CACHE_MISSES += 1
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
        result = (tuple(errors), tuple(proof.verified for proof in self.quantization_proofs))
        _VERIFY_CACHE[digest] = result
        _VERIFY_CACHE.move_to_end(digest)
        while len(_VERIFY_CACHE) > _VERIFY_CACHE_LIMIT:
            _VERIFY_CACHE.popitem(last=False)
        return list(errors)

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
            if q.shape[0] != k.shape[0] or q.shape[1] != k.shape[1] or q.shape[3] != k.shape[3] or k.shape[2] != v.shape[2] or k.shape[3] != v.shape[3]:
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
        try:
            payload = json.dumps(self.to_jsonable(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise HyperIRError("HyperIR contains non-canonical JSON data") from error
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_jsonable(self) -> dict[str, Any]:
        def evidence_json(evidence: EvidenceType | None) -> dict[str, Any] | None:
            if evidence is None:
                return None
            return {
                "kind": evidence.kind.value,
                "payload_type": evidence.payload_type,
                "confidence": evidence.confidence,
                "sources": list(evidence.sources),
            }

        def value_json(value: Value) -> dict[str, Any]:
            data = {"name": value.name, "type_name": value.type_name, "resource": value.resource}
            data["tensor"] = value.tensor.jsonable() if value.tensor else None
            data["evidence"] = evidence_json(value.evidence)
            return data

        def policy_json(policy: CapabilityPolicy) -> dict[str, Any]:
            def capability_json(capability: Capability) -> dict[str, str]:
                return {"resource": capability.resource, "operation": capability.operation, "scope": capability.scope}
            return {
                "allow": [capability_json(item) for item in policy.allow],
                "deny": [capability_json(item) for item in policy.deny],
            }

        return {
            "name": self.name,
            "values": {name: value_json(value) for name, value in self.values.items()},
            "operations": [{"op": op.op, "inputs": list(op.inputs), "outputs": list(op.outputs), "attrs": op.attrs, "effects": sorted(op.effects)} for op in self.operations],
            "policies": {name: policy_json(policy) for name, policy in sorted(self.policies.items())},
            "lowered_plan": self.lower_plan(),
            "quantization_proofs": [
                {
                    "model": proof.model,
                    "calibration_sha256": proof.calibration_sha256,
                    "precision": proof.precision,
                    "group_size": proof.group_size,
                    "layer_error": proof.layer_error,
                    "task_score": proof.task_score,
                    "baseline_task_score": proof.baseline_task_score,
                    "max_layer_error": proof.max_layer_error,
                    "minimum_task_score": proof.minimum_task_score,
                    "kernel": proof.kernel,
                    "device": proof.device,
                }
                for proof in self.quantization_proofs
            ],
        }

    def to_text(self) -> str:
        envelope = {"format": HYPERIR_TEXT_FORMAT, "version": HYPERIR_TEXT_VERSION, "ir": self.to_jsonable()}
        return json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_text(cls, text: str) -> "HyperIR":
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HyperIRError(f"invalid HyperIR text: {exc.msg}") from exc
        if not isinstance(envelope, dict) or envelope.get("format") != HYPERIR_TEXT_FORMAT or envelope.get("version") != HYPERIR_TEXT_VERSION:
            raise HyperIRError("unsupported HyperIR text format or version")
        data = envelope.get("ir")
        if not isinstance(data, dict):
            raise HyperIRError("HyperIR text is missing its ir object")
        try:
            ir = cls(str(data["name"]))
            parsed_values: dict[str, Value] = {}
            for name, value_data in data.get("values", {}).items():
                tensor_data = value_data.get("tensor")
                tensor = TensorType(tuple(tensor_data["shape"]), tensor_data["dtype"], tensor_data["device"], tensor_data["layout"]) if tensor_data else None
                evidence_data = value_data.get("evidence")
                evidence = None
                if evidence_data:
                    evidence = EvidenceType(EvidenceKind(evidence_data["kind"]), evidence_data["payload_type"], evidence_data.get("confidence"), tuple(evidence_data.get("sources", [])))
                parsed_values[str(name)] = Value(str(name), value_data["type_name"], tensor, evidence, value_data.get("resource"))
            operation_data_list = data.get("operations", [])
            produced_names = {output for operation_data in operation_data_list for output in operation_data.get("outputs", [])}
            for name, value in parsed_values.items():
                if name not in produced_names:
                    ir.add_value(value)
            for name, policy_data in data.get("policies", {}).items():
                allow = [Capability(item["resource"], item["operation"], item.get("scope", "*")) for item in policy_data.get("allow", [])]
                deny = [Capability(item["resource"], item["operation"], item.get("scope", "*")) for item in policy_data.get("deny", [])]
                ir.policies[str(name)] = CapabilityPolicy(allow, deny)
            for operation_data in operation_data_list:
                operation = Operation(operation_data["op"], tuple(operation_data.get("inputs", [])), tuple(operation_data.get("outputs", [])), dict(operation_data.get("attrs", {})), frozenset(operation_data.get("effects", [])))
                ir.add_operation(operation)
                for output in operation.outputs:
                    if output in parsed_values:
                        ir.add_output_value(operation, parsed_values[output])
            ir.quantization_proofs = [QuantizationProof(**proof_data) for proof_data in data.get("quantization_proofs", [])]
        except (AttributeError, KeyError, TypeError, ValueError, HyperIRError) as exc:
            raise HyperIRError(f"invalid HyperIR object: {exc}") from exc
        return ir

    @classmethod
    def read_text(cls, path: Path) -> "HyperIR":
        return cls.from_text(path.read_text(encoding="utf-8"))

    def write_text(self, path: Path) -> None:
        path.write_text(self.to_text(), encoding="utf-8")

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_jsonable(), indent=2, sort_keys=True, allow_nan=False) + "\n")


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
