#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch
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

    def test_float16_reconstruction_cache_is_explicit_and_memory_accounted(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_dtype="f16", max_reconstruction_error=0.01)
        self.assertEqual(matrix.reconstruction_cache_dtype, "f16")
        self.assertGreater(matrix.reconstruction_cache_bytes, 0)
        self.assertEqual(matrix.reconstruction_cache_bytes * 2, matrix.raw_weight_bytes)
        self.assertLessEqual(matrix.reconstruction_cache_error, 0.01)
        self.assertLess(matrix.memory_bytes, matrix.storage_bytes + matrix.raw_weight_bytes)
        matrix.clear_reconstruction_cache()
        self.assertEqual(matrix.reconstruction_cache_bytes, 0)
        self.assertIsNone(matrix.reconstruction_cache_dtype)

    def test_float16_reconstruction_cache_requires_quality_gate(self):
        with self.assertRaises(ValueError):
            QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_dtype="f16")
        with self.assertRaises(ValueError):
            QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_dtype="f16", max_reconstruction_error=0.0)

    def test_hybrid_cache_promotes_after_threshold(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="hybrid", max_reconstruction_error=0.01, promote_after=2)
        self.assertEqual(matrix.reconstruction_cache_mode, "hybrid_cold")
        cold_bytes = matrix.reconstruction_cache_bytes
        first = matrix.matmat(self.calibration)
        self.assertEqual(matrix.reconstruction_cache_mode, "hybrid_cold")
        second = matrix.matmat(self.calibration)
        self.assertEqual(matrix.reconstruction_cache_mode, "f32")
        self.assertGreater(matrix.reconstruction_cache_bytes, cold_bytes)
        reference = QuantizedMatrix.quantize(self.weight, 4, 4).matmat(self.calibration)
        np.testing.assert_allclose(second, reference, rtol=0.0, atol=1e-6)
        self.assertLessEqual(float(np.max(np.abs(first - reference))), 0.01 * float(np.linalg.norm(self.calibration)) + 0.01)

    def test_hybrid_cache_requires_positive_promotion_threshold(self):
        with self.assertRaises(ValueError):
            QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="hybrid", max_reconstruction_error=0.01, promote_after=0)

    def test_adaptive_cache_keeps_one_shot_access_cold(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="adaptive_hybrid", max_reconstruction_error=0.01, promote_after=4)
        with patch("hyperc_quantized_transformer.time.perf_counter_ns", return_value=0):
            matrix.matmat(self.calibration)
        self.assertEqual(matrix.reconstruction_cache_mode, "adaptive_cold")
        self.assertEqual(matrix.adaptive_promotion_stats["access_count"], 1)
        self.assertFalse(matrix.adaptive_promotion_stats["promoted"])
        self.assertEqual(matrix.reconstruction_cache_bytes * 2, matrix.raw_weight_bytes)

    def test_adaptive_cache_promotes_hot_burst_and_records_frequency(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="adaptive_hybrid", max_reconstruction_error=0.01, promote_after=4, adaptive_hysteresis=2)
        with patch("hyperc_quantized_transformer.time.perf_counter_ns", side_effect=[0, 1_000_000, 2_000_000, 3_000_000]):
            for _ in range(4):
                matrix.matmat(self.calibration)
        self.assertEqual(matrix.reconstruction_cache_mode, "f32")
        self.assertEqual(matrix.adaptive_promotion_stats["access_count"], 4)
        self.assertGreater(matrix.adaptive_promotion_stats["frequency_ewma"], 0.5)
        self.assertTrue(matrix.adaptive_promotion_stats["promoted"])

    def test_adaptive_cache_rejects_invalid_policy(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4)
        with self.assertRaises(ValueError):
            matrix.configure_adaptive_hybrid_cache(max_error=0.01, alpha=1.5)

    def test_adaptive_cache_accepts_runtime_timestamp_without_clock_read(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="adaptive_hybrid", max_reconstruction_error=0.01, promote_after=3)
        with patch("hyperc_quantized_transformer.time.perf_counter_ns", side_effect=AssertionError("duplicate clock read")):
            matrix.matmat(self.calibration, access_timestamp_ns=0)
        self.assertEqual(matrix.adaptive_promotion_stats["access_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
