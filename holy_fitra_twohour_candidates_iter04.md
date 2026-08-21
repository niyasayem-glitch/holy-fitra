# Two-Hour Autonomous Loop — Iteration 4 Candidates

## Selection context

The latest retained commit is `81b7b15`, with 93 tests passing and deterministic recursive effect-cycle diagnostics. The previous parallel-validation experiment was rejected on measured regression grounds. This iteration focuses on repeated checks and compiler daemon/TUI workloads where the same immutable parsed `Program` can be validated multiple times.

## Candidate matrix

| Rank | Track | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|---|
| 1 | Compiler/cache | Add a bounded whole-program validation memo keyed by immutable `Program` identity/equality | Medium/high for repeated check/emit/TUI validation | Low | **Selected** |
| 2 | Native/runtime | Lower structured task metadata into scheduler admission records | High Android integration value | High | Defer pending ABI review |
| 3 | Safety | Import capability policies from a versioned manifest into compiler checks | Medium deployment value | Medium | Defer |
| 4 | Language | Add enum declarations and checked constructors | Medium expressiveness | Medium/high | Defer |
| 5 | Language | Add algebraic data types and exhaustive matching | High expressiveness | High | Defer |
| 6 | Compiler | Add stable JSON diagnostic codes and source spans | Medium tooling value | Low/medium | Defer |
| 7 | Compiler | Cache constant-folded expression results by AST digest | Medium | Low/medium | Defer |
| 8 | Compiler | Add dependency-aware multi-file invalidation | High large-project value | High | Defer |
| 9 | Quantization | Add calibration-manifest cache invalidation telemetry | Medium | Low | Defer |
| 10 | Transformer | Add KV-cache buffer ownership assertions around speculative transactions | Medium safety | Medium | Defer |
| 11 | Native | Add thermal-gate transition telemetry with bounded sampling | Medium observability | Medium | Defer |
| 12 | Android | Add explicit runtime feature-probe fallback metadata | Medium portability | Low/medium | Defer |
| 13 | Tooling | Add LSP hover payloads for scalar/evidence types | Medium developer experience | Medium | Defer |
| 14 | Self-hosting | Bootstrap parser combinators in Holy Fitra source | Very high long-term | Very high | Roadmap only |
| 15 | Packaging | Add signed manifest schema version enforcement | Medium deployment integrity | Medium | Defer |

## Retention rule

Retain validation memoization only if repeated valid programs return identical results, mutable/invalid inputs cannot bypass validation, the cache is bounded, the full regression suite remains green, and native/Termux/sanitizer gates remain green. No Android execution claim is permitted from host measurements.

## Iteration 4 result

The validation memo was rejected and removed. On the x86-64 sandbox, repeated equivalent two-function programs measured a 0.006309 ms median without the memo versus 0.007406 ms with it, despite 99 cache hits. On a 64-function program, the median was 0.097688 ms without the memo versus 0.1033265 ms with it, despite 49 cache hits. The digest/hash overhead outweighed the saved validation work in both tested sizes.

The complete applicable suite remains green at **93 tests with 0 failures** after restoring the last retained compiler state. No iteration 4 source change is retained or published; the candidate remains documented as rejected by the measured-improvement rule.
