"""Measure the local HD stale-review workspace digest on a real selected workspace.

This script creates no plan, performs no provider call, writes no workspace file, and
does not run a command inside the selected project.
"""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import time

from holyfitra_agent import Workspace
from holyfitra_hd import HDCopilot


ROUNDS = 100


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: profile_hd_workspace_digest.py <workspace>")
    workspace = Workspace(Path(sys.argv[1]))
    copilot = HDCopilot(workspace)
    copilot.workspace_digest()
    samples: list[float] = []
    digest = ""
    for _ in range(ROUNDS):
        started = time.perf_counter()
        digest = copilot.workspace_digest()
        samples.append((time.perf_counter() - started) * 1000.0)
    files = workspace.files()
    print(json.dumps({
        "profile": "holyfitra-hd-workspace-digest/v1",
        "workspace": str(workspace.root),
        "eligible_files": len(files),
        "eligible_source_bytes": sum(len(workspace.read(path).encode("utf-8")) for path in files),
        "rounds": ROUNDS,
        "workspace_digest": digest,
        "latency_ms": {
            "min": round(min(samples), 4),
            "mean": round(statistics.mean(samples), 4),
            "p95": round(percentile(samples, 0.95), 4),
            "max": round(max(samples), 4),
        },
        "boundary": "Digest-only stale-review guard; no provider call, plan generation, write, shell command, Android execution, or device result.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
