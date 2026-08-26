from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from holyfitra_attention_lm import ATTENTION_SCHEMA, CausalEmbeddingAttentionLanguageModel
from holyfitra_local_lm import LocalLanguageModelError, load_local_language_model
from holyfitra_compiler import main as compiler_main


class CausalEmbeddingAttentionTests(unittest.TestCase):
    def test_future_tokens_cannot_change_prior_causal_logits(self):
        model = CausalEmbeddingAttentionLanguageModel(d_model=8, context_tokens=8, epochs=1, seed=7)
        prefix = model.logits_for_tokens([256, 65, 66])
        extended = model.logits_for_tokens([256, 65, 66, 99])
        np.testing.assert_allclose(prefix, extended[:3], rtol=0.0, atol=1e-6)

    def test_training_is_deterministic_and_reduces_its_matched_train_nll(self):
        corpus = ("xayaxayaxayaxayaxaya",)
        first = CausalEmbeddingAttentionLanguageModel(d_model=8, context_tokens=8, learning_rate=0.1, epochs=12, seed=17)
        before = first.evaluate(corpus).mean_nll
        receipt = first.fit(corpus)
        after = first.evaluate(corpus).mean_nll
        second = CausalEmbeddingAttentionLanguageModel(d_model=8, context_tokens=8, learning_rate=0.1, epochs=12, seed=17)
        second.fit(corpus)
        self.assertLess(after, before)
        self.assertEqual(first.model_sha256, second.model_sha256)
        self.assertEqual(receipt.schema, ATTENTION_SCHEMA)
        self.assertEqual(receipt.architecture, "causal-embedding-attention")
        self.assertEqual(receipt.context_rows, 0)
        self.assertEqual(receipt.parameter_count, first.parameter_count)

    def test_checkpoint_round_trip_and_bounds(self):
        model = CausalEmbeddingAttentionLanguageModel(d_model=8, context_tokens=8, epochs=3)
        model.fit(("ababa",))
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "attention.hflm"
            model.save(checkpoint)
            restored = load_local_language_model(checkpoint)
            self.assertIsInstance(restored, CausalEmbeddingAttentionLanguageModel)
            self.assertEqual(restored.model_sha256, model.model_sha256)
            self.assertEqual(restored.generate("a", max_new_tokens=3), model.generate("a", max_new_tokens=3))
            checkpoint.write_bytes(b"bad")
            with self.assertRaisesRegex(LocalLanguageModelError, "invalid local-language-model checkpoint"):
                load_local_language_model(checkpoint)
        with self.assertRaisesRegex(LocalLanguageModelError, "context_tokens"):
            CausalEmbeddingAttentionLanguageModel(context_tokens=1)

    def test_primary_cli_trains_attention_without_provider_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus.txt"
            checkpoint = root / "attention.hflm"
            corpus.write_text("xayaxayaxaya", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(compiler_main(["local-lm", "train", str(corpus), "--output", str(checkpoint), "--architecture", "attention", "--d-model", "8", "--context-tokens", "8", "--epochs", "3"]), 0)
            self.assertTrue(checkpoint.is_file())
            self.assertIn(ATTENTION_SCHEMA, output.getvalue())


if __name__ == "__main__":
    unittest.main()
