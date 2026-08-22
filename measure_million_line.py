#!/usr/bin/env python3
"""Measure Holy Fitra behavior on million-line corpora."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def vm_hwm_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except (FileNotFoundError, OSError, ValueError):
        pass
    return 0


def run(label: str, command: list[str], *, cwd: Path = ROOT, timeout_seconds: float = 180.0, env: dict[str, str] | None = None) -> dict[str, object]:
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    peak_hwm = 0
    timed_out = False
    while process.poll() is None:
        peak_hwm = max(peak_hwm, vm_hwm_kb(process.pid))
        if time.perf_counter() - started > timeout_seconds:
            timed_out = True
            process.kill()
            break
        time.sleep(0.01)
    stdout, stderr = process.communicate()
    peak_hwm = max(peak_hwm, vm_hwm_kb(process.pid))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "label": label,
        "command": command,
        "status": process.returncode if not timed_out else 124,
        "timeout": timed_out,
        "elapsed_ms": round(elapsed_ms, 3),
        "peak_hwm_kb": peak_hwm,
        "stdout_tail": stdout[-400:].strip(),
        "stderr_tail": stderr[-400:].strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_dir", type=Path)
    args = parser.parse_args()
    sparse = args.corpus_dir / "million_sparse.hf"
    dense = args.corpus_dir / "million_dense.hf"
    near_limit = args.corpus_dir / "near_limit_dense.hf"
    if not sparse.is_file() or not dense.is_file() or not near_limit.is_file():
        raise SystemExit("corpus directory must contain all million-line benchmark corpora")
    with tempfile.TemporaryDirectory(prefix="holyfitra-million-measure-") as temporary:
        work = Path(temporary)
        seed = work / "seed"
        v1_env = {**os.environ, "HOLYFITRA_V1_BUILD_DIR": str(work / "v1"), "PYTHONDONTWRITEBYTECODE": "1"}
        results = [
            run("seed-build", ["clang++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", str(ROOT / "holyfitra_bootstrap.cpp"), "-o", str(seed)]),
            run("seed-sparse-emit", [str(seed), str(sparse), "-o", str(work / "sparse.ll")]),
            run("seed-sparse-llvm-as", ["llvm-as", str(work / "sparse.ll"), "-o", str(work / "sparse.bc")]),
            run("seed-dense-reject", [str(seed), str(dense), "-o", str(work / "dense.ll")], timeout_seconds=30.0),
            run("python-sparse-cold", ["python3", str(ROOT / "holyfitra_compiler.py"), "check", str(sparse)], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}),
            run("python-sparse-warm", ["python3", str(ROOT / "holyfitra_compiler.py"), "check", str(sparse)], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}),
            run("python-dense-reject", ["python3", str(ROOT / "holyfitra_compiler.py"), "check", str(dense)], timeout_seconds=30.0, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}),
            run("python-near-limit-reject", ["python3", str(ROOT / "holyfitra_compiler.py"), "check", str(near_limit)], timeout_seconds=30.0, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}),
            run("v1-sparse-check-cold", ["bash", str(ROOT / "holyfitra-v1.sh"), "check", str(sparse)], env=v1_env),
            run("v1-sparse-check-warm", ["bash", str(ROOT / "holyfitra-v1.sh"), "check", str(sparse)], env=v1_env),
            run("v1-sparse-build", ["bash", str(ROOT / "holyfitra-v1.sh"), "build", str(sparse), "-o", str(work / "sparse")], env=v1_env),
            run("v1-sparse-run", [str(work / "sparse")], env=v1_env),
            run("v1-dense-reject", ["bash", str(ROOT / "holyfitra-v1.sh"), "check", str(dense)], timeout_seconds=30.0, env=v1_env),
            run("v1-near-limit-reject", ["bash", str(ROOT / "holyfitra-v1.sh"), "check", str(near_limit)], timeout_seconds=30.0, env=v1_env),
        ]
    print(json.dumps({"corpus": {"sparse_bytes": sparse.stat().st_size, "sparse_lines": sum(1 for _ in sparse.open("rb")), "dense_bytes": dense.stat().st_size, "dense_lines": sum(1 for _ in dense.open("rb")), "near_limit_bytes": near_limit.stat().st_size, "near_limit_lines": sum(1 for _ in near_limit.open("rb"))}, "results": results}, indent=2, sort_keys=True))
    failures = [item for item in results if item["timeout"] or (item["label"].endswith("reject") and item["status"] == 0) or (not item["label"].endswith("reject") and item["status"] != 0)]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
