from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from holyfitra_ai_pipeline import AIPipelineError, VerifiedAIPipeline
from holy_fitra_execution_plan import CorePolicy, KernelCandidate, PlanConstraints, Precision
from holyfitra_learning import TrainableMLP
from holyfitra_qat import QuantizationQualityGate, QuantizationSpec
from holyfitra_data import StreamingDataset


class HolyFitraAIPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        inputs = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
        targets = np.asarray([[0.0], [1.0], [1.0], [2.0]], dtype=np.float32)
        self.dataset = StreamingDataset.from_arrays(inputs, targets, seed=17, name="linear.validation")
        self.model = TrainableMLP(2, 4, 1, seed=3)

    def _candidate(self) -> KernelCandidate:
        return KernelCandidate(
            name="holyfitra.mlp.int8.reference",
            precision=Precision.INT8,
            abi_version=1,
            calibration_mse=0.0,
            max_mse=1.0,
            memory_bytes=4096,
            estimated_energy=1.0,
            supported_cores=(CorePolicy.ANY,),
            proof_hash="proof:reference:int8",
        )

    def _pipeline(self) -> VerifiedAIPipeline:
        return VerifiedAIPipeline(self.dataset)

    def test_fingerprint_is_deterministic_and_content_bound(self):
        first = self._pipeline().fingerprint()
        second = self._pipeline().fingerprint()
        self.assertEqual(first, second)
        changed = StreamingDataset.from_arrays(self.dataset.to_arrays()[0], self.dataset.to_arrays()[1] + 1.0, seed=17, name="linear.validation")
        self.assertNotEqual(first.digest, VerifiedAIPipeline(changed).fingerprint().digest)

    def test_pipeline_connects_evaluation_export_lineage_and_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._pipeline().export_verified(
                self.model,
                str(Path(temporary) / "model.hfbin"),
                weight_spec=QuantizationSpec(bits=8, axis=0),
                quality_gate=QuantizationQualityGate(max_mse=1.0, max_abs_error=1.0),
                candidates=[self._candidate()],
                constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=8192, energy_budget=2.0),
                training_config={"epochs": 2, "seed": 3},
                metadata={"task": "linear-regression"},
                max_mse=10.0,
                max_mae=10.0,
                max_abs_allowed=10.0,
            )
            result.verify()
            self.assertEqual(result.plan.model_hash, result.artifact.digest)
            self.assertEqual(result.lineage.deployment_hash, result.artifact.digest)
            self.assertEqual(result.lineage.dataset_digest, result.dataset.digest)
            self.assertTrue(result.digest())

    def test_repeated_export_has_stable_pipeline_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            kwargs = dict(
                weight_spec=QuantizationSpec(bits=8, axis=0),
                quality_gate=QuantizationQualityGate(max_mse=1.0, max_abs_error=1.0),
                candidates=[self._candidate()],
                constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=8192, energy_budget=2.0),
                training_config={"epochs": 2, "seed": 3},
                max_mse=10.0,
                max_mae=10.0,
                max_abs_allowed=10.0,
            )
            first = self._pipeline().export_verified(self.model, str(Path(temporary) / "a.hfbin"), **kwargs)
            second = self._pipeline().export_verified(self.model, str(Path(temporary) / "b.hfbin"), **kwargs)
            self.assertEqual(first.artifact.digest, second.artifact.digest)
            self.assertEqual(first.plan.plan_id, second.plan.plan_id)
            self.assertEqual(first.digest(), second.digest())

    def test_failed_quality_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(AIPipelineError):
                self._pipeline().export_verified(
                    self.model,
                    str(Path(temporary) / "model.hfbin"),
                    weight_spec=QuantizationSpec(bits=8, axis=0),
                    quality_gate=QuantizationQualityGate(max_mse=1.0, max_abs_error=1.0),
                    candidates=[KernelCandidate("missing-proof", Precision.INT8, 1, 0.0, 1.0, 4096, 1.0, proof_hash="")],
                    constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=8192, energy_budget=2.0),
                    training_config={},
                    max_mse=10.0,
                    max_mae=10.0,
                    max_abs_allowed=10.0,
                )


if __name__ == "__main__":
    unittest.main()
