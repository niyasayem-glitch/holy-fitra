#!/usr/bin/env python3
"""Small deterministic benchmark dashboard for Holy Fitra development."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from holyfitra_compiler import HolyFitraError, compile_native_file, load_project


def _stats(values: list[float]) -> dict[str, float]:
    values = sorted(values)
    if not values:
        return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}
    def percentile(fraction: float) -> float:
        index = min(len(values) - 1, int(round((len(values) - 1) * fraction)))
        return values[index]
    return {"count": len(values), "mean_ms": sum(values) / len(values), "p50_ms": percentile(0.50), "p95_ms": percentile(0.95)}


def benchmark_project(path: Path, repeats: int = 5) -> dict[str, Any]:
    project = load_project(path)
    source = project.entry.read_text(encoding="utf-8")
    result: dict[str, Any] = {"project": project.name, "entry": str(project.entry), "repeats": repeats}
    if "Tensor" in source or "capability" in source or "budget" in source:
        from hyperc_language_core import compile_source
        durations = []
        last_plan = None
        for _ in range(repeats):
            start = time.perf_counter_ns()
            last_plan = compile_source(source)
            durations.append((time.perf_counter_ns() - start) / 1_000_000.0)
        result["frontend"] = "hyperir"
        result["compile"] = _stats(durations)
        result["valid"] = bool(last_plan["valid"])
        result["hyperir_digest"] = last_plan["hyperir_digest"]
        result["operations"] = len(last_plan["lowered_plan"])
    else:
        durations = []
        last_digest = None
        cache_dir = project.root / ".holyfitra" / "benchmark-cache"
        for _ in range(repeats):
            start = time.perf_counter_ns()
            _, _, last_digest = compile_native_file(project.entry, cache_dir=cache_dir)
            durations.append((time.perf_counter_ns() - start) / 1_000_000.0)
        result["frontend"] = "native"
        result["compile"] = _stats(durations)
        result["valid"] = True
        result["digest"] = last_digest
    try:
        from hyperc_proof_quant import demo as proof_demo
        start = time.perf_counter_ns()
        proof = proof_demo()
        result["quantization"] = {"elapsed_ms": (time.perf_counter_ns() - start) / 1_000_000.0, "precision": proof["candidate"]["precision"], "proof_verified": proof["proof_verified"]}
    except Exception as error:
        result["quantization"] = {"error": str(error)}
    try:
        from holy_fitra_ragged_attention import demo as ragged_demo
        start = time.perf_counter_ns()
        ragged = ragged_demo()
        result["ragged_attention"] = {"elapsed_ms": (time.perf_counter_ns() - start) / 1_000_000.0, "max_error": ragged["max_error"], "total_tokens": ragged["total_tokens"]}
    except Exception as error:
        result["ragged_attention"] = {"error": str(error)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="holyfitra bench")
    parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
    try:
        result = benchmark_project(args.path, args.repeats)
    except (HolyFitraError, OSError, ValueError) as error:
        print(f"holyfitra bench: error: {error}")
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
