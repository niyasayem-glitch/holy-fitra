# HF Compiler-Cache Invalidation Profile

## Scope and method

This profile measures the current **single-file native compiler cache** on the host. The runner uses the maintained arithmetic smoke source already exercised by the compiler suite (126 UTF-8 bytes), a fresh temporary project for each sample, and eleven repetitions of each scenario. It clears the in-process compile cache before every measured build, approximating the cache path used by a newly launched command-line compiler while intentionally excluding Python process-start cost.

The runner records the compiler receipt time and surrounding wall time. It verifies the expected artifact-cache result for every sample, profiles one cold build and one warm disk-artifact hit with `cProfile`, and stores a machine-readable result using `holyfitra.compiler-cache-profile/v1`. It does not measure Android, Termux, physical devices, multi-module compilation, or a parser-valid production-scale native source.

## Current invalidation contract

`compile_native_file` derives its digest from the exact source text, effective target, LLVM cache schema, and native compiler ABI. A changed source digest creates a distinct persisted LLVM record and distinct native artifact cache entry. Before accepting a persisted LLVM record, the compiler validates its schema, digest, and LLVM SHA-256. Before accepting a native artifact, it validates the artifact SHA-256 and copies it to the requested output location. A process-local LRU can skip parsing and persisted-cache validation only while the same digest remains resident.

| Scenario | Expected artifact-cache result | Mean compiler receipt time | Measured interpretation |
|---|---:|---:|---|
| Cold build | Miss | 44.163 ms | Full source-to-native artifact path. |
| Warm disk artifact | Hit | 0.616 ms | Fresh-process approximation; persisted LLVM, source parsing, artifact integrity validation, output copy, and telemetry still occur. |
| Comment-only source edit | Miss | 41.431 ms | Exact-text digest invalidates an otherwise unchanged emitted program. |
| Semantic source edit | Miss | 41.105 ms | Expected source-to-native invalidation. |
| Corrupt persisted LLVM with valid artifact | Hit | 1.004 ms | The LLVM JSON is recovered while the validated native artifact avoids Clang. |

The warm artifact path was **71.75×** faster than the cold mean on this fixture. Comment-only invalidation measured **0.938×** of a cold build, while semantic invalidation measured **0.931×**. A corrupt LLVM record added a **1.63×** overhead relative to a warm artifact hit, but remained far below a Clang-invoking cold build.

## Measured bottlenecks

The cold `cProfile` sample spent approximately 40 ms of its 44 ms total in the Clang subprocess communication/wait path. The compiler’s own `compile_native_file` path consumed approximately 2 ms, including two atomic writes whose `fsync` operations together accounted for approximately 1 ms in that sample. This identifies external native compilation, rather than Python parsing or cache-key computation, as the dominant cold-path cost on the small maintained fixture.

The warm profile had only millisecond-level total duration, so it does not justify sub-millisecond causal claims. It does confirm the current control flow: a fresh process still reads and parses the source, validates the persisted LLVM payload, validates the native artifact hash, copies the artifact when needed, and appends telemetry before reporting a hit. These steps are a **potential** warm-path scaling cost, not a demonstrated bottleneck at 126 bytes.

> The profile proves cache behavior and timing only for the declared host fixture. It does not prove a causal cost model for larger programs, cross-target compilation, Android builds, or physical devices.

## Decision and next evidence gate

No cache semantic change is retained from this investigation. Full-text invalidation is conservative and correct under the current contract, but comments create a complete cache miss even when emitted LLVM is unchanged. A token- or semantic-signature candidate could reduce such misses, but it must first preserve source-position-sensitive `Program` behavior, diagnostics, target/schema/ABI separation, malformed-cache recovery, and native artifact integrity. It is not safe to treat comment stripping as a drop-in key change while the in-memory cache returns a previously parsed `Program`.

The next practical profiling increment is a maintained, parser-valid larger native fixture with per-stage receipt timing. Only after that evidence should HF decide whether to pursue semantic cache identities, module-level dependency fingerprints, or a lower-overhead warm artifact validation path.
