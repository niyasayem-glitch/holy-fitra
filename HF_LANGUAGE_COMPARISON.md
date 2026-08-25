# HF Bounded Cross-Language Test

## Scope

This investigation is a reproducible **host-only microbenchmark**, not a claim to have tested every programming language or to have produced a universal ranking. It tests the representative toolchains actually available in this sandbox: C and C++ via Clang 18.1.3, JavaScript via Node.js 22.13.0, Python via CPython 3.12.3, and Holy Fitra’s current native scalar compiler. Rust, Go, and Java were detected as unavailable and were not installed solely to manufacture coverage.

The runtime fixture accepts a dynamic iteration count and seed, runs the same unsigned 32-bit xorshift state transition 10,000,000 times, and reports the final state plus loop-only elapsed time. Each implementation produced the independently calculated result `3882214040` in every recorded run. Execution order rotated across nine samples. This protects against a constant-folded workload and reduces fixed first-run ordering bias, but does not make the result representative of I/O, allocation, garbage collection, concurrency, Android, or real applications.

> The Computer Language Benchmarks Game cautions that microbenchmarks are easy to measure but “far from realistic.” The local result is interpreted under that same limit.[1]

| Runtime implementation | Mean loop time | Relative to Clang C | Result verification |
|---|---:|---:|---|
| C / Clang | 13.768 ms | 1.000× | Exact dynamic-input result in 9/9 runs |
| C++ / Clang | 13.723 ms | 0.997× | Exact dynamic-input result in 9/9 runs |
| Node.js / V8 | 15.620 ms | 1.135× | Exact dynamic-input result in 9/9 runs |
| Python / CPython | 2,817.689 ms | 204.648× | Exact dynamic-input result in 9/9 runs |
| Holy Fitra native scalar | Not ranked | Not applicable | Separate functional loop compiled and returned 45 |

The C and C++ difference is small relative to ordinary host noise, so this test does not establish one as faster. Node.js was close on this narrow integer workload, while CPython took substantially longer. Those observations apply only to the stated engines, versions, flags, and host. They must not be generalized to library-backed numerical code, JIT warm-up behavior beyond the measured loop, or any Android target.

## HF-specific result

HF’s original functional fixture exercised mutable local state and a `while` loop, compiled through the existing `holyfitra_compiler.py build` route, and returned the expected exit status `45` in every cold-build round. It was initially excluded from the dynamic-input runtime ranking because the scalar `main` contract had no input primitive. That gap is now addressed by the separately documented bounded `arg_i32` bridge. Its new dynamic LCG result is recorded in `HF_DYNAMIC_INPUT_BRIDGE_RESULTS.md`; it must not be retroactively merged into this loop-only timing table because the metrics differ.

| Cold-build fixture | Mean wall time | Interpretation |
|---|---:|---|
| C / Clang xorshift source | 44.171 ms | Native C compiler and source fixture. |
| Holy Fitra functional loop | 106.999 ms | HF source lowers to LLVM, then invokes Clang; source and work differ from the dynamic-input fixture. |
| C++ / Clang xorshift source | 221.863 ms | Native C++ compiler and source fixture. |

These build times are recorded for operational context only, not a fair compiler ranking: the source programs, front-end work, and emitted IR differ. They reinforce the earlier HF cache profile’s conclusion that the downstream Clang invocation dominates small cold builds, but do not identify an HF language-runtime execution deficit.

> Managed-runtime performance depends on interactions among JIT compilation, thread libraries, garbage collection, and workload characteristics. A single integer loop cannot represent that full system.[2]

## Tested coverage and next gate

| Toolchain | Runtime loop | Cold build | Reason for any exclusion |
|---|---|---|---|
| C / Clang | Tested | Tested | Available locally. |
| C++ / Clang | Tested | Tested | Available locally. |
| Node.js / V8 | Tested | Not comparable | No ahead-of-time build step equivalent to the C fixtures. |
| Python / CPython | Tested | Not comparable | No ahead-of-time build step equivalent to the C fixtures. |
| Holy Fitra | Functionally tested only | Tested | No supported dynamic-input primitive in the scalar native subset. |
| Rust, Go, Java | Not tested | Not tested | Toolchains absent; no unreviewed installation was added under memory pressure. |

The highest-value next HF test is not another language ranking. It is a bounded native input bridge—such as a verified `main(args)` or explicit deterministic input primitive—followed by a numerical-equivalence and diagnostics suite. That would allow HF to execute the same nonconstant runtime fixture, while retaining the separate host, Android, and device evidence gates.

## References

[1]: https://benchmarksgame-team.pages.debian.net/benchmarksgame/index.html "The Computer Language Benchmarks Game"
[2]: https://www.usenix.org/conference/atc22/presentation/lion "Lion et al., Investigating Managed Language Runtime Performance"
