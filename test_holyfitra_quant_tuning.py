#!/usr/bin/env python3
from __future__ import annotations

import unittest

import numpy as np

from holyfitra_quant_utils import batched_matmat, calibration_mse
from hyperc_hybrid_quant import Float16Matrix
from hyperc_quantized_transformer import QuantizedMatrix


class HolyFitraQuantTuningTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(17)
        self.weight = rng.normal(0.0, 0.2, size=(16, 12)).astype(np.float32)
        self.calibration = rng.normal(size=(24, 16)).astype(np.float32)

    def test_batched_int4_matches_rowwise_reference(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4)
        batched = batched_matmat(matrix, self.calibration)
        rowwise = np.stack([matrix.matvec(row) for row in self.calibration])
        np.testing.assert_allclose(batched, rowwise, rtol=0.0, atol=1e-6)
        self.assertGreaterEqual(calibration_mse(self.weight, self.calibration, matrix), 0.0)

    def test_batched_int8_matches_rowwise_reference(self):
        matrix = QuantizedMatrix.quantize(self.weight, 8, 16)
        batched = batched_matmat(matrix, self.calibration)
        rowwise = np.stack([matrix.matvec(row) for row in self.calibration])
        np.testing.assert_allclose(batched, rowwise, rtol=0.0, atol=1e-6)

    def test_float16_uses_cached_float32_weight(self):
        matrix = Float16Matrix(self.weight)
        self.assertTrue(matrix._float32_weight.flags.c_contiguous)
        batched = batched_matmat(matrix, self.calibration)
        expected = self.calibration @ matrix._float32_weight
        np.testing.assert_allclose(batched, expected, rtol=0.0, atol=1e-6)

    def test_int4_batched_matmul_caches_reconstruction(self):
        class SpyPacked:
            def __init__(self):
                self.calls = 0

            def reconstruct(self):
                self.calls += 1
                return np.eye(4, dtype=np.float32)

        packed = SpyPacked()
        matrix = QuantizedMatrix(packed, 4, (4, 4))
        first = matrix.matmat(np.ones((3, 4), dtype=np.float32))
        second = matrix.matmat(np.ones((3, 4), dtype=np.float32))
        self.assertEqual(packed.calls, 1)
        np.testing.assert_array_equal(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
