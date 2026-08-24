#!/usr/bin/env python3
"""Optional ctypes bridge for Holy Fitra's bounded native streamed block ABI."""
from __future__ import annotations

import ctypes
from pathlib import Path

import numpy as np


class StreamedNativeKernelError(ValueError):
    """The optional native streamed block kernel cannot be loaded or used safely."""


class StreamedNativeKernel:
    ABI = 1

    def __init__(self, library_path: str | Path):
        try:
            self._library = ctypes.CDLL(str(library_path))
        except OSError as error:
            raise StreamedNativeKernelError("native streamed kernel library cannot be loaded") from error
        self._library.hf_streamed_f32_block_abi.restype = ctypes.c_uint32
        self._library.hf_streamed_f32_block_has_neon.restype = ctypes.c_int
        self._library.hf_streamed_f32_block_matvec.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
            ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32,
        ]
        self._library.hf_streamed_f32_block_matvec.restype = ctypes.c_int
        if self._library.hf_streamed_f32_block_abi() != self.ABI:
            raise StreamedNativeKernelError("native streamed kernel ABI is unsupported")

    @property
    def has_neon(self) -> bool:
        return bool(self._library.hf_streamed_f32_block_has_neon())

    def matmul(self, inputs: np.ndarray, weights: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(inputs, dtype=np.float32)
        matrix = np.ascontiguousarray(weights, dtype=np.float32)
        if x.ndim != 2 or matrix.ndim != 2 or x.shape[1] != matrix.shape[0] or x.shape[0] <= 0 or matrix.shape[1] <= 0 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(matrix)):
            raise StreamedNativeKernelError("native streamed kernel inputs are invalid")
        output = np.empty((x.shape[0], matrix.shape[1]), dtype=np.float32)
        for row in range(x.shape[0]):
            status = self._library.hf_streamed_f32_block_matvec(
                x[row].ctypes.data_as(ctypes.POINTER(ctypes.c_float)), x.shape[1],
                matrix.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), matrix.size,
                output[row].ctypes.data_as(ctypes.POINTER(ctypes.c_float)), output.shape[1],
                matrix.shape[0], matrix.shape[1], self.ABI,
            )
            if status != 0:
                raise StreamedNativeKernelError(f"native streamed kernel rejected block with status {status}")
        return output


__all__ = ["StreamedNativeKernel", "StreamedNativeKernelError"]
