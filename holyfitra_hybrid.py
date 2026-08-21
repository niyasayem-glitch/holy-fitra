#!/usr/bin/env python3
"""First-class hybrid function composition for Holy Fitra runtime code."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class HybridFunctionError(ValueError):
    pass


@dataclass(frozen=True)
class HybridPlan:
    name: str
    components: tuple[str, ...]
    input_arity: int
    max_steps: int
    effects: tuple[str, ...]


class HybridFunction:
    """Compose ``first(*args)`` followed by ``next(value)`` stages."""

    def __init__(self, name: str, functions: tuple[Callable[..., Any], ...], *, effects: tuple[str, ...] = (), max_steps: int | None = None):
        if not name or not name.isidentifier():
            raise HybridFunctionError("hybrid name must be a valid identifier")
        if len(functions) < 2:
            raise HybridFunctionError("a hybrid function requires at least two components")
        if any(not callable(function) for function in functions):
            raise HybridFunctionError("every hybrid component must be callable")
        component_names = tuple(getattr(function, "__name__", f"component_{index}") for index, function in enumerate(functions))
        if len(set(component_names)) != len(component_names):
            raise HybridFunctionError("hybrid components must have unique names")
        if max_steps is None:
            max_steps = len(functions)
        if max_steps < len(functions):
            raise HybridFunctionError("max_steps cannot be below component count")
        normalized_effects = tuple(effects)
        if len(set(normalized_effects)) != len(normalized_effects):
            raise HybridFunctionError("hybrid effects must be unique")
        self.name = name
        self.functions = tuple(functions)
        self.plan = HybridPlan(name, component_names, _required_arity(functions[0]), int(max_steps), normalized_effects)

    @property
    def components(self) -> tuple[str, ...]:
        return self.plan.components

    @property
    def effects(self) -> tuple[str, ...]:
        return self.plan.effects

    def __call__(self, *args: Any) -> Any:
        if len(args) != self.plan.input_arity:
            raise TypeError(f"hybrid {self.name} expects {self.plan.input_arity} arguments, got {len(args)}")
        value = self.functions[0](*args)
        for index, function in enumerate(self.functions[1:], start=1):
            if index >= self.plan.max_steps:
                raise HybridFunctionError("hybrid execution step budget exceeded")
            value = function(value)
        return value

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.plan.name,
            "components": list(self.plan.components),
            "input_arity": self.plan.input_arity,
            "max_steps": self.plan.max_steps,
            "effects": list(self.plan.effects),
        }


def hybrid(name: str, *functions: Callable[..., Any], effects: tuple[str, ...] = (), max_steps: int | None = None) -> HybridFunction:
    return HybridFunction(name, tuple(functions), effects=effects, max_steps=max_steps)


def _required_arity(function: Callable[..., Any]) -> int:
    code = getattr(function, "__code__", None)
    if code is None:
        return 1
    positional = int(code.co_argcount)
    defaults = getattr(function, "__defaults__", None) or ()
    return positional - len(defaults)


__all__ = ["HybridFunction", "HybridFunctionError", "HybridPlan", "hybrid"]
