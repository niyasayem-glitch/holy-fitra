# Holy Fitra Language and Compiler Breakthrough Brief — 2026-08-26

## Decision frame

Holy Fitra has a working native scalar LLVM path, persistent artifact cache, dynamic `i32`/`i64` inputs, typed hybrid metadata, and a separately validated Android-native runtime surface. Recent work closed three language-correctness gaps: signed constant division, contextual `i64` literals, and operator precedence. The evidence does **not** support a claim that a global `-O3` switch, unmeasured ARM64 specialization, or a broad rewrite will automatically improve real workloads.

The next wave should prioritize changes that either increase source-language usefulness with small semantic blast radius or produce measurements that make a larger optimization decision defensible.

## Ranked candidates

| Rank | Candidate | Why it matters now | Risk | Required retain gate |
|---:|---|---|---|---|
| 1 | **Interleaved backend experiment harness** | The rejected O3 run had only separate-session summaries. Raw alternating O2/O3 pairs would turn compiler tuning from guesswork into evidence. | Low | Fixed LLVM input, alternating prebuilt binaries, raw samples, paired statistics, startup-versus-loop split, exact outputs. |
| 2 | **Large-fixture per-stage compiler receipt** | The current cache profile attributes cold latency primarily to external Clang; the maintained fixture is too small to choose a cache redesign. | Low | Parser-valid large source, parse/validate/emit/Clang/cache timing fields, reproducible samples, no cache semantic change. |
| 3 | **`break` and `continue`** | The native statement grammar supports `while`, `if`, binding, assignment, and return, but lacks bounded loop exits. This is a high-value ergonomic control-flow gap with a contained LLVM lowering. | Medium | Nested-loop target tests, unreachable-path validation, loop-label correctness, host execution, AArch64 object generation. |
| 4 | **Deterministic native module imports** | The bootstrap work has module concepts, but the active scalar native frontend is still effectively single-source. Imports unlock real project decomposition. | High | Canonical path policy, duplicate/cycle diagnostics, deterministic dependency order, content-addressed cache identity, source-span preservation. |
| 5 | **Explicit integer conversions and unsigned widths** | `i32`/`i64` exist, but there are no signed/unsigned conversion semantics. This blocks safe bit-level, model-shape, and ABI code. | High | Defined overflow policy, `i32`/`i64` boundary matrix, LLVM emission checks, no implicit variable widening, cross-target objects. |
| 6 | **Source spans and diagnostic notes** | Parser tokens already track line and column, while many diagnostics are message-only. Better errors improve every later language feature and Studio handoff. | Medium | Stable golden diagnostics, nested-call context, deterministic ordering, no source-text leakage in packages. |
| 7 | **Arrays and fixed-layout records** | Structured values are the largest language capability gap between scalar functions and useful compiler/runtime programs. | Very high | Explicit layout/ownership design, bounds behavior, initialization rules, ABI tests, sanitizer, target objects; prototype only after an RFC. |
| 8 | **Defined checked-arithmetic mode** | Native arithmetic currently maps to LLVM scalar operations. An explicit checked mode would make safety-sensitive code auditable without changing existing wrap-oriented semantics silently. | Medium | Overflow/zero-divisor matrix, legacy behavior compatibility, ABI stability, performance receipt. |
| 9 | **Effect-aware call diagnostics** | Effect closure is already validated. Attaching the transitive call path to a missing-effect error would make contracts practical at scale. | Low | Golden diagnostic tests for direct, nested, hybrid, and recursive-cycle cases. |
| 10 | **Tail-call/recursion design RFC** | Current effect analysis rejects recursive cycles. Recursion could improve expressiveness, but requires stack/resource semantics before any lowering change. | Very high | Design-only first: termination/budget contract, cycle classes, stack receipt, differential tests. |
| 11 | **Per-function incremental compilation** | It could reduce edit-build latency, but the current evidence only proves Clang dominates a tiny whole-program cold build. | High | Larger-fixture profile must first prove an emission/link subdivision benefit and preserve cross-function ABI/cache integrity. |
| 12 | **Runtime-specialized ARM64 kernel paths** | Useful only when supported by Bionic/device receipts; host results cannot select NEON/I8MM behavior for phones. | High | Android NDK build, numerical equivalence, device correctness, thermal-aware repeated measurements. |

## Recommended order

The strongest next implementation is **not** a speculative optimizer. It is the paired backend measurement harness, immediately followed by a larger stage-resolved compiler profile. Those two items establish whether the next high-value engineering target is native compiler process cost, cache design, or emitted code quality.

For source-language capability, `break` and `continue` are the best bounded next feature. They add practical expressiveness while avoiding the memory-layout, ownership, ABI, and runtime complexity of arrays and records. Native module imports should follow only with an explicit path, cache, and diagnostic contract.

## Rejected shortcuts

| Shortcut | Why it is not a justified next step |
|---|---|
| Default every build to `-O3` | The existing LCG candidate did not improve; its hot loop was already identical at O2 and O3. |
| Claim universal language-benchmark leadership | Current evidence is one host microbenchmark plus limited comparative fixtures, not a broad application suite. |
| Add NEON/I8MM based on host intuition | ARM64 Android behavior requires an NDK build and physical-device receipts. |
| Make the Python compiler “fully self-hosted” by declaration | Bootstrap states and the active native Python frontend are distinct paths; self-hosting requires a verified end-to-end replacement. |
| Semantic cache-key rewrite now | Current profile lacks the larger-fixture evidence required to prove a benefit without risking diagnostic/cache correctness. |

## Concrete next gate

Implement an `--compare-opt-levels` benchmark tool that accepts one fixed `.hf` fixture, emits LLVM once, compiles O2 and O3 once, alternates the two binaries in every round, stores each paired raw timing and correctness result, and reports paired median/mean, spread, and startup-separated timing. Retain a compiler-flag change only when that gate shows a reproducible improvement on more than one representative fixture.
