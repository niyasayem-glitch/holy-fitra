# Holy Fitra Autonomous Performance Loop — Iteration 6 Candidates

## Selection context

Iteration 5 hardened persistent LLVM cache publication and is retained at commit `6b25b1e`. The next target should address measured runtime allocation overhead rather than speculative architecture changes.

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Quantization | Compute calibration MSE in-place in the reference buffer to avoid subtraction/square temporaries | Medium repeated calibration speed and memory reduction | Low | **Selected** |
| 2 | Quantization | Reuse calibration float32 normalization buffers across layers | Medium | Medium | Defer |
| 3 | Quantization | Cache calibration reference matmul by weight/calibration digest | Medium/high | Medium/high | Defer |
| 4 | Quantization | Fuse int4 dequantization and batched matmul into one native path | High | High | Defer |
| 5 | Transformer | Preallocate attention score/weight buffers for reference benchmarking | Medium | Medium | Defer |
| 6 | Transformer | Reuse KV-cache arrays across speculative-decoding repetitions | Medium/high | Medium | Defer |
| 7 | Ragged attention | Avoid repeated offsets conversion in work estimation | Low/medium | Low | Defer |
| 8 | Ragged attention | Reuse padded-reference triangular masks | Low/medium | Medium | Defer |
| 9 | Compiler | Avoid repeated JSON serialization on CLI cache hits | Medium | Medium | Defer |
| 10 | Compiler | Add source-read digest reuse under safe inode/mtime validation | Medium | Medium | Defer |
| 11 | Telemetry | Batch JSONL event writes with bounded flush policy | Medium | Medium | Defer due observability durability risk |
| 12 | TUI | Cache workspace source previews by file digest | Low/medium | Low | Defer |
| 13 | Native | Add fused scheduler work-size calculation | Medium Android value | High | Defer |
| 14 | Android | Reuse JNI benchmark buffers across runs | Medium | Medium/high | Defer pending device ABI gates |
| 15 | Self-hosting | Add native compiler profiling hooks in Holy Fitra source | Long-term | High | Roadmap only |

## Retention rule

Retain only if calibration MSE values remain numerically identical within tested floating-point tolerance, quality-gate decisions remain unchanged, the focused and complete tests pass, and measured runtime or allocation behavior improves on the x86-64 sandbox. No Android-device claim may be inferred.

## Iteration 6 result

The in-place calibration-MSE experiment was rejected: values were numerically identical, but median time regressed from 0.0324585 ms to 0.041713 ms at 256×128 and from 0.0870965 ms to 0.091163 ms at 1024×128. The helper was restored.

The retained optimization caches the reconstructed float32 int4 weight inside `QuantizedMatrix` after the first `matmat()` call. A focused test verifies reconstruction occurs once and output remains identical. The complete applicable suite passes **95 tests with 0 failures**. Termux-compatible host validation and ASAN/UBSAN native gates pass, including 2,688-byte AArch64 object emission and ragged scalar/NEON/SVE checks.

On the x86-64 sandbox, repeated int4 batched matmul medians changed as follows:

| Shape | Baseline | Cached reconstruction | Result |
|---|---:|---:|---|
| 32×128×96 | 4.2562195 ms | 0.00668 ms | 637× faster |
| 256×128×96 | 4.318378 ms | 0.0245825 ms | 176× faster |
| 1024×128×96 | 4.315934 ms | 0.0237615 ms | 182× faster |

Maximum absolute output difference was **0.0** in every measured case. These are x86-64 sandbox measurements only; no Android-device performance claim is made.

## Iteration 6 retention decision

Retain only the int4 reconstruction cache. It materially improves repeated batched calibration work, preserves exact tested outputs, and passes all regression, native, sanitizer, and Termux gates.
