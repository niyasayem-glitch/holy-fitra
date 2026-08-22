#!/usr/bin/env python3
from __future__ import annotations

import unittest

from hyperc_language_core import compile_source, parse_module


class LanguageCoreTests(unittest.TestCase):
    def test_valid_tensor_program_lowers_to_neon_kernel(self):
        source = '''
module test
fn infer(x: Tensor<[1, 4], f16, device=neon>) -> Tensor<[1, 4], f16> {
    budget memory <= 32 MiB
    let w: Tensor<[4, 4], int4, device=neon>
    let y = matmul(x, w)
}
'''
        result = compile_source(source)
        self.assertTrue(result["valid"])
        self.assertEqual(result["lowered_plan"][0]["kernel"], "neon.f16_matmul")
        self.assertEqual(result["functions"]["infer"]["budgets"][0]["unit"], "MiB")

    def test_garbage_and_unterminated_input_fail_closed(self):
        for source in ("garbage syntax", "module x\nnot valid", "fn infer(x: Tensor<[1, 4], f16>) -> Tensor<[1, 4], f16> {\n"):
            module = parse_module(source)
            self.assertFalse(module.valid)
            self.assertTrue(module.diagnostics)

    def test_trailing_unknown_syntax_and_duplicate_functions_fail(self):
        trailing = parse_module("fn infer(x: Tensor<[1, 4], f16>) -> Tensor<[1, 4], f16> {\n}\ntrailing junk")
        duplicate = parse_module("fn infer(x: Tensor<[1, 4], f16>) -> Tensor<[1, 4], f16> {\n}\nfn infer(x: Tensor<[1, 4], f16>) -> Tensor<[1, 4], f16> {\n}\n")
        self.assertFalse(trailing.valid)
        self.assertFalse(duplicate.valid)

    def test_shape_mismatch_is_rejected(self):
        source = '''
module bad
fn infer(x: Tensor<[1, 4], f16, device=neon>) -> Tensor<[1, 4], f16> {
    let w: Tensor<[3, 4], int4, device=neon>
    let y = matmul(x, w)
}
'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertTrue(any("dimensions" in item["message"] for item in result["diagnostics"]))

    def test_device_mismatch_is_rejected(self):
        source = '''
module bad_device
fn infer(x: Tensor<[1, 4], f16, device=cpu>) -> Tensor<[1, 4], f16> {
    let w: Tensor<[4, 4], int4, device=neon>
    let y = matmul(x, w)
}
'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertTrue(any("share a device" in item["message"] for item in result["diagnostics"]))

    def test_capability_scope_rejects_relative_path(self):
        source = '''
module unsafe
capability C {
    allow files.read("../secret")
}
'''
        module = parse_module(source)
        self.assertFalse(module.valid)
        self.assertTrue(any("absolute path" in item.message for item in module.diagnostics))

    def test_capability_and_digest_are_recorded(self):
        source = '''
module safe
capability C {
    allow files.read("/data/public/")
    deny files.write
}
fn noop() -> void {
}
'''
        module = parse_module(source)
        self.assertTrue(module.valid)
        self.assertIn("C", module.ir.policies)
        self.assertEqual(len(module.ir.policies["C"].allow), 1)
        self.assertEqual(len(module.ir.policies["C"].deny), 1)
        self.assertEqual(len(module.ir.digest()), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
