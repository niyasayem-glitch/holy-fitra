#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holyfitra_compiler import HolyFitraError, emit_llvm, init_project, load_project, parse_native, validate_native


class HolyFitraCompilerTests(unittest.TestCase):
    SOURCE = """
module arithmetic
fn add(a: i32, b: i32) -> i32 {
    let c = a + b
    return c
}
fn main() -> i32 {
    return add(40, 2)
}
"""

    def test_lexer_parser_and_typecheck(self):
        program = parse_native(self.SOURCE)
        self.assertEqual(program.module, "arithmetic")
        self.assertEqual([function.name for function in program.functions], ["add", "main"])
        validate_native(program)

    def test_llvm_contains_native_functions(self):
        llvm = emit_llvm(parse_native(self.SOURCE))
        self.assertIn("define i32 @add(i32 %a, i32 %b)", llvm)
        self.assertIn("define i32 @main()", llvm)
        self.assertIn("call i32 @add(i32 40, i32 2)", llvm)

    def test_type_error_is_rejected(self):
        source = "fn main() -> i32 { let x: i64 = 1 return x }"
        with self.assertRaises(HolyFitraError):
            validate_native(parse_native(source))

    def test_cli_check_emit_build_and_run(self):
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "main.hf"
            source.write_text(self.SOURCE, encoding="utf-8")
            llvm = directory / "main.ll"
            executable = directory / "main"
            check = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "check", str(source)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertTrue(json.loads(check.stdout)["valid"])
            emit = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "emit-llvm", str(source), "-o", str(llvm)], capture_output=True, text=True)
            self.assertEqual(emit.returncode, 0, emit.stderr)
            self.assertIn("define i32 @main", llvm.read_text(encoding="utf-8"))
            build = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "build", str(source), "-o", str(executable)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue(executable.exists())
            run = subprocess.run([str(executable)])
            self.assertEqual(run.returncode, 42)

    def test_project_init_and_manifest_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "demo"
            init_project(root, "demo_project")
            project = load_project(root)
            self.assertEqual(project.name, "demo_project")
            self.assertEqual(project.entry.name, "main.hf")
            self.assertEqual(project.target, "x86_64-pc-linux-gnu")

    def test_legacy_tensor_frontend_remains_available(self):
        source = """
module tensor
fn infer(x: Tensor<[1, 4], f16, device=neon>) -> Tensor<[1, 4], f16> {
    let w: Tensor<[4, 4], int4, device=neon>
    let y = matmul(x, w)
}
"""
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tensor.hf"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "check", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
