# Two-Hour Autonomous Loop — Iteration 2 Candidates

## Selection context

Iteration 1 is retained at commit `8f3ecc0`: 89 Python tests pass, the Termux-compatible host gate passes, the native sanitizer gate passes, and the repository is published privately. The next improvement must preserve the existing safety/evidence verifier and quantization proof gates.

## Candidate matrix

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | HyperIR | Add a versioned canonical textual dump, parser, round-trip digest check, and verifier-result cache | Medium/high for reproducibility, CI, daemon reuse, and debugging | Low/medium | **Selected** |
| 2 | Compiler | Add parallel per-function validation with deterministic diagnostic ordering | Medium on large modules | Medium | Defer until profiling confirms function validation dominates |
| 3 | Language | Add user-defined enum declarations with duplicate/unknown variant diagnostics | Medium language expressiveness | Medium | Defer to iteration 3 |
| 4 | Language | Add algebraic data type constructors and pattern matching | High expressiveness | High | Defer |
| 5 | Compiler | Add incremental dependency digest graph across source files | High on 50,000-line projects | High | Defer pending project-model review |
| 6 | Compiler | Cache parsed AST metadata on disk beside native artifacts | Medium repeated-process speedup | Medium | Defer until cache schema/version policy is defined |
| 7 | Safety | Add explicit recursive effect policy diagnostics for call-graph cycles | Medium safety clarity | Medium | Defer |
| 8 | Safety | Add capability-policy import/export with schema validation | Medium deployment portability | Medium | Defer |
| 9 | Runtime | Add task-scope cancellation tokens to the Python execution bridge | Medium reliability | Medium | Defer pending native ABI review |
| 10 | Transformer | Reuse KV buffers across benchmark repetitions with ownership checks | Medium benchmark latency/memory | Medium | Defer |
| 11 | Quantization | Add calibration artifact manifest checksums and invalidation telemetry | Medium reproducibility | Low/medium | Defer |
| 12 | Native | Add scheduler queue-depth telemetry with bounded sampling | Medium observability | Medium | Defer |
| 13 | Android | Add NEON feature detection and scalar fallback contract tests | Medium deployment reliability | Medium | Defer |
| 14 | Tooling | Add machine-readable HyperIR diagnostics with source spans | Medium editor integration | Medium | Defer |
| 15 | Self-hosting | Start a Holy Fitra lexer bootstrap module | Very high long-term | Very high | Roadmap only |

## Retention rule

Keep iteration 2 only if canonical text round-trips without digest drift, malformed input is rejected deterministically, verifier caching cannot bypass a changed graph, the complete regression suite remains green, and native/Termux gates remain green. Do not claim Android execution from cross-compilation evidence.

## Iteration 2 implementation and validation

The selected candidate is implemented in `hyperc_hyperir.py`. HyperIR now has a versioned canonical JSON-text envelope (`holyfitra.hyperir`, version 1), deterministic `to_text()`/`from_text()` and file helpers, explicit serialization for evidence, capability policies, and quantization proofs, and a bounded 64-entry verifier cache keyed by the full canonical graph digest. Derived `QuantizationProof.verified` state is excluded from identity, so verification can safely restore it on cache hits. Policy contents are included in the digest, preventing authorization changes from reusing stale verification results.

The focused HyperIR suite passes **16 tests**, and the complete applicable suite passes **92 tests with 0 failures**. The Termux-compatible host validation passes, including NibbleFlow numerical checks, 2,688-byte AArch64 object emission, ragged scalar/NEON/SVE object checks, scheduler execution, CLI smoke tests, project initialization, and benchmark invocation. The ASAN/UBSAN native gate passes for the ragged scheduler executable and sanitized NibbleFlow shared-library build.

Measured on the x86-64 sandbox, a 25-sample cold verifier median was **0.023997 ms**, while 100 repeated warm calls had a **0.018248 ms median** and **0.028944 ms p95**. The warm run recorded 100 cache hits and 1 miss. These measurements describe the sandbox host only and are not Android-device benchmarks.

## Iteration 2 retention decision

Retain the implementation: canonical text round-tripping preserves the digest, malformed format/JSON is rejected deterministically, graph mutation causes a verifier-cache miss, all Python/native/Termux/sanitizer gates remain green, and no safety or quantization proof gate was weakened.
