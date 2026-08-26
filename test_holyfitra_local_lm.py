from __future__ import annotations

import tempfile
import unittest
import contextlib
import io
from pathlib import Path

from holyfitra_local_lm import BOS_TOKEN, CausalBigramLanguageModel, ByteTokenizer, LocalLanguageModelError, VOCAB_SIZE
from holyfitra_compiler import main as compiler_main


class LocalLanguageModelTests(unittest.TestCase):
    def test_byte_tokenizer_is_deterministic_and_bounded(self):
        tokens = ByteTokenizer.encode("hé")
        self.assertEqual(tokens.tolist(), list("hé".encode("utf-8")))
        self.assertEqual(ByteTokenizer.decode(tokens), "hé")
        self.assertEqual(ByteTokenizer.vocabulary_size, VOCAB_SIZE)
        self.assertEqual(ByteTokenizer.bos_token, BOS_TOKEN)
        with self.assertRaisesRegex(LocalLanguageModelError, "must not be empty"):
            ByteTokenizer.encode("")

    def test_causal_training_generation_evaluation_and_receipts_are_reproducible(self):
        corpus = ("ababa", "ababa")
        first = CausalBigramLanguageModel(smoothing=0.1)
        first_receipt = first.fit(corpus)
        second = CausalBigramLanguageModel(smoothing=0.1)
        second_receipt = second.fit(corpus)
        self.assertEqual(first_receipt.body(), second_receipt.body())
        self.assertEqual(first.generate("a", max_new_tokens=4), "baba")
        evaluation = first.evaluate(corpus)
        self.assertEqual(evaluation.model_sha256, first.model_sha256)
        self.assertEqual(evaluation.transitions, 10)
        self.assertGreater(evaluation.mean_nll, 0.0)
        self.assertTrue(evaluation.mean_nll < 10.0)

    def test_checkpoint_round_trip_and_tamper_rejection(self):
        model = CausalBigramLanguageModel()
        model.fit(("abba",))
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "model.hflm"
            model.save(checkpoint)
            restored = CausalBigramLanguageModel.load(checkpoint)
            self.assertEqual(restored.model_sha256, model.model_sha256)
            self.assertEqual(restored.generate("a", max_new_tokens=3), model.generate("a", max_new_tokens=3))
            checkpoint.write_bytes(b"not-a-checkpoint")
            with self.assertRaisesRegex(LocalLanguageModelError, "invalid local-language-model checkpoint"):
                CausalBigramLanguageModel.load(checkpoint)

    def test_training_and_generation_reject_invalid_bounds(self):
        model = CausalBigramLanguageModel()
        with self.assertRaisesRegex(LocalLanguageModelError, "must not be empty"):
            model.fit(())
        model.fit(("abc",))
        with self.assertRaisesRegex(LocalLanguageModelError, "max_new_tokens"):
            model.generate("a", max_new_tokens=-1)

    def test_primary_cli_trains_and_generates_without_provider_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus.txt"
            checkpoint = root / "baseline.hflm"
            corpus.write_text("ababa", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(compiler_main(["local-lm", "train", str(corpus), "--output", str(checkpoint)]), 0)
            self.assertTrue(checkpoint.is_file())
            with contextlib.redirect_stdout(output):
                self.assertEqual(compiler_main(["local-lm", "generate", str(checkpoint), "a", "--max-new-tokens", "4"]), 0)
            self.assertIn('"text": "baba"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
