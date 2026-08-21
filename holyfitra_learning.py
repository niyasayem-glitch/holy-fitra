#!/usr/bin/env python3
"""Deterministic training and continual-learning utilities for Holy Fitra.

This module builds on the small NumPy autograd runtime in :mod:`hyperc_nn`.
It intentionally keeps the implementation dependency-free so it can run in
Termux and serve as a reference for future native/AOT lowering.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hyperc_nn import Dense, Tensor, mse, relu


class TrainableMLP:
    """A two-layer trainable MLP with explicit state serialization."""

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int, *, seed: int = 0):
        if min(input_dim, hidden_dim, output_dim) <= 0:
            raise ValueError("MLP dimensions must be positive")
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.output_dim = int(output_dim)
        self.hidden = Dense(self.input_dim, self.hidden_dim, seed=seed)
        self.output = Dense(self.hidden_dim, self.output_dim, seed=seed + 1)

    @property
    def parameters(self) -> tuple[Tensor, ...]:
        return self.hidden.parameters + self.output.parameters

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return ("hidden.weight", "hidden.bias", "output.weight", "output.bias")

    def forward_tensor(self, inputs: Tensor) -> Tensor:
        return self.output(relu(self.hidden(inputs)))

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        array = np.asarray(inputs, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.input_dim:
            raise ValueError("inputs must have shape [batch, input_dim]")
        return self.forward_tensor(Tensor(array)).data.copy()

    def state_dict(self) -> dict[str, np.ndarray]:
        return {name: parameter.data.copy() for name, parameter in zip(self.parameter_names, self.parameters)}

    def load_state_dict(self, state: dict[str, np.ndarray]) -> None:
        expected = set(self.parameter_names)
        if set(state) != expected:
            raise ValueError("model state keys do not match architecture")
        for name, parameter in zip(self.parameter_names, self.parameters):
            value = np.ascontiguousarray(state[name], dtype=np.float32)
            if value.shape != parameter.data.shape or not np.all(np.isfinite(value)):
                raise ValueError(f"invalid state for {name}")
            parameter.data[...] = value


class Adam:
    """Small Adam optimizer with serializable moment state."""

    def __init__(self, parameters: tuple[Tensor, ...], *, learning_rate: float = 1e-3, beta1: float = 0.9, beta2: float = 0.999, epsilon: float = 1e-8):
        if learning_rate <= 0.0 or not 0.0 < beta1 < 1.0 or not 0.0 < beta2 < 1.0 or epsilon <= 0.0:
            raise ValueError("invalid Adam hyperparameters")
        self.learning_rate = float(learning_rate)
        self.beta1 = float(beta1)
        self.beta2 = float(beta2)
        self.epsilon = float(epsilon)
        self.step_count = 0
        self._m = [np.zeros_like(parameter.data) for parameter in parameters]
        self._v = [np.zeros_like(parameter.data) for parameter in parameters]

    def step(self, parameters: tuple[Tensor, ...]) -> None:
        if len(parameters) != len(self._m):
            raise ValueError("optimizer parameter count changed")
        self.step_count += 1
        correction1 = 1.0 - self.beta1**self.step_count
        correction2 = 1.0 - self.beta2**self.step_count
        for index, parameter in enumerate(parameters):
            if parameter.grad is None or not np.all(np.isfinite(parameter.grad)):
                raise FloatingPointError("non-finite gradient rejected")
            gradient = np.asarray(parameter.grad, dtype=np.float32)
            self._m[index] = self.beta1 * self._m[index] + (1.0 - self.beta1) * gradient
            self._v[index] = self.beta2 * self._v[index] + (1.0 - self.beta2) * (gradient * gradient)
            update = (self._m[index] / correction1) / (np.sqrt(self._v[index] / correction2) + self.epsilon)
            if not np.all(np.isfinite(update)):
                raise FloatingPointError("non-finite Adam update rejected")
            parameter.data[...] -= self.learning_rate * update
            if not np.all(np.isfinite(parameter.data)):
                raise FloatingPointError("non-finite parameter update rejected")

    def state_dict(self) -> dict[str, Any]:
        return {"step_count": self.step_count, "m": [value.copy() for value in self._m], "v": [value.copy() for value in self._v], "learning_rate": self.learning_rate, "beta1": self.beta1, "beta2": self.beta2, "epsilon": self.epsilon}

    def load_state_dict(self, state: dict[str, Any], parameters: tuple[Tensor, ...]) -> None:
        if len(state.get("m", ())) != len(parameters) or len(state.get("v", ())) != len(parameters):
            raise ValueError("optimizer state parameter count mismatch")
        self.step_count = int(state["step_count"])
        if self.step_count < 0:
            raise ValueError("optimizer step_count must be non-negative")
        for index, parameter in enumerate(parameters):
            m = np.ascontiguousarray(state["m"][index], dtype=np.float32)
            v = np.ascontiguousarray(state["v"][index], dtype=np.float32)
            if m.shape != parameter.data.shape or v.shape != parameter.data.shape or not np.all(np.isfinite(m)) or not np.all(np.isfinite(v)):
                raise ValueError("invalid optimizer state")
            self._m[index] = m.copy()
            self._v[index] = v.copy()


def zero_grad(parameters: tuple[Tensor, ...]) -> None:
    for parameter in parameters:
        if parameter.grad is not None:
            parameter.grad.fill(0.0)


def clip_grad_norm(parameters: tuple[Tensor, ...], max_norm: float) -> float:
    if max_norm <= 0.0:
        raise ValueError("max_norm must be positive")
    norm = float(np.sqrt(sum(float(np.sum(parameter.grad * parameter.grad)) for parameter in parameters if parameter.grad is not None)))
    if not np.isfinite(norm):
        raise FloatingPointError("non-finite gradient norm rejected")
    if norm > max_norm:
        scale = max_norm / (norm + 1e-12)
        for parameter in parameters:
            if parameter.grad is not None:
                parameter.grad[...] *= scale
    return norm


class ReplayBuffer:
    """Bounded deterministic reservoir replay for continual learning."""

    def __init__(self, capacity: int, *, seed: int = 0):
        if capacity <= 0:
            raise ValueError("replay capacity must be positive")
        self.capacity = int(capacity)
        self._rng = np.random.default_rng(seed)
        self._seen = 0
        self._inputs: list[np.ndarray] = []
        self._targets: list[np.ndarray] = []

    def __len__(self) -> int:
        return len(self._inputs)

    @property
    def seen(self) -> int:
        return self._seen

    def add_batch(self, inputs: np.ndarray, targets: np.ndarray) -> None:
        x = np.asarray(inputs, dtype=np.float32)
        y = np.asarray(targets, dtype=np.float32)
        if x.ndim != 2 or y.ndim != 2 or x.shape[0] != y.shape[0]:
            raise ValueError("replay batch shapes are invalid")
        for row, target in zip(x, y):
            self._seen += 1
            if len(self._inputs) < self.capacity:
                self._inputs.append(np.ascontiguousarray(row))
                self._targets.append(np.ascontiguousarray(target))
            else:
                slot = int(self._rng.integers(0, self._seen))
                if slot < self.capacity:
                    self._inputs[slot] = np.ascontiguousarray(row)
                    self._targets[slot] = np.ascontiguousarray(target)

    def sample(self, count: int) -> tuple[np.ndarray, np.ndarray]:
        if count <= 0 or not self._inputs:
            return np.empty((0, 0), dtype=np.float32), np.empty((0, 0), dtype=np.float32)
        count = min(int(count), len(self._inputs))
        indices = self._rng.choice(len(self._inputs), size=count, replace=False)
        return np.stack([self._inputs[index] for index in indices]), np.stack([self._targets[index] for index in indices])

    def state_dict(self) -> dict[str, Any]:
        if not self._inputs:
            return {"capacity": self.capacity, "seen": self._seen, "inputs": np.empty((0, 0), dtype=np.float32), "targets": np.empty((0, 0), dtype=np.float32)}
        return {"capacity": self.capacity, "seen": self._seen, "inputs": np.stack(self._inputs), "targets": np.stack(self._targets)}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        inputs = np.asarray(state["inputs"], dtype=np.float32)
        targets = np.asarray(state["targets"], dtype=np.float32)
        if inputs.ndim != 2 or targets.ndim != 2 or inputs.shape[0] != targets.shape[0] or inputs.shape[0] > self.capacity:
            raise ValueError("invalid replay state")
        self._seen = int(state["seen"])
        if self._seen < inputs.shape[0]:
            raise ValueError("replay seen count is invalid")
        self._inputs = [np.ascontiguousarray(row) for row in inputs]
        self._targets = [np.ascontiguousarray(row) for row in targets]


@dataclass(frozen=True)
class TrainingConfig:
    epochs: int = 10
    batch_size: int = 32
    replay_ratio: float = 0.25
    max_grad_norm: float = 5.0
    seed: int = 0
    checkpoint_every: int = 0

    def __post_init__(self) -> None:
        if self.epochs <= 0 or self.batch_size <= 0 or not 0.0 <= self.replay_ratio <= 1.0 or self.max_grad_norm <= 0.0 or self.checkpoint_every < 0:
            raise ValueError("invalid training configuration")


@dataclass
class TrainingHistory:
    losses: list[float] = field(default_factory=list)
    eval_losses: list[float] = field(default_factory=list)
    gradient_norms: list[float] = field(default_factory=list)
    optimizer_steps: int = 0

    @property
    def initial_loss(self) -> float:
        return self.losses[0] if self.losses else float("nan")

    @property
    def final_loss(self) -> float:
        return self.losses[-1] if self.losses else float("nan")


def evaluate_mse(model: TrainableMLP, inputs: np.ndarray, targets: np.ndarray) -> float:
    x, y = _validate_dataset(inputs, targets, model.input_dim, model.output_dim)
    prediction = model.predict(x)
    return float(np.mean((prediction - y) ** 2))


def _validate_dataset(inputs: np.ndarray, targets: np.ndarray, input_dim: int, output_dim: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(inputs, dtype=np.float32)
    y = np.asarray(targets, dtype=np.float32)
    if x.ndim != 2 or y.ndim != 2 or x.shape[0] == 0 or x.shape[0] != y.shape[0] or x.shape[1] != input_dim or y.shape[1] != output_dim:
        raise ValueError("dataset shapes do not match model")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("dataset contains non-finite values")
    return np.ascontiguousarray(x), np.ascontiguousarray(y)


def train_supervised(model: TrainableMLP, inputs: np.ndarray, targets: np.ndarray, *, config: TrainingConfig | None = None, optimizer: Adam | None = None, replay: ReplayBuffer | None = None, eval_data: tuple[np.ndarray, np.ndarray] | None = None, checkpoint_path: str | os.PathLike[str] | None = None, threshold_controller: Any | None = None) -> TrainingHistory:
    config = config or TrainingConfig()
    x, y = _validate_dataset(inputs, targets, model.input_dim, model.output_dim)
    if eval_data is not None:
        _validate_dataset(eval_data[0], eval_data[1], model.input_dim, model.output_dim)
    optimizer = optimizer or Adam(model.parameters, learning_rate=1e-2)
    rng = np.random.default_rng(config.seed)
    history = TrainingHistory()
    for epoch in range(config.epochs):
        order = rng.permutation(x.shape[0])
        epoch_losses: list[float] = []
        epoch_norms: list[float] = []
        for start in range(0, x.shape[0], config.batch_size):
            indices = order[start : start + config.batch_size]
            batch_x = x[indices]
            batch_y = y[indices]
            if replay is not None and len(replay) and config.replay_ratio > 0.0:
                replay_count = max(1, int(round(batch_x.shape[0] * config.replay_ratio)))
                replay_x, replay_y = replay.sample(replay_count)
                if replay_x.size:
                    batch_x = np.concatenate((batch_x, replay_x), axis=0)
                    batch_y = np.concatenate((batch_y, replay_y), axis=0)
            zero_grad(model.parameters)
            prediction = model.forward_tensor(Tensor(batch_x))
            loss = mse(prediction, Tensor(batch_y))
            loss.backward()
            epoch_norms.append(clip_grad_norm(model.parameters, config.max_grad_norm))
            optimizer.step(model.parameters)
            epoch_losses.append(float(loss.data.item()))
        if replay is not None:
            replay.add_batch(x, y)
        history.losses.append(float(np.mean(epoch_losses)))
        history.gradient_norms.append(float(np.mean(epoch_norms)))
        history.optimizer_steps = optimizer.step_count
        if eval_data is not None:
            history.eval_losses.append(evaluate_mse(model, eval_data[0], eval_data[1]))
        if checkpoint_path is not None and config.checkpoint_every and (epoch + 1) % config.checkpoint_every == 0:
            save_checkpoint(checkpoint_path, model, optimizer, replay=replay, threshold_controller=threshold_controller, step=epoch + 1, metadata={"loss": history.losses[-1]})
    if checkpoint_path is not None:
        save_checkpoint(checkpoint_path, model, optimizer, replay=replay, threshold_controller=threshold_controller, step=config.epochs, metadata={"loss": history.final_loss})
    return history


def save_checkpoint(path: str | os.PathLike[str], model: TrainableMLP, optimizer: Adam, *, replay: ReplayBuffer | None = None, threshold_controller: Any | None = None, step: int = 0, metadata: dict[str, Any] | None = None) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    for index, parameter in enumerate(model.parameters):
        arrays[f"p{index}"] = parameter.data
    for index, value in enumerate(optimizer._m):
        arrays[f"m{index}"] = value
        arrays[f"v{index}"] = optimizer._v[index]
    if replay is not None:
        replay_state = replay.state_dict()
        arrays["replay_inputs"] = replay_state["inputs"]
        arrays["replay_targets"] = replay_state["targets"]
    manifest = {"version": 1, "step": int(step), "model": {"input_dim": model.input_dim, "hidden_dim": model.hidden_dim, "output_dim": model.output_dim}, "optimizer": {"step_count": optimizer.step_count}, "replay": None if replay is None else {"capacity": replay.capacity, "seen": replay.seen}, "threshold_controller": None if threshold_controller is None else threshold_controller.state_dict(), "metadata": metadata or {}}
    with tempfile.NamedTemporaryFile(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        np.savez_compressed(handle, manifest=np.asarray(json.dumps(manifest, sort_keys=True)), **arrays)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def load_checkpoint(path: str | os.PathLike[str], model: TrainableMLP, optimizer: Adam, *, replay: ReplayBuffer | None = None, threshold_controller: Any | None = None) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as archive:
        manifest = json.loads(str(archive["manifest"].item()))
        if manifest.get("version") != 1 or manifest.get("model") != {"input_dim": model.input_dim, "hidden_dim": model.hidden_dim, "output_dim": model.output_dim}:
            raise ValueError("checkpoint architecture or version mismatch")
        state = {name: np.asarray(archive[f"p{index}"]) for index, name in enumerate(model.parameter_names)}
        model.load_state_dict(state)
        optimizer_state = {"step_count": int(manifest["optimizer"]["step_count"]), "m": [np.asarray(archive[f"m{index}"]) for index in range(len(model.parameters))], "v": [np.asarray(archive[f"v{index}"]) for index in range(len(model.parameters))]}
        optimizer.load_state_dict(optimizer_state, model.parameters)
        if replay is not None and "replay_inputs" in archive and "replay_targets" in archive:
            replay.load_state_dict({"inputs": np.asarray(archive["replay_inputs"]), "targets": np.asarray(archive["replay_targets"]), "seen": int(manifest.get("replay", {}).get("seen", 0))})
        if threshold_controller is not None and manifest.get("threshold_controller") is not None:
            threshold_controller.load_state_dict(manifest["threshold_controller"])
        return manifest


__all__ = ["Adam", "ReplayBuffer", "TrainableMLP", "TrainingConfig", "TrainingHistory", "clip_grad_norm", "evaluate_mse", "load_checkpoint", "save_checkpoint", "train_supervised", "zero_grad"]
