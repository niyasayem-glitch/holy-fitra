#!/usr/bin/env python3
"""Bounded policy-gradient control for Holy Fitra runtime thresholds."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np


@dataclass(frozen=True)
class ThresholdAction:
    threshold_delta: int
    bonus_delta: int


class ThresholdPolicyGradient:
    """Small on-policy REINFORCE controller with hard safety bounds.

    The controller tunes only two cache-policy integers. It is intentionally
    separate from model weights so exploration cannot alter model numerics or
    bypass quantization quality gates.
    """

    ACTIONS = tuple(ThresholdAction(t, b) for t in (-1, 0, 1) for b in (-1, 0, 1))

    def __init__(self, *, min_threshold: int = 1, max_threshold: int = 16, min_bonus: int = 0, max_bonus: int = 8, learning_rate: float = 0.05, baseline_rate: float = 0.1, entropy_coefficient: float = 0.005, exploration: float = 0.1, seed: int = 0):
        if not 1 <= min_threshold <= max_threshold <= 64 or not 0 <= min_bonus <= max_bonus <= 16:
            raise ValueError("invalid threshold safety bounds")
        if learning_rate <= 0.0 or not 0.0 < baseline_rate <= 1.0 or entropy_coefficient < 0.0 or not 0.0 <= exploration <= 1.0:
            raise ValueError("invalid policy-gradient hyperparameters")
        self.min_threshold = int(min_threshold)
        self.max_threshold = int(max_threshold)
        self.min_bonus = int(min_bonus)
        self.max_bonus = int(max_bonus)
        self.learning_rate = float(learning_rate)
        self.baseline_rate = float(baseline_rate)
        self.entropy_coefficient = float(entropy_coefficient)
        self.exploration = float(exploration)
        self._rng = np.random.default_rng(seed)
        self.weights = np.zeros((len(self.ACTIONS), 6), dtype=np.float64)
        self.baseline = 0.0
        self.update_count = 0
        self._last_features: np.ndarray | None = None
        self._last_action: int | None = None
        self._last_policy: np.ndarray | None = None

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits)
        values = np.exp(shifted)
        return values / np.sum(values)

    def features(self, stats: dict[str, Any], batch_rows: int, *, current_threshold: int, current_bonus: int) -> np.ndarray:
        if batch_rows <= 0:
            raise ValueError("batch_rows must be positive")
        values = np.asarray([
            float(stats.get("frequency_ewma", 0.0)),
            min(1.0, float(stats.get("hot_streak", 0)) / 8.0),
            min(2.0, float(batch_rows) / 512.0) / 2.0,
            1.0 if stats.get("promoted", False) else 0.0,
            min(1.0, float(stats.get("cache_bytes", 0)) / max(1.0, float(stats.get("raw_weight_bytes", 1)))),
            1.0,
        ], dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise ValueError("non-finite policy observation")
        return values

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        vector = np.asarray(features, dtype=np.float64)
        if vector.shape != (6,) or not np.all(np.isfinite(vector)):
            raise ValueError("policy features must have shape (6,)")
        return self._softmax(self.weights @ vector)

    def decide(self, stats: dict[str, Any], batch_rows: int, *, current_threshold: int, current_bonus: int) -> dict[str, Any]:
        features = self.features(stats, batch_rows, current_threshold=current_threshold, current_bonus=current_bonus)
        probabilities = self.probabilities(features)
        if self.exploration > 0.0 and float(self._rng.random()) < self.exploration:
            action_index = int(self._rng.integers(len(self.ACTIONS)))
        else:
            action_index = int(np.argmax(probabilities))
        action = self.ACTIONS[action_index]
        next_threshold = int(np.clip(current_threshold + action.threshold_delta, self.min_threshold, self.max_threshold))
        next_bonus = int(np.clip(current_bonus + action.bonus_delta, self.min_bonus, self.max_bonus))
        self._last_features = features
        self._last_action = action_index
        self._last_policy = probabilities
        return {"action_index": action_index, "threshold_delta": action.threshold_delta, "bonus_delta": action.bonus_delta, "promote_after": next_threshold, "large_batch_bonus": next_bonus, "probabilities": probabilities.copy()}

    def update(self, reward: float) -> float:
        if self._last_features is None or self._last_action is None or self._last_policy is None:
            raise RuntimeError("decide must be called before update")
        value = float(reward)
        if not np.isfinite(value):
            raise FloatingPointError("non-finite policy reward rejected")
        advantage = float(np.clip(value - self.baseline, -10.0, 10.0))
        self.baseline += self.baseline_rate * (value - self.baseline)
        gradient = -self._last_policy[:, None] * self._last_features[None, :]
        gradient[self._last_action] += self._last_features
        entropy_gradient = -np.log(np.maximum(self._last_policy, 1e-12))[:, None] * self._last_features[None, :]
        gradient += self.entropy_coefficient * entropy_gradient
        gradient = np.clip(gradient * advantage, -10.0, 10.0)
        self.weights += self.learning_rate * gradient
        if not np.all(np.isfinite(self.weights)):
            raise FloatingPointError("non-finite policy update rejected")
        self.update_count += 1
        return advantage

    @staticmethod
    def reward(*, latency_ms: float, cache_bytes: int, raw_weight_bytes: int, quality_error: float = 0.0, quality_limit: float = 1.0, latency_scale: float = 1.0, memory_scale: float = 0.5) -> float:
        if latency_ms < 0.0 or cache_bytes < 0 or raw_weight_bytes <= 0 or quality_error < 0.0 or quality_limit <= 0.0:
            raise ValueError("invalid cache reward inputs")
        if quality_error > quality_limit:
            return -10.0
        memory_ratio = min(4.0, cache_bytes / float(raw_weight_bytes))
        return float(-(latency_scale * latency_ms) - (memory_scale * memory_ratio))

    def state_dict(self) -> dict[str, Any]:
        return {"version": 1, "bounds": [self.min_threshold, self.max_threshold, self.min_bonus, self.max_bonus], "learning_rate": self.learning_rate, "baseline_rate": self.baseline_rate, "entropy_coefficient": self.entropy_coefficient, "exploration": self.exploration, "weights": self.weights.tolist(), "baseline": self.baseline, "update_count": self.update_count}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("version") != 1 or list(state.get("bounds", [])) != [self.min_threshold, self.max_threshold, self.min_bonus, self.max_bonus]:
            raise ValueError("policy state version or bounds mismatch")
        weights = np.asarray(state["weights"], dtype=np.float64)
        if weights.shape != self.weights.shape or not np.all(np.isfinite(weights)):
            raise ValueError("invalid policy weights")
        self.weights[...] = weights
        self.baseline = float(state["baseline"])
        self.update_count = int(state["update_count"])
        if not np.isfinite(self.baseline) or self.update_count < 0:
            raise ValueError("invalid policy state counters")

    @property
    def stats(self) -> dict[str, Any]:
        return {"version": 1, "updates": self.update_count, "baseline": self.baseline, "weight_norm": float(np.linalg.norm(self.weights)), "bounds": [self.min_threshold, self.max_threshold, self.min_bonus, self.max_bonus]}


def train_policy_on_feedback(controller: ThresholdPolicyGradient, feedback: Iterable[tuple[dict[str, Any], int, int, int, float]], *, initial_threshold: int = 4, initial_bonus: int = 2) -> list[dict[str, Any]]:
    """Run deterministic policy-gradient updates over runtime feedback.

    Each item is `(stats, batch_rows, current_threshold, current_bonus, reward)`.
    The returned actions are safe bounded recommendations.
    """
    threshold, bonus = initial_threshold, initial_bonus
    history: list[dict[str, Any]] = []
    for stats, batch_rows, current_threshold, current_bonus, reward in feedback:
        decision = controller.decide(stats, batch_rows, current_threshold=current_threshold if current_threshold is not None else threshold, current_bonus=current_bonus if current_bonus is not None else bonus)
        advantage = controller.update(reward)
        threshold, bonus = decision["promote_after"], decision["large_batch_bonus"]
        history.append({"threshold": threshold, "large_batch_bonus": bonus, "action_index": decision["action_index"], "advantage": advantage, "reward": float(reward)})
    return history


__all__ = ["ThresholdAction", "ThresholdPolicyGradient", "train_policy_on_feedback"]
