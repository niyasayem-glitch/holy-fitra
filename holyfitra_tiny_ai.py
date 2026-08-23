#!/usr/bin/env python3
"""A bounded, deterministic from-scratch AI example for Holy Fitra.

This module trains a two-layer MLP to classify XOR using the repository's own
Tensor/autodiff, Adam, QAT, and deployment components.  It is deliberately a
small reference model: it demonstrates a complete train -> evaluate -> export
-> reload flow without claiming general intelligence or native Holy Fitra
language execution.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from holyfitra_deploy import DeploymentArtifact, export_mlp, load_deployment
from holyfitra_learning import TrainingConfig, evaluate_mse, train_supervised, TrainableMLP
from holyfitra_qat import QuantizationAwareMLP, QuantizationQualityGate, QuantizationSpec


@dataclass(frozen=True)
class TinyAiReport:
    """Measured result of the fixed XOR training fixture."""

    seed: int
    epochs: int
    initial_mse: float
    final_mse: float
    float_accuracy: float
    deployment_accuracy: float
    parameter_count: int
    deployment_digest: str
    deployment_bytes: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def xor_dataset() -> tuple[np.ndarray, np.ndarray]:
    """Return the complete, finite, deterministic XOR truth table."""
    inputs = np.asarray(((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)), dtype=np.float32)
    targets = np.asarray(((0.0,), (1.0,), (1.0,), (0.0,)), dtype=np.float32)
    return inputs, targets


def binary_accuracy(logits: np.ndarray, targets: np.ndarray) -> float:
    prediction = np.asarray(logits, dtype=np.float32)
    expected = np.asarray(targets, dtype=np.float32)
    if prediction.shape != expected.shape or prediction.ndim != 2 or prediction.shape[1] != 1:
        raise ValueError("binary predictions and targets must have shape [batch, 1]")
    if not np.all(np.isfinite(prediction)) or not np.all(np.isfinite(expected)):
        raise ValueError("binary predictions and targets must be finite")
    return float(np.mean((prediction >= 0.5) == (expected >= 0.5)))


def train_xor_classifier(*, seed: int = 17, epochs: int = 900) -> tuple[QuantizationAwareMLP, float, float, float]:
    """Train a compact QAT MLP and return model plus measured loss/accuracy."""
    if not isinstance(seed, int) or isinstance(seed, bool) or not isinstance(epochs, int) or isinstance(epochs, bool) or epochs <= 0:
        raise ValueError("seed must be an integer and epochs must be positive")
    inputs, targets = xor_dataset()
    quality_gate = QuantizationQualityGate(max_mse=0.002, max_abs_error=0.08)
    model = QuantizationAwareMLP(
        TrainableMLP(2, 8, 1, seed=seed),
        weight_spec=QuantizationSpec(bits=8, axis=0),
        quality_gate=quality_gate,
    )
    initial_mse = evaluate_mse(model, inputs, targets)
    history = train_supervised(
        model,
        inputs,
        targets,
        config=TrainingConfig(epochs=epochs, batch_size=4, max_grad_norm=5.0, seed=seed + 1),
    )
    final_mse = evaluate_mse(model, inputs, targets)
    accuracy = binary_accuracy(model.predict(inputs), targets)
    if not np.isfinite(history.final_loss) or final_mse >= initial_mse or accuracy < 1.0:
        raise RuntimeError("tiny XOR training did not reach the required deterministic quality threshold")
    return model, float(initial_mse), float(final_mse), accuracy


def build_xor_deployment(destination: str | Path, *, signing_key: bytes, seed: int = 17, epochs: int = 900) -> TinyAiReport:
    """Train, export, reload, and verify the small XOR classifier."""
    model, initial_mse, final_mse, float_accuracy = train_xor_classifier(seed=seed, epochs=epochs)
    quality_gate = model.quality_gate
    artifact: DeploymentArtifact = export_mlp(
        model,
        destination,
        weight_spec=model.weight_spec,
        quality_gate=quality_gate,
        signing_key=signing_key,
        metadata={"example": "tiny_xor", "seed": seed, "epochs": epochs, "training": "holyfitra_tensor_adam_qat"},
    )
    inputs, targets = xor_dataset()
    deployment_accuracy = binary_accuracy(load_deployment(destination, signing_key=signing_key).predict(inputs), targets)
    if deployment_accuracy < 1.0:
        raise RuntimeError("quantized deployment did not preserve XOR accuracy")
    parameter_count = sum(int(parameter.data.size) for parameter in model.parameters)
    return TinyAiReport(
        seed=seed,
        epochs=epochs,
        initial_mse=initial_mse,
        final_mse=final_mse,
        float_accuracy=float_accuracy,
        deployment_accuracy=deployment_accuracy,
        parameter_count=parameter_count,
        deployment_digest=artifact.digest,
        deployment_bytes=artifact.bytes_written,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and export Holy Fitra's deterministic from-scratch XOR AI example.")
    parser.add_argument("--output", default="build/tiny_xor.hfbin", help="deployment artifact path")
    parser.add_argument("--seed", type=int, default=17, help="deterministic model seed")
    parser.add_argument("--epochs", type=int, default=900, help="positive training epoch count")
    parser.add_argument("--signing-key-env", default="HOLY_FITRA_DEPLOYMENT_KEY", help="environment variable containing the deployment signing key")
    arguments = parser.parse_args()
    value = os.environ.get(arguments.signing_key_env)
    if value is None:
        raise SystemExit(f"missing deployment signing key environment variable: {arguments.signing_key_env}")
    report = build_xor_deployment(arguments.output, signing_key=value.encode("utf-8"), seed=arguments.seed, epochs=arguments.epochs)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
