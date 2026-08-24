import hashlib
import random
import unittest

from holyfitra_adapter_residency import AdapterActivationSnapshot, AdapterArtifact, AdapterCatalog, AdapterMode, AdapterResidencyError, AdapterResidencyLedger, AdapterResidencyPolicy


def digest(value: str | bytes) -> str:
    raw = value.encode("ascii") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


class AdapterResidencyTests(unittest.TestCase):
    base_digest = digest("base")

    def _policy(self, *, bytes_limit: int = 64, adapter_limit: int = 3, active_limit: int = 2, age: int = 4) -> AdapterResidencyPolicy:
        return AdapterResidencyPolicy(self.base_digest, bytes_limit, adapter_limit, active_limit, age, (AdapterMode.LOW_RANK,))

    def _artifact(self, adapter_id: str, payload: bytes, *, protected: bool = False) -> AdapterArtifact:
        return AdapterArtifact(adapter_id, self.base_digest, digest(payload), len(payload), 8, 8, 2, 4.0, AdapterMode.LOW_RANK, protected)

    def test_canonical_policy_and_catalog_reject_mismatch(self):
        first = self._artifact("adapter.alpha", b"a" * 16)
        second = self._artifact("adapter.beta", b"b" * 16)
        policy = self._policy()
        self.assertEqual(AdapterResidencyPolicy.from_body(policy.body()), policy)
        catalog = AdapterCatalog(policy.policy_id, self.base_digest, (first, second))
        self.assertEqual(AdapterCatalog.from_body(catalog.body()), catalog)
        with self.assertRaises(AdapterResidencyError):
            AdapterCatalog(policy.policy_id, self.base_digest, (second, first)).verify()
        with self.assertRaises(AdapterResidencyError):
            AdapterResidencyPolicy(self.base_digest, 64, 3, 4, 3, (AdapterMode.LOW_RANK,)).verify()

    def test_admission_activation_and_rollback_are_bounded(self):
        ledger = AdapterResidencyLedger(self._policy(bytes_limit=32, adapter_limit=2, active_limit=1))
        alpha = self._artifact("adapter.alpha", b"a" * 16, protected=True)
        beta = self._artifact("adapter.beta", b"b" * 16)
        gamma = self._artifact("adapter.gamma", b"c" * 16)
        self.assertEqual(ledger.admit(alpha, step=0).action, "admit")
        self.assertEqual(ledger.admit(beta, step=1).action, "admit")
        self.assertEqual(ledger.activate("adapter.alpha", step=2).action, "activate")
        snapshot = ledger.snapshot()
        self.assertEqual(ledger.deactivate("adapter.alpha", step=3).action, "deactivate")
        self.assertEqual(ledger.admit(gamma, step=4).evicted, ("adapter.beta",))
        rollback = ledger.rollback(snapshot, step=5)
        self.assertEqual((rollback.action, rollback.active_lanes), ("rollback", ("adapter.alpha",)))
        self.assertEqual(ledger.activate("adapter.gamma", step=6).reason, "active_lane_limit")
        receipt = ledger.receipt()
        self.assertEqual((receipt["resident_bytes"], receipt["resident_adapters"], receipt["active_lanes"]), (32, 2, ["adapter.alpha"]))
        self.assertEqual(receipt["receipt_id"], ledger.receipt()["receipt_id"])

    def test_expiry_and_rollback_fail_closed_when_snapshot_is_no_longer_resident(self):
        ledger = AdapterResidencyLedger(self._policy(bytes_limit=32, adapter_limit=2, active_limit=1, age=1))
        alpha = self._artifact("adapter.alpha", b"a" * 16)
        self.assertEqual(ledger.admit(alpha, step=0).action, "admit")
        snapshot = AdapterActivationSnapshot(ledger.policy.policy_id, ("adapter.alpha",))
        rejected = ledger.rollback(snapshot, step=2)
        self.assertEqual((rejected.action, rejected.reason, rejected.evicted), ("reject", "snapshot_adapter_not_resident", ("adapter.alpha",)))
        with self.assertRaises(AdapterResidencyError):
            AdapterActivationSnapshot("not-a-digest", ()).verify()

    def test_deterministic_stress_never_breaks_residency_limits(self):
        policy = self._policy(bytes_limit=256, adapter_limit=4, active_limit=2, age=5)
        ledger = AdapterResidencyLedger(policy)
        generator = random.Random(119)
        known: dict[str, AdapterArtifact] = {}
        for step in range(500):
            adapter_id = f"adapter.{generator.randrange(10)}"
            if generator.randrange(4) == 0:
                ledger.activate(adapter_id, step=step)
            elif generator.randrange(5) == 0:
                ledger.deactivate(adapter_id, step=step)
            else:
                payload = (adapter_id + str(generator.randrange(3))).encode("ascii") * generator.randrange(1, 6)
                artifact = self._artifact(adapter_id, payload)
                known[adapter_id] = artifact
                ledger.admit(artifact, step=step)
            receipt = ledger.receipt()
            self.assertLessEqual(receipt["resident_bytes"], policy.max_resident_bytes)
            self.assertLessEqual(receipt["resident_adapters"], policy.max_adapters)
            self.assertLessEqual(len(receipt["active_lanes"]), policy.max_active_lanes)
            self.assertTrue(set(receipt["active_lanes"]).issubset({entry["artifact"]["adapter_id"] for entry in receipt["entries"]}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
