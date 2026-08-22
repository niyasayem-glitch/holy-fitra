# Holy Fitra Million-Line Benchmark Contract

**Date:** 2026-08-22

## Purpose

Measure the host performance and safety behavior of the current native-first v1 toolchain on a controlled one-million-line source file. The benchmark must distinguish throughput of reading and lexing a large sparse source from throughput of building a million-line semantic AST.

## Corpus definitions

| Corpus | Construction | Expected result |
|---|---|---|
| Sparse valid | 999,999 short comment/blank lines followed by a minimal valid `module`/`fn main` program, staying below the 8 MiB v1 source limit | Accepted, emits LLVM, builds, and runs. Measures source scanning and low-token overhead. |
| Dense semantic | One million valid-looking declaration/statement lines whose byte size exceeds the hard source limit | Rejected quickly with a bounded source-size diagnostic. It must not allocate or compile the full semantic corpus. |
| Near-limit dense | 220,000 valid-looking function lines, generated below the 8 MiB source limit when possible | Measures the largest accepted semantic workload; if it crosses the limit on a toolchain or naming policy, rejection remains the correct result. |
| Deep expression | A bounded nested expression beyond the AST depth limit | Rejected with a structured nesting diagnostic, not a crash or timeout. |

## Measurements

Record source bytes, line count, generation time, cold seed-build time, cold check/emit/build time, warm-cache time, executable result, and peak resident memory where `/usr/bin/time` is available. Repeat accepted-path measurements at least three times. Use the same x86-64 host and toolchain for all runs.

## Safety requirements

No benchmark may disable source, token, AST, or memory limits. A timeout is a failure, not a performance result. The dense corpus’s rejection is a successful safety result, not a compilation-speed result. A blank-line-heavy corpus cannot be presented as one million semantically compiled lines; it measures source scanning and line accounting. The near-limit dense corpus is the semantic scaling measurement. No Android, AArch64 runtime, or device-performance conclusion may be inferred from this host benchmark.
