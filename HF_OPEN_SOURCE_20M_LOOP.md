# HF Open-Source Research Loop

**Start:** 2026-08-25T16:45:55Z  
**Time limit:** 20 minutes of focused landscape review, ending with one bounded adaptation at most.

## Scope

The review covers five HF-adjacent layers: native CPU/mobile inference, task scheduling and work stealing, quantization and kernel dispatch, compiler/IR incrementality, and Android/Termux packaging. It does not treat popularity as proof that a project’s code or performance transfers to HF.

## Adaptation gate

| Gate | Requirement |
|---|---|
| License | Prefer MIT, BSD-2/3-Clause, or Apache-2.0. Do not copy GPL/AGPL code into HF during this loop. |
| Provenance | Record repository URL, license, the narrow pattern adapted, and the source location or documentation that motivated it. |
| Fit | The pattern must map to an existing HF seam; no wholesale framework import or incompatible runtime dependency. |
| Verification | Add or extend focused tests and compare against an existing baseline when the change affects performance. |
| Evidence | Keep host, CI, remote AArch64 packaging, and physical Android device claims separate. |

## Candidate families

1. `llama.cpp` / `ggml` for lightweight CPU inference and Android deployment patterns.
2. `oneDNN`, `XNNPACK`, and `ExecuTorch` for bounded CPU parallelism, kernel dispatch, and mobile runtimes.
3. `Taskflow` and related task-graph schedulers for structured, cancellable work coordination.
4. LLVM/MLIR and `sccache` for compiler/IR and incremental artifact patterns.
5. Termux and Android Open Source Project documentation for packaging/lifecycle constraints.

## Runtime research findings

| Project | License / maturity | Relevant pattern | HF decision |
|---|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT; 125k+ stars; current upstream activity | Dependency-light C/C++, multi-bit quantization, backend separation, and extensive platform-specific build documentation. | Borrow design ideas only; a full GGML/GGUF import would be a separate compatibility project. |
| [XNNPACK](https://github.com/google/XNNPACK) | BSD-style source license; 2k+ stars; current activity | ARM64/mobile operator specialization, channel-stride-aware primitives, and deliberate single/multi-thread benchmark distinction. | Adopt the measurement discipline and bounded parallelism approach, not a wholesale operator dependency. |
| [ExecuTorch](https://github.com/pytorch/executorch) | BSD-style source license; 4k+ stars; current activity | Separate portable runtime, backend selection, memory planning, custom passes, and device tooling. | Defer integration; use its modular runtime/receipt separation as architectural guidance. |

The first concrete HF opportunity remains small and local: make the currently observed micro-batch scheduling policy inspectable and reproducible rather than importing another runtime. The review does not claim that external projects’ published Android results apply to HF.

## Scheduler and compiler research findings

| Project | License / maturity | Relevant pattern | HF decision |
|---|---|---|---|
| [Taskflow](https://github.com/taskflow/taskflow) | MIT source license; 12k+ stars; active releases | Structured task graphs, work stealing, task profiling, and bounded parallel primitives rather than unrestricted thread creation. | Adapt only the *observable bounded task-group* principle inside HF’s existing scheduler; do not import the framework. |
| [sccache](https://github.com/mozilla/sccache) | Apache-2.0; 7k+ stars; current activity | Compiler wrappers, failover, deterministic cache statistics, and normalized cache scopes. | Defer code integration; copy the explicit opt-in/fail-closed configuration pattern for a later HF build-cache cohort. |
| [LLVM](https://github.com/llvm/llvm-project) | LLVM exception / Apache-2.0 family; 39k+ stars; active | Stable IR tooling boundaries, modular compiler components, and lower-level artifact analysis. | Continue using LLVM as HF’s lowering target; do not vendor the monorepo. |

### Selected adaptation

The selected adaptation is a tiny, independently implemented **batch work receipt** pattern influenced by Taskflow’s visible task-graph/profiling discipline and by lightweight runtime request accounting. HF already executes bounded parallel ranges, but callers cannot see how many ranges were planned, admitted, cancelled, or completed for a single batch request. Adding that local receipt makes parallel execution observable and testable without importing Taskflow or asserting device speed.

The receipt will remain host-local runtime metadata. It will not claim that Android has used the expected number of cores, that native threads received a particular affinity, or that device throughput improved.

## Quantization and mobile deployment findings

| Project | License / maturity | Relevant pattern | HF decision |
|---|---|---|---|
| [ggml](https://github.com/ggml-org/ggml) | MIT; 15k+ stars; current activity | Dependency-light C/C++, quantized tensor formats, backend separation, and zero-runtime-allocation discipline. | Treat zero-allocation and explicit backend planning as future HF design goals; do not vendor the tensor library. |
| [ONNX Runtime Mobile](https://onnxruntime.ai/docs/tutorials/mobile/) | MIT project; broadly deployed | Model/operator-driven custom mobile builds, CPU-first validation, and measured size/latency/power requirements before accelerator selection. | Borrow its evidence sequence: baseline CPU → package size/latency measurement → hardware-specific provider only with device proof. |
| [gemmlowp](https://github.com/google/gemmlowp) | Apache-2.0; mature but legacy-adjacent | Low-precision GEMM portability, architecture-specialized paths, and per-target build/benchmark validation. | Do not import; HF’s INT4 NibbleFlow path has a different format. Retain its strict “compile flags plus device benchmark” discipline. |

## Candidate ranking

| Rank | Candidate | Fit | License | Evidence cost | Outcome |
|---:|---|---|---|---|---|
| 1 | Batch work receipt inspired by Taskflow observability | Directly fits HF’s new bounded parallel batch path. | Independently implemented; Taskflow source is MIT. | Host-native tests and sanitizer. | **Implement** |
| 2 | CMake compiler-cache launcher inspired by sccache | Useful build-time improvement, but optional tooling and no runtime impact. | Apache-2.0 reference. | Host/CI configuration tests. | Defer |
| 3 | Operator-selected custom runtime manifest inspired by ONNX Runtime Mobile | Strong mobile packaging direction, but needs model/operator inventory first. | MIT reference. | Android package plus device evidence. | Defer |
| 4 | Zero-allocation graph workspace inspired by ggml | High impact but architectural; too broad for a 20-minute loop. | MIT reference. | Extensive numerical and memory tests. | Defer |
| 5 | Work-stealing queue replacement from Taskflow | Potentially beneficial but riskier than the existing priority/thermal scheduler. | MIT reference. | Fairness, deadline, cancellation, and device tests. | Defer |

## References

[1]: https://github.com/ggml-org/llama.cpp "llama.cpp repository"
[2]: https://github.com/google/XNNPACK "XNNPACK repository"
[3]: https://docs.pytorch.org/executorch/stable/index.html "ExecuTorch documentation"
[4]: https://taskflow.github.io/ "Taskflow documentation"
[5]: https://github.com/mozilla/sccache "sccache repository"
[6]: https://github.com/llvm/llvm-project "LLVM project repository"
[7]: https://github.com/ggml-org/ggml "ggml repository"
[8]: https://onnxruntime.ai/docs/tutorials/mobile/ "ONNX Runtime Mobile documentation"
[9]: https://github.com/google/gemmlowp "gemmlowp repository"

## Adaptation result

HF now exposes `hf_runtime_get_batch_receipt` for a live request. The independently written receipt records ABI version, batch row count, planned ranges, admitted ranges, completed ranges, cancellation, deadline misses, failures, and scheduler rejections. It reuses HF’s request mutex and does not alter the public `hf_runtime_wait` result, scheduler selection, model ABI, or NibbleFlow kernel calculation.

Focused native checks covered a parallel multi-range batch, a one-row serial fallback, invalid receipt arguments, 100 consecutive host runs, address/undefined-behavior sanitizers, and adjacent runtime/scheduler regression binaries. The receipt reports only local scheduler lifecycle state. It is **not** evidence of Android core utilization, affinity success, JNI lifecycle correctness, NEON throughput, power consumption, thermal behavior, or physical-device performance.

### Attribution

The visibility pattern was independently implemented after reviewing Taskflow’s public documentation and project framing around task graphs, work stealing, and profiling. No Taskflow source code, headers, or runtime dependency were copied into HF. Taskflow is available at <https://github.com/taskflow/taskflow>; credit to its maintainers and contributors.
