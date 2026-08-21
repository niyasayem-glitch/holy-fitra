#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from hyperc_adaptive_speculative import AdaptiveSpeculativeDecoder, AdaptiveSpeculativePolicy, ThermalState
from hyperc_hyperir import (
    Capability,
    CapabilityPolicy,
    EvidenceKind,
    EvidenceType,
    HyperIR,
    HyperIRError,
    Operation,
    QuantizationProof,
    TensorType,
    Value,
    demo_ir,
)
from hyperc_speculative import SpeculativePlan, make_models, standard_generate
from hyperc_proof_quant import select_matrix


class HyperIRTests(unittest.TestCase):
    def test_tensor_validation_and_lowering(self):
        with self.assertRaises(HyperIRError):
            TensorType((0, 4))
        with self.assertRaises(HyperIRError):
            TensorType((4, 4), "fp8")
        ir = demo_ir()
        self.assertEqual(ir.verify(), [])
        self.assertEqual(ir.lower_plan()[0]["kernel"], "neon.nibble_dot")

    def test_matmul_shape_error_is_reported(self):
        ir = HyperIR("bad")
        ir.add_value(Value("a", "Tensor", TensorType((1, 4), "f16", "neon")))
        ir.add_value(Value("b", "Tensor", TensorType((3, 4), "int4", "neon")))
        op = Operation("matmul", ("a", "b"), ("c",))
        ir.add_operation(op)
        ir.add_output_value(op, Value("c", "Tensor", TensorType((1, 4), "int4", "neon")))
        self.assertTrue(any("incompatible matmul" in error for error in ir.verify()))

    def test_evidence_flow(self):
        prediction = EvidenceType(EvidenceKind.PREDICTION, "String", 0.8)
        claim = EvidenceType(EvidenceKind.CLAIM, "String", sources=("source:a",))
        fact = EvidenceType(EvidenceKind.FACT, "String", sources=("source:a", "verifier:b"))
        self.assertTrue(fact.can_flow_to(claim))
        self.assertFalse(prediction.can_flow_to(fact))
        self.assertTrue(claim.can_flow_to(claim))

    def test_capability_policy_deny_overrides_allow(self):
        policy = CapabilityPolicy(
            allow=[Capability("files", "read", "/public/")],
            deny=[Capability("files", "read", "/public/secrets/")],
        )
        self.assertTrue(policy.authorize(Capability("files", "read", "/public/a.txt")))
        self.assertFalse(policy.authorize(Capability("files", "read", "/public/secrets/a.txt")))
        self.assertFalse(policy.authorize(Capability("files", "write", "/public/a.txt")))

    def test_quantization_proof_pass_fail(self):
        passing = QuantizationProof("m", "sha", "int4", 4, 0.01, 0.95, 0.96, 0.02, 0.94, "neon.nibble_dot", "android.arm64")
        failing = copy.deepcopy(passing)
        failing.layer_error = 0.03
        self.assertTrue(passing.verify())
        self.assertFalse(failing.verify())
        self.assertFalse(failing.verified)

    def test_cache_transaction_contracts(self):
        ir = HyperIR("cache")
        begin = Operation("cache_begin", (), (), {"cache_id": "kv"})
        append = Operation("cache_append", (), (), {"cache_id": "kv"}, frozenset({"cache.write"}))
        commit = Operation("cache_commit", (), (), {"cache_id": "kv"})
        for operation in (begin, append, commit):
            ir.add_operation(operation)
        self.assertEqual(ir.verify(), [])
        bad = HyperIR("bad_cache")
        bad.add_operation(Operation("cache_append", (), (), {"cache_id": "kv"}, frozenset({"cache.write"})))
        self.assertTrue(any("open transaction" in error for error in bad.verify()))

    def test_tool_proposal_requires_policy(self):
        ir = HyperIR("safe")
        proposal = Value("p", "Prediction", evidence=EvidenceType(EvidenceKind.PREDICTION, "String"))
        op = Operation("tool_propose", (), ("p",), {"policy": "none", "resource": "network", "operation": "post"}, frozenset({"tool.propose"}))
        ir.add_operation(op)
        ir.add_output_value(op, proposal)
        self.assertTrue(any("not authorized" in error for error in ir.verify()))

    def test_digest_stability(self):
        first = demo_ir().digest()
        second = demo_ir().digest()
        self.assertEqual(first, second)

    def test_proof_selector_selects_int4_when_gate_passes(self):
        import numpy as np
        rng = np.random.default_rng(7)
        weight = rng.normal(0.0, 0.2, size=(16, 16)).astype(np.float32)
        calibration = rng.normal(size=(32, 16)).astype(np.float32)
        _, candidate, proof = select_matrix(weight, calibration, model="m", layer="q", max_layer_error=0.2)
        self.assertEqual(candidate.precision, "int4")
        self.assertTrue(proof.verified)

    def test_proof_selector_falls_back_to_int8(self):
        import numpy as np
        rng = np.random.default_rng(19)
        weight = rng.normal(0.0, 0.8, size=(16, 16)).astype(np.float32)
        calibration = rng.normal(size=(64, 16)).astype(np.float32)
        _, candidate, proof = select_matrix(weight, calibration, model="m", layer="sensitive", max_layer_error=0.001)
        self.assertIn(candidate.precision, {"int8", "f16"})
        self.assertTrue(proof.verified)

    def test_proof_selector_can_refuse_all_candidates(self):
        import numpy as np
        rng = np.random.default_rng(19)
        weight = rng.normal(0.0, 0.8, size=(16, 16)).astype(np.float32)
        calibration = rng.normal(size=(64, 16)).astype(np.float32)
        with self.assertRaises(RuntimeError):
            select_matrix(weight, calibration, model="m", layer="blocked", max_layer_error=0.0)

    def test_adaptive_policy_increases_and_thermal_clamps(self):
        policy = AdaptiveSpeculativePolicy(draft_k=2, k_max=8, target_acceptance=0.5, gain=3.0)
        self.assertGreater(policy.update(4, 0, ThermalState("cool")), 2)
        self.assertEqual(policy.update(4, 0, ThermalState("critical")), 1)

    def test_adaptive_decoder_preserves_greedy_output(self):
        draft, target = make_models(vocab=24, seed=41)
        plan = SpeculativePlan(draft_k=3, mode="greedy")
        decoder = AdaptiveSpeculativeDecoder(draft, target, plan, policy=AdaptiveSpeculativePolicy(draft_k=3, k_max=6), max_tokens=128)
        decoder.cache.tokens = [0]
        expected = standard_generate(target, [0], 48)
        actual = decoder.generate(48)
        self.assertEqual(actual, expected)
        self.assertTrue(all(1 <= int(row["draft_k"]) <= 6 for row in decoder.history))
        self.assertEqual(len(decoder.cache.tokens), 1 + 48)


if __name__ == "__main__":
    unittest.main(verbosity=2)
