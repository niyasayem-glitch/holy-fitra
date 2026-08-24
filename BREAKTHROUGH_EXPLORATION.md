# Holy Fitra Breakthrough Exploration

## Research signal, not Holy Fitra performance evidence

Recent work identifies long-context key-value (KV) state as a primary mobile inference pressure point. The adaptive KV-cache paper proposes token-level precision selection across 2-bit, 4-bit, 8-bit, and FP16 using bounded controller inputs; its reported accuracy and latency results are for its own models and evaluation setup, not for Holy Fitra.[1] A 2026 on-device LLM review likewise frames memory traffic, KV-cache management, quantization, and short burst-style execution as central system constraints; it explicitly recommends profiling real hardware rather than trusting emulators.[2]

EdgeLLM shows that speculative decoding can pair a memory-resident draft model with a larger target model and uses adaptive fallback and overlapping compute/I/O. Its reported speedup applies to its own system, so it is a design input rather than a Holy Fitra claim.[3]

## Candidate directions

| Candidate | Existing Holy Fitra leverage | Why it is high-value | Evidence needed before a performance claim |
|---|---|---|---|
| **Typed KV residency ledger** | Streamed capsules, deterministic receipts, static calibration plan | Gives every attention-cache allocation a fixed budget, format, expiry, source hash, and eviction reason. It is foundational for long-context mobile execution. | Reference parity, bounds/fuzz checks, AArch64 build, then physical-device memory and quality receipts. |
| **Deterministic precision governor** | Static INT8 calibration gates and benchmark receipts | Makes precision choices auditable and fail-closed instead of adaptive black-box behavior. It can begin as a static policy table, not a learned on-device controller. | Golden policy cases, numerical equivalence, calibration acceptance checks, device quality study. |
| **Adapter capsule residency** | Bounded low-rank adapter overlay and streamed block model path | Lets the runtime swap small validated adapters independently of immutable base-weight chunks, with explicit rollback and fingerprints. | Layout validation, streamed reference tests, JNI/package validation, device lifecycle evidence. |
| **Draft/verify contract** | Scheduler deadlines, cancellation, streamed execution | Establishes a typed speculative-decoding transaction boundary before claiming an actual accelerator. It can track acceptance, reject reason, and resource budgets deterministically. | Contract tests first; model-backed quality and speed only after device testing. |
| **Evidence-first tuning lab** | Studio Evidence Ledger and versioned benchmark receipts | Turns experiments into reproducible comparison cards rather than one-off claims; joins project, model capsule, policy, benchmark fixture, and raw receipt hashes. | Schema/import tests, host receipts; physical campaign for mobile measurements. |

## Initial priority

The most coherent next implementation is a **Typed KV Residency Ledger and deterministic precision governor**. It creates the memory-management and evidence contracts needed by later streamed adapters and speculative decoding, adds direct value even without a live model, and can be exercised with host/native safety tests while preserving the device-evidence boundary.

## Wave 1 design

The implementation will introduce a pure-Python `holyfitra_kv_residency` contract layer rather than pretend that the present MLP capsule already performs transformer attention. A `KVResidencyPolicy` declares immutable byte, entry, age, and permitted-precision ceilings. A `KVResidencyLedger` admits or rejects typed cache blocks, deterministically evicts only evictable least-recent entries, prevents an admission from exceeding the configured budget, and creates canonical receipts containing policy identity, requested bytes, evictions, and the final residency state.

`KVPrecisionGovernor` will be a static, fail-closed planner. It chooses a requested format only from policy-allowed precision levels using explicit quality and budget signals. Missing quality evidence resolves to the conservative FP16 policy, while threshold failures reject the lower-precision request rather than silently degrading a cache entry. It does not claim to train, learn, quantize tensors, or increase mobile speed.

The capsule layer will optionally store an authenticated `kv_residency_policy.json` payload bound to the existing capsule index. This enables a streamed runtime or future JNI layer to obtain the same policy identity and lets Studio/host receipts correlate the capsule, policy, and cache decisions. Existing capsules and callers remain compatible because the new payload is optional.

| Contract | Fail-closed invariant | First acceptance gate |
|---|---|---|
| KV block | Positive bounded dimensions, approved precision, exact logical byte size, lowercase SHA-256 identity | Unit tests for malformed blocks, overflow, and duplicate identity |
| Policy | Non-empty unique precision ladder, positive bounded budgets, static quality thresholds | Policy validation matrix |
| Ledger | No admission leaves bytes or entry count above budget; protected entries are never evicted | Deterministic eviction and rejection tests |
| Governor | Unknown or failed quality metrics cannot select lower precision | Golden decision cases |
| Capsule binding | Policy payload is indexed and authenticated just like existing chunks | Export/open/tamper compatibility tests |

## References

[1]: [Don't Waste Bits! Adaptive KV-Cache Quantization for Lightweight On-Device LLMs — arXiv](https://arxiv.org/abs/2604.04722)
[2]: [On-Device LLMs: State of the Union, 2026 — Vikas Chandra and Raghuraman Krishnamoorthi](https://v-chandra.github.io/on-device-llms/)
[3]: [EdgeLLM: Fast On-Device LLM Inference With Speculative Decoding — IEEE Transactions on Mobile Computing](https://dl.acm.org/doi/10.1109/TMC.2024.3513457)
