from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from holyfitra_agent import AgentAction, AgentError, AgentPlan, AgentPolicy, CodingAgent, Workspace
from holyfitra_hd import HD_SCHEMA, HDCopilot, ObsidianSecondBrain, load_private_provider_env, load_reviewed_plan_packet, run_hd, save_reviewed_plan_packet


class HDCopilotTests(unittest.TestCase):
    def _vault(self, root: Path) -> Path:
        vault = root / "vault"
        vault.mkdir()
        (vault / "hf.md").write_text("# HF Notes\nHD should retain validation receipts and use deterministic imports.\n", encoding="utf-8")
        (vault / "architecture.md").write_text("# Architecture\nThe HD copilot is supervised and must roll back failed checks.\n", encoding="utf-8")
        (vault / ".obsidian").mkdir()
        (vault / ".obsidian" / "private.md").write_text("do not index", encoding="utf-8")
        return vault

    def test_obsidian_compatible_markdown_retrieval_is_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = self._vault(Path(temporary))
            brain = ObsidianSecondBrain(vault)
            first = brain.search("HD validation imports")
            second = brain.search("HD validation imports")
            self.assertEqual([item.body() for item in first], [item.body() for item in second])
            self.assertEqual([item.document.path for item in first], ["hf.md", "architecture.md"])
            self.assertEqual(brain.digest(first), brain.digest(second))

    def test_hd_inspection_records_knowledge_and_rejects_unvalidated_writes_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            plan = AgentPlan("unsafe draft", (AgentAction("write_file", "main.txt", "changed"), AgentAction("finish", reason="done")))
            hd = HDCopilot(Workspace(root), ObsidianSecondBrain(self._vault(root)))
            result = hd.inspect_plan("HD validation", plan)
            self.assertEqual(result.schema, HD_SCHEMA)
            self.assertEqual(result.agent_run.status, "rejected")
            self.assertTrue(result.knowledge_digest)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "original")

    def test_hd_apply_requires_explicit_authorization_and_preserves_agent_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            vault = self._vault(root)
            plan = AgentPlan("safe draft", (
                AgentAction("write_file", "main.txt", "changed"),
                AgentAction("write_file", "test_hd_smoke.py", "import unittest\n\nclass Smoke(unittest.TestCase):\n    def test_change(self):\n        self.assertEqual(open('main.txt', encoding='utf-8').read(), 'changed')\n"),
                AgentAction("run_check", command=("python3", "-m", "unittest", "test_hd_smoke")),
                AgentAction("finish", reason="done"),
            ))
            with self.assertRaisesRegex(AgentError, "apply mode requires"):
                HDCopilot(Workspace(root), ObsidianSecondBrain(vault)).apply_plan("HD apply", plan)
            policy = AgentPolicy(allow_write=True, allow_commands=True)
            applied = HDCopilot(Workspace(root, policy), ObsidianSecondBrain(vault)).apply_plan("HD apply", plan)
            self.assertEqual(applied.agent_run.status, "applied")
            self.assertFalse(applied.agent_run.rolled_back)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "changed")
            self.assertTrue(applied.agent_run.review and applied.agent_run.review.accepted)

    def test_hd_failed_validation_rolls_back_all_staged_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            (root / "test_hd_failure.py").write_text("import unittest\n\nclass Failure(unittest.TestCase):\n    def test_failure(self):\n        self.fail('intentional validation failure')\n", encoding="utf-8")
            plan = AgentPlan("rollback draft", (
                AgentAction("write_file", "main.txt", "changed"),
                AgentAction("write_file", "created.txt", "temporary"),
                AgentAction("run_check", command=("python3", "-m", "unittest", "test_hd_failure")),
                AgentAction("finish", reason="done"),
            ))
            policy = AgentPolicy(allow_write=True, allow_commands=True)
            result = HDCopilot(Workspace(root, policy), ObsidianSecondBrain(self._vault(root))).apply_plan("HD rollback", plan)
            self.assertEqual(result.agent_run.status, "rolled_back")
            self.assertTrue(result.agent_run.rolled_back)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "original")
            self.assertFalse((root / "created.txt").exists())
            self.assertEqual(result.agent_run.observations[-1]["kind"], "rollback")

    def test_hd_provider_plan_receives_bounded_provenance_but_plan_only_mode_cannot_write(self):
        class FakeClient:
            def __init__(self):
                self.prompt = ""
                self.system = ""

            def chat(self, prompt, **kwargs):
                self.prompt = prompt
                self.system = kwargs["system"]
                return SimpleNamespace(text=(
                    '{"summary":"draft","acceptance":["smoke"],"actions":['
                    '{"kind":"write_file","path":"main.txt","content":"changed"},'
                    '{"kind":"run_check","command":["python3","-m","unittest","test_hd_smoke"]},'
                    '{"kind":"finish","reason":"done"}]}'
                ))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            (root / "test_hd_smoke.py").write_text("import unittest\n\nclass Smoke(unittest.TestCase):\n    def test_value(self):\n        self.assertTrue(True)\n", encoding="utf-8")
            client = FakeClient()
            agent = CodingAgent(Workspace(root), client=client)
            result = HDCopilot(agent.workspace, ObsidianSecondBrain(self._vault(root)), agent).run("HD validation imports")
            self.assertEqual(result.agent_run.status, "planned")
            self.assertIn("Source: hf.md", client.prompt)
            self.assertIn("sha256:", client.prompt)
            self.assertIn("untrusted context", client.system)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "original")

    def test_private_provider_environment_is_explicitly_loaded_without_disclosure_and_is_not_workspace_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret_file = root / "hd.providers.env"
            secret_file.write_text("# local only\nOPENROUTER_API_KEY=not-a-real-value\nHOLYFITRA_AI_PROVIDER=openrouter\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=False):
                names = load_private_provider_env(secret_file)
            self.assertEqual(names, ("HOLYFITRA_AI_PROVIDER", "OPENROUTER_API_KEY"))
            with self.assertRaisesRegex(AgentError, "protected"):
                Workspace(root).read("hd.providers.env")

    def test_private_provider_environment_rejects_unrelated_variables(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "hd.providers.env"
            source.write_text("PATH=unsafe\n", encoding="utf-8")
            with self.assertRaisesRegex(AgentError, "not allowed"):
                load_private_provider_env(source)

    def test_private_provider_filename_is_ignored_but_the_template_is_tracked(self):
        repository = Path(__file__).with_name(".gitignore")
        self.assertIn("\nhd.providers.env\n", repository.read_text(encoding="utf-8"))
        self.assertTrue(Path(__file__).with_name("hd.providers.env.example").is_file())

    def test_github_secret_workflow_is_manual_only_and_never_calls_a_provider(self):
        workflow = Path(__file__).parent / ".github" / "workflows" / "hd-provider-secret-check.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", content)
        self.assertNotIn("push:", content)
        self.assertNotIn("pull_request:", content)
        self.assertIn("HD_OPENROUTER_API_KEY: ${{ secrets.HD_OPENROUTER_API_KEY }}", content)
        self.assertIn("HD_GEMINI_API_KEY: ${{ secrets.HD_GEMINI_API_KEY }}", content)
        self.assertIn("HD_CEREBRAS_API_KEY: ${{ secrets.HD_CEREBRAS_API_KEY }}", content)
        self.assertIn("HD_GROQ_API_KEY: ${{ secrets.HD_GROQ_API_KEY }}", content)
        self.assertIn("HD_COHERE_API_KEY: ${{ secrets.HD_COHERE_API_KEY }}", content)
        self.assertNotIn("holyfitra hd", content)
        self.assertNotIn("ai chat", content)
        self.assertNotIn("curl ", content)

    def test_hd_plan_receipt_contains_visible_bounded_create_and_modify_diffs_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("before\n", encoding="utf-8")
            plan = AgentPlan("visible review", (
                AgentAction("write_file", "main.txt", "after\n"),
                AgentAction("write_file", "new.txt", "created\n"),
                AgentAction("run_check", command=("git", "diff", "--check")),
                AgentAction("finish", reason="done"),
            ))
            receipt = HDCopilot(Workspace(root)).inspect_plan("show changes", plan)
            previews = {preview.path: preview for preview in receipt.changes}
            self.assertEqual(previews["main.txt"].operation, "modify")
            self.assertIn("-before", previews["main.txt"].unified_diff)
            self.assertIn("+after", previews["main.txt"].unified_diff)
            self.assertEqual(previews["new.txt"].operation, "create")
            self.assertIn("/dev/null", previews["new.txt"].unified_diff)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "before\n")
            self.assertFalse((root / "new.txt").exists())

    def test_exact_reviewed_plan_packet_replays_only_the_visible_plan_and_refuses_stale_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("before\n", encoding="utf-8")
            (root / "test_hd_packet.py").write_text("import unittest\n\nclass Packet(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(open('main.txt', encoding='utf-8').read(), 'after\\n')\n", encoding="utf-8")
            plan = AgentPlan("reviewed exact plan", (
                AgentAction("write_file", "main.txt", "after\n"),
                AgentAction("run_check", command=("python3", "-m", "unittest", "test_hd_packet")),
                AgentAction("finish", reason="done"),
            ))
            preview = HDCopilot(Workspace(root)).prepare_review_packet("replace main", plan)
            packet_path = root / "review.hfhd-plan.json"
            save_reviewed_plan_packet(packet_path, preview)
            loaded = load_reviewed_plan_packet(packet_path)
            self.assertEqual(loaded.plan.digest, plan.digest)
            self.assertIn("-before", preview.run.changes[0].unified_diff)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "before\n")
            applied = HDCopilot(Workspace(root, AgentPolicy(allow_write=True, allow_commands=True))).apply_review_packet(loaded)
            self.assertEqual(applied.agent_run.status, "applied")
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "after\n")

            second_plan = AgentPlan("reviewed stale plan", (
                AgentAction("write_file", "main.txt", "would-change\n"),
                AgentAction("run_check", command=("python3", "-m", "unittest", "test_hd_packet")),
                AgentAction("finish", reason="done"),
            ))
            second_packet = HDCopilot(Workspace(root)).prepare_review_packet("stale", second_plan)
            (root / "main.txt").write_text("user-edit\n", encoding="utf-8")
            with self.assertRaisesRegex(AgentError, "workspace changed"):
                HDCopilot(Workspace(root, AgentPolicy(allow_write=True, allow_commands=True))).apply_review_packet(second_packet)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "user-edit\n")

    def test_hd_advice_is_read_only_and_campaign_requires_explicit_scoped_approval(self):
        class FakeClient:
            def __init__(self):
                self.system = ""

            def chat(self, _prompt, **kwargs):
                self.system = kwargs["system"]
                return SimpleNamespace(text="HF explanation")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            agent = CodingAgent(Workspace(root), client=FakeClient())
            advice = HDCopilot(agent.workspace, agent=agent).advise("Explain main.txt")
            self.assertEqual(advice["mutation"], "none")
            self.assertIn("Do not generate an action plan", agent.client.system)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "original")
            with self.assertRaisesRegex(AgentError, "require --apply"):
                run_hd(root, "do work", rounds=1, approve_campaign=True)
            with self.assertRaisesRegex(AgentError, "explicit campaign approval"):
                run_hd(root, "do work", apply=True, rounds=1)

    def test_hd_campaign_is_bounded_and_stops_after_a_failed_validation_receipt(self):
        class QueueClient:
            def __init__(self):
                def plan(summary, content, test_source):
                    return json.dumps({
                        "summary": summary,
                        "acceptance": ["smoke"],
                        "actions": [
                            {"kind": "write_file", "path": "main.txt", "content": content},
                            {"kind": "write_file", "path": "test_hd_cycle.py", "content": test_source},
                            {"kind": "run_check", "command": ["python3", "-m", "unittest", "test_hd_cycle"]},
                            {"kind": "finish", "reason": "done"},
                        ],
                    })
                self.responses = [
                    plan("first", "first", "import unittest\n\nclass Cycle(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(open('main.txt', encoding='utf-8').read(), 'first')\n"),
                    plan("second", "second", "import unittest\n\nclass Cycle(unittest.TestCase):\n    def test_value(self):\n        self.fail('intentional')\n"),
                ]

            def chat(self, _prompt, **_kwargs):
                return SimpleNamespace(text=self.responses.pop(0))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.txt").write_text("original", encoding="utf-8")
            policy = AgentPolicy(allow_write=True, allow_commands=True)
            agent = CodingAgent(Workspace(root, policy), client=QueueClient())
            campaign = HDCopilot(agent.workspace, agent=agent).campaign("iterate", rounds=3)
            self.assertEqual(campaign.requested_rounds, 3)
            self.assertEqual(len(campaign.rounds), 2)
            self.assertEqual(campaign.rounds[0].agent_run.status, "applied")
            self.assertEqual(campaign.rounds[1].agent_run.status, "rolled_back")
            self.assertIn("rolled_back", campaign.stopped_reason)
            self.assertEqual((root / "main.txt").read_text(encoding="utf-8"), "first")
            self.assertTrue(campaign.rounds[0].changes[0].unified_diff)


if __name__ == "__main__":
    unittest.main()
