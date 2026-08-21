#!/usr/bin/env python3
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import numpy as np
from hyperc_quantized_transformer import QuantizedMatrix
from holyfitra_learning import Adam, ReplayBuffer, TrainableMLP, load_checkpoint, save_checkpoint
from hyperc_rl import ThresholdPolicyGradient


class HolyFitraRLTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(4040)
        self.weight = rng.normal(0.0, 0.2, size=(16, 12)).astype(np.float32)
        self.batch = rng.normal(size=(24, 16)).astype(np.float32)

    def test_policy_gradient_updates_and_bounds_actions(self):
        controller = ThresholdPolicyGradient(min_threshold=2, max_threshold=6, min_bonus=0, max_bonus=4, exploration=0.0, seed=1)
        stats = {"frequency_ewma": 0.8, "hot_streak": 4, "promoted": False, "cache_bytes": 24, "raw_weight_bytes": 48}
        before = controller.weights.copy()
        decision = controller.decide(stats, 1024, current_threshold=4, current_bonus=2)
        advantage = controller.update(2.0)
        self.assertTrue(np.all(np.isfinite(controller.weights)))
        self.assertFalse(np.array_equal(before, controller.weights))
        self.assertTrue(2 <= decision["promote_after"] <= 6)
        self.assertTrue(0 <= decision["large_batch_bonus"] <= 4)
        self.assertTrue(np.isfinite(advantage))

    def test_reward_penalizes_memory_and_rejects_quality_violation(self):
        reward = ThresholdPolicyGradient.reward(latency_ms=2.0, cache_bytes=50, raw_weight_bytes=100, quality_error=0.01, quality_limit=0.1)
        self.assertAlmostEqual(reward, -2.25)
        bad = ThresholdPolicyGradient.reward(latency_ms=0.1, cache_bytes=10, raw_weight_bytes=100, quality_error=0.2, quality_limit=0.1)
        self.assertEqual(bad, -10.0)
        with self.assertRaises(ValueError):
            ThresholdPolicyGradient.reward(latency_ms=-1.0, cache_bytes=1, raw_weight_bytes=1)

    def test_controller_tunes_live_adaptive_cache_with_safe_bounds(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4, reconstruction_mode="adaptive_hybrid", max_reconstruction_error=0.01, promote_after=4, adaptive_large_batch_bonus=2)
        controller = ThresholdPolicyGradient(min_threshold=1, max_threshold=8, min_bonus=0, max_bonus=4, exploration=0.0, seed=2)
        stats = matrix.adaptive_promotion_stats | {"cache_bytes": matrix.reconstruction_cache_bytes, "raw_weight_bytes": matrix.raw_weight_bytes}
        decision = controller.decide(stats, self.batch.shape[0], current_threshold=4, current_bonus=2)
        applied = matrix.set_adaptive_policy(promote_after=decision["promote_after"], large_batch_bonus=decision["large_batch_bonus"])
        self.assertEqual(applied, {"promote_after": decision["promote_after"], "large_batch_bonus": decision["large_batch_bonus"]})
        self.assertTrue(1 <= matrix.adaptive_promotion_stats["threshold"] <= 8)
        matrix.matmat(self.batch, access_timestamp_ns=0)
        self.assertIn(matrix.reconstruction_cache_mode, {"adaptive_cold", "f32"})

    def test_policy_controller_checkpoint_round_trip(self):
        model = TrainableMLP(2, 4, 1, seed=8)
        optimizer = Adam(model.parameters)
        replay = ReplayBuffer(4, seed=8)
        controller = ThresholdPolicyGradient(seed=8, exploration=0.0)
        stats = {"frequency_ewma": 0.7, "hot_streak": 3, "promoted": False, "cache_bytes": 10, "raw_weight_bytes": 20}
        controller.decide(stats, 256, current_threshold=4, current_bonus=2)
        controller.update(1.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.npz"
            save_checkpoint(path, model, optimizer, replay=replay, threshold_controller=controller)
            restored_model = TrainableMLP(2, 4, 1, seed=99)
            restored_optimizer = Adam(restored_model.parameters)
            restored_replay = ReplayBuffer(4, seed=8)
            restored_controller = ThresholdPolicyGradient(seed=99, exploration=0.0)
            manifest = load_checkpoint(path, restored_model, restored_optimizer, replay=restored_replay, threshold_controller=restored_controller)
            self.assertEqual(restored_controller.update_count, controller.update_count)
            np.testing.assert_array_equal(restored_controller.weights, controller.weights)
            self.assertIsNotNone(manifest["threshold_controller"])

    def test_policy_rejects_unsafe_action_bounds(self):
        matrix = QuantizedMatrix.quantize(self.weight, 4, 4)
        with self.assertRaises(ValueError):
            matrix.set_adaptive_policy(promote_after=100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
