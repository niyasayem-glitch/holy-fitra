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

## Retained fixes

The compiler now centralizes constant signed division in `_signed_truncating_division`. It rejects zero divisors and computes a magnitude quotient before applying the sign, yielding the same truncation direction as generated LLVM signed division. New compiler regressions cover negative dividend, negative divisor, both negative, native executable behavior, and zero-divisor rejection.

The campaign also exposed a pre-definition call in `nibbleflow_kernel.c`: the ARM64 branch of `nibbleflow_int4_f32_batch4` called `nibbleflow_int4_f32` before that function was declared. A prototype now precedes the batch wrapper. This is a build-correctness repair; it does not alter the kernel’s algorithm or establish device performance.

## Validation record

| Gate | Result | Evidence boundary |
|---|---|---|
| Focused compiler suite | Pass: 41 tests | Includes signed-division execution and zero-divisor rejection |
| Documented compiler/core suite | Pass: 114 tests | Python/compiler/runtime contracts only |
| Native NibbleFlow host tests | Pass | Android wrapper and batch-runtime host fixtures |
| ASan/UBSan NibbleFlow host gate | Pass | Host execution only |
| Strict AArch64 Android-21 object | Pass | Cross-object generation and ELF architecture only; not Bionic linking or device execution |
| Full aggregate Termux runner | Initially exposed declaration error | Its Python phase completed 280 tests; its stale AArch64 object gate failed before the repair and was replaced by the focused post-repair cross-object gate above |

## Next bounded opportunities

The next justified work is to profile compiler cold-build stages on a larger, real source fixture; remove only measured frontend or process-launch overhead; and add a separate Android NDK/Bionic build receipt. Any architecture-specific kernel work should remain behind numerical equivalence, sanitizer, cross-build, and measured retain gates.
