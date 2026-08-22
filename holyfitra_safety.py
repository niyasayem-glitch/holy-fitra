"""Shared safety contracts for Holy Fitra Python frontends and tooling."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path


MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_AST_DEPTH = 512
MAX_FUNCTIONS = 4096
MAX_TOKENS = 1 << 16
MAX_TENSOR_ELEMENTS = 1 << 26
MAX_TELEMETRY_EVENTS = 500


class Frontend(StrEnum):
    NATIVE = "native"
    HYPERIR = "hyperir"


def parse_frontend(value: object) -> Frontend:
    if not isinstance(value, str):
        raise ValueError("frontend must be 'native' or 'hyperir'")
    try:
        return Frontend(value.strip().lower())
    except ValueError as error:
        raise ValueError(f"unsupported frontend: {value!r}") from error


def read_source(path: Path, *, max_bytes: int = MAX_SOURCE_BYTES) -> str:
    """Read UTF-8 source with a hard byte limit before decoding."""
    if max_bytes <= 0:
        raise ValueError("source byte limit must be positive")
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"source exceeds {max_bytes} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"source is not valid UTF-8: {error}") from error


__all__ = [
    "Frontend",
    "MAX_AST_DEPTH",
    "MAX_FUNCTIONS",
    "MAX_SOURCE_BYTES",
    "MAX_TOKENS",
    "MAX_TELEMETRY_EVENTS",
    "MAX_TENSOR_ELEMENTS",
    "parse_frontend",
    "read_source",
]
