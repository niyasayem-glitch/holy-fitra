#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import json
import subprocess
from pathlib import Path

import numpy as np

from nibbleflow import NibbleFlowLayout, build_shared_library, load_native, quantize_weight, run_native


def compile_object(source: Path, output: Path) -> dict[str, object]:
    command = ["clang", "--target=aarch64-linux-android21", "-O3", "-ffreestanding", "-nostdinc", "-isystem", "/usr/lib/llvm-18/lib/clang/18/include", "-c", str(source), "-o", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    return {"success": result.returncode == 0, "command": " ".join(command), "stderr": result.stderr[-1000:], "bytes": output.stat().st_size if output.exists() else None}


def main() -> int:
    root = Path(__file__).parent
    build = root / "nibbleflow-build"
    build.mkdir(exist_ok=True)
    shared = build / "libnibbleflow.so"
    (build / "nibbleflow_kernel.c").write_text((root / "nibbleflow_kernel.c").read_text())
    build_result = build_shared_library(build, shared)
    if not build_result["success"]:
        print(json.dumps({"build": build_result}, indent=2, sort_keys=True))
        return 1
    native = load_native(shared)
    abi = ctypes.CDLL(str(shared.resolve())).nibbleflow_abi_version
    abi.restype = ctypes.c_int32
    rng = np.random.default_rng(123)
    cases: list[dict[str, object]] = []
    all_pass = True
    for out_dim, in_dim, group_size in ((1, 1, 2), (3, 5, 2), (7, 19, 6), (8, 32, 8), (11, 37, 10), (17, 65, 16)):
        weight = rng.normal(0, 0.7, size=(out_dim, in_dim)).astype(np.float32)
        vector = rng.normal(size=in_dim).astype(np.float32)
        bias = rng.normal(0, 0.1, size=out_dim).astype(np.float32)
        packed = quantize_weight(weight, group_size)
        reference = packed.matvec_reference(vector, bias)
        native_output = run_native(native, packed, vector, bias)
        error = float(np.max(np.abs(reference - native_output)))
        reconstruction_error = float(np.max(np.abs(weight - packed.reconstruct())))
        passed = error <= 1e-6
        all_pass = all_pass and passed
        cases.append({"shape": [out_dim, in_dim], "group_size": group_size, "packed_bytes": int(packed.packed.nbytes), "scale_count": int(packed.scales.size), "native_max_abs_error": error, "reconstruction_max_abs_error": reconstruction_error, "pass": passed})
    object_result = compile_object(root / "nibbleflow_kernel.c", build / "nibbleflow_kernel.aarch64.o")
    result = {"abi_version": int(abi()), "native_build": build_result, "aarch64_object": object_result, "layout_example": NibbleFlowLayout(65, 17, 16).jsonable(), "cases": cases, "all_numerical_cases_pass": all_pass, "host_arch": __import__("platform").machine(), "device_claim": "No physical Android execution performed; AArch64 object emission is not device validation."}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all_pass and object_result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
