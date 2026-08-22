from __future__ import annotations

import unittest

import numpy as np

from hyperc_nn import Dense, Tensor, mse


class HypercNNTests(unittest.TestCase):
    def test_tensor_rejects_empty_and_nonfinite_data(self):
        with self.assertRaises(ValueError):
            Tensor([])
        with self.assertRaises(ValueError):
            Tensor([[np.nan]])
        with self.assertRaises(ValueError):
            Tensor([[np.inf]])

    def test_matmul_and_mse_reject_shape_mismatch(self):
        with self.assertRaises(ValueError):
            Tensor(np.zeros((2, 3), dtype=np.float32)) @ Tensor(np.zeros((2, 2), dtype=np.float32))
        with self.assertRaises(ValueError):
            mse(Tensor(np.zeros((2, 1), dtype=np.float32)), Tensor(np.zeros((2, 2), dtype=np.float32)))

    def test_backward_rejects_wrong_shape_and_nonfinite_gradient(self):
        value = Tensor(np.ones((2, 2), dtype=np.float32), requires_grad=True)
        with self.assertRaises(ValueError):
            value.backward(np.ones((2, 1), dtype=np.float32))
        with self.assertRaises(ValueError):
            value.backward(np.full((2, 2), np.nan, dtype=np.float32))

    def test_dense_rejects_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            Dense(0, 2)
        with self.assertRaises(ValueError):
            Dense(2, 0)
        with self.assertRaises(ValueError):
            Dense(True, 2)


if __name__ == "__main__":
    unittest.main()
