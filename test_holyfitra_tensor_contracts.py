from __future__ import annotations

import unittest

from holy_fitra_execution_plan import CorePolicy, KernelCandidate, PlanCompiler, PlanConstraints, Precision
from holyfitra_tensor_contracts import TensorContract, TensorContractError, TensorResourceContract


class TensorContractTests(unittest.TestCase):
    def test_contract_canonicalizes_tensor_storage_and_accepts_matching_plan(self):
        contract = TensorResourceContract((TensorContract("input", (1, 64), "f32", device="neon"), TensorContract("weights", (64, 128), "int8", device="neon")), memory_budget_bytes=16_384, max_energy=2.0)
        candidate = KernelCandidate("contract.int8", Precision.INT8, 1, 0.0, 1.0, 12_000, 1.0, (CorePolicy.ANY,), "proof:contract")
        plan = PlanCompiler().compile(model_hash="a" * 64, candidates=(candidate,), constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=16_384, energy_budget=2.0))
        contract.verify_plan(plan)
        self.assertEqual(contract.digest(), TensorResourceContract((TensorContract("input", (1, 64), "f32", device="neon"), TensorContract("weights", (64, 128), "int8", device="neon")), memory_budget_bytes=16_384, max_energy=2.0).digest())

    def test_contract_rejects_over_budget_storage_and_plan(self):
        with self.assertRaises(TensorContractError):
            TensorResourceContract((TensorContract("weights", (64, 128), "f32"),), memory_budget_bytes=4)
        contract = TensorResourceContract((TensorContract("input", (1, 2), "f32"),), memory_budget_bytes=128)
        candidate = KernelCandidate("too-large", Precision.INT8, 1, 0.0, 1.0, 129, 1.0, (CorePolicy.ANY,), "proof:large")
        plan = PlanCompiler().compile(model_hash="b" * 64, candidates=(candidate,), constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=256, energy_budget=2.0))
        with self.assertRaises(TensorContractError):
            contract.verify_plan(plan)
