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
| 6 | Quantization-aware training with explicit fake-quantization quality gates | Better int4/int8 accuracy without silent degradation | High | **Selected and retained** |
| 7 | Knowledge distillation trainer | Small student models | Medium/high | Defer |
| 8 | Neural architecture search under budget | Automated compact design | High | Defer |
| 9 | Low-rank optimizer state | Lower training memory | Medium | Defer |
| 10 | Structured pruning trainer | Smaller models | Medium | Defer |
| 11 | Dataset streaming and deterministic batching | Larger training sets with reproducible training | Medium | **Selected and retained** |
| 12 | Adapter composition/router | Multi-domain specialization | High | Defer |
| 13 | Mixed-precision training scaler | Faster/cheaper training | High | Defer |
| 14 | Deterministic Holy Fitra deployment exporter | Reproducible compact artifacts with verified round trips | Medium | **Selected and retained** |
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

**Retain.** The milestone adds an actual frozen-base/trainable-adapter path, deterministic pruning, merge-equivalent export behavior, explicit model manifests, and fail-closed resource contracts without weakening existing safety or quantization gates. Future milestones should add knowledge distillation, quantization-aware training, and deterministic deployment export while preserving the same regression and native-gate policy.

## Dataset pipeline verification

The next model-development sequence is now implemented in `holyfitra_data.py` and integrated into `holyfitra_learning.py`.
 `StreamingDataset` accepts repeatable factories or reusable iterables, validates fixed-shape finite float32 samples, performs deterministic hash-based train/validation assignment, and emits fixed-size `Batch` records. Shuffling uses a bounded buffer and a deterministic per-seed/per-epoch generator, so large or reopenable sources do not need to be materialized. `train_supervised_streaming` and `evaluate_streaming_mse` connect the stream to the existing Tensor/Adam and bounded replay path.

The focused dataset suite passed 6 tests, the combined dataset/model-development/learning suite passed 15 tests, and the complete applicable Python regression suite passed **151 tests with 0 failures**. The Termux-compatible host gate passed **112 tests**, plus compiler/runtime workflows, NibbleFlow numerical validation, AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler execution, and CLI project workflows. The module was added to `pyproject.toml`, and `test_holyfitra_data.py` is now part of `termux-build.sh --host-tests`.

The validation ran on the x86-64 sandbox. No physical Android device, thermal, battery, latency, or throughput measurement is claimed.

## Dataset retention decision

**Retain.** The pipeline is deterministic, bounded-memory for source traversal and shuffle buffering, fail-closed on malformed/non-finite samples, compatible with existing replay and checkpoint-aware training, and covered by full regression plus Termux-native gates.

## Quantization-aware training and deployment verification

The QAT milestone is implemented in `holyfitra_qat.py`. Symmetric int4 and int8 fake quantization supports scalar or per-axis scales, packed int4 storage, explicit MSE and maximum-error measurements, and a straight-through estimator for training. `QuantizationQualityGate` fails closed when either quality limit is exceeded. `QuantizationAwareMLP` applies fake-quantized weights, with optional fake-quantized activations, while retaining the existing Tensor/Adam parameter interface.

`holyfitra_deploy.py` adds a versioned `HOLYFITRA` binary artifact. Export uses canonical JSON metadata, fixed array ordering, little-endian payloads, explicit quantization scales and quality contracts, atomic publication, and a SHA-256 artifact identity. The loader validates magic, version, model dimensions, array order, payload sizes, and quantization metadata before reconstructing a dependency-free deployment bundle.

The focused QAT/deployment suite passed 5 tests, the full applicable Python regression suite passed **156 tests with 0 failures**, and the Termux-compatible host gate passed **117 tests**. Deterministic export produced byte-identical artifacts and equal digests; loaded predictions matched the QAT path within the tested tolerance; int4 quality-gate rejection and malformed-input protections passed. Existing NibbleFlow, AArch64 object emission, ragged scalar/NEON/SVE, scheduler, and CLI validations also passed.

Validation was performed on the x86-64 sandbox. The native checks validate existing generated artifacts and host execution paths; no physical Android device latency, throughput, thermal, battery, or deployment claim is made.

## QAT/deployment retention decision

**Retain.** Quantization is explicit, measurable, and quality-gated rather than silently degrading model behavior. Export is deterministic and fail-closed on malformed artifacts, making the model ready for a later native Android loader without claiming that device integration has already been measured.

## Hybrid-function verification

Holy Fitra now supports first-class hybrid functions in the native language with syntax such as `hybrid fn pipeline(x: i32) -> i32 using [double, increment]`. The compiler validates that at least two unique components exist, the first component matches the hybrid input signature, each later component accepts the previous result, the final result matches the declared return type, and all component effects are declared transitively. LLVM lowering emits a direct deterministic call chain, so ordinary code can call the hybrid as one function.

The dependency-free runtime module `holyfitra_hybrid.py` provides the same composition model for Python/native integration: the first callable receives the original arguments, each subsequent callable receives the prior result, and a bounded execution plan exposes component names, input arity, effects, and step budget. Invalid arity, duplicate components, missing components, recursive composition, and undersized budgets fail closed.

The focused compiler/runtime hybrid suite passed **5 tests**, the full applicable Python regression suite passed **162 tests with 0 failures**, and the Termux-compatible host gate passed **123 tests**. Existing LLVM, AArch64 object, NibbleFlow, ragged attention, scheduler, and CLI validations passed. Validation was performed on the x86-64 sandbox; no physical Android performance measurement is claimed.

## Hybrid-function retention decision

**Retain.** Hybrid functions are now directly callable, statically checked, effect-aware, deterministic, and available both in Holy Fitra source and the dependency-free runtime layer.

## Parallel hybrid branch verification

Parallel hybrids now execute independent runtime branches through a bounded thread pool and pass their results to a typed reducer. Branch results are collected in declaration order even when completion order differs, making reductions deterministic. The runtime supports pre-cancellation, branch-failure wrapping, reducer output-type checks, and a maximum of 32 workers. Compiler syntax is `hybrid parallel fn fanout(x: i32) -> i32 using [left, right] reduce combine workers=2`; compiler validation checks branch input signatures, reducer arity and types, final return type, worker bounds, and transitive effects. LLVM emission lowers the branches as independent direct calls followed by the typed reducer call.

The complete applicable Python suite passed **167 tests with 0 failures**. The Termux-compatible host gate passed **128 tests**, and the focused hybrid compiler/runtime tests passed 9 tests. Existing AArch64 object emission, NibbleFlow, ragged attention, scheduler, and CLI validations passed. Validation was performed on the x86-64 sandbox; no physical Android performance claim is made.

## Parallel hybrid retention decision

**Retain.** Parallel branches are bounded, cancelable, reducer-typed, deterministic at the reduction boundary, and fail closed on invalid signatures, worker limits, cancellation, and branch errors.


## AArch64 parallel-hybrid lowering verification

The LLVM emitter now carries the requested target triple into target-aware lowering. For `aarch64-linux-android21`, generated IR records AAPCS64 ABI intent, NEON capability metadata, and the parallel-hybrid branch-call/reducer lowering contract. The branch calls remain independent in emitted IR and the typed reducer is emitted afterward; actual runtime thread execution remains a host/runtime concern rather than an unverified device claim.

The focused compiler suite passed **23 tests**, including cross-compilation of generated parallel-hybrid LLVM IR into a non-empty AArch64 object. The complete applicable Python regression suite passed **168 tests with 0 failures**. The Termux-compatible host gate passed **129 tests**, and the requested ragged scheduler ASAN/UBSAN executable passed. Existing NibbleFlow numerical validation, AArch64 kernel object emission, ragged scalar/NEON/SVE checks, scheduler execution, and CLI workflows passed.

The validation host is x86-64. Successful AArch64 object generation is artifact evidence only; no physical Android execution, NEON runtime measurement, thermal measurement, or device throughput claim is made.

## AArch64 lowering retention decision

**Retain.** Parallel hybrid reducers now lower through the target-aware LLVM path and are cross-compiled into AArch64 objects under the declared ABI/vector metadata, while fail-closed type, effect, reducer, and worker contracts remain intact.


## Self-hosting Stage-0 seed verification

The first no-Python bootstrap compiler is implemented in `holyfitra_bootstrap.cpp` as a standalone C++17 executable. It supports the minimal scalar subset needed for the first bootstrap boundary: modules, functions, `i32`, `i64`, `bool`, `void`, typed parameters, local bindings, arithmetic, comparisons, Boolean logic, unary operators, direct calls, `if`/`else`, `while`, returns, target selection, diagnostics, and textual LLVM emission.

`bootstrap/test_bootstrap.sh` passed strict C++17 compilation, host execution with exit code 42, control-flow execution with exit code 1, fail-closed invalid-type diagnostics, AArch64 object generation, and execution with Python removed from the environment. The measured AArch64 fixture object was 1,040 bytes in the x86-64 sandbox.

This milestone is **Stage 0 only**, not a claim of a fully self-compiled compiler. The seed does not yet support strings, arrays, structs, imports, file/process APIs, effects, tasks, hybrids, tensors, or compiler-core standard-library services. The next self-hosting milestone is a minimal `compiler/main.hf` compiler core compiled by this seed, followed by Stage-1 self-rebuild and fixed-point verification.


## Aggregate seed substrate verification

The no-Python Stage-0 compiler now supports named structs, fixed arrays, string literals, aggregate constructors, indexing, field access, aggregate LLVM types, string constants, and aggregate load/store lowering. The aggregate fixture combines a `[3]i32` array, a `Pair` struct, a string value, `values[2]`, and `pair.second`, and executes with native exit code 42.

The bootstrap gate passed strict C++17 compilation, scalar and control-flow fixtures, aggregate execution, fail-closed invalid-type diagnostics, AArch64 object generation, and Python-free invocation. The full Termux-compatible host gate passed **129 tests** and included the updated aggregate bootstrap gate. The measured AArch64 fixture object was 1,040 bytes on the x86-64 sandbox.

This remains a compiler-core substrate milestone rather than a complete self-hosting claim. Dynamic arrays, pointer/handle APIs, file/process services, imports, effects, tasks, hybrids, and the `compiler/main.hf` self-hosted compiler core remain to be implemented.
