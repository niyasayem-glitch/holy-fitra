#!/usr/bin/env python3
"""Evidence-grounded local agent runtime for Holy Fitra."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

import numpy as np


class EvidenceKind(str, Enum):
    FACT = "fact"
    CLAIM = "claim"
    PREDICTION = "prediction"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    content: str
    confidence: float
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.content or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("invalid evidence record")
        if self.kind != EvidenceKind.PREDICTION and not self.provenance:
            raise ValueError("facts and claims require provenance")


class EvidenceLedger:
    """Append-only evidence store with monotonic confidence updates."""

    def __init__(self) -> None:
        self._records: dict[str, Evidence] = {}

    def add(self, evidence: Evidence) -> Evidence:
        previous = self._records.get(evidence.evidence_id)
        if previous is not None:
            if previous.kind != evidence.kind or previous.content != evidence.content or evidence.confidence < previous.confidence or not set(previous.provenance).issubset(evidence.provenance):
                raise ValueError("evidence update violates monotonicity")
        self._records[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> Evidence:
        return self._records[evidence_id]

    @property
    def records(self) -> tuple[Evidence, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


@dataclass(frozen=True)
class MemoryDocument:
    document_id: str
    text: str
    vector: tuple[float, ...]
    provenance: tuple[str, ...]
    kind: EvidenceKind = EvidenceKind.FACT

    def __post_init__(self) -> None:
        if not self.document_id or not self.text or not self.vector or not self.provenance:
            raise ValueError("invalid memory document")
        if self.kind == EvidenceKind.PREDICTION:
            raise ValueError("retrieval documents cannot be predictions")


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    score: float
    text: str
    provenance: tuple[str, ...]
    kind: EvidenceKind


class VectorMemory:
    """Small deterministic cosine-similarity memory index."""

    def __init__(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("memory dimension must be positive")
        self.dimension = int(dimension)
        self._documents: dict[str, MemoryDocument] = {}

    def add(self, document: MemoryDocument) -> None:
        vector = np.asarray(document.vector, dtype=np.float32)
        if vector.shape != (self.dimension,) or not np.all(np.isfinite(vector)) or float(np.linalg.norm(vector)) == 0.0:
            raise ValueError("document vector does not match memory dimension")
        if document.document_id in self._documents:
            raise ValueError("duplicate document id")
        self._documents[document.document_id] = document

    def search(self, query: Iterable[float], *, top_k: int = 4, min_score: float = -1.0) -> tuple[RetrievalHit, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        vector = np.asarray(tuple(query), dtype=np.float32)
        if vector.shape != (self.dimension,) or not np.all(np.isfinite(vector)):
            raise ValueError("query vector does not match memory dimension")
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("query vector must be non-zero")
        scored: list[RetrievalHit] = []
        for document_id, document in self._documents.items():
            candidate = np.asarray(document.vector, dtype=np.float32)
            score = float(np.dot(vector, candidate) / (norm * np.linalg.norm(candidate)))
            if score >= min_score:
                scored.append(RetrievalHit(document_id, score, document.text, document.provenance, document.kind))
        scored.sort(key=lambda hit: (-hit.score, hit.document_id))
        return tuple(scored[:top_k])


@dataclass(frozen=True)
class ToolResult:
    content: str
    evidence_kind: EvidenceKind = EvidenceKind.CLAIM
    confidence: float = 0.5
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required_capability: str
    handler: Callable[[dict[str, Any]], ToolResult]
    validator: Callable[[dict[str, Any]], bool] = lambda _args: True


class CapabilityError(PermissionError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not spec.required_capability or spec.name in self._tools:
            raise ValueError("invalid or duplicate tool specification")
        self._tools[spec.name] = spec

    def invoke(self, name: str, arguments: dict[str, Any], *, grants: frozenset[str]) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        if spec.required_capability not in grants:
            raise CapabilityError(f"capability denied: {spec.required_capability}")
        if not spec.validator(arguments):
            raise ValueError(f"tool arguments rejected: {name}")
        result = spec.handler(dict(arguments))
        if not isinstance(result, ToolResult):
            raise TypeError("tool handlers must return ToolResult")
        return result


@dataclass(frozen=True)
class AgentAction:
    kind: str
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    step: int
    event: str
    detail: str


@dataclass(frozen=True)
class AgentResult:
    status: str
    evidence: tuple[Evidence, ...]
    trace: tuple[AuditEvent, ...]


class AgentRuntime:
    """Bounded retrieve/tool loop with cancellation and evidence auditing."""

    def __init__(self, memory: VectorMemory, tools: ToolRegistry, *, max_steps: int = 8) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.memory = memory
        self.tools = tools
        self.max_steps = int(max_steps)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self, query_vector: Iterable[float], actions: Iterable[AgentAction], *, grants: frozenset[str] = frozenset(), top_k: int = 4) -> AgentResult:
        self._cancelled = False
        ledger = EvidenceLedger()
        trace: list[AuditEvent] = []
        action_list = tuple(actions)
        if len(action_list) > self.max_steps:
            raise ValueError("agent plan exceeds step budget")
        for step, action in enumerate(action_list, start=1):
            if self._cancelled:
                trace.append(AuditEvent(step, "cancelled", "execution cancelled before action"))
                return AgentResult("cancelled", ledger.records, tuple(trace))
            if action.kind == "retrieve":
                hits = self.memory.search(query_vector, top_k=top_k)
                for hit in hits:
                    ledger.add(Evidence(f"memory:{hit.document_id}", hit.kind, hit.text, max(0.0, min(1.0, (hit.score + 1.0) / 2.0)), hit.provenance))
                trace.append(AuditEvent(step, "retrieve", f"hits={len(hits)}"))
            elif action.kind == "tool":
                result = self.tools.invoke(action.name, action.arguments, grants=grants)
                evidence_id = f"tool:{step}:{action.name}"
                ledger.add(Evidence(evidence_id, result.evidence_kind, result.content, result.confidence, result.provenance or (f"tool:{action.name}",)))
                trace.append(AuditEvent(step, "tool", action.name))
            else:
                raise ValueError(f"unknown agent action: {action.kind}")
        return AgentResult("completed", ledger.records, tuple(trace))


__all__ = ["AgentAction", "AgentResult", "AgentRuntime", "AuditEvent", "CapabilityError", "Evidence", "EvidenceKind", "EvidenceLedger", "MemoryDocument", "RetrievalHit", "ToolRegistry", "ToolResult", "ToolSpec", "VectorMemory"]
