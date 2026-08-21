#!/usr/bin/env python3
"""Proof-carrying mixed-precision selection for HyperC.

The selector is conservative: it returns the smallest candidate that passes
both reconstruction and optional task-quality gates, otherwise it raises
instead of silently shipping degraded weights.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from hyperc_hyperir import QuantizationProof
from hyperc_quantized_transformer import QuantizedMatrix
from hyperc_hybrid_quant import Float16Matrix
from holyfitra_quant_utils import calibration_mse


@dataclass(frozen=True)
class PrecisionCandidate:
    precision: str
    group_size: int
    layer_error: float
    storage_bytes: int
    kernel: str


@dataclass
class ProofManifest:
    model: str
    calibration_sha256: str
    selected: list[PrecisionCandidate]
    max_layer_error: float
    minimum_task_score: float | None
    device: str
    proofs: list[QuantizationProof]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "calibration_sha256": self.calibration_sha256,
            "selected": [asdict(candidate) for candidate in self.selected],
            "max_layer_error": self.max_layer_error,
            "minimum_task_score": self.minimum_task_score,
            "device": self.device,
            "proofs": [asdict(proof) for proof in self.proofs],
        }

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_jsonable(), handle, indent=2, sort_keys=True)


def _mse(weight: np.ndarray, calibration: np.ndarray, candidate: Any) -> float:
    return calibration_mse(weight, calibration, candidate)


def select_matrix(
    weight: np.ndarray,
    calibration: np.ndarray,
    *,
    model: str,
    layer: str,
    group_size: int = 4,
    max_layer_error: float = 0.02,
    task_score: float | None = None,
    minimum_task_score: float | None = None,
    device: str = "android.arm64",
) -> tuple[Any, PrecisionCandidate, QuantizationProof]:
    weight = np.asarray(weight, dtype=np.float32)
    calibration = np.asarray(calibration, dtype=np.float32)
    if weight.ndim != 2 or calibration.ndim != 2 or calibration.shape[1] != weight.shape[0]:
        raise ValueError("weight and calibration shapes are incompatible")
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    calibration_hash = hashlib.sha256(np.ascontiguousarray(calibration).tobytes()).hexdigest()
    candidates: list[tuple[Any, str, int, str]] = []
    # Candidate order is the optimization objective: lower precision first.
    candidates.append((QuantizedMatrix.quantize(weight, 4, group_size), "int4", group_size, "neon.nibble_dot"))
    candidates.append((QuantizedMatrix.quantize(weight, 8, weight.shape[0]), "int8", weight.shape[0], "neon.int8_dot"))
    candidates.append((Float16Matrix(weight), "f16", weight.shape[0], "neon.f16_matmul"))
    for implementation, precision, candidate_group, kernel in candidates:
        error = _mse(weight, calibration, implementation)
        candidate = PrecisionCandidate(precision, candidate_group, error, implementation.storage_bytes, kernel)
        proof = QuantizationProof(model=f"{model}:{layer}", calibration_sha256=calibration_hash, precision=precision, group_size=candidate_group, layer_error=error, task_score=task_score, baseline_task_score=None, max_layer_error=max_layer_error, minimum_task_score=minimum_task_score, kernel=kernel, device=device)
        if proof.verify():
            return implementation, candidate, proof
    raise RuntimeError(f"no precision candidate passed quality gates for {model}:{layer}")


@lru_cache(maxsize=8)
def demo() -> dict[str, Any]:
    rng = np.random.default_rng(7)
    weight = rng.normal(0.0, 0.2, size=(16, 16)).astype(np.float32)
    calibration = rng.normal(size=(32, 16)).astype(np.float32)
    _, candidate, proof = select_matrix(weight, calibration, model="demo", layer="qkv", max_layer_error=0.2)
    return {"candidate": asdict(candidate), "proof_verified": proof.verified, "proof": asdict(proof)}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, sort_keys=True))
