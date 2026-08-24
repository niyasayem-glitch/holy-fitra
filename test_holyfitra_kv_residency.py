import hashlib
import random
import unittest

from holyfitra_kv_residency import KVBlock, KVPrecision, KVPrecisionGovernor, KVResidencyError, KVResidencyLedger, KVResidencyPolicy


def digest(letter: str) -> str:
    return hashlib.sha256(letter.encode("ascii")).hexdigest()


class KVResidencyTests(unittest.TestCase):
    def _policy(self, *, max_bytes: int = 64, max_entries: int = 2, max_age_steps: int = 3) -> KVResidencyPolicy:
        return KVResidencyPolicy(max_bytes, max_entries, max_age_steps, (KVPrecision.FP16, KVPrecision.INT8, KVPrecision.INT4), 0.80, 0.10)

    def _block(self, key: str, precision: KVPrecision, *, protected: bool = False) -> KVBlock:
        return KVBlock(key, digest(key[0]), 1, 2, 4, precision, protected)

    def test_policy_round_trip_and_precision_fail_closed(self):
        policy = self._policy()
        self.assertEqual(KVResidencyPolicy.from_body(policy.body()), policy)
        governor = KVPrecisionGovernor(policy)
        self.assertEqual(governor.decide(KVPrecision.INT4, quality_score=0.9, normalized_error=0.05).body()["action"], "accept")
        missing = governor.decide(KVPrecision.INT4, quality_score=None, normalized_error=None)
        self.assertEqual((missing.action, missing.selected, missing.reason), ("fallback", KVPrecision.FP16, "missing_quality_evidence"))
        failed = governor.decide(KVPrecision.INT8, quality_score=0.7, normalized_error=0.02)
        self.assertEqual((failed.action, failed.selected, failed.reason), ("fallback", KVPrecision.FP16, "quality_below_threshold"))
        forbidden = KVPrecisionGovernor(KVResidencyPolicy(64, 2, 3, (KVPrecision.FP16,), 0.8, 0.1)).decide(KVPrecision.INT4, quality_score=1.0, normalized_error=0.0)
        self.assertEqual((forbidden.action, forbidden.selected), ("reject", None))

    def test_ledger_evicts_only_evictable_entries_and_receipt_is_deterministic(self):
        ledger = KVResidencyLedger(self._policy())
        first = self._block("a", KVPrecision.FP16, protected=True)
        second = self._block("b", KVPrecision.FP16)
        third = self._block("c", KVPrecision.FP16)
        self.assertEqual(ledger.admit(first, step=0).action, "admit")
        self.assertEqual(ledger.admit(second, step=1).action, "admit")
        decision = ledger.admit(third, step=2)
        self.assertEqual((decision.action, decision.evicted, decision.resident_bytes, decision.resident_entries), ("admit", ("b",), 64, 2))
        self.assertEqual(ledger.access("a", step=3).action, "touch")
        receipt = ledger.receipt()
        self.assertEqual(receipt["resident_bytes"], 64)
        self.assertEqual(receipt["resident_entries"], 2)
        self.assertEqual(receipt["receipt_id"], ledger.receipt()["receipt_id"])
        protected_only = KVResidencyLedger(KVResidencyPolicy(32, 1, 3, (KVPrecision.FP16,), 0.8, 0.1))
        self.assertEqual(protected_only.admit(first, step=0).action, "admit")
        self.assertEqual(protected_only.admit(self._block("d", KVPrecision.FP16), step=1).reason, "protected_entries_block_admission")

    def test_expiry_and_malformed_contracts_are_rejected(self):
        ledger = KVResidencyLedger(self._policy(max_age_steps=1))
        self.assertEqual(ledger.admit(self._block("e", KVPrecision.INT8), step=0).action, "admit")
        expired = ledger.access("e", step=2)
        self.assertEqual((expired.action, expired.evicted), ("reject", ("e",)))
        with self.assertRaises(KVResidencyError):
            KVBlock("bad key", digest("a"), 1, 2, 4, KVPrecision.FP16).verify()
        with self.assertRaises(KVResidencyError):
            KVResidencyPolicy(64, 2, 3, (KVPrecision.INT8,), 0.8, 0.1).verify()
        with self.assertRaises(KVResidencyError):
            KVResidencyPolicy.from_body({"schema": "holyfitra.kv-residency-policy/v1"})

    def test_deterministic_stress_keeps_the_budget_invariant(self):
        policy = KVResidencyPolicy(256, 4, 6, (KVPrecision.FP16, KVPrecision.INT8, KVPrecision.INT4), 0.8, 0.1)
        ledger = KVResidencyLedger(policy)
        generator = random.Random(41)
        precisions = (KVPrecision.FP16, KVPrecision.INT8, KVPrecision.INT4)
        for step in range(500):
            if generator.randrange(3) == 0:
                key = chr(ord("a") + generator.randrange(12))
                ledger.access(key, step=step)
            else:
                key = chr(ord("a") + generator.randrange(12))
                block = KVBlock(key, digest(key), 1, generator.randrange(1, 5), generator.randrange(1, 9), precisions[generator.randrange(len(precisions))], False)
                ledger.admit(block, step=step)
            receipt = ledger.receipt()
            self.assertLessEqual(receipt["resident_bytes"], policy.max_bytes)
            self.assertLessEqual(receipt["resident_entries"], policy.max_entries)
            self.assertEqual(receipt["resident_entries"], len(receipt["entries"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
