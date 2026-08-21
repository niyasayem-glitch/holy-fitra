# Holy Fitra Smooth-Performance Report

**Scope:** Fast and smooth execution across the decoding hot path.  
**Author:** Manus AI  
**Status:** Host-validated prototype; physical Android performance not claimed.

## Executive Summary

The highest-leverage smoothness bottleneck in the current speculative prototype was not the mathematical decoding rule. It was avoidable hot-loop overhead: copying prefix lists for every proposal token, allocating proposal and emission lists dynamically, recomputing softmax probabilities for an immutable Markov fixture, and using list-based cache transactions.

This cycle implemented `hyperc_smooth_runtime.py`, a specialized fast path that preserves the existing greedy semantics while using precomputed immutable transition tables, precomputed greedy-token tables, preallocated NumPy buffers, cursor-based cache transactions, direct state transitions, and a separate greedy execution path. The result remained exactly equivalent to target-only decoding and the existing speculative baseline on the deterministic fixtures.

A completed host benchmark with 512 tokens, draft length 5, and five repeats measured approximately **7.24 ms** for the baseline and **0.56 ms** for the smooth path, an observed **12.9× speedup** on this deterministic Markov fixture. A separate run measured approximately 7.34 ms versus 0.52 ms, or 14.2×. These are prototype x86-64 Python measurements, not neural-model or Android-device claims.

## What Was Optimized

| Bottleneck | Baseline behavior | Smooth path |
|---|---|---|
| Prefix handling | `list(self.cache.tokens)` and `prefix + proposal` in the hot loop | Read the last token from a preallocated cursor buffer |
| Proposal storage | New Python list per round | Reused NumPy `int32` proposal array |
| Emission storage | New list and concatenation on acceptance | Reused preallocated emission array |
| Probability calculation | Repeated max, exp, sum, and normalization | Precomputed immutable probability matrix |
| Greedy decision | Repeated `np.argmax` over probability rows | Precomputed greedy-token table |
| Cache transaction | Python list slicing and extending | Cursor checkpoint, rollback, and typed buffer commit |
| Execution path | Greedy and sampling share more machinery | Greedy fast path isolated from sampling correctness path |
| Output trimming | Over-generation can leave surplus state | Exact requested output count and cache cursor |

## Smooth Runtime Architecture

```text
immutable model tables
  → preallocated request buffers
  → cursor-based cache checkpoint
  → direct draft state transitions
  → direct target verification
  → bounded emission buffer
  → atomic cache commit
  → exact output trim
```

The optimization follows a general Holy Fitra rule:

> **Move invariant work out of the latency-critical path, preallocate bounded state, and keep safety checks at transaction boundaries rather than inside every scalar operation.**

The rule applies beyond the toy Markov fixture. For real transformers, the corresponding implementations are memory-planned KV pages, prepacked weights, cached kernel selection, precomputed strides, fused ARM64 kernels, and a separate sampling path that retains distributional guarantees.

## Correctness Validation

The smooth path passed four dedicated tests:

| Test | Result |
|---|---|
| Preallocated cache transaction | Passed |
| Exact target-only equivalence | Passed |
| Weak-draft equivalence to baseline | Passed |
| No overcommit of unrequested tokens | Passed |

The corrected post-reset validation also passed the restored language frontend suite with 5 tests, package suite with 3 tests, and Python syntax compilation for the smooth runtime and tests.

## Broader Smoothness Blueprint

The implemented fast path is one layer of a broader low-latency Holy Fitra design.

### Compilation smoothness

Use a persistent compiler service, content-addressed query cache, module-level invalidation, parallel parsing, compact diagnostics, and hot/cold optimization tiers. The first response should come from a fast debug tier, while expensive AOT specialization runs asynchronously and promotes only after proof validation.

### Memory smoothness

Use arenas for graph lifetimes, exact scratch-buffer planning, page pools for KV cache, slab allocation for small runtime objects, prepacked model pages, and bounded queues. Avoid allocation in decode loops and make backpressure explicit rather than allowing unbounded buffering.

### Inference smoothness

Separate prefill, decode, verification, and sampling kernels. Use shape-specialized plans, fused QKV or matvec operations, weight prepacking, persistent worker threads, adaptive speculative length, and target-model batch verification. Reuse buffers across requests and keep tokenizer, scheduler, and model threads decoupled through bounded ring buffers.

### Scheduling smoothness

Use priority classes, deadline-aware admission, hysteresis, minimum dwell time, thermal emergency profiles, and cancellation-safe state. A slow request should not block interactive work. The scheduler should report queue delay separately from kernel time so user-visible latency can be diagnosed.

### Tooling smoothness

Keep the editor connected to a long-lived compiler process, stream diagnostics incrementally, cache syntax trees, render HyperIR views lazily, and never block the UI on package signing or full model validation. The integrated workspace should show whether a result is provisional, cached, verified, or device-specific.

## Why the Benchmark Is Limited

The fast path uses deterministic Markov models whose next state depends only on the last token. That makes direct-state optimization appropriate and gives a clean equivalence oracle, but it does not represent the compute or memory behavior of a transformer. It also runs in Python on the sandbox host. Therefore the measured speedup is evidence that the identified overhead exists and can be removed in the fixture, not evidence of Android or neural-model speed.

The real Android implementation must preserve the same principles in native code: preallocated ARM64 buffers, packed weights, fused NEON kernels, cache pages, fixed-shape plans, and device-side differential tests. No physical Android latency, energy, or thermal result is claimed here.

## Regression Note

The post-reset full regression command could not run every historical test because some older transformer and quantization modules were absent from the restored workspace. The smooth-runtime suite, language frontend suite, package suite, syntax checks, and benchmark completed successfully. The missing historical modules are an environment-restoration limitation, not a failure of the new smooth path.

## Next Optimization Priorities

| Priority | Optimization | Validation gate |
|---:|---|---|
| 1 | Integrate preallocated buffers into real Android transformer decode | Exact transformer differential test |
| 2 | Replace scalar int4 unpacking with fused NibbleFlow NEON kernels | ARM64 numerical and device benchmark |
| 3 | Add bounded multi-request continuous batching | Tail-latency and fairness budget |
| 4 | Add persistent compiler query daemon | Warm incremental compile benchmark |
| 5 | Add page-pool KV cache | Allocation count and memory-pressure tests |
| 6 | Add smooth scheduler traces | Replayable queue, thermal, and cancellation decisions |
| 7 | Keep sampling separate from greedy fast paths | Distributional equivalence tests |

Holy Fitra becomes smooth not by deleting safety or correctness checks, but by moving invariant work to compile time, caching verified decisions, reusing bounded memory, and keeping runtime transitions explicit and transactional.

## References

[1]: https://llvm.org/docs/LangRef.html "LLVM Language Reference Manual"
[2]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[3]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
