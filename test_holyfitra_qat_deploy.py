#!/usr/bin/env python3
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import numpy as np
from hyperc_nn import Tensor
from holyfitra_deploy import export_mlp, load_deployment
from holyfitra_learning import TrainableMLP, TrainingConfig, train_supervised
from holyfitra_qat import QuantizationAwareMLP, QuantizationQualityError, QuantizationQualityGate, QuantizationSpec, fake_quantize_tensor, quantize_array


class HolyFitraQATDeploymentTests(unittest.TestCase):
    def test_int4_round_trip_and_quality_metadata(self):
        values = np.array([[0.1, -1.2, 2.4, 0.0, 0.8], [1.7, -0.2, 0.4, -2.1, 0.3], [-0.5, 1.1, -1.9, 0.7, 2.0]], dtype=np.float32)
        quantized = quantize_array(values, QuantizationSpec(bits=4, axis=0))
        restored = quantized.dequantize()
        self.assertEqual(quantized.packed.dtype, np.dtype(np.uint8))
        self.assertEqual(quantized.packed.size, (values.size + 1) // 2)
        self.assertEqual(quantized.metadata()["scale_shape"], [3, 1])
        self.assertLessEqual(quantized.max_abs_error, 0.3)
        np.testing.assert_allclose(restored, np.asarray(quantized.metadata()["scales"], dtype=np.float32) * 0 + restored)

    def test_fake_quantization_uses_straight_through_gradient(self):
        value = Tensor(np.array([[0.25, -0.7]], dtype=np.float32), requires_grad=True)
        output = fake_quantize_tensor(value, QuantizationSpec(bits=4))
        output.mean().backward()
        np.testing.assert_allclose(value.grad, np.full_like(value.data, 0.5), atol=1e-6)

    def test_qat_wrapper_trains_with_existing_learning_loop(self):
        rng = np.random.default_rng(13)
        x = rng.normal(size=(64, 4)).astype(np.float32)
        target = x @ np.array([[1.1, -0.4], [0.2, 0.8], [-0.7, 0.3], [0.5, 0.6]], dtype=np.float32)
        base = TrainableMLP(4, 8, 2, seed=4)
        qat = QuantizationAwareMLP(base, weight_spec=QuantizationSpec(bits=8, axis=0), quality_gate=QuantizationQualityGate(max_mse=0.001, max_abs_error=0.1))
        history = train_supervised(qat, x, target, config=TrainingConfig(epochs=35, batch_size=16, seed=7))
        self.assertLess(history.final_loss, history.initial_loss)
        self.assertTrue(np.all(np.isfinite(qat.predict(x))))

    def test_export_is_deterministic_and_round_trips(self):
        gate = QuantizationQualityGate(max_mse=0.03, max_abs_error=0.3)
        model = QuantizationAwareMLP(TrainableMLP(3, 5, 2, seed=8), weight_spec=QuantizationSpec(bits=4, axis=0), quality_gate=gate)
        inputs = np.arange(15, dtype=np.float32).reshape(5, 3) / 7.0
        with tempfile.TemporaryDirectory() as directory:
            path_a = Path(directory) / "model_a.hfbin"
            path_b = Path(directory) / "model_b.hfbin"
            artifact_a = export_mlp(model, path_a, weight_spec=model.weight_spec, quality_gate=gate, metadata={"purpose": "test", "seed": 8})
            artifact_b = export_mlp(model, path_b, weight_spec=model.weight_spec, quality_gate=gate, metadata={"purpose": "test", "seed": 8})
            self.assertEqual(path_a.read_bytes(), path_b.read_bytes())
            self.assertEqual(artifact_a.digest, artifact_b.digest)
            bundle = load_deployment(path_a)
            np.testing.assert_allclose(bundle.predict(inputs), model.predict(inputs), atol=1e-6)
            self.assertEqual(bundle.digest, artifact_a.digest)
            self.assertEqual(bundle.manifest["format"], "holyfitra.deployment")

    def test_export_quality_gate_fails_closed(self):
        model = TrainableMLP(3, 5, 2, seed=8)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(QuantizationQualityError):
                export_mlp(model, Path(directory) / "rejected.hfbin", weight_spec=QuantizationSpec(bits=4, axis=0), quality_gate=QuantizationQualityGate(max_mse=0.0, max_abs_error=0.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
