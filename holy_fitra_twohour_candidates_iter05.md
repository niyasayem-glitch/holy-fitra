# Holy Fitra Autonomous Optimization Loop — Iteration 5 Candidates

## Selection context

The retained repository is at `979ce2b`, with the compiler restored after two measured cache/parallel-validation regressions. The next candidate should improve reliability without adding hot-path hashing overhead or weakening safety, evidence, quantization, or native fallback contracts.

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Compiler/cache | Validate persistent LLVM cache digest/schema and write cache entries atomically | High reliability after interruption or corruption | Low | **Selected** |
| 2 | Compiler/cache | Atomically publish native artifacts through temporary files | Medium reliability | Low/medium | Defer |
| 3 | Compiler | Persist JSON AST metadata beside LLVM cache | Medium cross-process speed | Medium/high | Defer |
| 4 | Compiler | Add mtime/size fast path with content verification fallback | Medium speed | Medium | Defer |
| 5 | Compiler | Add dependency digest graph for multi-file projects | High large-project speed | High | Defer |
| 6 | Safety | Add capability-policy schema version checks | Medium deployment safety | Low/medium | Defer |
| 7 | Safety | Add policy provenance to diagnostics | Medium auditability | Low | Defer |
| 8 | Language | Add enum declarations lowered to checked tags | Medium expressiveness | Medium | Defer |
| 9 | Language | Add exhaustive pattern matching | High expressiveness | High | Defer |
| 10 | HyperIR | Add text-file integrity digest in the canonical envelope | Medium corruption detection | Low/medium | Defer |
| 11 | Quantization | Add calibration artifact checksum validation | Medium reproducibility | Low/medium | Defer |
| 12 | Transformer | Add speculative KV transaction sequence numbers | Medium safety | Medium | Defer |
| 13 | Native | Add scheduler metadata pool leak diagnostics | Medium reliability | Medium | Defer |
| 14 | Android | Add runtime ABI version checks to JNI entry points | Medium deployment safety | Low/medium | Defer |
| 15 | Self-hosting | Bootstrap a parser module in Holy Fitra source | Very high long-term | Very high | Roadmap only |

## Retention rule

Retain only if corrupted or interrupted cache entries are rejected and rebuilt deterministically, valid cache hits remain valid, atomic writes leave no partially published cache file, the complete regression suite remains green, and native/Termux/sanitizer gates remain green.

## Iteration 5 result

The selected improvement is implemented in `holyfitra_compiler.py`. Persistent LLVM cache records now include schema version 1 and the expected content digest. Malformed JSON, stale schema, digest mismatch, or non-string LLVM payloads are invalidated and rebuilt. Rebuilt entries are published through a temporary file with flush, `fsync`, and atomic `os.replace`; temporary files are cleaned up after success or failure.

The complete applicable suite passes **94 tests with 0 failures**. Termux-compatible host validation passes, including compiler/runtime/dashboard tests, NibbleFlow numerical validation, 2,688-byte AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, project initialization, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox, the retained baseline disk-cache-hit median was **0.0753545 ms**, while iteration 5 measured **0.074403 ms** under the same saved benchmark harness. Corruption recovery rebuilt the artifact with a matching digest, non-empty LLVM, schema 1, and no leftover temporary files. These are sandbox measurements only.

## Iteration 5 retention decision

Retain the cache-integrity and atomic-publication change. It provides a small measured cache-hit improvement while adding deterministic recovery from interrupted or corrupt cache writes without changing safety, quantization, or Android fallback contracts.
