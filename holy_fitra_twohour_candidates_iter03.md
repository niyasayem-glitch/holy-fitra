# Two-Hour Autonomous Loop — Iteration 3 Candidates

## Measured rejection from the first experiment

A guarded `ThreadPoolExecutor` validator was tested on the x86-64 sandbox. It was restored rather than retained because the 16-function case increased median validation time from 0.0380325 ms to 1.468202 ms, and the 64-function case increased it from 0.163628 ms to 5.224408 ms. The small three-function case was effectively unchanged at 0.0093900 ms versus 0.009124 ms. The experiment passed semantics tests but failed the optimization retention rule.

## Candidate matrix

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Safety/effects | Emit explicit recursive effect-cycle diagnostics instead of silently truncating cycles | High reliability and policy correctness | Low | **Selected** |
| 2 | Compiler | Rework parallel validation as process-free batched expression checks | Medium on large modules | Medium/high | Defer after thread overhead rejection |
| 3 | Language | Add user-defined enum declarations lowered to checked integer tags | Medium expressiveness | Medium | Defer |
| 4 | Language | Add exhaustive enum matching diagnostics | High safety | High | Defer until enums exist |
| 5 | Compiler | Add numeric literal range/type diagnostics before LLVM emission | Medium correctness | Low | Defer |
| 6 | Compiler | Add constant-propagation cache for repeated expression inference | Medium | Medium | Defer |
| 7 | Compiler | Add source-span diagnostics to every type error | Medium tooling value | Medium | Defer |
| 8 | Safety | Add an explicit `recursive` effect annotation and depth budget | Medium | Medium | Defer |
| 9 | Safety | Add capability-policy provenance to compiler diagnostics | Medium auditability | Low/medium | Defer |
| 10 | Runtime | Add cancellation checks to long-running Python decode loops | Medium reliability | Medium | Defer |
| 11 | Quantization | Add proof-cache invalidation telemetry keyed by calibration hash | Medium observability | Low | Defer |
| 12 | Transformer | Add KV-cache ownership assertions at speculative commit boundaries | Medium safety | Medium | Defer |
| 13 | Native | Add scheduler queue overflow diagnostic counters | Medium observability | Medium | Defer |
| 14 | Android | Add explicit scalar fallback metadata to ARM64 kernel manifests | Medium deployment clarity | Low | Defer |
| 15 | Self-hosting | Bootstrap a typed lexer module in Holy Fitra source | Very high long-term | Very high | Roadmap only |

## Retention rule

Retain the selected safety improvement only if cyclic calls are rejected deterministically with the full cycle path, acyclic effect behavior remains unchanged, the complete regression suite and native/Termux/sanitizer gates remain green, and no valid program is silently weakened.

## Iteration 3 result

The parallel-validation experiment was rejected and removed. On the x86-64 sandbox, median validation timings were 0.0380325 ms sequential versus 1.468202 ms guarded-parallel for 16 functions, and 0.163628 ms sequential versus 5.224408 ms guarded-parallel for 64 functions. The result is treated as a real regression, not hidden behind a positive semantic test.

The accepted safety improvement changes the effect call-graph closure from silent cycle truncation to deterministic rejection with a complete path such as `recursive effect cycle: a -> b -> a`. Callee traversal is sorted for stable diagnostics, while acyclic transitive-effect behavior remains unchanged.

The compiler-focused suite and complete applicable suite pass **93 tests with 0 failures**. Termux-compatible host validation passes, including 2,688-byte AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. The ASAN/UBSAN native gate passes for the ragged scheduler and sanitized NibbleFlow build. No physical Android execution was performed.

## Iteration 3 retention decision

Retain only the recursive effect-cycle diagnostic change. The parallel-validation candidate is explicitly rejected due to measured regression and is not present in the working tree.
