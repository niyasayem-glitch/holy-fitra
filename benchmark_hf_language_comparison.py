#!/usr/bin/env python3
"""Run a bounded, matched host comparison for the locally available language toolchains.

The runtime comparison uses an identical dynamic-input 32-bit xorshift loop.
HF is separately compiled and executed through its current parameterless scalar
entry contract. It is excluded from the dynamic-input runtime ranking because
the contract has no supported argv/console/input primitive.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BENCHMARK_DIR = ROOT / "language_benchmarks"
RESULT_PATTERN = re.compile(r"result=(\d+)\s+loop_ns=(\d+)")
RUNTIME_ORDER = ("c_clang", "cpp_clang", "node_js", "python_cpython")
BUILD_ORDER = ("c_clang", "cpp_clang", "holy_fitra")


def run(command: list[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}\n{completed.stdout}")
    return completed


def version(command: list[str]) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    completed = run([executable, *command[1:]])
    return (completed.stdout or completed.stderr).splitlines()[0]


def reference(iterations: int, seed: int) -> int:
    state = seed & 0xFFFFFFFF
    for _ in range(iterations):
        state ^= (state << 13) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        state ^= state >> 17
        state &= 0xFFFFFFFF
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
    return state


def parse_runtime(name: str, command: list[str], expected: int) -> dict[str, object]:
    completed = run(command, timeout=120.0)
    match = RESULT_PATTERN.fullmatch(completed.stdout.strip())
    if match is None:
        raise RuntimeError(f"{name} emitted an unexpected result: {completed.stdout!r}")
    result = int(match.group(1))
    if result != expected:
        raise RuntimeError(f"{name} result mismatch: expected {expected}, got {result}")
    return {"language": name, "result": result, "loop_ns": int(match.group(2))}


def compile_runtime_binaries(build_dir: Path) -> dict[str, list[str]]:
    c_output = build_dir / "xorshift-c"
    cpp_output = build_dir / "xorshift-cpp"
    run(["clang", "-std=c17", "-O3", str(BENCHMARK_DIR / "xorshift32.c"), "-o", str(c_output)])
    run(["clang++", "-std=c++17", "-O3", str(BENCHMARK_DIR / "xorshift32.cpp"), "-o", str(cpp_output)])
    return {
        "c_clang": [str(c_output)],
        "cpp_clang": [str(cpp_output)],
        "node_js": ["node", str(BENCHMARK_DIR / "xorshift32.js")],
        "python_cpython": [sys.executable, str(BENCHMARK_DIR / "xorshift32.py")],
    }


def cold_build(language: str, temporary_root: Path) -> float:
    output = temporary_root / "out"
    started = time.perf_counter_ns()
    if language == "c_clang":
        run(["clang", "-std=c17", "-O3", str(BENCHMARK_DIR / "xorshift32.c"), "-o", str(output)])
    elif language == "cpp_clang":
        run(["clang++", "-std=c++17", "-O3", str(BENCHMARK_DIR / "xorshift32.cpp"), "-o", str(output)])
    elif language == "holy_fitra":
        source = temporary_root / "hf_loop_functional.hf"
        source.write_text((BENCHMARK_DIR / "hf_loop_functional.hf").read_text(encoding="utf-8"), encoding="utf-8")
        receipt = run([sys.executable, str(ROOT / "holyfitra_compiler.py"), "build", str(source), "-o", str(output)])
        payload = json.loads(receipt.stdout)
        if payload.get("cache_hit") is not False:
            raise RuntimeError(f"HF cold build unexpectedly reported a cache hit: {payload}")
        executed = subprocess.run([str(output)], text=True, capture_output=True)
        if executed.returncode != 45:
            raise RuntimeError(f"HF functional fixture should return 45, got {executed.returncode}")
    else:
        raise RuntimeError(f"unknown cold-build language: {language}")
    return (time.perf_counter_ns() - started) / 1_000_000.0


def summarize(values: list[float]) -> dict[str, float]:
    return {"mean": statistics.fmean(values), "median": statistics.median(values), "min": min(values), "max": max(values)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000_000)
    parser.add_argument("--seed", type=int, default=2463534242)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--output", type=Path, default=Path("/tmp/hf_language_comparison.json"))
    arguments = parser.parse_args()
    if arguments.iterations <= 0 or arguments.repeats <= 0:
        raise SystemExit("--iterations and --repeats must be positive")
    expected = reference(arguments.iterations, arguments.seed)
    versions = {
        "clang": version(["clang", "--version"]),
        "clang++": version(["clang++", "--version"]),
        "node": version(["node", "--version"]),
        "python": version([sys.executable, "--version"]),
        "rustc": version(["rustc", "--version"]),
        "go": version(["go", "version"]),
        "javac": version(["javac", "--version"]),
    }
    if any(versions[name] is None for name in ("clang", "clang++", "node", "python")):
        raise SystemExit("C, C++, Node.js, and Python toolchains are required for this bounded comparison")
    runtime_samples: dict[str, list[float]] = {name: [] for name in RUNTIME_ORDER}
    with tempfile.TemporaryDirectory(prefix="holyfitra-language-runtime-") as temporary:
        commands = compile_runtime_binaries(Path(temporary))
        for round_index in range(arguments.repeats):
            ordered = RUNTIME_ORDER[round_index % len(RUNTIME_ORDER):] + RUNTIME_ORDER[:round_index % len(RUNTIME_ORDER)]
            for name in ordered:
                sample = parse_runtime(name, [*commands[name], str(arguments.iterations), str(arguments.seed)], expected)
                runtime_samples[name].append(float(sample["loop_ns"]) / 1_000_000.0)
    build_samples: dict[str, list[float]] = {name: [] for name in BUILD_ORDER}
    for round_index in range(arguments.repeats):
        ordered = BUILD_ORDER[round_index % len(BUILD_ORDER):] + BUILD_ORDER[:round_index % len(BUILD_ORDER)]
        for name in ordered:
            with tempfile.TemporaryDirectory(prefix="holyfitra-language-build-") as temporary:
                build_samples[name].append(cold_build(name, Path(temporary)))
    payload = {
        "schema": "holyfitra.language-comparison/v1",
        "workload": "dynamic-input xorshift32 loop; loop-only timing from each runtime",
        "iterations": arguments.iterations,
        "seed": arguments.seed,
        "expected_result": expected,
        "repeats": arguments.repeats,
        "interleaving": "runtime and cold-build language order rotate once each round",
        "toolchains": versions,
        "runtime_ms": {name: summarize(samples) for name, samples in runtime_samples.items()},
        "cold_build_ms": {name: summarize(samples) for name, samples in build_samples.items()},
        "hf_runtime_boundary": "HF functional loop fixture compiled and returned 45, but is excluded from dynamic-input loop timing because current native scalar main has no supported argv/console/input primitive.",
        "exclusions": {name: "not installed in this sandbox" for name in ("rustc", "go", "javac") if versions[name] is None},
        "boundary": "Host-only microbenchmark; it is not a universal language ranking and does not measure Android, ARM64, garbage collection, memory allocation, I/O, concurrency, or application workloads.",
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(arguments.output), "expected_result": expected}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
