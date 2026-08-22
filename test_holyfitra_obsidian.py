from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from holyfitra_ai_system import CapabilityError, EvidenceKind, ToolRegistry
from holyfitra_obsidian import ObsidianError, ObsidianVaultIndex


class HolyFitraObsidianTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "vault"
        (self.root / ".obsidian").mkdir(parents=True)
        (self.root / "Project").mkdir()
        (self.root / "AI.md").write_text(
            "---\ntitle: AI Notes\ntags: [ai, research]\n---\n# AI Notes\nTransformer inference uses quantization and careful evaluation.\nSee [[Project/Compiler]] and [[Missing Note]].\n",
            encoding="utf-8",
        )
        (self.root / "Project" / "Compiler.md").write_text(
            "# Compiler\nThe compiler lowers verified AI plans.\n[[AI]]\n",
            encoding="utf-8",
        )
        (self.root / "ignored.md").write_text("This note is not hidden.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_refresh_parses_notes_and_excludes_obsidian_directory(self):
        index = ObsidianVaultIndex(self.root)
        snapshot = index.refresh()
        self.assertEqual(snapshot.note_count, 3)
        self.assertIn("Missing Note", snapshot.unresolved_links)
        self.assertEqual(index.get("AI.md").title, "AI Notes")
        self.assertIn("ai", index.get("AI.md").tags)
        self.assertEqual(index.get("AI.md").headings[0], ("AI Notes", 5))

    def test_backlinks_and_search_are_deterministic(self):
        index = ObsidianVaultIndex(self.root)
        index.refresh()
        backlinks = index.backlinks_for("Project/Compiler")
        self.assertEqual(tuple(note.path for note in backlinks), ("AI.md",))
        first = index.search("quantization transformer", top_k=5)
        second = index.search("quantization transformer", top_k=5)
        self.assertEqual(first, second)
        self.assertEqual(first[0].path, "AI.md")
        self.assertGreater(first[0].score, 0.0)

    def test_evidence_has_claim_kind_and_vault_provenance(self):
        index = ObsidianVaultIndex(self.root)
        evidence = index.evidence_for("verified AI plans")
        self.assertGreaterEqual(len(evidence), 1)
        self.assertEqual(evidence[0].kind.value, "claim")
        self.assertTrue(evidence[0].provenance[0].startswith("obsidian:"))
        with self.assertRaises(ObsidianError):
            index.evidence_for("compiler", kind=EvidenceKind.PREDICTION)

    def test_scalar_frontmatter_tag_is_normalized(self):
        (self.root / "scalar.md").write_text("---\ntags: ai\n---\nA note.\n", encoding="utf-8")
        index = ObsidianVaultIndex(self.root)
        self.assertEqual(index.get("scalar").tags, ("ai",))

    def test_agent_tool_is_capability_gated_and_read_only(self):
        index = ObsidianVaultIndex(self.root)
        registry = ToolRegistry()
        index.register_read_tool(registry)
        with self.assertRaises(CapabilityError):
            registry.invoke("obsidian.search", {"query": "compiler"}, grants=frozenset())
        result = registry.invoke("obsidian.search", {"query": "compiler"}, grants=frozenset({"obsidian.read"}))
        self.assertIn("Compiler", result.content)
        with self.assertRaises(PermissionError):
            index.write_note("new.md", "# New")

    def test_canvas_and_bases_exports_are_valid_and_deterministic(self):
        import json

        index = ObsidianVaultIndex(self.root)
        index.refresh()
        first = index.canvas()
        second = index.canvas()
        self.assertEqual(first, second)
        node_ids = {node["id"] for node in first["nodes"]}
        self.assertEqual(len(node_ids), len(first["nodes"]))
        self.assertTrue(all(edge["fromNode"] in node_ids and edge["toNode"] in node_ids for edge in first["edges"]))
        self.assertEqual(json.loads(index.canvas_json()), first)
        base = index.bases_yaml(tag="#ai")
        self.assertIn('file.hasTag("ai")', base)
        self.assertIn("- type: table", base)
        with self.assertRaises(PermissionError):
            index.export_artifact("graph.canvas", kind="canvas")
        destination = index.export_artifact("graph.canvas", kind="canvas", capability="obsidian.write")
        self.assertTrue(destination.is_file())

    def test_path_escape_and_external_links_are_not_imported(self):
        index = ObsidianVaultIndex(self.root)
        with self.assertRaises(ObsidianError):
            index.get("../secret.md")
        (self.root / "AI.md").write_text("External [site](https://example.com) and [[Project/Compiler]].\n", encoding="utf-8")
        snapshot = index.refresh()
        self.assertEqual(snapshot.unresolved_links, ())


if __name__ == "__main__":
    unittest.main()
