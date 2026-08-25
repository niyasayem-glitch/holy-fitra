#!/usr/bin/env python3
"""Reproducibly profile Holy Fitra's current single-file compiler cache contract.

The runner uses the maintained native compiler smoke fixture, fixed mutations,
fresh temporary projects, and direct ``build`` calls with the memory cache
cleared before each measured invocation. This measures the cache implementation
without claiming process-start, Android, or physical-device behavior.
"""
from __future__ import annotations

import argparse
import contextlib
import cProfile
import io
import json
import pstats
import statistics
import tempfile
import time
from pathlib import Path
from typing import Callable

from holyfitra_compiler import _MEMORY_COMPILE_CACHE, build


SOURCE = """\
module arithmetic
fn add(a: i32, b: i32) -> i32 {
    let c = a + b
    return c
}
fn main() -> i32 {
    return add(40, 2)
}
"""
COMMENT_ONLY_SOURCE = SOURCE + "\n// profiling-only non-semantic comment\n"
SEMANTIC_SOURCE = SOURCE.replace("add(40, 2)", "add(40, 3)")


def invoke(source_path: Path, output: Path) -> dict[str, float | bool | str]:
    """Run one build as a fresh-process cache approximation and capture its receipt."""
    _MEMORY_COMPILE_CACHE.clear()
    stream = io.StringIO()
    started_ns = time.perf_counter_ns()
    with contextlib.redirect_stdout(stream):
        result = build(source_path, output)
    wall_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    if result != 0:
        raise RuntimeError("compiler build returned a non-zero status")
    receipt = json.loads(stream.getvalue())
    if not receipt.get("ok"):
        raise RuntimeError(f"compiler build did not report success: {receipt}")
    return {
        "wall_ms": wall_ms,
        "compiler_elapsed_ms": float(receipt["elapsed_ms"]),
        "cache_hit": bool(receipt["cache_hit"]),
        "digest": str(receipt["digest"]),
    }


def scenario(
    name: str,
    repeats: int,
    setup: Callable[[Path, Path, Path], None],
    expected_cache_hit: bool,
) -> dict[str, object]:
    samples: list[dict[str, float | bool | str]] = []
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="holyfitra-cache-profile-") as temporary:
            root = Path(temporary)
            source_path = root / "main.hf"
            output = root / "build" / "program"
            source_path.write_text(SOURCE, encoding="utf-8")
            setup(root, source_path, output)
            sample = invoke(source_path, output)
            if sample["cache_hit"] is not expected_cache_hit:
                raise RuntimeError(f"{name} expected cache_hit={expected_cache_hit}, got {sample}")
            samples.append(sample)
    wall_ms = [float(sample["wall_ms"]) for sample in samples]
    compiler_elapsed_ms = [float(sample["compiler_elapsed_ms"]) for sample in samples]
    return {
        "scenario": name,
        "repeats": repeats,
        "expected_cache_hit": expected_cache_hit,
        "wall_ms": {"mean": statistics.fmean(wall_ms), "median": statistics.median(wall_ms), "min": min(wall_ms), "max": max(wall_ms)},
        "compiler_elapsed_ms": {
            "mean": statistics.fmean(compiler_elapsed_ms),
            "median": statistics.median(compiler_elapsed_ms),
            "min": min(compiler_elapsed_ms),
            "max": max(compiler_elapsed_ms),
        },
        "unique_digests": len({str(sample["digest"]) for sample in samples}),
    }


def no_setup(_: Path, __: Path, ___: Path) -> None:
    return None


def warm_artifact_setup(_: Path, source_path: Path, output: Path) -> None:
    invoke(source_path, output)


def comment_invalidation_setup(_: Path, source_path: Path, output: Path) -> None:
    baseline = invoke(source_path, output)
    source_path.write_text(COMMENT_ONLY_SOURCE, encoding="utf-8")
    if baseline["cache_hit"]:
        raise RuntimeError("fresh baseline unexpectedly hit the artifact cache")


def semantic_invalidation_setup(_: Path, source_path: Path, output: Path) -> None:
    baseline = invoke(source_path, output)
    source_path.write_text(SEMANTIC_SOURCE, encoding="utf-8")
    if baseline["cache_hit"]:
        raise RuntimeError("fresh baseline unexpectedly hit the artifact cache")


def corrupt_llvm_setup(root: Path, source_path: Path, output: Path) -> None:
    baseline = invoke(source_path, output)
    cache_path = root / ".holyfitra" / "cache" / f"{baseline['digest']}.json"
    cache_path.write_text("{broken", encoding="utf-8")


def render_profile(profile: cProfile.Profile) -> str:
    rendered = io.StringIO()
    stats = pstats.Stats(profile, stream=rendered).strip_dirs().sort_stats("cumulative")
    stats.print_stats(20)
    return rendered.getvalue()


def profile_cold_build() -> str:
    """Capture cumulative function time for one cold build without memory reuse."""
    with tempfile.TemporaryDirectory(prefix="holyfitra-cache-cprofile-") as temporary:
        root = Path(temporary)
        source_path = root / "main.hf"
        output = root / "build" / "program"
        source_path.write_text(SOURCE, encoding="utf-8")
        _MEMORY_COMPILE_CACHE.clear()
        profile = cProfile.Profile()
        with contextlib.redirect_stdout(io.StringIO()):
            result = profile.runcall(build, source_path, output)
        if result != 0:
            raise RuntimeError("cold cProfile build failed")
        return render_profile(profile)


def profile_warm_artifact() -> str:
    """Capture cumulative function time for one disk-artifact hit without memory reuse."""
    with tempfile.TemporaryDirectory(prefix="holyfitra-cache-cprofile-") as temporary:
        root = Path(temporary)
        source_path = root / "main.hf"
        output = root / "build" / "program"
        source_path.write_text(SOURCE, encoding="utf-8")
        invoke(source_path, output)
        _MEMORY_COMPILE_CACHE.clear()
        profile = cProfile.Profile()
        with contextlib.redirect_stdout(io.StringIO()):
            result = profile.runcall(build, source_path, output)
        if result != 0:
            raise RuntimeError("warm cProfile build failed")
        return render_profile(profile)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7, help="fresh temporary-project samples per scenario")
    parser.add_argument("--output", type=Path, default=Path("/tmp/hf_compiler_cache_profile.json"))
    arguments = parser.parse_args()
    if arguments.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    results = [
        scenario("cold_build", arguments.repeats, no_setup, False),
        scenario("warm_disk_artifact", arguments.repeats, warm_artifact_setup, True),
        scenario("comment_only_invalidation", arguments.repeats, comment_invalidation_setup, False),
        scenario("semantic_invalidation", arguments.repeats, semantic_invalidation_setup, False),
        scenario("corrupt_llvm_recovery_with_artifact_hit", arguments.repeats, corrupt_llvm_setup, True),
    ]
    payload = {
        "schema": "holyfitra.compiler-cache-profile/v1",
        "fixture": "maintained native compiler arithmetic smoke source",
        "source_bytes": len(SOURCE.encode("utf-8")),
        "repeats": arguments.repeats,
        "memory_cache": "cleared before every measured build to approximate a fresh CLI process",
        "boundary": "Host-only direct-library measurements. They exclude Python process startup and do not measure Android, Termux, or physical-device behavior.",
        "scenarios": results,
        "cold_build_cprofile_cumulative_top20": profile_cold_build(),
        "warm_artifact_cprofile_cumulative_top20": profile_warm_artifact(),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(arguments.output), "scenarios": [item["scenario"] for item in results]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
