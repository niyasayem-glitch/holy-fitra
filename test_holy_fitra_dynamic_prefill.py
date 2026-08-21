#!/usr/bin/env python3
from __future__ import annotations

import unittest
import numpy as np

from holy_fitra_dynamic_prefill import AdaptivePrefillPolicy, DynamicPrefillPacker, KVPagePool, PrefillCostProfile, PrefillError, SequenceRequest, ToyCausalPrefill


class DynamicPrefillTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.requests = [SequenceRequest(f"r{i}", rng.standard_normal((length, 4)).astype(np.float32), priority=i % 2) for i, length in enumerate([1, 3, 8, 9, 15, 16, 23])]

    def test_offsets_and_lengths_are_exact(self):
        batches = DynamicPrefillPacker(bucket_width=8, max_tokens=100, max_sequences=20).pack(self.requests)
        for batch in batches:
            self.assertEqual(batch.offsets[0], 0)
            self.assertEqual(batch.offsets[-1], batch.token_count)
            self.assertTrue(np.array_equal(np.diff(batch.offsets), batch.lengths))
            for row, request in enumerate(batch.requests):
                start, end = batch.offsets[row], batch.offsets[row + 1]
                self.assertTrue(np.array_equal(batch.tokens[start:end], request.tokens))

    def test_bucket_and_token_limits(self):
        batches = DynamicPrefillPacker(bucket_width=8, max_tokens=16, max_sequences=2).pack(self.requests)
        for batch in batches:
            self.assertLessEqual(batch.batch_size, 2)
            self.assertTrue(batch.token_count <= 16 or batch.batch_size == 1)
            self.assertEqual(len({batch.bucket_id}), 1)
            self.assertEqual(batch.bucket_id, (batch.lengths[0] + 7) // 8)
            self.assertTrue(np.all((batch.lengths + 7) // 8 == batch.bucket_id))

    def test_exact_batched_causal_attention(self):
        model = ToyCausalPrefill(4)
        batches = DynamicPrefillPacker(bucket_width=8, max_tokens=100, max_sequences=20).pack(self.requests)
        for batch in batches:
            outputs = model.packed_bucket(batch)
            for request in batch.requests:
                np.testing.assert_allclose(outputs[request.request_id], model.single(request.tokens), rtol=1e-5, atol=1e-5)

    def test_kv_leases_are_non_overlapping_and_reusable(self):
        pool = KVPagePool(128)
        batches = DynamicPrefillPacker(bucket_width=8, max_tokens=100, max_sequences=20).pack(self.requests, kv_pool=pool)
        leases = [lease for batch in batches for lease in batch.kv_leases]
        spans = sorted((lease.start, lease.start + lease.length) for lease in leases)
        for (_, previous_end), (current_start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(previous_end, current_start)
        for request in self.requests:
            pool.release(request.request_id)
        self.assertEqual(pool._used, 0)
        new_lease = pool.reserve("new", 64)
        self.assertEqual(new_lease.start, 0)

    def test_cancelled_and_expired_requests_rejected(self):
        cancelled = SequenceRequest("cancel", np.zeros((2, 4), dtype=np.float32), cancelled=True)
        with self.assertRaises(PrefillError):
            DynamicPrefillPacker().pack([cancelled])
        expired = SequenceRequest("expired", np.zeros((2, 4), dtype=np.float32), deadline_ns=1)
        with self.assertRaises(PrefillError):
            DynamicPrefillPacker().pack([expired], now_ns=2)

    def test_invalid_dtype_rejected(self):
        invalid = SequenceRequest("bad", np.zeros((2, 4), dtype=np.int8))
        with self.assertRaises(PrefillError):
            DynamicPrefillPacker().pack([invalid])

    def test_kv_capacity_rejected(self):
        with self.assertRaises(PrefillError):
            DynamicPrefillPacker().pack(self.requests, kv_pool=KVPagePool(2))

    def test_adaptive_policy_avoids_high_padding(self):
        batches = DynamicPrefillPacker(bucket_width=64, max_tokens=1000, max_sequences=20).pack(self.requests[:4])
        policy = AdaptivePrefillPolicy(PrefillCostProfile(max_padding_ratio=1.05, min_fused_sequences=2))
        self.assertEqual(policy.choose(batches[0]), "scalar")
        normal_requests = [SequenceRequest(f"n{i}", np.zeros((length, 4), dtype=np.float32)) for i, length in enumerate([8, 9, 10, 11])]
        normal = DynamicPrefillPacker(bucket_width=8, max_tokens=1000, max_sequences=20).pack(normal_requests)
        policy = AdaptivePrefillPolicy(PrefillCostProfile(max_padding_ratio=1.5, min_fused_sequences=2))
        self.assertEqual(policy.choose(max(normal, key=lambda batch: batch.batch_size),), "fused")


if __name__ == "__main__":
    unittest.main(verbosity=2)
