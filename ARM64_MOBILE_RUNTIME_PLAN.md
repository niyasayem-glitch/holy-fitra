# Holy Fitra ARM64 Mobile Runtime: Implementation Wave 1

## Scope

This wave hardens the runtime contract that joins quantized execution, calibration, low-rank adaptation, scheduling, and evidence receipts. It does not claim to convert the host into an Android phone, to validate ART/JNI lifecycle behavior, or to establish device throughput or thermal results.

| Layer | Current verified gap | Wave 1 change | Acceptance proof |
|---|---|---|---|
| Quantized format | The v1 NibbleFlow model only accepts static INT4 weights, per-group float scales, and optional bias. | Add an opt-in v2 execution descriptor for a validated bounded low-rank residual adapter and static activation calibration. Preserve v1 execution unchanged. | Scalar/reference equivalence and malformed-layout tests. |
| Calibration | Scale arrays are structurally checked but have no quality receipt or acceptance policy. | Add a deterministic static calibration summary with finite-range, clipping, and normalized-error limits; fail closed when a supplied calibration receipt is invalid. | Deterministic unit tests for accepted, rejected, and overflow inputs. |
| Execution | The existing matvec accepts only float activations; adaptation cannot be applied within the native call boundary. | Apply an optional bounded low-rank residual after the base INT4 matvec, while honoring a static activation scale/zero point only when explicitly selected. | Matvec parity tests against a direct reference calculation. |
| Scheduling | The scheduler reports aggregate queue activity but does not expose a stateful evidence receipt for every benchmark operation. | Retain its priority/deadline/thermal contract and add receipt fields that identify host versus Android-native process build scope, seed, and deterministic workload configuration. | JSON schema regression tests and host benchmark fixture. |
| Packaging | The Android graph already compiles the core runtime and benchmark library. | Keep the v1 graph intact, include the extended NibbleFlow implementation through existing source ownership, and make cross-target validation verify the new source. | AArch64 object/assembly gate plus Android graph/build checks. |
| Evidence | A benchmark JSON can be created from host or device without declaring the build context. | Version the receipt schemas and label Android-native versus host-native execution context without upgrading either to a device-performance claim. | Snapshot-style JSON assertions. |

## Compatibility and safety rules

The original `hf_nibbleflow_model` ABI remains version 1. A new execution-plan structure is deliberately separate, versioned, optional, and validated before any dereference. It requires exact dimensions, bounded rank, finite coefficients, non-overlapping invariants, and explicit precision mode. Default calls continue through the validated v1 `hf_nibbleflow_matvec` path.

No runtime calibration is learned from user inputs. Calibration parameters are static package metadata supplied by an offline process; the runtime only validates and applies them. This avoids dynamic per-token range inference, preserves deterministic behavior, and supplies a device-friendly static path consistent with the research constraints above.[3] [4]

## Design boundary

> The work is an integration and validation upgrade. It does not prove that INT4/INT8, low-rank adaptation, or the scheduler is faster on a particular ARM64 phone. That requires raw receipts from a repeated physical-device campaign.

## References

[1]: [QLoRA: Efficient Finetuning of Quantized LLMs — arXiv](https://arxiv.org/abs/2305.14314)
[2]: [QA-LoRA: Quantization-Aware Low-Rank Adaptation of Large Language Models — ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/e6c2e85db1f1039177c4495ccd399ac4-Abstract-Conference.html)
[3]: [A practical guide to LLM quantization on Arm Mobile CPUs — Arm](https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/llm-quantization-for-mobile-deployment)
[4]: [MobileQuant: Mobile-friendly Quantization for On-device Language Models — arXiv](https://arxiv.org/html/2408.13933v1)
