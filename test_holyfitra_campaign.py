from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from holyfitra_ai_api import AIResponse, ProviderStatus
from holyfitra_campaign import CampaignConfig, CampaignError, MultiAICampaign, load_campaign_config


class FakeRegistry:
    def __init__(self, names: tuple[str, ...]) -> None:
        self._statuses = tuple(
            ProviderStatus(name, "fake", True, "https://fake.invalid", None, "fake-model", "offline test provider")
            for name in names
        )

    def statuses(self):
        return self._statuses


class FakeClient:
    def __init__(self, plans: dict[str, str]) -> None:
        self.registry = FakeRegistry(tuple(plans))
        self.plans = plans

    def chat(self, prompt: str, *, provider: str | None = None, model: str | None = None, **kwargs):
        assert provider is not None
        return AIResponse(provider, model or "fake-model", self.plans[provider])


def plan_json(path: str = "generated/main.hf", content: str = "module generated\n\nfn main() -> i32 {\n  return 42\n}\n") -> str:
    return json.dumps(
        {
            "summary": "Generate a validated Fitra entry point",
            "acceptance": ["the source validates"],
            "actions": [
                {"kind": "write_file", "path": path, "content": content, "reason": "generated source"},
                {"kind": "run_check", "command": ["git", "diff", "--check"], "reason": "check the patch"},
                {"kind": "finish", "reason": "candidate complete"},
            ],
        }
    )


class MultiAICampaignTests(unittest.TestCase):
    def make_workspace(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="holyfitra-campaign-"))
        (root / "README.md").write_text("offline campaign workspace\n", encoding="utf-8")
        return root

    def test_plan_only_generates_and_writes_report_without_workspace_changes(self) -> None:
        root = self.make_workspace()
        before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        client = FakeClient({"alpha": plan_json(), "beta": plan_json()})
        config = CampaignConfig(root, "add a generated entry point", ("alpha", "beta"), rounds=1, min_consensus=2)
        report = MultiAICampaign(config, client=client).run()
        after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        self.assertEqual(sorted(before + [".holyfitra", ".holyfitra/campaign", ".holyfitra/campaign/latest.json"]), after)
        self.assertEqual(report["summary"]["selected_rounds"], 1)
        self.assertEqual(report["summary"]["applied_rounds"], 0)
        self.assertFalse((root / "generated/main.hf").exists())

    def test_consensus_selects_deterministic_provider(self) -> None:
        root = self.make_workspace()
        client = FakeClient({"zeta": plan_json(), "alpha": plan_json(), "beta": plan_json()})
        config = CampaignConfig(root, "select a consensus plan", ("zeta", "alpha", "beta"), rounds=1, min_consensus=2)
        report = MultiAICampaign(config, client=client).run()
        self.assertEqual(report["rounds"][0]["selected_provider"], "alpha")
        self.assertEqual(report["rounds"][0]["consensus"], 3)

    def test_no_consensus_does_not_select_candidate(self) -> None:
        root = self.make_workspace()
        client = FakeClient({"alpha": plan_json("a.hf"), "beta": plan_json("b.hf")})
        config = CampaignConfig(root, "reject disagreement", ("alpha", "beta"), rounds=1, min_consensus=2)
        report = MultiAICampaign(config, client=client).run()
        self.assertIsNone(report["rounds"][0]["selected_provider"])
        self.assertEqual(report["summary"]["selected_rounds"], 0)

    def test_apply_requires_high_risk_git_branch(self) -> None:
        root = self.make_workspace()
        client = FakeClient({"alpha": plan_json()})
        config = CampaignConfig(root, "apply a change", ("alpha",), rounds=1, min_consensus=1, apply=True)
        with self.assertRaises(CampaignError):
            MultiAICampaign(config, client=client).run()

    def test_output_cannot_escape_workspace(self) -> None:
        root = self.make_workspace()
        with self.assertRaises(CampaignError):
            CampaignConfig(root, "unsafe output", (), output=Path("/tmp/outside.json"))

    def test_toml_configuration_loads(self) -> None:
        root = self.make_workspace()
        config_path = root / "campaign.toml"
        config_path.write_text(
            "[campaign]\nworkspace = \".\"\ngoal = \"improve tests\"\nproviders = [\"alpha\"]\nrounds = 2\nmin_consensus = 1\n",
            encoding="utf-8",
        )
        config = load_campaign_config(config_path)
        self.assertEqual(config.workspace, root)
        self.assertEqual(config.providers, ("alpha",))
        self.assertEqual(config.rounds, 2)


if __name__ == "__main__":
    unittest.main()
