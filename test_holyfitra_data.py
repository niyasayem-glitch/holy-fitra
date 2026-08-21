#!/usr/bin/env python3
from __future__ import annotations
import unittest
import numpy as np
from holyfitra_data import StreamingDataset
from holyfitra_learning import TrainableMLP, TrainingConfig, evaluate_streaming_mse, train_supervised_streaming


class HolyFitraDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        x = np.arange(40, dtype=np.float32).reshape(20, 2)
        y = (x[:, :1] * 3.0).astype(np.float32)
        self.dataset = StreamingDataset.from_arrays(x, y, seed=17, name="toy")

    def test_deterministic_buffer_shuffle_by_epoch(self):
        first = [batch.indices.tolist() for batch in self.dataset.iter_batches(4, epoch=2, shuffle=True, shuffle_buffer=20)]
        repeat = [batch.indices.tolist() for batch in self.dataset.iter_batches(4, epoch=2, shuffle=True, shuffle_buffer=20)]
        other_epoch = [batch.indices.tolist() for batch in self.dataset.iter_batches(4, epoch=3, shuffle=True, shuffle_buffer=20)]
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, other_epoch)
        self.assertEqual(sorted(index for batch in first for index in batch), list(range(20)))

    def test_streaming_shuffle_consumes_bounded_prefix_before_first_batch(self):
        consumed: list[int] = []
        def source():
            for index in range(1000):
                consumed.append(index)
                yield np.array([index], dtype=np.float32), np.array([index + 1], dtype=np.float32)
        dataset = StreamingDataset(source, input_shape=(1,), target_shape=(1,), seed=3)
        batches = dataset.iter_batches(2, shuffle=True, shuffle_buffer=5)
        next(batches)
        self.assertLessEqual(len(consumed), 7)
        self.assertGreaterEqual(len(consumed), 5)

    def test_split_is_repeatable_and_value_disjoint(self):
        split_a = self.dataset.split(0.75, seed=99)
        split_b = self.dataset.split(0.75, seed=99)
        train_x, train_y = split_a.train.to_arrays()
        valid_x, valid_y = split_a.validation.to_arrays()
        train_x2, train_y2 = split_b.train.to_arrays()
        valid_x2, valid_y2 = split_b.validation.to_arrays()
        np.testing.assert_array_equal(train_x, train_x2)
        np.testing.assert_array_equal(train_y, train_y2)
        np.testing.assert_array_equal(valid_x, valid_x2)
        np.testing.assert_array_equal(valid_y, valid_y2)
        self.assertEqual(set(map(tuple, train_x)).intersection(set(map(tuple, valid_x))), set())
        self.assertEqual(train_x.shape[0] + valid_x.shape[0], 20)
        self.assertGreater(train_x.shape[0], valid_x.shape[0])

    def test_batch_metadata_partial_batch_and_drop_last(self):
        batches = list(self.dataset.iter_batches(6, epoch=4, shuffle=False))
        self.assertEqual([batch.size for batch in batches], [6, 6, 6, 2])
        self.assertEqual([batch.step for batch in batches], [0, 1, 2, 3])
        self.assertTrue(all(batch.epoch == 4 for batch in batches))
        dropped = list(self.dataset.iter_batches(6, drop_last=True))
        self.assertEqual([batch.size for batch in dropped], [6, 6, 6])

    def test_streaming_training_and_evaluation_integrate_with_learning_runtime(self):
        x = np.linspace(-1.0, 1.0, 48, dtype=np.float32).reshape(24, 2)
        y = np.concatenate((x[:, :1] * 2.0, x[:, 1:] * -1.5), axis=1)
        train = StreamingDataset.from_arrays(x, y, seed=8)
        model = TrainableMLP(2, 8, 2, seed=4)
        history = train_supervised_streaming(model, train, config=TrainingConfig(epochs=20, batch_size=6, seed=8, shuffle_buffer=8))
        self.assertLess(history.final_loss, history.initial_loss)
        self.assertLess(evaluate_streaming_mse(model, train, batch_size=5), 0.2)

    def test_sample_validation_and_one_shot_source_rejection(self):
        with self.assertRaises(ValueError):
            StreamingDataset((sample for sample in [(np.zeros(2), np.zeros(1))]), input_shape=(1,), target_shape=(1,))
        invalid = StreamingDataset(lambda: iter([(np.array([1.0, np.nan]), np.array([1.0]))]), input_shape=(2,), target_shape=(1,))
        with self.assertRaises(ValueError):
            list(invalid.iter_samples())
        with self.assertRaises(ValueError):
            list(self.dataset.iter_batches(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
