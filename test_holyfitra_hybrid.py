#!/usr/bin/env python3
from __future__ import annotations
import time
import unittest
from threading import Event
from holyfitra_hybrid import HybridFunctionError, TypedReducer, hybrid, parallel_hybrid


def double(value: int) -> int:
    return value * 2


def increment(value: int) -> int:
    return value + 1


def widen(left: int, right: int) -> int:
    return left + right


def branch_slow(value: int) -> int:
    time.sleep(0.06)
    return value + 10


def branch_fast(value: int) -> int:
    time.sleep(0.01)
    return value + 20


def branch_fail(value: int) -> int:
    raise RuntimeError(f"bad branch {value}")


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

    def test_parallel_branches_reduce_deterministically(self):
        reducer = TypedReducer(lambda values: tuple(values), int, tuple, name="ordered_tuple")
        fanout = parallel_hybrid("fanout", branch_slow, branch_fast, reducer=reducer, max_workers=2)
        started = time.perf_counter()
        result = fanout(5)
        elapsed = time.perf_counter() - started
        self.assertEqual(result, (15, 25))
        self.assertLess(elapsed, 0.12)
        self.assertEqual(fanout.describe()["mode"], "parallel")
        self.assertEqual(fanout.describe()["reducer"], "ordered_tuple")

    def test_parallel_reducer_type_and_cancellation_contracts(self):
        reducer = TypedReducer(sum, int, int, name="sum_ints")
        fanout = parallel_hybrid("sum_fanout", double, increment, reducer=reducer)
        self.assertEqual(fanout(3), 10)
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(HybridFunctionError):
            fanout(3, cancel_event=cancelled)
        with self.assertRaises(HybridFunctionError):
            parallel_hybrid("bad_workers", double, increment, reducer=reducer, max_workers=33)

    def test_parallel_branch_failure_is_wrapped_and_fail_closed(self):
        reducer = TypedReducer(sum, int, int, name="sum_ints")
        fanout = parallel_hybrid("failing_fanout", double, branch_fail, reducer=reducer)
        with self.assertRaisesRegex(HybridFunctionError, "hybrid branch failed"):
            fanout(3)

    def test_hybrid_metadata_and_reducer_types_fail_closed(self):
        with self.assertRaises(HybridFunctionError):
            TypedReducer(sum, (int, 1), int)
        reducer = TypedReducer(sum, int, int)
        with self.assertRaises(HybridFunctionError):
            parallel_hybrid("float_workers", double, increment, reducer=reducer, max_workers=1.5)
        with self.assertRaises(HybridFunctionError):
            hybrid("bad_effect", double, increment, effects=("",))

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
