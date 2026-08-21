#!/usr/bin/env python3
"""Small calibration-aware AWQ-inspired weight quantizer."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hyperc_quantized_transformer import QuantizedMatrix
from holyfitra_quant_utils import calibration_mse


@dataclass
class CalibratedMatrix:
    matrix: QuantizedMatrix
    calibration_mse: float
    sidecar_fraction: float

    @property
    def storage_bytes(self) -> int:
        return self.matrix.storage_bytes

    @property
    def raw_weight_bytes(self) -> int:
        return self.matrix.raw_weight_bytes

    @property
    def compression_ratio(self) -> float:
        return self.matrix.compression_ratio

    def matvec(self, vector: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
        result = self.matrix.matvec(vector)
        if out is not None:
            out[...] = result
            return out
        return result


def calibrate_matrix(weight: np.ndarray, calibration: np.ndarray, bits: int, group_size: int, sidecar_fraction: float = 0.0) -> CalibratedMatrix:
    weight = np.asarray(weight, dtype=np.float32)
    calibration = np.asarray(calibration, dtype=np.float32)
    if weight.ndim != 2 or calibration.ndim != 2 or calibration.shape[1] != weight.shape[0]:
        raise ValueError("weight and calibration shapes are incompatible")
    if not 0.0 <= sidecar_fraction <= 1.0:
        raise ValueError("sidecar_fraction must be between 0 and 1")
    matrix = QuantizedMatrix.quantize(weight, bits, group_size)
    mse = calibration_mse(weight, calibration, matrix)
    return CalibratedMatrix(matrix, mse, sidecar_fraction)
