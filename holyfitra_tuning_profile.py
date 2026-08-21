#!/usr/bin/env python3
from __future__ import annotations

import cProfile
import json
import pstats
import subprocess
import tempfile
import time
from pathlib import Path

from holyfitra_compiler import build, emit_llvm, parse_native, validate_native
from holyfitra_contracts import KernelContract

SOURCE = """module tune
fn infer(x: borrow i32) -> i32 effects [model, memory] task [async, priority=5, deadline_ms=50, capacity=4, supervised] {
    if x >= 0 {
        return x + 1
    } else {
        return 0
    }
}
fn main() -> i32 effects [model, memory] {
    return infer(41)
}
"""


def timed(fn, repeats: int = 10) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    values = sorted(samples)
    return {
        "min_ms": values[0],
        "median_ms": values[len(values) // 2],
        "mean_ms": sum(values) / len(values),
        "max_ms": values[-1],
    }


def main() -> None:
    program = parse_native(SOURCE)
    validate_native(program)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "main.hf"
        output = root / "main"
        source.write_text(SOURCE, encoding="utf-8")
        cold_start = time.perf_counter_ns()
        subprocess.run(["./holyfitra", "build", str(source), "-o", str(output)], check=True, capture_output=True, text=True)
        cold_ms = (time.perf_counter_ns() - cold_start) / 1_000_000
        warm = timed(lambda: emit_llvm(program), 25)
        validate = timed(lambda: validate_native(program), 25)
        contracts = timed(lambda: KernelContract("qkv", "int4", "neon", "row_major", "proof", 4096).verify(available_memory=8192, allowed_effects=("model",)), 25)
        profile_path = root / "compiler.prof"
        cProfile.runctx("emit_llvm(program)", globals(), locals(), str(profile_path))
        profile = pstats.Stats(str(profile_path)).sort_stats("cumulative").print_stats(8)
        print(json.dumps({"cold_native_build_ms": cold_ms, "warm_emit_llvm": warm, "validate_native": validate, "kernel_contract": contracts, "profile_file": str(profile_path)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
