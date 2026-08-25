#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holyfitra_compiler import HolyFitraError, _MEMORY_COMPILE_CACHE, build, capabilities_report, compile_native_file, emit_llvm, init_project, inspect_file, load_project, mobile_inspect_package, parse_native, test_project, validate_native


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

    def test_constant_signed_division_matches_llvm_truncation(self):
        cases = ((-5, 2, -2), (5, -2, -2), (-5, -2, 2))
        for left, right, expected in cases:
            source = f"fn main() -> i32 {{ return {left} / {right} }}"
            program = parse_native(source)
            validate_native(program)
            self.assertIn(f"ret i32 {expected}", emit_llvm(program))
            with tempfile.TemporaryDirectory() as temporary:
                source_path = Path(temporary) / "division.hf"
                executable = Path(temporary) / "division"
                source_path.write_text(source, encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    build(source_path, executable)
                self.assertEqual(subprocess.run([str(executable)], timeout=5).returncode, expected % 256)
        with self.assertRaisesRegex(HolyFitraError, "division by zero"):
            emit_llvm(parse_native("fn main() -> i32 { return 1 / 0 }"))

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

    def test_builtin_parallel_hybrid_reducers_lower_and_run(self):
        source = """
module builtin_hybrid
fn left(x: i32) -> i32 { return x + 1 }
fn right(x: i32) -> i32 { return x * 3 }
hybrid parallel fn total(x: i32) -> i32 using [left, right] reduce builtin sum workers=2
hybrid parallel fn lowest(x: i32) -> i32 using [left, right] reduce builtin min workers=2
fn main() -> i32 { return total(7) }
"""
        program = parse_native(source)
        validate_native(program)
        llvm = emit_llvm(program)
        self.assertIn('"reducer":"builtin:sum"', llvm)
        self.assertIn("add i32", llvm)
        self.assertIn("icmp slt i32", llvm)
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "builtin.hf"
            source_path.write_text(source, encoding="utf-8")
            executable = Path(temporary) / "builtin"
            build(source_path, executable)
            run = subprocess.run([str(executable)], timeout=5)
            self.assertEqual(run.returncode, 29)

    def test_builtin_boolean_hybrid_reducers_lower_to_boolean_operations(self):
        source = """
module bool_hybrid
fn left(x: bool) -> bool { return x }
fn right(x: bool) -> bool { return true }
hybrid parallel fn every(x: bool) -> bool using [left, right] reduce builtin all workers=2
hybrid parallel fn either(x: bool) -> bool using [left, right] reduce builtin any workers=2
fn main() -> i32 { if every(true) && either(false) { return 0 } else { return 1 } }
"""
        llvm = emit_llvm(parse_native(source))
        self.assertIn("and i1", llvm)
        self.assertIn("or i1", llvm)

    def test_builtin_hybrid_reducer_contracts_fail_closed(self):
        cases = [
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i32) -> i32 { return x }\nhybrid parallel fn h(x: i32) -> i32 using [a, b] reduce builtin average\n",
            "fn a(x: bool) -> bool { return x }\nfn b(x: bool) -> bool { return x }\nhybrid parallel fn h(x: bool) -> bool using [a, b] reduce builtin sum\n",
            "fn a(x: i32) -> i32 { return x }\nfn b(x: i32) -> i32 { return x }\nhybrid parallel fn h(x: i32) -> bool using [a, b] reduce builtin any\n",
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
            self.assertEqual(payload["schema"], 3)
            self.assertEqual(payload["llvm_sha256"], hashlib.sha256(expected_llvm.encode("utf-8")).hexdigest())

    def test_comment_only_source_change_has_a_distinct_cache_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "main.hf"
            cache_dir = root / "cache"
            source.write_text(self.SOURCE, encoding="utf-8")
            _, original_llvm, original_digest = compile_native_file(source, cache_dir=cache_dir)
            _MEMORY_COMPILE_CACHE.clear()
            source.write_text(self.SOURCE + "\n// source-content cache-key regression\n", encoding="utf-8")
            _, comment_llvm, comment_digest = compile_native_file(source, cache_dir=cache_dir)
            self.assertNotEqual(original_digest, comment_digest)
            self.assertEqual(original_llvm, comment_llvm)
            self.assertTrue((cache_dir / f"{original_digest}.json").is_file())
            self.assertTrue((cache_dir / f"{comment_digest}.json").is_file())

    def test_arg_i32_bridge_parses_bounded_decimal_main_arguments(self):
        source_text = """
module dynamic_input
fn main() -> i32 effects [io] { return arg_i32(0, 7) }
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "main.hf"
            executable = root / "main"
            source.write_text(source_text, encoding="utf-8")
            program = parse_native(source_text)
            validate_native(program)
            llvm = emit_llvm(program)
            self.assertIn("define internal i32 @hf_arg_i32", llvm)
            self.assertIn("define i32 @main(i32 %hf_argc, i8** %hf_argv)", llvm)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build(source, executable), 0)
            self.assertEqual(subprocess.run([str(executable)]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "12"]).returncode, 12)
            self.assertEqual(subprocess.run([str(executable), "12x"]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "2147483648"]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "-9"]).returncode, 247)
            legacy_llvm = emit_llvm(parse_native(self.SOURCE))
            self.assertIn("define i32 @main()", legacy_llvm)

    def test_arg_i32_bridge_rejects_missing_io_and_nonliteral_position(self):
        missing_io = "fn main() -> i32 { return arg_i32(0, 7) }"
        with self.assertRaisesRegex(HolyFitraError, r"effects \[io\]"):
            validate_native(parse_native(missing_io))
        dynamic_position = "fn main() -> i32 effects [io] { let index = 0 return arg_i32(index, 7) }"
        with self.assertRaisesRegex(HolyFitraError, "literal position"):
            validate_native(parse_native(dynamic_position))
        reserved_builtin = "fn arg_i32(x: i32) -> i32 { return x } fn main() -> i32 { return 0 }"
        with self.assertRaisesRegex(HolyFitraError, "reserved"):
            validate_native(parse_native(reserved_builtin))

    def test_arg_i64_bridge_accepts_signed_bounds_and_rejects_overflow(self):
        source_text = """
module dynamic_i64
fn main() -> i32 effects [io] {
    let value = arg_i64(0, -7)
    let maximum = arg_i64(1, 9223372036854775807)
    let minimum = arg_i64(2, -9223372036854775808)
    let negative = arg_i64(3, -9)
    if value == maximum { return 11 } else {
        if value == minimum { return 12 } else {
            if value == negative { return 13 } else { return 7 }
        }
    }
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "main.hf"
            executable = root / "main"
            source.write_text(source_text, encoding="utf-8")
            program = parse_native(source_text)
            validate_native(program)
            llvm = emit_llvm(program)
            self.assertIn("define internal i64 @hf_arg_i64", llvm)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build(source, executable), 0)
            self.assertEqual(subprocess.run([str(executable)]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "9223372036854775807"]).returncode, 11)
            self.assertEqual(subprocess.run([str(executable), "-9223372036854775808"]).returncode, 12)
            self.assertEqual(subprocess.run([str(executable), "-9"]).returncode, 13)
            self.assertEqual(subprocess.run([str(executable), "9223372036854775808"]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "-9223372036854775809"]).returncode, 7)
            self.assertEqual(subprocess.run([str(executable), "12x"]).returncode, 7)

    def test_arg_i64_bridge_rejects_out_of_range_fallback(self):
        out_of_range_fallback = "fn main() -> i32 effects [io] { let value = arg_i64(0, 9223372036854775808) return 0 }"
        with self.assertRaisesRegex(HolyFitraError, "fallback must fit i64"):
            validate_native(parse_native(out_of_range_fallback))

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
            self.assertTrue((root / "tests" / "smoke.hf").is_file())

    def test_hybrid_project_template_and_inspection_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "hybrid_project"
            init_project(root, "hybrid_project", "hybrid")
            self.assertTrue((root / "hybrid" / "README.md").is_file())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(inspect_file(root), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["schema"], "holyfitra.inspect/v1")
            self.assertEqual(report["hybrids"][0]["reducer"], {"kind": "builtin", "name": "sum"})
            self.assertEqual(report["hybrids"][0]["native_parallel_execution"], "not_proven_by_scalar_ir")

    def test_mobile_bridge_package_receipt_matches_exact_studio_source(self):
        def mobile_fingerprint(value: str) -> str:
            digest = 0x811C9DC5
            encoded = value.encode("utf-16-le", errors="surrogatepass")
            for index in range(0, len(encoded), 2):
                digest ^= encoded[index] | (encoded[index + 1] << 8)
                digest = (digest * 0x01000193) & 0xFFFFFFFF
            return f"local-{digest:08x}"

        main_source = "module mobile_bridge\nfn main() -> i32 { return 0 }\n"
        extra_source = "module helpers\nfn score(x: i32) -> i32 { return x + 1 }\n"
        files = [
            {"path": "main.hf", "content": main_source},
            {"path": "helper.hf", "content": extra_source},
            {"path": "README.hfmd", "content": "# Mobile bridge\n"},
        ]
        for file in files:
            file["fingerprint"] = mobile_fingerprint(f"{file['path']}\0{file['content']}")
        workspace_fingerprint = mobile_fingerprint("\1".join(sorted(f"{file['path']}\0{file['content']}" for file in files)))
        package = {
            "format": "holyfitra.mobile-handoff.v1",
            "projectName": "Bridge test",
            "files": files,
            "toolchainBridge": {
                "format": "holyfitra.toolchain-bridge.v1",
                "entryPath": "main.hf",
                "workspaceFingerprint": workspace_fingerprint,
                "fingerprintAlgorithm": "fnv1a32-local-utf16",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            package_path = Path(temporary) / "mobile-package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(mobile_inspect_package(package_path), 0)
            receipt = json.loads(output.getvalue())
            self.assertEqual(receipt["schema"], "holyfitra.mobile-inspect-receipt.v1")
            self.assertEqual(receipt["conclusion"], "success")
            self.assertEqual(receipt["workspace_fingerprint"], workspace_fingerprint)
            self.assertEqual(receipt["unlinked_source_files"], ["helper.hf"])
            package["files"][0]["content"] = "module mobile_bridge\nfn main() -> i32 { return 1 }\n"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(mobile_inspect_package(package_path), 1)
            self.assertIn("fingerprint does not match", json.loads(output.getvalue())["error"])

    def test_ai_project_template_is_explicit_and_runnable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ai_project"
            init_project(root, "ai_project", "ai")
            source = (root / "src" / "main.hf").read_text(encoding="utf-8")
            self.assertIn("effects [model, memory]", source)
            self.assertTrue((root / "ai" / "README.md").is_file())
            self.assertEqual(test_project(root), 0)

    def test_capabilities_report_has_explicit_evidence_boundaries(self):
        report = capabilities_report()
        self.assertEqual(report["schema"], "holyfitra.capabilities/v1")
        self.assertEqual(report["android"]["supported_abi"], "arm64-v8a")
        self.assertTrue(report["evidence_boundaries"]["host_regression"])
        self.assertFalse(report["evidence_boundaries"]["thermal_throttling_device_run"])

    def test_call_arity_rejection_is_user_facing(self):
        source = "fn add(a: i32, b: i32) -> i32 { return a + b } fn main() -> i32 { return add(1) }"
        with self.assertRaisesRegex(HolyFitraError, "expects 2 arguments"):
            emit_llvm(parse_native(source))

    def test_empty_project_test_suite_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "empty_project"
            init_project(root, "empty_project")
            (root / "tests" / "smoke.hf").unlink()
            self.assertEqual(test_project(root), 1)

    def test_cross_target_project_tests_are_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "arm_project"
            init_project(root, "arm_project")
            with self.assertRaisesRegex(HolyFitraError, "requires an executable host target"):
                test_project(root, "aarch64-linux-android21")

    def test_cli_test_runs_project_smoke_suite(self):
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "test_project"
            init_project(directory, "test_project")
            completed = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "test", str(directory)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["count"], 1)
            self.assertTrue(payload["tests"][0]["passed"])

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
            result = subprocess.run([sys.executable, str(root / "holyfitra_compiler.py"), "check", "--frontend=hyperir", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_mutable_assignment_and_while_compile_and_run(self):
        source = """
module loop_test
fn countdown() -> i32 {
    var x: i32 = 3
    while x > 0 {
        x = x - 1
    }
    return x
}
fn main() -> i32 { return countdown() }
"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source_path = directory / "loop_test.hf"
            source_path.write_text(source, encoding="utf-8")
            output = directory / "loop_test"
            build(source_path, output)
            run = subprocess.run([str(output)], capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0)

    def test_assignment_to_let_is_rejected(self):
        source = "fn main() -> i32 { let x: i32 = 1 x = 2 return x }"
        with self.assertRaisesRegex(HolyFitraError, "cannot assign to immutable value"):
            validate_native(parse_native(source))

    def test_native_short_circuit_emits_cfg_phi(self):
        source = """
module short_circuit_native
fn rhs() -> bool { return true }
fn main() -> i32 {
    if false && rhs() { return 1 }
    if true || rhs() { return 0 }
    return 2
}
"""
        llvm = emit_llvm(parse_native(source))
        self.assertIn("phi i1", llvm)
        self.assertNotIn(" = and i1 ", llvm)
        self.assertNotIn(" = or i1 ", llvm)


if __name__ == "__main__":
    unittest.main(verbosity=2)
