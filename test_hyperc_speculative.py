#!/usr/bin/env python3
from __future__ import annotations

import unittest
import numpy as np

from hyperc_speculative import CacheState, MarkovModel, SpeculativeDecoder, SpeculativePlan, make_models


class SpeculativeHardeningTests(unittest.TestCase):
    def test_model_rejects_nonfinite_or_empty_logits(self):
        with self.assertRaises(ValueError):
            MarkovModel(np.array([[np.nan]], dtype=np.float64), "bad")
        with self.assertRaises(ValueError):
            MarkovModel(np.empty((0, 0), dtype=np.float64), "empty")

    def test_plan_and_decoder_reject_invalid_contracts(self):
        draft, target = make_models(vocab=4)
        with self.assertRaises(ValueError):
            SpeculativePlan(draft_k=0)
        with self.assertRaises(ValueError):
            SpeculativeDecoder(draft, target, SpeculativePlan(), max_tokens=True)
        with self.assertRaises(ValueError):
            SpeculativeDecoder(draft, MarkovModel(np.zeros((3, 3)), "other"), SpeculativePlan())

    def test_generation_count_and_cache_capacity_are_strict(self):
        draft, target = make_models(vocab=4)
        decoder = SpeculativeDecoder(draft, target, SpeculativePlan(draft_k=2), max_tokens=8)
        with self.assertRaises(ValueError):
            decoder.generate(True)
        decoder.cache.tokens = [0] * 8
        with self.assertRaises(RuntimeError):
            decoder.step()
        cache = CacheState(max_tokens=4)
        with self.assertRaises(RuntimeError):
            cache.commit(0, [0, 1, 2, 3, 4])

    def test_standard_generation_rejects_out_of_range_prefix(self):
        _, target = make_models(vocab=4)
        from hyperc_speculative import standard_generate
        with self.assertRaises(ValueError):
            standard_generate(target, [4], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
