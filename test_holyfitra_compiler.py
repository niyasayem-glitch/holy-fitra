#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holyfitra_compiler import HolyFitraError, _MEMORY_COMPILE_CACHE, compile_native_file, emit_llvm, init_project, load_project, parse_native, validate_native


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

    def test_hybrid_function_composes_multiple_typed_functions(self):
        source = """
module hybrid_test
fn double(x: i32) -> i32 { return x * 2 }
fn increment(x: i32) -> i32 { return x + 1 }
hybrid fn pipeline(x: i32) -> i32 using [double, increment]
fn main() -> i32 { return pipeline(20) }
"""
        program = parse_native(source)
        validate_native(program)
        self.assertEqual(program.functions[2].hybrid.components, ("double", "increment"))
        llvm = emit_llvm(program)
        self.assertIn('; hybrid: {"components":["double","increment"],"max_workers":1,"mode":"pipe","reducer":null}', llvm)
        self.assertIn("call i32 @double(i32 %x)", llvm)
        self.assertIn("call i32 @increment(i32 %t0)", llvm)
        self.assertIn("call i32 @pipeline(i32 20)", llvm)

    def test_parallel_hybrid_uses_typed_reducer_and_direct_branch_calls(self):
        source = """
module parallel_hybrid
fn left(x: i32) -> i32 effects [model] { return x + 1 }
fn right(x: i32) -> i32 effects [memory] { return x * 2 }
fn combine(a: i32, b: i32) -> i32 effects [model, memory] { return a + b }
hybrid parallel fn fanout(x: i32) -> i32 effects [model, memory] using [left, right] reduce combine workers=2
fn main() -> i32 effects [model, memory] { return fanout(5) }
"""
        program = parse_native(source)
        validate_native(program)
        hybrid = program.functions[3]
        self.assertEqual(hybrid.hybrid.strategy, "parallel")
        self.assertEqual(hybrid.hybrid.reducer, "combine")
        self.assertEqual(hybrid.hybrid.max_workers, 2)
        llvm = emit_llvm(program)
        self.assertIn('"mode":"parallel"', llvm)
        self.assertIn("call i32 @left(i32 %x)", llvm)
        self.assertIn("call i32 @right(i32 %x)", llvm)
        self.assertIn("call i32 @combine(i32 %t0, i32 %t1)", llvm)

    def test_parallel_hybrid_emits_aarch64_object(self):
        source = """
module arm_parallel_hybrid
fn left(x: i32) -> i32 { return x + 1 }
fn right(x: i32) -> i32 { return x * 2 }
fn combine(a: i32, b: i32) -> i32 { return a + b }
hybrid parallel fn fanout(x: i32) -> i32 using [left, right] reduce combine workers=2
fn main() -> i32 { return fanout(5) }
"""
        llvm = emit_llvm(parse_native(source), "aarch64-linux-android21")
        self.assertIn("target triple = \"aarch64-linux-android21\"", llvm)
        self.assertIn("Holy Fitra ABI: AAPCS64", llvm)
        self.assertIn("Holy Fitra vector capability: NEON", llvm)
        self.assertIn('"native_abi":"aapcs64"', llvm)
        self.assertIn('"native_lowering":"branch_calls_then_reducer"', llvm)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ll_path = directory / "parallel.ll"
            object_path = directory / "parallel.aarch64.o"
            ll_path.write_text(llvm, encoding="utf-8")
            result = subprocess.run(["clang", "--target=aarch64-linux-android21", "-c", str(ll_path), "-o", str(object_path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(object_path.stat().st_size > 0)

    def test_parallel_hybrid_contracts_fail_closed(self):
        cases = [
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i32) -> i32 { return x }\nfn r(a: i32) -> i32 { return a }\nhybrid parallel fn h(x: i32) -> i32 using [a, b] reduce r",
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i64) -> i64 { return x }\nfn r(a: i32, b: i32) -> i32 { return a + b }\nhybrid parallel fn h(x: i32) -> i32 using [a, b] reduce r",
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i32) -> i32 { return x }\nfn r(a: i32, b: i32) -> i64 { return a + b }\nhybrid parallel fn h(x: i32) -> i32 using [a, b] reduce r workers=33",
        ]
        for source in cases:
            with self.assertRaises(HolyFitraError):
                validate_native(parse_native(source))

    def test_hybrid_effects_are_transitive(self):
        source = """
module hybrid_effects
fn encode(x: i32) -> i32 effects [model] { return x }
fn guard(x: i32) -> i32 effects [memory] { return x }
hybrid fn secure(x: i32) -> i32 effects [model, memory] using [encode, guard]
fn main() -> i32 effects [model, memory] { return secure(1) }
"""
        validate_native(parse_native(source))

    def test_hybrid_contracts_fail_closed(self):
        cases = [
            "fn a(x: i32) -> i32 { return x }\nhybrid fn h(x: i32) -> i32 using [a]",
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i64) -> i64 { return x }\nhybrid fn h(x: i32) -> i32 using [a, b]",
            "hybrid fn h(x: i32) -> i32 using [missing, other]\n",
        ]
        for source in cases:
            with self.assertRaises(HolyFitraError):
                validate_native(parse_native(source))

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

    def test_control_flow_if_else_compiles_and_runs(self):
        source = (
            'module control_test\n'
            'fn choose(x: i32) -> i32 {\n'
            '    if x >= 10 {\n'
            '        return 1\n'
            '    } else {\n'
            '        return 2\n'
            '    }\n'
            '}\n'
            'fn main() -> i32 {\n'
            '    return choose(12)\n'
            '}\n'
        )
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / 'control_test.hf'
            source_path.write_text(source, encoding='utf-8')
            output = Path(temporary) / 'control_test'
            from holyfitra_compiler import build
            build(source_path, output)
            run = subprocess.run([str(output)], timeout=5)
            self.assertEqual(run.returncode, 1)

    def test_bool_literal_and_comparison_typecheck(self):
        source = (
            'module bool_test\n'
            'fn is_positive(x: i32) -> bool {\n'
            '    if x > 0 {\n'
            '        return true\n'
            '    } else {\n'
            '        return false\n'
            '    }\n'
            '}\n'
            'fn main() -> i32 { return 0 }\n'
        )
        program = parse_native(source)
        validate_native(program)
        self.assertEqual(program.functions[0].return_type.name, 'bool')

    def test_missing_else_path_is_rejected(self):
        source = (
            'module missing_else\n'
            'fn maybe(x: i32) -> i32 {\n'
            '    if x > 0 { return 1 }\n'
            '}\n'
        )
        with self.assertRaises(HolyFitraError):
            validate_native(parse_native(source))

    def test_effect_annotations_are_typed_metadata(self):
        source = (
            'module effect_test\n'
            'fn infer() -> i32 effects [model, memory] { return 7 }\n'
            'fn main() -> i32 effects [model, memory] { return infer() }\n'
        )
        program = parse_native(source)
        validate_native(program)
        self.assertEqual(program.functions[0].effects, ('model', 'memory'))
        self.assertIn('; effects: model, memory', emit_llvm(program))

    def test_unknown_effect_is_rejected(self):
        source = 'module effect_test\nfn main() -> i32 effects [telepathy] { return 0 }\n'
        with self.assertRaises(HolyFitraError):
            validate_native(parse_native(source))

    def test_recursive_effect_cycle_reports_full_deterministic_path(self):
        source = """
module cycle
fn a() -> i32 effects [model] { return b() }
fn b() -> i32 effects [model] { return a() }
fn main() -> i32 effects [model] { return a() }
"""
        with self.assertRaisesRegex(HolyFitraError, r"recursive effect cycle: a -> b -> a"):
            validate_native(parse_native(source))

    def test_ownership_and_task_annotations_are_preserved(self):
        source = (
            'module contracts_test\n'
            'fn decode(x: borrow i32) -> i32 effects [model] task [async, priority=5, deadline_ms=50, capacity=4, supervised] {\n'
            '    return x\n'
            '}\n'
            'fn main() -> i32 effects [model] { return decode(7) }\n'
        )
        program = parse_native(source)
        validate_native(program)
        function = program.functions[0]
        self.assertEqual(function.parameters[0][1].mode, 'borrow')
        self.assertTrue(function.task.async_)
        self.assertEqual(function.task.priority, 5)
        self.assertEqual(function.task.capacity, 4)
        self.assertTrue(function.task.supervised)
        llvm = emit_llvm(program)
        self.assertIn('; ownership: x:borrow', llvm)
        self.assertIn('; task:', llvm)

    def test_multiple_mutable_borrows_are_rejected(self):
        source = 'module bad\nfn main(a: borrow_mut i32, b: borrow_mut i32) -> i32 { return a }\n'
        with self.assertRaises(HolyFitraError):
            validate_native(parse_native(source))

    def test_type_error_is_rejected(self):
        source = "fn main() -> i32 { let x: i64 = 1 return x }"
        with self.assertRaises(HolyFitraError):
            validate_native(parse_native(source))

    def test_corrupt_persistent_llvm_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "main.hf"
            source.write_text(self.SOURCE, encoding="utf-8")
            cache_dir = root / "cache"
            _, expected_llvm, digest = compile_native_file(source, cache_dir=cache_dir)
            _MEMORY_COMPILE_CACHE.clear()
            cache_path = cache_dir / f"{digest}.json"
            cache_path.write_text("{broken", encoding="utf-8")
            _, rebuilt_llvm, rebuilt_digest = compile_native_file(source, cache_dir=cache_dir)
            self.assertEqual(rebuilt_digest, digest)
            self.assertEqual(rebuilt_llvm, expected_llvm)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["digest"], digest)
            self.assertEqual(payload["schema"], 1)

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
            self.assertFalse(json.loads(build.stdout)["cache_hit"])
            self.assertTrue(executable.exists())
            second = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "build", str(source), "-o", str(executable)], capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(json.loads(second.stdout)["cache_hit"])
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
