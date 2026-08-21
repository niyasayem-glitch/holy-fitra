#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from holyfitra_compiler import doctor_report, init_project
from holyfitra_repl import run_repl
from holyfitra_tui import Workspace


class HolyFitraUITests(unittest.TestCase):
    def test_repl_help_and_safe_source_buffer(self):
        output = run_repl([
            "/help",
            "/source",
            "module repl_demo",
            "fn main() -> i32 {",
            "return 7",
            "}",
            "/end",
            "/check",
            "/quit",
        ])
        self.assertIn("Holy Fitra REPL commands", output)
        self.assertIn('"valid": true', output)
        self.assertIn("never executed as a shell command", output)

    def test_repl_unknown_command_is_nonfatal(self):
        output = run_repl(["/not-a-command", "/quit"])
        self.assertIn("unknown command", output)

    def test_workspace_snapshot_and_hyperir_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            init_project(root, "ui_demo")
            source = root / "src" / "tensor.hf"
            source.write_text(
                'module tensor_ui\n'
                'fn infer(x: Tensor<[1, 4], f16, device=neon>) -> Tensor<[1, 4], f16> {\n'
                '  let w: Tensor<[4, 4], int4, device=neon>\n'
                '  let y = matmul(x, w)\n'
                '}\n',
                encoding="utf-8",
            )
            workspace = Workspace.open(root)
            workspace.selected = next(index for index, path in enumerate(workspace.files) if path.name == "tensor.hf")
            result = workspace.inspect()
            snapshot = workspace.snapshot()
            self.assertTrue(result["valid"])
            self.assertEqual(result["mode"], "hyperir")
            self.assertIn("tensor.hf", snapshot)
            self.assertIn("hyperir_digest", snapshot)
            self.assertIn("KEYS:", snapshot)

    def test_doctor_report_is_structured(self):
        report = doctor_report()
        self.assertIn("python", report)
        self.assertIn("native_backend_ready", report)
        self.assertIn("hyperir_backend_ready", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
