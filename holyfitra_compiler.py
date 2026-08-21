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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


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


Statement = LetStmt | ReturnStmt | IfStmt


@dataclass(frozen=True)
class TaskMetadata:
    async_: bool = False
    priority: int = 0
    deadline_ms: int | None = None
    capacity: int = 1
    cancelable: bool = True
    supervised: bool = False


@dataclass(frozen=True)
class Function:
    name: str
    parameters: tuple[tuple[str, Type], ...]
    return_type: Type
    body: tuple[Statement, ...]
    line: int
    effects: tuple[str, ...] = ()
    task: TaskMetadata | None = None


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
            if self.accept("IDENT", "capability"):
                self._skip_balanced_block()
                continue
            if self.accept("IDENT", "budget"):
                self._skip_to_statement_end()
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

    def parse_function(self) -> Function:
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
        if self.accept("IDENT", "if"):
            line = self.tokens[self.index - 1].line
            condition = self.parse_expression()
            then_body = self.parse_block()
            else_body: tuple[Statement, ...] = ()
            if self.accept("IDENT", "else"):
                else_body = self.parse_block()
            return IfStmt(condition, then_body, else_body, line)
        if self.accept("IDENT", "let") or self.accept("IDENT", "var"):
            name = self.expect("IDENT")
            declared_type = None
            if self.accept("PUNCT", ":"):
                declared_type = self.parse_type()
            self.expect("OP", "=")
            value = self.parse_expression()
            self.accept("PUNCT", ";")
            return LetStmt(name.text, declared_type, value, name.line)
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
        return self.parse_additive()

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
    return Parser(lex(source)).parse()


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
        if isinstance(statement, LetStmt):
            calls.update(_direct_calls_expression(statement.value))
        elif isinstance(statement, ReturnStmt) and statement.value is not None:
            calls.update(_direct_calls_expression(statement.value))
        elif isinstance(statement, IfStmt):
            calls.update(_direct_calls_expression(statement.condition))
            calls.update(_direct_calls_block(statement.then_body))
            calls.update(_direct_calls_block(statement.else_body))
    return calls


def _effect_call_graph(program: Program) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    functions = {function.name: function for function in program.functions}
    direct = {name: _direct_calls_block(function.body) for name, function in functions.items()}
    for name, calls in direct.items():
        unknown = calls - functions.keys()
        if unknown:
            raise HolyFitraError(f"function {name} calls unknown functions: {', '.join(sorted(unknown))}")
    memo: dict[str, set[str]] = {}
    active: set[str] = set()

    def closure(name: str) -> set[str]:
        if name in memo:
            return set(memo[name])
        if name in active:
            return set()
        active.add(name)
        result = set(functions[name].effects)
        for callee in direct[name]:
            result.update(closure(callee))
        active.remove(name)
        memo[name] = result
        return set(result)

    for name in functions:
        closure(name)
    return direct, memo


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
        variables = dict(function.parameters)

        def validate_block(statements: tuple[Statement, ...], scope: dict[str, Type]) -> bool:
            guaranteed_return = False
            for statement in statements:
                if isinstance(statement, LetStmt):
                    actual = _infer_expression(statement.value, scope, functions)
                    if statement.type is not None and not _same_value_type(actual, statement.type):
                        raise HolyFitraError(f"let {statement.name} declares {statement.type.name} but receives {actual.name}")
                    scope[statement.name] = statement.type or actual
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
                    then_return = validate_block(statement.then_body, dict(scope))
                    else_return = bool(statement.else_body) and validate_block(statement.else_body, dict(scope))
                    guaranteed_return = then_return and else_return
                if guaranteed_return:
                    break
            return guaranteed_return

        guaranteed_return = validate_block(function.body, variables)
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
        lines = [f"; Holy Fitra module {self.program.module}", f'target triple = "{triple}"', ""]
        for function in self.program.functions:
            lines.extend(self.emit_function(function))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def emit_expr(self, expression: Expr) -> tuple[str, Type]:
        if isinstance(expression, BoolLiteral):
            return ("1" if expression.value else "0"), Type("bool")
        if isinstance(expression, IntLiteral):
            return str(expression.value), Type("i32")
        if isinstance(expression, NameExpr):
            if expression.name not in self.variables:
                raise HolyFitraError(f"unknown value {expression.name}")
            return self.variables[expression.name], self.types[expression.name]
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
            left, type_ = self.emit_expr(expression.left)
            right, right_type = self.emit_expr(expression.right)
            if not _same_value_type(type_, right_type):
                raise HolyFitraError("binary operands have different types")
            if expression.operator in {"&&", "||"}:
                opcode = "and" if expression.operator == "&&" else "or"
                result = self.temp()
                self.current_lines.append(f"  {result} = {opcode} i1 {left}, {right}")
                return result, Type("bool")
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
            function = self.functions[expression.name]
            args: list[str] = []
            for argument, (_, parameter_type) in zip(expression.arguments, function.parameters):
                value, actual_type = self.emit_expr(argument)
                if not _same_value_type(actual_type, parameter_type):
                    raise HolyFitraError("call argument type mismatch")
                args.append(f"{parameter_type.llvm} {value}")
            result_type = function.return_type
            if result_type.name == "void":
                self.current_lines.append(f"  call void @{function.name}({', '.join(args)})")
                return "", result_type
            result = self.temp()
            self.current_lines.append(f"  {result} = call {result_type.llvm} @{function.name}({', '.join(args)})")
            return result, result_type
        raise HolyFitraError("unsupported expression")

    def emit_function(self, function: Function) -> list[str]:
        validate_native(self.program)
        self.counter = 0
        self.block_counter = 0
        self.terminated = False
        self.variables = {name: f"%{name}" for name, _ in function.parameters}
        self.types = dict(function.parameters)
        parameters = ", ".join(f"{type_.llvm} %{name}" for name, type_ in function.parameters)
        return_type = "void" if function.return_type.name == "void" else function.return_type.llvm
        effect_comment = f"; effects: {', '.join(function.effects) if function.effects else 'pure'}"
        ownership_comment = "; ownership: " + ", ".join(f"{name}:{type_.mode}" for name, type_ in function.parameters) if function.parameters else "; ownership: none"
        task_comment = "; task: " + (json.dumps({"async": function.task.async_, "priority": function.task.priority, "deadline_ms": function.task.deadline_ms, "capacity": function.task.capacity, "cancelable": function.task.cancelable, "supervised": function.task.supervised}, sort_keys=True) if function.task else "sync")
        lines = [effect_comment, ownership_comment, task_comment, f"define {return_type} @{function.name}({parameters}) {{", "entry:"]
        self.current_lines = lines
        self.emit_block(function.body)
        if not self.terminated and function.return_type.name == "void":
            lines.append("  ret void")
        elif not self.terminated:
            raise HolyFitraError(f"function {function.name} has an unterminated return path")
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
                self.variables[statement.name] = value
                self.types[statement.name] = statement.type or value_type
            elif isinstance(statement, ReturnStmt):
                if statement.value is None:
                    self.current_lines.append("  ret void")
                else:
                    value, value_type = self.emit_expr(statement.value)
                    self.current_lines.append(f"  ret {value_type.llvm} {value}")
                self.terminated = True
                block_terminated = True
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


def compile_native_file(source_path: Path, cache_dir: Path | None = None, target: str | None = None) -> tuple[Program, str, str]:
    source = source_path.read_text(encoding="utf-8")
    cache_identity = source + "\\0" + (target or "x86_64-pc-linux-gnu")
    digest = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()
    if cache_dir is None:
        cache_dir = source_path.parent / ".holyfitra" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{digest}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return parse_native(source), cached["llvm"], digest
    program = parse_native(source)
    llvm = emit_llvm(program, target)
    cache_path.write_text(json.dumps({"digest": digest, "llvm": llvm}, sort_keys=True), encoding="utf-8")
    return program, llvm, digest


def write_llvm(source_path: Path, output: Path, target: str | None = None) -> int:
    _, llvm, digest = compile_native_file(source_path, target=target)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(llvm, encoding="utf-8")
    print(json.dumps({"ok": True, "source": str(source_path), "output": str(output), "digest": digest}, sort_keys=True))
    return 0


def build(source_path: Path, output: Path, target: str | None = None, keep_llvm: bool = False) -> int:
    program, llvm, digest = compile_native_file(source_path, target=target)
    output.parent.mkdir(parents=True, exist_ok=True)
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
        if keep_llvm:
            persistent_llvm = output.with_suffix(output.suffix + ".ll")
            persistent_llvm.write_text(llvm, encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "digest": digest, "target": target or "host"}, sort_keys=True))
    return 0


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    entry: Path
    target: str | None = None


def load_project(path: Path) -> Project:
    root = path if path.is_dir() else path.parent
    manifest = root / "holyfitra.toml"
    if not manifest.exists():
        if path.is_file():
            return Project(path.parent, path.stem, path, None)
        raise HolyFitraError(f"no holyfitra.toml found in {root}")
    try:
        document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise HolyFitraError(f"invalid holyfitra.toml: {error}") from error
    project = document.get("project", {})
    build_config = document.get("build", {})
    name = project.get("name") or root.name
    entry = root / project.get("entry", "src/main.hf")
    if not entry.is_file():
        raise HolyFitraError(f"project entry does not exist: {entry}")
    return Project(root, str(name), entry, build_config.get("target"))


def init_project(root: Path, name: str | None = None) -> int:
    root.mkdir(parents=True, exist_ok=True)
    project_name = name or root.name
    source_dir = root / "src"
    source_dir.mkdir(exist_ok=True)
    manifest = root / "holyfitra.toml"
    source = source_dir / "main.hf"
    if manifest.exists() or source.exists():
        raise HolyFitraError(f"project already exists: {root}")
    manifest.write_text(f'''[project]\nname = "{project_name}"\nentry = "src/main.hf"\n\n[build]\ntarget = "x86_64-pc-linux-gnu"\n''', encoding="utf-8")
    source.write_text(f"module {project_name}\nfn main() -> i32 {{\n    return 0\n}}\n", encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(root), "entry": str(source)}, sort_keys=True))
    return 0


def package_file(source_path: Path, output: Path, version: str, target: str | None = None) -> int:
    project = load_project(source_path)
    from hyperc_package import HyperPackageBuilder
    relative_entry = project.entry.relative_to(project.root).as_posix()
    builder = HyperPackageBuilder(project.name, version, target or project.target or "host")
    builder.add_file(project.root, relative_entry, "source")
    builder.set_metadata(compiler="holyfitra", frontend="native+hyperir", entry=relative_entry)
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


def check_file(source_path: Path) -> int:
    project = load_project(source_path)
    source_path = project.entry
    source = source_path.read_text(encoding="utf-8")
    try:
        # Tensor/HyperIR programs remain fully supported by the existing frontend.
        if "Tensor" in source or "capability" in source or "budget" in source:
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
    repl_parser = subparsers.add_parser("repl", help="start the interactive Holy Fitra REPL")
    bench_parser = subparsers.add_parser("bench", help="run compiler and AI runtime benchmark diagnostics")
    contracts_parser = subparsers.add_parser("contracts", help="validate structured task, supervisor, result, and kernel contracts")
    bench_parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    bench_parser.add_argument("--repeats", type=int, default=5)
    bench_parser.add_argument("-o", "--output", type=Path)
    check_parser = subparsers.add_parser("check", help="parse and validate a Holy Fitra source file or project directory")
    check_parser.add_argument("source", type=Path)
    plan_parser = subparsers.add_parser("plan", help="lower tensor/effect source into a HyperIR execution plan")
    plan_parser.add_argument("source", type=Path)
    plan_parser.add_argument("-o", "--output", type=Path)
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
            return run_tui(args.path, args.snapshot)
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
            return check_file(args.source)
        if args.command == "plan":
            return plan_file(args.source, args.output)
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
