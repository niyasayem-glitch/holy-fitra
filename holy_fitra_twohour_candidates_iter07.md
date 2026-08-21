# Holy Fitra Memory and Cache Optimization Loop — Iteration 7 Candidates

## Baseline probe

Iteration 6 caches reconstructed int4 weights as float32 for repeated batched matmul. For a 128×96 reconstructed weight, the cache consumes 49,152 bytes. A temporary float16 cache probe reduced this to 24,576 bytes, but introduced a measured maximum output difference of approximately 0.00178–0.00249 and was slower for small/medium batches. Therefore, any float16 mode must be explicit and quality-gated; it must not silently replace the default float32 path.

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Quantization/memory | Add explicit float16 reconstruction-cache mode with a caller-supplied maximum cache error gate and memory accounting | 50% cache-memory reduction when accepted | Medium | **Selected** |
| 2 | Quantization/cache | Add `clear_reconstruction_cache()` and cached-byte reporting for deterministic memory release | Medium memory control | Low | Included with selected mode |
| 3 | Quantization | Store packed weights only and reconstruct per call | Maximum memory reduction | High latency | Reject; defeats iteration 6 gain |
| 4 | Quantization | Store blockwise dequantized tiles instead of full reconstruction | Medium/high | High implementation risk | Defer |
| 5 | Quantization | Use bfloat16 reconstruction cache | 50% memory reduction | Medium numerical risk | Defer |
| 6 | Android | Allocate KV buffers in float16 with explicit output promotion | High memory reduction | High numerical/ABI risk | Defer |
| 7 | Android | Add bounded KV-cache capacity watermark telemetry | Medium observability | Low | Defer |
| 8 | Transformer | Reuse attention score/probability workspaces | Medium allocation reduction | Medium | Defer |
| 9 | Transformer | Add memory-budgeted speculative KV-cache eviction | High | High correctness risk | Defer |
| 10 | Ragged attention | Reuse offsets and length work arrays | Low/medium | Low | Defer |
| 11 | Compiler | Add bounded AST cache memory accounting | Medium observability | Low | Defer |
| 12 | Compiler | Add cache entry eviction by estimated LLVM bytes | Medium memory control | Low/medium | Defer |
| 13 | TUI | Display native and reconstruction cache bytes | Medium operator value | Low | Defer |
| 14 | Native | Add packed-weight residency hints to kernel manifests | Medium Android value | Medium | Defer |
| 15 | Self-hosting | Add memory layout annotations to Holy Fitra source | Long-term | High | Roadmap only |

## Retention rule

Retain only if the default float32 path remains numerically and performance compatible, the explicit float16 mode refuses configurations exceeding the declared error gate, cached bytes are observable and reclaimable, focused and complete tests pass, and native/Termux/sanitizer gates remain green. No Android-device claim may be inferred.

## Iteration 7 result

The selected implementation adds an explicit `reconstruction_dtype="f16"` mode to `QuantizedMatrix.quantize()`, requiring a caller-supplied `max_reconstruction_error` gate. It adds `configure_reconstruction_cache()`, `clear_reconstruction_cache()`, `reconstruction_cache_bytes`, `memory_bytes`, cache dtype, and measured reconstruction-error properties. The default remains float32 and keeps iteration 6 behavior unchanged. Transformer memory reporting now includes resident reconstruction-cache bytes.

The complete applicable suite passes **97 tests with 0 failures**. Termux-compatible host validation passes, including NibbleFlow numerical checks, 2,688-byte AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox, the explicit float16 mode reduced reconstruction-cache memory by **50%** in all tested cases, from 49,152 bytes to 24,576 bytes for a 128×96 weight. The measured cache reconstruction error stayed below 0.000244, while maximum output differences versus the default float32 cache ranged from 0.00178 to 0.00249. Float16 matmul was slower in the tested CPU path, so the mode is retained strictly as an explicit memory-saving tradeoff behind a quality gate; it does not silently replace the faster default.

## Iteration 7 retention decision

Retain the explicit memory-aware float16 cache mode and accounting APIs. The default float32 path remains unchanged, float16 requires an error gate, cache memory is observable and reclaimable, exact legacy tests pass, and all native compatibility gates remain green. No Android-device performance claim is made.
