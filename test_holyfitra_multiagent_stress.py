from __future__ import annotations

import unittest

from holyfitra_multiagent_stress import LocalNeuralMultiAgentStress, MultiAgentStressConfig, MultiAgentStressError, stress_tasks

TEST_SIGNING_KEY = b"holyfitra-local-multiagent-test-key-v1"


class LocalNeuralMultiAgentStressTests(unittest.TestCase):
    def test_deterministic_read_only_coordination(self):
        config = MultiAgentStressConfig(task_count=12, max_workers=3, work_iterations=4, max_elapsed_seconds=10.0)
        first = LocalNeuralMultiAgentStress(TEST_SIGNING_KEY, config).run(stress_tasks(12))
        second = LocalNeuralMultiAgentStress(TEST_SIGNING_KEY, config).run(stress_tasks(12))
        self.assertEqual(first.proposal_count, 12 * 6)
        self.assertEqual(first.report_digest, second.report_digest)
        self.assertEqual(first.scorer_digest, second.scorer_digest)
        self.assertEqual(first.side_effects, ())

    def test_policy_refuses_external_mutation_and_excessive_work(self):
        config = MultiAgentStressConfig(task_count=2, max_workers=2, work_iterations=2, max_elapsed_seconds=10.0)
        system = LocalNeuralMultiAgentStress(TEST_SIGNING_KEY, config)
        with self.assertRaises(MultiAgentStressError):
            system.run(("publish a model",))
        with self.assertRaises(MultiAgentStressError):
            system.run(stress_tasks(3))

    def test_policy_rejects_unicode_and_punctuation_filter_bypasses(self):
        system = LocalNeuralMultiAgentStress(TEST_SIGNING_KEY, MultiAgentStressConfig(task_count=2, max_workers=2, work_iterations=2, max_elapsed_seconds=10.0))
        for task in ("pu\u200bsh a model", "p.u.s.h a model", "write\u200b file", "w r i t e file", "evaluate\nlocal work"):
            with self.subTest(task=task):
                with self.assertRaises(MultiAgentStressError):
                    system.run((task,))

    def test_generator_consumption_stops_at_task_budget(self):
        system = LocalNeuralMultiAgentStress(TEST_SIGNING_KEY, MultiAgentStressConfig(task_count=2, max_workers=2, work_iterations=2, max_elapsed_seconds=10.0))
        with self.assertRaises(MultiAgentStressError):
            system.run(("safe local neural evaluation" for _ in range(3)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
