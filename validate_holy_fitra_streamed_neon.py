#!/usr/bin/env python3
"""Validate portable streamed-block math and Android ARM64 NEON code generation."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from holyfitra_streamed_native import StreamedNativeKernel


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def main() -> int:
    root = Path(__file__).parent
    clang = shutil.which("clang")
    if clang is None:
        print(json.dumps({"success": False, "reason": "clang is required"}, sort_keys=True))
        return 1
    with tempfile.TemporaryDirectory(prefix="holyfitra-streamed-neon-") as directory:
        build = Path(directory)
        shared = build / "libholyfitra_streamed_native.so"
        shared_result = _run([clang, "-shared", "-fPIC", "-O2", "-I", str(root), str(root / "holy_fitra_streamed_neon.c"), "-lm", "-o", str(shared)])
        if shared_result.returncode != 0:
            print(json.dumps({"success": False, "host_build_stderr": shared_result.stderr[-1000:]}, sort_keys=True))
            return 1
        native = StreamedNativeKernel(shared)
        rng = np.random.default_rng(6401)
        cases: list[dict[str, object]] = []
        numerical_success = True
        for batch, rows, columns in ((1, 1, 1), (2, 3, 5), (3, 19, 7), (2, 64, 16), (1, 128, 17)):
            inputs = rng.normal(0.0, 0.4, size=(batch, rows)).astype(np.float32)
            weights = rng.normal(0.0, 0.3, size=(rows, columns)).astype(np.float32)
            expected = inputs @ weights
            actual = native.matmul(inputs, weights)
            error = float(np.max(np.abs(expected - actual)))
            passed = bool(np.allclose(expected, actual, rtol=1e-6, atol=1e-6))
            numerical_success = numerical_success and passed
            cases.append({"shape": [batch, rows, columns], "max_abs_error": error, "pass": passed})
        cross_object = build / "holy_fitra_streamed_neon.android-arm64.o"
        assembly = build / "holy_fitra_streamed_neon.android-arm64.s"
        cross_flags = ["--target=aarch64-linux-android21", "-ffreestanding", "-DHOLY_FITRA_FREESTANDING=1", "-O3", "-I", str(root)]
        object_result = _run([clang, *cross_flags, "-c", str(root / "holy_fitra_streamed_neon.c"), "-o", str(cross_object)])
        assembly_result = _run([clang, *cross_flags, "-S", str(root / "holy_fitra_streamed_neon.c"), "-o", str(assembly)])
        header = _run(["readelf", "-h", str(cross_object)]) if object_result.returncode == 0 else None
        assembly_text = assembly.read_text() if assembly_result.returncode == 0 else ""
        aarch64_object = bool(header and "AArch64" in header.stdout)
        neon_instructions = all(instruction in assembly_text for instruction in ("fmla", "ldr\tq", "str\tq"))
        result = {
            "host_arch": platform.machine(),
            "native_backend": "native-neon" if native.has_neon else "native-scalar",
            "cases": cases,
            "all_numerical_cases_pass": numerical_success,
            "aarch64_object": {"success": object_result.returncode == 0 and aarch64_object, "stderr": object_result.stderr[-1000:]},
            "aarch64_neon_assembly": {"success": assembly_result.returncode == 0 and neon_instructions, "stderr": assembly_result.stderr[-1000:]},
            "device_claim": "No physical Android execution performed; host equivalence and AArch64 NEON object/assembly emission are not device performance or runtime evidence.",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if numerical_success and result["aarch64_object"]["success"] and result["aarch64_neon_assembly"]["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
