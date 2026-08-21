# Holy Fitra Lightweight AI-Development Candidate Matrix

## Current development gap

Holy Fitra can already train a NumPy MLP with Adam, replay, checkpoints, and evaluation, and it can run transformer/quantized inference. It still lacks a model-development layer that lets users build compact specialized models, adapt an existing model without updating every parameter, enforce memory/latency budgets, and export a deterministic model manifest.

| Rank | Candidate | Breakthrough value | Risk | Decision |
|---:|---|---|---|---|
| 1 | Parameter-efficient LoRA adapters over dense layers | Specialize models with a tiny trainable footprint | Medium | **Selected** |
| 2 | Native model manifest and resource budget contract | Makes size/parameter/activation limits enforceable | Low | **Selected** |
| 3 | Structured sparsity masks | Reduces compute and model footprint | Medium | **Selected** |
| 4 | Adapter merge/export path | Produces standalone compact models | Medium | **Selected** |
| 5 | Deterministic model profiler | Makes tradeoffs measurable | Low | **Selected** |
| 6 | Quantization-aware training fake quantization | Better int4/int8 accuracy | High | Defer |
| 7 | Knowledge distillation trainer | Small student models | Medium/high | Defer |
| 8 | Neural architecture search under budget | Automated compact design | High | Defer |
| 9 | Low-rank optimizer state | Lower training memory | Medium | Defer |
| 10 | Structured pruning trainer | Smaller models | Medium | Defer |
| 11 | Dataset streaming and bucketing | Larger training sets | Medium | Defer |
| 12 | Adapter composition/router | Multi-domain specialization | High | Defer |
| 13 | Mixed-precision training scaler | Faster/cheaper training | High | Defer |
| 14 | Native ONNX/TFLite exporter | Wider deployment | High/toolchain-dependent | Defer |
| 15 | Self-generating model compiler | Full AI synthesis loop | Very high | Defer |

## Selected foundation

Implement a dependency-free `holyfitra_model_dev.py` layer around the existing trainable MLP. It will provide trainable low-rank adapters, frozen-base versus trainable-parameter accounting, deterministic magnitude pruning, model/resource manifests, adapter merge/export, and hard resource-budget checks. Existing copy/default behavior stays unchanged. Retain only if adapter training changes outputs, updates far fewer parameters than the dense base, pruning and manifests are deterministic, merged output matches the adapter path, and all regression/native/Termux gates pass.


## Verification results

The selected foundation was implemented in `holyfitra_model_dev.py` and validated on the x86-64 sandbox. The benchmark used a 16×8 frozen dense base, rank-2 LoRA adapter, 64 examples, 180 Adam updates, and a deterministic 25% base-weight pruning request.

| Measurement | Result |
|---|---:|
| Initial MSE | 0.1532496512 |
| Final MSE | 0.0827450603 |
| MSE reduction | 46.0% |
| Frozen-base parameters | 136 |
| Trainable LoRA parameters | 48 |
| Trainable ratio of total parameters | 26.09% |
| Weight bytes in manifest | 544 |
| Actual pruning sparsity | 25.00% (32 of 128 base weights) |
| Adapter-path vs merged-weight maximum absolute error | 0.0 |
| Deliberately undersized budget rejected | Yes |

The focused model-development suite passed 4 tests, the combined learning/model-development suite passed 9 tests, and the complete applicable Python regression suite passed **145 tests with 0 failures**. The Termux-compatible host gate passed 106 tests, compiler/runtime workflows, NibbleFlow numerical validation, AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler execution, and CLI project workflows. The requested ragged scheduler ASAN/UBSAN executable passed, and the sanitized NibbleFlow shared-library build succeeded at 47,920 bytes.

The benchmark and native checks were performed on the x86-64 sandbox. AArch64 cross-compilation and object emission are artifact validation only; no physical Android device execution, Android latency, thermal, battery, or throughput measurement is claimed.

## Retention decision

**Retain.** The milestone adds an actual frozen-base/trainable-adapter path, deterministic pruning, merge-equivalent export behavior, explicit model manifests, and fail-closed resource contracts without weakening existing safety or quantization gates. Future milestones should add dataset pipelines, knowledge distillation, quantization-aware training, and deterministic deployment export while preserving the same regression and native-gate policy.
