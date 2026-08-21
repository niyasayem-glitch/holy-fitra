#!/usr/bin/env python3
from __future__ import annotations

import time
import unittest

from holy_fitra_execution_plan import (
    CorePolicy,
    ExecutionReceipt,
    KernelCandidate,
    PlanCompiler,
    PlanConstraints,
    PlanError,
    Precision,
    Priority,
    Thermal,
    VerifiedPlanCache,
)


class ExecutionPlanTests(unittest.TestCase):
    def candidates(self):
        return [
            KernelCandidate("int4", Precision.INT4, 1, 0.08, 0.05, 12000, 0.7, proof_hash="p4"),
            KernelCandidate("int8", Precision.INT8, 1, 0.006, 0.05, 18000, 1.2, proof_hash="p8"),
            KernelCandidate("f16", Precision.F16, 1, 0.0, 0.05, 65000, 2.4, proof_hash="pf"),
        ]

    def test_quality_gate_falls_back_to_int8(self):
        plan = PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0))
        self.assertEqual(plan.precision, Precision.INT8)
        self.assertEqual(plan.fallbacks, ())
        plan.verify()

    def test_deterministic_plan_digest(self):
        compiler = PlanCompiler()
        constraints = PlanConstraints(0.05, 20000, 2.0, Thermal.NORMAL)
        a = compiler.compile(model_hash="m", candidates=self.candidates(), constraints=constraints, metadata={"shape": [4, 4]})
        b = compiler.compile(model_hash="m", candidates=self.candidates(), constraints=constraints, metadata={"shape": [4, 4]})
        self.assertEqual(a.plan_id, b.plan_id)
        self.assertEqual(a.canonical(), b.canonical())

    def test_tampered_plan_is_rejected(self):
        plan = PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0))
        object.__setattr__(plan, "memory_bytes", 1)
        with self.assertRaises(PlanError):
            plan.verify()

    def test_receipt_cannot_change_kernel_or_exceed_bound(self):
        plan = PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0))
        bad_kernel = ExecutionReceipt(plan.plan_id, plan.model_hash, "different", plan.precision, plan.core_policy, 0.001, plan.memory_bytes, 0.5, True, time.monotonic_ns())
        with self.assertRaises(PlanError):
            bad_kernel.verify_against(plan)
        bad_memory = ExecutionReceipt(plan.plan_id, plan.model_hash, plan.kernel_name, plan.precision, plan.core_policy, 0.001, plan.memory_bytes + 1, 0.5, True, time.monotonic_ns())
        with self.assertRaises(PlanError):
            bad_memory.verify_against(plan)
        bad_energy = ExecutionReceipt(plan.plan_id, plan.model_hash, plan.kernel_name, plan.precision, plan.core_policy, 0.001, plan.memory_bytes, plan.estimated_energy + 0.1, True, time.monotonic_ns())
        with self.assertRaises(PlanError):
            bad_energy.verify_against(plan)

    def test_native_request_fields_are_stable(self):
        plan = PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0))
        self.assertEqual(plan.native_request_fields(), {"core_class": 3, "priority": 3, "deadline_ns": 0})

    def test_critical_thermal_forbids_big_only(self):
        candidates = [KernelCandidate("big", Precision.INT8, 1, 0.01, 0.05, 100, 0.1, (CorePolicy.BIG_ONLY,), "pb")]
        with self.assertRaises(PlanError):
            PlanCompiler().compile(model_hash="m", candidates=candidates, constraints=PlanConstraints(0.05, 1000, 1.0, Thermal.CRITICAL, Priority.INTERACTIVE, allowed_cores=(CorePolicy.BIG_ONLY,)))

    def test_budget_refuses_all_candidates(self):
        with self.assertRaises(PlanError):
            PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 100, 0.1))

    def test_abi_refuses_mismatch(self):
        with self.assertRaises(PlanError):
            PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0, required_abi=2))

    def test_cache_revalidates_tamper(self):
        plan = PlanCompiler().compile(model_hash="m", candidates=self.candidates(), constraints=PlanConstraints(0.05, 20000, 2.0))
        cache = VerifiedPlanCache()
        cache.put(plan)
        object.__setattr__(plan, "kernel_name", "tampered")
        with self.assertRaises(PlanError):
            cache.get(plan.plan_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
