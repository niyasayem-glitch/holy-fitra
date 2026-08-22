#!/usr/bin/env python3
from __future__ import annotations

import unittest
import numpy as np

from hyperc_android_transformer import AndroidBuffers


class AndroidBufferHardeningTests(unittest.TestCase):
    def test_dimensions_are_strict_and_bounded(self):
        with self.assertRaises(ValueError):
            AndroidBuffers(True, 1, 1, 1)
        with self.assertRaises(ValueError):
            AndroidBuffers(1_000_001, 1, 1, 1)

    def test_append_is_shape_and_finite_safe(self):
        buffers = AndroidBuffers(2, 2, 3, 6)
        with self.assertRaises(ValueError):
            buffers.append(np.zeros((2, 2), dtype=np.float32), np.zeros((2, 3), dtype=np.float32))
        with self.assertRaises(ValueError):
            buffers.append(np.full((2, 3), np.nan, dtype=np.float32), np.zeros((2, 3), dtype=np.float32))
        buffers.append(np.ones((2, 3), dtype=np.float32), np.zeros((2, 3), dtype=np.float32))
        buffers.append(np.ones((2, 3), dtype=np.float32), np.zeros((2, 3), dtype=np.float32))
        with self.assertRaises(ValueError):
            buffers.append(np.ones((2, 3), dtype=np.float32), np.zeros((2, 3), dtype=np.float32))


if __name__ == "__main__":
    unittest.main(verbosity=2)
