# HF Upgrade Campaign

## Non-negotiable performance baseline

The prior pure-Python test was a correctness floor, not a competitive performance target. The stronger comparison expands the exact same deterministic packed-INT4 fixture to FP32 and executes the batch with OpenBLAS SGEMM, configured with three OpenBLAS threads. Both paths produce exact output sum and weighted checksum agreement within `1e-6`.

| Host-only result | HF INT4 runtime | OpenBLAS FP32 expanded fixture |
|---|---:|---:|
| Matvec dimensions / batch | 1,024 × 1,024 / 32 | 1,024 × 1,024 / 32 |
| Dense-equivalent MACs | 33,554,432 | 33,554,432 |
| Matched samples | 5 | 5 |
| Mean batch latency | 7.890 ms | 0.349 ms |
| Range | 6.375–11.724 ms | 0.268–0.432 ms |
| Throughput | 4.253 GMAC/s | 96.214 GMAC/s |

OpenBLAS is **22.62× faster** than the current HF host runtime on this particular host and expanded FP32 baseline. This is intentionally an uncomfortable but useful result: HF cannot be described as competitive with optimized native linear algebra on this workload. It does **not** prove the same ratio on ARM64/Android, because the current host binary follows NibbleFlow’s scalar fallback while its NEON path is AArch64-only. It also does not erase INT4’s memory-footprint advantage; it identifies a kernel and scheduling throughput gap that must be closed with measured work.

## First audit finding

The current scalar fallback loops one output at a time, repeatedly reloads input values across the four packed output lanes, and executes scalar nibble decode / float multiply-add operations. The AArch64 NEON implementation already recognizes output tiles of four lanes but currently expands bytes and scalar constructs inside its inner pair loop. The immediate high-value target is therefore a **portable output-tile kernel** that makes four output lanes the fundamental fallback unit, then a separately tested ARM64 NEON rewrite that removes stack-array decode/construct overhead. Neither change should be accepted merely because it looks vectorized; each needs numerical equivalence, sanitizer checks, host baseline improvement where applicable, and later Android evidence.

## Evidence limits

All values in this record are x86-64 host results. No Android ABI, ART/JNI lifecycle, ARM64 NEON throughput, core affinity, thermals, battery use, or physical-device latency is claimed. OpenBLAS is credited at <https://github.com/OpenMathLib/OpenBLAS>; its FP32 expanded model is a stronger comparator, not code imported into HF.

## Whole-system audit

| Layer | Verified state | Bottleneck or gap | Candidate upgrade | Evidence required |
|---|---|---|---|---|
| INT4 kernel | Scalar host fallback is one-output-at-a-time; ARM64 path tiles four outputs but decodes through scalar stack arrays in the inner loop. | Repeated input loads and nibble decode; no host SIMD path. | **P0:** portable 4-output tile fallback; **P1:** register-first ARM64 NEON 4×depth block. | Numerical equivalence, host benchmark, sanitizer; separate Android run. |
| Batch runtime | Bounded batch ranges and deterministic receipt state are present. | Rows are scheduled independently of kernel-level input block reuse. | P1: batch-aware `M×K×N` microkernel API after P0 kernel is stable. | Range/cancellation tests and matched throughput benchmark. |
| Scheduler | Priority/deadline/thermal policies and stealing are implemented. | Pop and steal linearly scan each protected deque; submit also scans worker queues. | Custom priority lanes and deadline heaps were tested and rejected on the host dispatch gate; profile topology or compiler-cache work before another queue redesign. | Queue-contention, fairness, deadline, cancellation, and device tests. |
| Topology | Sysfs capacity/frequency classification and conservative worker counts are present. | Fallback fabricates an eight-CPU layout when sysfs is unavailable. | P1: truthful unknown-topology mode rather than inferred big/little partition. | Topology unit tests and Android device validation. |
| JNI / buffers | Direct buffers and global references avoid per-request data copies; lifecycle leases guard handles. | Registry access is globally serialized; effect unmeasured. | P2: sharded registry only if JNI concurrency profiling justifies it. | JNI lifecycle and contention testing. |
| Compiler | Self-hosted seed has bounded lexer/parser/type/lowering, LLVM textual emission, exact-source persistent LLVM/artifact cache entries, and cache telemetry. | The first host cache profile shows cold builds dominated by Clang; comment-only edits fully invalidate exact-text cache entries. No parser-valid large native fixture or module-level invalidation record exists yet. | P1: first add a larger maintained native fixture and per-stage receipts; then consider source-safe semantic or module dependency fingerprints only if their invalidation behavior is proven. | Compiler corpus correctness, cache hit/miss/invalidation, deterministic output, and stage-timing tests. |
| Android build | Release target uses `-O3`, section garbage collection, and hidden visibility. | No optional LTO/PGO measurement gate and host CMake cannot link JNI without NDK headers. | P2: opt-in Android LTO matrix, only retained if NDK package size/latency regressions pass. | Android NDK build, package size, and device measurements. |
| Studio / cloud | Local rules, contracts, capsules, and manual cloud backup are user-controlled. | No reliable native compiler execution inside the app, by design. | Keep explicit host handoff; ingest only matching host/CI receipts. | Host/CI receipt validation, no device performance claim. |

## External guidance applied

The gemmlowp kernel and design documentation separates a packed format from an architecture-specific inner block kernel, emphasizing register reuse and cache-friendly traversal.[1] [2] This supports HF’s plan to optimize only after defining a stable tile format and benchmark gate, rather than adding arbitrary SIMD instructions. ExecuTorch’s XNNPACK overview confirms that mobile CPU kernels are backend-specific and that operator/lowering selection must precede a direct runtime comparison.[3] HF will therefore not claim equivalence to an XNNPACK or OpenBLAS backend until it has a matched operator and target build.

## References

[1]: https://github.com/google/gemmlowp/blob/master/doc/kernel.md "gemmlowp kernels"
[2]: https://chromium.googlesource.com/external/github.com/google/gemmlowp/+/HEAD/doc/design.md "gemmlowp design"
[3]: https://docs.pytorch.org/executorch/stable/backends/xnnpack/xnnpack-overview.html "ExecuTorch XNNPACK backend"

## Selected upgrade cohort

The P0 cohort is a portable **4-output-tile FP32 activation / packed-INT4 weight fallback**. It will reuse each two-element activation pair across the four packed output lanes, preserve existing per-group scale semantics, and retain the old single-output loop only for a tail smaller than four outputs. This is a direct response to the measured scalar bottleneck and remains independently implemented.

The cohort deliberately excludes a premature XNNPACK dependency, OpenBLAS runtime dependency, queue replacement, cache implementation, LTO, and ARM assembly rewrite. Each is valuable only after a smaller correctness-preserving kernel change establishes a better baseline.

## Measured cohort result

The portable four-output fallback reduced the five-sample host mean from 7.890 ms to 6.650 ms, a **1.187×** gain, while preserving both deterministic checksums within `1e-6`. The follow-on four-row batch helper reuses packed weights across compatible FP32 rows inside each existing runtime range. With both changes, the host mean fell to **3.283 ms**, or **10.220 GMAC/s**: a **2.403×** improvement over the original 7.890 ms path. The matched OpenBLAS FP32-expanded comparator remains 9.41× faster on this host, which is an honest remaining gap rather than a success claim.

The direct batch API and shared-request batch runtime passed their focused regressions, the neighboring runtime and scheduler regressions, 100 repeated direct-plus-runtime stress rounds, and AddressSanitizer/UndefinedBehaviorSanitizer on the large fixture. The bare host cross-compiler could not verify the AArch64 object because an Android NDK sysroot is unavailable in this sandbox. The AArch64 branch deliberately keeps the established per-row NEON route until a separately tested multi-row NEON microkernel is available. No Android package, device, thermal, or ARM throughput result is claimed.

## Rejected custom scheduler cohort

The scheduler cohort was tailored to HF’s four priority values, earliest-deadline rule, core-class/thermal filtering, cancellation, shutdown drainage, and batch receipt semantics. It did not import an external scheduler. Targeted priority ordering, batch runtime, 100 multi-producer all-priority stress rounds, and ASan/UBSan passed for both a lane/deque version and a lane/heap refinement. The required 20-pair interleaved 20,000-task host benchmark did not retain either implementation: the deque candidate achieved 0.569× paired geometric throughput and the heap candidate 0.592×, with 0/20 faster pairs in each run. The source was restored to the last validated scheduler. These measurements are host-only and do not imply Android worker, thermal, or big.LITTLE results.

## Compiler-cache invalidation profile

The first reproducible compiler-cache profile used the maintained 126-byte native arithmetic fixture, 11 fresh-project samples per scenario, and cleared the in-process cache before each timed build. The cold mean was 44.163 ms; a warm persisted artifact hit averaged 0.616 ms (71.75× faster). Both comment-only and semantic edits produced full artifact-cache misses, averaging 41.431 ms and 41.105 ms respectively, because the cache identity includes exact source text. A corrupt persisted LLVM payload recovered behind a valid artifact hit in 1.004 ms. One cold `cProfile` sample spent about 40 ms waiting for the Clang subprocess, making native compilation—not Python parsing—the measured small-fixture cold-path bottleneck. No cache-key semantics changed. The profile is host-only, excludes Python startup, and does not establish large-project, Android, or device behavior; see `HF_COMPILER_CACHE_PROFILE.md` for the contract and next gate.

## Bounded cross-language test

HF was tested against the high-performance and mainstream toolchains available in this sandbox: C and C++ through Clang 18.1.3, Node.js 22.13.0, and CPython 3.12.3. Nine rotating samples of an identical dynamic-input 10,000,000-iteration xorshift32 loop produced the same final state for each tested runtime. Mean loop time was 13.768 ms for C, 13.723 ms for C++, 15.620 ms for Node.js, and 2,817.689 ms for CPython. HF’s scalar frontend compiled and executed a separate mutable-loop fixture correctly, but it has no current argv/console/input primitive, so it was intentionally not assigned a runtime rank. Its 106.999 ms cold-build timing is operational context only, not a compiler ranking. Rust, Go, and Java were unavailable rather than silently substituted or installed. This remains a host microbenchmark, excludes Android and application workloads, and is documented with exact coverage and references in `HF_LANGUAGE_COMPARISON.md`.

## Retained dynamic-input bridge

HF now has an independently implemented `arg_i32(position, fallback)` builtin for a parameterless `main` that explicitly declares `effects [io]`. It accepts only literal positions `0..7`, validates signed decimal argv content with a bounded emitted LLVM helper, and falls back on absent, malformed, trailing-content, or out-of-range input. It preserves legacy parameterless-main ABI when unused and exposes no general process, file, environment, shell, stdin, or network API. All 38 compiler regressions passed. A new nine-sample 10,000,000-iteration dynamic argv LCG32 host exercise measured whole-process means of 1.811 ms for C and 1.969 ms for HF (1.087×), with HF’s expected low-byte exit status verified in every run. This is retained capability evidence, not a universal performance win or a full-width HF numerical proof; Android/ARM/device behavior remains unmeasured. Details are in `HF_DYNAMIC_INPUT_BRIDGE_DESIGN.md` and `HF_DYNAMIC_INPUT_BRIDGE_RESULTS.md`.
