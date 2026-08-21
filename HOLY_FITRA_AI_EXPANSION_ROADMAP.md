# Holy Fitra AI Expansion Roadmap

## Strategic direction

Holy Fitra already contains useful pieces across datasets, supervised learning, reinforcement learning, LoRA, pruning, quantization-aware training, speculative decoding, vector memory, evidence verification, deployment artifacts, execution plans, Android kernels, and thermal-aware scheduling. The missing capability is **cross-lifecycle composition**: a trained model should carry deterministic lineage, quality evidence, resource metadata, deployment identity, and a verified runtime execution plan from data ingestion through Android execution.

The expansion therefore prioritizes integration and proof-carrying artifacts over isolated feature count.

## Ranked architecture investments

| Rank | Investment | AI lifecycle impact | Safety/evidence value | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Training-to-deployment lineage and verified execution-plan bridge | Connects data, training, QAT, export, inference, and Android policy | High | Medium | **Implement first** |
| 2 | Deterministic evaluation suite with regression thresholds and best-checkpoint selection | Prevents quality regressions during training and quantization | High | Low/medium | Implement in same wave |
| 3 | Dataset schema/version/fingerprint contracts | Makes training reproducible and detects data drift | High | Low | Implement in same wave |
| 4 | Model registry with content-addressed manifests and parent lineage | Enables reproducible model families, adapters, pruned variants, and deployments | High | Medium | Implement after bridge |
| 5 | Distillation and teacher/student quality gates | Produces lighter models for Android with explicit accuracy proof | High | Medium/high | Next wave |
| 6 | First-class multimodal tensor and ragged-sequence abstractions | Broadens language support beyond MLP and transformer fixtures | Medium/high | High | Later |
| 7 | Agent planning graph with typed tool/evidence/capability edges | Makes multi-step agents auditable and resource-bounded | High | High | Next safety wave |
| 8 | Retrieval evaluation and provenance-aware memory compaction | Improves RAG quality without accepting unsupported claims | High | Medium | Next agent wave |
| 9 | Full RL environments, policy/value networks, and safe offline updates | Extends current threshold-only RL into model-development capability | Medium/high | High | Later |
| 10 | Kernel autotuning with measured device profiles | Improves ARM64 performance under thermal and energy constraints | Medium | High and device-dependent | Later; no fabricated measurements |
| 11 | ONNX/StableHLO/native model import contracts | Broadens interoperability | Medium | High dependency surface | Later |
| 12 | Compiler-native AI declarations and effect types | Makes model/evidence/resource contracts part of Holy Fitra syntax | Very high | Very high | After self-hosted semantic core |

## Selected implementation: proof-carrying AI pipeline

The first implementation wave introduces a small `holyfitra_ai_pipeline.py` integration layer with four deterministic artifacts:

| Artifact | Role |
|---|---|
| `DatasetFingerprint` | Captures dataset name, shapes, cardinality, seed, and content digest |
| `EvaluationReport` | Stores finite MSE, MAE, max error, sample count, and pass/fail thresholds |
| `ModelLineage` | Binds model identity to dataset, training configuration, parent model, and evaluation reports |
| `VerifiedAIPipeline` | Evaluates a model, exports it through the existing QAT/deployment gate, creates kernel candidates, compiles a verified execution plan, and returns a canonical pipeline receipt |

The bridge must reject non-finite metrics, empty evaluation data, mismatched model dimensions, missing proof hashes, invalid resource budgets, stale dataset fingerprints, and execution plans whose model hash does not match the exported artifact. Every canonical artifact is JSON-stable and content-addressed.

## End-to-end lifecycle

```text
StreamingDataset
    │ validate shapes, finiteness, seed, and fingerprint
    ▼
TrainableMLP / LoRAAdapter / QuantizationAwareMLP
    │ evaluate against frozen validation set
    ▼
EvaluationReport
    │ enforce MSE/MAE/max-error thresholds
    ▼
export_mlp + QuantizationQualityGate
    │ canonical deployment digest
    ▼
ModelLineage
    │ model hash + dataset fingerprint + training/config/evaluation metadata
    ▼
KernelCandidate set
    │ ABI, precision, proof hash, memory, energy, quality
    ▼
PlanCompiler
    │ thermal/core/deadline/resource constraints
    ▼
ExecutionPlan + PipelineReceipt
    │ verify identity, proof, quality, and resource bounds
    ▼
Android/host inference runtime
```

## Later AI language surface

After the self-hosted semantic core is stable, the language can expose typed declarations such as:

```holyfitra
model TinyClassifier {
    input: tensor[f32, 784]
    hidden: dense[784, 128, activation=relu]
    output: dense[128, 10]
    quantization: int4 quality(mse <= 0.01, max_abs <= 0.2)
    budget: memory <= 128KB, latency <= 5ms
}

train TinyClassifier on dataset.train
validate TinyClassifier against dataset.validation
export TinyClassifier target android.arm64 with proof
```

These declarations should lower into the same ordinary type, effect, resource, and execution-plan contracts rather than bypassing them. This syntax is deliberately deferred until the compiler can represent typed tensors, resource expressions, and diagnostics natively.

## Quality gates

The AI expansion is retained only when the following conditions hold:

| Gate | Requirement |
|---|---|
| Dataset | Shapes, finiteness, seed, cardinality, and fingerprint are valid |
| Training | Checkpoint and optimizer state are serializable and finite |
| Evaluation | Metrics are finite and threshold checks pass on a deterministic validation stream |
| Quantization | Calibration quality gate passes; no silent precision degradation |
| Deployment | Artifact digest is stable across repeated export and load/predict round trips |
| Lineage | Dataset, model, parent, training, evaluation, and deployment identities agree |
| Execution | Kernel ABI, proof hash, memory, energy, thermal, and core constraints pass |
| Agent safety | Tool capabilities and claim verification remain fail-closed |
| Android boundary | AArch64 artifacts are labeled cross-compilation only unless a real device run exists |

## Next frontier after this wave

The next strongest extension is distillation with a frozen teacher, deterministic calibration batches, and a quality gate comparing teacher/student outputs. After that, the agent layer should gain a typed plan graph where retrieval, claim verification, tool invocation, and model execution are explicit audited edges. Full multimodal and compiler-native AI syntax should wait until the self-hosted HIR/type system can represent these contracts without special-case metadata.
