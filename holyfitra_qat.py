#!/usr/bin/env python3
"""Quantization-aware training primitives for Holy Fitra.

The fake-quantization path uses a straight-through estimator: forward values
are quantized and dequantized, while backward gradients pass through unchanged.
Every quantized result carries explicit scale, error, and quality-gate metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hyperc_nn import Tensor, relu


class QuantizationQualityError(ValueError):
    pass


@dataclass(frozen=True)
class QuantizationSpec:
    bits: int = 8
    axis: int | None = None
    symmetric: bool = True

    def __post_init__(self) -> None:
        if self.bits not in {4, 8}:
            raise ValueError("quantization bits must be 4 or 8")
        if not self.symmetric:
            raise ValueError("only symmetric quantization is currently supported")

    @property
    def qmin(self) -> int:
        return -8 if self.bits == 4 else -128

    @property
    def qmax(self) -> int:
        return 7 if self.bits == 4 else 127


@dataclass(frozen=True)
class QuantizedArray:
    packed: np.ndarray
    scales: np.ndarray
    logical_shape: tuple[int, ...]
    bits: int
    axis: int | None
    max_abs_error: float
    mse: float

    @property
    def storage_bytes(self) -> int:
        return int(self.packed.nbytes + self.scales.nbytes)

    @property
    def compression_ratio(self) -> float:
        return float(np.prod(self.logical_shape, dtype=np.int64) * 4 / max(1, self.storage_bytes))

    def dequantize(self) -> np.ndarray:
        q = _unpack_values(self.packed, int(np.prod(self.logical_shape, dtype=np.int64)), self.bits).reshape(self.logical_shape)
        return np.ascontiguousarray(q.astype(np.float32) * self.scales, dtype=np.float32)

    def metadata(self) -> dict[str, Any]:
        return {
            "bits": self.bits,
            "axis": self.axis,
            "logical_shape": list(self.logical_shape),
            "scale_shape": list(self.scales.shape),
            "scales": self.scales.tolist(),
            "max_abs_error": self.max_abs_error,
            "mse": self.mse,
            "storage_bytes": self.storage_bytes,
        }


def quantize_array(values: np.ndarray, spec: QuantizationSpec) -> QuantizedArray:
    reference = np.ascontiguousarray(np.asarray(values, dtype=np.float32))
    if reference.ndim == 0 or not np.all(np.isfinite(reference)):
        raise ValueError("quantization values must be finite and non-scalar")
    axis = _normalize_axis(spec.axis, reference.ndim)
    if axis is None:
        scale = np.asarray(np.max(np.abs(reference)), dtype=np.float32) / max(abs(spec.qmin), abs(spec.qmax))
        scale = np.asarray(max(float(scale), np.finfo(np.float32).eps), dtype=np.float32)
    else:
        reduce_axes = tuple(index for index in range(reference.ndim) if index != axis)
        scale = np.max(np.abs(reference), axis=reduce_axes, keepdims=True).astype(np.float32) / max(abs(spec.qmin), abs(spec.qmax))
        scale = np.maximum(scale, np.finfo(np.float32).eps).astype(np.float32)
    quantized = np.clip(np.rint(reference / scale), spec.qmin, spec.qmax).astype(np.int8)
    reconstructed = np.ascontiguousarray(quantized.astype(np.float32) * scale, dtype=np.float32)
    error = reference - reconstructed
    return QuantizedArray(_pack_values(quantized, spec.bits), np.ascontiguousarray(scale, dtype=np.float32), tuple(reference.shape), spec.bits, axis, float(np.max(np.abs(error))), float(np.mean(error * error)))


def fake_quantize_array(values: np.ndarray, spec: QuantizationSpec) -> np.ndarray:
    return quantize_array(values, spec).dequantize()


def fake_quantize_tensor(value: Tensor, spec: QuantizationSpec) -> Tensor:
    """Fake-quantize forward data and use a straight-through backward pass."""
    quantized = fake_quantize_array(value.data, spec)
    output = Tensor(quantized, requires_grad=value.requires_grad, _parents=(value,))

    def backward() -> None:
        if value.requires_grad:
            value.grad += output.grad

    output._backward = backward
    return output


@dataclass(frozen=True)
class QuantizationQualityGate:
    max_mse: float
    max_abs_error: float

    def __post_init__(self) -> None:
        if self.max_mse < 0.0 or self.max_abs_error < 0.0:
            raise ValueError("quality limits must be non-negative")

    def enforce(self, reference: np.ndarray, candidate: np.ndarray) -> dict[str, float | bool]:
        quality = quantization_quality(reference, candidate)
        if quality["mse"] > self.max_mse or quality["max_abs_error"] > self.max_abs_error:
            raise QuantizationQualityError(f"quantization quality gate failed: mse={quality['mse']:.9g}, max_abs_error={quality['max_abs_error']:.9g}")
        return {**quality, "passed": True}


def quantization_quality(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    reference = np.asarray(reference, dtype=np.float32)
    candidate = np.asarray(candidate, dtype=np.float32)
    if reference.shape != candidate.shape or not np.all(np.isfinite(reference)) or not np.all(np.isfinite(candidate)):
        raise ValueError("quality arrays must have equal finite shapes")
    error = reference - candidate
    return {"mse": float(np.mean(error * error)), "max_abs_error": float(np.max(np.abs(error)) if error.size else 0.0)}


class QuantizationAwareMLP:
    """TrainableMLP-compatible wrapper with quality-gated fake-quantized weights."""

    def __init__(self, model: Any, *, weight_spec: QuantizationSpec | None = None, activation_spec: QuantizationSpec | None = None, quality_gate: QuantizationQualityGate | None = None):
        required = ("hidden", "output", "input_dim", "hidden_dim", "output_dim", "parameters", "forward_tensor", "predict", "state_dict", "load_state_dict")
        if any(not hasattr(model, name) for name in required):
            raise TypeError("model is not compatible with QuantizationAwareMLP")
        self.base_model = model
        self.hidden = model.hidden
        self.output = model.output
        self.input_dim = model.input_dim
        self.hidden_dim = model.hidden_dim
        self.output_dim = model.output_dim
        self.weight_spec = weight_spec or QuantizationSpec(bits=8, axis=0)
        self.activation_spec = activation_spec
        if quality_gate is None:
            raise ValueError("QuantizationAwareMLP requires an explicit quality_gate")
        self.quality_gate = quality_gate

    @property
    def parameters(self):
        return self.base_model.parameters

    @property
    def parameter_names(self):
        return self.base_model.parameter_names

    def forward_tensor(self, inputs: Tensor) -> Tensor:
        self.quality_gate.enforce(self.hidden.weight.data, fake_quantize_array(self.hidden.weight.data, self.weight_spec))
        self.quality_gate.enforce(self.output.weight.data, fake_quantize_array(self.output.weight.data, self.weight_spec))
        hidden_weight = fake_quantize_tensor(self.hidden.weight, self.weight_spec)
        output_weight = fake_quantize_tensor(self.output.weight, self.weight_spec)
        hidden = inputs @ hidden_weight + self.hidden.bias
        hidden = relu(hidden)
        if self.activation_spec is not None:
            hidden = fake_quantize_tensor(hidden, self.activation_spec)
        return hidden @ output_weight + self.output.bias

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        array = np.asarray(inputs, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.input_dim:
            raise ValueError("inputs must have shape [batch, input_dim]")
        return self.forward_tensor(Tensor(array)).data.copy()

    def state_dict(self):
        return self.base_model.state_dict()

    def load_state_dict(self, state):
        return self.base_model.load_state_dict(state)


def _normalize_axis(axis: int | None, ndim: int) -> int | None:
    if axis is None:
        return None
    normalized = axis + ndim if axis < 0 else axis
    if normalized < 0 or normalized >= ndim:
        raise ValueError("quantization axis is outside the array rank")
    return normalized


def _pack_values(values: np.ndarray, bits: int) -> np.ndarray:
    flat = np.asarray(values, dtype=np.int8).reshape(-1)
    if bits == 8:
        return np.ascontiguousarray(flat, dtype=np.int8)
    unsigned = (flat.astype(np.int16) & 0x0F).astype(np.uint8)
    if unsigned.size % 2:
        unsigned = np.concatenate((unsigned, np.zeros(1, dtype=np.uint8)))
    return np.ascontiguousarray(unsigned[0::2] | (unsigned[1::2] << 4), dtype=np.uint8)


def _unpack_values(packed: np.ndarray, count: int, bits: int) -> np.ndarray:
    if bits == 8:
        values = np.asarray(packed, dtype=np.int8).reshape(-1)
        if values.size != count:
            raise ValueError("int8 payload length does not match logical shape")
        return values.copy()
    raw = np.asarray(packed, dtype=np.uint8).reshape(-1)
    unpacked = np.empty(raw.size * 2, dtype=np.int8)
    low = raw & 0x0F
    high = raw >> 4
    unpacked[0::2] = np.where(low >= 8, low.astype(np.int16) - 16, low).astype(np.int8)
    unpacked[1::2] = np.where(high >= 8, high.astype(np.int16) - 16, high).astype(np.int8)
    if unpacked.size < count:
        raise ValueError("int4 payload is shorter than logical shape")
    return unpacked[:count]


__all__ = ["QuantizationAwareMLP", "QuantizationQualityError", "QuantizationQualityGate", "QuantizationSpec", "QuantizedArray", "fake_quantize_array", "fake_quantize_tensor", "quantization_quality", "quantize_array"]
