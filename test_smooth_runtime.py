#!/usr/bin/env python3
from __future__ import annotations

import unittest

from hyperc_smooth_runtime import PrecomputedMarkov, PreallocatedTokenCache, SmoothGreedyDecoder, SmoothPlan
from hyperc_speculative import SpeculativePlan, SpeculativeDecoder, make_models, standard_generate


class SmoothRuntimeTests(unittest.TestCase):
    def test_preallocated_cache_transaction(self):
        cache = PreallocatedTokenCache(8)
        cache.load([1, 2])
        checkpoint = cache.begin()
        cache.rollback(checkpoint)
        cache.commit(checkpoint, __import__("numpy").array([3, 4], dtype="int32"), 2)
        self.assertEqual(cache.as_list(), [1, 2, 3, 4])
        cache.rollback(2)
        self.assertEqual(cache.as_list(), [1, 2])

    def test_smooth_path_matches_target_only(self):
        draft, target = make_models(vocab=32, seed=41)
        expected = standard_generate(target, [0], 128)
        fast = SmoothGreedyDecoder(PrecomputedMarkov(draft), PrecomputedMarkov(target), SmoothPlan(draft_k=5, max_tokens=256))
        fast.cache.load([0])
        actual = fast.generate(128)
        self.assertEqual(actual, expected)
        self.assertEqual(fast.cache.length, 129)

    def test_smooth_path_matches_baseline_with_weak_draft(self):
        draft, target = make_models(vocab=32, seed=41)
        weak_draft, _ = make_models(vocab=32, seed=99)
        expected = standard_generate(target, [0], 96)
        baseline = SpeculativeDecoder(weak_draft, target, SpeculativePlan(draft_k=4, mode="greedy"), max_tokens=128)
        baseline.cache.tokens = [0]
        baseline_output = baseline.generate(96)
        fast = SmoothGreedyDecoder(PrecomputedMarkov(weak_draft), PrecomputedMarkov(target), SmoothPlan(draft_k=4, max_tokens=128))
        fast.cache.load([0])
        fast_output = fast.generate(96)
        self.assertEqual(baseline_output, expected)
        self.assertEqual(fast_output, expected)

    def test_output_count_never_overcommits(self):
        draft, target = make_models(vocab=32, seed=41)
        fast = SmoothGreedyDecoder(PrecomputedMarkov(draft), PrecomputedMarkov(target), SmoothPlan(draft_k=8, max_tokens=128))
        fast.cache.load([0])
        self.assertEqual(len(fast.generate(3)), 3)
        self.assertEqual(fast.cache.length, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
