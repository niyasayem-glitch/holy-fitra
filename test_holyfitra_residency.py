#!/usr/bin/env python3
from __future__ import annotations
import unittest
import numpy as np
from holyfitra_tensor_pool import SharedTensorPool
from holyfitra_residency import ResidencyTier, TieredResidencyManager


class HolyFitraResidencyTests(unittest.TestCase):
    def setUp(self):
        self.pool = SharedTensorPool(8192)
        self.manager = TieredResidencyManager(self.pool, cold_after_ns=10, pressure_start=0.6, pressure_critical=0.9)

    def test_pressure_hysteresis_does_not_evict_nominal_work(self):
        handle = self.manager.admit(np.ones((16,), dtype=np.float32), timestamp_ns=0)
        self.manager.set_hints(pressure=0.5)
        self.assertEqual(self.manager.rebalance(now_ns=100), ())
        self.assertFalse(handle._record.evicted)
        handle._record.tensor.release()

    def test_cold_unpinned_tensor_is_evicted_under_critical_pressure(self):
        handle = self.manager.admit(np.ones((16,), dtype=np.float32), timestamp_ns=0)
        self.manager.set_hints(pressure=0.95, thermal_hint="critical")
        evicted = self.manager.rebalance(now_ns=100)
        self.assertEqual(evicted, (handle.key,))
        self.assertEqual(handle.tier, ResidencyTier.EVICTED)
        with self.assertRaises(RuntimeError):
            handle.lease()
        self.assertEqual(self.pool.stats.physical_bytes, 0)

    def test_pinned_and_leased_tensors_are_preserved(self):
        pinned = self.manager.admit(np.ones((16,), dtype=np.float32), pinned=True, timestamp_ns=0)
        leased = self.manager.admit(np.zeros((16,), dtype=np.float32), timestamp_ns=0)
        with leased.lease(timestamp_ns=1) as active:
            self.manager.set_hints(pressure=1.0, thermal_hint="critical")
            evicted = self.manager.rebalance(now_ns=100)
            self.assertNotIn(pinned.key, evicted)
            self.assertNotIn(leased.key, evicted)
            np.testing.assert_array_equal(active.numpy(), np.zeros((16,), dtype=np.float32))
        pinned._record.tensor.release()
        leased._record.tensor.release()

    def test_hot_access_is_preserved_and_cold_access_is_reclaimed(self):
        hot = self.manager.admit(np.ones((16,), dtype=np.float32), timestamp_ns=0)
        cold = self.manager.admit(np.zeros((16,), dtype=np.float32), timestamp_ns=0)
        hot.lease(timestamp_ns=1).__exit__()
        hot.lease(timestamp_ns=2).__exit__()
        self.manager.set_hints(pressure=0.95)
        evicted = self.manager.rebalance(now_ns=100)
        self.assertIn(cold.key, evicted)
        self.assertNotIn(hot.key, evicted)
        hot._record.tensor.release()

    def test_invalid_hints_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.set_hints(pressure=1.1)
        with self.assertRaises(ValueError):
            self.manager.set_hints(pressure=0.5, thermal_hint="unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
