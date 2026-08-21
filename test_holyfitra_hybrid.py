#!/usr/bin/env python3
from __future__ import annotations
import unittest
from holyfitra_hybrid import HybridFunctionError, hybrid


def double(value: int) -> int:
    return value * 2


def increment(value: int) -> int:
    return value + 1


def widen(left: int, right: int) -> int:
    return left + right


class HolyFitraHybridTests(unittest.TestCase):
    def test_direct_multi_function_composition(self):
        pipeline = hybrid("pipeline", double, increment, lambda value: value * 3, effects=("model", "memory"))
        self.assertEqual(pipeline(4), 27)
        self.assertEqual(pipeline.components, ("double", "increment", "<lambda>"))
        self.assertEqual(pipeline.effects, ("model", "memory"))
        self.assertEqual(pipeline.describe()["max_steps"], 3)

    def test_first_component_can_accept_multiple_inputs(self):
        pipeline = hybrid("sum_pipeline", widen, double)
        self.assertEqual(pipeline(4, 5), 18)

    def test_arity_and_invalid_composition_fail_closed(self):
        with self.assertRaises(TypeError):
            hybrid("pipeline", double, increment)(1, 2)
        with self.assertRaises(HybridFunctionError):
            hybrid("single", double)
        with self.assertRaises(HybridFunctionError):
            hybrid("bad", double, double)
        with self.assertRaises(HybridFunctionError):
            hybrid("too_short", double, increment, max_steps=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
