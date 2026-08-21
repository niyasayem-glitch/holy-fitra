#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path

import numpy as np

from holy_fitra_ragged_attention import pack_sequences, ragged_attention_reference

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "holy_fitra_ragged_build"
BUILD.mkdir(exist_ok=True)


def build_host() -> Path:
    lib = BUILD / "libragged.so"
    subprocess.run(["clang", "-O2", "-fPIC", "-shared", "holy_fitra_ragged_kernel.c", "-o", str(lib), "-lm"], cwd=ROOT, check=True)
    return lib


def run_native(lib_path: Path, batch, symbol: str) -> np.ndarray:
    lib = ctypes.CDLL(str(lib_path))
    class Batch(ctypes.Structure):
        _fields_ = [("q", ctypes.POINTER(ctypes.c_float)), ("k", ctypes.POINTER(ctypes.c_float)), ("v", ctypes.POINTER(ctypes.c_float)), ("output", ctypes.POINTER(ctypes.c_float)), ("offsets", ctypes.POINTER(ctypes.c_int32)), ("sequence_count", ctypes.c_int32), ("d_model", ctypes.c_int32)]
    q = np.ascontiguousarray(batch.q, dtype=np.float32)
    k = np.ascontiguousarray(batch.k, dtype=np.float32)
    v = np.ascontiguousarray(batch.v, dtype=np.float32)
    out = np.zeros_like(q)
    offsets = np.ascontiguousarray(batch.offsets, dtype=np.int32)
    native_batch = Batch(q.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), k.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), offsets.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), batch.sequence_count, batch.d_model)
    fn = getattr(lib, symbol)
    fn.argtypes = [ctypes.POINTER(Batch)]
    fn.restype = None
    fn(ctypes.byref(native_batch))
    return out


def emit_objects() -> dict[str, str]:
    outputs = {}
    for name, extra in [("neon", ["-target", "aarch64-linux-android21", "-march=armv8.2-a"]), ("sve", ["-target", "aarch64-linux-android21", "-march=armv8.2-a+sve"])]:
        obj = BUILD / f"holy_fitra_ragged_{name}.o"
        result = subprocess.run(["clang", "-O2", "-ffreestanding", "-c", "holy_fitra_ragged_kernel.c", "-o", str(obj), *extra], cwd=ROOT, text=True, capture_output=True)
        outputs[name] = "ok" if result.returncode == 0 else result.stderr.strip().splitlines()[-1]
    return outputs


def main() -> int:
    rng = np.random.default_rng(101)
    rows = []
    for length in [1, 2, 5, 8, 13, 17]:
        rows.append(tuple(rng.standard_normal((length, 12)).astype(np.float32) for _ in range(3)))
    batch = pack_sequences(rows)
    reference = ragged_attention_reference(batch)
    lib = build_host()
    scalar = run_native(lib, batch, "holy_fitra_ragged_attention_scalar")
    neon_fallback = run_native(lib, batch, "holy_fitra_ragged_attention_neon")
    print({"tokens": batch.total_tokens, "sequences": batch.sequence_count, "offsets": batch.offsets.tolist(), "scalar_max_error": float(np.max(np.abs(reference - scalar))), "neon_entry_max_error": float(np.max(np.abs(reference - neon_fallback))), "objects": emit_objects()})
    return 0 if np.max(np.abs(reference - scalar)) < 2e-5 and np.max(np.abs(reference - neon_fallback)) < 2e-5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
