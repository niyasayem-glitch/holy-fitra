#!/usr/bin/env python3
"""Adversarial compiler stress pass for the Holy Fitra host checkout."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import holyfitra_compiler as compiler

ROOT = Path(__file__).resolve().parent
DRIVER = ROOT / "holyfitra-v1.sh"


def expect_reject(label: str, source: str) -> tuple[str, str]:
    try:
        compiler.validate_native(compiler.parse_native(source))
    except Exception as exc:  # diagnostic taxonomy is checked separately by the compiler tests
        return label, f"rejected:{type(exc).__name__}"
    return label, "ACCEPTED"


def run_driver(label: str, source: str, expected_nonzero: bool = True) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="holyfitra-compiler-stress-") as directory:
        path = Path(directory) / f"{label}.hf"
        path.write_text(source, encoding="utf-8")
        try:
            completed = subprocess.run(
                ["timeout", "5", str(DRIVER), "check", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return label, f"runner-error:{exc}"
        state = "rejected" if completed.returncode != 0 else "accepted"
        if expected_nonzero and completed.returncode == 124:
            state = "TIMEOUT"
        return label, f"{state}:status={completed.returncode}"


def artifact_tamper_probe() -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="holyfitra-artifact-stress-") as directory:
        root = Path(directory)
        source = root / "artifact.hf"
        output = root / "artifact"
        source.write_text("module artifact\nfn main() -> i32 { return 0 }\n", encoding="utf-8")
        compiler._MEMORY_COMPILE_CACHE.clear()
        compiler.build(source, output)
        original = output.read_bytes()
        cache_dir = root / ".holyfitra" / "cache"
        artifacts = list(cache_dir.glob("*.native"))
        if len(artifacts) != 1:
            return "artifact-tamper", "MISSING_ARTIFACT"
        artifacts[0].write_bytes(b"tampered")
        compiler.build(source, output)
        return "artifact-tamper", "reused" if output.read_bytes() == b"tampered" else ("repaired" if output.read_bytes() == original else "UNEXPECTED_OUTPUT")


def cache_tamper_probe() -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="holyfitra-cache-stress-") as directory:
        root = Path(directory)
        source = root / "cache.hf"
        cache = root / "cache"
        source.write_text("module cache\nfn main() -> i32 { return 0 }\n", encoding="utf-8")
        compiler._MEMORY_COMPILE_CACHE.clear()
        _, original, digest = compiler.compile_native_file(source, cache_dir=cache)
        cache_path = cache / f"{digest}.json"
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["llvm"] = "; tampered\n"
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        compiler._MEMORY_COMPILE_CACHE.clear()
        _, repaired, _ = compiler.compile_native_file(source, cache_dir=cache)
        return "cache-tamper", "repaired" if repaired == original else "FAILED_REPAIR"


def main() -> int:
    deep = "module deep\nfn main() -> i32 { return " + "(" * 1200 + "1" + ")" * 1200 + " }\n"
    huge_array = "module huge\nfn main(a: [999999999]i32) -> i32 { return 0 }\n"
    malformed = "module malformed\nfn main() -> i32 { return 0 nonsense }\n"
    duplicate = "module duplicate\nfn main(x: i32, x: i32) -> i32 { return x }\n"
    unreachable = "module unreachable\nfn main() -> i32 { return 0 let bad: bool = 1 }\n"
    cases = [
        expect_reject("deep-python", deep),
        expect_reject("huge-array-python", huge_array),
        expect_reject("malformed-python", malformed),
        expect_reject("duplicate-python", duplicate),
        expect_reject("unreachable-python", unreachable),
        run_driver("deep-native", deep),
        run_driver("huge-array-native", huge_array),
        run_driver("malformed-native", malformed),
        run_driver("duplicate-native", duplicate),
        run_driver("unreachable-native", unreachable),
        cache_tamper_probe(),
        artifact_tamper_probe(),
    ]
    failures = []
    for label, result in cases:
        print(f"{label}: {result}")
        if result == "ACCEPTED" or result.endswith("FAILED_REPAIR") or result.endswith("TIMEOUT"):
            failures.append((label, result))
    if failures:
        print("confirmed_or_suspect_failures:")
        for label, result in failures:
            print(f"  {label}: {result}")
        return 1
    print(f"compiler_stress_cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
