#!/usr/bin/env python3
from __future__ import annotations
import unittest
import numpy as np
from holyfitra_tensor_pool import SharedTensorPool


class HolyFitraTensorPoolTests(unittest.TestCase):
    def test_identical_tensors_share_physical_storage(self):
        pool = SharedTensorPool(4096)
        values = np.arange(16, dtype=np.float32).reshape(4, 4)
        first = pool.intern(values)
        second = pool.intern(values.copy())
        self.assertEqual(first.key, second.key)
        self.assertEqual(pool.stats.entries, 1)
        self.assertEqual(pool.stats.handles, 2)
        self.assertEqual(pool.stats.physical_bytes, values.nbytes)
        self.assertEqual(pool.stats.logical_bytes, values.nbytes * 2)
        self.assertEqual(pool.stats.deduplicated_bytes, values.nbytes)
        np.testing.assert_array_equal(first.numpy(), second.numpy())
        first.release()
        self.assertEqual(pool.stats.entries, 1)
        second.release()
        self.assertEqual(pool.stats.entries, 0)
        self.assertEqual(pool.arena.stats.live_bytes, 0)

    def test_training_materialization_isolated_from_inference(self):
        pool = SharedTensorPool(4096)
        values = np.ones((8,), dtype=np.float32)
        shared = pool.intern(values)
        train_copy = shared.materialize_for_training()
        train_copy[0] = 99.0
        self.assertEqual(float(shared.numpy()[0]), 1.0)
        self.assertEqual(float(train_copy[0]), 99.0)
        shared.release()

    def test_shared_inference_view_is_read_only(self):
        pool = SharedTensorPool(4096)
        shared = pool.intern(np.ones((4,), dtype=np.float32))
        with self.assertRaises(ValueError):
            shared.numpy()[0] = 2.0
        shared.release()

    def test_explicit_key_collision_is_rejected(self):
        pool = SharedTensorPool(4096)
        first = pool.intern(np.zeros((4,), dtype=np.float32), key="same")
        with self.assertRaises(ValueError):
            pool.intern(np.ones((4,), dtype=np.float32), key="same")
        first.release()

    def test_pool_reuses_arena_after_all_handles_release(self):
        pool = SharedTensorPool(4096)
        first = pool.intern(np.ones((16,), dtype=np.float32))
        offset = first._view.offset
        first.release()
        second = pool.intern(np.ones((16,), dtype=np.float32))
        self.assertEqual(second._view.offset, offset)
        self.assertGreaterEqual(pool.arena.stats.reused_bytes, second.nbytes)
        second.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
