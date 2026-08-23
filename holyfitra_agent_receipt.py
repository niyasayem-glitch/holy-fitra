#!/usr/bin/env python3
"""Typed, canonical receipts for bounded Holy Fitra agent-plan execution."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class AgentReceiptError(ValueError):
    """An agent receipt violates a capability, evidence, budget, or approval contract."""


def _digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True)
class AgentBudget:
    task_limit: int
    proposal_limit: int
    work_iteration_limit: int
    elapsed_limit_ms: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (self.task_limit, self.proposal_limit, self.work_iteration_limit, self.elapsed_limit_ms)):
            raise AgentReceiptError("agent budget fields must be positive integers")

    def body(self) -> dict[str, int]:
        return {"task_limit": self.task_limit, "proposal_limit": self.proposal_limit, "work_iteration_limit": self.work_iteration_limit, "elapsed_limit_ms": self.elapsed_limit_ms}


@dataclass(frozen=True)
class AgentEvidence:
    kind: str
    digest: str

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.isascii() or not _digest(self.digest):
            raise AgentReceiptError("agent evidence identity is invalid")

    def body(self) -> dict[str, str]:
        return {"kind": self.kind, "digest": self.digest}


@dataclass(frozen=True)
class AgentApproval:
    role: str
    approved_tasks: int

    def __post_init__(self) -> None:
        if self.role not in {"verifier", "governor"} or not isinstance(self.approved_tasks, int) or self.approved_tasks < 0:
            raise AgentReceiptError("agent approval is invalid")

    def body(self) -> dict[str, object]:
        return {"role": self.role, "approved_tasks": self.approved_tasks}


@dataclass(frozen=True)
class AgentPlanReceipt:
    capabilities: tuple[str, ...]
    budget: AgentBudget
    evidence: tuple[AgentEvidence, ...]
    approvals: tuple[AgentApproval, ...]
    proposal_digest: str
    side_effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.capabilities != ("model.predict.local",) or not _digest(self.proposal_digest) or self.side_effects:
            raise AgentReceiptError("agent receipt capabilities, proposal identity, or side effects are invalid")
        if len({item.kind for item in self.evidence}) != len(self.evidence) or tuple(item.role for item in self.approvals) != ("verifier", "governor"):
            raise AgentReceiptError("agent receipt evidence or approval order is invalid")

    def body(self) -> dict[str, object]:
        return {
            "schema": "holyfitra.agent-plan-receipt/v1",
            "capabilities": list(self.capabilities),
            "budget": self.budget.body(),
            "evidence": [item.body() for item in self.evidence],
            "approvals": [item.body() for item in self.approvals],
            "proposal_digest": self.proposal_digest,
            "side_effects": [],
        }

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = ["AgentApproval", "AgentBudget", "AgentEvidence", "AgentPlanReceipt", "AgentReceiptError"]
