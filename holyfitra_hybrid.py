#!/usr/bin/env python3
"""First-class sequential and parallel hybrid function composition."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable


class HybridFunctionError(ValueError):
    pass


@dataclass(frozen=True)
class TypedReducer:
    """Reducer contract for parallel branch results."""

    function: Callable[[tuple[Any, ...]], Any]
    input_type: type | tuple[type, ...]
    output_type: type | tuple[type, ...]
    name: str = "reducer"

    def __post_init__(self) -> None:
        if not callable(self.function) or not self.name or not self.name.isidentifier():
            raise HybridFunctionError("typed reducer requires a callable and valid name")
        if not isinstance(self.input_type, tuple) and not isinstance(self.input_type, type):
            raise HybridFunctionError("reducer input_type must be a type or type tuple")
        if not isinstance(self.output_type, tuple) and not isinstance(self.output_type, type):
            raise HybridFunctionError("reducer output_type must be a type or type tuple")

    def __call__(self, values: tuple[Any, ...]) -> Any:
        if not all(isinstance(value, self.input_type) for value in values):
            raise HybridFunctionError(f"reducer {self.name} received a value outside its input type")
        result = self.function(values)
        if not isinstance(result, self.output_type):
            raise HybridFunctionError(f"reducer {self.name} returned a value outside its output type")
        return result


@dataclass(frozen=True)
class HybridPlan:
    name: str
    components: tuple[str, ...]
    input_arity: int
    max_steps: int
    effects: tuple[str, ...]
    mode: str = "pipe"
    reducer: str | None = None
    max_workers: int = 1


class HybridFunction:
    """Compose sequential stages or execute parallel branches and reduce them."""

    def __init__(self, name: str, functions: tuple[Callable[..., Any], ...], *, effects: tuple[str, ...] = (), max_steps: int | None = None, mode: str = "pipe", reducer: TypedReducer | None = None, max_workers: int | None = None):
        if not name or not name.isidentifier():
            raise HybridFunctionError("hybrid name must be a valid identifier")
        if len(functions) < 2:
            raise HybridFunctionError("a hybrid function requires at least two components")
        if any(not callable(function) for function in functions):
            raise HybridFunctionError("every hybrid component must be callable")
        if mode not in {"pipe", "parallel"}:
            raise HybridFunctionError("hybrid mode must be pipe or parallel")
        component_names = tuple(getattr(function, "__name__", f"component_{index}") for index, function in enumerate(functions))
        if len(set(component_names)) != len(component_names):
            raise HybridFunctionError("hybrid components must have unique names")
        if max_steps is None:
            max_steps = len(functions)
        if max_steps < len(functions) or max_steps > 4096:
            raise HybridFunctionError("max_steps is outside the safe hybrid bound")
        normalized_effects = tuple(effects)
        if len(set(normalized_effects)) != len(normalized_effects):
            raise HybridFunctionError("hybrid effects must be unique")
        input_arity = _required_arity(functions[0])
        if mode == "parallel":
            if reducer is None:
                raise HybridFunctionError("parallel hybrids require a typed reducer")
            if not isinstance(reducer, TypedReducer):
                raise HybridFunctionError("parallel reducer must be a TypedReducer")
            if any(_required_arity(function) != input_arity for function in functions):
                raise HybridFunctionError("parallel branches must have the same input arity")
            requested_workers = 32 if max_workers is None else int(max_workers)
            if requested_workers <= 0 or requested_workers > 32:
                raise HybridFunctionError("max_workers must be between 1 and 32")
            workers = min(len(functions), requested_workers)
            if workers <= 0 or workers > 32:
                raise HybridFunctionError("max_workers must be between 1 and 32")
        else:
            if reducer is not None:
                raise HybridFunctionError("sequential hybrids cannot specify a reducer")
            workers = 1
        self.name = name
        self.functions = tuple(functions)
        self.reducer = reducer
        self.plan = HybridPlan(name, component_names, input_arity, int(max_steps), normalized_effects, mode, reducer.name if reducer else None, workers)

    @property
    def components(self) -> tuple[str, ...]:
        return self.plan.components

    @property
    def effects(self) -> tuple[str, ...]:
        return self.plan.effects

    def __call__(self, *args: Any, cancel_event: Event | None = None) -> Any:
        if len(args) != self.plan.input_arity:
            raise TypeError(f"hybrid {self.name} expects {self.plan.input_arity} arguments, got {len(args)}")
        if cancel_event is not None and cancel_event.is_set():
            raise HybridFunctionError(f"hybrid {self.name} was cancelled")
        if self.plan.mode == "parallel":
            return self._invoke_parallel(args, cancel_event)
        value = self.functions[0](*args)
        for index, function in enumerate(self.functions[1:], start=1):
            if cancel_event is not None and cancel_event.is_set():
                raise HybridFunctionError(f"hybrid {self.name} was cancelled")
            if index >= self.plan.max_steps:
                raise HybridFunctionError("hybrid execution step budget exceeded")
            value = function(value)
        return value

    def _invoke_parallel(self, args: tuple[Any, ...], cancel_event: Event | None) -> Any:
        assert self.reducer is not None
        futures: list[Future[Any]] = []
        executor = ThreadPoolExecutor(max_workers=self.plan.max_workers, thread_name_prefix=f"hf-{self.name}")
        try:
            for function in self.functions:
                if cancel_event is not None and cancel_event.is_set():
                    raise HybridFunctionError(f"hybrid {self.name} was cancelled")
                futures.append(executor.submit(function, *args))
            results: list[Any] = []
            for future in futures:
                if cancel_event is not None and cancel_event.is_set():
                    raise HybridFunctionError(f"hybrid {self.name} was cancelled")
                try:
                    results.append(future.result())
                except Exception as error:
                    raise HybridFunctionError(f"hybrid branch failed: {error}") from error
            return self.reducer(tuple(results))
        except Exception:
            for future in futures:
                future.cancel()
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.plan.name,
            "components": list(self.plan.components),
            "input_arity": self.plan.input_arity,
            "max_steps": self.plan.max_steps,
            "effects": list(self.plan.effects),
            "mode": self.plan.mode,
            "reducer": self.plan.reducer,
            "max_workers": self.plan.max_workers,
        }


def hybrid(name: str, *functions: Callable[..., Any], effects: tuple[str, ...] = (), max_steps: int | None = None, mode: str = "pipe", reducer: TypedReducer | None = None, max_workers: int | None = None) -> HybridFunction:
    return HybridFunction(name, tuple(functions), effects=effects, max_steps=max_steps, mode=mode, reducer=reducer, max_workers=max_workers)


def parallel_hybrid(name: str, *functions: Callable[..., Any], reducer: TypedReducer, effects: tuple[str, ...] = (), max_steps: int | None = None, max_workers: int | None = None) -> HybridFunction:
    return hybrid(name, *functions, effects=effects, max_steps=max_steps, mode="parallel", reducer=reducer, max_workers=max_workers)


def _required_arity(function: Callable[..., Any]) -> int:
    code = getattr(function, "__code__", None)
    if code is None:
        return 1
    positional = int(code.co_argcount)
    defaults = getattr(function, "__defaults__", None) or ()
    return positional - len(defaults)


__all__ = ["HybridFunction", "HybridFunctionError", "HybridPlan", "TypedReducer", "hybrid", "parallel_hybrid"]
