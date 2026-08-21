#!/usr/bin/env python3
from __future__ import annotations
import unittest
import numpy as np
from hyperc_nn import Tensor
from holyfitra_memory import UnifiedMemoryArena


class HolyFitraMemoryTests(unittest.TestCase):
    def test_zero_copy_view_aliases_tensor_storage(self):
        arena = UnifiedMemoryArena(4096, alignment=64)
        view = arena.allocate((8, 4), dtype=np.float32)
        array = view.numpy(writable=True)
        array.fill(3.0)
        tensor = Tensor.from_buffer(array)
        self.assertEqual(tensor.data.__array_interface__["data"][0], array.__array_interface__["data"][0])
        array[0, 0] = 9.0
        self.assertEqual(float(tensor.data[0, 0]), 9.0)
        self.assertEqual(view.offset % 64, 0)

    def test_readonly_ownership_is_enforced(self):
        arena = UnifiedMemoryArena(1024)
        view = arena.allocate((4,), readonly=True)
        with self.assertRaises(PermissionError):
            view.numpy(writable=True)
        self.assertFalse(view.numpy().flags.writeable)
        with self.assertRaises(PermissionError):
            view.alias(readonly=False)

    def test_release_coalesces_and_reuses_space(self):
        arena = UnifiedMemoryArena(1024, alignment=64)
        first = arena.allocate((64,), dtype=np.float32)
        first_offset = first.offset
        first.release()
        second = arena.allocate((64,), dtype=np.float32)
        self.assertEqual(second.offset, first_offset)
        self.assertEqual(arena.stats.live_bytes, 256)
        self.assertGreaterEqual(arena.stats.reused_bytes, 256)
        with self.assertRaises(RuntimeError):
            first.numpy()

    def test_aliases_share_data_but_release_independently(self):
        arena = UnifiedMemoryArena(2048)
        source = arena.allocate((4,), dtype=np.float32)
        alias = source.alias()
        self.assertEqual(arena.stats.live_bytes, source.nbytes)
        source.numpy(writable=True)[...] = [1, 2, 3, 4]
        np.testing.assert_array_equal(alias.numpy(), [1, 2, 3, 4])
        source.release()
        np.testing.assert_array_equal(alias.numpy(), [1, 2, 3, 4])
        alias.release()
        self.assertEqual(arena.stats.live_bytes, 0)

    def test_arena_exposes_high_water_and_capacity(self):
        arena = UnifiedMemoryArena(4096)
        a = arena.allocate((128,), dtype=np.float32)
        b = arena.allocate((128,), dtype=np.float32)
        self.assertEqual(arena.stats.live_bytes, 1024)
        self.assertGreaterEqual(arena.stats.high_water_bytes, 1024)
        self.assertEqual(arena.stats.capacity_bytes, 4096)
        a.release()
        b.release()
        self.assertEqual(arena.stats.free_bytes, 4096)


if __name__ == "__main__":
    unittest.main(verbosity=2)
