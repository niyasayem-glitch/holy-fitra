from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from holy_fitra_execution_plan import CorePolicy, KernelCandidate, PlanConstraints, Precision
from holyfitra_ai_pipeline import VerifiedAIPipeline
from holyfitra_adapter_residency import AdapterArtifact, AdapterMode, AdapterResidencyPolicy
from holyfitra_data import StreamingDataset
from holyfitra_deploy import load_deployment
from holyfitra_agent_receipt import AgentApproval, AgentBudget, AgentEvidence, AgentPlanReceipt
from holyfitra_learning import TrainableMLP
from holyfitra_kv_residency import KVPrecision, KVResidencyPolicy
from holyfitra_model_capsule import CapsuleError, StreamedInferenceError, export_pipeline_capsule, open_model_capsule
from holyfitra_streamed_native import StreamedNativeKernel
from holyfitra_qat import QuantizationQualityGate, QuantizationSpec
from holyfitra_tensor_contracts import TensorContract, TensorResourceContract

DEPLOYMENT_KEY = b"holyfitra-capsule-deployment-test-key-v1"
CAPSULE_KEY = b"holyfitra-capsule-index-test-key-v1"


class ModelCapsuleTests(unittest.TestCase):
    def _pipeline_result(self, directory: str):
        inputs = np.arange(512, dtype=np.float32).reshape(8, 64) / 64.0
        targets = inputs[:, :8] * 0.5
        dataset = StreamingDataset.from_arrays(inputs, targets, seed=4, name="capsule.validation")
        pipeline = VerifiedAIPipeline(dataset)
        model = TrainableMLP(64, 128, 8, seed=8)
        candidate = KernelCandidate("capsule.int8.reference", Precision.INT8, 1, 0.0, 1.0, 32_768, 1.0, (CorePolicy.ANY,), "proof:capsule")
        return pipeline.export_verified(
            model,
            str(Path(directory) / "model.hfbin"),
            signing_key=DEPLOYMENT_KEY,
            weight_spec=QuantizationSpec(bits=8, axis=0),
            quality_gate=QuantizationQualityGate(max_mse=1.0, max_abs_error=1.0),
            candidates=(candidate,),
            constraints=PlanConstraints(max_mse=1.0, memory_budget_bytes=65_536, energy_budget=2.0),
            max_mse=10.0,
            max_mae=10.0,
            max_abs_allowed=10.0,
        )

    def test_capsule_loads_chunks_lazily_and_reconstructs_verified_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            contract = TensorResourceContract((TensorContract("input", (1, 64), "f32", device="neon"), TensorContract("output", (1, 8), "f32", device="neon")), memory_budget_bytes=65_536, max_energy=2.0)
            digest = "c" * 64
            agent_receipt = AgentPlanReceipt(("model.predict.local",), AgentBudget(1, 6, 4, 1000), (AgentEvidence("scorer", digest), AgentEvidence("proposals", digest)), (AgentApproval("verifier", 1), AgentApproval("governor", 1)), digest)
            kv_policy = KVResidencyPolicy(4_096, 8, 16, (KVPrecision.FP16, KVPrecision.INT8, KVPrecision.INT4), 0.80, 0.10)
            adapter_payload = b"capsule-adapter-payload-v1"
            adapter_policy = AdapterResidencyPolicy(result.artifact.digest, 4_096, 2, 1, 16, (AdapterMode.LOW_RANK,))
            adapter_artifact = AdapterArtifact("adapter.capsule", result.artifact.digest, hashlib.sha256(adapter_payload).hexdigest(), len(adapter_payload), 64, 128, 2, 4.0, AdapterMode.LOW_RANK)
            artifact = export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, chunk_bytes=1_024, resource_contract=contract, agent_receipt=agent_receipt, kv_residency_policy=kv_policy, adapter_residency_policy=adapter_policy, adapter_artifacts=(adapter_artifact,), adapter_payloads={"adapter.capsule": adapter_payload}, deployment_signing_key=DEPLOYMENT_KEY, stream_block_columns=16)
            capsule = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY, cache_chunks=2)
            self.assertEqual(capsule.cached_chunk_count, 0)
            deployment_chunks = tuple(name for name in capsule.chunk_names if name.startswith("deployment/"))
            self.assertGreater(len(deployment_chunks), 1)
            self.assertEqual(b"".join(capsule.iter_deployment_chunks()), Path(result.artifact.path).read_bytes())
            self.assertLessEqual(capsule.cached_chunk_count, 2)
            plan = capsule.execution_plan_json()
            self.assertEqual(plan["plan_id"], result.plan.plan_id)
            self.assertLessEqual(capsule.cached_chunk_count, 2)
            bundle = capsule.load_deployment(signing_key=DEPLOYMENT_KEY)
            inputs = np.zeros((1, 64), dtype=np.float32)
            expected = load_deployment(result.artifact.path, signing_key=DEPLOYMENT_KEY).predict(inputs)
            np.testing.assert_allclose(bundle.predict(inputs), expected)
            self.assertEqual(capsule.manifest["deployment_hash"], result.artifact.digest)
            self.assertEqual(capsule.resource_contract_json()["required_kernel_abi"], 1)
            self.assertEqual(capsule.agent_receipt_json()["schema"], "holyfitra.agent-plan-receipt/v1")
            self.assertEqual(capsule.kv_residency_policy(), kv_policy)
            self.assertEqual(capsule.kv_residency_policy_json()["schema"], "holyfitra.kv-residency-policy/v1")
            self.assertEqual(capsule.adapter_residency_policy(), adapter_policy)
            self.assertEqual(capsule.adapter_catalog().adapters, (adapter_artifact,))
            self.assertEqual(capsule.read_adapter_payload("adapter.capsule"), adapter_payload)
            streamed = capsule.open_streamed_mlp()
            capsule.deployment_bytes = lambda: self.fail("streamed inference must not reassemble deployment bytes")
            np.testing.assert_allclose(streamed.predict(inputs), expected, rtol=1e-6, atol=1e-6)
            self.assertFalse(streamed.uses_full_reassembly)
            self.assertGreater(streamed.loaded_block_count, 1)
            self.assertLessEqual(capsule.cached_chunk_count, 2)
            self.assertGreater(artifact.bytes_written, result.artifact.bytes_written)

    def test_capsule_rejects_wrong_key_and_lazy_chunk_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, chunk_bytes=1_024)
            with self.assertRaises(CapsuleError):
                open_model_capsule(capsule_path, signing_key=b"wrong-capsule-signing-key")
            capsule = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY)
            first_chunk = next(name for name in capsule.chunk_names if name.startswith("deployment/"))
            offset = capsule._chunks[first_chunk].offset
            raw = bytearray(capsule_path.read_bytes())
            raw[offset] ^= 1
            capsule_path.write_bytes(raw)
            with self.assertRaises(CapsuleError):
                capsule.read_chunk(first_chunk)

    def test_capsule_rejects_incomplete_or_tampered_adapter_residency_data(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            adapter_payload = b"tamper-resistant-adapter"
            policy = AdapterResidencyPolicy(result.artifact.digest, 4_096, 2, 1, 16, (AdapterMode.LOW_RANK,))
            adapter = AdapterArtifact("adapter.tamper", result.artifact.digest, hashlib.sha256(adapter_payload).hexdigest(), len(adapter_payload), 64, 128, 2, 4.0, AdapterMode.LOW_RANK)
            with self.assertRaises(CapsuleError):
                export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, adapter_residency_policy=policy)
            export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, adapter_residency_policy=policy, adapter_artifacts=(adapter,), adapter_payloads={adapter.adapter_id: adapter_payload})
            capsule = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY)
            raw = bytearray(capsule_path.read_bytes())
            raw[capsule._chunks["adapter/adapter.tamper/payload.bin"].offset] ^= 1
            capsule_path.write_bytes(raw)
            with self.assertRaises(CapsuleError):
                capsule.read_adapter_payload("adapter.tamper")

    def test_streamed_layer_inference_rejects_lazy_block_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, chunk_bytes=1_024, deployment_signing_key=DEPLOYMENT_KEY, stream_block_columns=16)
            capsule = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY, cache_chunks=1)
            stream_chunk = next(name for name in capsule.chunk_names if name.startswith("stream/hidden.weight/"))
            raw = bytearray(capsule_path.read_bytes())
            raw[capsule._chunks[stream_chunk].offset] ^= 1
            capsule_path.write_bytes(raw)
            with self.assertRaises(CapsuleError):
                capsule.open_streamed_mlp().predict(np.zeros((1, 64), dtype=np.float32))

    def test_streamed_layer_inference_rejects_unsafe_inputs_and_incomplete_stream_request(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            with self.assertRaises(CapsuleError):
                export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, deployment_signing_key=DEPLOYMENT_KEY)
            export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, chunk_bytes=1_024, deployment_signing_key=DEPLOYMENT_KEY, stream_block_columns=16)
            stream = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY, cache_chunks=1).open_streamed_mlp()
            with self.assertRaises(StreamedInferenceError):
                stream.predict(np.full((1, 64), np.nan, dtype=np.float32))
            with self.assertRaises(StreamedInferenceError):
                stream.predict(np.zeros((1, 63), dtype=np.float32))

    @unittest.skipUnless(shutil.which("clang"), "clang is required for the native streamed-kernel bridge test")
    def test_streamed_layer_inference_matches_optional_native_scalar_backend(self):
        source_root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "libholyfitra_streamed_native.so"
            subprocess.run(
                ["clang", "-shared", "-fPIC", "-O2", "-I", str(source_root), str(source_root / "holy_fitra_streamed_neon.c"), "-lm", "-o", str(library_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = self._pipeline_result(directory)
            capsule_path = Path(directory) / "model.hfcaps"
            export_pipeline_capsule(result, capsule_path, signing_key=CAPSULE_KEY, chunk_bytes=1_024, deployment_signing_key=DEPLOYMENT_KEY, stream_block_columns=16)
            inputs = np.arange(128, dtype=np.float32).reshape(2, 64) / 64.0
            reference = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY, cache_chunks=1).open_streamed_mlp()
            native = open_model_capsule(capsule_path, signing_key=CAPSULE_KEY, cache_chunks=1).open_streamed_mlp(StreamedNativeKernel(library_path))
            np.testing.assert_allclose(native.predict(inputs), reference.predict(inputs), rtol=1e-6, atol=1e-6)
            self.assertEqual(native.backend_name, "native-scalar")
            self.assertEqual(reference.backend_name, "numpy-reference")


if __name__ == "__main__":
    unittest.main(verbosity=2)
