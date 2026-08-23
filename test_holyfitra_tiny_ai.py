from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from holyfitra_tiny_ai import binary_accuracy, build_xor_deployment, train_xor_classifier, xor_dataset
from hyperc_language_core import compile_source

TEST_SIGNING_KEY = b"holyfitra-tiny-ai-test-key-v2"

class HolyFitraTinyAiTests(unittest.TestCase):
    def test_train_export_reload_and_repeat_are_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.hfbin"
            second_path = Path(directory) / "second.hfbin"
            first = build_xor_deployment(first_path, signing_key=TEST_SIGNING_KEY)
            second = build_xor_deployment(second_path, signing_key=TEST_SIGNING_KEY)
            self.assertLess(first.final_mse, first.initial_mse)
            self.assertEqual(first.float_accuracy, 1.0)
            self.assertEqual(first.deployment_accuracy, 1.0)
            self.assertEqual(first.deployment_digest, second.deployment_digest)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertGreater(first.deployment_bytes, 0)

    def test_classifier_outputs_all_xor_labels(self):
        model, _, _, accuracy = train_xor_classifier()
        inputs, targets = xor_dataset()
        self.assertEqual(accuracy, 1.0)
        np.testing.assert_array_equal(model.predict(inputs) >= 0.5, targets >= 0.5)

    def test_binary_accuracy_and_language_inference_declaration_fail_closed(self):
        with self.assertRaises(ValueError):
            binary_accuracy(np.zeros((2, 2), dtype=np.float32), np.zeros((2, 1), dtype=np.float32))
        source = (Path(__file__).parent / "examples" / "tiny_xor_inference.hf").read_text(encoding="utf-8")
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(len(result["lowered_plan"]), 2)
        self.assertEqual([operation["kernel"] for operation in result["lowered_plan"]], ["neon.f16_matmul", "neon.f16_matmul"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
