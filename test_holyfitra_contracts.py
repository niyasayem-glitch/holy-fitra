#!/usr/bin/env python3
from __future__ import annotations

import unittest

from holyfitra_contracts import (
    Evidence,
    EvidenceKind,
    ContractError,
    KernelContract,
    Option,
    OwnershipContract,
    OwnershipMode,
    RestartPolicy,
    Result,
    TaskScope,
    SupervisorSpec,
    TaskSpec,
)


class HolyFitraContractTests(unittest.TestCase):
    def test_option_and_result_are_exclusive(self):
        self.assertTrue(Option.some(7).is_some)
        self.assertFalse(Option.none().is_some)
        self.assertEqual(Result.ok(7).unwrap(), 7)
        self.assertFalse(Result.err("bad").is_ok)
        with self.assertRaises(ContractError):
            Result(value=7, error="bad")

    def test_evidence_cannot_gain_certainty_silently(self):
        prediction = Evidence("x", EvidenceKind.PREDICTION, 0.7, "model:draft")
        fact = Evidence("x", EvidenceKind.FACT, 1.0, "verified:test")
        self.assertFalse(prediction.can_promote_to(EvidenceKind.FACT))
        self.assertTrue(fact.can_promote_to(EvidenceKind.CLAIM))
        with self.assertRaises(ContractError):
            Evidence("x", EvidenceKind.CLAIM, 1.2, "bad")

    def test_task_scope_is_bounded_and_cancelable(self):
        scope = TaskScope("decode")
        scope.spawn(TaskSpec("draft", parent="decode"))
        scope.cancel()
        with self.assertRaises(ContractError):
            scope.spawn(TaskSpec("target", parent="decode"))
        self.assertEqual(scope.close(), ("draft",))
        self.assertEqual(scope.close(), ("draft",))

    def test_ownership_move_advances_generation(self):
        contract = OwnershipContract("kv", OwnershipMode.OWNED)
        moved = contract.moved()
        self.assertEqual(moved.generation, 1)
        self.assertEqual(moved.mode, OwnershipMode.OWNED)
        with self.assertRaises(ContractError):
            OwnershipContract("x", OwnershipMode.BORROW).moved()

    def test_task_and_supervisor_contracts(self):
        task = TaskSpec("decode", parent="root", priority=5, deadline_ms=50, capacity=4, effects=("model",))
        supervisor = SupervisorSpec("root", (task,), RestartPolicy.ONCE, max_restarts=2)
        self.assertEqual(supervisor.children[0].capacity, 4)
        with self.assertRaises(ContractError):
            TaskSpec("bad", capacity=0)
        with self.assertRaises(ContractError):
            SupervisorSpec("duplicate", (task, task))

    def test_kernel_specialization_key_is_deterministic(self):
        kernel = KernelContract("qkv", "int4", "neon", "row_major", "proof:q", 512, fallbacks=("int8", "f16"))
        first = kernel.specialization_key((1, 64)).digest()
        second = kernel.specialization_key((1, 64)).digest()
        different = kernel.specialization_key((1, 128)).digest()
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_kernel_contract_requires_proof_for_int4(self):
        missing = KernelContract("q", "int4", "neon", "row_major")
        self.assertFalse(missing.verify(available_memory=1024, allowed_effects=("model",)).is_ok)
        valid = KernelContract("q", "int4", "neon", "row_major", "proof:q", 512, required_effects=("model",))
        self.assertTrue(valid.verify(available_memory=1024, allowed_effects=("model",)).is_ok)
        self.assertFalse(valid.verify(available_memory=128, allowed_effects=("model",)).is_ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
