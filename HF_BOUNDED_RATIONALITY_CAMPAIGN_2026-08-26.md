# Bounded Rationality Campaign — 2026-08-26

## Scope and decision rule

This campaign examined one reproducible host language microbenchmark, one backend flag candidate, and compiler/native build correctness. A change was retained only when it either corrected observable semantics or passed a focused build/test gate. The work does **not** establish that Holy Fitra leads every benchmark, workload, architecture, or language category.

## Baseline and candidate result

The baseline used the repository's rotated nine-sample dynamic-`argv` LCG32 workload at 10,000,000 iterations. Each fixture received the same iteration count and seed; HF’s result was checked through its documented exit-code-modulo-256 contract.

| Candidate | Result | Decision | Reason |
|---|---:|---|---|
| Existing HF backend (`-O2`) | 1.947 ms mean | Baseline | 1.0839× the 1.796 ms C/Clang mean on this host-only workload |
| Raise backend default to `-O3` | 2.001 ms mean | Rejected | It was 2.00% slower than the `-O2` run and provided no retained gain |
| Constant signed-division correction | Semantics corrected | Retained | `-5 / 2` now folds to `-2`, matching LLVM `sdiv` truncation toward zero rather than Python floor division (`-3`) |
| NibbleFlow AArch64 declaration repair | Cross-object builds | Retained | Restores strict AArch64 object compilation by declaring the established runtime entry before the batch wrapper calls it |

The LCG result is a **single host microbenchmark**, not a universal ranking. It does not measure Android, ARM64 CPU execution, allocations, I/O, concurrency, garbage collection, compiler build throughput, model inference, or application workloads.

## Rejected O3 candidate analysis

The O3 candidate was correctly rejected by the retain rule, but the available data does **not** prove that O3 intrinsically regresses Holy Fitra. The two nine-sample runs were separate sessions and record only summary statistics, not paired raw samples.

| Metric | O2 baseline | O3 candidate | Change |
|---|---:|---:|---:|
| HF mean wall time | 1.946903 ms | 2.000823 ms | +0.053921 ms / +2.70% |
| HF median wall time | 1.916459 ms | 1.931452 ms | +0.70% |
| HF observed range | 0.296438 ms | 0.483784 ms | Wider under O3 |
| C/Clang mean in the same comparison session | 1.796107 ms | 1.829210 ms | +1.80% session-to-session drift |
| HF/C mean ratio | 1.0839× | 1.0938× | No positive O3 evidence |

Fresh code-generation comparison explains why a substantial gain was unlikely. O2 had already reduced the loop to an eight-iteration unrolled scalar recurrence using an integer multiply, add, and decrement/test. O3 emitted the same hot-loop body. Its observable difference was only a small entry/preheader control-flow rearrangement, and the full executable text increased from 1,539 to 1,555 bytes. LLVM loop-vectorization remarks reported the same blockers at both levels: the loop-carried state is used outside the loop and the trip count is dynamic, so it is not recognized as a vectorizable reduction.

The benchmark measures **whole-process wall time**, deliberately including process startup and argument parsing. At approximately two milliseconds per run, OS scheduling, frequency state, loader work, and other environmental effects can be comparable to a two-to-three-percent change. The independent C/Clang drift and the O3 run’s wider observed range reinforce that interpretation. Without raw paired samples, a randomized O2/O3 order, and a variance estimate, attributing the 0.053921 ms mean difference solely to the optimization level would be unjustified.

The retained conclusion is therefore narrower: O3 did not pass the evidence gate because it showed no repeatable improvement on this workload. A stronger follow-up should compile O2 and O3 artifacts once from the identical LLVM file, alternate them within every round, retain raw timings, report dispersion and paired confidence intervals, and separately time in-process loop execution versus process startup.

## Retained fixes

The compiler now centralizes constant signed division in `_signed_truncating_division`. It rejects zero divisors and computes a magnitude quotient before applying the sign, yielding the same truncation direction as generated LLVM signed division. New compiler regressions cover negative dividend, negative divisor, both negative, native executable behavior, and zero-divisor rejection.

The campaign also exposed a pre-definition call in `nibbleflow_kernel.c`: the ARM64 branch of `nibbleflow_int4_f32_batch4` called `nibbleflow_int4_f32` before that function was declared. A prototype now precedes the batch wrapper. This is a build-correctness repair; it does not alter the kernel’s algorithm or establish device performance.

## Cycle two: contextual i64 literals

The native frontend already accepted `i64` values from `arg_i64`, but a bare integer literal inferred as `i32` everywhere. Consequently, ordinary code such as `value + 1`, an `i64` declaration initialized from a literal, an `i64` return literal, or a literal argument to an `i64` parameter could be rejected despite the language advertising native `i64` arithmetic.

The retained change applies a literal’s type from a nearby explicit `i32` or `i64` context only. It covers typed declarations, assignments, returns, function parameters, and the other operand of an arithmetic or comparison expression. It validates the literal’s signed range for that target width. Existing variables retain their exact types: combining an `i64` variable with an `i32` variable still fails rather than silently widening either value.

| Case | Result |
|---|---|
| `arg_i64(0, 40) + 1` stored as `i64` | Accepted and emits `add i64` |
| Literal passed to an `i64` parameter | Accepted and emitted as `i64` |
| `i64` function returning `42` | Accepted and emitted as `ret i64 42` |
| `2147483648` in an `i32` context | Rejected as out of range |
| `9223372036854775808` in an `i64` context | Rejected as out of range |
| `2147483647 + 1` in `i32`, or `9223372036854775807 + 1` in `i64` | Rejected before LLVM emission as out of range |
| Mixed `i64` and `i32` variables | Rejected; no implicit variable widening |

The contextual-i64 program also emitted an AArch64 Android-21 object with the expected `add i64` instruction in its LLVM IR. That is a cross-compilation check only. It does not demonstrate Android Bionic linking, APK integration, or physical ARM64 execution.

## Cycle three: expression precedence

The native parser previously placed arithmetic, comparisons, `&&`, and `||` in incompatible precedence groups. For example, `1 == 1 && 2 == 2` was grouped as a boolean combined with an integer and rejected by type checking. The parser now follows the conventional order: multiplication/division, addition/subtraction, comparisons, logical AND, then logical OR. Parentheses continue to override that order.

The regression compiles and executes a combined arithmetic/comparison/logical expression, and the documented full compiler/core suite passed afterward. This changes source-language interpretation for previously ambiguous unparenthesized expressions, but it moves that interpretation to the documented conventional ordering rather than silently accepting a mixed-type form.

## Cycle four: bounded loop control

The native scalar frontend now supports `break` and `continue` inside `while` bodies. Both statements are rejected outside a loop with a line-specific diagnostic. Nested loops bind each statement to its innermost loop: `continue` branches to that loop’s condition head, while `break` branches to that loop’s exit label. This adds practical source-language control flow without introducing implicit exceptions, runtime allocation, or new ABI behavior.

The retained regression executes nested loops where the inner `continue` skips one value and the inner `break` exits another; the expected result is produced on the host. The focused compiler suite passed 44 tests, the documented compiler/core suite passed 117 tests, and the same fixture emitted an AArch64 Android-21 object. The cross-object receipt does not establish Bionic linking, APK behavior, or physical-device execution.

## Cycle five: deterministic native modules

The native scalar frontend now accepts top-level `import "relative/module.hf";` directives after the optional `module` declaration and before functions. Resolution is deterministic and dependency-first. A project manifest defines the import root when present; otherwise the entry file’s directory is the root. Imports must be relative `.hf` files, must resolve inside that root after canonicalization, and are bounded to a 64-file graph. Escaped paths, missing files, duplicate imports, cycles, duplicate module names, anonymous imported modules, and imported `main` functions fail closed with deterministic diagnostics.

Imported functions join one explicit global native function namespace. This first module wave intentionally does not introduce module-qualified calls, selective imports, implicit visibility, package execution, dynamic loading, or device-runtime claims. The compiler incorporates each module’s canonical root-relative path and exact source into cache identity, so a transitive import change produces a new LLVM and native-artifact cache key. `check` and `inspect` receipts include the resolved dependency order; native package creation includes the resolved source modules.

Validation exercised a transitive three-module call that returned the expected host status, repeated resolution with stable module order/digest/LLVM, imported-source cache invalidation, root-escape rejection, duplicate-import rejection, cycle rejection, imported-main rejection, the `check` receipt, and an AArch64 Android-21 object emission. The cross-object gate establishes neither Android Bionic linking nor physical-device execution.

## Cycle six: explicit integer conversions and unsigned widths

The native scalar frontend now supports `u32` and `u64` in addition to `i32` and `i64`. Conversion is explicit through `to_i32`, `to_u32`, `to_i64`, and `to_u64`; there is no implicit widening or signedness change. Equal-width signedness conversions preserve the fixed-width bit pattern, while widening uses sign extension from signed values and zero extension from unsigned values. Direct literals are checked against the requested target range. Runtime narrowing from 64 to 32 bits is rejected rather than silently truncating, so callers must establish an application-level bound before conversion.

Unsigned arithmetic is fixed-width and follows LLVM’s non-`nuw` wrapping behavior for addition, subtraction, and multiplication. Unsigned division and relational comparisons lower to `udiv` and unsigned `icmp` predicates. Constant unsigned arithmetic follows the same fixed-width wrap behavior; negative unsigned literals remain invalid. This wave deliberately does not add runtime checked casts, bitwise operators, unsigned command-line input, unsigned hybrid reducers, tensor dtypes, Bionic linking, or device execution claims.

Validation covered host execution of signed and unsigned widening, equal-width conversion, unsigned wrap, unsigned comparison, static range rejection, runtime-narrowing rejection, non-integer rejection, intrinsic-name reservation, and no-implicit-mixed-width arithmetic. The full suite then passed and the stored fixture emitted an AArch64 Android-21 object; that is cross-object evidence only.

## Validation record

| Gate | Result | Evidence boundary |
|---|---|---|
| Focused compiler suite | Pass: 41 tests | Includes signed-division execution and zero-divisor rejection |
| Documented compiler/core suite | Pass: 114 tests | Python/compiler/runtime contracts only |
| Native NibbleFlow host tests | Pass | Android wrapper and batch-runtime host fixtures |
| ASan/UBSan NibbleFlow host gate | Pass | Host execution only |
| Strict AArch64 Android-21 object | Pass | Cross-object generation and ELF architecture only; not Bionic linking or device execution |
| Contextual-i64 compiler suite | Pass: 42 tests | Includes literal-width, range, no-widening, and executable checks |
| Documented compiler/core suite after cycle two | Pass: 115 tests | Host compiler/runtime contracts only |
| Contextual-i64 AArch64 Android-21 object | Pass | Emitted object only; a target-triple override warning was emitted by Clang |
| Precedence-focused compiler suite | Pass: 43 tests | Covers an unparenthesized arithmetic, comparison, AND, and OR expression |
| Documented compiler/core suite after cycle three | Pass: 116 tests | Host compiler/runtime contracts only |
| Loop-control focused compiler suite | Pass: 44 tests | Nested host execution plus outside-loop diagnostics |
| Documented compiler/core suite after cycle four | Pass: 117 tests | Host compiler/runtime contracts only |
| Loop-control AArch64 Android-21 object | Pass | Cross-object only; no Bionic, APK, or device-execution claim |
| Native module focused compiler suite | Pass: 45 tests | Transitive calls, deterministic order, import-aware cache identity, and graph diagnostics |
| Documented compiler/core suite after cycle five | Pass: 118 tests | Host compiler/runtime contracts only |
| Imported-module AArch64 Android-21 object | Pass | Cross-object only; no Bionic, APK, or device-execution claim |
| AI plan-review focused suite | Pass: 22 tests | Deterministic review receipt, zero-mutation rejection, provider normalization, and campaign contracts |
| Full Holy Fitra regression suite after AI review gate | Pass: 286 tests | Host-only unit and integration contracts; no external model, Android, or device execution implied |
| Unsigned-conversion focused compiler suite | Pass: 46 tests | Host execution, LLVM `sext`/`zext`/`udiv`/unsigned-comparison checks, and diagnostics |
| Full Holy Fitra regression suite after cycle six | Pass: 287 tests | Host-only unit and integration contracts; no Android or device execution implied |
| Unsigned-conversion AArch64 Android-21 object | Pass | Cross-object only; no Bionic, APK, or device-execution claim |
| Local causal baseline focused suite | Pass: 5 tests | Tokenization, deterministic training/generation, checkpoint integrity, bounds, and primary CLI dispatch |
| Full Holy Fitra regression suite after local baseline | Pass: 292 tests | Host-only unit and integration contracts; no Qwen comparison, external provider, Android, or device execution implied |
| Local documentation-corpus receipt | Pass | 28,646 in-corpus transitions and NLL 2.624217972399485; sanity receipt only, not held-out quality or model-capability benchmark |
| Sparse n-gram focused suite | Pass: 6 tests | Matched-NLL behavior, interpolation fallback, checkpoint round-trip, context bound, and CLI order selection |
| Sparse n-gram matched retention gate | Retained | Current identical documentation corpus: order-1 NLL 2.6247765502432703; order-2 NLL 1.6327421523496604; 37.79500383% relative in-corpus reduction only |
| Full aggregate Termux runner | Initially exposed declaration error | Its Python phase completed 280 tests; its stale AArch64 object gate failed before the repair and was replaced by the focused post-repair cross-object gate above |

## Next bounded opportunities

The next justified work is to profile compiler cold-build stages on a larger, real source fixture; remove only measured frontend or process-launch overhead; and add a separate Android NDK/Bionic build receipt. Any architecture-specific kernel work should remain behind numerical equivalence, sanitizer, cross-build, and measured retain gates.
