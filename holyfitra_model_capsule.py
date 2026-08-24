#!/usr/bin/env python3
"""Signed, content-addressed model capsules with verified lazy chunk loading."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from holyfitra_ai_pipeline import PipelineResult
from holyfitra_agent_receipt import AgentPlanReceipt
from holyfitra_deploy import DeploymentBundle, MAX_DEPLOYMENT_BYTES, MAX_INFERENCE_BATCH_ROWS, MAX_INFERENCE_INPUT_BYTES, load_deployment_bytes
from holyfitra_tensor_contracts import TensorResourceContract

_MAGIC = b"HFCAPSULE\x01"
_PREFIX = struct.Struct("<Q")
_TAG_BYTES = hashlib.sha256().digest_size
_MIN_KEY_BYTES = 16
MAX_CAPSULE_BYTES = 128 * 1024 * 1024
MAX_CAPSULE_CHUNKS = 4_096
MIN_CHUNK_BYTES = 1_024
MAX_CHUNK_BYTES = 1_048_576
MAX_STREAM_BLOCK_COLUMNS = 512
MAX_STREAM_BLOCK_BYTES = 1_048_576


class CapsuleError(ValueError):
    """A capsule identity, chunk, or execution-plan contract is invalid."""


@dataclass(frozen=True)
class CapsuleArtifact:
    path: str
    digest: str
    manifest: dict[str, Any]
    bytes_written: int


@dataclass(frozen=True)
class CapsuleChunk:
    name: str
    offset: int
    size: int
    digest: str


class StreamedInferenceError(ValueError):
    """A layer-indexed capsule stream cannot be evaluated safely."""


class StreamedMLPInference:
    """Bounded-memory MLP evaluation over verified layer blocks in a capsule."""

    def __init__(self, capsule: "ModelCapsule", manifest: dict[str, Any], native_kernel: Any | None = None):
        self._capsule = capsule
        self._manifest = _validate_layer_stream_manifest(manifest, capsule._chunks)
        if self._manifest["deployment_digest"] != capsule.manifest["deployment_hash"]:
            raise StreamedInferenceError("layer stream is not bound to this capsule deployment identity")
        if native_kernel is not None and not callable(getattr(native_kernel, "matmul", None)):
            raise StreamedInferenceError("native streamed kernel must expose matmul(inputs, weights)")
        self._native_kernel = native_kernel
        self.loaded_block_count = 0

    @property
    def uses_full_reassembly(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        if self._native_kernel is None:
            return "numpy-reference"
        return "native-neon" if bool(getattr(self._native_kernel, "has_neon", False)) else "native-scalar"

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        x = np.asarray(inputs, dtype=np.float32)
        model = self._manifest["model"]["dimensions"]
        if x.ndim != 2 or x.shape[0] <= 0 or x.shape[0] > MAX_INFERENCE_BATCH_ROWS or x.shape[1] != model["input_dim"]:
            raise StreamedInferenceError("inputs must have shape [batch, input_dim]")
        if x.nbytes > MAX_INFERENCE_INPUT_BYTES or not np.all(np.isfinite(x)):
            raise StreamedInferenceError("streamed inference inputs must be finite and within the configured byte budget")
        current = x
        with np.errstate(over="raise", invalid="raise"):
            try:
                for layer in self._manifest["layers"]:
                    current = self._evaluate_layer(current, layer)
            except FloatingPointError as error:
                raise StreamedInferenceError("streamed layer evaluation produced a non-finite intermediate") from error
        if not np.all(np.isfinite(current)):
            raise StreamedInferenceError("streamed layer evaluation produced non-finite output")
        return np.ascontiguousarray(current, dtype=np.float32)

    def _evaluate_layer(self, inputs: np.ndarray, layer: dict[str, Any]) -> np.ndarray:
        output = np.empty((inputs.shape[0], layer["output_dim"]), dtype=np.float32)
        for block in layer["blocks"]:
            payload = self._capsule.read_chunk(block["chunk"])
            expected_shape = (layer["input_dim"], block["output_end"] - block["output_start"])
            if len(payload) != expected_shape[0] * expected_shape[1] * 4:
                raise StreamedInferenceError("layer block byte count no longer matches its authenticated stream index")
            weights = np.frombuffer(payload, dtype="<f4").reshape(expected_shape)
            if not np.all(np.isfinite(weights)):
                raise StreamedInferenceError("layer block contains non-finite weights")
            if self._native_kernel is None:
                output[:, block["output_start"] : block["output_end"]] = inputs @ weights
            else:
                try:
                    native_output = self._native_kernel.matmul(inputs, weights)
                except Exception as error:
                    raise StreamedInferenceError("native streamed kernel rejected a verified block") from error
                if native_output.shape != (inputs.shape[0], expected_shape[1]) or not np.all(np.isfinite(native_output)):
                    raise StreamedInferenceError("native streamed kernel returned an invalid block output")
                output[:, block["output_start"] : block["output_end"]] = native_output
            self.loaded_block_count += 1
        bias_payload = self._capsule.read_chunk(layer["bias_chunk"])
        if len(bias_payload) != layer["output_dim"] * 4:
            raise StreamedInferenceError("layer bias byte count no longer matches its authenticated stream index")
        bias = np.frombuffer(bias_payload, dtype="<f4")
        if not np.all(np.isfinite(bias)):
            raise StreamedInferenceError("layer bias contains non-finite values")
        output += bias
        if layer["activation"] == "relu":
            np.maximum(output, 0.0, out=output)
        return output


class ModelCapsule:
    """Authenticated capsule index that loads payload chunks only on demand."""

    def __init__(self, path: Path, manifest: dict[str, Any], chunks: dict[str, CapsuleChunk], *, cache_chunks: int = 4):
        self.path = path
        self.manifest = manifest
        self._chunks = chunks
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_chunks = cache_chunks

    @property
    def cached_chunk_count(self) -> int:
        return len(self._cache)

    @property
    def chunk_names(self) -> tuple[str, ...]:
        return tuple(self._chunks)

    def read_chunk(self, name: str) -> bytes:
        if name not in self._chunks:
            raise CapsuleError("requested capsule chunk is absent")
        cached = self._cache.get(name)
        if cached is not None:
            self._cache.move_to_end(name)
            return cached
        chunk = self._chunks[name]
        try:
            with self.path.open("rb") as handle:
                handle.seek(chunk.offset)
                payload = handle.read(chunk.size)
        except OSError as error:
            raise CapsuleError("capsule chunk cannot be read") from error
        if len(payload) != chunk.size or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), chunk.digest):
            raise CapsuleError("capsule chunk digest does not match authenticated index")
        self._cache[name] = payload
        while len(self._cache) > self._cache_chunks:
            self._cache.popitem(last=False)
        return payload

    def deployment_bytes(self) -> bytes:
        names = tuple(name for name in self._chunks if name.startswith("deployment/"))
        if not names:
            raise CapsuleError("capsule has no deployment payload")
        payload = b"".join(self.read_chunk(name) for name in names)
        expected = self.manifest["deployment_hash"]
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected):
            raise CapsuleError("deployment digest does not match capsule identity")
        return payload

    def iter_deployment_chunks(self) -> Iterator[bytes]:
        """Yield verified deployment chunks in canonical order for streaming runtimes."""
        names = tuple(name for name in self._chunks if name.startswith("deployment/"))
        if not names:
            raise CapsuleError("capsule has no deployment payload")
        for name in names:
            yield self.read_chunk(name)

    def load_deployment(self, *, signing_key: bytes) -> DeploymentBundle:
        return load_deployment_bytes(self.deployment_bytes(), signing_key=signing_key)

    def execution_plan_json(self) -> dict[str, Any]:
        return _json_chunk(self.read_chunk("execution_plan.json"))

    def pipeline_receipt_json(self) -> dict[str, Any]:
        return _json_chunk(self.read_chunk("pipeline_receipt.json"))

    def resource_contract_json(self) -> dict[str, Any] | None:
        return _json_chunk(self.read_chunk("resource_contract.json")) if "resource_contract.json" in self._chunks else None

    def agent_receipt_json(self) -> dict[str, Any] | None:
        return _json_chunk(self.read_chunk("agent_receipt.json")) if "agent_receipt.json" in self._chunks else None

    def layer_stream_manifest_json(self) -> dict[str, Any] | None:
        return _json_chunk(self.read_chunk("layer_stream_manifest.json")) if "layer_stream_manifest.json" in self._chunks else None

    def open_streamed_mlp(self, native_kernel: Any | None = None) -> StreamedMLPInference:
        manifest = self.layer_stream_manifest_json()
        if manifest is None:
            raise CapsuleError("capsule has no layer-indexed streamed inference payload")
        return StreamedMLPInference(self, manifest, native_kernel=native_kernel)


def export_pipeline_capsule(result: PipelineResult, destination: str | os.PathLike[str], *, signing_key: bytes, chunk_bytes: int = 65_536, metadata: dict[str, Any] | None = None, resource_contract: TensorResourceContract | None = None, agent_receipt: AgentPlanReceipt | None = None, deployment_signing_key: bytes | None = None, stream_block_columns: int | None = None) -> CapsuleArtifact:
    """Package an already-verified pipeline result into a lazily readable capsule."""
    result.verify()
    if resource_contract is not None:
        resource_contract.verify_plan(result.plan)
    try:
        deployment = Path(result.artifact.path).read_bytes()
    except OSError as error:
        raise CapsuleError("verified deployment artifact cannot be read") from error
    if not hmac.compare_digest(hashlib.sha256(deployment).hexdigest(), result.artifact.digest):
        raise CapsuleError("deployment bytes no longer match the verified pipeline artifact")
    plan_payload = result.plan.to_json().encode("utf-8")
    receipt_payload = result.canonical().encode("utf-8")
    if (deployment_signing_key is None) != (stream_block_columns is None):
        raise CapsuleError("deployment_signing_key and stream_block_columns must be supplied together")
    layer_stream_payload = None
    stream_payloads: tuple[tuple[str, bytes], ...] = ()
    if deployment_signing_key is not None and stream_block_columns is not None:
        bundle = load_deployment_bytes(deployment, signing_key=deployment_signing_key)
        layer_stream_payload, stream_payloads = _build_layer_stream(bundle, stream_block_columns)
    return _write_capsule(
        destination,
        deployment=deployment,
        deployment_hash=result.artifact.digest,
        plan_payload=plan_payload,
        receipt_payload=receipt_payload,
        signing_key=signing_key,
        chunk_bytes=chunk_bytes,
        metadata=metadata or {},
        resource_contract_payload=json.dumps(resource_contract.body(), sort_keys=True, separators=(",", ":")).encode("utf-8") if resource_contract is not None else None,
        agent_receipt_payload=json.dumps(agent_receipt.body(), sort_keys=True, separators=(",", ":")).encode("utf-8") if agent_receipt is not None else None,
        layer_stream_payload=layer_stream_payload,
        stream_payloads=stream_payloads,
    )


def open_model_capsule(path: str | os.PathLike[str], *, signing_key: bytes, cache_chunks: int = 4) -> ModelCapsule:
    key = _validated_key(signing_key)
    if not isinstance(cache_chunks, int) or not 0 <= cache_chunks <= 64:
        raise CapsuleError("capsule cache chunk count is invalid")
    source = Path(path)
    try:
        total_size = source.stat().st_size
        if total_size > MAX_CAPSULE_BYTES:
            raise CapsuleError("capsule exceeds the configured byte budget")
        with source.open("rb") as handle:
            prefix = handle.read(len(_MAGIC) + _PREFIX.size)
            if len(prefix) != len(_MAGIC) + _PREFIX.size or prefix[: len(_MAGIC)] != _MAGIC:
                raise CapsuleError("capsule magic is invalid")
            header_size = _PREFIX.unpack_from(prefix, len(_MAGIC))[0]
            if header_size <= 0 or header_size > MAX_CAPSULE_BYTES:
                raise CapsuleError("capsule header length is invalid")
            header = handle.read(header_size)
            tag = handle.read(_TAG_BYTES)
    except OSError as error:
        raise CapsuleError("capsule cannot be opened") from error
    if len(header) != header_size or len(tag) != _TAG_BYTES:
        raise CapsuleError("capsule header is truncated")
    authenticated = prefix + header
    if not hmac.compare_digest(hmac.new(key, authenticated, hashlib.sha256).digest(), tag):
        raise CapsuleError("capsule header authentication failed")
    manifest = _json_chunk(header)
    payload_start = len(authenticated) + _TAG_BYTES
    chunks = _validate_manifest(manifest, payload_start, total_size)
    return ModelCapsule(source, manifest, chunks, cache_chunks=cache_chunks)


def _write_capsule(destination: str | os.PathLike[str], *, deployment: bytes, deployment_hash: str, plan_payload: bytes, receipt_payload: bytes, signing_key: bytes, chunk_bytes: int, metadata: dict[str, Any], resource_contract_payload: bytes | None, agent_receipt_payload: bytes | None, layer_stream_payload: bytes | None, stream_payloads: tuple[tuple[str, bytes], ...]) -> CapsuleArtifact:
    key = _validated_key(signing_key)
    if not isinstance(chunk_bytes, int) or not MIN_CHUNK_BYTES <= chunk_bytes <= MAX_CHUNK_BYTES:
        raise CapsuleError("capsule chunk size is outside the configured range")
    if not _is_digest(deployment_hash) or hashlib.sha256(deployment).hexdigest() != deployment_hash:
        raise CapsuleError("capsule deployment identity is invalid")
    _ensure_json(metadata)
    chunks_payload: list[tuple[str, bytes]] = []
    for index in range(0, len(deployment), chunk_bytes):
        chunks_payload.append((f"deployment/{index // chunk_bytes:06d}", deployment[index : index + chunk_bytes]))
    if not chunks_payload:
        raise CapsuleError("capsule deployment cannot be empty")
    chunks_payload.extend((("execution_plan.json", plan_payload), ("pipeline_receipt.json", receipt_payload)))
    if resource_contract_payload is not None:
        chunks_payload.append(("resource_contract.json", resource_contract_payload))
    if agent_receipt_payload is not None:
        chunks_payload.append(("agent_receipt.json", agent_receipt_payload))
    if layer_stream_payload is not None:
        chunks_payload.append(("layer_stream_manifest.json", layer_stream_payload))
        chunks_payload.extend(stream_payloads)
    relative_offset = 0
    chunk_manifest: list[dict[str, Any]] = []
    for name, payload in chunks_payload:
        chunk_manifest.append({"name": name, "offset": relative_offset, "size": len(payload), "digest": hashlib.sha256(payload).hexdigest()})
        relative_offset += len(payload)
    manifest = {
        "format": "holyfitra.model-capsule",
        "version": 1,
        "deployment_hash": deployment_hash,
        "chunk_bytes": chunk_bytes,
        "chunks": chunk_manifest,
        "metadata": metadata,
    }
    header = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    authenticated = _MAGIC + _PREFIX.pack(len(header)) + header
    payload = authenticated + hmac.new(key, authenticated, hashlib.sha256).digest() + b"".join(item[1] for item in chunks_payload)
    if len(payload) > MAX_CAPSULE_BYTES:
        raise CapsuleError("capsule exceeds the configured byte budget")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=target.name + ".", suffix=".tmp", dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return CapsuleArtifact(str(target), hashlib.sha256(payload).hexdigest(), manifest, len(payload))


def _validate_manifest(manifest: dict[str, Any], payload_start: int, total_size: int) -> dict[str, CapsuleChunk]:
    if not isinstance(manifest, dict) or manifest.get("format") != "holyfitra.model-capsule" or manifest.get("version") != 1 or not _is_digest(manifest.get("deployment_hash", "")):
        raise CapsuleError("capsule manifest identity is invalid")
    _ensure_json(manifest.get("metadata", {}))
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not 3 <= len(chunks) <= MAX_CAPSULE_CHUNKS:
        raise CapsuleError("capsule chunk index is invalid")
    result: dict[str, CapsuleChunk] = {}
    expected_offset = 0
    seen_deployment = 0
    for item in chunks:
        if not isinstance(item, dict):
            raise CapsuleError("capsule chunk item is malformed")
        name, offset, size, digest = item.get("name"), item.get("offset"), item.get("size"), item.get("digest")
        if not isinstance(name, str) or not name.isascii() or not name or name in result or not isinstance(offset, int) or not isinstance(size, int) or offset != expected_offset or size <= 0 or not _is_digest(digest):
            raise CapsuleError("capsule chunk ordering or identity is invalid")
        if name.startswith("deployment/"):
            seen_deployment += 1
        elif name not in {"execution_plan.json", "pipeline_receipt.json", "resource_contract.json", "agent_receipt.json", "layer_stream_manifest.json"} and not name.startswith("stream/"):
            raise CapsuleError("capsule contains an unsupported chunk name")
        result[name] = CapsuleChunk(name, payload_start + offset, size, digest)
        expected_offset += size
    if seen_deployment == 0 or "execution_plan.json" not in result or "pipeline_receipt.json" not in result or payload_start + expected_offset != total_size:
        raise CapsuleError("capsule payload layout is incomplete")
    return result


def _build_layer_stream(bundle: DeploymentBundle, block_columns: int) -> tuple[bytes, tuple[tuple[str, bytes], ...]]:
    if not isinstance(block_columns, int) or isinstance(block_columns, bool) or not 1 <= block_columns <= MAX_STREAM_BLOCK_COLUMNS:
        raise CapsuleError("layer stream block column count is invalid")
    dimensions = bundle.manifest["model"]["dimensions"]
    layer_specs = (("hidden", "hidden.weight", "hidden.bias", "relu"), ("output", "output.weight", "output.bias", "identity"))
    payloads: list[tuple[str, bytes]] = []
    layers: list[dict[str, Any]] = []
    for layer_name, weight_name, bias_name, activation in layer_specs:
        weights = np.ascontiguousarray(bundle.arrays[weight_name], dtype="<f4")
        bias = np.ascontiguousarray(bundle.arrays[bias_name], dtype="<f4")
        if weights.ndim != 2 or bias.ndim != 1 or weights.shape[1] != bias.shape[0] or weights.nbytes > MAX_DEPLOYMENT_BYTES:
            raise CapsuleError("deployment cannot be converted into a valid layer stream")
        blocks: list[dict[str, Any]] = []
        for start in range(0, weights.shape[1], block_columns):
            end = min(start + block_columns, weights.shape[1])
            block = np.ascontiguousarray(weights[:, start:end], dtype="<f4")
            if block.nbytes > MAX_STREAM_BLOCK_BYTES:
                raise CapsuleError("layer stream block exceeds the configured byte budget")
            name = f"stream/{layer_name}.weight/{start:08d}"
            payloads.append((name, block.tobytes(order="C")))
            blocks.append({"chunk": name, "output_start": start, "output_end": end})
        bias_name_chunk = f"stream/{layer_name}.bias"
        payloads.append((bias_name_chunk, bias.tobytes(order="C")))
        layers.append({"name": layer_name, "activation": activation, "input_dim": int(weights.shape[0]), "output_dim": int(weights.shape[1]), "blocks": blocks, "bias_chunk": bias_name_chunk})
    stream_manifest = {
        "schema": "holyfitra.layer-stream/v1",
        "deployment_digest": bundle.digest,
        "model": {"type": "mlp", "dimensions": {key: int(value) for key, value in dimensions.items()}},
        "dtype": "<f4",
        "layers": layers,
    }
    return json.dumps(stream_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"), tuple(payloads)


def _validate_layer_stream_manifest(manifest: dict[str, Any], chunks: dict[str, CapsuleChunk]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema") != "holyfitra.layer-stream/v1" or not _is_digest(manifest.get("deployment_digest", "")) or manifest.get("dtype") != "<f4":
        raise StreamedInferenceError("layer stream manifest identity is invalid")
    model = manifest.get("model")
    if not isinstance(model, dict) or model.get("type") != "mlp" or not isinstance(model.get("dimensions"), dict):
        raise StreamedInferenceError("layer stream model metadata is invalid")
    try:
        dimensions = {key: int(model["dimensions"][key]) for key in ("input_dim", "hidden_dim", "output_dim")}
    except (KeyError, TypeError, ValueError) as error:
        raise StreamedInferenceError("layer stream dimensions are invalid") from error
    if min(dimensions.values()) <= 0 or max(dimensions.values()) > 8_192:
        raise StreamedInferenceError("layer stream dimensions exceed the configured bounds")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or len(layers) != 2:
        raise StreamedInferenceError("layer stream must contain exactly hidden and output layers")
    expected = (("hidden", dimensions["input_dim"], dimensions["hidden_dim"], "relu"), ("output", dimensions["hidden_dim"], dimensions["output_dim"], "identity"))
    for item, (name, input_dim, output_dim, activation) in zip(layers, expected):
        if not isinstance(item, dict) or item.get("name") != name or item.get("input_dim") != input_dim or item.get("output_dim") != output_dim or item.get("activation") != activation or item.get("bias_chunk") != f"stream/{name}.bias" or item.get("bias_chunk") not in chunks:
            raise StreamedInferenceError("layer stream layer metadata is invalid")
        blocks = item.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise StreamedInferenceError("layer stream blocks are missing")
        cursor = 0
        for block in blocks:
            if not isinstance(block, dict) or block.get("chunk") != f"stream/{name}.weight/{cursor:08d}" or block.get("chunk") not in chunks or block.get("output_start") != cursor or not isinstance(block.get("output_end"), int) or block["output_end"] <= cursor or block["output_end"] > output_dim:
                raise StreamedInferenceError("layer stream block metadata is invalid")
            block_chunk = chunks[block["chunk"]]
            if block_chunk.size != input_dim * (block["output_end"] - cursor) * 4 or block_chunk.size > MAX_STREAM_BLOCK_BYTES:
                raise StreamedInferenceError("layer stream block byte contract is invalid")
            cursor = block["output_end"]
        if cursor != output_dim or chunks[item["bias_chunk"]].size != output_dim * 4:
            raise StreamedInferenceError("layer stream output coverage is incomplete")
    return manifest


def _json_chunk(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapsuleError("capsule JSON chunk is invalid") from error
    if not isinstance(value, dict):
        raise CapsuleError("capsule JSON chunk must be an object")
    return value


def _validated_key(value: bytes) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) < _MIN_KEY_BYTES:
        raise CapsuleError("capsule signing key must contain at least 16 bytes")
    return bytes(value)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _ensure_json(value: Any) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as error:
        raise CapsuleError("capsule metadata must be JSON-serializable") from error


__all__ = ["CapsuleArtifact", "CapsuleError", "ModelCapsule", "export_pipeline_capsule", "open_model_capsule"]
