# HF Gap-Closure Plan

## Measured starting point

The current portable tiled/batched fallback reaches 10.220 GMAC/s on the 1,024 × 1,024 × 32 host fixture. Its matched three-thread OpenBLAS FP32-expanded comparator reaches 96.214 GMAC/s, leaving a 9.41× host gap. Compiler diagnostics confirm that the outer row/tile loops vectorize on the AVX-capable host, while the critical per-group/pair accumulation loops do not. This is consistent with decode, scaling, and accumulation dependencies rather than an absence of general SIMD hardware.

## Architecture-specific next path

HF’s static-INT8 activation mode already provides the input representation that an ARM I8MM path requires. ARM’s I8MM guidance describes `SMMLA` / `vmmlaq_s32` as an int8 matrix multiply-accumulate primitive with int32 accumulation, and shows it progressing in multiple rows and columns.[1] However, I8MM is an optional ARMv8.6 extension, so it must never replace the universal NEON/scalar route without a verified runtime-capability gate. The current HF packed-INT4 weights also require a separately tested block expansion/repacking design; the existing FP32 activation path cannot be silently routed through an int8 kernel.

The next implementation therefore has three non-negotiable layers: an independently implemented four-row static-INT8 packed-weight block path; a per-device capability gate that falls back on all non-I8MM hardware; and a testable receipt that states which kernel family ran. It will not pretend that a host x86 result measures I8MM, and it will not use a compile-time-only ARM feature guard as a device capability check.

## Why the design is block-first

Arm’s Neon matrix guide demonstrates that multiple independent accumulators reduce pipeline dependency pressure, while gemmlowp’s kernel model separates packed format from architecture-specific block execution.[2] [3] The design target is therefore a defined `rows × four outputs × depth block` contract, rather than arbitrary instruction substitution. A correct block format will also make later SVE2, I8MM, or packed-activation paths comparable under one numerical contract.

## Rejected host AVX2 experiment

An independently implemented runtime-gated eight-row AVX2 experiment preserved the benchmark checksum, but did not clear the retain gate. A five-sample mean suggested only 1.028× improvement; the stronger 20-pair interleaved comparison measured a 0.989× geometric speed ratio, with a 3.041 ms AVX2 mean versus 2.992 ms for the validated four-row path. The AVX2 route was removed rather than retained. Its avoidable per-pair lane construction did not overcome the existing packed-nibble decode and scaling overhead.

## Rejected custom scheduler experiment

HF also evaluated an independently designed priority-lane scheduler instead of importing a generic queue. Both a four-lane FIFO candidate and a deadline/sequence-heap refinement passed scheduler, batch-runtime, priority-order, 100-round multi-producer stress, and ASan/UBSan checks. However, each failed the same 20-pair host dispatch retain gate: the FIFO version measured 0.569× paired geometric throughput and the heap refinement measured 0.592×, with neither faster in any pair. The scheduler source was restored to the previously validated queue, so this produces no retained runtime performance claim. It is host-only evidence and does not establish Android or big.LITTLE behavior.

The next candidate is therefore not a wider FP32 broadcast kernel or another unmeasured queue rewrite. It is a static-INT8 block contract suitable for a later ARM I8MM path, accompanied by explicit packing and numerical-error gates. That candidate remains design-only until an Android NDK sysroot and real ARM64 measurement surface are available.

## References

[1]: https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/optimize-llama-cpp-with-arm-i8mm-instruction "Arm: Optimize Llama.cpp with I8MM"
[2]: https://support.arm.com/documentation/102159/0400/Matrix-multiplication "Arm Neon matrix multiplication guide"
[3]: https://github.com/google/gemmlowp/blob/master/doc/kernel.md "gemmlowp kernel design"
