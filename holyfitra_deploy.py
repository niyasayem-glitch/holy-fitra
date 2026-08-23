#!/usr/bin/env python3
"""Deterministic deployment export and loading for compact Holy Fitra MLPs."""
from __future__ import annotations

import hashlib
import hmac
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
_AUTH_TRAILER = b"HFAUTH\x01"
_AUTH_TAG_BYTES = hashlib.sha256().digest_size
_MIN_SIGNING_KEY_BYTES = 16
MAX_DEPLOYMENT_BYTES = 64 * 1024 * 1024
MAX_DEPLOYMENT_DIMENSION = 8_192
MAX_DEPLOYMENT_PARAMETERS = 32_000_000
MAX_INFERENCE_BATCH_ROWS = 65_536
MAX_INFERENCE_INPUT_BYTES = 64 * 1024 * 1024


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
        if x.ndim != 2 or x.shape[0] <= 0 or x.shape[0] > MAX_INFERENCE_BATCH_ROWS or x.shape[1] != dimensions["input_dim"]:
            raise ValueError("inputs must have shape [batch, input_dim]")
        if x.nbytes > MAX_INFERENCE_INPUT_BYTES or not np.all(np.isfinite(x)):
            raise ValueError("deployment inputs must be finite and within the configured byte budget")
        with np.errstate(over="raise", invalid="raise"):
            try:
                hidden = np.maximum(x @ self.arrays["hidden.weight"] + self.arrays["hidden.bias"], 0.0)
                output = np.ascontiguousarray(hidden @ self.arrays["output.weight"] + self.arrays["output.bias"], dtype=np.float32)
            except FloatingPointError as error:
                raise ValueError("deployment inference produced a non-finite intermediate") from error
        if not np.all(np.isfinite(output)):
            raise ValueError("deployment inference produced non-finite output")
        return output


def export_mlp(model: Any, path: str | os.PathLike[str], *, weight_spec: QuantizationSpec, quality_gate: QuantizationQualityGate, signing_key: bytes, metadata: dict[str, Any] | None = None) -> DeploymentArtifact:
    """Export a TrainableMLP or QuantizationAwareMLP as a canonical artifact."""
    base = getattr(model, "base_model", model)
    for name in ("hidden", "output", "input_dim", "hidden_dim", "output_dim"):
        if not hasattr(base, name):
            raise TypeError("model is not a supported Holy Fitra MLP")
    if not isinstance(weight_spec, QuantizationSpec) or not isinstance(quality_gate, QuantizationQualityGate):
        raise TypeError("weight_spec and quality_gate are required typed contracts")
    key = _validated_signing_key(signing_key)
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
        "version": 2,
        "model": {"type": "mlp", "dimensions": {"input_dim": int(base.input_dim), "hidden_dim": int(base.hidden_dim), "output_dim": int(base.output_dim)}},
        "quantization": {"bits": weight_spec.bits, "axis": weight_spec.axis, "symmetric": weight_spec.symmetric, "quality_gate": {"max_mse": quality_gate.max_mse, "max_abs_error": quality_gate.max_abs_error}},
        "arrays": array_manifest,
        "metadata": metadata or {},
    }
    payload = _encode(manifest, arrays, key)
    if len(payload) > MAX_DEPLOYMENT_BYTES:
        raise ValueError("deployment artifact exceeds the configured byte budget")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return DeploymentArtifact(str(destination), hashlib.sha256(payload).hexdigest(), manifest, len(payload))


def load_deployment(path: str | os.PathLike[str], *, signing_key: bytes) -> DeploymentBundle:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_DEPLOYMENT_BYTES:
            raise ValueError("deployment artifact exceeds the configured byte budget")
        payload = source.read_bytes()
    except OSError as error:
        raise ValueError("deployment artifact cannot be read") from error
    return load_deployment_bytes(payload, signing_key=signing_key)


def load_deployment_bytes(payload: bytes | bytearray, *, signing_key: bytes) -> DeploymentBundle:
    """Verify and decode a bounded deployment payload already held in memory."""
    key = _validated_signing_key(signing_key)
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_DEPLOYMENT_BYTES:
        raise ValueError("deployment artifact exceeds the configured byte budget")
    payload = bytes(payload)
    manifest, arrays = _decode(payload, key)
    return DeploymentBundle(manifest, arrays, hashlib.sha256(payload).hexdigest())


def _encode(manifest: dict[str, Any], arrays: dict[str, np.ndarray], signing_key: bytes) -> bytes:
    header = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    body = bytearray()
    body.extend(_MAGIC)
    body.extend(_PREFIX.pack(len(header)))
    body.extend(header)
    for name in _ARRAY_ORDER:
        body.extend(np.ascontiguousarray(arrays[name]).tobytes(order="C"))
    unsigned = bytes(body)
    tag = hmac.new(signing_key, unsigned, hashlib.sha256).digest()
    return unsigned + _AUTH_TRAILER + tag


def _decode(payload: bytes, signing_key: bytes) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    minimum_size = len(_MAGIC) + _PREFIX.size + len(_AUTH_TRAILER) + _AUTH_TAG_BYTES
    if len(payload) < minimum_size or payload[-(_AUTH_TAG_BYTES + len(_AUTH_TRAILER)) : -_AUTH_TAG_BYTES] != _AUTH_TRAILER:
        raise ValueError("deployment authentication trailer is missing")
    unsigned = payload[: -(_AUTH_TAG_BYTES + len(_AUTH_TRAILER))]
    supplied_tag = payload[-_AUTH_TAG_BYTES:]
    expected_tag = hmac.new(signing_key, unsigned, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied_tag, expected_tag):
        raise ValueError("deployment authentication tag does not match")
    payload = unsigned
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
        try:
            dtype = np.dtype(item["dtype"])
        except TypeError as error:
            raise ValueError("deployment array dtype is invalid") from error
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
        if not np.all(np.isfinite(arrays[item["name"]])):
            raise ValueError("deployment contains non-finite model parameters")
        cursor = end
    if cursor != len(payload):
        raise ValueError("unexpected trailing deployment bytes")
    return manifest, arrays


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict) or manifest.get("format") != "holyfitra.deployment" or manifest.get("version") != 2:
        raise ValueError("unsupported deployment format")
    model = manifest.get("model")
    if not isinstance(model, dict) or model.get("type") != "mlp":
        raise ValueError("unsupported deployment model type")
    dimensions = model.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("deployment dimensions are missing")
    try:
        input_dim, hidden_dim, output_dim = (int(dimensions[key]) for key in ("input_dim", "hidden_dim", "output_dim"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid deployment dimensions") from error
    parameter_count = input_dim * hidden_dim + hidden_dim + hidden_dim * output_dim + output_dim
    if min(input_dim, hidden_dim, output_dim) <= 0 or max(input_dim, hidden_dim, output_dim) > MAX_DEPLOYMENT_DIMENSION or parameter_count > MAX_DEPLOYMENT_PARAMETERS:
        raise ValueError("invalid deployment dimensions")
    arrays = manifest.get("arrays")
    if not isinstance(arrays, list) or len(arrays) != len(_ARRAY_ORDER):
        raise ValueError("deployment arrays are incomplete")
    expected_shapes = {
        "hidden.weight": (input_dim, hidden_dim),
        "hidden.bias": (hidden_dim,),
        "output.weight": (hidden_dim, output_dim),
        "output.bias": (output_dim,),
    }
    for expected_name, item in zip(_ARRAY_ORDER, arrays):
        if not isinstance(item, dict) or item.get("name") != expected_name:
            raise ValueError("deployment arrays are not in canonical order")
        try:
            shape = tuple(int(value) for value in item["shape"])
            byte_count = int(item["bytes"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("deployment array metadata is malformed") from error
        if shape != expected_shapes[expected_name] or byte_count < 0:
            raise ValueError("deployment array shape or byte count is invalid")
        quantization = item.get("quantization")
        element_count = int(np.prod(shape, dtype=np.int64))
        if quantization is None:
            if expected_name.endswith("weight"):
                raise ValueError("deployment weights require quantization metadata")
            if item.get("dtype") != "<f4" or byte_count != element_count * 4:
                raise ValueError("deployment floating array metadata is invalid")
            continue
        if not expected_name.endswith("weight") or not isinstance(quantization, dict):
            raise ValueError("deployment quantization metadata is invalid")
        bits = quantization.get("bits")
        if bits not in {4, 8}:
            raise ValueError("deployment quantization bits are invalid")
        expected_bytes = (element_count + 1) // 2 if bits == 4 else element_count
        if byte_count != expected_bytes or item.get("dtype") not in {"|u1", "|i1"}:
            raise ValueError("deployment quantized payload metadata is invalid")
        try:
            scales = np.asarray(quantization["scales"], dtype=np.float32)
            if scales.size == 0 or not np.all(np.isfinite(scales)) or np.any(scales <= 0.0):
                raise ValueError("deployment scales are invalid")
            np.broadcast_to(scales, shape)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("deployment scales are not broadcast-compatible") from error


def _ensure_json_value(value: Any) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as error:
        raise ValueError("deployment metadata must be JSON-serializable") from error


def _validated_signing_key(signing_key: bytes) -> bytes:
    if not isinstance(signing_key, (bytes, bytearray)):
        raise TypeError("deployment signing_key must be bytes")
    key = bytes(signing_key)
    if len(key) < _MIN_SIGNING_KEY_BYTES:
        raise ValueError("deployment signing_key must contain at least 16 bytes")
    return key


__all__ = ["DeploymentArtifact", "DeploymentBundle", "MAX_DEPLOYMENT_BYTES", "MAX_INFERENCE_BATCH_ROWS", "export_mlp", "load_deployment", "load_deployment_bytes"]
