#!/usr/bin/env python3
"""Lightweight model development primitives for Holy Fitra.

The module intentionally builds on the dependency-free Tensor and Adam runtime:
base weights can stay frozen while a small low-rank adapter learns a task-specific
update. Model manifests and budgets make compact deployment measurable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hyperc_nn import Tensor


class ResourceBudgetError(ValueError):
    pass


@dataclass(frozen=True)
class ResourceBudget:
    max_total_parameters: int | None = None
    max_trainable_parameters: int | None = None
    max_weight_bytes: int | None = None
    min_density: float = 0.0

    def __post_init__(self) -> None:
        for value in (self.max_total_parameters, self.max_trainable_parameters, self.max_weight_bytes):
            if value is not None and value <= 0:
                raise ValueError("resource limits must be positive")
        if not 0.0 <= self.min_density <= 1.0:
            raise ValueError("min_density must be in [0, 1]")


@dataclass(frozen=True)
class ModelManifest:
    model_type: str
    input_dim: int
    output_dim: int
    rank: int
    alpha: float
    base_parameters: int
    trainable_parameters: int
    total_parameters: int
    weight_bytes: int
    density: float
    adapter_only: bool = True

    def __post_init__(self) -> None:
        if self.input_dim <= 0 or self.output_dim <= 0 or self.rank <= 0 or self.alpha <= 0.0:
            raise ValueError("invalid model manifest dimensions")
        if min(self.base_parameters, self.trainable_parameters, self.total_parameters, self.weight_bytes) < 0:
            raise ValueError("manifest counts must be non-negative")
        if not 0.0 <= self.density <= 1.0:
            raise ValueError("manifest density must be in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
            "rank": self.rank,
            "alpha": self.alpha,
            "base_parameters": self.base_parameters,
            "trainable_parameters": self.trainable_parameters,
            "total_parameters": self.total_parameters,
            "weight_bytes": self.weight_bytes,
            "density": self.density,
            "adapter_only": self.adapter_only,
        }


@dataclass(frozen=True)
class PruneReport:
    requested_sparsity: float
    actual_sparsity: float
    zeroed_parameters: int
    remaining_parameters: int


class LoRAAdapter:
    """Frozen dense base plus trainable low-rank update: W + alpha/rank * A @ B."""

    def __init__(self, base_weight: np.ndarray, *, base_bias: np.ndarray | None = None, rank: int = 4, alpha: float = 8.0, seed: int = 0):
        weight = np.ascontiguousarray(np.asarray(base_weight, dtype=np.float32))
        if weight.ndim != 2 or min(weight.shape) <= 0:
            raise ValueError("base_weight must be a non-empty matrix")
        if rank <= 0 or rank > max(weight.shape) or alpha <= 0.0:
            raise ValueError("invalid LoRA rank or alpha")
        self.input_dim, self.output_dim = map(int, weight.shape)
        self.rank = int(rank)
        self.alpha = float(alpha)
        self.base_weight = weight.copy()
        if base_bias is None:
            self.base_bias = np.zeros(self.output_dim, dtype=np.float32)
        else:
            self.base_bias = np.ascontiguousarray(np.asarray(base_bias, dtype=np.float32))
            if self.base_bias.shape != (self.output_dim,):
                raise ValueError("base_bias shape mismatch")
        rng = np.random.default_rng(seed)
        self.A = Tensor(rng.normal(0.0, 0.02, (self.input_dim, self.rank)), requires_grad=True)
        self.B = Tensor(np.zeros((self.rank, self.output_dim), dtype=np.float32), requires_grad=True)
        self._base_mask = np.ones_like(self.base_weight, dtype=np.float32)

    @property
    def parameters(self) -> tuple[Tensor, Tensor]:
        return self.A, self.B

    @property
    def trainable_parameter_count(self) -> int:
        return int(self.A.data.size + self.B.data.size)

    @property
    def base_parameter_count(self) -> int:
        return int(self.base_weight.size + self.base_bias.size)

    @property
    def total_parameter_count(self) -> int:
        return self.base_parameter_count + self.trainable_parameter_count

    @property
    def trainable_ratio(self) -> float:
        return self.trainable_parameter_count / max(1, self.total_parameter_count)

    def forward(self, inputs: Tensor) -> Tensor:
        if inputs.data.ndim != 2 or inputs.data.shape[1] != self.input_dim:
            raise ValueError("inputs must have shape [batch, input_dim]")
        base = Tensor(self.base_weight * self._base_mask, requires_grad=False)
        bias = Tensor(self.base_bias, requires_grad=False)
        update = (self.A @ self.B) * (self.alpha / self.rank)
        return inputs @ (base + update) + bias

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        return self.forward(Tensor(np.asarray(inputs, dtype=np.float32))).data.copy()

    def merged_weight(self) -> np.ndarray:
        update = (self.A.data @ self.B.data) * (self.alpha / self.rank)
        return np.ascontiguousarray(self.base_weight * self._base_mask + update, dtype=np.float32)

    def merged_bias(self) -> np.ndarray:
        return self.base_bias.copy()

    def prune_base(self, sparsity: float) -> PruneReport:
        mask, report = magnitude_prune(self.base_weight, sparsity)
        self._base_mask = mask
        return report

    def manifest(self) -> ModelManifest:
        merged = self.merged_weight()
        return ModelManifest("lora_dense", self.input_dim, self.output_dim, self.rank, self.alpha, self.base_parameter_count, self.trainable_parameter_count, self.total_parameter_count, int(merged.nbytes + self.base_bias.nbytes), float(np.count_nonzero(merged) / merged.size), True)

    def enforce_budget(self, budget: ResourceBudget) -> ModelManifest:
        manifest = self.manifest()
        if budget.max_total_parameters is not None and manifest.total_parameters > budget.max_total_parameters:
            raise ResourceBudgetError("total parameter budget exceeded")
        if budget.max_trainable_parameters is not None and manifest.trainable_parameters > budget.max_trainable_parameters:
            raise ResourceBudgetError("trainable parameter budget exceeded")
        if budget.max_weight_bytes is not None and manifest.weight_bytes > budget.max_weight_bytes:
            raise ResourceBudgetError("weight byte budget exceeded")
        if manifest.density < budget.min_density:
            raise ResourceBudgetError("minimum density contract violated")
        return manifest

    def state_dict(self) -> dict[str, np.ndarray]:
        return {"A": self.A.data.copy(), "B": self.B.data.copy(), "base_mask": self._base_mask.copy()}

    def load_state_dict(self, state: dict[str, np.ndarray]) -> None:
        if set(state) != {"A", "B", "base_mask"}:
            raise ValueError("adapter state keys do not match")
        for target, source in ((self.A, state["A"]), (self.B, state["B"])):
            value = np.ascontiguousarray(source, dtype=np.float32)
            if value.shape != target.data.shape or not np.all(np.isfinite(value)):
                raise ValueError("invalid adapter state")
            target.data[...] = value
        mask = np.ascontiguousarray(state["base_mask"], dtype=np.float32)
        if mask.shape != self.base_weight.shape or not np.all(np.isin(mask, (0.0, 1.0))):
            raise ValueError("invalid base mask")
        self._base_mask = mask.copy()


def magnitude_prune(weight: np.ndarray, sparsity: float) -> tuple[np.ndarray, PruneReport]:
    """Zero the smallest magnitudes deterministically and return a binary mask."""
    values = np.asarray(weight, dtype=np.float32)
    if values.ndim != 2 or not 0.0 <= sparsity < 1.0:
        raise ValueError("weight must be a matrix and sparsity must be in [0, 1)")
    count = int(np.floor(values.size * sparsity))
    flat_abs = np.abs(values).reshape(-1)
    order = np.argsort(flat_abs, kind="stable")
    mask = np.ones(values.size, dtype=np.float32)
    if count:
        mask[order[:count]] = 0.0
    mask = mask.reshape(values.shape)
    report = PruneReport(float(sparsity), float(np.count_nonzero(mask == 0.0) / mask.size), int(np.count_nonzero(mask == 0.0)), int(np.count_nonzero(mask)))
    return mask, report


def enforce_model_budget(manifest: ModelManifest, budget: ResourceBudget) -> ModelManifest:
    if budget.max_total_parameters is not None and manifest.total_parameters > budget.max_total_parameters:
        raise ResourceBudgetError("total parameter budget exceeded")
    if budget.max_trainable_parameters is not None and manifest.trainable_parameters > budget.max_trainable_parameters:
        raise ResourceBudgetError("trainable parameter budget exceeded")
    if budget.max_weight_bytes is not None and manifest.weight_bytes > budget.max_weight_bytes:
        raise ResourceBudgetError("weight byte budget exceeded")
    if manifest.density < budget.min_density:
        raise ResourceBudgetError("minimum density contract violated")
    return manifest


__all__ = ["LoRAAdapter", "ModelManifest", "PruneReport", "ResourceBudget", "ResourceBudgetError", "enforce_model_budget", "magnitude_prune"]
