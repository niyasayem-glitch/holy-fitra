#!/usr/bin/env python3
"""Summarize the reproducible Holy Fitra compiler-cache profile artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def mean_ms(scenarios: dict[str, dict[str, object]], name: str) -> float:
    return float(dict(scenarios[name]["compiler_elapsed_ms"])["mean"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", type=Path, default=Path("/tmp/hf_compiler_cache_profile.json"))
    arguments = parser.parse_args()
    payload = json.loads(arguments.profile.read_text(encoding="utf-8"))
    if payload.get("schema") != "holyfitra.compiler-cache-profile/v1":
        raise SystemExit("unsupported cache profile schema")
    scenarios = {str(item["scenario"]): item for item in payload["scenarios"]}
    required = {"cold_build", "warm_disk_artifact", "comment_only_invalidation", "semantic_invalidation", "corrupt_llvm_recovery_with_artifact_hit"}
    if set(scenarios) != required:
        raise SystemExit("cache profile scenarios do not match the expected contract")
    cold = mean_ms(scenarios, "cold_build")
    warm = mean_ms(scenarios, "warm_disk_artifact")
    comment = mean_ms(scenarios, "comment_only_invalidation")
    semantic = mean_ms(scenarios, "semantic_invalidation")
    recovery = mean_ms(scenarios, "corrupt_llvm_recovery_with_artifact_hit")
    print(
        f"repeats={payload['repeats']} source_bytes={payload['source_bytes']}"
        f" cold_mean_ms={cold:.3f}"
        f" warm_mean_ms={warm:.3f}"
        f" cold_to_warm_speedup={cold / warm:.2f}x"
        f" comment_mean_ms={comment:.3f}"
        f" comment_vs_cold={comment / cold:.3f}x"
        f" semantic_mean_ms={semantic:.3f}"
        f" semantic_vs_cold={semantic / cold:.3f}x"
        f" corrupt_recovery_mean_ms={recovery:.3f}"
        f" recovery_vs_warm={recovery / warm:.2f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
