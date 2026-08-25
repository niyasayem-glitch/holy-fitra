#!/usr/bin/env python3
"""Summarize the recorded bounded Holy Fitra cross-language comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def mean(section: dict[str, object], name: str) -> float:
    return float(dict(section[name])["mean"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", nargs="?", type=Path, default=Path("/tmp/hf_language_comparison.json"))
    arguments = parser.parse_args()
    payload = json.loads(arguments.comparison.read_text(encoding="utf-8"))
    if payload.get("schema") != "holyfitra.language-comparison/v1":
        raise SystemExit("unsupported language comparison schema")
    runtime = dict(payload["runtime_ms"])
    build = dict(payload["cold_build_ms"])
    c_runtime = mean(runtime, "c_clang")
    c_build = mean(build, "c_clang")
    print(
        f"repeats={payload['repeats']} iterations={payload['iterations']} expected_result={payload['expected_result']}"
        f" c_runtime_mean_ms={c_runtime:.3f}"
        f" cpp_runtime_mean_ms={mean(runtime, 'cpp_clang'):.3f}"
        f" cpp_vs_c={mean(runtime, 'cpp_clang') / c_runtime:.3f}x"
        f" node_runtime_mean_ms={mean(runtime, 'node_js'):.3f}"
        f" node_vs_c={mean(runtime, 'node_js') / c_runtime:.3f}x"
        f" python_runtime_mean_ms={mean(runtime, 'python_cpython'):.3f}"
        f" python_vs_c={mean(runtime, 'python_cpython') / c_runtime:.3f}x"
        f" c_cold_build_mean_ms={c_build:.3f}"
        f" cpp_cold_build_mean_ms={mean(build, 'cpp_clang'):.3f}"
        f" cpp_build_vs_c={mean(build, 'cpp_clang') / c_build:.3f}x"
        f" hf_cold_build_mean_ms={mean(build, 'holy_fitra'):.3f}"
        f" hf_build_vs_c={mean(build, 'holy_fitra') / c_build:.3f}x"
        f" hf_runtime_ranked=no"
        f" exclusions={','.join(sorted(dict(payload['exclusions']))) or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
