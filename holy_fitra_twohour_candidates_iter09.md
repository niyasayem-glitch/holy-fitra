# Holy Fitra Runtime Promotion Optimization — Iteration 9 Candidates

## Selection context

Iteration 8 uses a fixed `promote_after` threshold. Iteration 9 targets runtime access patterns so cold weights retain float16 memory savings while repeatedly accessed weights promote earlier, without immediately promoting one-off or bursty accesses.

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Quantization/cache | EWMA query-frequency tracker with warmup, promotion threshold, and hysteresis | Better promotion timing across cold, burst, and hot patterns | Medium | **Selected** |
| 2 | Quantization/cache | Promote based on exponentially weighted batch-size × frequency score | Better workload sensitivity | Medium | Included as score input |
| 3 | Quantization/cache | Demote float32 after inactivity window | Lower long-lived memory | Medium/statefulness risk | Defer |
| 4 | Quantization/cache | Per-layer promotion thresholds from observed latency | Better multi-layer balance | Medium/high | Defer |
| 5 | Quantization/cache | Shared global memory-budgeted promotion queue | Strong footprint control | High concurrency risk | Defer |
| 6 | Quantization/cache | Tiny float32 hot-tile cache for top output blocks | Lower promotion cost | High numerical/layout complexity | Defer |
| 7 | Quantization/cache | Batch-size threshold plus frequency threshold | Simple adaptive policy | Low/medium | Defer in favor of EWMA |
| 8 | Quantization/cache | Promotion cost amortization estimator | Better threshold selection | Medium | Defer |
| 9 | Transformer | Track Q/K/V projection access separately | Fine-grained adaptation | Medium/high | Defer |
| 10 | Transformer | Decode/prefill-specific cache policy | Better phase adaptation | Medium | Defer |
| 11 | Android | Thermal-aware promotion suppression | Device value | High without physical device | Defer |
| 12 | Telemetry | Emit promotion decision and frequency events | Observability | Low | Defer |
| 13 | Compiler | Add cache policy fields to execution-plan manifests | Integration value | Medium | Defer |
| 14 | Native | Use runtime cache hints in NibbleFlow dispatch | Android value | High | Defer |
| 15 | Self-hosting | Add adaptive cache policy types to Holy Fitra syntax | Long-term | High | Roadmap only |

## Retention rule

Retain only if cold/one-shot workloads do not promote, hot workloads promote materially earlier than a fixed conservative threshold, burst workloads avoid premature promotion through hysteresis, quality/memory gates remain enforced, and all complete regression/native/sanitizer/Termux gates pass. No Android-device claim may be inferred.

## Iteration 9 result

The selected implementation adds an `adaptive_hybrid` mode. It tracks access intervals using a bounded EWMA, a hot-access streak, batch-size load factor, and hysteresis. Cold or spaced accesses remain float16; bursty repeated accesses lower the effective promotion threshold by one and promote earlier. The policy is explicitly configured through `adaptive_alpha`, `adaptive_hysteresis`, `adaptive_burst_window_ms`, and `promote_after`. Promotion remains quality-gated and converts to the existing float32 cache path.

The complete applicable suite passes **102 tests with 0 failures**. Termux-compatible host validation passes, including 2,688-byte AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox with `promote_after=4` and a 5 ms burst window:

| Access pattern | Adaptive result | Fixed hybrid result |
|---|---|---|
| One-shot | Stayed `adaptive_cold`, 24,576-byte cache, no promotion | Stayed `hybrid_cold`, 24,576-byte cache |
| Spaced 20 ms accesses | Stayed cold through six accesses, 24,576-byte cache | Promoted by its fixed count threshold |
| 1 ms burst | Promoted on the third access after hysteresis and EWMA detection | Promoted on the fourth access |

The adaptive policy therefore avoids promoting one-shot and spaced workloads while promoting bursty hot access one call earlier than the fixed policy. These are x86-64 sandbox measurements only.

## Iteration 9 retention decision

Retain the adaptive query-frequency and access-pattern promotion policy. It preserves cold memory savings, reacts to observed bursts rather than only raw call count, records access statistics, maintains the existing quality gate, and passes all regression/native/sanitizer/Termux gates.
