#!/usr/bin/env python3
from __future__ import annotations

import unittest
import numpy as np

from holy_fitra_ragged_attention import RaggedAttentionError, RaggedBatch, RaggedKernelDispatch, pack_sequences, padded_attention_reference, ragged_attention_reference, ragged_work


class RaggedAttentionTests(unittest.TestCase):
    def test_sequence_isolation_and_exact_causality(self):
        rng = np.random.default_rng(8)
        rows = [tuple(rng.standard_normal((length, 6)).astype(np.float32) for _ in range(3)) for length in [1, 4, 9]]
        batch = pack_sequences(rows)
        ragged = ragged_attention_reference(batch)
        padded = padded_attention_reference(batch)
        np.testing.assert_allclose(ragged, padded, rtol=1e-5, atol=1e-5)
        self.assertLessEqual(ragged_work(batch), batch.total_tokens * batch.total_tokens * batch.d_model)

    def test_no_padding_work_for_unequal_sequences(self):
        rng = np.random.default_rng(9)
        rows = [tuple(rng.standard_normal((length, 4)).astype(np.float32) for _ in range(3)) for length in [1, 2, 16]]
        batch = pack_sequences(rows)
        ragged_cost = ragged_work(batch)
        padded_cost = 3 * 16 * 16 * 4
        self.assertLess(ragged_cost, padded_cost)

    def test_payload_digest_and_finite_state_are_verified(self):
        rng = np.random.default_rng(12)
        rows = [tuple(rng.standard_normal((3, 4)).astype(np.float32) for _ in range(3))]
        batch = pack_sequences(rows)
        batch.q[0, 0] = np.nan
        with self.assertRaises(RaggedAttentionError):
            batch.validate()
        batch = pack_sequences(rows)
        batch.q[0, 0] += 1.0
        with self.assertRaises(RaggedAttentionError):
            batch.validate()

    def test_offsets_must_be_strictly_increasing(self):
        rng = np.random.default_rng(10)
        rows = [tuple(rng.standard_normal((2, 4)).astype(np.float32) for _ in range(3))]
        batch = pack_sequences(rows)
        invalid = RaggedBatch(batch.q, batch.k, batch.v, np.asarray([0, 0], dtype=np.int32), 1, 4, batch.digest)
        with self.assertRaises(RaggedAttentionError):
            invalid.validate()

    def test_dispatch_rejects_non_boolean_flags(self):
        with self.assertRaises(ValueError):
            RaggedKernelDispatch(has_neon=1)

    def test_dispatch_priority(self):
        self.assertEqual(RaggedKernelDispatch(has_neon=False, has_sve=False).kernel_name(8), "holy_fitra_ragged_attention_scalar")
        self.assertEqual(RaggedKernelDispatch(has_neon=True, has_sve=False).kernel_name(8), "holy_fitra_ragged_attention_neon")
        self.assertEqual(RaggedKernelDispatch(has_neon=True, has_sve=True).kernel_name(8), "holy_fitra_ragged_attention_sve")


if __name__ == "__main__":
    unittest.main(verbosity=2)
