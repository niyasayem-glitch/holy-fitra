#!/usr/bin/env python3
from __future__ import annotations
import itertools
import unittest
from holyfitra_ai_system import AgentAction, AgentRuntime, CapabilityError, ClaimVerifier, Evidence, EvidenceKind, EvidenceLedger, MemoryDocument, ToolRegistry, ToolResult, ToolSpec, VectorMemory, VerificationStatus


class HolyFitraAISystemTests(unittest.TestCase):
    def setUp(self):
        self.memory = VectorMemory(3)
        self.memory.add(MemoryDocument("fact-a", "ARM64 uses compact tensor buffers.", (1.0, 0.0, 0.0), ("runtime-doc",)))
        self.memory.add(MemoryDocument("fact-b", "Replay reduces forgetting.", (0.0, 1.0, 0.0), ("learning-doc",)))
        self.tools = ToolRegistry()
        self.tools.register(ToolSpec("safe_echo", "cap.echo", lambda args: ToolResult(args["text"], EvidenceKind.CLAIM, 0.8, ("echo",)), lambda args: isinstance(args.get("text"), str) and len(args["text"]) <= 64))

    def test_retrieval_is_deterministic_and_provenance_preserved(self):
        hits = self.memory.search((1.0, 0.0, 0.0), top_k=2)
        self.assertEqual(hits[0].document_id, "fact-a")
        self.assertEqual(hits[0].provenance, ("runtime-doc",))
        self.assertGreater(hits[0].score, hits[1].score)

    def test_evidence_confidence_is_monotonic(self):
        ledger = EvidenceLedger()
        ledger.add(Evidence("e", EvidenceKind.CLAIM, "bounded", 0.4, ("test",)))
        ledger.add(Evidence("e", EvidenceKind.CLAIM, "bounded", 0.8, ("test", "more")))
        with self.assertRaises(ValueError):
            ledger.add(Evidence("e", EvidenceKind.CLAIM, "bounded", 0.2, ("test",)))
        with self.assertRaises(ValueError):
            ledger.add(Evidence("e", EvidenceKind.CLAIM, "changed", 0.9, ("test", "more")))

    def test_capability_scoped_tool_invocation(self):
        with self.assertRaises(CapabilityError):
            self.tools.invoke("safe_echo", {"text": "hello"}, grants=frozenset())
        result = self.tools.invoke("safe_echo", {"text": "hello"}, grants=frozenset({"cap.echo"}))
        self.assertEqual(result.content, "hello")

    def test_agent_retrieves_and_calls_only_granted_tools(self):
        runtime = AgentRuntime(self.memory, self.tools, max_steps=3)
        result = runtime.run((1.0, 0.0, 0.0), (AgentAction("retrieve"), AgentAction("tool", "safe_echo", {"text": "ok"})), grants=frozenset({"cap.echo"}))
        self.assertEqual(result.status, "completed")
        self.assertEqual([event.event for event in result.trace], ["retrieve", "claim_verification", "tool"])
        self.assertTrue(any(e.evidence_id == "memory:fact-a" for e in result.evidence))
        self.assertTrue(any(e.evidence_id == "tool:2:safe_echo" for e in result.evidence))

    def test_agent_plan_budget_bounds_unbounded_iterators(self):
        runtime = AgentRuntime(self.memory, self.tools, max_steps=2)
        with self.assertRaises(ValueError):
            runtime.run((1.0, 0.0, 0.0), (AgentAction("retrieve") for _ in itertools.count()))

    def test_tool_registry_rejects_malformed_argument_contracts(self):
        with self.assertRaises(ValueError):
            self.tools.invoke("safe_echo", [], grants=frozenset({"cap.echo"}))
        with self.assertRaises(ValueError):
            self.tools.invoke("safe_echo", {}, grants={"cap.echo"})

    def test_agent_plan_budget_and_cancellation(self):
        runtime = AgentRuntime(self.memory, self.tools, max_steps=1)
        with self.assertRaises(ValueError):
            runtime.run((1.0, 0.0, 0.0), (AgentAction("retrieve"), AgentAction("retrieve")))
        runtime = AgentRuntime(self.memory, self.tools, max_steps=2)
        cancelling_tools = ToolRegistry()
        cancelling_tools.register(ToolSpec("cancel", "cap.cancel", lambda _args: (runtime.cancel() or ToolResult("cancelled"))))
        runtime.tools = cancelling_tools
        result = runtime.run((1.0, 0.0, 0.0), (AgentAction("tool", "cancel"), AgentAction("retrieve")), grants=frozenset({"cap.cancel"}))
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.trace[-1].event, "cancelled")

    def test_claim_verifier_classifies_support_and_contradiction(self):
        ledger = EvidenceLedger()
        ledger.add(Evidence("f", EvidenceKind.FACT, "cache uses shared tensor memory", 0.95, ("doc",)))
        verifier = ClaimVerifier(min_confidence=0.6, min_overlap=0.5)
        supported = verifier.verify("shared tensor memory uses cache", ledger, evidence_ids=("f",))
        self.assertEqual(supported.status, VerificationStatus.SUPPORTED)
        contradicted = verifier.verify("cache does not use shared tensor memory", ledger, evidence_ids=("f",))
        self.assertEqual(contradicted.status, VerificationStatus.CONTRADICTED)
        unsupported = verifier.verify("scheduler uses external network", ledger)
        self.assertEqual(unsupported.status, VerificationStatus.UNSUPPORTED)

    def test_low_confidence_fact_cannot_authorize_tool_claim(self):
        ledger = EvidenceLedger()
        ledger.add(Evidence("weak", EvidenceKind.FACT, "tool is safe", 0.2, ("untrusted",)))
        verifier = ClaimVerifier(min_confidence=0.6)
        result = verifier.verify("tool is safe", ledger, evidence_ids=("weak",))
        self.assertEqual(result.status, VerificationStatus.UNSUPPORTED)

    def test_pre_tool_verifier_blocks_unsupported_claim(self):
        runtime = AgentRuntime(self.memory, self.tools, max_steps=2, verifier=ClaimVerifier(min_overlap=0.5), require_claims=True)
        blocked = runtime.run((1.0, 0.0, 0.0), (AgentAction("retrieve"), AgentAction("tool", "safe_echo", {"text": "blocked"}, claim="external network is authorized")), grants=frozenset({"cap.echo"}))
        self.assertEqual(blocked.status, "blocked_claim")
        self.assertEqual(blocked.trace[-1].event, "claim_verification")
        self.assertNotIn("tool", [event.event for event in blocked.trace])

    def test_pre_tool_verifier_allows_supported_claim(self):
        runtime = AgentRuntime(self.memory, self.tools, max_steps=2, verifier=ClaimVerifier(min_overlap=0.5), require_claims=True)
        allowed = runtime.run((1.0, 0.0, 0.0), (AgentAction("retrieve"), AgentAction("tool", "safe_echo", {"text": "allowed"}, claim="ARM64 uses compact tensor buffers", evidence_ids=("memory:fact-a",))), grants=frozenset({"cap.echo"}))
        self.assertEqual(allowed.status, "completed")
        self.assertEqual([event.event for event in allowed.trace], ["retrieve", "claim_verification", "tool"])

    def test_prediction_can_exist_without_provenance_but_fact_cannot(self):
        Evidence("p", EvidenceKind.PREDICTION, "likely", 0.5, ())
        with self.assertRaises(ValueError):
            Evidence("f", EvidenceKind.FACT, "fact", 0.9, ())

    def test_evidence_and_verifier_reject_nonfinite_numbers(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                Evidence("nonfinite", EvidenceKind.PREDICTION, "uncertain", value, ())
            with self.assertRaises(ValueError):
                ClaimVerifier(min_confidence=value)
            with self.assertRaises(ValueError):
                ClaimVerifier(min_overlap=value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
