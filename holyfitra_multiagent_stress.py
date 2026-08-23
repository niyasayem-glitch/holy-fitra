#!/usr/bin/env python3
"""Bounded local neural multi-agent stress system for Holy Fitra.

The system is deliberately test-only.  Six deterministic sub-agent roles share
an authenticated compact neural scorer, exchange typed proposals in memory,
and reach consensus without network access, shell execution, source edits, or
publishing.  It is not an autonomous coding or deployment agent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from holyfitra_deploy import DeploymentBundle, export_mlp, load_deployment
from holyfitra_learning import TrainingConfig, TrainableMLP, train_supervised
from holyfitra_qat import QuantizationQualityGate, QuantizationSpec

ROLE_NAMES = ("planner", "researcher", "trainer", "reviewer", "verifier", "governor")
_PROHIBITED_TERMS = ("publish", "push", "network", "shell", "command", "write file", "delete", "payment")


class MultiAgentStressError(RuntimeError):
    """A bounded local coordination request was rejected or exceeded a limit."""


@dataclass(frozen=True)
class MultiAgentStressConfig:
    task_count: int = 192
    max_workers: int = 6
    work_iterations: int = 32
    max_task_bytes: int = 256
    max_elapsed_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 1 <= self.task_count <= 512:
            raise ValueError("task_count must be in [1, 512]")
        if not 1 <= self.max_workers <= len(ROLE_NAMES):
            raise ValueError("max_workers must not exceed the local role count")
        if not 1 <= self.work_iterations <= 128:
            raise ValueError("work_iterations must be in [1, 128]")
        if not 32 <= self.max_task_bytes <= 4096 or not np.isfinite(self.max_elapsed_seconds) or not 0.1 <= self.max_elapsed_seconds <= 120.0:
            raise ValueError("invalid local stress resource limits")


@dataclass(frozen=True)
class SubAgentProposal:
    task_id: int
    role: str
    decision: str
    neural_score: float
    evidence_digest: str
    side_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultiAgentStressReport:
    task_count: int
    proposal_count: int
    approved_tasks: int
    rejected_tasks: int
    elapsed_seconds: float
    proposals_per_second: float
    scorer_digest: str
    report_digest: str
    side_effects: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _feature_vector(task: str, role: str) -> np.ndarray:
    digest = hashlib.blake2b(f"holyfitra-local-agent:{role}:{task}".encode("utf-8"), digest_size=64).digest()
    values = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    return np.ascontiguousarray((values / 127.5 - 1.0).reshape(1, 64), dtype=np.float32)


def _teacher_dataset(rows: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    teacher = np.random.default_rng(911)
    inputs = rng.normal(size=(rows, 64)).astype(np.float32)
    first = teacher.normal(0.0, 1.0 / 8.0, size=(64, 128)).astype(np.float32)
    second = teacher.normal(0.0, 1.0 / np.sqrt(128), size=(128, 8)).astype(np.float32)
    return inputs, (np.maximum(inputs @ first, 0.0) @ second).astype(np.float32)


def _build_scorer(signing_key: bytes) -> tuple[DeploymentBundle, str]:
    inputs, targets = _teacher_dataset(2048, 71)
    model = TrainableMLP(64, 128, 8, seed=72)
    train_supervised(model, inputs, targets, config=TrainingConfig(epochs=8, batch_size=128, max_grad_norm=5.0, seed=73))
    gate = QuantizationQualityGate(max_mse=0.002, max_abs_error=0.08)
    with tempfile.TemporaryDirectory(prefix="holyfitra-multiagent-scorer-") as directory:
        path = Path(directory) / "scorer.hfbin"
        artifact = export_mlp(
            model,
            path,
            weight_spec=QuantizationSpec(bits=8, axis=0),
            quality_gate=gate,
            signing_key=signing_key,
            metadata={"purpose": "local_multi_agent_stress", "external_side_effects": False},
        )
        bundle = load_deployment(path, signing_key=signing_key)
    return bundle, artifact.digest


class LocalNeuralMultiAgentStress:
    """Read-only deterministic agent coordination with a shared local neural scorer."""

    def __init__(self, signing_key: bytes, config: MultiAgentStressConfig | None = None):
        self.config = config or MultiAgentStressConfig()
        self._scorer, self._scorer_digest = _build_scorer(signing_key)

    def _validate_task(self, task: str) -> str:
        if not isinstance(task, str) or not task.strip() or not task.isascii() or not task.isprintable() or len(task.encode("utf-8")) > self.config.max_task_bytes:
            raise MultiAgentStressError("agent task is empty or exceeds the byte budget")
        normalized = task.strip().casefold()
        compact = "".join(character for character in normalized if character.isalnum())
        if any(term in normalized or "".join(character for character in term if character.isalnum()) in compact for term in _PROHIBITED_TERMS):
            raise MultiAgentStressError("local stress agents refuse external or mutating actions")
        return normalized

    def _proposal(self, task_id: int, task: str, role: str) -> SubAgentProposal:
        vector = _feature_vector(task, role)
        for index in range(self.config.work_iterations):
            vector = np.tanh(vector + np.roll(vector, (index % 7) + 1, axis=1)).astype(np.float32)
        output = self._scorer.predict(vector)
        score = float(np.mean(output))
        evidence = hashlib.sha256(np.ascontiguousarray(output).tobytes() + role.encode("utf-8") + task.encode("utf-8")).hexdigest()
        decision = "approve" if score >= -0.25 else "reject"
        if role == "governor" and (not np.isfinite(score) or not evidence):
            decision = "reject"
        return SubAgentProposal(task_id, role, decision, score, evidence)

    def run(self, tasks: Iterable[str]) -> MultiAgentStressReport:
        iterator = iter(tasks)
        prepared_items: list[str] = []
        for _ in range(self.config.task_count + 1):
            try:
                task = next(iterator)
            except StopIteration:
                break
            prepared_items.append(self._validate_task(task))
        if not prepared_items or len(prepared_items) > self.config.task_count:
            raise MultiAgentStressError("task count is outside the configured local budget")
        prepared = tuple(prepared_items)
        started = time.perf_counter()
        jobs = ((task_id, task, role) for task_id, task in enumerate(prepared) for role in ROLE_NAMES)
        with ThreadPoolExecutor(max_workers=self.config.max_workers, thread_name_prefix="holyfitra-local-agent") as executor:
            proposals = tuple(executor.map(lambda job: self._proposal(*job), jobs))
        elapsed = time.perf_counter() - started
        if elapsed > self.config.max_elapsed_seconds:
            raise MultiAgentStressError("local multi-agent stress run exceeded the time budget")
        approved = 0
        for task_id in range(len(prepared)):
            group = [proposal for proposal in proposals if proposal.task_id == task_id]
            decisions = {proposal.role: proposal.decision for proposal in group}
            if len(group) != len(ROLE_NAMES) or any(proposal.side_effects for proposal in group):
                raise MultiAgentStressError("agent proposal policy violation")
            if decisions.get("verifier") == "approve" and decisions.get("governor") == "approve" and sum(item == "approve" for item in decisions.values()) >= 4:
                approved += 1
        canonical = [{"task_id": item.task_id, "role": item.role, "decision": item.decision, "neural_score": round(item.neural_score, 8), "evidence_digest": item.evidence_digest} for item in proposals]
        report_digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return MultiAgentStressReport(
            task_count=len(prepared),
            proposal_count=len(proposals),
            approved_tasks=approved,
            rejected_tasks=len(prepared) - approved,
            elapsed_seconds=elapsed,
            proposals_per_second=len(proposals) / elapsed,
            scorer_digest=self._scorer_digest,
            report_digest=report_digest,
            side_effects=(),
        )


def stress_tasks(count: int) -> tuple[str, ...]:
    return tuple(f"evaluate local neural coordination workload {index:04d}" for index in range(count))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded local-only Holy Fitra neural multi-agent stress test.")
    parser.add_argument("--task-count", type=int, default=192)
    parser.add_argument("--work-iterations", type=int, default=32)
    parser.add_argument("--signing-key-env", default="HOLY_FITRA_MULTI_AGENT_KEY")
    arguments = parser.parse_args()
    key = os.environ.get(arguments.signing_key_env)
    if key is None:
        raise SystemExit(f"missing signing key environment variable: {arguments.signing_key_env}")
    config = MultiAgentStressConfig(task_count=arguments.task_count, work_iterations=arguments.work_iterations)
    report = LocalNeuralMultiAgentStress(key.encode("utf-8"), config).run(stress_tasks(config.task_count))
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
