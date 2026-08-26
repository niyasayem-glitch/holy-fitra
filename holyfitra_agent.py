"""Supervised AI coding agent for Holy Fitra projects.

The agent is deliberately transactional: model output is a proposal, file writes
are confined to the selected project, commands are allowlisted, and a failed
validation restores the pre-change files. It never grants the model a shell,
network, credential, or unrestricted filesystem capability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

from holyfitra_ai_api import AIClient, AIConfigurationError, AIProviderError


MAX_CONTEXT_BYTES = 256 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_PLAN_BYTES = 512 * 1024
MAX_COMMAND_OUTPUT = 32 * 1024
DENIED_NAMES = frozenset({".env", ".env.local", ".env.production", ".env.development", "hd.providers.env", "id_rsa", "id_ed25519"})
DENIED_SUFFIXES = (".hfhd-plan.json",)
DENIED_PARTS = frozenset({".git", ".hg", ".svn", "__pycache__", ".venv", "node_modules"})


class AgentError(RuntimeError):
    """A coding-agent request was rejected or failed safely."""


@dataclass(frozen=True)
class AgentPolicy:
    max_steps: int = 12
    max_file_bytes: int = MAX_FILE_BYTES
    command_timeout_seconds: float = 60.0
    allow_write: bool = False
    allow_commands: bool = False
    require_tests_after_write: bool = True
    max_iterations: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 64:
            raise AgentError("max_steps must be between 1 and 64")
        if not 1024 <= self.max_file_bytes <= 4 * 1024 * 1024:
            raise AgentError("max_file_bytes must be between 1 KiB and 4 MiB")
        if not 0.1 <= self.command_timeout_seconds <= 600.0:
            raise AgentError("command_timeout_seconds must be between 0.1 and 600")
        if not 1 <= self.max_iterations <= 20:
            raise AgentError("max_iterations must be between 1 and 20")


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    status: int
    stdout: str
    stderr: str
    elapsed_ms: float
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.status == 0 and not self.timed_out

    def body(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "status": self.status,
            "stdout": self.stdout[-MAX_COMMAND_OUTPUT:],
            "stderr": self.stderr[-MAX_COMMAND_OUTPUT:],
            "elapsed_ms": round(self.elapsed_ms, 3),
            "timed_out": self.timed_out,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class AgentAction:
    kind: str
    path: str = ""
    content: str = ""
    command: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"read_file", "search", "write_file", "run_check", "finish"}:
            raise AgentError(f"unsupported agent action: {self.kind}")
        if self.kind in {"read_file", "write_file"} and not self.path:
            raise AgentError(f"{self.kind} requires a path")
        if self.kind == "write_file" and not isinstance(self.content, str):
            raise AgentError("write_file content must be text")
        if self.kind == "run_check" and not self.command:
            raise AgentError("run_check requires a command")


@dataclass(frozen=True)
class AgentPlan:
    summary: str
    actions: tuple[AgentAction, ...]
    acceptance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary or not self.actions:
            raise AgentError("agent plan requires a summary and at least one action")

    def body(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "acceptance": list(self.acceptance),
            "actions": [
                {"kind": action.kind, "path": action.path, "content": action.content, "command": list(action.command), "reason": action.reason}
                for action in self.actions
            ],
        }

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentPlanReview:
    plan_digest: str
    accepted: bool
    errors: tuple[str, ...]
    write_digests: tuple[dict[str, Any], ...]
    validation_commands: tuple[tuple[str, ...], ...]

    def body(self) -> dict[str, Any]:
        return {
            "plan_digest": self.plan_digest,
            "accepted": self.accepted,
            "errors": list(self.errors),
            "write_digests": list(self.write_digests),
            "validation_commands": [list(command) for command in self.validation_commands],
        }


@dataclass(frozen=True)
class AgentRun:
    status: str
    goal: str
    plan: AgentPlan | None
    observations: tuple[dict[str, Any], ...]
    changed_files: tuple[str, ...] = ()
    rolled_back: bool = False
    review: AgentPlanReview | None = None

    def body(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "goal": self.goal,
            "plan": self.plan.body() if self.plan else None,
            "observations": list(self.observations),
            "changed_files": list(self.changed_files),
            "rolled_back": self.rolled_back,
            "review": self.review.body() if self.review else None,
        }


class Workspace:
    """Constrained project workspace with secret and traversal protection."""

    def __init__(self, root: str | os.PathLike[str], policy: AgentPolicy | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.policy = policy or AgentPolicy()
        if not self.root.is_dir():
            raise AgentError(f"workspace is not a directory: {self.root}")
        if self.root == Path.home().resolve() or self.root == Path("/"):
            raise AgentError("refusing to use a broad home/root directory as an agent workspace")

    def resolve(self, relative: str) -> Path:
        if not relative or "\x00" in relative:
            raise AgentError("workspace path is empty or contains NUL")
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise AgentError(f"workspace path escapes root: {relative}")
        if any(part in DENIED_PARTS for part in candidate.relative_to(self.root).parts) or candidate.name in DENIED_NAMES or candidate.name.endswith(DENIED_SUFFIXES):
            raise AgentError(f"workspace path is protected: {relative}")
        return candidate

    def read(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.is_file():
            raise AgentError(f"workspace file does not exist: {relative}")
        if path.stat().st_size > self.policy.max_file_bytes:
            raise AgentError(f"workspace file exceeds {self.policy.max_file_bytes} bytes: {relative}")
        return path.read_text(encoding="utf-8")

    def write(self, relative: str, content: str) -> None:
        if not self.policy.allow_write:
            raise AgentError("workspace writes are disabled; use explicit apply mode")
        if len(content.encode("utf-8")) > self.policy.max_file_bytes:
            raise AgentError(f"generated file exceeds {self.policy.max_file_bytes} bytes: {relative}")
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.agent-tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)

    def files(self) -> tuple[str, ...]:
        found: list[str] = []
        total = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part in DENIED_PARTS for part in relative.parts) or path.name in DENIED_NAMES or path.name.endswith(DENIED_SUFFIXES):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.policy.max_file_bytes:
                continue
            total += size
            if total > MAX_CONTEXT_BYTES:
                break
            found.append(relative.as_posix())
        return tuple(found)

    def context(self, goal: str) -> str:
        manifest = self.root / "holyfitra.toml"
        pieces = [f"workspace={self.root}", f"goal={goal}", "files:"]
        total = sum(len(piece) for piece in pieces)
        for relative in self.files():
            try:
                text = self.read(relative)
            except AgentError:
                continue
            excerpt = text[:16384]
            piece = f"\n--- file: {relative} ---\n{excerpt}"
            if total + len(piece) > MAX_CONTEXT_BYTES:
                break
            pieces.append(piece)
            total += len(piece)
        return "\n".join(pieces)[:MAX_CONTEXT_BYTES]

    def search(self, pattern: str) -> tuple[dict[str, Any], ...]:
        if not pattern or len(pattern) > 256:
            raise AgentError("search pattern must be between 1 and 256 characters")
        results: list[dict[str, Any]] = []
        for relative in self.files():
            text = self.read(relative)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.lower() in line.lower():
                    results.append({"path": relative, "line": line_number, "text": line[:1000]})
                    if len(results) >= 100:
                        return tuple(results)
        return tuple(results)


class AgentCommandRunner:
    """Allow only project-local, non-shell validation commands."""

    _allowed_programs = frozenset({"holyfitra", "python", "python3", "bash", "git"})
    _allowed_prefixes = (
        ("holyfitra", "check"),
        ("holyfitra", "build"),
        ("holyfitra", "test"),
        ("python", "-m", "unittest"),
        ("python3", "-m", "unittest"),
        ("bash", "termux-build.sh", "test"),
        ("git", "diff", "--check"),
    )

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def validate(self, command: Sequence[str]) -> tuple[str, ...]:
        values = tuple(command)
        if not values or any(not isinstance(value, str) or not value or "\x00" in value for value in values):
            raise AgentError("validation command contains an invalid argument")
        if values[0] not in self._allowed_programs:
            raise AgentError(f"command is not allowlisted: {values[0]}")
        if not any(values[: len(prefix)] == prefix for prefix in self._allowed_prefixes):
            raise AgentError(f"command shape is not allowlisted: {' '.join(shlex.quote(value) for value in values)}")
        for value in values[1:]:
            if value.startswith("/"):
                path = Path(value).resolve()
                if self.workspace.root != path and self.workspace.root not in path.parents:
                    raise AgentError("command references a path outside the workspace")
        return values

    def run(self, command: Sequence[str]) -> CommandResult:
        if not self.workspace.policy.allow_commands:
            raise AgentError("command execution is disabled; use explicit apply mode")
        values = self.validate(command)
        started = time.perf_counter_ns()
        try:
            completed = subprocess.run(values, cwd=self.workspace.root, capture_output=True, text=True, timeout=self.workspace.policy.command_timeout_seconds, shell=False, env=self._safe_env())
            timed_out = False
            status = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            status = 124
            stdout = error.stdout or ""
            stderr = (error.stderr or "") + "\nagent: command timed out"
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        return CommandResult(values, status, str(stdout)[-MAX_COMMAND_OUTPUT:], str(stderr)[-MAX_COMMAND_OUTPUT:], elapsed_ms, timed_out)

    def _safe_env(self) -> dict[str, str]:
        allowed = {"PATH", "HOME", "PREFIX", "TMPDIR", "LANG", "LC_ALL", "TERM", "HOLYFITRA_TARGET", "HOLYFITRA_CC", "HOLYFITRA_CXX", "HOLYFITRA_RUN_TIMEOUT"}
        return {key: value for key, value in os.environ.items() if key in allowed}


class CodingAgent:
    """Plan, apply, validate, and rollback AI-generated project changes."""

    def __init__(self, workspace: Workspace, client: AIClient | None = None) -> None:
        self.workspace = workspace
        self.client = client or AIClient()
        self.commands = AgentCommandRunner(workspace)

    def build_plan(self, goal: str, *, provider: str | None = None, model: str | None = None) -> AgentPlan:
        if not goal or not goal.strip():
            raise AgentError("agent goal must be non-empty")
        system = (
            "You are the supervised Holy Fitra coding agent. Produce only a JSON object with keys summary, acceptance, actions. "
            "Each action must be one of read_file, search, write_file, run_check, finish. "
            "Paths are relative to the workspace. Never request secrets, .git, shell=true, arbitrary commands, network commands, deletion, or paths outside the workspace. "
            "For write_file, provide complete UTF-8 file content. For run_check, use only: holyfitra check/build/test, python3 -m unittest, bash termux-build.sh test, or git diff --check. "
            "Prefer the smallest change and include a validation command after writes."
        )
        prompt = f"{self.workspace.context(goal)}\n\nReturn a safe implementation plan for this goal:\n{goal}"
        response = self.client.chat(prompt, provider=provider, model=model, system=system, temperature=0.1, max_tokens=8192, response_format={"type": "json_object"})
        try:
            document = json.loads(response.text)
        except json.JSONDecodeError as error:
            raise AgentError("AI agent returned invalid JSON; no files were changed") from error
        return self._parse_plan(document)

    def _parse_plan(self, document: Any) -> AgentPlan:
        if not isinstance(document, dict):
            raise AgentError("agent plan must be a JSON object")
        raw_actions = document.get("actions")
        if not isinstance(raw_actions, list) or len(raw_actions) > self.workspace.policy.max_steps:
            raise AgentError("agent plan exceeds the action budget")
        actions: list[AgentAction] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise AgentError("agent action must be an object")
            command_value = item.get("command", ())
            if isinstance(command_value, str):
                command = tuple(shlex.split(command_value))
            elif isinstance(command_value, list) and all(isinstance(value, str) for value in command_value):
                command = tuple(command_value)
            else:
                command = ()
            action = AgentAction(str(item.get("kind", "")), str(item.get("path", "")), str(item.get("content", "")), command, str(item.get("reason", "")))
            if action.kind == "write_file":
                self.workspace.resolve(action.path)
            if action.kind == "run_check":
                self.commands.validate(action.command)
            actions.append(action)
        acceptance = document.get("acceptance", [])
        if not isinstance(acceptance, list) or any(not isinstance(item, str) for item in acceptance):
            raise AgentError("agent acceptance criteria must be strings")
        return AgentPlan(str(document.get("summary", "")), tuple(actions), tuple(acceptance))

    def review_plan(self, plan: AgentPlan) -> AgentPlanReview:
        errors: list[str] = []
        write_digests: list[dict[str, Any]] = []
        validation_commands: list[tuple[str, ...]] = []
        last_write = -1
        last_validation = -1
        finish_indices: list[int] = []
        for index, action in enumerate(plan.actions):
            if action.kind == "write_file":
                last_write = index
                content = action.content.encode("utf-8")
                write_digests.append({"path": action.path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            elif action.kind == "run_check":
                last_validation = index
                validation_commands.append(action.command)
            elif action.kind == "finish":
                finish_indices.append(index)
        if len(finish_indices) > 1:
            errors.append("AI plan contains more than one finish action")
        if finish_indices and finish_indices[0] != len(plan.actions) - 1:
            errors.append("AI plan finish action must be last")
        if self.workspace.policy.require_tests_after_write and last_write >= 0 and last_validation <= last_write:
            errors.append("AI plan writes files without a later validation command")
        return AgentPlanReview(plan.digest, not errors, tuple(errors), tuple(write_digests), tuple(validation_commands))

    def inspect_plan(self, plan: AgentPlan) -> AgentRun:
        review = self.review_plan(plan)
        observations: list[dict[str, Any]] = [{"kind": "plan_review", **review.body()}]
        for action in plan.actions:
            if action.kind == "read_file":
                observations.append({"kind": "read_file", "path": action.path, "content": self.workspace.read(action.path)})
            elif action.kind == "search":
                observations.append({"kind": "search", "pattern": action.path, "matches": list(self.workspace.search(action.path))})
            elif action.kind == "run_check":
                observations.append({"kind": "run_check", "command": list(action.command), "status": "requires_apply_mode"})
            elif action.kind == "finish":
                observations.append({"kind": "finish", "reason": action.reason})
        return AgentRun("planned" if review.accepted else "rejected", plan.summary, plan, tuple(observations), review=review)

    def apply_plan(self, goal: str, plan: AgentPlan) -> AgentRun:
        if not self.workspace.policy.allow_write or not self.workspace.policy.allow_commands:
            raise AgentError("apply mode requires both allow_write and allow_commands policy flags")
        review = self.review_plan(plan)
        if not review.accepted:
            return AgentRun("rejected", goal, plan, ({"kind": "plan_review", **review.body()},), review=review)
        backups: dict[Path, bytes | None] = {}
        observations: list[dict[str, Any]] = [{"kind": "plan_review", **review.body()}]
        changed: list[str] = []
        try:
            for action in plan.actions:
                if action.kind == "read_file":
                    observations.append({"kind": "read_file", "path": action.path, "content": self.workspace.read(action.path)})
                elif action.kind == "search":
                    observations.append({"kind": "search", "pattern": action.path, "matches": list(self.workspace.search(action.path))})
                elif action.kind == "write_file":
                    path = self.workspace.resolve(action.path)
                    if path not in backups:
                        backups[path] = path.read_bytes() if path.is_file() else None
                    self.workspace.write(action.path, action.content)
                    changed.append(action.path)
                    observations.append({"kind": "write_file", "path": action.path, "bytes": len(action.content.encode("utf-8"))})
                elif action.kind == "run_check":
                    result = self.commands.run(action.command)
                    observations.append({"kind": "run_check", **result.body()})
                    if not result.passed:
                        raise AgentError(f"validation failed: {' '.join(result.command)}")
                elif action.kind == "finish":
                    observations.append({"kind": "finish", "reason": action.reason})
            if self.workspace.policy.require_tests_after_write and changed and not any(item.get("kind") == "run_check" for item in observations):
                raise AgentError("plan wrote files but did not include a validation command")
        except Exception as error:
            self._rollback(backups)
            observations.append({"kind": "rollback", "reason": str(error)})
            return AgentRun("rolled_back", goal, plan, tuple(observations), tuple(sorted(set(changed))), True, review)
        return AgentRun("applied", goal, plan, tuple(observations), tuple(sorted(set(changed))), False, review)

    def run(self, goal: str, *, apply: bool = False, provider: str | None = None, model: str | None = None) -> AgentRun:
        plan = self.build_plan(goal, provider=provider, model=model)
        if not apply:
            return self.inspect_plan(plan)
        return self.apply_plan(goal, plan)

    def improve(self, goal: str, *, rounds: int = 1, provider: str | None = None, model: str | None = None) -> tuple[AgentRun, ...]:
        if not self.workspace.policy.allow_write or not self.workspace.policy.allow_commands:
            raise AgentError("improve mode requires explicit write and command permissions")
        if not 1 <= rounds <= self.workspace.policy.max_iterations:
            raise AgentError("rounds exceed the policy iteration budget")
        results: list[AgentRun] = []
        for _ in range(rounds):
            plan = self.build_plan(goal, provider=provider, model=model)
            result = self.apply_plan(goal, plan)
            results.append(result)
            if result.status != "applied":
                break
        return tuple(results)

    @staticmethod
    def _rollback(backups: Mapping[Path, bytes | None]) -> None:
        for path, content in backups.items():
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            except OSError:
                pass


def run_agent(root: str | os.PathLike[str], goal: str, *, apply: bool = False, improve_rounds: int = 0, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    policy = AgentPolicy(allow_write=apply, allow_commands=apply)
    agent = CodingAgent(Workspace(root, policy))
    if improve_rounds:
        runs = agent.improve(goal, rounds=improve_rounds, provider=provider, model=model)
        return {"runs": [run.body() for run in runs]}
    return agent.run(goal, apply=apply, provider=provider, model=model).body()


__all__ = ["AgentAction", "AgentCommandRunner", "AgentError", "AgentPlan", "AgentPlanReview", "AgentPolicy", "AgentRun", "CodingAgent", "CommandResult", "Workspace", "run_agent"]
