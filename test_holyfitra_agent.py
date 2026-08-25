from __future__ import annotations

import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from holyfitra_ai_api import AIClient, AIRequest, AIResponse, OpenAICompatibleProvider, ProviderRegistry
from holyfitra_agent import AgentAction, AgentCommandRunner, AgentError, AgentPlan, AgentPolicy, CodingAgent, Workspace


class FakeProvider(OpenAICompatibleProvider):
    def __init__(self, response_text: str) -> None:
        super().__init__("fake", base_url="https://example.test/v1", api_key_env=None, default_model="fake-model")
        self.response_text = response_text

    def chat(self, request: AIRequest) -> AIResponse:
        return AIResponse("fake", request.model, self.response_text)


class AgentTests(unittest.TestCase):
    def workspace(self, *, apply: bool = False) -> tuple[tempfile.TemporaryDirectory[str], Workspace]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "holyfitra.toml").write_text('[project]\nname = "demo"\nentry = "src/main.hf"\n', encoding="utf-8")
        (root / "src").mkdir()
        (root / "src/main.hf").write_text("module demo\nfn main() -> i32 { return 0 }\n", encoding="utf-8")
        policy = AgentPolicy(allow_write=apply, allow_commands=apply)
        return temporary, Workspace(root, policy)

    def test_workspace_rejects_escape_and_secret_paths(self) -> None:
        temporary, workspace = self.workspace()
        with self.assertRaises(AgentError):
            workspace.resolve("../outside.txt")
        with self.assertRaises(AgentError):
            workspace.resolve(".env")
        temporary.cleanup()

    def test_command_runner_rejects_shell_and_external_paths(self) -> None:
        temporary, workspace = self.workspace(apply=True)
        runner = AgentCommandRunner(workspace)
        with self.assertRaises(AgentError):
            runner.validate(("bash", "-c", "rm -rf ."))
        with self.assertRaises(AgentError):
            runner.validate(("python3", "-m", "unittest", "/tmp/external.py"))
        temporary.cleanup()

    def test_plan_only_mode_never_writes(self) -> None:
        payload = '{"summary":"inspect project","acceptance":["read source"],"actions":[{"kind":"read_file","path":"src/main.hf"}]}'
        temporary, workspace = self.workspace()
        agent = CodingAgent(workspace, AIClient(ProviderRegistry([FakeProvider(payload)])))
        result = agent.run("inspect the entry point")
        self.assertEqual(result.status, "planned")
        self.assertFalse(result.changed_files)
        temporary.cleanup()

    def test_apply_plan_writes_and_validates(self) -> None:
        temporary, workspace = self.workspace(apply=True)
        agent = CodingAgent(workspace)
        plan = AgentPlan(
            "update return value",
            (
                AgentAction("write_file", "src/main.hf", "module demo\nfn main() -> i32 { return 42 }\n"),
                AgentAction("run_check", command=("holyfitra", "check", "src/main.hf")),
            ),
            ("source parses",),
        )
        with patch.dict(os.environ, {"PATH": f"{Path(__file__).parent}:{os.environ.get('PATH', '')}"}, clear=False):
            result = agent.apply_plan("return 42", plan)
        self.assertEqual(result.status, "applied")
        self.assertEqual(workspace.read("src/main.hf").split("return ")[1].split()[0], "42")
        temporary.cleanup()

    def test_failed_validation_rolls_back_new_file(self) -> None:
        temporary, workspace = self.workspace(apply=True)
        agent = CodingAgent(workspace)
        plan = AgentPlan(
            "write invalid source",
            (
                AgentAction("write_file", "src/bad.hf", "not valid Fitra\n"),
                AgentAction("run_check", command=("holyfitra", "check", "src/bad.hf")),
            ),
        )
        with patch.dict(os.environ, {"PATH": f"{Path(__file__).parent}:{os.environ.get('PATH', '')}"}, clear=False):
            result = agent.apply_plan("try invalid change", plan)
        self.assertEqual(result.status, "rolled_back")
        self.assertTrue(result.rolled_back)
        self.assertFalse((Path(temporary.name) / "src/bad.hf").exists())
        temporary.cleanup()

    def test_write_requires_validation_action(self) -> None:
        temporary, workspace = self.workspace(apply=True)
        agent = CodingAgent(workspace)
        plan = AgentPlan("write without test", (AgentAction("write_file", "src/main.hf", "module demo\nfn main() -> i32 { return 1 }\n"),))
        result = agent.apply_plan("write source", plan)
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.rolled_back)
        self.assertIsNotNone(result.review)
        self.assertEqual(workspace.read("src/main.hf").split("return ")[1].split()[0], "0")
        temporary.cleanup()

    def test_review_rejects_write_after_last_validation_without_mutation(self) -> None:
        temporary, workspace = self.workspace(apply=True)
        agent = CodingAgent(workspace)
        plan = AgentPlan(
            "unsafe ordering",
            (
                AgentAction("write_file", "src/main.hf", "module demo\nfn main() -> i32 { return 1 }\n"),
                AgentAction("run_check", command=("git", "diff", "--check")),
                AgentAction("write_file", "src/main.hf", "module demo\nfn main() -> i32 { return 2 }\n"),
            ),
        )
        result = agent.apply_plan("unsafe ordering", plan)
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.rolled_back)
        self.assertIsNotNone(result.review)
        assert result.review is not None
        self.assertFalse(result.review.accepted)
        self.assertIn("without a later validation command", result.review.errors[0])
        self.assertEqual(workspace.read("src/main.hf").split("return ")[1].split()[0], "0")
        temporary.cleanup()

    def test_review_receipt_uses_digests_not_generated_write_content(self) -> None:
        temporary, workspace = self.workspace()
        agent = CodingAgent(workspace)
        plan = AgentPlan(
            "review proof",
            (
                AgentAction("write_file", "src/main.hf", "module demo\nfn main() -> i32 { return 7 }\n"),
                AgentAction("run_check", command=("holyfitra", "check", "src/main.hf")),
            ),
        )
        review = agent.review_plan(plan)
        self.assertTrue(review.accepted)
        body = review.body()
        self.assertEqual(len(body["plan_digest"]), 64)
        self.assertEqual(body["write_digests"][0]["path"], "src/main.hf")
        self.assertNotIn("return 7", json.dumps(body))
        temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
