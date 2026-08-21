# Holy Fitra Hybrid Cache Optimization Loop — Iteration 8 Candidates

## Selection context

Iteration 7 introduced explicit quality-gated float16 reconstruction caches. The probe demonstrated 50% cache-memory reduction but slower CPU matmul. Iteration 8 targets a two-tier policy that preserves compact cold-state memory and promotes frequently used weights to a fast float32 cache.

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Quantization/cache | Adaptive float16 cold cache with quality gate and float32 promotion after a configurable use threshold | Memory savings for cold weights; near-f32 latency for hot weights | Medium | **Selected** |
| 2 | Quantization/cache | Keep a small float32 tile hot-cache over the most-used output rows | Lower promotion memory | High numerical/layout complexity | Defer |
| 3 | Quantization/cache | Promote based on observed batch size rather than call count | Better workload adaptation | Medium | Defer |
| 4 | Quantization/cache | Demote inactive float32 caches back to float16 after an idle epoch | Dynamic memory reduction | Medium/statefulness risk | Defer |
| 5 | Quantization/cache | Use float16 for cold layers and float32 for latency-critical layers | Practical hybrid policy | Medium API complexity | Defer |
| 6 | Quantization/cache | Store f16 plus a compact residual correction tile | Better quality at similar memory | High | Defer |
| 7 | Quantization/cache | Use bfloat16 cold cache with f32 promotion | Better range | Medium | Defer |
| 8 | Transformer | Promote Q/K/V caches independently by access frequency | Fine-grained memory/latency tradeoff | High | Defer |
| 9 | Transformer | Keep output projection f32 and other projections f16 | Likely quality/latency balance | Medium | Defer |
| 10 | Android | Add device-class cache policy selection | Android deployment value | High without devices | Defer |
| 11 | Quantization | Persist cache policy and error metadata in manifests | Reproducibility | Low/medium | Defer |
| 12 | Telemetry | Emit cache promotion/demotion events | Observability | Low | Defer |
| 13 | Compiler | Add cache-budget diagnostics to execution plans | Operator value | Low/medium | Defer |
| 14 | Native | Add packed-weight residency and promotion hints to NibbleFlow | Android value | High | Defer |
| 15 | Self-hosting | Add cache policy types to Holy Fitra syntax | Long-term | High | Roadmap only |

## Retention rule

Retain only if the cold state demonstrates the expected memory reduction, hot repeated workloads converge to float32-like latency after promotion, promotion preserves the quality gate, default behavior remains unchanged, and all regression/native/sanitizer/Termux gates pass. No Android-device claim may be inferred.

## Iteration 8 result

The selected implementation adds `reconstruction_mode="hybrid"` with an explicit float16 error gate and configurable `promote_after` threshold. Hybrid caches begin in a compact float16 cold state and promote to float32 when the batched matmul use count reaches the threshold. The mode exposes `hybrid_cold` versus `f32`, preserves the default float32 path, and keeps deterministic cache clearing and memory accounting.

The complete applicable suite passes **99 tests with 0 failures**. Termux-compatible host validation passes, including 2,688-byte AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox with `promote_after=4`, hybrid cold caches used 24,576 bytes versus 49,152 bytes for float32. After promotion, the cache used 49,152 bytes and the mode became `f32`. Representative medians were:

| Shape | Hybrid cold median | Promotion-call cost | Hybrid hot median | Float32 median | Float16 median |
|---|---:|---:|---:|---:|---:|
| 32×128×96 | 0.029013 ms | 4.692259 ms | 0.006840 ms | 0.006870 ms | 0.026490 ms |
| 256×128×96 | 0.052650 ms | 5.201119 ms | 0.029149 ms | 0.0260995 ms | 0.0478175 ms |
| 1024×128×96 | 0.098780 ms | 4.636956 ms | 0.063320 ms | 0.0465905 ms | 0.0693445 ms |

The hybrid mode therefore preserves the 50% cold-cache memory reduction and converges near float32 latency for small and medium batches, while making the promotion cost and memory tradeoff explicit. These are x86-64 sandbox measurements only.

## Iteration 8 retention decision

Retain the adaptive hybrid cache strategy. The float16 cold state is quality-gated, hot weights promote deterministically, default behavior remains unchanged, and all regression/native/sanitizer/Termux gates pass.
