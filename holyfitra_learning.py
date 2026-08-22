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
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (input_dim, hidden_dim, output_dim)):
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
        if any(not np.isfinite(value) for value in (learning_rate, beta1, beta2, epsilon)) or learning_rate <= 0.0 or not 0.0 < beta1 < 1.0 or not 0.0 < beta2 < 1.0 or epsilon <= 0.0:
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
        next_step = self.step_count + 1
        correction1 = 1.0 - self.beta1**next_step
        correction2 = 1.0 - self.beta2**next_step
        proposals: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        for index, parameter in enumerate(parameters):
            if parameter.data.shape != self._m[index].shape or parameter.data.shape != self._v[index].shape:
                raise ValueError("optimizer parameter shape changed")
            if not np.all(np.isfinite(parameter.data)) or parameter.grad is None or not np.all(np.isfinite(parameter.grad)):
                raise FloatingPointError("non-finite gradient rejected")
            gradient = np.asarray(parameter.grad, dtype=np.float32)
            next_m = self.beta1 * self._m[index] + (1.0 - self.beta1) * gradient
            next_v = self.beta2 * self._v[index] + (1.0 - self.beta2) * (gradient * gradient)
            update = (next_m / correction1) / (np.sqrt(next_v / correction2) + self.epsilon)
            next_data = parameter.data - self.learning_rate * update
            if not np.all(np.isfinite(next_m)) or not np.all(np.isfinite(next_v)) or not np.all(np.isfinite(update)) or not np.all(np.isfinite(next_data)):
                raise FloatingPointError("non-finite Adam update rejected")
            proposals.append((next_m, next_v, next_data))
        self.step_count = next_step
        for index, parameter in enumerate(parameters):
            next_m, next_v, next_data = proposals[index]
            self._m[index] = next_m
            self._v[index] = next_v
            parameter.data[...] = next_data

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
    if not np.isfinite(max_norm) or max_norm <= 0.0:
        raise ValueError("max_norm must be finite and positive")
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
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("replay capacity must be positive")
        self.capacity = int(capacity)
        self._rng = np.random.default_rng(seed)
        self._seen = 0
        self._inputs: list[np.ndarray] = []
        self._targets: list[np.ndarray] = []
        self._input_shape: tuple[int, ...] | None = None
        self._target_shape: tuple[int, ...] | None = None

    def __len__(self) -> int:
        return len(self._inputs)

    @property
    def seen(self) -> int:
        return self._seen

    def add_batch(self, inputs: np.ndarray, targets: np.ndarray) -> None:
        x = np.asarray(inputs, dtype=np.float32)
        y = np.asarray(targets, dtype=np.float32)
        if x.ndim != 2 or y.ndim != 2 or x.shape[0] == 0 or x.shape[0] != y.shape[0] or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("replay batch shapes or values are invalid")
        if self._input_shape is None:
            self._input_shape = tuple(x.shape[1:])
            self._target_shape = tuple(y.shape[1:])
        if tuple(x.shape[1:]) != self._input_shape or tuple(y.shape[1:]) != self._target_shape:
            raise ValueError("replay feature or target shape changed")
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
        if inputs.ndim != 2 or targets.ndim != 2 or inputs.shape[0] != targets.shape[0] or inputs.shape[0] > self.capacity or not np.all(np.isfinite(inputs)) or not np.all(np.isfinite(targets)):
            raise ValueError("invalid replay state")
        self._seen = int(state["seen"])
        if self._seen < 0 or self._seen < inputs.shape[0]:
            raise ValueError("replay seen count is invalid")
        self._input_shape = tuple(inputs.shape[1:]) if inputs.shape[0] else None
        self._target_shape = tuple(targets.shape[1:]) if targets.shape[0] else None
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
    shuffle_buffer: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.epochs, int) or isinstance(self.epochs, bool) or not isinstance(self.batch_size, int) or isinstance(self.batch_size, bool) or not isinstance(self.checkpoint_every, int) or isinstance(self.checkpoint_every, bool) or not isinstance(self.shuffle_buffer, int) or isinstance(self.shuffle_buffer, bool) or any(not np.isfinite(value) for value in (self.replay_ratio, self.max_grad_norm)) or self.epochs <= 0 or self.batch_size <= 0 or not 0.0 <= self.replay_ratio <= 1.0 or self.max_grad_norm <= 0.0 or self.checkpoint_every < 0 or self.shuffle_buffer < 0:
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


def evaluate_streaming_mse(model: TrainableMLP, dataset: Any, *, batch_size: int = 256) -> float:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    total = 0.0
    count = 0
    for batch in dataset.iter_batches(batch_size, shuffle=False):
        _validate_dataset(batch.inputs, batch.targets, model.input_dim, model.output_dim)
        error = model.predict(batch.inputs) - batch.targets
        total += float(np.sum(error * error, dtype=np.float64))
        count += int(error.size)
    if count == 0:
        raise ValueError("streaming evaluation dataset is empty")
    return total / count


def train_supervised_streaming(model: TrainableMLP, dataset: Any, *, config: TrainingConfig | None = None, optimizer: Adam | None = None, replay: ReplayBuffer | None = None, eval_data: Any | None = None, checkpoint_path: str | os.PathLike[str] | None = None, threshold_controller: Any | None = None) -> TrainingHistory:
    """Train from a repeatable StreamingDataset without materializing all samples."""
    config = config or TrainingConfig()
    optimizer = optimizer or Adam(model.parameters, learning_rate=1e-2)
    history = TrainingHistory()
    shuffle_buffer = config.shuffle_buffer or max(config.batch_size * 4, config.batch_size)
    for epoch in range(config.epochs):
        epoch_losses: list[float] = []
        epoch_norms: list[float] = []
        for batch in dataset.iter_batches(config.batch_size, epoch=epoch, shuffle=True, shuffle_buffer=shuffle_buffer):
            _validate_dataset(batch.inputs, batch.targets, model.input_dim, model.output_dim)
            batch_x, batch_y = batch.inputs, batch.targets
            if replay is not None and len(replay) and config.replay_ratio > 0.0:
                replay_count = max(1, int(round(batch_x.shape[0] * config.replay_ratio)))
                replay_x, replay_y = replay.sample(replay_count)
                if replay_x.size:
                    batch_x = np.concatenate((batch_x, replay_x), axis=0)
                    batch_y = np.concatenate((batch_y, replay_y), axis=0)
            zero_grad(model.parameters)
            loss = mse(model.forward_tensor(Tensor(batch_x)), Tensor(batch_y))
            loss.backward()
            epoch_norms.append(clip_grad_norm(model.parameters, config.max_grad_norm))
            optimizer.step(model.parameters)
            if replay is not None:
                replay.add_batch(batch.inputs, batch.targets)
            epoch_losses.append(float(loss.data.item()))
        if not epoch_losses:
            raise ValueError("streaming training dataset is empty")
        history.losses.append(float(np.mean(epoch_losses)))
        history.gradient_norms.append(float(np.mean(epoch_norms)))
        history.optimizer_steps = optimizer.step_count
        if eval_data is not None:
            history.eval_losses.append(evaluate_streaming_mse(model, eval_data, batch_size=config.batch_size))
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


__all__ = ["Adam", "ReplayBuffer", "TrainableMLP", "TrainingConfig", "TrainingHistory", "clip_grad_norm", "evaluate_mse", "evaluate_streaming_mse", "load_checkpoint", "save_checkpoint", "train_supervised", "train_supervised_streaming", "zero_grad"]
