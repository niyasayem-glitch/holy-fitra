# Two-Hour Autonomous Loop — Iteration 1 Candidates

## Baseline evidence

The retained baseline passes 88 Python tests, Termux shell syntax, contract validation, NibbleFlow validation, and ragged-attention validation. The compiler reports approximately 35 ms for a cold native smoke build in the current process, while identical artifact reuse is sub-millisecond. The benchmark dashboard and telemetry are already functional.

## Candidate matrix

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Compiler/cache | Persist parsed native AST metadata beside LLVM cache to avoid reparsing on cache hits | Medium on repeated checks | Medium | Selected for design review |
| 2 | Compiler/cache | Add bounded in-memory LRU for source digest, parsed AST, and LLVM text | High for daemon/TUI/REPL sessions | Low | Selected |
| 3 | Compiler | Batch multi-file project parsing with dependency digest graph | High for large projects | High | Defer |
| 4 | Compiler | Parallel function validation | Medium for large modules | Medium | Defer until profiling |
| 5 | Safety | Cache effect-call-graph closure with immutable program identity | Medium | Low | Selected |
| 6 | Safety | Call-graph cycle diagnostics with explicit recursive effect policy | Medium | Medium | Selected for design |
| 7 | HyperIR | Stable textual HyperIR dump and verifier cache | Medium | Low | Defer |
| 8 | AI/quant | Cache proof-demo calibration artifacts by calibration hash | Medium in repeated dashboard runs | Low | Selected |
| 9 | AI/quant | Reuse dequantized int4 matrix for multiple calibration passes | Medium | Low | Selected |
| 10 | Transformer | Reuse KV-cache buffers between benchmark repetitions | Medium | Medium | Defer |
| 11 | Native | Add compiler artifact cache statistics to telemetry | Medium observability | Low | Already partially present; extend |
| 12 | Scheduler | Recycle task metadata in persistent ragged execution context | High on Android workloads | High | Defer pending native ABI review |
| 13 | TUI | Incremental telemetry tail reading instead of rereading 500 lines | Low/medium | Low | Selected |
| 14 | Termux | Avoid unavailable optional CMake assumptions in host validation | Low compatibility risk | Low | Selected |
| 15 | Self-hosting | Bootstrap lexer/parser in Holy Fitra source | Very high long-term | Very high | Roadmap only |

## Iteration 1 selection

Implement a bounded in-memory compiler cache, immutable effect-graph memoization, proof calibration memoization, and incremental TUI telemetry tailing. These are low-risk changes that target repeated compiler/TUI/benchmark work without weakening safety or quantization proof gates.

## Retention rule

Keep the implementation only if the complete applicable regression suite passes, sanitizer/native checks remain green, telemetry remains deterministic, proof verification remains true, and repeated benchmark work improves or does not regress beyond measurement noise.

## Iteration 1 validation result

The incremental cursor fix changed the cursor invariant to byte offsets that always advance to the end of bytes read, while retaining an unconsumed partial line separately. This prevents the same partial bytes from being concatenated twice when the terminating newline arrives. A regression test now covers complete append, partial append, newline completion, and file truncation.

The full applicable Python suite passes: **89 tests, 0 failures**. The Termux-compatible validation with host tests passes, including compiler/runtime/dashboard tests, NibbleFlow numerical validation, AArch64 object emission, ragged attention scalar/NEON/SVE object checks, scheduler execution, CLI smoke tests, project initialization, and benchmark invocation. The sanitizer gate also passes for the ragged kernel/scheduler executable and a sanitized NibbleFlow shared library build using ASAN and UBSAN. No physical Android execution was performed; AArch64 results are cross-compilation/object-validation evidence only.

Observed host measurements from this iteration remain evidence for the x86-64 sandbox only: the compiler smoke test emitted a native artifact in approximately 34–36 ms in the current process, while warm cache results are sub-millisecond in the existing benchmark notes. Quantization benchmark improvements remain retained only because the existing proof and regression gates pass; no Android latency claim is made.
