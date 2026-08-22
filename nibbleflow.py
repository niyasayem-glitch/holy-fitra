#!/usr/bin/env python3
"""NibbleFlow int4 weight-only matrix-vector format and build helpers."""
from __future__ import annotations

import ctypes
import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np


TILE_OUT = 4
ABI_VERSION = 1


@dataclass(frozen=True)
class NibbleFlowLayout:
    in_dim: int
    out_dim: int
    group_size: int
    tile_out: int = TILE_OUT

    def __post_init__(self) -> None:
        if self.in_dim <= 0 or self.out_dim <= 0 or self.group_size <= 0:
            raise ValueError("dimensions and group_size must be positive")
        if self.group_size % 2:
            raise ValueError("group_size must be even for nibble packing")
        if self.tile_out != TILE_OUT:
            raise ValueError("this ABI uses four output lanes per tile")

    @property
    def groups(self) -> int:
        return math.ceil(self.in_dim / self.group_size)

    @property
    def pairs_per_group(self) -> int:
        return self.group_size // 2

    @property
    def out_tiles(self) -> int:
        return math.ceil(self.out_dim / self.tile_out)

    @property
    def packed_bytes(self) -> int:
        return self.out_tiles * self.groups * self.pairs_per_group * self.tile_out

    @property
    def scale_count(self) -> int:
        return self.out_tiles * self.groups * self.tile_out

    def packed_index(self, tile: int, group: int, pair: int, lane: int) -> int:
        return (((tile * self.groups + group) * self.pairs_per_group + pair) * self.tile_out + lane)

    def scale_index(self, tile: int, group: int, lane: int) -> int:
        return ((tile * self.groups + group) * self.tile_out + lane)

    def jsonable(self) -> dict[str, int]:
        return {"in_dim": self.in_dim, "out_dim": self.out_dim, "group_size": self.group_size, "tile_out": self.tile_out, "groups": self.groups, "pairs_per_group": self.pairs_per_group, "out_tiles": self.out_tiles, "packed_bytes": self.packed_bytes, "scale_count": self.scale_count}


@dataclass
class PackedNibbleFlow:
    layout: NibbleFlowLayout
    packed: np.ndarray
    scales: np.ndarray

    def __post_init__(self) -> None:
        self.packed = np.ascontiguousarray(self.packed, dtype=np.uint8).reshape(-1)
        self.scales = np.ascontiguousarray(self.scales, dtype=np.float32).reshape(-1)
        if self.packed.size != self.layout.packed_bytes:
            raise ValueError("packed byte count does not match layout")
        if self.scales.size != self.layout.scale_count:
            raise ValueError("scale count does not match layout")

    def reconstruct(self) -> np.ndarray:
        result = np.zeros((self.layout.out_dim, self.layout.in_dim), dtype=np.float32)
        for out_index in range(self.layout.out_dim):
            tile, lane = divmod(out_index, self.layout.tile_out)
            for group in range(self.layout.groups):
                start = group * self.layout.group_size
                for pair in range(self.layout.pairs_per_group):
                    byte = int(self.packed[self.layout.packed_index(tile, group, pair, lane)])
                    q0 = byte & 0x0F
                    q1 = (byte >> 4) & 0x0F
                    if q0 >= 8:
                        q0 -= 16
                    if q1 >= 8:
                        q1 -= 16
                    input0 = start + pair * 2
                    if input0 < self.layout.in_dim:
                        result[out_index, input0] = q0 * self.scales[self.layout.scale_index(tile, group, lane)]
                    if input0 + 1 < self.layout.in_dim:
                        result[out_index, input0 + 1] = q1 * self.scales[self.layout.scale_index(tile, group, lane)]
        return result

    def matvec_reference(self, vector: np.ndarray, bias: np.ndarray | None = None) -> np.ndarray:
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != self.layout.in_dim:
            raise ValueError("vector dimension mismatch")
        result = np.zeros(self.layout.out_dim, dtype=np.float32)
        for out_index in range(self.layout.out_dim):
            tile, lane = divmod(out_index, self.layout.tile_out)
            total = 0.0
            for group in range(self.layout.groups):
                group_sum = 0.0
                start = group * self.layout.group_size
                scale = float(self.scales[self.layout.scale_index(tile, group, lane)])
                for pair in range(self.layout.pairs_per_group):
                    byte = int(self.packed[self.layout.packed_index(tile, group, pair, lane)])
                    q0 = byte & 0x0F
                    q1 = (byte >> 4) & 0x0F
                    if q0 >= 8:
                        q0 -= 16
                    if q1 >= 8:
                        q1 -= 16
                    input0 = start + pair * 2
                    if input0 < self.layout.in_dim:
                        group_sum += float(vector[input0]) * q0
                    if input0 + 1 < self.layout.in_dim:
                        group_sum += float(vector[input0 + 1]) * q1
                total += group_sum * scale
            result[out_index] = total + (float(bias[out_index]) if bias is not None else 0.0)
        return result

    def to_manifest(self, model: str, kernel: str = "nibbleflow.int4.f32") -> dict[str, object]:
        return {"schema": "holy-fitra.nibbleflow/v1", "abi_version": ABI_VERSION, "model": model, "kernel": kernel, "layout": self.layout.jsonable(), "packed_dtype": "u8", "scale_dtype": "f32", "signed_quant": True, "nibble_order": "low_input_even_high_input_odd", "tile_order": "output_tile_group_pair_lane"}


def quantize_weight(weight: np.ndarray, group_size: int = 32) -> PackedNibbleFlow:
    weight = np.asarray(weight, dtype=np.float32)
    if weight.ndim != 2:
        raise ValueError("weight must be rank-2 [out, in]")
    layout = NibbleFlowLayout(weight.shape[1], weight.shape[0], group_size)
    packed = np.zeros(layout.packed_bytes, dtype=np.uint8)
    scales = np.zeros(layout.scale_count, dtype=np.float32)
    for out_index in range(layout.out_dim):
        tile, lane = divmod(out_index, layout.tile_out)
        for group in range(layout.groups):
            start = group * layout.group_size
            stop = min(start + layout.group_size, layout.in_dim)
            values = weight[out_index, start:stop]
            max_abs = float(np.max(np.abs(values))) if values.size else 0.0
            scale = max_abs / 7.0 if max_abs > 0 else 1.0
            scales[layout.scale_index(tile, group, lane)] = scale
            quantized = np.clip(np.rint(values / scale), -8, 7).astype(np.int8) if values.size else np.zeros(0, dtype=np.int8)
            for pair in range(layout.pairs_per_group):
                input0 = pair * 2
                q0 = int(quantized[input0]) if input0 < quantized.size else 0
                q1 = int(quantized[input0 + 1]) if input0 + 1 < quantized.size else 0
                packed[layout.packed_index(tile, group, pair, lane)] = (q0 & 0x0F) | ((q1 & 0x0F) << 4)
    return PackedNibbleFlow(layout, packed, scales)


def build_shared_library(source_dir: Path, output: Path) -> dict[str, object]:
    source_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    source = source_dir / "nibbleflow_kernel.c"
    compiler = os.environ.get("HOLYFITRA_CC") or os.environ.get("CC") or shutil.which("clang")
    if not compiler:
        return {"success": False, "command": "", "stderr": "clang is required; on Termux run: pkg install clang", "library": str(output), "bytes": None}
    command = [compiler, "-O3", "-shared", "-fPIC", "-fno-math-errno", str(source), "-o", str(output)]
    completed = subprocess.run(command, capture_output=True, text=True)
    return {"success": completed.returncode == 0, "command": " ".join(command), "stderr": completed.stderr[-2000:], "library": str(output), "bytes": output.stat().st_size if output.exists() else None}


def load_native(path: Path):
    library = ctypes.CDLL(str(path.resolve()))
    function = library.nibbleflow_int4_f32
    function.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
    function.restype = None
    return function


def run_native(function, packed: PackedNibbleFlow, vector: np.ndarray, bias: np.ndarray | None = None) -> np.ndarray:
    vector = np.ascontiguousarray(vector, dtype=np.float32).reshape(-1)
    output = np.zeros(packed.layout.out_dim, dtype=np.float32)
    bias_array = np.ascontiguousarray(bias if bias is not None else np.zeros(packed.layout.out_dim), dtype=np.float32)
    function(vector.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), packed.packed.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)), packed.scales.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), bias_array.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), packed.layout.in_dim, packed.layout.out_dim, packed.layout.group_size)
    return output


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    packed = quantize_weight(rng.normal(size=(7, 19)).astype(np.float32), group_size=6)
    print(json.dumps(packed.to_manifest("demo"), indent=2, sort_keys=True))
