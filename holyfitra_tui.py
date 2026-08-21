#!/usr/bin/env python3
"""Holy Fitra terminal workspace UI.

The UI intentionally uses only Python's standard library so it works in
Termux without Textual/Rich dependencies.  `--snapshot` is deterministic and
is used by scripts, CI, and terminals without a real TTY.
"""
from __future__ import annotations

import argparse
import curses
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from holyfitra_compiler import HolyFitraError, load_project, parse_native, validate_native


@dataclass
class Workspace:
    root: Path
    files: list[Path] = field(default_factory=list)
    selected: int = 0
    status: str = "ready"
    last_result: dict[str, object] | None = None

    @classmethod
    def open(cls, path: Path) -> "Workspace":
        root = path.resolve() if path.is_dir() else path.parent.resolve()
        workspace = cls(root)
        workspace.refresh()
        return workspace

    def refresh(self) -> None:
        self.files = sorted(
            [candidate for candidate in self.root.rglob("*.hf") if ".holyfitra" not in candidate.parts and "build" not in candidate.parts],
            key=lambda candidate: candidate.as_posix(),
        )
        if self.files:
            self.selected = min(self.selected, len(self.files) - 1)
        else:
            self.selected = 0

    @property
    def selected_file(self) -> Path | None:
        return self.files[self.selected] if self.files else None

    def source(self) -> str:
        if self.selected_file is None:
            return ""
        return self.selected_file.read_text(encoding="utf-8")

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def inspect(self) -> dict[str, object]:
        path = self.selected_file
        if path is None:
            self.last_result = {"valid": False, "error": "no .hf files found"}
            return self.last_result
        source = self.source()
        try:
            if any(marker in source for marker in ("Tensor", "capability", "budget")):
                from hyperc_language_core import compile_source
                result = compile_source(source)
                self.last_result = {
                    "valid": bool(result["valid"]),
                    "mode": "hyperir",
                    "module": result["module"],
                    "diagnostics": result["diagnostics"],
                    "hyperir_digest": result["hyperir_digest"],
                    "operations": len(result["lowered_plan"]),
                }
            else:
                program = parse_native(source)
                validate_native(program)
                from holyfitra_compiler import _effect_call_graph
                direct_calls, effective_effects = _effect_call_graph(program)
                self.last_result = {"valid": True, "mode": "native", "module": program.module, "call_graph": {name: sorted(calls) for name, calls in direct_calls.items()}, "effective_effects": {name: sorted(effects) for name, effects in effective_effects.items()}, "functions": [{"name": fn.name, "effects": list(fn.effects), "parameters": [{"name": name, "type": type_.name, "mode": type_.mode} for name, type_ in fn.parameters], "task": ({"async": fn.task.async_, "priority": fn.task.priority, "deadline_ms": fn.task.deadline_ms, "capacity": fn.task.capacity, "cancelable": fn.task.cancelable, "supervised": fn.task.supervised} if fn.task else None)} for fn in program.functions]}
        except (HolyFitraError, OSError, ValueError) as error:
            self.last_result = {"valid": False, "error": str(error), "file": self.relative(path)}
        self.status = "valid" if self.last_result.get("valid") else "error"
        return self.last_result

    def benchmark(self) -> dict[str, object]:
        from holyfitra_benchmark import benchmark_project
        try:
            result = benchmark_project(self.root, repeats=3)
        except (HolyFitraError, OSError, ValueError) as error:
            result = {"valid": False, "error": str(error)}
        self.last_result = result
        self.status = "benchmarked" if result.get("valid", True) else "benchmark error"
        return result

    def move(self, delta: int) -> None:
        if self.files:
            self.selected = (self.selected + delta) % len(self.files)
            self.status = "ready"

    def snapshot(self, width: int = 100, source_lines: int = 18) -> str:
        self.refresh()
        lines = ["HOLY FITRA WORKSPACE", "=" * min(width, 80), f"root: {self.root}", f"status: {self.status}", "", "FILES"]
        if not self.files:
            lines.append("  (no .hf files found)")
        for index, path in enumerate(self.files):
            marker = ">" if index == self.selected else " "
            lines.append(f" {marker} {self.relative(path)}")
        lines.extend(["", "SOURCE"])
        if self.selected_file:
            for number, line in enumerate(self.source().splitlines()[:source_lines], 1):
                lines.append(f" {number:4d} | {line}")
        lines.extend(["", "INSPECTION"])
        result = self.last_result or self.inspect()
        lines.extend(json.dumps(result, indent=2, sort_keys=True, default=str).splitlines())
        lines.extend(["", "KEYS: j/k or arrows select | c check | p plan summary | b benchmark | r refresh | q quit"])
        return "\n".join(lines)


class CursesApp:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def draw(self, screen) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        title = "Holy Fitra TUI  |  q quit  j/k move  c check  p plan  b bench  r refresh"
        screen.addnstr(0, 0, title, max(1, width - 1), curses.A_BOLD)
        split = max(22, min(34, width // 3))
        screen.addnstr(1, 0, f"Workspace: {self.workspace.root}", max(1, width - 1))
        screen.addnstr(3, 0, "FILES", split - 1, curses.A_UNDERLINE)
        for index, path in enumerate(self.workspace.files[: max(0, height - 10)]):
            marker = ">" if index == self.workspace.selected else " "
            label = f"{marker} {self.workspace.relative(path)}"
            attribute = curses.A_REVERSE if index == self.workspace.selected else curses.A_NORMAL
            screen.addnstr(4 + index, 0, label, max(1, split - 1), attribute)
        screen.addnstr(3, split + 1, "SOURCE / PLAN", max(1, width - split - 2), curses.A_UNDERLINE)
        source = self.workspace.source().splitlines() if self.workspace.selected_file else []
        for offset, line in enumerate(source[: max(0, height - 12)]):
            screen.addnstr(4 + offset, split + 1, f"{offset + 1:4d} | {line}", max(1, width - split - 2))
        result = self.workspace.last_result or self.workspace.inspect()
        status_y = max(5, height - 7)
        screen.addnstr(status_y, 0, "INSPECTION", max(1, width - 1), curses.A_UNDERLINE)
        summary = json.dumps(result, sort_keys=True, default=str)
        screen.addnstr(status_y + 1, 0, summary, max(1, width - 1))
        screen.addnstr(height - 2, 0, f"status: {self.workspace.status}", max(1, width - 1), curses.A_BOLD)
        screen.refresh()

    def run(self, screen) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        self.workspace.inspect()
        while True:
            self.draw(screen)
            key = screen.getch()
            if key in {ord("q"), ord("Q"), 27}:
                return
            if key in {ord("j"), curses.KEY_DOWN}:
                self.workspace.move(1)
                self.workspace.inspect()
            elif key in {ord("k"), curses.KEY_UP}:
                self.workspace.move(-1)
                self.workspace.inspect()
            elif key in {ord("r"), ord("R")}:
                self.workspace.refresh()
                self.workspace.inspect()
            elif key in {ord("c"), ord("C"), ord("p"), ord("P")}:
                self.workspace.inspect()
            elif key in {ord("b"), ord("B")}:
                self.workspace.benchmark()


def run_tui(path: Path, snapshot: bool = False) -> int:
    workspace = Workspace.open(path)
    if snapshot or not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(workspace.snapshot())
        return 0
    curses.wrapper(CursesApp(workspace).run)
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holyfitra tui")
    parser.add_argument("path", nargs="?", default=".", type=Path)
    parser.add_argument("--snapshot", action="store_true", help="print a deterministic text view instead of opening curses")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run_tui(args.path, args.snapshot)
    except (HolyFitraError, OSError, curses.error) as error:
        print(f"holyfitra tui: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
