# Holy Fitra capability map

Holy Fitra is currently a **multi-layer AI-oriented language and runtime project**, not one monolithic compiler feature. The repository contains a native scalar compiler, a HyperIR/tensor-oriented frontend, a self-hosted bootstrap path, provider-neutral AI interfaces, a supervised coding agent, learning and quantization components, native kernels, Android JNI packaging, and a local Android Workbench.

The authoritative machine-readable inventory is available locally with:

```bash
holyfitra capabilities
```

## Implemented capability layers

| Layer | Current capability | Evidence status |
|---|---|---|
| Language frontend | Modules, functions, `i32`/`u32`/`i64`/`u64` scalar types, explicit `to_i32`/`to_u32`/`to_i64`/`to_u64` conversions, booleans, comparisons, logical operators, structured control flow, path-sensitive returns, constant folding, ownership modes, effects, bounded `arg_i32` and `arg_i64` command-line input for an explicit `io` main, task metadata, user-defined hybrid reducers, typed built-in hybrid reducers, and static hybrid inspection | Host regression and compiler tests; literal narrowing is range-checked, runtime narrowing is rejected, equal-width signedness conversion is explicit bit reinterpretation, and widening selects sign or zero extension; input builtins accept only bounded literal positions with fallback, and `arg_i64` checks signed bounds via i128 accumulation; neither adds general process or device I/O; scalar native lowering only |
| HyperIR/tensor frontend | Tensor-oriented source parsing, execution-plan lowering, quantization metadata, ragged/dynamic prefill surfaces, and structured contracts | Python contract and numerical test surfaces; not equivalent to full native tensor-language lowering |
| Compiler | LLVM IR emission, native build/run, cache telemetry, deterministic diagnostics, package manifests, project tests, TUI, and REPL | Host and Termux-compatible gates |
| Mobile Studio bridge | Versioned bounded Studio package, per-file and workspace fingerprint verification, `holyfitra mobile-inspect` static receipt, and user-controlled Android/iOS JSON export | Cross-contract regression and host native gate; no embedded mobile compiler or device execution claim |
| Self-hosting | C++17 seed compiler with lexer, parser, diagnostics, module/type-checking states, structured `basic`/`selfhost-core` presets, whole-tree digest manifests, portable source bundles, and AArch64 object emission | Bootstrap State 1–9 gate plus no-Python native v1 package/bundle regression |
| AI integration | Provider-neutral chat, embeddings, validated Holy Fitra generation, model selection, request boundaries, credential-safe provider status, and deterministic local UTF-8-byte causal bigram plus bounded sparse n-gram baselines with checkpoint and evaluation receipts | Unit tests and explicit provider configuration; the local baselines provide one- or bounded two-to-four-token context only, and are not transformers, Qwen comparisons, general language models, coding models, or multimodal models |
| Coding automation | Plan-first supervised agent, workspace confinement, allowlisted commands, transactional writes, rollback, improvement rounds, and high-risk branch restrictions | Unit tests and campaign dry-run gates |
| Learning | Deterministic batching, streaming datasets, replay, supervised training, threshold policy learning, checkpoints, calibration-aware quantization, and deployment manifests | Python tests and numerical checks; not a claim of production-scale training |
| Native AI runtime | NibbleFlow INT4 kernels with opt-in static-INT8 activation execution, calibration quality gates, bounded low-rank residual adapters, authenticated capsule adapter-residency lanes with rollback receipts, deterministic KV residency and precision-governor contracts, ragged kernels, a priority/deadline/core-class/thermal-aware task scheduler, bounded parallel matvec micro-batches behind one cancellable request, portable four-output tiles, compatible four-row packed-weight reuse, local per-batch range receipts, JNI wrappers, and versioned benchmark receipts | Host/native/sanitizer gates, scheduler priority/deadline and multi-producer stress checks, deterministic residency stress and capsule-tamper checks, host-only micro-batch and large-model-versus-Python/OpenBLAS benchmark evidence, AArch64 object emission when an NDK sysroot is available, and remote Android arm64-v8a package verification. A custom priority-lane scheduler did not pass its host throughput retain gate and is not retained; device performance remains unmeasured. |
| Android | arm64-v8a library, 16 KB ELF alignment, `c++_shared` packaging, installable Workbench debug APK, release APK, and AAR | Remote SDK/NDK CI; no physical-device execution in this environment |

## AI-first language direction

The highest-potential architecture is to keep the language deterministic at its core and make AI behavior explicit in the type, effect, ownership, task, and evidence systems. A future production language should add tensor shapes and dtypes to the canonical type checker, capability-secure model and tool handles, structured uncertainty with provenance, asynchronous cancellation and deadlines in the runtime, package-level dependency locking, incremental compilation across modules, and a stable native ABI for CPU, GPU, and accelerator backends.

The project should not treat a large campaign count or a generated source file as proof of production quality. Every AI-generated change must pass parsing, semantic validation, safety policy, deterministic replay, tests, and the relevant native or device gate before promotion.

## Explicit evidence boundaries

> Remote AArch64 compilation, 16 KB packaging verification, and an Android-native-process benchmark receipt schema do not prove ART/JNI lifecycle correctness, NEON throughput, big.LITTLE scheduling, thermal throttling behavior, or physical-device stability.

> Native built-in hybrid reducers lower to deterministic branch calls followed by scalar reduction. Their `workers` value is validated metadata, not evidence that the emitted scalar LLVM has launched native threads or achieved parallel speedup.

The remaining high-value proof gates are a physical ARM64 Android campaign, an Android instrumentation app that exercises library loading and JNI error paths, repeated cold/warm runs across device states, thermal and frequency capture, and comparison against a declared baseline. These are separate from the language/compiler implementation and should not be silently inferred from host results.

## Maximum-potential roadmap

| Stage | Upgrade | Acceptance gate |
|---|---|---|
| A | Stable language specification, versioned AST/IR schemas, richer type checker, module imports, and canonical diagnostics | Golden parser/type-checker suite and compatibility fixtures |
| B | First-class tensor shapes, dtype/layout constraints, ownership of model/KV buffers, and safe async model tasks | Compile-time rejection tests plus deterministic lowering snapshots |
| C | Provider/tool/model capabilities as explicit handles with consent, budgets, provenance, and fallbacks | Policy matrix, malformed-input tests, and replayable traces |
| D | Incremental self-hosted compiler core and native AArch64 lowering | Fixed-point bootstrap and object-level equivalence checks |
| E | Optimized CPU kernels, quantization calibration, scheduler policies, and device instrumentation | Native numerical checks plus physical-device benchmark evidence |
| F | Package registry, lockfiles, reproducible builds, signed artifacts, IDE/LSP support, and release channels | Clean-room install and verified artifact reproduction |
