"""Cross-lifecycle proof-carrying AI pipeline for Holy Fitra.

This module composes existing dataset, training, quantization, deployment, and
execution-plan contracts. It deliberately does not invent latency or energy
measurements: runtime candidates must be supplied with measured or explicitly
proven metadata by the caller.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from holyfitra_deploy import DeploymentArtifact, DeploymentBundle, export_mlp, load_deployment
from holy_fitra_execution_plan import ExecutionPlan, KernelCandidate, PlanCompiler, PlanConstraints, PlanError
from holyfitra_qat import QuantizationQualityGate, QuantizationSpec


class AIPipelineError(ValueError):
    """Raised when a cross-lifecycle AI contract cannot be proven."""


@dataclass(frozen=True)
class DatasetFingerprint:
    name: str
    input_shape: tuple[int, ...]
    target_shape: tuple[int, ...]
    cardinality: int
    seed: int
    digest: str

    def __post_init__(self) -> None:
        if not self.name or not self.input_shape or not self.target_shape or self.cardinality <= 0 or not self.digest:
            raise AIPipelineError("invalid dataset fingerprint")
        if any(int(value) <= 0 for value in self.input_shape + self.target_shape):
            raise AIPipelineError("dataset fingerprint shapes must be positive")
        if len(self.digest) != 64 or any(character not in "0123456789abcdef" for character in self.digest):
            raise AIPipelineError("dataset fingerprint digest must be lowercase SHA-256")

    def body(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "input_shape": list(self.input_shape),
            "target_shape": list(self.target_shape),
            "cardinality": self.cardinality,
            "seed": self.seed,
            "digest": self.digest,
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class EvaluationReport:
    dataset_digest: str
    sample_count: int
    mse: float
    mae: float
    max_abs_error: float
    max_mse: float
    max_mae: float
    max_abs_allowed: float

    def __post_init__(self) -> None:
        if not self.dataset_digest or self.sample_count <= 0:
            raise AIPipelineError("invalid evaluation identity")
        values = (self.mse, self.mae, self.max_abs_error, self.max_mse, self.max_mae, self.max_abs_allowed)
        if not all(np.isfinite(value) and value >= 0.0 for value in values):
            raise AIPipelineError("evaluation metrics and thresholds must be finite and non-negative")

    @property
    def passed(self) -> bool:
        return self.mse <= self.max_mse and self.mae <= self.max_mae and self.max_abs_error <= self.max_abs_allowed

    def body(self) -> dict[str, Any]:
        return {
            "dataset_digest": self.dataset_digest,
            "sample_count": self.sample_count,
            "mse": self.mse,
            "mae": self.mae,
            "max_abs_error": self.max_abs_error,
            "max_mse": self.max_mse,
            "max_mae": self.max_mae,
            "max_abs_allowed": self.max_abs_allowed,
            "passed": self.passed,
        }

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelLineage:
    source_model_hash: str
    deployment_hash: str
    dataset_digest: str
    evaluation_digest: str
    training_config: dict[str, Any]
    parent_model_hash: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        for value in (self.source_model_hash, self.deployment_hash, self.dataset_digest, self.evaluation_digest):
            if not _is_sha256(value):
                raise AIPipelineError("model lineage identities must be lowercase SHA-256 digests")
        if self.parent_model_hash is not None and not _is_sha256(self.parent_model_hash):
            raise AIPipelineError("parent model identity must be a lowercase SHA-256 digest")
        _ensure_json(self.training_config)
        _ensure_json(self.metadata or {})

    def body(self) -> dict[str, Any]:
        return {
            "source_model_hash": self.source_model_hash,
            "deployment_hash": self.deployment_hash,
            "dataset_digest": self.dataset_digest,
            "evaluation_digest": self.evaluation_digest,
            "training_config": self.training_config,
            "parent_model_hash": self.parent_model_hash,
            "metadata": self.metadata or {},
        }

    def canonical(self) -> str:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PipelineResult:
    dataset: DatasetFingerprint
    evaluation: EvaluationReport
    lineage: ModelLineage
    artifact: DeploymentArtifact
    plan: ExecutionPlan

    def verify(self) -> None:
        if self.artifact.digest != self.lineage.deployment_hash:
            raise AIPipelineError("deployment artifact does not match lineage")
        if self.evaluation.dataset_digest != self.lineage.dataset_digest:
            raise AIPipelineError("evaluation dataset does not match lineage")
        if self.plan.model_hash != self.artifact.digest:
            raise AIPipelineError("execution plan is bound to a different deployment")
        plan_metadata = self.plan.metadata
        if plan_metadata.get("lineage_digest") != self.lineage.digest() or plan_metadata.get("dataset_digest") != self.dataset.digest or plan_metadata.get("evaluation_digest") != self.evaluation.digest() or plan_metadata.get("source_model_hash") != self.lineage.source_model_hash:
            raise AIPipelineError("execution plan metadata is inconsistent with AI lineage")
        self.plan.verify()
        if not self.evaluation.passed:
            raise AIPipelineError("pipeline result contains a failed evaluation")

    def body(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset.body(),
            "evaluation": self.evaluation.body(),
            "evaluation_digest": self.evaluation.digest(),
            "lineage": self.lineage.body(),
            "lineage_digest": self.lineage.digest(),
            "deployment_hash": self.artifact.digest,
            "plan_id": self.plan.plan_id,
        }

    def canonical(self) -> str:
        self.verify()
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


class VerifiedAIPipeline:
    """Compose training outputs into a verified deployment execution contract."""

    def __init__(self, validation_dataset: Any):
        for name in ("iter_samples", "iter_batches", "input_shape", "target_shape", "seed", "name"):
            if not hasattr(validation_dataset, name):
                raise TypeError(f"validation dataset lacks required field {name}")
        self.validation_dataset = validation_dataset
        self._dataset_fingerprint: DatasetFingerprint | None = None

    def fingerprint(self) -> DatasetFingerprint:
        if self._dataset_fingerprint is not None:
            return self._dataset_fingerprint
        digest = hashlib.sha256()
        header = {
            "name": str(self.validation_dataset.name),
            "input_shape": list(self.validation_dataset.input_shape),
            "target_shape": list(self.validation_dataset.target_shape),
            "seed": int(self.validation_dataset.seed),
        }
        digest.update(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        count = 0
        for inputs, targets in self.validation_dataset.iter_samples():
            x = np.ascontiguousarray(np.asarray(inputs, dtype=np.float32))
            y = np.ascontiguousarray(np.asarray(targets, dtype=np.float32))
            if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise AIPipelineError("dataset fingerprint rejects non-finite values")
            digest.update(struct.pack("<Q", count))
            digest.update(x.tobytes(order="C"))
            digest.update(y.tobytes(order="C"))
            count += 1
        if count == 0:
            raise AIPipelineError("cannot fingerprint an empty validation dataset")
        self._dataset_fingerprint = DatasetFingerprint(str(self.validation_dataset.name), tuple(self.validation_dataset.input_shape), tuple(self.validation_dataset.target_shape), count, int(self.validation_dataset.seed), digest.hexdigest())
        return self._dataset_fingerprint

    def evaluate(self, model: Any, *, max_mse: float, max_mae: float, max_abs_allowed: float, batch_size: int = 256) -> EvaluationReport:
        if batch_size <= 0:
            raise AIPipelineError("evaluation batch_size must be positive")
        dataset = self.fingerprint()
        if not hasattr(model, "predict"):
            raise TypeError("model must provide predict")
        squared = 0.0
        absolute = 0.0
        maximum = 0.0
        elements = 0
        samples = 0
        for batch in self.validation_dataset.iter_batches(batch_size, shuffle=False):
            predictions = np.ascontiguousarray(np.asarray(model.predict(batch.inputs), dtype=np.float32))
            targets = np.ascontiguousarray(np.asarray(batch.targets, dtype=np.float32))
            if predictions.shape != targets.shape or not np.all(np.isfinite(predictions)):
                raise AIPipelineError("model evaluation produced invalid predictions")
            error = predictions.astype(np.float64) - targets.astype(np.float64)
            squared += float(np.sum(error * error, dtype=np.float64))
            absolute += float(np.sum(np.abs(error), dtype=np.float64))
            maximum = max(maximum, float(np.max(np.abs(error))) if error.size else 0.0)
            elements += int(error.size)
            samples += int(batch.size)
        if samples == 0 or elements == 0:
            raise AIPipelineError("validation dataset produced no evaluation elements")
        report = EvaluationReport(dataset.digest, samples, squared / elements, absolute / elements, maximum, float(max_mse), float(max_mae), float(max_abs_allowed))
        if not report.passed:
            raise AIPipelineError(f"evaluation quality gate failed: mse={report.mse:.9g}, mae={report.mae:.9g}, max_abs_error={report.max_abs_error:.9g}")
        return report

    def export_verified(
        self,
        model: Any,
        path: str,
        *,
        signing_key: bytes,
        weight_spec: QuantizationSpec,
        quality_gate: QuantizationQualityGate,
        candidates: Iterable[KernelCandidate],
        constraints: PlanConstraints,
        training_config: dict[str, Any] | None = None,
        parent_model_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        max_mse: float,
        max_mae: float,
        max_abs_allowed: float,
        batch_size: int = 256,
    ) -> PipelineResult:
        if not np.isfinite(max_mse) or not np.isfinite(max_mae) or not np.isfinite(max_abs_allowed):
            raise AIPipelineError("pipeline evaluation thresholds must be finite")
        report = self.evaluate(model, max_mse=max_mse, max_mae=max_mae, max_abs_allowed=max_abs_allowed, batch_size=batch_size)
        source_hash = _model_hash(model)
        dataset = self.fingerprint()
        export_metadata = {
            "ai_pipeline": "holyfitra.ai-pipeline/v1",
            "source_model_hash": source_hash,
            "dataset_digest": dataset.digest,
            "evaluation_digest": report.digest(),
            "training_config": training_config or {},
            "parent_model_hash": parent_model_hash,
            "metadata": metadata or {},
        }
        _ensure_json(export_metadata)
        try:
            artifact = export_mlp(model, path, weight_spec=weight_spec, quality_gate=quality_gate, signing_key=signing_key, metadata=export_metadata)
            bundle = load_deployment(path, signing_key=signing_key)
            self._verify_deployment_predictions(model, bundle, report, batch_size)
        except AIPipelineError:
            raise
        except (OSError, ValueError) as error:
            raise AIPipelineError(f"deployment quality or round-trip gate failed: {error}") from error
        lineage = ModelLineage(source_hash, artifact.digest, dataset.digest, report.digest(), training_config or {}, parent_model_hash, metadata or {})
        plan_metadata = {
            "ai_pipeline": "holyfitra.ai-pipeline/v1",
            "lineage_digest": lineage.digest(),
            "dataset_digest": dataset.digest,
            "evaluation_digest": report.digest(),
            "source_model_hash": source_hash,
        }
        if metadata:
            plan_metadata["metadata"] = metadata
        try:
            plan = PlanCompiler(kernel_abi=constraints.required_abi).compile(model_hash=artifact.digest, candidates=tuple(candidates), constraints=constraints, metadata=plan_metadata)
        except PlanError as error:
            raise AIPipelineError(f"execution plan quality/resource gate failed: {error}") from error
        result = PipelineResult(dataset, report, lineage, artifact, plan)
        result.verify()
        return result

    def _verify_deployment_predictions(self, model: Any, bundle: DeploymentBundle, report: EvaluationReport, batch_size: int) -> None:
        squared = 0.0
        elements = 0
        for batch in self.validation_dataset.iter_batches(batch_size, shuffle=False):
            reference = np.asarray(model.predict(batch.inputs), dtype=np.float32)
            candidate = np.asarray(bundle.predict(batch.inputs), dtype=np.float32)
            if reference.shape != candidate.shape or not np.all(np.isfinite(candidate)):
                raise AIPipelineError("deployment round-trip produced invalid predictions")
            error = reference.astype(np.float64) - candidate.astype(np.float64)
            squared += float(np.sum(error * error, dtype=np.float64))
            elements += int(error.size)
        if elements == 0 or squared / elements > report.max_mse:
            raise AIPipelineError("deployment prediction drift exceeded evaluation MSE budget")


def _is_sha256(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _model_hash(model: Any) -> str:
    if not hasattr(model, "state_dict"):
        raise TypeError("model must provide state_dict for lineage")
    state = model.state_dict()
    if not isinstance(state, dict) or not state:
        raise AIPipelineError("model state is empty")
    digest = hashlib.sha256()
    for name in sorted(state):
        value = np.ascontiguousarray(np.asarray(state[name], dtype=np.float32))
        if not np.all(np.isfinite(value)):
            raise AIPipelineError("model state contains non-finite values")
        digest.update(name.encode("utf-8"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _ensure_json(value: Any) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as error:
        raise AIPipelineError("AI pipeline metadata must be JSON-serializable") from error


__all__ = ["AIPipelineError", "DatasetFingerprint", "EvaluationReport", "ModelLineage", "PipelineResult", "VerifiedAIPipeline"]
