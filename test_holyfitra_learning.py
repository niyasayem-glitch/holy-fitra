#!/usr/bin/env python3
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import numpy as np
from hyperc_nn import Tensor
from holyfitra_learning import Adam, ReplayBuffer, TrainableMLP, TrainingConfig, evaluate_mse, load_checkpoint, train_supervised


class HolyFitraLearningTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2026)
        self.x = rng.normal(size=(96, 2)).astype(np.float32)
        self.y = (2.0 * self.x[:, :1] - 1.5 * self.x[:, 1:2] + 0.25).astype(np.float32)

    def test_mlp_actually_learns_regression(self):
        model = TrainableMLP(2, 12, 1, seed=4)
        before = evaluate_mse(model, self.x, self.y)
        history = train_supervised(model, self.x, self.y, config=TrainingConfig(epochs=80, batch_size=16, seed=9))
        self.assertLess(history.final_loss, before * 0.05)
        self.assertLess(evaluate_mse(model, self.x, self.y), before * 0.05)
        self.assertEqual(history.optimizer_steps, 80 * 6)
        self.assertTrue(np.all(np.isfinite(model.predict(self.x))))

    def test_replay_buffer_is_bounded_and_reloads(self):
        replay = ReplayBuffer(8, seed=3)
        replay.add_batch(self.x, self.y)
        self.assertEqual(len(replay), 8)
        state = replay.state_dict()
        restored = ReplayBuffer(8, seed=3)
        restored.load_state_dict(state)
        self.assertEqual(len(restored), 8)
        self.assertEqual(restored.seen, replay.seen)
        sample_x, sample_y = restored.sample(4)
        self.assertEqual(sample_x.shape, (4, 2))
        self.assertEqual(sample_y.shape, (4, 1))

    def test_checkpoint_restores_model_optimizer_and_replay(self):
        model = TrainableMLP(2, 8, 1, seed=5)
        optimizer = Adam(model.parameters, learning_rate=0.02)
        replay = ReplayBuffer(12, seed=6)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            train_supervised(model, self.x, self.y, config=TrainingConfig(epochs=5, batch_size=16, seed=1), optimizer=optimizer, replay=replay, checkpoint_path=path)
            expected = model.predict(self.x)
            restored_model = TrainableMLP(2, 8, 1, seed=99)
            restored_optimizer = Adam(restored_model.parameters, learning_rate=0.02)
            restored_replay = ReplayBuffer(12, seed=6)
            manifest = load_checkpoint(path, restored_model, restored_optimizer, replay=restored_replay)
            np.testing.assert_array_equal(restored_model.predict(self.x), expected)
            self.assertEqual(restored_optimizer.step_count, optimizer.step_count)
            self.assertEqual(len(restored_replay), len(replay))
            self.assertEqual(manifest["version"], 1)

    def test_optimizer_step_is_atomic_on_nonfinite_later_parameter(self):
        model = TrainableMLP(2, 4, 1, seed=2)
        optimizer = Adam(model.parameters)
        for parameter in model.parameters:
            parameter.grad = np.ones_like(parameter.data)
        model.parameters[-1].grad[...] = np.nan
        before_data = [parameter.data.copy() for parameter in model.parameters]
        before_m = [value.copy() for value in optimizer._m]
        before_v = [value.copy() for value in optimizer._v]
        with self.assertRaises(FloatingPointError):
            optimizer.step(model.parameters)
        self.assertEqual(optimizer.step_count, 0)
        for parameter, expected in zip(model.parameters, before_data):
            np.testing.assert_array_equal(parameter.data, expected)
        for value, expected in zip(optimizer._m, before_m):
            np.testing.assert_array_equal(value, expected)
        for value, expected in zip(optimizer._v, before_v):
            np.testing.assert_array_equal(value, expected)

    def test_nonfinite_gradient_is_rejected(self):
        model = TrainableMLP(2, 4, 1, seed=2)
        optimizer = Adam(model.parameters)
        model.parameters[0].grad[...] = np.nan
        with self.assertRaises(FloatingPointError):
            optimizer.step(model.parameters)

    def test_replay_continual_update_preserves_previous_task_signal(self):
        first_x = self.x[:48]
        first_y = self.y[:48]
        second_x = self.x[48:]
        second_y = self.y[48:]
        model = TrainableMLP(2, 10, 1, seed=10)
        train_supervised(model, first_x, first_y, config=TrainingConfig(epochs=50, batch_size=12, seed=2))
        before = evaluate_mse(model, first_x, first_y)
        replay = ReplayBuffer(48, seed=11)
        replay.add_batch(first_x, first_y)
        train_supervised(model, second_x, second_y, config=TrainingConfig(epochs=35, batch_size=12, replay_ratio=0.5, seed=3), replay=replay)
        after = evaluate_mse(model, first_x, first_y)
        self.assertLess(after, max(before * 8.0, 0.02))
        self.assertLess(evaluate_mse(model, second_x, second_y), 0.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
