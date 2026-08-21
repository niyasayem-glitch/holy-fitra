# Holy Fitra Multi-Round Optimization — Round 12 Candidates

## Selection context

Round 11 added inactivity demotion. Round 12 targets promotion precision: large batched queries make float16 conversion overhead more expensive, while tiny queries benefit from remaining compact. The selected policy adds a configurable large-batch threshold and promotion bonus to the existing EWMA/hysteresis decision.

| Rank | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|
| 1 | Batch-size-aware adaptive promotion bonus for large queries | Earlier hot promotion where f32 amortizes better; cold small queries remain compact | Medium policy risk | **Selected** |
| 2 | Promotion threshold from measured batch FLOPs | Better cost model | Medium | Defer |
| 3 | Batch-size EWMA instead of current instantaneous factor | More stable behavior | Low/medium | Defer |
| 4 | Per-layer batch-size thresholds | Better multi-layer control | Medium | Defer |
| 5 | Promotion bonus based on matrix output width | Better cost sensitivity | Medium | Defer |
| 6 | Demotion threshold scaled by recent batch size | Better memory control | Medium | Defer |
| 7 | Promotion cooldown after demotion | Prevent thrashing | Medium | Defer |
| 8 | Policy snapshot and restore API | Reproducibility | Low | Defer |
| 9 | Access-pattern telemetry counters in TUI | Observability | Low | Defer |
| 10 | Lock-free counters for concurrent callers | Lower overhead | High | Defer |
| 11 | Native batch-size hint ABI | Android value | High | Defer |
| 12 | Calibration-derived promotion error budget | Quality | Medium/high | Defer |
| 13 | Cache policy manifests in HyperPackage | Deployment value | Medium | Defer |
| 14 | Compiler lowering for cache hints | Language integration | High | Defer |
| 15 | Device thermal-aware batch policy | Android value | High without hardware | Defer |

## Retention rule

Retain only if large-batch workloads promote no later than the baseline, small one-shot/spaced workloads do not promote prematurely, quality and memory gates remain enforced, and all complete regression/native/sanitizer/Termux gates pass. No Android-device claim may be inferred.

## Round 12 result

Adaptive promotion now accepts `adaptive_large_batch_rows` and `adaptive_large_batch_bonus`. When the recent access EWMA is active and the query batch reaches the configured size, the bonus lowers the effective promotion threshold. Small bursts retain the normal threshold and remain compact; large bursts promote earlier so float32 conversion cost can be amortized.

The complete applicable suite passes **106 tests with 0 failures**. Termux-compatible host validation passes, including AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox with `promote_after=4`, hysteresis 2, large-batch threshold 512 rows, and bonus 3:

| Access pattern | Result after three 1 ms accesses | Resident cache |
|---|---|---:|
| Small 24-row burst | Remained `adaptive_cold` | 24,576 bytes |
| Large 512-row burst | Promoted to `f32` | 49,152 bytes |

The large-batch policy therefore promotes a high-workload query while avoiding premature promotion for the same-frequency small workload. These are sandbox measurements only.

## Round 12 retention decision

Retain the batch-size-aware promotion bonus. It is configurable, preserves the existing EWMA/hysteresis and quality gates, differentiates workload cost, and passes all regression/native/sanitizer/Termux gates.
