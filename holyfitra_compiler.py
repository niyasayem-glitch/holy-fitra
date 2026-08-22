#!/usr/bin/env python3
"""Holy Fitra compiler driver.

This is the first native compiler layer for Holy Fitra.  It deliberately keeps
hyperc_language_core.py as the compatibility frontend for tensor/HyperIR
programs, while adding a real lexer, recursive-descent parser, typed scalar
AST, LLVM IR emitter, cache, and build/run CLI for executable programs.

Supported native source subset:

module name
fn add(a: i32, b: i32) -> i32 {
    let c = a + b
    return c
}

fn main() -> i32 { return add(40, 2) }
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from holyfitra_safety import Frontend, MAX_AST_DEPTH, MAX_FUNCTIONS, MAX_TOKENS, parse_frontend, read_source


_MEMORY_COMPILE_CACHE: OrderedDict[str, tuple["Program", str]] = OrderedDict()
_MEMORY_COMPILE_CACHE_LIMIT = 32
_EFFECT_GRAPH_CACHE: OrderedDict[object, tuple[dict[str, set[str]], dict[str, set[str]]]] = OrderedDict()
_EFFECT_GRAPH_CACHE_LIMIT = 64
_LLVM_CACHE_SCHEMA = 3
_NATIVE_COMPILER_ABI = "holyfitra-native-scalar-v2"


class HolyFitraError(Exception):
    """A user-facing compilation error."""


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


@dataclass(frozen=True)
class Type:
    name: str
    mode: str = "owned"

    @property
    def llvm(self) -> str:
        mapping = {"i32": "i32", "i64": "i64", "bool": "i1"}
        if self.name not in mapping:
            raise HolyFitraError(f"native LLVM backend does not yet support type {self.name}")
        return mapping[self.name]


@dataclass(frozen=True)
class Expr:
    pass


@dataclass(frozen=True)
class BoolLiteral(Expr):
    value: bool


@dataclass(frozen=True)
class IntLiteral(Expr):
    value: int


@dataclass(frozen=True)
class NameExpr(Expr):
    name: str


@dataclass(frozen=True)
class BinaryExpr(Expr):
    operator: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class CallExpr(Expr):
    name: str
    arguments: tuple[Expr, ...]


@dataclass(frozen=True)
class LetStmt:
    name: str
    type: Type | None
    value: Expr
    line: int
    mutable: bool = False


@dataclass(frozen=True)
class AssignStmt:
    name: str
    value: Expr
    line: int


@dataclass(frozen=True)
class ReturnStmt:
    value: Expr | None
    line: int


@dataclass(frozen=True)
class IfStmt:
    condition: Expr
    then_body: tuple[Statement, ...]
    else_body: tuple[Statement, ...]
    line: int


@dataclass(frozen=True)
class WhileStmt:
    condition: Expr
    body: tuple[Statement, ...]
    line: int


Statement = LetStmt | AssignStmt | ReturnStmt | IfStmt | WhileStmt


@dataclass(frozen=True)
class TaskMetadata:
    async_: bool = False
    priority: int = 0
    deadline_ms: int | None = None
    capacity: int = 1
    cancelable: bool = True
    supervised: bool = False


@dataclass(frozen=True)
class HybridSpec:
    components: tuple[str, ...]
    strategy: str = "pipe"
    reducer: str | None = None
    max_workers: int = 1


@dataclass(frozen=True)
class Function:
    name: str
    parameters: tuple[tuple[str, Type], ...]
    return_type: Type
    body: tuple[Statement, ...]
    line: int
    effects: tuple[str, ...] = ()
    task: TaskMetadata | None = None
    hybrid: HybridSpec | None = None


@dataclass(frozen=True)
class Program:
    module: str
    functions: tuple[Function, ...]


_TOKEN_RE = re.compile(
    r"(?P<ws>\s+)|(?P<comment>//[^\n]*|#[^\n]*)|(?P<float>\d+\.\d+)|(?P<int>\d+)|"
    r"(?P<ident>[A-Za-z_][A-Za-z0-9_.]*)|(?P<arrow>->)|(?P<cmp>==|!=|<=|>=|&&|\|\|)|(?P<op>[+\-*/=<>!])|"
    r"(?P<punct>[{}(),:;\[\]])|(?P<string>\"(?:\\.|[^\"\\])*\")"
)


def lex(source: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    position = 0
    line = 1
    column = 1
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if match is None:
            raise HolyFitraError(f"unexpected character at {line}:{column}: {source[position]!r}")
        text = match.group(0)
        kind = match.lastgroup or ""
        if kind not in {"ws", "comment"}:
            if len(tokens) >= MAX_TOKENS:
                raise HolyFitraError(f"source token limit exceeded at {line}:{column}")
            normalized = "ARROW" if kind == "arrow" else "OP" if kind == "cmp" else kind.upper()
            tokens.append(Token(normalized, text, line, column))
        newlines = text.count("\n")
        if newlines:
            line += newlines
            column = len(text.rsplit("\n", 1)[1]) + 1
        else:
            column += len(text)
        position = match.end()
    tokens.append(Token("EOF", "", line, column))
    return tuple(tokens)


class Parser:
    def __init__(self, tokens: Sequence[Token]):
        self.tokens = tokens
        self.index = 0
        self._expression_depth = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def accept(self, kind: str, text: str | None = None) -> Token | None:
        if self.current.kind == kind and (text is None or self.current.text == text):
            return self.advance()
        return None

    def expect(self, kind: str, text: str | None = None) -> Token:
        token = self.accept(kind, text)
        if token is None:
            expected = text or kind
            raise HolyFitraError(f"expected {expected} at {self.current.line}:{self.current.column}, got {self.current.text!r}")
        return token

    def parse(self) -> Program:
        module = "anonymous"
        if self.accept("IDENT", "module"):
            module = self.expect("IDENT").text
        functions: list[Function] = []
        while self.current.kind != "EOF":
            if len(functions) >= MAX_FUNCTIONS and self.current.kind == "IDENT" and self.current.text in {"fn", "hybrid"}:
                raise HolyFitraError(f"function count exceeds {MAX_FUNCTIONS}")
            if self.accept("IDENT", "capability"):
                self._skip_balanced_block()
                continue
            if self.accept("IDENT", "budget"):
                self._skip_to_statement_end()
                continue
            if self.accept("IDENT", "hybrid"):
                strategy = "parallel" if self.accept("IDENT", "parallel") else "pipe"
                self.expect("IDENT", "fn")
                functions.append(self.parse_function(hybrid=True, strategy=strategy))
                continue
            if self.accept("IDENT", "fn"):
                functions.append(self.parse_function())
                continue
            token = self.current
            raise HolyFitraError(f"unexpected top-level token {token.text!r} at {token.line}:{token.column}")
        if not functions:
            raise HolyFitraError("program must declare at least one function")
        return Program(module, tuple(functions))

    def _skip_balanced_block(self) -> None:
        if self.accept("PUNCT", "{") is None:
            self._skip_to_statement_end()
            return
        depth = 1
        while depth and self.current.kind != "EOF":
            if self.accept("PUNCT", "{"):
                depth += 1
            elif self.accept("PUNCT", "}"):
                depth -= 1
            else:
                self.advance()

    def _skip_to_statement_end(self) -> None:
        while self.current.kind != "EOF" and not (self.current.kind == "PUNCT" and self.current.text in {";", "}"}):
            self.advance()
        self.accept("PUNCT", ";")

    def parse_function(self, *, hybrid: bool = False, strategy: str = "pipe") -> Function:
        name_token = self.expect("IDENT")
        self.expect("PUNCT", "(")
        parameters: list[tuple[str, Type]] = []
        if not self.accept("PUNCT", ")"):
            while True:
                parameter_name = self.expect("IDENT").text
                self.expect("PUNCT", ":")
                parameters.append((parameter_name, self.parse_type()))
                if self.accept("PUNCT", ")"):
                    break
                self.expect("PUNCT", ",")
        self.expect("ARROW")
        return_type = self.parse_type()
        effects: list[str] = []
        if self.accept("IDENT", "effects"):
            self.expect("PUNCT", "[")
            if not self.accept("PUNCT", "]"):
                while True:
                    effects.append(self.expect("IDENT").text)
                    if self.accept("PUNCT", "]"):
                        break
                    self.expect("PUNCT", ",")
        task = None
        if self.accept("IDENT", "task"):
            values: dict[str, object] = {}
            self.expect("PUNCT", "[")
            if not self.accept("PUNCT", "]"):
                while True:
                    key = self.expect("IDENT").text
                    value: object = True
                    if self.accept("OP", "="):
                        if self.current.kind == "INT":
                            value = int(self.advance().text)
                        else:
                            value = self.expect("IDENT").text == "true"
                    values[key] = value
                    if self.accept("PUNCT", "]"):
                        break
                    self.expect("PUNCT", ",")
            allowed = {"async", "priority", "deadline_ms", "capacity", "cancelable", "supervised"}
            unknown = set(values) - allowed
            if unknown:
                raise HolyFitraError(f"unknown task metadata: {', '.join(sorted(unknown))}")
            task = TaskMetadata(
                async_=bool(values.get("async", False)),
                priority=int(values.get("priority", 0)),
                deadline_ms=int(values["deadline_ms"]) if "deadline_ms" in values else None,
                capacity=int(values.get("capacity", 1)),
                cancelable=bool(values.get("cancelable", True)),
                supervised=bool(values.get("supervised", False)),
            )
        if hybrid:
            self.expect("IDENT", "using")
            self.expect("PUNCT", "[")
            components: list[str] = []
            if not self.accept("PUNCT", "]"):
                while True:
                    components.append(self.expect("IDENT").text)
                    if self.accept("PUNCT", "]"):
                        break
                    self.expect("PUNCT", ",")
            reducer = None
            max_workers = 1
            if strategy == "parallel":
                self.expect("IDENT", "reduce")
                reducer = self.expect("IDENT").text
                if self.accept("IDENT", "workers"):
                    self.expect("OP", "=")
                    max_workers = int(self.expect("INT").text)
            self.accept("PUNCT", ";")
            return Function(name_token.text, tuple(parameters), return_type, (), name_token.line, tuple(effects), task, HybridSpec(tuple(components), strategy, reducer, max_workers))
        body = self.parse_block()
        return Function(name_token.text, tuple(parameters), return_type, body, name_token.line, tuple(effects), task)

    def parse_block(self) -> tuple[Statement, ...]:
        self.expect("PUNCT", "{")
        body: list[Statement] = []
        while not self.accept("PUNCT", "}"):
            if self.current.kind == "EOF":
                raise HolyFitraError("unterminated block")
            body.append(self.parse_statement())
        return tuple(body)

    def parse_type(self) -> Type:
        mode = "owned"
        if self.current.kind == "IDENT" and self.current.text in {"owned", "borrow", "borrow_mut", "shared"}:
            mode = self.advance().text
        token = self.expect("IDENT")
        return Type(token.text, mode)

    def parse_statement(self) -> Statement:
        if self.accept("IDENT", "while"):
            line = self.tokens[self.index - 1].line
            condition = self.parse_expression()
            return WhileStmt(condition, self.parse_block(), line)
        if self.accept("IDENT", "if"):
            line = self.tokens[self.index - 1].line
            condition = self.parse_expression()
            then_body = self.parse_block()
            else_body: tuple[Statement, ...] = ()
            if self.accept("IDENT", "else"):
                else_body = self.parse_block()
            return IfStmt(condition, then_body, else_body, line)
        let_token = self.accept("IDENT", "let")
        mutable = False
        if let_token is None:
            var_token = self.accept("IDENT", "var")
            if var_token is not None:
                mutable = True
        if let_token is not None or mutable:
            name = self.expect("IDENT")
            declared_type = None
            if self.accept("PUNCT", ":"):
                declared_type = self.parse_type()
            self.expect("OP", "=")
            value = self.parse_expression()
            self.accept("PUNCT", ";")
            return LetStmt(name.text, declared_type, value, name.line, mutable)
        if self.current.kind == "IDENT" and self.index + 1 < len(self.tokens):
            next_token = self.tokens[self.index + 1]
            if next_token.kind == "OP" and next_token.text == "=":
                name = self.advance()
                self.advance()
                value = self.parse_expression()
                self.accept("PUNCT", ";")
                return AssignStmt(name.text, value, name.line)
        if self.accept("IDENT", "return"):
            line = self.tokens[self.index - 1].line
            if self.current.kind == "PUNCT" and self.current.text in {";", "}"}:
                value = None
            else:
                value = self.parse_expression()
            self.accept("PUNCT", ";")
            return ReturnStmt(value, line)
        token = self.current
        raise HolyFitraError(f"expected let, var, or return at {token.line}:{token.column}")

    def parse_expression(self) -> Expr:
        if self._expression_depth >= MAX_AST_DEPTH:
            token = self.current
            raise HolyFitraError(f"expression nesting exceeds {MAX_AST_DEPTH} at {token.line}:{token.column}")
        self._expression_depth += 1
        try:
            return self.parse_additive()
        finally:
            self._expression_depth -= 1

    def parse_additive(self) -> Expr:
        expression = self.parse_comparison()
        while self.current.kind == "OP" and self.current.text in {"+", "-"}:
            operator = self.advance().text
            expression = BinaryExpr(operator, expression, self.parse_comparison())
        return expression

    def parse_comparison(self) -> Expr:
        expression = self.parse_multiplicative()
        while self.current.kind == "OP" and self.current.text in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
            operator = self.advance().text
            expression = BinaryExpr(operator, expression, self.parse_multiplicative())
        return expression

    def parse_multiplicative(self) -> Expr:
        expression = self.parse_primary()
        while self.current.kind == "OP" and self.current.text in {"*", "/"}:
            operator = self.advance().text
            expression = BinaryExpr(operator, expression, self.parse_primary())
        return expression

    def parse_primary(self) -> Expr:
        if self.current.kind == "IDENT" and self.current.text in {"true", "false"}:
            return BoolLiteral(self.advance().text == "true")
        if self.current.kind == "INT":
            return IntLiteral(int(self.advance().text))
        if self.current.kind == "IDENT":
            name = self.advance().text
            if self.accept("PUNCT", "("):
                arguments: list[Expr] = []
                if not self.accept("PUNCT", ")"):
                    while True:
                        arguments.append(self.parse_expression())
                        if self.accept("PUNCT", ")"):
                            break
                        self.expect("PUNCT", ",")
                return CallExpr(name, tuple(arguments))
            return NameExpr(name)
        if self.accept("PUNCT", "("):
            expression = self.parse_expression()
            self.expect("PUNCT", ")")
            return expression
        token = self.current
        raise HolyFitraError(f"expected expression at {token.line}:{token.column}")


def parse_native(source: str) -> Program:
    try:
        return Parser(lex(source)).parse()
    except RecursionError as error:
        raise HolyFitraError(f"expression nesting exceeds {MAX_AST_DEPTH}") from error


def _same_value_type(left: Type, right: Type) -> bool:
    return left.name == right.name


def _direct_calls_expression(expr: Expr) -> set[str]:
    if isinstance(expr, CallExpr):
        calls = {expr.name}
        for argument in expr.arguments:
            calls.update(_direct_calls_expression(argument))
        return calls
    if isinstance(expr, BinaryExpr):
        return _direct_calls_expression(expr.left) | _direct_calls_expression(expr.right)
    return set()


def _direct_calls_block(statements: tuple[Statement, ...]) -> set[str]:
    calls: set[str] = set()
    for statement in statements:
        if isinstance(statement, (LetStmt, AssignStmt)):
            calls.update(_direct_calls_expression(statement.value))
        elif isinstance(statement, ReturnStmt) and statement.value is not None:
            calls.update(_direct_calls_expression(statement.value))
        elif isinstance(statement, IfStmt):
            calls.update(_direct_calls_expression(statement.condition))
            calls.update(_direct_calls_block(statement.then_body))
            calls.update(_direct_calls_block(statement.else_body))
        elif isinstance(statement, WhileStmt):
            calls.update(_direct_calls_expression(statement.condition))
            calls.update(_direct_calls_block(statement.body))
    return calls


def _effect_call_graph(program: Program) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    try:
        cache_key: object = hash(program)
    except TypeError:
        cache_key = id(program)
    cached = _EFFECT_GRAPH_CACHE.get(cache_key)
    if cached is not None:
        _EFFECT_GRAPH_CACHE.move_to_end(cache_key)
        return cached
    functions = {function.name: function for function in program.functions}
    direct = {
        name: ((set(function.hybrid.components) | ({function.hybrid.reducer} if function.hybrid.reducer else set())) if function.hybrid is not None else _direct_calls_block(function.body))
        for name, function in functions.items()
    }
    for name, calls in direct.items():
        unknown = calls - functions.keys()
        if unknown:
            raise HolyFitraError(f"function {name} calls unknown functions: {', '.join(sorted(unknown))}")
    memo: dict[str, set[str]] = {}
    active: list[str] = []

    def closure(name: str) -> set[str]:
        if name in memo:
            return set(memo[name])
        if name in active:
            start = active.index(name)
            cycle = active[start:] + [name]
            raise HolyFitraError(f"recursive effect cycle: {' -> '.join(cycle)}")
        active.append(name)
        try:
            result = set(functions[name].effects)
            for callee in sorted(direct[name]):
                result.update(closure(callee))
        finally:
            active.pop()
        memo[name] = result
        return set(result)

    for name in functions:
        closure(name)
    result = (direct, memo)
    _EFFECT_GRAPH_CACHE[cache_key] = result
    _EFFECT_GRAPH_CACHE.move_to_end(cache_key)
    while len(_EFFECT_GRAPH_CACHE) > _EFFECT_GRAPH_CACHE_LIMIT:
        _EFFECT_GRAPH_CACHE.popitem(last=False)
    return result


def _function_map(program: Program) -> dict[str, Function]:
    functions: dict[str, Function] = {}
    for function in program.functions:
        if function.name in functions:
            raise HolyFitraError(f"duplicate function {function.name}")
        functions[function.name] = function
    return functions


def _infer_expression(expr: Expr, variables: dict[str, Type], functions: dict[str, Function]) -> Type:
    if isinstance(expr, BoolLiteral):
        return Type("bool")
    if isinstance(expr, IntLiteral):
        return Type("i32")
    if isinstance(expr, NameExpr):
        if expr.name not in variables:
            raise HolyFitraError(f"unknown value {expr.name}")
        return variables[expr.name]
    if isinstance(expr, BinaryExpr):
        left = _infer_expression(expr.left, variables, functions)
        right = _infer_expression(expr.right, variables, functions)
        if not _same_value_type(left, right):
            raise HolyFitraError(f"operator {expr.operator} requires matching types, got {left.name} and {right.name}")
        if expr.operator in {"&&", "||"}:
            if left.name != "bool":
                raise HolyFitraError(f"logical operator {expr.operator} requires bool operands")
            return Type("bool")
        if expr.operator in {"==", "!=", "<", "<=", ">", ">="}:
            if left.name not in {"i32", "i64", "bool"}:
                raise HolyFitraError(f"comparison does not support {left.name}")
            return Type("bool")
        if left.name not in {"i32", "i64"}:
            raise HolyFitraError(f"native arithmetic currently supports i32 and i64, not {left.name}")
        return left
    if isinstance(expr, CallExpr):
        if expr.name not in functions:
            raise HolyFitraError(f"unknown function {expr.name}")
        function = functions[expr.name]
        if len(expr.arguments) != len(function.parameters):
            raise HolyFitraError(f"function {expr.name} expects {len(function.parameters)} arguments")
        for argument, (_, parameter_type) in zip(expr.arguments, function.parameters):
            actual = _infer_expression(argument, variables, functions)
            if not _same_value_type(actual, parameter_type):
                raise HolyFitraError(f"argument to {expr.name} requires {parameter_type.name}, got {actual.name}")
        return function.return_type
    raise HolyFitraError("unsupported expression")


def validate_native(program: Program) -> None:
    functions = _function_map(program)
    direct_calls, effective_effects = _effect_call_graph(program)
    allowed_effects = {"io", "network", "tool", "model", "memory", "thermal", "random", "unsafe"}
    for function in program.functions:
        parameter_names = [name for name, _ in function.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise HolyFitraError(f"function {function.name} has duplicate parameters")
        ownership_modes = {type_.mode for _, type_ in function.parameters}
        if not ownership_modes.issubset({"owned", "borrow", "borrow_mut", "shared"}):
            raise HolyFitraError(f"function {function.name} uses an unknown ownership mode")
        if sum(type_.mode == "borrow_mut" for _, type_ in function.parameters) > 1:
            raise HolyFitraError(f"function {function.name} has multiple borrow_mut parameters; mutable access must be exclusive")
        unknown_effects = set(function.effects) - allowed_effects
        if unknown_effects:
            raise HolyFitraError(f"function {function.name} declares unknown effects: {', '.join(sorted(unknown_effects))}")
        if len(set(function.effects)) != len(function.effects):
            raise HolyFitraError(f"function {function.name} declares duplicate effects")
        required_from_calls = effective_effects[function.name] - set(function.effects)
        if required_from_calls and "unsafe" not in function.effects:
            raise HolyFitraError(f"function {function.name} must declare transitive effects: {', '.join(sorted(required_from_calls))}")
        if function.task is not None:
            if function.task.capacity <= 0:
                raise HolyFitraError(f"function {function.name} task capacity must be positive")
            if function.task.deadline_ms is not None and function.task.deadline_ms <= 0:
                raise HolyFitraError(f"function {function.name} task deadline must be positive")
        if function.return_type.name not in {"i32", "i64", "bool", "void"}:
            raise HolyFitraError(f"function {function.name} has unsupported return type {function.return_type.name}")
        if function.hybrid is not None:
            if len(function.hybrid.components) < 2:
                raise HolyFitraError(f"hybrid function {function.name} requires at least two components")
            if len(set(function.hybrid.components)) != len(function.hybrid.components):
                raise HolyFitraError(f"hybrid function {function.name} contains duplicate components")
            if function.name in function.hybrid.components:
                raise HolyFitraError(f"hybrid function {function.name} cannot contain itself")
            components = [functions.get(component) for component in function.hybrid.components]
            if any(component is None for component in components):
                missing = sorted(set(function.hybrid.components) - functions.keys())
                raise HolyFitraError(f"hybrid function {function.name} uses unknown components: {', '.join(missing)}")
            first = components[0]
            assert first is not None
            if len(first.parameters) != len(function.parameters):
                raise HolyFitraError(f"hybrid function {function.name} input arity does not match {first.name}")
            for (_, expected), (_, actual) in zip(function.parameters, first.parameters):
                if not _same_value_type(expected, actual):
                    raise HolyFitraError(f"hybrid function {function.name} input type does not match {first.name}")
            if function.hybrid.strategy == "parallel":
                if function.hybrid.reducer is None or function.hybrid.reducer not in functions:
                    raise HolyFitraError(f"parallel hybrid {function.name} requires a known reducer")
                if function.hybrid.max_workers <= 0 or function.hybrid.max_workers > 32:
                    raise HolyFitraError(f"parallel hybrid {function.name} workers must be between 1 and 32")
                reducer = functions[function.hybrid.reducer]
                if reducer.hybrid is not None:
                    raise HolyFitraError(f"parallel reducer {reducer.name} cannot itself be a hybrid")
                if len(reducer.parameters) != len(components):
                    raise HolyFitraError(f"reducer {reducer.name} expects {len(reducer.parameters)} branch values")
                for component, (_, reducer_type) in zip(components, reducer.parameters):
                    assert component is not None
                    if component.return_type.name == "void":
                        raise HolyFitraError(f"parallel component {component.name} must return a value")
                    if not _same_value_type(component.return_type, reducer_type):
                        raise HolyFitraError(f"reducer {reducer.name} expects {reducer_type.name}, got {component.return_type.name}")
                if not _same_value_type(reducer.return_type, function.return_type):
                    raise HolyFitraError(f"parallel hybrid {function.name} returns {reducer.return_type.name}, expected {function.return_type.name}")
            else:
                previous = first.return_type
                if previous.name == "void":
                    raise HolyFitraError(f"hybrid component {first.name} must return a value")
                for component in components[1:]:
                    assert component is not None
                    if len(component.parameters) != 1:
                        raise HolyFitraError(f"hybrid component {component.name} must accept exactly one value")
                    if not _same_value_type(previous, component.parameters[0][1]):
                        raise HolyFitraError(f"hybrid component {component.name} expects {component.parameters[0][1].name}, got {previous.name}")
                    previous = component.return_type
                    if previous.name == "void" and component is not components[-1]:
                        raise HolyFitraError(f"hybrid component {component.name} cannot produce void before the end")
                if not _same_value_type(previous, function.return_type):
                    raise HolyFitraError(f"hybrid function {function.name} returns {previous.name}, expected {function.return_type.name}")
            continue
        variables = dict(function.parameters)
        mutable_parameters = {name for name, type_ in function.parameters if type_.mode == "borrow_mut"}

        def validate_block(
            statements: tuple[Statement, ...],
            scope: dict[str, Type],
            mutable_names: set[str],
            declared_names: set[str],
        ) -> bool:
            guaranteed_return = False
            for statement in statements:
                was_terminated = guaranteed_return
                if isinstance(statement, LetStmt):
                    if statement.name in declared_names:
                        raise HolyFitraError(f"duplicate declaration {statement.name}")
                    actual = _infer_expression(statement.value, scope, functions)
                    if statement.type is not None and not _same_value_type(actual, statement.type):
                        raise HolyFitraError(f"let {statement.name} declares {statement.type.name} but receives {actual.name}")
                    scope[statement.name] = statement.type or actual
                    declared_names.add(statement.name)
                    if statement.mutable:
                        mutable_names.add(statement.name)
                elif isinstance(statement, AssignStmt):
                    if statement.name not in scope:
                        raise HolyFitraError(f"unknown value {statement.name}")
                    if statement.name not in mutable_names:
                        raise HolyFitraError(f"cannot assign to immutable value {statement.name}")
                    actual = _infer_expression(statement.value, scope, functions)
                    expected = scope[statement.name]
                    if not _same_value_type(actual, expected):
                        raise HolyFitraError(f"assignment to {statement.name} requires {expected.name}, got {actual.name}")
                elif isinstance(statement, ReturnStmt):
                    guaranteed_return = True
                    if function.return_type.name == "void":
                        if statement.value is not None:
                            raise HolyFitraError(f"void function {function.name} cannot return a value")
                    else:
                        if statement.value is None:
                            raise HolyFitraError(f"function {function.name} must return {function.return_type.name}")
                        actual = _infer_expression(statement.value, scope, functions)
                        if not _same_value_type(actual, function.return_type):
                            raise HolyFitraError(f"function {function.name} returns {actual.name}, expected {function.return_type.name}")
                elif isinstance(statement, IfStmt):
                    condition_type = _infer_expression(statement.condition, scope, functions)
                    if condition_type.name != "bool":
                        raise HolyFitraError("if condition must be bool")
                    then_return = validate_block(statement.then_body, dict(scope), set(mutable_names), set())
                    else_return = bool(statement.else_body) and validate_block(statement.else_body, dict(scope), set(mutable_names), set())
                    guaranteed_return = then_return and else_return
                elif isinstance(statement, WhileStmt):
                    condition_type = _infer_expression(statement.condition, scope, functions)
                    if condition_type.name != "bool":
                        raise HolyFitraError("while condition must be bool")
                    validate_block(statement.body, dict(scope), set(mutable_names), set())
                    guaranteed_return = False
                if was_terminated:
                    guaranteed_return = True
            return guaranteed_return

        guaranteed_return = validate_block(function.body, variables, mutable_parameters, set(variables))
        if function.return_type.name != "void" and not guaranteed_return:
            raise HolyFitraError(f"function {function.name} does not return on every path")


class LLVMEmitter:
    def __init__(self, program: Program):
        self.program = program
        self.functions = _function_map(program)
        self.counter = 0
        self.block_counter = 0
        self.terminated = False
        self.variables: dict[str, str] = {}
        self.types: dict[str, Type] = {}
        self.target = "x86_64-pc-linux-gnu"

    def temp(self) -> str:
        value = f"%t{self.counter}"
        self.counter += 1
        return value

    def block(self, prefix: str) -> str:
        value = f"{prefix}{self.block_counter}"
        self.block_counter += 1
        return value

    def emit(self, target: str | None = None) -> str:
        validate_native(self.program)
        triple = target or "x86_64-pc-linux-gnu"
        self.target = triple
        target_lines = [f"; Holy Fitra target: {triple}"]
        if triple.startswith("aarch64"):
            target_lines.extend(("; Holy Fitra ABI: AAPCS64", "; Holy Fitra vector capability: NEON when available", "; Parallel hybrid lowering: independent branch calls followed by typed reducer"))
        lines = [f"; Holy Fitra module {self.program.module}", *target_lines, f'target triple = "{triple}"', ""]
        for function in self.program.functions:
            lines.extend(self.emit_function(function))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def emit_call_values(self, name: str, arguments: list[tuple[str, Type]]) -> tuple[str, Type]:
        function = self.functions.get(name)
        if function is None:
            raise HolyFitraError(f"unknown function {name}")
        if len(arguments) != len(function.parameters):
            raise HolyFitraError(f"call argument count mismatch for {name}")
        rendered: list[str] = []
        for (value, actual), (_, expected) in zip(arguments, function.parameters):
            if not _same_value_type(actual, expected):
                raise HolyFitraError(f"call argument type mismatch for {name}")
            rendered.append(f"{expected.llvm} {value}")
        result_type = function.return_type
        if result_type.name == "void":
            self.current_lines.append(f"  call void @{name}({', '.join(rendered)})")
            return "", result_type
        result = self.temp()
        self.current_lines.append(f"  {result} = call {result_type.llvm} @{name}({', '.join(rendered)})")
        return result, result_type

    def emit_expr(self, expression: Expr) -> tuple[str, Type]:
        if isinstance(expression, BoolLiteral):
            return ("1" if expression.value else "0"), Type("bool")
        if isinstance(expression, IntLiteral):
            return str(expression.value), Type("i32")
        if isinstance(expression, NameExpr):
            if expression.name not in self.variables:
                raise HolyFitraError(f"unknown value {expression.name}")
            result = self.temp()
            self.current_lines.append(f"  {result} = load {self.types[expression.name].llvm}, ptr {self.variables[expression.name]}")
            return result, self.types[expression.name]
        if isinstance(expression, BinaryExpr):
            if isinstance(expression.left, (IntLiteral, BoolLiteral)) and isinstance(expression.right, (IntLiteral, BoolLiteral)):
                left_value = expression.left.value
                right_value = expression.right.value
                if expression.operator == "+":
                    return str(left_value + right_value), Type("i32")
                if expression.operator == "-":
                    return str(left_value - right_value), Type("i32")
                if expression.operator == "*":
                    return str(left_value * right_value), Type("i32")
                if expression.operator == "/":
                    if right_value == 0:
                        raise HolyFitraError("division by zero in constant expression")
                    return str(left_value // right_value), Type("i32")
                if expression.operator in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
                    outcomes = {"==": left_value == right_value, "!=": left_value != right_value, "<": left_value < right_value, "<=": left_value <= right_value, ">": left_value > right_value, ">=": left_value >= right_value, "&&": bool(left_value and right_value), "||": bool(left_value or right_value)}
                    return ("1" if outcomes[expression.operator] else "0"), Type("bool")
            if expression.operator in {"&&", "||"}:
                left, left_type = self.emit_expr(expression.left)
                if left_type.name != "bool":
                    raise HolyFitraError(f"logical operator {expression.operator} requires bool operands")
                rhs_label = self.block("bool_rhs")
                short_label = self.block("bool_short")
                merge_label = self.block("bool_merge")
                result = self.temp()
                if expression.operator == "&&":
                    self.current_lines.append(f"  br i1 {left}, label %{rhs_label}, label %{short_label}")
                    short_value = "0"
                else:
                    self.current_lines.append(f"  br i1 {left}, label %{short_label}, label %{rhs_label}")
                    short_value = "1"
                self.current_lines.append(f"{rhs_label}:")
                right, right_type = self.emit_expr(expression.right)
                if right_type.name != "bool":
                    raise HolyFitraError(f"logical operator {expression.operator} requires bool operands")
                self.current_lines.append(f"  br label %{merge_label}")
                self.current_lines.append(f"{short_label}:")
                self.current_lines.append(f"  br label %{merge_label}")
                self.current_lines.append(f"{merge_label}:")
                self.current_lines.append(f"  {result} = phi i1 [ {right}, %{rhs_label} ], [ {short_value}, %{short_label} ]")
                return result, Type("bool")
            left, type_ = self.emit_expr(expression.left)
            right, right_type = self.emit_expr(expression.right)
            if not _same_value_type(type_, right_type):
                raise HolyFitraError("binary operands have different types")
            if expression.operator in {"==", "!=", "<", "<=", ">", ">="}:
                predicates = {"==": "eq", "!=": "ne", "<": "slt", "<=": "sle", ">": "sgt", ">=": "sge"}
                result = self.temp()
                self.current_lines.append(f"  {result} = icmp {predicates[expression.operator]} {type_.llvm} {left}, {right}")
                return result, Type("bool")
            opcode = {"+": "add", "-": "sub", "*": "mul", "/": "sdiv"}[expression.operator]
            result = self.temp()
            lines = getattr(self, "current_lines", None)
            if lines is None:
                raise HolyFitraError("internal emitter state error")
            lines.append(f"  {result} = {opcode} {type_.llvm} {left}, {right}")
            return result, type_
        if isinstance(expression, CallExpr):
            function = self.functions.get(expression.name)
            if function is None:
                raise HolyFitraError(f"unknown function {expression.name}")
            if len(expression.arguments) != len(function.parameters):
                raise HolyFitraError(f"function {expression.name} expects {len(function.parameters)} arguments")
            arguments: list[tuple[str, Type]] = []
            for argument, (_, parameter_type) in zip(expression.arguments, function.parameters):
                value, actual_type = self.emit_expr(argument)
                arguments.append((value, actual_type))
                if not _same_value_type(actual_type, parameter_type):
                    raise HolyFitraError("call argument type mismatch")
            return self.emit_call_values(function.name, arguments)
        raise HolyFitraError("unsupported expression")

    def emit_function(self, function: Function) -> list[str]:
        self.counter = 0
        self.block_counter = 0
        self.local_counter = 0
        self.alloca_lines: list[str] = []
        self.terminated = False
        self.variables = {name: f"%{name}.addr" for name, _ in function.parameters}
        self.types = dict(function.parameters)
        parameters = ", ".join(f"{type_.llvm} %{name}" for name, type_ in function.parameters)
        return_type = "void" if function.return_type.name == "void" else function.return_type.llvm
        effect_comment = f"; effects: {', '.join(function.effects) if function.effects else 'pure'}"
        ownership_comment = "; ownership: " + ", ".join(f"{name}:{type_.mode}" for name, type_ in function.parameters) if function.parameters else "; ownership: none"
        task_comment = "; task: " + (json.dumps({"async": function.task.async_, "priority": function.task.priority, "deadline_ms": function.task.deadline_ms, "capacity": function.task.capacity, "cancelable": function.task.cancelable, "supervised": function.task.supervised}, sort_keys=True) if function.task else "sync")
        if function.hybrid:
            hybrid_payload = {"mode": function.hybrid.strategy, "components": list(function.hybrid.components), "reducer": function.hybrid.reducer, "max_workers": function.hybrid.max_workers}
            if self.target.startswith("aarch64") and function.hybrid.strategy == "parallel":
                hybrid_payload.update({"native_abi": "aapcs64", "native_vector": "neon", "native_lowering": "branch_calls_then_reducer"})
            hybrid_comment = "; hybrid: " + json.dumps(hybrid_payload, separators=(",", ":"), sort_keys=True)
        else:
            hybrid_comment = "; hybrid: none"
        lines = [effect_comment, ownership_comment, task_comment, hybrid_comment, f"define {return_type} @{function.name}({parameters}) {{", "entry:"]
        self.current_lines = lines
        for name, type_ in function.parameters:
            lines.append(f"  %{name}.addr = alloca {type_.llvm}")
            lines.append(f"  store {type_.llvm} %{name}, ptr %{name}.addr")
        entry_alloca_index = len(lines)
        if function.hybrid is not None:
            current_arguments = [(f"%{name}", type_) for name, type_ in function.parameters]
            if function.hybrid.strategy == "parallel":
                branch_values = [self.emit_call_values(component_name, current_arguments) for component_name in function.hybrid.components]
                current_value, current_type = self.emit_call_values(function.hybrid.reducer or "", branch_values)
            else:
                current_value, current_type = self.emit_call_values(function.hybrid.components[0], current_arguments)
                for component_name in function.hybrid.components[1:]:
                    current_value, current_type = self.emit_call_values(component_name, [(current_value, current_type)])
            self.current_lines.append(f"  ret {current_type.llvm} {current_value}")
            self.terminated = True
        else:
            self.emit_block(function.body)
        if not self.terminated and function.return_type.name == "void":
            lines.append("  ret void")
        elif not self.terminated:
            raise HolyFitraError(f"function {function.name} has an unterminated return path")
        if self.alloca_lines:
            lines[entry_alloca_index:entry_alloca_index] = self.alloca_lines
        lines.append("}")
        return lines

    def emit_block(self, statements: tuple[Statement, ...]) -> bool:
        block_terminated = False
        for statement in statements:
            if self.terminated:
                block_terminated = True
                break
            if isinstance(statement, LetStmt):
                value, value_type = self.emit_expr(statement.value)
                local_type = statement.type or value_type
                address = f"%{statement.name}.addr.{self.local_counter}"
                self.local_counter += 1
                self.alloca_lines.append(f"  {address} = alloca {local_type.llvm}")
                self.current_lines.append(f"  store {local_type.llvm} {value}, ptr {address}")
                self.variables[statement.name] = address
                self.types[statement.name] = local_type
            elif isinstance(statement, AssignStmt):
                if statement.name not in self.variables:
                    raise HolyFitraError(f"unknown value {statement.name}")
                value, value_type = self.emit_expr(statement.value)
                expected = self.types[statement.name]
                if not _same_value_type(value_type, expected):
                    raise HolyFitraError(f"assignment to {statement.name} requires {expected.name}, got {value_type.name}")
                self.current_lines.append(f"  store {expected.llvm} {value}, ptr {self.variables[statement.name]}")
            elif isinstance(statement, ReturnStmt):
                if statement.value is None:
                    self.current_lines.append("  ret void")
                else:
                    value, value_type = self.emit_expr(statement.value)
                    self.current_lines.append(f"  ret {value_type.llvm} {value}")
                self.terminated = True
                block_terminated = True
            elif isinstance(statement, WhileStmt):
                head_label = self.block("while_head")
                body_label = self.block("while_body")
                exit_label = self.block("while_exit")
                self.current_lines.append(f"  br label %{head_label}")
                self.current_lines.append(f"{head_label}:")
                condition, condition_type = self.emit_expr(statement.condition)
                if condition_type.name != "bool":
                    raise HolyFitraError("while condition must be bool")
                self.current_lines.append(f"  br i1 {condition}, label %{body_label}, label %{exit_label}")
                self.current_lines.append(f"{body_label}:")
                saved_variables = self.variables
                saved_types = self.types
                self.variables = dict(saved_variables)
                self.types = dict(saved_types)
                self.terminated = False
                body_terminated = self.emit_block(statement.body)
                if not body_terminated:
                    self.current_lines.append(f"  br label %{head_label}")
                self.current_lines.append(f"{exit_label}:")
                self.variables = saved_variables
                self.types = saved_types
                self.terminated = False
                block_terminated = False
            elif isinstance(statement, IfStmt):
                condition, condition_type = self.emit_expr(statement.condition)
                if condition_type.name != "bool":
                    raise HolyFitraError("if condition must be bool")
                then_label = self.block("if_then")
                else_label = self.block("if_else")
                merge_label = self.block("if_merge")
                self.current_lines.append(f"  br i1 {condition}, label %{then_label}, label %{else_label}")
                self.current_lines.append(f"{then_label}:")
                saved_variables = self.variables
                saved_types = self.types
                self.variables = dict(saved_variables)
                self.types = dict(saved_types)
                self.terminated = False
                then_terminated = self.emit_block(statement.then_body)
                if not then_terminated:
                    self.current_lines.append(f"  br label %{merge_label}")
                self.current_lines.append(f"{else_label}:")
                self.variables = dict(saved_variables)
                self.types = dict(saved_types)
                self.terminated = False
                else_terminated = self.emit_block(statement.else_body) if statement.else_body else False
                if not else_terminated:
                    self.current_lines.append(f"  br label %{merge_label}")
                self.current_lines.append(f"{merge_label}:")
                self.variables = saved_variables
                self.types = saved_types
                self.terminated = then_terminated and else_terminated
                if self.terminated:
                    self.current_lines.append("  unreachable")
                block_terminated = self.terminated
        return block_terminated


def emit_llvm(program: Program, target: str | None = None) -> str:
    return LLVMEmitter(program).emit(target)


def _atomic_write_text(path: Path, text: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compile_native_file(source_path: Path, cache_dir: Path | None = None, target: str | None = None) -> tuple[Program, str, str]:
    source = read_source(source_path)
    effective_target = target or "x86_64-pc-linux-gnu"
    cache_identity = "\\0".join((source, effective_target, str(_LLVM_CACHE_SCHEMA), _NATIVE_COMPILER_ABI))
    digest = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()
    memory_cached = _MEMORY_COMPILE_CACHE.get(digest)
    if memory_cached is not None:
        _MEMORY_COMPILE_CACHE.move_to_end(digest)
        return memory_cached[0], memory_cached[1], digest
    if cache_dir is None:
        cache_dir = source_path.parent / ".holyfitra" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{digest}.json"
    llvm: str | None = None
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_llvm = cached.get("llvm")
            cached_hash = cached.get("llvm_sha256")
            if (
                cached.get("schema") != _LLVM_CACHE_SCHEMA
                or cached.get("digest") != digest
                or not isinstance(cached_llvm, str)
                or not isinstance(cached_hash, str)
                or hashlib.sha256(cached_llvm.encode("utf-8")).hexdigest() != cached_hash
            ):
                raise ValueError("stale or malformed LLVM cache")
            llvm = cached_llvm
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            try:
                cache_path.unlink()
            except OSError:
                pass
    program = parse_native(source)
    if llvm is None:
        llvm = emit_llvm(program, target)
        payload = json.dumps(
            {
                "digest": digest,
                "llvm": llvm,
                "llvm_sha256": hashlib.sha256(llvm.encode("utf-8")).hexdigest(),
                "schema": _LLVM_CACHE_SCHEMA,
            },
            sort_keys=True,
        )
        _atomic_write_text(cache_path, payload)
    _MEMORY_COMPILE_CACHE[digest] = (program, llvm)
    _MEMORY_COMPILE_CACHE.move_to_end(digest)
    while len(_MEMORY_COMPILE_CACHE) > _MEMORY_COMPILE_CACHE_LIMIT:
        _MEMORY_COMPILE_CACHE.popitem(last=False)
    return program, llvm, digest


def write_llvm(source_path: Path, output: Path, target: str | None = None) -> int:
    _, llvm, digest = compile_native_file(source_path, target=target)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(llvm, encoding="utf-8")
    print(json.dumps({"ok": True, "source": str(source_path), "output": str(output), "digest": digest}, sort_keys=True))
    return 0


def build(source_path: Path, output: Path, target: str | None = None, keep_llvm: bool = False) -> int:
    started_ns = time.perf_counter_ns()
    program, llvm, digest = compile_native_file(source_path, target=target)
    output.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = source_path.parent / ".holyfitra" / "cache"
    artifact_cache = cache_dir / f"{digest}.native"
    artifact_hash_path = cache_dir / f"{digest}.native.sha256"
    artifact_valid = False
    if artifact_cache.is_file() and artifact_cache.stat().st_size > 0 and artifact_hash_path.is_file():
        try:
            expected_hash = artifact_hash_path.read_text(encoding="ascii").strip()
            artifact_valid = bool(re.fullmatch(r"[0-9a-f]{64}", expected_hash)) and _sha256_file(artifact_cache) == expected_hash
        except (OSError, UnicodeError):
            artifact_valid = False
    if artifact_valid:
        if artifact_cache.resolve() != output.resolve():
            shutil.copy2(artifact_cache, output)
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        from holyfitra_telemetry import record_event
        record_event(source_path.parent, "compile", stage="native", cache_hit=True, digest=digest, elapsed_ms=elapsed_ms, target=target or "host")
        print(json.dumps({"ok": True, "output": str(output), "digest": digest, "target": target or "host", "cache_hit": True, "elapsed_ms": elapsed_ms}, sort_keys=True))
        return 0
    for stale_path in (artifact_cache, artifact_hash_path):
        if stale_path.exists() and not artifact_valid:
            try:
                stale_path.unlink()
            except OSError:
                pass
    main = next((function for function in program.functions if function.name == "main"), None)
    if main is None or main.parameters or main.return_type.name not in {"i32", "i64"}:
        raise HolyFitraError("build/run requires fn main() -> i32 or fn main() -> i64")
    with tempfile.TemporaryDirectory(prefix="holyfitra-") as temporary:
        llvm_path = Path(temporary) / f"{source_path.stem}.ll"
        llvm_path.write_text(llvm, encoding="utf-8")
        command = ["clang", "-O2"]
        if target:
            command.append(f"--target={target}")
        command += [str(llvm_path), "-o", str(output)]
        completed = subprocess.run(command, text=True, capture_output=True)
        if completed.returncode:
            raise HolyFitraError(completed.stderr.strip() or "clang failed")
        cache_dir.mkdir(parents=True, exist_ok=True)
        if artifact_cache.resolve() != output.resolve():
            shutil.copy2(output, artifact_cache)
        _atomic_write_text(artifact_hash_path, _sha256_file(artifact_cache) + "\n")
        if keep_llvm:
            persistent_llvm = output.with_suffix(output.suffix + ".ll")
            persistent_llvm.write_text(llvm, encoding="utf-8")
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    from holyfitra_telemetry import record_event
    record_event(source_path.parent, "compile", stage="native", cache_hit=False, digest=digest, elapsed_ms=elapsed_ms, target=target or "host")
    print(json.dumps({"ok": True, "output": str(output), "digest": digest, "target": target or "host", "cache_hit": False, "elapsed_ms": elapsed_ms}, sort_keys=True))
    return 0


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    entry: Path
    target: str | None = None
    frontend: Frontend = Frontend.NATIVE


def load_project(path: Path) -> Project:
    root = path if path.is_dir() else path.parent
    manifest = root / "holyfitra.toml"
    if not manifest.exists():
        if path.is_file():
            return Project(path.parent, path.stem, path, None, Frontend.NATIVE)
        raise HolyFitraError(f"no holyfitra.toml found in {root}")
    try:
        document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise HolyFitraError(f"invalid holyfitra.toml: {error}") from error
    project = document.get("project", {})
    build_config = document.get("build", {})
    try:
        frontend = parse_frontend(build_config.get("frontend", project.get("frontend", "native")))
    except ValueError as error:
        raise HolyFitraError(str(error)) from error
    name = project.get("name") or root.name
    entry = (root / str(project.get("entry", "src/main.hf"))).resolve()
    root_resolved = root.resolve()
    if entry != root_resolved and root_resolved not in entry.parents:
        raise HolyFitraError(f"project entry escapes project root: {entry}")
    if not entry.is_file():
        raise HolyFitraError(f"project entry does not exist: {entry}")
    return Project(root_resolved, str(name), entry, build_config.get("target"), frontend)


def init_project(root: Path, name: str | None = None) -> int:
    root.mkdir(parents=True, exist_ok=True)
    project_name = name or root.name
    source_dir = root / "src"
    source_dir.mkdir(exist_ok=True)
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    manifest = root / "holyfitra.toml"
    source = source_dir / "main.hf"
    if manifest.exists() or source.exists():
        raise HolyFitraError(f"project already exists: {root}")
    manifest.write_text(f'''[project]\nname = "{project_name}"\nentry = "src/main.hf"\n\n[build]\ntarget = "x86_64-pc-linux-gnu"\nfrontend = "native"\n''', encoding="utf-8")
    source.write_text(f"module {project_name}\nfn main() -> i32 {{\n    return 0\n}}\n", encoding="utf-8")
    smoke_test = tests_dir / "smoke.hf"
    smoke_test.write_text(f"module {project_name}_tests\nfn main() -> i32 {{\n    return 0\n}}\n", encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(root), "entry": str(source), "tests": str(tests_dir)}, sort_keys=True))
    return 0


def test_project(source_path: Path, target: str | None = None) -> int:
    project = load_project(source_path)
    effective_target = target or project.target or "x86_64-pc-linux-gnu"
    if not (effective_target == "host" or effective_target.startswith("x86_64")):
        raise HolyFitraError(f"holyfitra test requires an executable host target, got {effective_target}")
    tests_dir = project.root / "tests"
    test_sources = sorted(tests_dir.glob("*.hf")) if tests_dir.is_dir() else []
    if not test_sources:
        print(json.dumps({"ok": False, "project": str(project.root), "tests": [], "count": 0, "error": "no .hf tests found"}, indent=2, sort_keys=True))
        return 1
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="holyfitra-tests-") as temporary:
        temporary_root = Path(temporary)
        for test_source in test_sources:
            executable = temporary_root / test_source.stem
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    build(test_source, executable, target or project.target)
                completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
                results.append({"name": test_source.stem, "source": str(test_source), "status": completed.returncode, "passed": completed.returncode == 0})
            except (HolyFitraError, OSError, subprocess.SubprocessError) as error:
                results.append({"name": test_source.stem, "source": str(test_source), "status": None, "passed": False, "error": str(error)})
    passed = all(bool(result["passed"]) for result in results)
    print(json.dumps({"ok": passed, "project": str(project.root), "tests": results, "count": len(results)}, indent=2, sort_keys=True))
    return 0 if passed else 1


def package_file(source_path: Path, output: Path, version: str, target: str | None = None) -> int:
    project = load_project(source_path)
    from hyperc_package import HyperPackageBuilder
    relative_entry = project.entry.relative_to(project.root).as_posix()
    builder = HyperPackageBuilder(project.name, version, target or project.target or "host")
    builder.add_file(project.root, relative_entry, "source")
    builder.set_metadata(compiler="holyfitra", frontend=str(project.frontend), entry=relative_entry)
    package = builder.build()
    secret = os.environ.get("HOLYFITRA_PACKAGE_SECRET")
    if secret:
        package.sign_hmac(secret.encode("utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    package.write_manifest(output)
    print(json.dumps({"ok": True, "manifest": str(output), "digest": package.digest(), "signed": bool(secret)}, sort_keys=True))
    return 0


def plan_file(source_path: Path, output: Path | None = None) -> int:
    project = load_project(source_path)
    source = project.entry.read_text(encoding="utf-8")
    from hyperc_language_core import compile_source
    result = compile_source(source)
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str)
    if output is None:
        print(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({"ok": bool(result["valid"]), "output": str(output), "hyperir_digest": result["hyperir_digest"]}, sort_keys=True))
    return 0 if result["valid"] else 1


def check_file(source_path: Path, frontend: Frontend | str | None = None) -> int:
    project = load_project(source_path)
    source_path = project.entry
    try:
        selected_frontend = project.frontend if frontend is None else parse_frontend(frontend)
        source = read_source(source_path)
        if selected_frontend is Frontend.HYPERIR:
            from hyperc_language_core import compile_source
            result = compile_source(source)
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
            return 0 if result["valid"] else 1
        program = parse_native(source)
        validate_native(program)
        direct_calls, effective_effects = _effect_call_graph(program)
        print(json.dumps({"valid": True, "module": program.module, "call_graph": {name: sorted(calls) for name, calls in direct_calls.items()}, "effective_effects": {name: sorted(effects) for name, effects in effective_effects.items()}, "functions": [{"name": function.name, "effects": list(function.effects), "parameters": [{"name": name, "type": type_.name, "mode": type_.mode} for name, type_ in function.parameters], "task": ({"async": function.task.async_, "priority": function.task.priority, "deadline_ms": function.task.deadline_ms, "capacity": function.task.capacity, "cancelable": function.task.cancelable, "supervised": function.task.supervised} if function.task else None)} for function in program.functions]}, indent=2))
        return 0
    except (HolyFitraError, ValueError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2))
        return 1


def doctor_report() -> dict[str, object]:
    import importlib.util
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "termux": bool(os.environ.get("PREFIX", "").endswith("com.termux/files/usr")),
        "clang": shutil.which("clang") or False,
        "llvm_as": shutil.which("llvm-as") or False,
        "llc": shutil.which("llc") or False,
        "cmake": shutil.which("cmake") or False,
        "numpy": bool(importlib.util.find_spec("numpy")),
        "android_ndk": bool(os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")),
        "curses": bool(importlib.util.find_spec("curses")),
    }
    checks["native_backend_ready"] = bool(checks["clang"] and checks["python"])
    checks["hyperir_backend_ready"] = bool(checks["numpy"])
    checks["android_build_ready"] = bool(checks["android_ndk"] and checks["cmake"])
    return checks


def doctor() -> int:
    print(json.dumps(doctor_report(), indent=2, sort_keys=True, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holyfitra", description="Holy Fitra compiler and runtime driver")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="create a new Holy Fitra project")
    init_parser.add_argument("directory", type=Path)
    init_parser.add_argument("--name")
    doctor_parser = subparsers.add_parser("doctor", help="inspect compiler, Termux, LLVM, NumPy, and Android readiness")
    tui_parser = subparsers.add_parser("tui", help="open the Holy Fitra terminal workspace UI")
    tui_parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    tui_parser.add_argument("--snapshot", action="store_true")
    tui_parser.add_argument("--watch-interval", type=float, default=1.0)
    repl_parser = subparsers.add_parser("repl", help="start the interactive Holy Fitra REPL")
    bench_parser = subparsers.add_parser("bench", help="run compiler and AI runtime benchmark diagnostics")
    contracts_parser = subparsers.add_parser("contracts", help="validate structured task, supervisor, result, and kernel contracts")
    bench_parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    bench_parser.add_argument("--repeats", type=int, default=5)
    bench_parser.add_argument("-o", "--output", type=Path)
    check_parser = subparsers.add_parser("check", help="parse and validate a Holy Fitra source file or project directory")
    check_parser.add_argument("source", type=Path)
    check_parser.add_argument("--frontend", choices=[frontend.value for frontend in Frontend], help="explicitly select the frontend")
    plan_parser = subparsers.add_parser("plan", help="lower tensor/effect source into a HyperIR execution plan")
    plan_parser.add_argument("source", type=Path)
    plan_parser.add_argument("-o", "--output", type=Path)
    test_parser = subparsers.add_parser("test", help="build and run standalone Holy Fitra tests in a project")
    test_parser.add_argument("source", type=Path)
    test_parser.add_argument("--target")
    package_parser = subparsers.add_parser("package", help="create an integrity-checked Holy Fitra package manifest")
    package_parser.add_argument("source", type=Path)
    package_parser.add_argument("-o", "--output", type=Path, required=True)
    package_parser.add_argument("--version", default="0.1.0")
    package_parser.add_argument("--target")
    llvm_parser = subparsers.add_parser("emit-llvm", help="emit LLVM IR for the native scalar subset")
    llvm_parser.add_argument("source", type=Path)
    llvm_parser.add_argument("-o", "--output", type=Path, required=True)
    llvm_parser.add_argument("--target")
    build_parser = subparsers.add_parser("build", help="compile and link an executable")
    build_parser.add_argument("source", type=Path)
    build_parser.add_argument("-o", "--output", type=Path, required=True)
    build_parser.add_argument("--target")
    build_parser.add_argument("--keep-llvm", action="store_true")
    run_parser = subparsers.add_parser("run", help="build and execute a zero-argument main function")
    run_parser.add_argument("source", type=Path)
    run_parser.add_argument("--target")
    run_parser.add_argument("--keep-llvm", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init_project(args.directory, args.name)
        if args.command == "doctor":
            return doctor()
        if args.command == "tui":
            from holyfitra_tui import run_tui
            return run_tui(args.path, args.snapshot, args.watch_interval)
        if args.command == "repl":
            from holyfitra_repl import Repl
            return Repl().run()
        if args.command == "contracts":
            from holyfitra_contracts import demo
            print(json.dumps(demo(), indent=2, sort_keys=True))
            return 0
        if args.command == "bench":
            from holyfitra_benchmark import benchmark_project
            result = benchmark_project(args.path, args.repeats)
            rendered = json.dumps(result, indent=2, sort_keys=True, default=str)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0
        if args.command == "check":
            return check_file(args.source, args.frontend)
        if args.command == "plan":
            return plan_file(args.source, args.output)
        if args.command == "test":
            return test_project(args.source, args.target)
        if args.command == "package":
            return package_file(args.source, args.output, args.version, args.target)
        if args.command == "emit-llvm":
            project = load_project(args.source)
            return write_llvm(project.entry, args.output, args.target or project.target)
        if args.command == "build":
            project = load_project(args.source)
            return build(project.entry, args.output, args.target or project.target, args.keep_llvm)
        if args.command == "run":
            project = load_project(args.source)
            with tempfile.TemporaryDirectory(prefix="holyfitra-run-") as temporary:
                executable = Path(temporary) / "program"
                build(project.entry, executable, args.target or project.target, args.keep_llvm)
                completed = subprocess.run([str(executable)])
                return completed.returncode
    except (HolyFitraError, OSError, subprocess.SubprocessError) as error:
        print(f"holyfitra: error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
