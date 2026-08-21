#!/usr/bin/env python3
"""Deterministic deployment export and loading for compact Holy Fitra MLPs."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hyperc_nn import relu
from holyfitra_qat import QuantizationQualityGate, QuantizationSpec, QuantizedArray, quantization_quality, quantize_array

_MAGIC = b"HOLYFITRA\x01"
_PREFIX = struct.Struct("<Q")
_ARRAY_ORDER = ("hidden.weight", "hidden.bias", "output.weight", "output.bias")


@dataclass(frozen=True)
class DeploymentArtifact:
    path: str
    digest: str
    manifest: dict[str, Any]
    bytes_written: int


@dataclass(frozen=True)
class DeploymentBundle:
    manifest: dict[str, Any]
    arrays: dict[str, np.ndarray]
    digest: str

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        x = np.asarray(inputs, dtype=np.float32)
        dimensions = self.manifest["model"]["dimensions"]
        if x.ndim != 2 or x.shape[1] != dimensions["input_dim"]:
            raise ValueError("inputs must have shape [batch, input_dim]")
        hidden = np.maximum(x @ self.arrays["hidden.weight"] + self.arrays["hidden.bias"], 0.0)
        return np.ascontiguousarray(hidden @ self.arrays["output.weight"] + self.arrays["output.bias"], dtype=np.float32)


def export_mlp(model: Any, path: str | os.PathLike[str], *, weight_spec: QuantizationSpec, quality_gate: QuantizationQualityGate, metadata: dict[str, Any] | None = None) -> DeploymentArtifact:
    """Export a TrainableMLP or QuantizationAwareMLP as a canonical artifact."""
    base = getattr(model, "base_model", model)
    for name in ("hidden", "output", "input_dim", "hidden_dim", "output_dim"):
        if not hasattr(base, name):
            raise TypeError("model is not a supported Holy Fitra MLP")
    if not isinstance(weight_spec, QuantizationSpec) or not isinstance(quality_gate, QuantizationQualityGate):
        raise TypeError("weight_spec and quality_gate are required typed contracts")
    if metadata is not None:
        _ensure_json_value(metadata)
    quantized: dict[str, QuantizedArray] = {}
    original: dict[str, np.ndarray] = {
        "hidden.weight": np.asarray(base.hidden.weight.data, dtype=np.float32),
        "hidden.bias": np.asarray(base.hidden.bias.data, dtype=np.float32),
        "output.weight": np.asarray(base.output.weight.data, dtype=np.float32),
        "output.bias": np.asarray(base.output.bias.data, dtype=np.float32),
    }
    for name in ("hidden.weight", "output.weight"):
        item = quantize_array(original[name], weight_spec)
        quality_gate.enforce(original[name], item.dequantize())
        quantized[name] = item
    arrays: dict[str, np.ndarray] = {
        "hidden.weight": quantized["hidden.weight"].packed,
        "hidden.bias": np.ascontiguousarray(original["hidden.bias"], dtype="<f4"),
        "output.weight": quantized["output.weight"].packed,
        "output.bias": np.ascontiguousarray(original["output.bias"], dtype="<f4"),
    }
    array_manifest: list[dict[str, Any]] = []
    for name in _ARRAY_ORDER:
        array = arrays[name]
        if name in quantized:
            item = quantized[name]
            array_manifest.append({"name": name, "dtype": np.dtype(array.dtype).str, "shape": list(item.logical_shape), "bytes": int(array.nbytes), "quantization": item.metadata()})
        else:
            array_manifest.append({"name": name, "dtype": np.dtype(array.dtype).str, "shape": list(array.shape), "bytes": int(array.nbytes), "quantization": None})
    manifest = {
        "format": "holyfitra.deployment",
        "version": 1,
        "model": {"type": "mlp", "dimensions": {"input_dim": int(base.input_dim), "hidden_dim": int(base.hidden_dim), "output_dim": int(base.output_dim)}},
        "quantization": {"bits": weight_spec.bits, "axis": weight_spec.axis, "symmetric": weight_spec.symmetric, "quality_gate": {"max_mse": quality_gate.max_mse, "max_abs_error": quality_gate.max_abs_error}},
        "arrays": array_manifest,
        "metadata": metadata or {},
    }
    payload = _encode(manifest, arrays)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return DeploymentArtifact(str(destination), hashlib.sha256(payload).hexdigest(), manifest, len(payload))


def load_deployment(path: str | os.PathLike[str]) -> DeploymentBundle:
    payload = Path(path).read_bytes()
    manifest, arrays = _decode(payload)
    return DeploymentBundle(manifest, arrays, hashlib.sha256(payload).hexdigest())


def _encode(manifest: dict[str, Any], arrays: dict[str, np.ndarray]) -> bytes:
    header = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    body = bytearray()
    body.extend(_MAGIC)
    body.extend(_PREFIX.pack(len(header)))
    body.extend(header)
    for name in _ARRAY_ORDER:
        body.extend(np.ascontiguousarray(arrays[name]).tobytes(order="C"))
    return bytes(body)


def _decode(payload: bytes) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if len(payload) < len(_MAGIC) + _PREFIX.size or payload[: len(_MAGIC)] != _MAGIC:
        raise ValueError("invalid Holy Fitra deployment magic")
    cursor = len(_MAGIC)
    header_size = _PREFIX.unpack_from(payload, cursor)[0]
    cursor += _PREFIX.size
    end_header = cursor + header_size
    if end_header > len(payload):
        raise ValueError("truncated deployment manifest")
    manifest = json.loads(payload[cursor:end_header].decode("utf-8"))
    _validate_manifest(manifest)
    cursor = end_header
    arrays: dict[str, np.ndarray] = {}
    for item in manifest["arrays"]:
        size = int(item["bytes"])
        end = cursor + size
        if end > len(payload):
            raise ValueError("truncated deployment array")
        dtype = np.dtype(item["dtype"])
        raw = np.frombuffer(payload[cursor:end], dtype=dtype).copy()
        shape = tuple(int(value) for value in item["shape"])
        if raw.size != int(np.prod(shape, dtype=np.int64)) and item["quantization"] is None:
            raise ValueError("deployment array shape does not match payload")
        if item["quantization"] is not None:
            quant = item["quantization"]
            logical_count = int(np.prod(shape, dtype=np.int64))
            from holyfitra_qat import _unpack_values
            unpacked = _unpack_values(raw, logical_count, int(quant["bits"]))
            scales = np.asarray(quant["scales"], dtype=np.float32) if "scales" in quant else None
            if scales is None:
                raise ValueError("quantized array metadata lacks scales")
            arrays[item["name"]] = np.ascontiguousarray(unpacked.reshape(shape).astype(np.float32) * scales, dtype=np.float32)
        else:
            arrays[item["name"]] = np.ascontiguousarray(raw.reshape(shape), dtype=np.float32)
        cursor = end
    if cursor != len(payload):
        raise ValueError("unexpected trailing deployment bytes")
    return manifest, arrays


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("format") != "holyfitra.deployment" or manifest.get("version") != 1:
        raise ValueError("unsupported deployment format")
    if manifest.get("model", {}).get("type") != "mlp":
        raise ValueError("unsupported deployment model type")
    dimensions = manifest["model"].get("dimensions", {})
    if any(int(dimensions.get(key, 0)) <= 0 for key in ("input_dim", "hidden_dim", "output_dim")):
        raise ValueError("invalid deployment dimensions")
    arrays = manifest.get("arrays")
    if [item.get("name") for item in arrays or []] != list(_ARRAY_ORDER):
        raise ValueError("deployment arrays are not in canonical order")


def _ensure_json_value(value: Any) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as error:
        raise ValueError("deployment metadata must be JSON-serializable") from error


__all__ = ["DeploymentArtifact", "DeploymentBundle", "export_mlp", "load_deployment"]
