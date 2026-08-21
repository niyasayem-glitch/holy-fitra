#!/usr/bin/env python3
from __future__ import annotations
import unittest
import numpy as np
from hyperc_nn import Tensor, mse
from holyfitra_learning import Adam, clip_grad_norm, zero_grad
from holyfitra_model_dev import LoRAAdapter, ResourceBudget, ResourceBudgetError, magnitude_prune


class HolyFitraModelDevelopmentTests(unittest.TestCase):
    def test_lora_adapter_learns_residual_with_frozen_base(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=(32, 4)).astype(np.float32)
        base = np.zeros((4, 2), dtype=np.float32)
        target = x @ np.array([[1.5, -0.7], [0.3, 0.8], [-0.4, 0.2], [0.9, 0.1]], dtype=np.float32)
        adapter = LoRAAdapter(base, rank=2, alpha=2.0, seed=5)
        optimizer = Adam(adapter.parameters, learning_rate=0.05)
        initial = float(mse(adapter.forward(Tensor(x)), Tensor(target)).data.item())
        for _ in range(160):
            zero_grad(adapter.parameters)
            loss = mse(adapter.forward(Tensor(x)), Tensor(target))
            loss.backward()
            clip_grad_norm(adapter.parameters, 10.0)
            optimizer.step(adapter.parameters)
        final = float(mse(adapter.forward(Tensor(x)), Tensor(target)).data.item())
        self.assertLess(final, initial * 0.05)
        self.assertEqual(adapter.base_parameter_count, base.size + 2)
        self.assertLess(adapter.trainable_parameter_count, adapter.total_parameter_count)
        self.assertLess(adapter.trainable_ratio, 0.6)
        np.testing.assert_array_equal(adapter.base_weight, base)

    def test_manifest_and_budget_accounting(self):
        adapter = LoRAAdapter(np.ones((8, 4), dtype=np.float32), rank=2, alpha=4.0)
        manifest = adapter.enforce_budget(ResourceBudget(max_trainable_parameters=24, max_weight_bytes=512, min_density=0.5))
        self.assertEqual(manifest.trainable_parameters, 24)
        self.assertEqual(manifest.base_parameters, 36)
        self.assertEqual(manifest.total_parameters, 60)
        with self.assertRaises(ResourceBudgetError):
            adapter.enforce_budget(ResourceBudget(max_trainable_parameters=10))

    def test_pruning_is_deterministic_and_reports_actual_sparsity(self):
        values = np.array([[0.0, 1.0, -2.0], [0.5, -0.25, 3.0]], dtype=np.float32)
        mask_a, report_a = magnitude_prune(values, 0.5)
        mask_b, report_b = magnitude_prune(values, 0.5)
        np.testing.assert_array_equal(mask_a, mask_b)
        self.assertEqual(report_a, report_b)
        self.assertEqual(report_a.zeroed_parameters, 3)
        self.assertEqual(report_a.remaining_parameters, 3)

    def test_pruned_adapter_preserves_binary_mask_and_state_round_trip(self):
        adapter = LoRAAdapter(np.arange(12, dtype=np.float32).reshape(4, 3), rank=1, alpha=1.0)
        report = adapter.prune_base(0.25)
        self.assertEqual(report.zeroed_parameters, 3)
        state = adapter.state_dict()
        restored = LoRAAdapter(adapter.base_weight, base_bias=adapter.base_bias, rank=1, alpha=1.0)
        restored.load_state_dict(state)
        np.testing.assert_array_equal(restored.merged_weight(), adapter.merged_weight())


if __name__ == "__main__":
    unittest.main(verbosity=2)
