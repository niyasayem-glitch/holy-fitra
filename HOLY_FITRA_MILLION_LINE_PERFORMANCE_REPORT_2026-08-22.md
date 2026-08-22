# Holy Fitra Million-Line Performance Report

**Date:** 2026-08-22

**Repository baseline:** `b28d15a` before this benchmark hardening pass

**Platform:** x86-64 Linux sandbox with Clang/LLVM host tools

## Executive result

Holy Fitra processed a valid one-million-line sparse source file successfully. The native seed emitted LLVM in approximately **10.6 ms**, while the warmed v1 shell path completed check in approximately **31.1 ms**. The Python compiler completed the same check in approximately **61.2 ms**. These correspond to roughly **94.7 million**, **32.2 million**, and **16.3 million source lines per second**, respectively, for this comment/blank-line-heavy corpus.

The sparse corpus contains one million physical lines but only a minimal semantic program. It measures source reading, line accounting, lexing, and low-token overhead; it is not evidence that one million functions or statements compile in those times.

## Corpus

| Corpus | Lines | Bytes | Expected result |
|---|---:|---:|---|
| Sparse valid | 1,000,000 | 1,000,052 | Accepted, LLVM assembled, executable built and ran with exit code 0. |
| Dense semantic | 1,000,000 | 32,888,875 | Rejected at the 8 MiB source limit. |
| Near-limit dense | 220,000 | 7,148,872 | Rejected at the token limit after hardening; no semantic explosion. |

The initial near-limit run exposed a serious resource problem: the Python compiler consumed approximately **563 MiB** and timed out at **180 seconds** while lexing/retaining a dense semantic source. This was a real fail-open scalability defect, not a benchmark inconvenience.

## Corrective optimization

The safety contract now defines a shared **65,536-token limit** and a **4,096-function limit**. Both Python and native lexers reject as soon as the token bound is reached, before retaining an oversized token collection. The parser also rejects excessive function count before constructing additional function AST nodes.

After the fix, the same near-limit dense corpus rejected in approximately **142.6 ms** with approximately **41 MiB** sampled peak high-water memory. Compared with the timed-out baseline, the bounded rejection was over **1,262 times faster** and used roughly **13.4 times less sampled memory**. The correct result is rejection, not compilation, because the input violates the v1 resource contract.

## Measured host timings

| Operation | Elapsed | Status | Sampled peak HWM |
|---|---:|---:|---:|
| Seed compiler build | 2,672.2 ms | Passed | 69,284 KiB |
| Native seed sparse emit | 10.6 ms | Passed | Too short for reliable `/proc` sampling |
| LLVM assembler validation | 10.5 ms | Passed | Too short for reliable sampling |
| Native seed dense rejection | 10.4 ms | Passed | Too short for reliable sampling |
| Python sparse check | 61.2 ms | Passed | 26,712 KiB |
| Python dense rejection | 61.5 ms | Passed | 32,012 KiB |
| Python near-limit rejection after fix | 142.6 ms | Passed | 41,920 KiB |
| v1 sparse check, cold seed | 2,562.1 ms | Passed | 3,792 KiB |
| v1 sparse check, warm seed | 31.1 ms | Passed | 3,740 KiB |
| v1 sparse build | 61.4 ms | Passed | 3,772 KiB |
| v1 executable run | 10.5 ms | Passed | Too short for reliable sampling |
| v1 dense rejection | 10.6 ms | Passed | Too short for reliable sampling |
| v1 near-limit rejection | 31.0 ms | Passed | 3,752 KiB |

Memory for short-lived native processes is marked as unreliable because the benchmark samples `/proc/<pid>/status` every 10 ms. The Python and seed-build samples were long enough to observe meaningful high-water values.

## Regression evidence

The corrected benchmark generator and measurement runner passed corpus validation, native/Python sparse acceptance, dense source-limit rejection, near-limit semantic rejection, LLVM assembly, v1 build/run, and deterministic status classification. The permanent v1 regression now includes oversized fixed-array and string-literal cases. The new shared token bound is covered by the stress harness.

The final repository gate was rerun after the benchmark and safety changes. The full Python suite, compileall, shell syntax, State-1–9 bootstrap, Termux host tests, v1 regression, and compiler stress all passed. Native strict tests and sanitizer/fuzz gates also passed during the same post-fix campaign. The deterministic release packager was corrected to create its tools staging directory, then archive generation and benchmark-asset inclusion passed.

## Interpretation and limits

This is host x86-64 evidence only. It does not measure Android, AArch64 runtime execution, NEON/SVE kernels, JNI on ART, big.LITTLE scheduling, thermal throttling, or device memory bandwidth. The native seed remains a bounded scalar compiler subset and the one-million-line sparse test does not establish one-million-line semantic compilation. The dense corpus demonstrates that the compiler refuses unsafe workloads rather than allowing them to consume unbounded memory or time.
