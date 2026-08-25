#!/usr/bin/env python3
"""Measure the new HF `arg_i32` bridge on a dynamic LCG loop.

Each runtime receives the same decimal iteration count and seed. Timing is
whole-process wall time, deliberately including process startup because HF's
new bridge is an executable-entry capability. Results are host-only and no
runtime is declared universally faster from this single microbenchmark.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "language_benchmarks"
RUNTIMES = ("c_clang", "cpp_clang", "node_js", "python_cpython", "holy_fitra")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=120.0)


def compile_native(command: list[str]) -> None:
    completed = run(command)
    if completed.returncode:
        raise RuntimeError(f"compile failed: {' '.join(command)}\n{completed.stderr}")


def reference(iterations: int, seed: int) -> int:
    state = seed & 0xFFFFFFFF
    for _ in range(iterations):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
    return state


def parse_result(stdout: str) -> int:
    prefix = "result="
    if not stdout.startswith(prefix):
        raise RuntimeError(f"unexpected runtime output: {stdout!r}")
    return int(stdout[len(prefix):].strip())


def summarize(values: list[float]) -> dict[str, float]:
    return {"mean": statistics.fmean(values), "median": statistics.median(values), "min": min(values), "max": max(values)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000_000)
    parser.add_argument("--seed", type=int, default=123456789)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--output", type=Path, default=Path("/tmp/hf_dynamic_input_comparison.json"))
    arguments = parser.parse_args()
    if arguments.iterations <= 0 or arguments.iterations > 2**31 - 1:
        raise SystemExit("--iterations must be between 1 and 2147483647")
    if not 0 <= arguments.seed <= 2**31 - 1 or arguments.repeats <= 0:
        raise SystemExit("--seed must fit nonnegative i32 and --repeats must be positive")
    required = ("clang", "clang++", "node")
    absent = [tool for tool in required if shutil.which(tool) is None]
    if absent:
        raise SystemExit(f"required toolchains are unavailable: {', '.join(absent)}")
    expected = reference(arguments.iterations, arguments.seed)
    samples: dict[str, list[float]] = {name: [] for name in RUNTIMES}
    with tempfile.TemporaryDirectory(prefix="holyfitra-dynamic-input-") as temporary:
        root = Path(temporary)
        c_binary = root / "lcg-c"
        cpp_binary = root / "lcg-cpp"
        hf_binary = root / "lcg-hf"
        compile_native(["clang", "-std=c17", "-O3", str(FIXTURES / "lcg32.c"), "-o", str(c_binary)])
        compile_native(["clang++", "-std=c++17", "-O3", str(FIXTURES / "lcg32.cpp"), "-o", str(cpp_binary)])
        hf_source = root / "hf_lcg32_dynamic.hf"
        hf_source.write_text((FIXTURES / "hf_lcg32_dynamic.hf").read_text(encoding="utf-8"), encoding="utf-8")
        compiler = run([sys.executable, str(ROOT / "holyfitra_compiler.py"), "build", str(hf_source), "-o", str(hf_binary)])
        if compiler.returncode:
            raise RuntimeError(f"HF build failed: {compiler.stderr}\n{compiler.stdout}")
        commands = {
            "c_clang": [str(c_binary)],
            "cpp_clang": [str(cpp_binary)],
            "node_js": ["node", str(FIXTURES / "lcg32.js")],
            "python_cpython": [sys.executable, str(FIXTURES / "lcg32.py")],
            "holy_fitra": [str(hf_binary)],
        }
        for round_index in range(arguments.repeats):
            order = RUNTIMES[round_index % len(RUNTIMES):] + RUNTIMES[:round_index % len(RUNTIMES)]
            for name in order:
                started = time.perf_counter_ns()
                completed = run([*commands[name], str(arguments.iterations), str(arguments.seed)])
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
                if name == "holy_fitra":
                    if completed.returncode != expected & 0xFF:
                        raise RuntimeError(f"HF exit status mismatch: expected {expected & 0xFF}, got {completed.returncode}")
                else:
                    if completed.returncode or parse_result(completed.stdout) != expected:
                        raise RuntimeError(f"{name} result mismatch: {completed.stderr}\n{completed.stdout}")
                samples[name].append(elapsed_ms)
    payload = {
        "schema": "holyfitra.dynamic-input-comparison/v1",
        "workload": "dynamic argv LCG32; whole-process wall time including startup",
        "iterations": arguments.iterations,
        "seed": arguments.seed,
        "expected_result_u32": expected,
        "expected_exit_code": expected & 0xFF,
        "repeats": arguments.repeats,
        "order": "rotated once per round",
        "wall_ms": {name: summarize(values) for name, values in samples.items()},
        "hf_verification": "HF return value is validated modulo 256 through the process exit status; the other fixtures print and validate the full unsigned-32-bit result.",
        "boundary": "Host-only microbenchmark. It does not measure Android, ARM64, I/O, allocation, concurrency, or application performance.",
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(arguments.output), "expected_result_u32": expected}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
