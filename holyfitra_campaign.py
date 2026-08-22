"""Supervised multi-provider coding campaign for Holy Fitra.

The campaign asks several configured providers for independent plans, compares
those plans deterministically, and never writes by default. Apply mode is
explicit, requires a high-risk branch, and reuses CodingAgent's confined
workspace, allowlisted validation, and transactional rollback contracts.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
from typing import Any, Callable, Mapping, Sequence

from holyfitra_ai_api import AIClient, AIConfigurationError, AIProviderError, provider_status_json
from holyfitra_agent import AgentError, AgentPlan, AgentPolicy, AgentRun, CodingAgent, Workspace


MAX_PROVIDERS = 6
MAX_ROUNDS = 20
MAX_WORKERS = 6
MAX_REPORT_BYTES = 2 * 1024 * 1024


class CampaignError(RuntimeError):
    """A campaign configuration or promotion decision was rejected."""


@dataclass(frozen=True)
class CampaignConfig:
    workspace: Path
    goal: str
    providers: tuple[str, ...] = ()
    models: Mapping[str, str] = None  # type: ignore[assignment]
    rounds: int = 3
    max_workers: int = 3
    min_consensus: int = 2
    apply: bool = False
    output: Path = Path(".holyfitra/campaign/latest.json")

    def __post_init__(self) -> None:
        root = self.workspace.expanduser().resolve()
        object.__setattr__(self, "workspace", root)
        object.__setattr__(self, "models", dict(self.models or {}))
        if not root.is_dir() or root in {Path("/"), Path.home().resolve()}:
            raise CampaignError("workspace must be an existing project directory, not home or root")
        if not self.goal or not self.goal.strip() or len(self.goal) > 4096:
            raise CampaignError("campaign goal must be between 1 and 4096 characters")
        names = tuple(dict.fromkeys(name.strip().lower() for name in self.providers if name.strip()))
        if len(names) > MAX_PROVIDERS:
            raise CampaignError(f"campaign supports at most {MAX_PROVIDERS} providers")
        object.__setattr__(self, "providers", names)
        if not 1 <= self.rounds <= MAX_ROUNDS:
            raise CampaignError(f"rounds must be between 1 and {MAX_ROUNDS}")
        if not 1 <= self.max_workers <= MAX_WORKERS:
            raise CampaignError(f"max_workers must be between 1 and {MAX_WORKERS}")
        if not 1 <= self.min_consensus <= MAX_PROVIDERS:
            raise CampaignError(f"min_consensus must be between 1 and {MAX_PROVIDERS}")
        output = Path(self.output)
        if output.is_absolute():
            try:
                output.relative_to(root)
            except ValueError as error:
                raise CampaignError("campaign output must remain inside the workspace") from error
        object.__setattr__(self, "output", output)

    def output_path(self) -> Path:
        path = self.output if self.output.is_absolute() else self.workspace / self.output
        path = path.resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise CampaignError("campaign output escapes workspace")
        return path

    def body(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "goal": self.goal,
            "providers": list(self.providers),
            "models": dict(self.models),
            "rounds": self.rounds,
            "max_workers": self.max_workers,
            "min_consensus": self.min_consensus,
            "apply": self.apply,
            "output": str(self.output),
        }


@dataclass(frozen=True)
class CampaignCandidate:
    provider: str
    model: str | None
    status: str
    plan: AgentPlan | None = None
    error: str = ""

    def body(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "plan": self.plan.body() if self.plan else None,
            "error": self.error,
        }

    def signature(self) -> tuple[Any, ...]:
        if not self.plan:
            return ()
        writes = tuple(sorted((action.path, action.content) for action in self.plan.actions if action.kind == "write_file"))
        checks = tuple(sorted(tuple(action.command) for action in self.plan.actions if action.kind == "run_check"))
        return writes, checks


@dataclass(frozen=True)
class CampaignRound:
    number: int
    candidates: tuple[CampaignCandidate, ...]
    selected_provider: str | None
    consensus: int
    run: AgentRun | None

    def body(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "candidates": [candidate.body() for candidate in self.candidates],
            "selected_provider": self.selected_provider,
            "consensus": self.consensus,
            "run": self.run.body() if self.run else None,
        }


class MultiAICampaign:
    """Generate and optionally apply bounded multi-provider coding plans."""

    def __init__(
        self,
        config: CampaignConfig,
        *,
        client: AIClient | None = None,
        agent_factory: Callable[[Workspace], CodingAgent] | None = None,
    ) -> None:
        self.config = config
        policy = AgentPolicy(allow_write=config.apply, allow_commands=config.apply, max_iterations=config.rounds)
        self.workspace = Workspace(config.workspace, policy)
        self.client = client or AIClient()
        self.agent = agent_factory(self.workspace) if agent_factory else CodingAgent(self.workspace, client=self.client)

    def available_providers(self) -> tuple[str, ...]:
        statuses = self.client.registry.statuses()
        if self.config.providers:
            known = {status.name for status in statuses}
            unknown = [name for name in self.config.providers if name not in known]
            if unknown:
                raise AIConfigurationError(f"unknown campaign provider(s): {', '.join(unknown)}")
            return self.config.providers
        configured = tuple(status.name for status in statuses if status.configured)
        if not configured:
            raise AIConfigurationError("no configured AI provider is available for the campaign")
        return configured[:MAX_PROVIDERS]

    def status(self) -> dict[str, Any]:
        return {"providers": provider_status_json(self.client.registry), "campaign": self.config.body()}

    def ensure_apply_branch(self) -> None:
        if not self.config.apply:
            return
        try:
            branch = subprocess.run(
                ["git", "-C", str(self.config.workspace), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise CampaignError("apply mode requires a Git workspace on a high-risk branch") from error
        if not branch.startswith("high-risk/"):
            raise CampaignError(f"apply mode is restricted to high-risk/* branches; current branch is {branch or 'unknown'}")

    def _candidate(self, provider: str) -> CampaignCandidate:
        model = self.config.models.get(provider) or None
        try:
            plan = self.agent.build_plan(self.config.goal, provider=provider, model=model)
            if not any(action.kind == "run_check" for action in plan.actions):
                return CampaignCandidate(provider, model, "rejected", plan, "plan does not include a validation command")
            return CampaignCandidate(provider, model, "ready", plan)
        except (AgentError, AIConfigurationError, AIProviderError, OSError) as error:
            return CampaignCandidate(provider, model, "error", None, str(error))

    def generate_candidates(self, providers: Sequence[str]) -> tuple[CampaignCandidate, ...]:
        candidates: list[CampaignCandidate] = []
        workers = min(self.config.max_workers, len(providers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._candidate, provider): provider for provider in providers}
            for future in as_completed(futures):
                candidates.append(future.result())
        return tuple(sorted(candidates, key=lambda candidate: candidate.provider))

    def select_consensus(self, candidates: Sequence[CampaignCandidate]) -> tuple[CampaignCandidate | None, int]:
        ready = [candidate for candidate in candidates if candidate.status == "ready" and candidate.plan]
        if not ready:
            return None, 0
        groups: dict[tuple[Any, ...], list[CampaignCandidate]] = {}
        for candidate in ready:
            groups.setdefault(candidate.signature(), []).append(candidate)
        ranked = sorted(groups.values(), key=lambda group: (-len(group), tuple(item.provider for item in group)))
        winner = ranked[0]
        required = min(self.config.min_consensus, len({candidate.provider for candidate in ready}))
        if len(winner) < required:
            return None, len(winner)
        return winner[0], len(winner)

    def run(self) -> dict[str, Any]:
        self.ensure_apply_branch()
        providers = self.available_providers()
        rounds: list[CampaignRound] = []
        for number in range(1, self.config.rounds + 1):
            candidates = self.generate_candidates(providers)
            selected, consensus = self.select_consensus(candidates)
            run: AgentRun | None = None
            if self.config.apply and selected and selected.plan:
                run = self.agent.apply_plan(self.config.goal, selected.plan)
            rounds.append(CampaignRound(number, candidates, selected.provider if selected else None, consensus, run))
            if run and run.status != "applied":
                break
        report = {
            "schema": "holyfitra.multi-ai-campaign/v1",
            "config": self.config.body(),
            "provider_status": provider_status_json(self.client.registry),
            "rounds": [item.body() for item in rounds],
            "summary": {
                "requested_rounds": self.config.rounds,
                "completed_rounds": len(rounds),
                "ready_candidates": sum(candidate.status == "ready" for item in rounds for candidate in item.candidates),
                "errors": sum(candidate.status == "error" for item in rounds for candidate in item.candidates),
                "selected_rounds": sum(item.selected_provider is not None for item in rounds),
                "applied_rounds": sum(item.run is not None and item.run.status == "applied" for item in rounds),
                "rolled_back_rounds": sum(item.run is not None and item.run.rolled_back for item in rounds),
                "claims": [
                    "Provider proposals are model output and are not trusted as execution authority.",
                    "Plan-only mode makes no workspace changes.",
                    "Apply mode requires a high-risk/* Git branch and uses transactional rollback.",
                    "Host/CI validation is not Android ARM64 device evidence.",
                ],
            },
        }
        self.write_report(report)
        return report

    def write_report(self, report: Mapping[str, Any]) -> None:
        output = self.config.output_path()
        payload = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
        if len(payload.encode("utf-8")) > MAX_REPORT_BYTES:
            raise CampaignError("campaign report exceeds the safety limit")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, output)


def load_campaign_config(path: str | os.PathLike[str], *, workspace: Path | None = None, goal: str | None = None, apply: bool | None = None) -> CampaignConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CampaignError(f"cannot read campaign config: {config_path}") from error
    values = document.get("campaign", document)
    if not isinstance(values, dict):
        raise CampaignError("campaign config must contain a [campaign] table")
    raw_workspace = Path(workspace or values.get("workspace", ".")).expanduser()
    root = raw_workspace if raw_workspace.is_absolute() else config_path.parent / raw_workspace
    providers = values.get("providers", ())
    if isinstance(providers, str):
        providers = tuple(item.strip() for item in providers.split(",") if item.strip())
    if not isinstance(providers, (list, tuple)) or any(not isinstance(item, str) for item in providers):
        raise CampaignError("campaign providers must be a list of names")
    models = document.get("models", values.get("models", {}))
    if not isinstance(models, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in models.items()):
        raise CampaignError("campaign models must be a provider-to-model string map")
    return CampaignConfig(
        workspace=root,
        goal=str(goal if goal is not None else values.get("goal", "")),
        providers=tuple(providers),
        models=models,
        rounds=int(values.get("rounds", 3)),
        max_workers=int(values.get("max_workers", 3)),
        min_consensus=int(values.get("min_consensus", 2)),
        apply=bool(apply if apply is not None else values.get("apply", False)),
        output=Path(str(values.get("output", ".holyfitra/campaign/latest.json"))),
    )


__all__ = ["CampaignCandidate", "CampaignConfig", "CampaignError", "CampaignRound", "MultiAICampaign", "load_campaign_config"]
