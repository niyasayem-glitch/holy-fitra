# Holy Fitra Multi-Round Optimization — Round 11 Candidates

## Selection context

Round 10 removed duplicate clock reads when runtimes provide timestamps. Round 11 targets the opposite lifecycle problem: promoted float32 caches can remain resident after a layer becomes cold. The selected policy adds timestamp-aware inactivity demotion with a hysteresis guard.

| Rank | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|
| 1 | Demote promoted float32 cache to float16 after bounded inactivity | Reclaims 50% reconstruction-cache memory for cold layers | Medium statefulness risk | **Selected** |
| 2 | Add explicit `demote_reconstruction_cache()` API only | Deterministic manual memory release | Low | Included |
| 3 | Demote using EWMA frequency decay | Better workload adaptation | Medium | Defer |
| 4 | Global memory-budgeted demotion queue | Strong footprint control | High concurrency risk | Defer |
| 5 | Per-layer idle epochs | Multi-layer value | Medium | Defer |
| 6 | Demote only after promotion amortization threshold | Avoid repeated reconstruction cost | Medium | Defer |
| 7 | Preserve a tiny float32 checksum/residual during demotion | Faster re-promotion | High memory/quality complexity | Defer |
| 8 | Batch demotions at scheduler safepoints | Lower synchronization overhead | High | Defer |
| 9 | Add thermal-triggered demotion | Android value | High without device data | Defer |
| 10 | Add telemetry for promotion/demotion transitions | Observability | Low | Defer |
| 11 | Persist demotion policy in model manifests | Reproducibility | Medium | Defer |
| 12 | Add cache memory watermark diagnostics | Operator value | Low | Defer |
| 13 | Add native packed-weight demotion hints | Android value | High | Defer |
| 14 | Add demotion-aware quality proof records | Formal integration | Medium/high | Defer |
| 15 | Add adaptive cache lifecycle syntax to Holy Fitra | Long-term | High | Roadmap only |

## Retention rule

Retain only if demotion restores the compact float16 footprint, preserves the reconstruction-error gate, avoids demotion during active bursts, and passes all complete regression/native/sanitizer/Termux gates. No Android-device claim may be inferred.

## Round 11 result

Adaptive caches now accept `adaptive_demote_after_ms`. When a promoted float32 cache receives an access after the bounded inactivity interval, it is converted back to float16 using the same explicit reconstruction-error gate. The lifecycle also exposes `demote_reconstruction_cache()` for deterministic manual release.

The complete applicable suite passes **105 tests with 0 failures**. Termux-compatible host validation passes, including AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox, a 128×96 reconstructed weight used 49,152 bytes after promotion and 24,576 bytes after a 10 ms inactivity demotion, reclaiming **24,576 bytes / 50% of the reconstructed cache**. The cache returned to `adaptive_cold`, and the float16 quality gate remained enforced. These are sandbox measurements only.

## Round 11 retention decision

Retain inactivity demotion and the explicit manual demotion API. The policy restores compact cold-state memory without demoting active bursts, preserves quality checks, and passes all regression/native/sanitizer/Termux gates.
