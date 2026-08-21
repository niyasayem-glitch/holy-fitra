#!/usr/bin/env python3
"""Shared allocation-aware calibration helpers for Holy Fitra quantization."""
from __future__ import annotations

import numpy as np


def batched_matmat(candidate, calibration: np.ndarray) -> np.ndarray:
    calibration = np.ascontiguousarray(calibration, dtype=np.float32)
    matmat = getattr(candidate, "matmat", None)
    if matmat is not None:
        return np.asarray(matmat(calibration), dtype=np.float32)
    shape = getattr(candidate, "_raw_shape", None)
    if shape is None:
        raise TypeError("candidate must provide matmat or _raw_shape")
    output = np.empty((calibration.shape[0], int(shape[1])), dtype=np.float32)
    for index, row in enumerate(calibration):
        output[index] = candidate.matvec(row)
    return output


def calibration_mse(weight: np.ndarray, calibration: np.ndarray, candidate) -> float:
    weight = np.asarray(weight, dtype=np.float32)
    calibration = np.ascontiguousarray(calibration, dtype=np.float32)
    reference = calibration @ weight
    predicted = batched_matmat(candidate, calibration)
    return float(np.mean((reference - predicted) ** 2))
