#!/usr/bin/env python3
"""Interactive Holy Fitra REPL for Termux and ordinary terminals."""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Callable, Iterable, TextIO

from holyfitra_compiler import HolyFitraError, build, check_file, emit_llvm, load_project, parse_native, validate_native

HELP = """Holy Fitra REPL commands:
  /help                         Show this help.
  /project PATH                 Load a source file or holyfitra.toml project.
  /check                        Validate the loaded project.
  /plan [OUTPUT]                Emit a HyperIR plan for tensor/effect source.
  /llvm OUTPUT                  Emit native-subset LLVM IR.
  /build OUTPUT                 Build a native executable.
  /source                       Enter multiline Holy Fitra source; finish with /end.
  /show                         Show the current source path and source text.
  /clear                        Clear the transient source buffer.
  /quit                         Exit the REPL.

A line beginning with / is a command. Source lines are accumulated only after
/source, so ordinary Holy Fitra text is never executed as a shell command.
"""


class Repl:
    def __init__(self, *, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout):
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.project_path: Path | None = None
        self.source_buffer: list[str] = []

    def write(self, text: str = "") -> None:
        self.output_stream.write(text + "\n")
        self.output_stream.flush()

    def prompt(self, text: str) -> str | None:
        self.output_stream.write(text)
        self.output_stream.flush()
        line = self.input_stream.readline()
        if line == "":
            return None
        return line.rstrip("\n")

    def current_source(self) -> str:
        if self.source_buffer:
            return "\n".join(self.source_buffer) + "\n"
        if self.project_path is not None:
            project = load_project(self.project_path)
            return project.entry.read_text(encoding="utf-8")
        return ""

    def execute(self, command_line: str) -> bool:
        try:
            parts = shlex.split(command_line)
        except ValueError as error:
            self.write(f"parse error: {error}")
            return True
        if not parts:
            return True
        command = parts[0].lower()
        args = parts[1:]
        if command in {"/quit", "/exit", ":q"}:
            return False
        if command in {"/help", ":help"}:
            self.write(HELP.rstrip())
            return True
        if command == "/project":
            if len(args) != 1:
                self.write("usage: /project PATH")
            else:
                self.project_path = Path(args[0]).expanduser().resolve()
                self.source_buffer.clear()
                try:
                    project = load_project(self.project_path)
                    self.write(f"loaded {project.name}: {project.entry}")
                except (HolyFitraError, OSError) as error:
                    self.write(f"project error: {error}")
            return True
        if command == "/source":
            self.source_buffer.clear()
            self.write("Enter Holy Fitra source. Finish with /end.")
            while True:
                line = self.prompt("... ")
                if line is None or line == "/end":
                    break
                self.source_buffer.append(line)
            self.write(f"buffered {len(self.source_buffer)} lines")
            return True
        if command == "/clear":
            self.source_buffer.clear()
            self.write("source buffer cleared")
            return True
        if command == "/show":
            if self.source_buffer:
                self.write("<transient source buffer>")
                self.write("\n".join(self.source_buffer))
            elif self.project_path:
                project = load_project(self.project_path)
                self.write(str(project.entry))
                self.write(project.entry.read_text(encoding="utf-8"))
            else:
                self.write("no project or source buffer loaded")
            return True
        source = self.current_source()
        if command == "/check":
            if self.source_buffer:
                try:
                    program = parse_native(source)
                    validate_native(program)
                    self.write(json.dumps({"valid": True, "module": program.module, "functions": [fn.name for fn in program.functions]}, indent=2))
                except HolyFitraError as error:
                    self.write(json.dumps({"valid": False, "error": str(error)}, indent=2))
            elif self.project_path:
                check_file(self.project_path)
            else:
                self.write("load a project or enter /source first")
            return True
        if command == "/plan":
            if not source:
                self.write("load a project or enter /source first")
            else:
                temporary = Path(".holyfitra-repl-plan.json")
                if args:
                    temporary = Path(args[0])
                try:
                    from hyperc_language_core import compile_source
                    result = compile_source(source)
                    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
                    self.write(f"plan written to {temporary} (valid={result['valid']})")
                except (HolyFitraError, OSError, KeyError) as error:
                    self.write(f"plan error: {error}")
            return True
        if command == "/llvm":
            if len(args) != 1 or not source:
                self.write("usage: /llvm OUTPUT")
            else:
                try:
                    temporary = Path(".holyfitra-repl-source.hf")
                    temporary.write_text(source, encoding="utf-8")
                    emit_llvm(parse_native(source), None).strip()
                    from holyfitra_compiler import write_llvm
                    write_llvm(temporary, Path(args[0]))
                except (HolyFitraError, OSError) as error:
                    self.write(f"LLVM error: {error}")
            return True
        if command == "/build":
            if len(args) != 1 or not source:
                self.write("usage: /build OUTPUT")
            else:
                try:
                    temporary = Path(".holyfitra-repl-source.hf")
                    temporary.write_text(source, encoding="utf-8")
                    build(temporary, Path(args[0]))
                except (HolyFitraError, OSError) as error:
                    self.write(f"build error: {error}")
            return True
        self.write(f"unknown command: {command}. Type /help.")
        return True

    def run(self) -> int:
        self.write("Holy Fitra REPL. Type /help for commands.")
        while True:
            line = self.prompt("holyfitra> ")
            if line is None:
                return 0
            if line.startswith("/") or line.startswith(":"):
                if not self.execute(line):
                    return 0
            elif line.strip():
                self.write("Source text is accepted through /source; type /help for commands.")


def run_repl(lines: Iterable[str]) -> str:
    from io import StringIO

    input_stream = StringIO("\n".join(lines) + "\n")
    output_stream = StringIO()
    Repl(input_stream=input_stream, output_stream=output_stream).run()
    return output_stream.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(prog="holyfitra repl")
    parser.parse_args()
    return Repl().run()


if __name__ == "__main__":
    raise SystemExit(main())
