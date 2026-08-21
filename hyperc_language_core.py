#!/usr/bin/env python3
"""HyperC semantic-kernel frontend prototype.

This is deliberately dependency-free. It parses a useful subset of HyperC
source into the existing Tensor-Effect HyperIR and produces structured
compile diagnostics instead of silently accepting invalid programs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from hyperc_hyperir import (
    Capability,
    CapabilityPolicy,
    HyperIR,
    HyperIRError,
    Operation,
    TensorType,
    Value,
)


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    line: int = 0


@dataclass(frozen=True)
class Budget:
    resource: str
    limit: float
    unit: str


@dataclass(frozen=True)
class FunctionDecl:
    name: str
    parameters: tuple[tuple[str, str], ...]
    return_type: str
    effects: tuple[str, ...] = ()
    budgets: tuple[Budget, ...] = ()


@dataclass
class HyperModule:
    name: str
    functions: dict[str, FunctionDecl] = field(default_factory=dict)
    ir: HyperIR | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(diagnostic.severity == "error" for diagnostic in self.diagnostics)

    def compile_plan(self) -> dict[str, Any]:
        if self.ir is None:
            raise HyperIRError("module has not been lowered")
        return {
            "module": self.name,
            "valid": self.valid,
            "diagnostics": [diagnostic.__dict__ for diagnostic in self.diagnostics],
            "hyperir_digest": self.ir.digest(),
            "lowered_plan": self.ir.lower_plan(),
            "functions": {name: {"return_type": fn.return_type, "effects": list(fn.effects), "budgets": [budget.__dict__ for budget in fn.budgets]} for name, fn in self.functions.items()},
        }


_TENSOR_RE = re.compile(r"Tensor\s*<\s*\[([^]]+)\]\s*,\s*(f32|f16|bf16|int8|int4)(?:\s*,\s*device\s*=\s*([A-Za-z0-9_.-]+))?(?:\s*,\s*layout\s*=\s*([A-Za-z0-9_.-]+))?\s*>")
_FN_RE = re.compile(r"fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*->\s*([A-Za-z_][A-Za-z0-9_<>,\[\]. =-]*)")
_BUDGET_RE = re.compile(r"budget\s+([A-Za-z_][A-Za-z0-9_]*)\s*<=\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)")
_CAP_RE = re.compile(r"(allow|deny)\s+([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)(?:\(\"([^\"]*)\"\))?")


def _parse_shape(raw: str) -> tuple[int | str, ...]:
    shape: list[int | str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            raise HyperIRError("empty tensor dimension")
        shape.append(int(item) if item.isdigit() else item)
    return tuple(shape)


def _parse_tensor(raw: str) -> TensorType:
    match = _TENSOR_RE.fullmatch(raw.strip())
    if not match:
        raise HyperIRError(f"invalid tensor type: {raw}")
    shape, dtype, device, layout = match.groups()
    return TensorType(_parse_shape(shape), dtype, device or "cpu", layout or "row_major")


def _canonical_scope(scope: str) -> str:
    if not scope or "\x00" in scope or not scope.startswith("/"):
        raise HyperIRError("capability scope must be an absolute path without NUL")
    normalized = str(PurePosixPath(scope))
    if scope.endswith("/") and normalized != "/":
        normalized += "/"
    if normalized == "/.." or normalized.startswith("/../"):
        raise HyperIRError("capability scope escapes root")
    return normalized


def parse_module(source: str) -> HyperModule:
    lines = source.splitlines()
    module_name = "anonymous"
    module = HyperModule(module_name)
    ir = HyperIR(module_name)
    active_policy: CapabilityPolicy | None = None
    policy_name: str | None = None
    current_function: FunctionDecl | None = None
    tensor_values: dict[str, Value] = {}

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            if line.startswith("module "):
                module_name = line[len("module "):].strip()
                module.name = module_name
                ir.name = module_name
                continue
            if line.startswith("capability "):
                policy_name = line[len("capability "):].split("{", 1)[0].strip()
                active_policy = CapabilityPolicy()
                ir.policies[policy_name] = active_policy
                continue
            cap_match = _CAP_RE.search(line)
            if cap_match and active_policy is not None and policy_name is not None:
                mode, resource, operation, scope = cap_match.groups()
                requested_scope = _canonical_scope(scope) if scope else "*"
                capability = Capability(resource, operation, requested_scope)
                (active_policy.allow if mode == "allow" else active_policy.deny).append(capability)
                continue
            if line == "}":
                active_policy = None
                policy_name = None
                current_function = None
                continue
            fn_match = _FN_RE.search(line)
            if fn_match:
                name, raw_params, return_type = fn_match.groups()
                parameters: list[tuple[str, str]] = []
                if raw_params.strip():
                    chunks: list[str] = []
                    current: list[str] = []
                    angle_depth = 0
                    for character in raw_params:
                        if character == "<":
                            angle_depth += 1
                        elif character == ">":
                            angle_depth -= 1
                        if character == "," and angle_depth == 0:
                            chunks.append("".join(current))
                            current = []
                        else:
                            current.append(character)
                    if current:
                        chunks.append("".join(current))
                    for parameter in chunks:
                        parameter = parameter.strip()
                        if ":" not in parameter:
                            raise HyperIRError(f"parameter requires name: type: {parameter}")
                        param_name, param_type = parameter.split(":", 1)
                        parameters.append((param_name.strip(), param_type.strip()))
                        if param_type.strip().startswith("Tensor"):
                            tensor = _parse_tensor(param_type.strip())
                            value = Value(param_name.strip(), "Tensor", tensor=tensor)
                            ir.add_value(value)
                            tensor_values[param_name.strip()] = value
                current_function = FunctionDecl(name, tuple(parameters), return_type.strip())
                module.functions[name] = current_function
                continue
            budget_match = _BUDGET_RE.search(line)
            if budget_match and current_function is not None:
                resource, limit, unit = budget_match.groups()
                budget = Budget(resource, float(limit), unit)
                module.functions[current_function.name] = FunctionDecl(current_function.name, current_function.parameters, current_function.return_type, current_function.effects, current_function.budgets + (budget,))
                current_function = module.functions[current_function.name]
                continue
            tensor_match = re.match(r"(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(Tensor\s*<.*>)", line)
            if tensor_match:
                name, tensor_raw = tensor_match.groups()
                tensor = _parse_tensor(tensor_raw)
                value = Value(name, "Tensor", tensor=tensor)
                ir.add_value(value)
                tensor_values[name] = value
                continue
            matmul_match = re.match(r"(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*matmul\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", line)
            if matmul_match:
                output_name, left_name, right_name = matmul_match.groups()
                if left_name not in tensor_values or right_name not in tensor_values:
                    raise HyperIRError("matmul uses an unknown tensor")
                left = tensor_values[left_name].tensor
                right = tensor_values[right_name].tensor
                if left is None or right is None or len(left.shape) != 2 or len(right.shape) != 2 or left.shape[1] != right.shape[0]:
                    raise HyperIRError("matmul dimensions cannot be proven compatible")
                output_type = TensorType((left.shape[0], right.shape[1]), left.dtype, left.device, left.layout)
                output = Value(output_name, "Tensor", tensor=output_type)
                operation = Operation("matmul", (left_name, right_name), (output_name,), effects=frozenset())
                ir.add_operation(operation)
                ir.add_output_value(operation, output)
                tensor_values[output_name] = output
                continue
        except (HyperIRError, ValueError) as exc:
            module.diagnostics.append(Diagnostic("error", "HYPER" + str(line_number), str(exc), line_number))

    module.name = module_name
    module.ir = ir
    for error in ir.verify():
        module.diagnostics.append(Diagnostic("error", "HYPERIR", error))
    return module


def compile_source(source: str) -> dict[str, Any]:
    return parse_module(source).compile_plan()


def demo_source() -> str:
    return '''
module demo.mobile
capability PublicRead {
    allow files.read("/data/public/")
    deny files.write
}
fn infer(x: Tensor<[1, 64], f16, device=neon>) -> Tensor<[1, 64], f16> {
    budget memory <= 64 MiB
    let w: Tensor<[64, 64], int4, device=neon>
    let y: Tensor<[1, 64], f16, device=neon>
    let z = matmul(x, w)
}
'''


if __name__ == "__main__":
    print(json.dumps(compile_source(demo_source()), indent=2, sort_keys=True))
