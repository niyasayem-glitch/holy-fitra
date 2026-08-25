#!/usr/bin/env python3
"""Summarize a recorded HF dynamic-input comparison result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", nargs="?", type=Path, default=Path("/tmp/hf_dynamic_input_comparison.json"))
    arguments = parser.parse_args()
    payload = json.loads(arguments.comparison.read_text(encoding="utf-8"))
    if payload.get("schema") != "holyfitra.dynamic-input-comparison/v1":
        raise SystemExit("unsupported dynamic-input comparison schema")
    timings = dict(payload["wall_ms"])
    c_mean = float(dict(timings["c_clang"])["mean"])
    hf_mean = float(dict(timings["holy_fitra"])["mean"])
    print(
        f"repeats={payload['repeats']} iterations={payload['iterations']} expected_result_u32={payload['expected_result_u32']}"
        f" c_wall_mean_ms={c_mean:.3f}"
        f" hf_wall_mean_ms={hf_mean:.3f}"
        f" hf_vs_c={hf_mean / c_mean:.3f}x"
        f" cpp_wall_mean_ms={float(dict(timings['cpp_clang'])['mean']):.3f}"
        f" cpp_vs_c={float(dict(timings['cpp_clang'])['mean']) / c_mean:.3f}x"
        f" node_wall_mean_ms={float(dict(timings['node_js'])['mean']):.3f}"
        f" node_vs_c={float(dict(timings['node_js'])['mean']) / c_mean:.3f}x"
        f" python_wall_mean_ms={float(dict(timings['python_cpython'])['mean']):.3f}"
        f" python_vs_c={float(dict(timings['python_cpython'])['mean']) / c_mean:.3f}x"
        " hf_result_verification=exit_code_modulo_256"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
