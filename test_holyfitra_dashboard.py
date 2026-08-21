#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holyfitra_telemetry import read_events, record_event, summarize_events
from holyfitra_tui import CursesApp, Workspace


class HolyFitraDashboardTests(unittest.TestCase):
    def test_telemetry_summary_tracks_cache_and_quantization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_event(root, "compile", stage="native", cache_hit=False, digest="a", elapsed_ms=80.0, target="host")
            record_event(root, "compile", stage="native", cache_hit=True, digest="a", elapsed_ms=0.2, target="host")
            record_event(root, "quantization", precision="int4", proof_verified=True, fallback=False, layer_error=0.01, elapsed_ms=4.0)
            summary = summarize_events(read_events(root))
            self.assertEqual(summary["compile"]["cache_hits"], 1)
            self.assertEqual(summary["compile"]["cache_misses"], 1)
            self.assertEqual(summary["compile"]["hit_rate"], 0.5)
            self.assertEqual(summary["quantization"]["precision"], "int4")
            self.assertTrue(summary["quantization"]["proof_verified"])

    def test_source_directory_events_roll_up_to_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            (root / "src").mkdir(parents=True)
            (root / "holyfitra.toml").write_text('[project]\nname = "demo"\nentry = "src/main.hf"\n', encoding="utf-8")
            record_event(root / "src", "compile", cache_hit=True, digest="rooted", elapsed_ms=0.2)
            summary = summarize_events(read_events(root))
            self.assertEqual(summary["compile"]["cache_hits"], 1)

    def test_workspace_snapshot_contains_live_dashboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.hf").write_text("module demo\nfn main() -> i32 { return 7 }\n", encoding="utf-8")
            record_event(root, "compile", stage="native", cache_hit=True, digest="demo", elapsed_ms=0.1, target="host")
            record_event(root, "quantization", precision="int8", proof_verified=True, fallback=True, layer_error=0.03, elapsed_ms=5.0)
            snapshot = Workspace.open(root).snapshot()
            self.assertIn("LIVE DASHBOARD", snapshot)
            self.assertIn("cache_hits", snapshot)
            self.assertIn("quantization", snapshot)
            self.assertIn("int8", snapshot)

    def test_curses_poll_interval_is_bounded(self):
        workspace = Workspace(Path("."))
        self.assertEqual(CursesApp(workspace, poll_interval=0.0).poll_interval, 0.1)
        self.assertEqual(CursesApp(workspace, poll_interval=2.0).poll_interval, 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
