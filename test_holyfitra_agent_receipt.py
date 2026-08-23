from __future__ import annotations

import unittest

from holyfitra_agent_receipt import AgentApproval, AgentBudget, AgentEvidence, AgentPlanReceipt, AgentReceiptError


class AgentReceiptTests(unittest.TestCase):
    def test_canonical_receipt_binds_capability_evidence_budget_and_approval(self):
        digest = "a" * 64
        receipt = AgentPlanReceipt(("model.predict.local",), AgentBudget(2, 12, 4, 1000), (AgentEvidence("scorer", digest), AgentEvidence("proposals", digest)), (AgentApproval("verifier", 2), AgentApproval("governor", 2)), digest)
        self.assertEqual(receipt.digest(), AgentPlanReceipt(("model.predict.local",), AgentBudget(2, 12, 4, 1000), (AgentEvidence("scorer", digest), AgentEvidence("proposals", digest)), (AgentApproval("verifier", 2), AgentApproval("governor", 2)), digest).digest())

    def test_receipt_rejects_ungranted_capability_or_side_effect(self):
        digest = "b" * 64
        with self.assertRaises(AgentReceiptError):
            AgentPlanReceipt(("files.write",), AgentBudget(1, 6, 1, 1000), (AgentEvidence("scorer", digest), AgentEvidence("proposals", digest)), (AgentApproval("verifier", 0), AgentApproval("governor", 0)), digest)
        with self.assertRaises(AgentReceiptError):
            AgentPlanReceipt(("model.predict.local",), AgentBudget(1, 6, 1, 1000), (AgentEvidence("scorer", digest), AgentEvidence("proposals", digest)), (AgentApproval("verifier", 0), AgentApproval("governor", 0)), digest, ("write",))
