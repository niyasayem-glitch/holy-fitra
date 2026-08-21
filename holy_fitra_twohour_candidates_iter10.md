# Holy Fitra Multi-Round Optimization — Round 10 Candidates

## Selection context

Iteration 9 dynamically promotes caches using access intervals, EWMA frequency, hot streak, batch size, and hysteresis. The adaptive path currently reads a monotonic clock inside every matmul call. Android and native runtimes often already possess a scheduling timestamp, so round 10 targets a zero-duplicate-clock fast path.

| Rank | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|
| 1 | Accept caller-supplied access timestamps in adaptive `matmat()` | Removes duplicate clock read and improves deterministic testing/integration | Low | **Selected** |
| 2 | Add a no-telemetry adaptive matmul fast path after promotion | Lower hot-path branching | Low/medium | Defer |
| 3 | Cache batch-size load factors by row count | Small Python overhead reduction | Low | Defer |
| 4 | Quantize EWMA state to fixed-point integers | Lower state footprint | Medium numerical-policy risk | Defer |
| 5 | Use a lock-free native access counter | Lower concurrent overhead | High | Defer |
| 6 | Batch access observations per micro-batch | Lower timing overhead | Medium | Defer |
| 7 | Add per-layer policy snapshots | Better multi-layer control | Medium | Defer |
| 8 | Add adaptive policy serialization | Reproducibility | Low/medium | Defer |
| 9 | Emit promotion telemetry asynchronously | Better observability | Medium | Defer |
| 10 | Add adaptive policy validation diagnostics | Reliability | Low | Defer |
| 11 | Reuse matrix contiguity checks after first call | Lower validation overhead | Medium mutability risk | Defer |
| 12 | Add packed-weight residency metadata | Native integration | Medium | Defer |
| 13 | Add memory budget warnings | Operator value | Low | Defer |
| 14 | Add cache-policy type annotations to manifests | Tooling | Low | Defer |
| 15 | Add language-level adaptive-cache syntax | Long-term | High | Roadmap only |

## Retention rule

Retain only if explicit timestamps preserve promotion decisions exactly, reduce or avoid clock overhead in measured adaptive calls, keep default behavior unchanged, and pass all full validation gates.

## Round 10 result

Adaptive `QuantizedMatrix.matmat()` now accepts an optional `access_timestamp_ns`. When supplied by a runtime or scheduler, the adaptive policy reuses that timestamp and avoids an internal monotonic-clock read. Existing callers retain the original behavior.

The complete applicable suite passes **103 tests with 0 failures**. Termux-compatible host validation passes, including compiler/runtime/dashboard tests, NibbleFlow numerical validation, 2,688-byte AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox under a 24-call hot adaptive workload, median matmul time changed from **0.0277815 ms** with an internal clock read to **0.0212665 ms** with caller-supplied timestamps, a measured reduction of approximately **23.4%**. Promotion decisions and final adaptive statistics were identical: promotion occurred on the third access under the same burst pattern. These are sandbox measurements only.

## Round 10 retention decision

Retain the explicit timestamp fast path. It reduces duplicate timing work, preserves the default API behavior and promotion semantics, and passes all regression, native, sanitizer, and Termux gates.
