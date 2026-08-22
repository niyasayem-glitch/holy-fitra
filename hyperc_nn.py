#!/usr/bin/env python3
"""AI-native tensor and autodiff reference runtime for Holy Fitra."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import numpy as np


def _unbroadcast(gradient: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    result = np.asarray(gradient, dtype=np.float32)
    while result.ndim > len(shape):
        result = result.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and result.shape[axis] != 1:
            result = result.sum(axis=axis, keepdims=True)
    return result.reshape(shape)


@dataclass(frozen=True)
class TensorSpec:
    shape: tuple[int, ...]
    dtype: str = "f32"
    device: str = "cpu"

    def __post_init__(self) -> None:
        if not self.shape or any(d <= 0 for d in self.shape):
            raise ValueError("tensor shape must contain positive dimensions")
        if self.dtype not in {"f32", "f16", "bf16", "int8", "int4"}:
            raise ValueError("unsupported tensor dtype")


class Tensor:
    def __init__(self, data, *, requires_grad: bool = False, copy: bool = True, _parents=(), _backward: Callable[[], None] | None = None):
        array = np.asarray(data, dtype=np.float32)
        if array.size == 0 or not np.all(np.isfinite(array)):
            raise ValueError("Tensor data must be non-empty and finite")
        if copy:
            self.data = np.ascontiguousarray(array)
        else:
            if not array.flags.c_contiguous:
                raise ValueError("zero-copy Tensor requires contiguous storage")
            self.data = array
        self.grad: np.ndarray | None = np.zeros_like(self.data) if requires_grad else None
        self.requires_grad = requires_grad
        self._parents = tuple(_parents)
        self._backward = _backward or (lambda: None)

    @classmethod
    def from_buffer(cls, data, *, requires_grad: bool = False) -> "Tensor":
        return cls(data, requires_grad=requires_grad, copy=False)

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self.data.shape)

    @property
    def spec(self) -> TensorSpec:
        return TensorSpec(self.shape)

    def __matmul__(self, other: "Tensor") -> "Tensor":
        if not isinstance(other, Tensor) or self.data.ndim != 2 or other.data.ndim != 2 or self.data.shape[1] != other.data.shape[0]:
            raise ValueError("matrix multiplication requires compatible two-dimensional tensors")
        output = Tensor(self.data @ other.data, requires_grad=self.requires_grad or other.requires_grad, _parents=(self, other))

        def backward() -> None:
            if self.requires_grad:
                self.grad += output.grad @ other.data.T
            if other.requires_grad:
                other.grad += self.data.T @ output.grad

        output._backward = backward
        return output

    def __add__(self, other: "Tensor | float") -> "Tensor":
        other_tensor = other if isinstance(other, Tensor) else Tensor(np.asarray(other, dtype=np.float32))
        output = Tensor(self.data + other_tensor.data, requires_grad=self.requires_grad or other_tensor.requires_grad, _parents=(self, other_tensor))

        def backward() -> None:
            if self.requires_grad:
                self.grad += _unbroadcast(output.grad, self.data.shape)
            if other_tensor.requires_grad:
                other_tensor.grad += _unbroadcast(output.grad, other_tensor.data.shape)

        output._backward = backward
        return output

    def __sub__(self, other: "Tensor") -> "Tensor":
        return self + (other * -1.0)

    def __mul__(self, other: "Tensor | float") -> "Tensor":
        other_tensor = other if isinstance(other, Tensor) else Tensor(np.asarray(other, dtype=np.float32))
        output = Tensor(self.data * other_tensor.data, requires_grad=self.requires_grad or other_tensor.requires_grad, _parents=(self, other_tensor))

        def backward() -> None:
            if self.requires_grad:
                self.grad += _unbroadcast(output.grad * other_tensor.data, self.data.shape)
            if other_tensor.requires_grad:
                other_tensor.grad += _unbroadcast(output.grad * self.data, other_tensor.data.shape)

        output._backward = backward
        return output

    def __rmul__(self, other: float) -> "Tensor":
        return self * other

    def mean(self) -> "Tensor":
        output = Tensor(np.asarray(self.data.mean(), dtype=np.float32), requires_grad=self.requires_grad, _parents=(self,))

        def backward() -> None:
            if self.requires_grad:
                self.grad += np.ones_like(self.data) * output.grad / self.data.size

        output._backward = backward
        return output

    def backward(self, gradient: np.ndarray | None = None) -> None:
        if gradient is not None:
            supplied = np.asarray(gradient, dtype=np.float32)
            if supplied.shape != self.data.shape or not np.all(np.isfinite(supplied)):
                raise ValueError("backward gradient must be finite and match tensor shape")
        order: list[Tensor] = []
        visited: set[int] = set()

        def visit(node: Tensor) -> None:
            if id(node) in visited:
                return
            visited.add(id(node))
            for parent in node._parents:
                visit(parent)
            order.append(node)

        visit(self)
        if self.grad is None:
            self.grad = np.ones_like(self.data) if gradient is None else supplied
        else:
            self.grad[...] = np.ones_like(self.data) if gradient is None else supplied
        for node in reversed(order):
            node._backward()


def relu(value: Tensor) -> Tensor:
    output = Tensor(np.maximum(value.data, 0.0), requires_grad=value.requires_grad, _parents=(value,))

    def backward() -> None:
        if value.requires_grad:
            value.grad += output.grad * (value.data > 0.0)

    output._backward = backward
    return output


class Dense:
    def __init__(self, input_dim: int, output_dim: int, seed: int = 0):
        if not isinstance(input_dim, int) or isinstance(input_dim, bool) or not isinstance(output_dim, int) or isinstance(output_dim, bool) or input_dim <= 0 or output_dim <= 0:
            raise ValueError("Dense dimensions must be positive integers")
        rng = np.random.default_rng(seed)
        self.weight = Tensor(rng.normal(0.0, 1.0 / np.sqrt(input_dim), (input_dim, output_dim)), requires_grad=True)
        self.bias = Tensor(np.zeros(output_dim, dtype=np.float32), requires_grad=True)

    def __call__(self, inputs: Tensor) -> Tensor:
        return inputs @ self.weight + self.bias

    @property
    def parameters(self) -> tuple[Tensor, ...]:
        return self.weight, self.bias


def mse(prediction: Tensor, target: Tensor) -> Tensor:
    if prediction.shape != target.shape:
        raise ValueError("MSE tensors must have identical shapes")
    difference = prediction - target
    return (difference * difference).mean()


def demo() -> dict[str, object]:
    rng = np.random.default_rng(7)
    layer = Dense(4, 2, seed=11)
    inputs = Tensor(rng.normal(size=(8, 4)), requires_grad=False)
    target = Tensor(rng.normal(size=(8, 2)), requires_grad=False)
    prediction = relu(layer(inputs))
    loss = mse(prediction, target)
    loss.backward()
    return {"input_shape": inputs.shape, "prediction_shape": prediction.shape, "loss": float(loss.data.item()), "weight_grad_norm": float(np.linalg.norm(layer.weight.grad))}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, sort_keys=True))
