# Holy Fitra Deep Repository Audit

**Author:** Manus AI
**Audit date:** 2026-08-22
**Repository:** [`niyasayem-glitch/holy-fitra`](https://github.com/niyasayem-glitch/holy-fitra)
**Scope:** Python compiler/runtime, Stage-0 and State-9 no-Python bootstrap, native NibbleFlow and ragged kernels, scheduler, JNI/Android integration, packaging, telemetry, AI contracts, quantization, persistence, and validation claims.

## Executive summary

Holy Fitra has made real progress: the repository contains a functioning scalar LLVM compiler, a substantial Stage-0 bootstrap path, State-9 parser-derived module/signature/call validation, native scheduling and quantized-kernel code, and a broad regression suite. The current baseline is reproducible on the sandbox host: **153 Python tests pass**, Python compilation and shell syntax checks pass, the no-Python bootstrap gate passes through State 9, Termux-compatible host validation passes, and AArch64 object emission succeeds as a cross-compilation artifact. These results establish a credible engineering foundation, but they do not establish production safety, a buildable Android package, general self-hosting, or physical Android performance.

The most serious risks are not isolated missing features; they are **trust-boundary inconsistencies**. The Android build files point to a native project that does not exist at the configured path. JNI handles are raw, unsynchronized pointers with unchecked signed-to-unsigned conversions and unchecked global-reference allocation. The ragged ABI has no buffer lengths, so it cannot prove memory safety. The CPU-topology parser mishandles the normal Linux range form `0-7`. The benchmark JSON can report completion after failures and can label scalar host execution as NEON. The HyperIR frontend silently accepts arbitrary garbage, while the native frontend has a separate grammar and rejects `pub` declarations used by the self-hosting path. The next effort should therefore prioritize **unifying the compiler frontends and hardening every native boundary before adding more AI surface area**.

> **Bottom line:** Holy Fitra is best described as a promising Stage-0 bootstrap and AI-runtime research repository with a State-9 self-hosted semantic foundation. It is not yet a production compiler, a generally safe native runtime, or a buildable Android library.

## Remediation status after the audit

The audit findings above describe the pre-remediation baseline and remain the historical record of why the P0 work was required. Subsequent edits produced a validated partial hardening patch. An `android-lib` project layout and host CMake graph now exist, JNI boundaries use opaque registry tokens and lifecycle leases, ragged buffers carry capacities with shared validation, Stage-0 managed resources use a pointer/kind live-resource bridge, and HyperIR routing is explicit with bounded fail-closed diagnostics. The updated scheduler drains queued work and converts task exceptions to terminal failure, while topology range parsing and runtime enum validation have regression coverage.

The P0 blockers are **not marked resolved**. The sandbox has no Gradle wrapper, Android SDK/NDK, or physical Android device, so Android packaging and execution are unverified. JNI tokens are not yet generation-tagged and have no real-JNI race stress evidence. The Stage-0 registry is a temporary pointer-ABI bridge rather than ABI-v2 handles; the HyperIR compatibility parser remains line-oriented rather than canonical; and ARM execution and finite-input ragged policy remain open. Post-remediation evidence is 155 passing Python tests, passing no-Python State-1–9 bootstrap and Termux-compatible host gates, passing native ASAN/UBSan regressions, and host-stub CMake linkage only.

## Audit method and baseline

The audit used source inspection, Git history and repository metadata, targeted adversarial probes, native sanitizer execution, and the existing validation scripts. No repository source files were changed during this audit; only the report and temporary evidence notes were created.

| Check | Result | Interpretation |
|---|---:|---|
| Python unit suite | Pass, 153 tests | Existing Python regression is green. |
| `python3 -m compileall -q .` | Pass | Python files compile. |
| Shell syntax checks | Pass | `bootstrap/test_bootstrap.sh` and `termux-build.sh` parse. |
| No-Python bootstrap gate | Pass through State 9 | Fixture-based bootstrap path is green. |
| Termux-compatible host gate | Pass | Host-side compatibility only; not a Termux-device run. |
| State-9 AArch64 object | 89,392 bytes | Cross-compilation artifact only; not Android execution. |
| Native ASAN/UBSan probe | No sanitizer report | The exercised ordinary path was clean; semantic acceptance defects still occurred. |
| Android Gradle build | Not runnable from repository layout | Required Gradle/CMake paths and project files are absent. |

The existing test suite is broad but mostly tests **happy-path bounded inputs**. It does not currently provide adequate coverage for JNI concurrency, malformed direct buffers, Linux CPU range syntax, ragged buffer bounds, hostile archives, cache tampering, NaN confidence/model values, parser depth, duplicate native parameters, or frontend differential equivalence.

## Priority model

| Priority | Meaning |
|---|---|
| **P0 — critical blocker** | Can cause memory unsafety, process termination, false success in a safety-sensitive path, or prevents the claimed platform from building. Fix before adding capability. |
| **P1 — high risk** | Can silently miscompile, misreport, deadlock, exhaust resources, or undermine a claimed contract under realistic inputs. |
| **P2 — medium risk** | Correctness, maintainability, reproducibility, or hardening weakness that should be fixed before production. |
| **P3 — design enhancement** | Important architectural improvement, but not itself a confirmed defect. |

## P0 findings

### P0-01 — Android integration is not a buildable Android project

**Evidence (historical baseline):** [`holyfitra_android_build.gradle.kts`](https://github.com/niyasayem-glitch/holy-fitra/blob/8eaf121c5ec59c36f7ef998fe2c6410b284840e7/holyfitra_android_build.gradle.kts#L1-L61) pointed `externalNativeBuild.cmake.path` to `src/main/cpp/CMakeLists.txt`, but the repository then contained only a root `CMakeLists.txt`. The repository also lacked `settings.gradle.kts`, a root Android `build.gradle.kts`, `src/main/AndroidManifest.xml`, and `src/main/cpp/CMakeLists.txt`. The separate benchmark Gradle fragment referenced `CMakeLists_benchmark.txt`, which was also absent at that baseline. The remediation now adds `android-lib/`, but Gradle/NDK packaging remains unverified.

**Impact:** An Android consumer cannot follow the documented Gradle integration as checked in. The current Android story consists of loose Kotlin/C++ sources and build fragments rather than a reproducible library module. This blocks APK/AAB packaging, ART loading, device validation, and meaningful JNI integration testing.

**Repair:** Create a real Android library module with pinned Gradle/AGP/Kotlin/NDK versions, move or reference the native sources from the correct relative path, add the manifest and source sets, build both debug and release `arm64-v8a` artifacts in CI, and run an emulator/device smoke test. Keep the root CMake build as a host-validation target rather than pretending it is the Android package.

### P0-02 — JNI runtime handles are raw unsynchronized pointers

**Evidence:** [`holy_fitra_jni.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_jni.cpp#L82-L187) casts Java `Long` values directly to `hf_jni_runtime*` and `hf_jni_request*`. `nativeClose`, `nativeSubmit*`, `nativeStats`, `nativeCancel`, `nativeWait`, and `nativeDestroyRequest` have no shared mutex, atomic closed-state, generation counter, or ownership registry.

**Impact:** Concurrent close/submit/stats or concurrent request wait/cancel/destroy can dereference freed memory. Repeated destruction is unchecked. A Java wrapper’s local `closed` boolean does not protect callers using multiple threads or stale handles. This is a genuine use-after-free and double-destroy risk at the managed/native trust boundary.

**Repair:** Replace raw pointer handles with a process-local handle table containing generation-tagged IDs, strong shared ownership, and per-runtime/request mutexes. Make close transition atomically to `CLOSING`, reject new submissions, drain or cancel requests, and release Java global references only after all native work has completed. Make request destruction idempotent and define a documented thread-safe lifecycle.

### P0-03 — Ragged attention cannot prove buffer safety

**Evidence:** [`holy_fitra_ragged_kernel.h`](https://github.com/niyasayem-glitch/holyfitra/blob/master/holy_fitra_ragged_kernel.h#L10-L22) carries pointers and dimensions but no q/k/v/output element counts and no offsets length. [`holy_fitra_ragged_kernel.c`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_ragged_kernel.c#L29-L58) dereferences offsets, rows, keys, and values without checking their total extents. The scheduler checks only that each adjacent offset increases in [`holy_fitra_ragged_scheduler.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_ragged_scheduler.cpp#L127-L131).

**Impact:** A caller can supply an offset endpoint beyond the allocated q/k/v/output memory and cause out-of-bounds access. The API has no information with which to reject this. On ARM, the NEON and SVE entry points also lack the scalar path’s null-pointer checks and can crash immediately on null q/k/v/output/offsets. The SVE path divides by `normalizer` without the scalar/NEON positive guard.

**Repair:** Extend the ABI with `q_elements`, `k_elements`, `v_elements`, `output_elements`, and `offsets_count`, or use byte lengths for every buffer. Add one shared preflight validator that checks non-null pointers, finite dimensions, monotonic offsets, endpoint bounds, multiplication overflow, and finite input/output policy. Call the same validator before scalar, NEON, and SVE paths. Add ARM-targeted malformed-input tests under QEMU or device CI.

### P0-04 — Stage-0 runtime ownership is not enforced

**Evidence:** [`bootstrap/holyfitra_runtime.c`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/bootstrap/holyfitra_runtime.c#L32-L69) frees dynamic arrays without a released marker; file and buffer close/free functions have the same raw-pointer design at lines 111–168 and 226–282. Stage-0 ownership annotations are carried as types/comments and are not converted into a runtime state machine.

**Impact:** Double-free, use-after-free, double-close, and stale-handle use are possible for compiler-generated or foreign-function code. A language claiming owned/shared/borrowed values cannot safely rely on callers to obey ownership comments. This is especially dangerous because compiler-core code exercises file and buffer primitives extensively.

**Repair:** Introduce opaque runtime handles with a header containing a magic value, kind, generation, and released state. Make free/close operations idempotent or return a typed error; reject wrong-kind handles. Add ownership-aware lowering so `owned` values have one destruction path and `borrow` values cannot be freed. Use sanitizer-backed negative tests for every primitive.

### P0-05 — The compatibility HyperIR frontend accepts malformed programs as valid

**Evidence:** [`hyperc_language_core.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/hyperc_language_core.py#L110-L219) processes recognized line patterns but does not reject unrecognized lines and does not require a function. A probe showed that `garbage syntax that is not a module` and `module x\nthis is not valid` both returned `valid=True`, with zero functions and no diagnostics. A malformed function body containing `nonsense` was also accepted.

**Impact:** Invalid source can be treated as a valid compilation plan. This is a direct violation of fail-closed compilation and makes downstream evidence meaningless. It also means that a comment or unsupported construct can be silently dropped rather than diagnosed.

**Repair:** Replace line-pattern recognition with a real token stream and grammar, require complete token consumption, require the minimum program structure, and emit an error for every unrecognized construct. Until then, make the compatibility frontend explicitly opt-in and never select it heuristically from source substrings.

## P1 findings — compiler correctness and self-hosting

### P1-01 — Two frontends have divergent grammars and semantics

The Python native parser accepts `fn` but not the `pub` visibility token used by State 9. The State-9 parser accepts public functions and parser-derived exports. A probe showed `pub fn main() -> i32 { return 42; }` is rejected by `holyfitra_compiler.parse_native`. This is not merely a missing feature; it means the repository has no single language definition. The native parser also puts `&&` and `||` in the same precedence loop ([`holyfitra_compiler.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L422-L468)), while Stage-0 has separate logical-or/logical-and functions ([`holyfitra_bootstrap.cpp`](https://github.com/niyasayem-glitch/holyfitra_bootstrap.cpp#L345-L351)). The same source can therefore parse differently depending on the frontend.

**Repair:** Publish one grammar and token/AST schema. Generate or mechanically embed the same parser tables where possible. Add differential tests that compile identical positive and negative fixtures through Python, Stage-0, and State-9 and compare AST shape, diagnostics, and emitted behavior.

### P1-02 — `check` and `bench` select a frontend from substring heuristics

**Evidence:** [`holyfitra_compiler.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L1232-L1250) and [`holyfitra_benchmark.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_benchmark.py#L24-L52) route source to HyperIR if the raw text contains `Tensor`, `capability`, or `budget`. A comment, string, or ordinary identifier is sufficient. Probes confirmed `// Tensor` and a variable named `Tensor` took the HyperIR route.

**Impact:** The CLI can report success from a different language implementation than the user intended. It also makes benchmark results depend on incidental text. This undermines reproducibility and can hide native compiler errors.

**Repair:** Use an explicit manifest/frontend field or a grammar-based detection pass that reports ambiguity. Better, unify both frontends behind one parser and use feature declarations in the module header.

### P1-03 — Duplicate native parameters are accepted and produce invalid LLVM

**Evidence:** [`holyfitra_compiler.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L555-L561) checks duplicate function names but not duplicate parameter names. A probe accepted `fn f(x: i32, x: i32) -> i32`; LLVM emission then created duplicate `%x` arguments and `%x.addr` allocas, and Clang rejected the IR.

**Repair:** Reject duplicate parameters during declaration collection with a source-span diagnostic. Add `llvm-as`/LLVM verifier execution to every native emission test so accepted source cannot produce invalid IR.

### P1-04 — Unreachable statements are not semantically checked

**Evidence:** [`validate_native`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L683-L740) breaks validation after a guaranteed return. `fn main() -> i32 { return 0; let x: bool = 1; }` was accepted and emitted only `ret i32 0`.

**Impact:** Diagnostics and source semantics diverge. Dead code can hide invalid types, ownership violations, and future effect/capability operations. This is particularly harmful during bootstrap because Stage-0 and Stage-1 can silently disagree about code after a return.

**Repair:** Continue type/effect checking after termination while separately marking statements unreachable. Emit an unreachable-code warning or error according to a language policy, but never skip semantic validation.

### P1-05 — Parser recursion and compiler resource limits are incomplete

The Python parser recursively handles parenthesized expressions and nested AST structures. Depth 1,000 produced `RecursionError` rather than a controlled diagnostic. The native CLI has no source-size, token-count, AST-depth, or compilation-time budget. `run` has no process timeout or resource limits ([`holyfitra_compiler.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L1083-L1120)).

**Repair:** Establish limits for source bytes, tokens, nesting depth, functions, statements, constants, and emitted IR. Convert recursion errors to structured diagnostics. For `run` and `test`, use process groups, wall-clock deadlines, CPU/memory limits where available, and forced group termination on timeout.

### P1-06 — Native cache artifacts are not independently verified

`compile_native_file` keys cache data by source/target/schema, but the `.native` artifact used by `build` is copied solely because its digest-named file exists ([`holyfitra_compiler.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py#L1038-L1120)). There is no stored executable hash, compiler/toolchain identity, or post-copy validation. The cache also omits the actual compiler binary version and Clang version.

**Impact:** A stale or locally modified artifact can be executed. Toolchain changes can reuse incompatible binaries. This is a supply-chain and reproducibility weakness even if the cache is normally local.

**Repair:** Store a signed/cache-manifest record containing source digest, compiler build ID, target triple, Clang version, linker identity, artifact SHA-256, size, and file mode. Verify the artifact before every cache hit and rebuild on any mismatch. Keep cache directories outside source trees in CI.

### P1-07 — Stage-0 LLVM identifiers are not escaped or reserved-name checked

The Stage-0 lexer accepts identifiers with dots, and the emitter places user names directly into `%struct.<name>`, `@<function>`, and `%<parameter>` identifiers ([`holyfitra_bootstrap.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_bootstrap.cpp#L332-L334) and lines 391–445). There is no LLVM identifier mangling layer.

**Impact:** Legal Holy Fitra names can produce malformed LLVM, collide with generated temporaries, or collide with builtin symbols. This blocks a trustworthy general backend.

**Repair:** Add a deterministic LLVM symbol-mangling layer with collision-resistant escaping, reserved builtin namespaces, and a symbol map retained for diagnostics. Verify all output with LLVM’s verifier before linking.

## P1 findings — Android, native kernels, and scheduler

### P1-08 — JNI signed-to-unsigned conversion breaks deadline and timeout validation

`deadline_ns` and `timeout_ms` arrive as signed Kotlin/Java `Long` values but are cast to `uint64_t` in [`holy_fitra_jni.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_jni.cpp#L90-L159). The native runtime then checks `deadline_ns < 0` even though the type is unsigned ([`holy_fitra_runtime.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_runtime.cpp#L81-L124)). Negative deadlines are therefore accepted as enormous future timestamps; negative waits become enormous positive waits instead of invalid arguments.

**Repair:** Validate `jlong < 0` before conversion, use a dedicated `HF_INVALID_ARGUMENT` path, and define whether deadlines are absolute monotonic nanoseconds or relative durations. Reject values exceeding platform-safe duration bounds.

### P1-09 — Direct-buffer ABI validation is incomplete

Both JNI layers use `GetDirectBufferAddress` and divide byte capacity by `sizeof(float)` without checking that the address is suitably aligned, the capacity is divisible by four, the buffer’s byte order is native, or `NewGlobalRef` succeeded. Kotlin helpers set native order only for newly allocated buffers; caller-provided direct/sliced buffers can violate assumptions. Android’s JNI guidance notes that global references are required for retained objects and that `NewGlobalRef` can return null on allocation failure [E1].

**Repair:** Require native byte order in the Kotlin API, validate alignment and exact byte lengths in JNI, reject non-multiple capacities, check every global-reference result, and use a single typed `DirectBuffer` validation routine. Prefer explicit byte-count APIs over inferred float counts.

### P1-10 — CPU topology parser mishandles normal Linux range syntax

[`holy_fitra_android_topology.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_android_topology.cpp#L19-L35) reads `/sys/devices/system/cpu/online` as one integer. For the normal content `0-7`, stream extraction yields `0`, so the function returns only CPU 0 and never scans the `cpuN` directories. A native probe produced `range_cpus=2 little=1 big=1` for an eight-CPU fixture because the fallback partition duplicated the lone CPU.

**Impact:** Core affinity and big.LITTLE classification are wrong on common Android/Linux systems. Performance measurements and thermal scheduling decisions become unreliable.

**Repair:** Parse comma-separated ranges (`0-3,6-7`) with overflow checks, intersect with actually present CPU directories, and treat malformed sysfs as an explicit degraded mode. Never synthesize eight CPUs for a production device without marking the topology unknown.

### P1-11 — Topology filesystem exceptions can escape the C ABI

`hf_runtime_create` calls `detect_android_topology()` before its `try` block ([`holy_fitra_runtime.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_runtime.cpp#L60-L72)). `directory_iterator` can throw on missing or inaccessible sysfs paths. The exception can cross an `extern "C"` API boundary and terminate the process.

**Repair:** Put all allocation, topology detection, scheduler construction, and model setup inside one exception barrier. Return a typed native error. Make topology detection `noexcept` at the public boundary.

### P1-12 — NibbleFlow model validation accepts non-finite scales and bias

[`nibbleflow_android.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/nibbleflow_android.cpp#L42-L60) verifies dimensions and capacities but not finite scale/bias values. A native probe reported `nan_scale=0`, where `0` is `HF_OK`. The kernel can consequently emit NaN/Inf results from an apparently valid model.

**Repair:** Validate every required scale and bias element with a bounded finite scan, define whether input/output finiteness is required, and include a model checksum/quantization proof in the ready-state transition. For very large models, validate during artifact loading and retain the result rather than rescanning on every matvec.

### P1-13 — NibbleFlow dimension arithmetic can overflow before size checks

`(in_dim + group_size - 1)` and related tile/group arithmetic are evaluated in signed 32-bit expressions in [`nibbleflow_android.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/nibbleflow_android.cpp#L7-L30) and [`nibbleflow_kernel.c`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/nibbleflow_kernel.c#L17-L27). Positive extreme dimensions can overflow before conversion to `size_t`.

**Repair:** Widen to checked `uint64_t`/`size_t` arithmetic, cap dimensions and total bytes, and ensure the kernel receives already-validated bounded values. Add maximum model dimensions to the artifact format.

### P1-14 — Ragged scheduler requests can hang after worker failure or shutdown

[`holy_fitra_ragged_scheduler.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_ragged_scheduler.cpp#L127-L171) calls `state->finish` only on normal/cancel/deadline paths. If a task callback throws, the generic scheduler catches the exception and the request’s `remaining` count is never decremented. Scheduler shutdown also stops worker loops without draining queued tasks or invoking their completion callbacks.

**Repair:** Wrap every task body in an RAII completion guard that decrements exactly once and records failure. Make scheduler shutdown drain/cancel queues, complete all associated requests, and expose a terminal `Stopped` result. Add deadlock tests that inject throwing callbacks and destroy schedulers with queued work.

### P1-15 — Scheduler compatibility wakeups are inefficient and thermal behavior is incomplete

`has_compatible_work` treats any non-empty queue as compatible for little workers, even if every task is `BigOnly` ([`holy_fitra_dispatch.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_dispatch.cpp#L150-L158)). This creates repeated wakeups/spin under incompatible workloads. The scheduler also ignores errors from `pthread_setaffinity_np`.

**Repair:** Make the wake predicate inspect task compatibility or maintain per-core-class queue counters. Record affinity failures and expose degraded placement in stats. Add fairness and starvation tests for BigOnly/LittleOnly tasks under thermal transitions.

## P1 findings — benchmark and evidence integrity

### P1-16 — Device benchmark JSON reports completion after failures

[`holy_fitra_device_benchmark.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark.cpp#L263-L281) always starts its JSON with `{"completed":true`, while `result.completed` is separately set false when failures occur. The JNI benchmark API returns the JSON string, not the separate C++ boolean.

**Impact:** A failed benchmark can be reported to Kotlin consumers as completed. This directly corrupts validation and performance evidence.

**Repair:** Serialize the actual result status, include a machine-readable error array, and make consumers reject `completed=false`, missing samples, non-finite metrics, or failed iterations. Add a regression fixture with forced submission failure.

### P1-17 — Host benchmark can label scalar execution as NEON

The benchmark sets `has_neon` true when topology has any CPUs, including synthetic fallback topology ([`holy_fitra_device_benchmark.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark.cpp#L187-L194)). On x86, the selected NEON entry point is compiled to the scalar fallback, yet the report can identify it as NEON.

**Repair:** Determine ISA from compile-time and runtime feature checks independently of topology. Report `compiled_kernel`, `executed_kernel`, and `hardware_isa` separately. Never use the existence of a topology list as an ISA signal.

### P1-18 — Benchmark workload construction lacks hard upper bounds

`max_length-min_length+1`, cumulative offsets, and total element counts can overflow in [`holy_fitra_device_benchmark.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark.cpp#L119-L141). JNI passes signed values directly ([`holy_fitra_device_benchmark_jni.cpp`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark_jni.cpp#L5-L31)).

**Repair:** Define maximum d_model, sequence count, sequence length, total tokens, and total bytes. Perform checked 64-bit arithmetic before allocation, then convert to `size_t` only after bounds are proven.

### P1-19 — Benchmark failures are downgraded to soft result fields

[`holyfitra_benchmark.py`](https://github.com/niyasayem-glitch/holyfitra/blob/master/holyfitra_benchmark.py#L53-L73) catches all exceptions from quantization and ragged demos and returns `{"error": ...}` while the command can still complete normally. It also measures repeated compilation using a persistent cache, so the default result is primarily a warm-cache measurement rather than a cold compiler measurement.

**Repair:** Add `--cold`, `--warm`, and `--verify` modes. Make validation mode fail nonzero on any missing subsystem or non-finite metric. Report cache-hit ratios and separately measure parse, semantic, emit, link, and execution stages.

## P1 findings — AI contracts, evidence, and persistence

### P1-20 — Agent evidence accepts NaN confidence

[`holyfitra_ai_system.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_ai_system.py#L19-L32) checks `0.0 <= confidence <= 1.0` but not `math.isfinite(confidence)`. NaN passes because the chained comparison is false and its negation is true.

**Impact:** Tool results can inject non-finite confidence into the evidence ledger. Downstream comparisons, serialization, or policy gates can behave inconsistently.

**Repair:** Require `math.isfinite`, exact numeric type policy, bounded content/provenance lengths, and canonical serialization. Apply the same rule to every evidence/quantization/telemetry contract.

### P1-21 — Claim verification is lexical overlap, not evidence verification

[`ClaimVerifier`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_ai_system.py#L150-L201) marks claims supported when token overlap reaches a threshold and uses a simplistic global negation set. It does not authenticate the source, validate claim structure, account for temporal validity, distinguish entity/number relationships, or require a trusted verifier.

**Impact:** A semantically unrelated fact with shared common tokens can satisfy `require_claims=True` and authorize a tool action. This is a safety-boundary weakness, not just an NLP-quality issue.

**Repair:** Split retrieval from verification. Require structured claims with entities, predicates, values, timestamps, and source IDs; use source-specific verifiers or signed attestations; make lexical overlap only a candidate-generation signal. Tool authorization should fail closed when verification is unsupported or ambiguous.

### P1-22 — Checkpoint and deployment loaders have no resource envelope

[`holyfitra_learning.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_learning.py#L357-L392) uses `np.load` on untrusted paths, while [`holyfitra_deploy.py`](https://github.com/niyasayem-glitch/holyfitra/blob/master/holyfitra_deploy.py#L119-L220) parses attacker-controlled headers, shapes, byte counts, and quantization arrays. There are no total file, header, metadata, element-count, or decompression budgets.

**Repair:** Add maximum artifact bytes, header bytes, metadata depth, total elements, array count, and decompressed bytes. Read through a bounded file object, reject dimensions before multiplication, validate all manifest fields strictly, and authenticate artifacts before loading when they cross trust boundaries.

### P1-23 — Quantized deployment validation does not bind proof to artifact identity

The deployment manifest records quantization metadata and quality thresholds, but the loader reconstructs arrays without a cryptographic binding between model bytes, calibration data, selected kernel, and device profile. The proof model in HyperIR similarly records identity strings but does not verify a signed/calibration artifact relationship.

**Repair:** Define a signed deployment envelope containing model digest, calibration digest, quantization spec, quality report, kernel implementation ID, target ABI, and fallback policy. Verify it before entering a `READY` state. Reject a proof copied from another model or calibration set.

### P1-24 — Telemetry is mutable, unbounded, and schema-free

[`holyfitra_telemetry.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_telemetry.py#L23-L139) allows an arbitrary `HOLYFITRA_TELEMETRY` path, appends without locking, reads the entire file using `readlines()` before slicing, silently skips malformed lines, and trusts event field types in `summarize_events`. A limit of zero or a negative limit does not provide the intended bounded behavior.

**Impact:** Telemetry can exhaust memory, be corrupted by concurrent writers, crash summaries on malformed numeric fields, or be forged. Performance dashboards are not suitable as evidence without integrity and schema checks.

**Repair:** Use rotating bounded logs, an event schema/version, length limits, atomic record framing or a lock, safe numeric parsing, and explicit corruption counters. Treat telemetry as advisory and never as proof of a compiler/runtime guarantee.

## P2 findings — packaging, filesystem, and API hardening

### P2-01 — Package signing uses a shared HMAC secret

[`hyperc_package.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/hyperc_package.py#L35-L115) supports HMAC signing, which is suitable for a closed shared-secret deployment but not public package authenticity. There is no package manifest loader or command that verifies a package before installation, and no key ID, signature algorithm version, or rotation model.

**Repair:** Use a versioned detached Ed25519 signature for public distribution, include signer key ID and canonical payload digest, and keep HMAC only as an explicitly named local-integrity mode. Add `package verify` and reject unsigned packages when policy requires signatures.

### P2-02 — Atomic-write claims are incomplete

Package manifests and Obsidian artifacts use temporary/direct writes without directory fsync; Obsidian `write_note` and `export_artifact` directly call `write_text` ([`holyfitra_obsidian.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_obsidian.py#L235-L289)). Predictable temporary names and symlink-swap races remain possible in hostile local directories.

**Repair:** Use unique temporary files, flush and fsync the file, atomically replace, fsync the directory, apply restrictive permissions, and re-check containment using directory handles/openat-style operations where the platform permits.

### P2-03 — Obsidian writes lack size and concurrency policy

The adapter bounds note reads but not write content size and has no writer lock or version check. A capable tool caller can write an arbitrarily large note or overwrite a concurrently changed note.

**Repair:** Add maximum write bytes, optimistic concurrency via expected digest, atomic replacement, and audit events containing actor/capability/path/digest. Keep read and write capabilities separate, as the code already intends.

### P2-04 — Memory view inspection can invalidate live aliases

[`holyfitra_memory.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_memory.py#L78-L130) returns fresh `ArenaView` wrappers from `live_views` without incrementing reference counts. Releasing an inspection wrapper marks the underlying block released and can invalidate another live view.

**Repair:** Return immutable inspection records rather than owning views, or create a true alias with a reference increment. Add alias-lifetime tests that exercise `live_views`, `alias`, `clear`, and reuse.

### P2-05 — Native file/path primitives are lexical, not sandboxed

`hf_path_canonicalize` normalizes dot segments but does not resolve symlinks or enforce a root. `hf_write_text` writes a predictable `path.tmp` and renames it. The primitive is therefore not a capability sandbox by itself.

**Repair:** Represent filesystem capabilities as validated root-relative handles, resolve/open with no-follow semantics, and make path canonicalization a presentation utility rather than an authorization decision.

### P2-06 — Native `run` lacks process containment

The compiler’s `run` command invokes an executable with no timeout, process-group cleanup, CPU limit, memory limit, or filesystem/network policy. The test path has a timeout but does not guarantee process-group termination.

**Repair:** Add a runner abstraction with timeout, process group/session isolation, resource limits, captured output caps, and deterministic environment. Make unrestricted execution an explicit unsafe mode.

## P2 findings — native numerical and concurrency correctness

### P2-07 — Hybrid cancellation is not interruptible

[`holyfitra_hybrid.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_hybrid.py#L122-L145) cancels pending futures but then calls `executor.shutdown(wait=True)`. Running branches must finish even after cancellation, so a non-cooperative branch can block the caller indefinitely.

**Repair:** Define cooperative cancellation as part of the callable contract, use bounded waits, surface `cancel_pending` versus `cancelled_running`, and avoid claiming hard cancellation without process isolation.

### P2-08 — Evidence-order APIs are easy to misuse

Both `Evidence.can_promote_to` in [`holyfitra_contracts.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_contracts.py#L80-L102) and `EvidenceType.can_flow_to` in [`hyperc_hyperir.py`](https://github.com/niyasayem-glitch/holy-fitra/blob/master/hyperc_hyperir.py#L77-L93) encode ordering in a direction that is counterintuitive for methods named “promote” or “flow”: a stronger Fact can flow to a weaker category, while a Prediction cannot promote to Fact. The current HyperIR verification path is conservative, but the duplicated APIs invite future inversion bugs.

**Repair:** Rename operations to `can_downgrade_to` or define one monotonic lattice with explicit `can_upgrade_to`, `can_downgrade_to`, and `requires_verifier` tests. Add property-based tests for the lattice.

### P2-09 — Quantization and tensor shape code lack universal maximums

Several NumPy paths rely on `np.prod` and array construction with caller-controlled dimensions. The normal validation rejects malformed shapes but does not establish a global memory budget. A valid but enormous tensor can still exhaust host memory.

**Repair:** Add a shared `ResourceBudget` contract used by tensor construction, quantization, deployment loading, replay buffers, and HyperIR. Check element count and byte count before allocation, with target-specific budgets.

## Self-hosting assessment

State 9 is meaningful but still bounded. It preserves parser child arenas, derives signatures from parser-produced function nodes, and validates the focused imported-call cases `core.inc(41)`, `inc()`, and `inc(true)`. Its current call environment intentionally supports one import per module and a constrained fixture graph. That is a valid milestone, but it is not yet a general module compiler.

The fixed-point roadmap itself correctly defines the remaining bar: Stage-1 must compile the complete compiler without Python; Stage-1 must reproduce Stage-2; semantic/backend products must match over repeated rounds; multi-file imports, visibility, cycles, caches, diagnostics, and packaging must work without Python; and general LLVM lowering must consume verified MIR rather than fixture-specific AST paths. The next architectural step should therefore be **CFG/MIR with a verified intermediate contract**, not more syntax or AI features.

| Self-hosting blocker | Current status | Required proof |
|---|---|---|
| One canonical parser | Not achieved | Differential AST/diagnostic equivalence across Python, Stage-0, and self-hosted parser. |
| General module/import system | State-9 bounded fixture | Multiple imports, qualified names, re-exports, cycles, visibility, and arbitrary module counts. |
| Ownership/effect enforcement | Metadata and runtime conventions | Typed MIR checks plus runtime handle state and negative tests. |
| General CFG/MIR | Not yet implemented | Verified blocks, terminators, dominance/def-use checks, and source spans. |
| General LLVM lowering | Fixture-oriented foundations | MIR-to-LLVM lowering with verifier and differential execution tests. |
| Fixed point | Not claimed | Two or more byte-identical rebuild rounds over the complete compiler source. |
| Android self-host execution | Not available | Buildable APK/AAB, ART load, device execution, and honest thermal/latency evidence. |

## Recommended implementation sequence

### Phase A — P0 boundary hardening

First, create the Android module and make the checked-in build reproducible. In parallel, harden JNI handles with generation-tagged ownership, validate every signed numeric parameter before conversion, check direct-buffer alignment/order/length, and add lifecycle race tests. Extend ragged buffers with lengths and a common validator. Make topology parsing range-aware and exception-safe. Replace raw Stage-0 pointers with typed stateful handles.

### Phase B — One language definition

Freeze a grammar and canonical token/AST schema. Remove substring frontend selection. Reject all unrecognized input. Add public visibility, imports, qualified calls, arrays, strings, and parameter rules to one grammar rather than independently extending multiple parsers. Add differential fixtures for precedence, duplicate names, unreachable code, overflow, nesting, and diagnostics.

### Phase C — Verified CFG/MIR

Lower typed AST/HIR into a MIR with explicit blocks and terminators. Verify that every block has one terminator, every use dominates its definition, all calls resolve to a signature, all returns match function types, and ownership/effects/capabilities are preserved. Only verified MIR may reach LLVM. Run LLVM verification before any link or execution.

### Phase D — Resource and evidence contracts

Introduce one shared resource-budget layer. Apply it to source parsing, AST/MIR, tensors, quantization, checkpoints, deployment archives, telemetry, queues, and process execution. Replace lexical claim verification with structured provenance and signed/source-bound verification. Bind quantization proofs to model/calibration/kernel/device identities.

### Phase E — Fixed-point and Android proof

Require Stage-0 → Stage-1 → Stage-2 rebuilds over the complete compiler source, byte-identical canonical snapshots, identical diagnostics, and at least two stable rounds. Then build the Android module with a pinned NDK, run on an actual arm64 device, and report device facts separately from sandbox x86-64 and AArch64 cross-compilation artifacts.

## High-value test additions

| Test family | Minimum cases |
|---|---|
| JNI lifecycle | Concurrent close/submit/stats; double request destroy; runtime close with queued requests; global-ref allocation failure. |
| JNI buffers | Misaligned slices; non-native order; non-multiple byte capacity; zero-length and oversized buffers; direct-buffer GC/lifetime. |
| Ragged kernel | Null ARM pointers; decreasing/negative/out-of-range offsets; offsets endpoint at each buffer boundary; NaN/Inf inputs; d_model tails; SVE/NEON differential output. |
| Topology | `0-7`, `0-3,6-7`, malformed ranges, missing sysfs, inaccessible directory, affinity failure. |
| Compiler | `pub`, precedence, duplicate parameters, dead invalid code, deep nesting, huge literals, unknown task booleans, identifier collisions, invalid LLVM verification. |
| Frontend differential | Same source through Python native, compatibility frontend, Stage-0, and State-9; compare AST/diagnostics/exit behavior. |
| Artifact security | Tampered cache executable, stale toolchain cache, oversized deployment/checkpoint, malformed scales, duplicate manifest entries, signature/key rotation. |
| Scheduler | Throwing callback, shutdown with queued work, cancellation during running work, incompatible-core starvation, thermal transitions. |
| Evidence/telemetry | NaN/Inf confidence, malformed event fields, forged provenance, lexical-overlap false positives, concurrent log writers, bounded log rotation. |

## Claims that should remain explicitly unavailable

The repository should continue to distinguish the following facts. A passing AArch64 compile is an **artifact-only cross-compilation result**, not physical Android execution. A host fallback to scalar code is not NEON performance. A Markov-model speculative decoder is not evidence of transformer quality. A green fixture bootstrap gate is not a complete fixed point. A local HMAC is not public package authenticity. A lexical overlap score is not factual verification. Keeping these distinctions explicit is a strength of the project and should be enforced in machine-readable reports as well as prose.

## Conclusion

The most powerful enhancement is not another optimization kernel. It is a **single verified contract from source to native execution**: one grammar, one typed AST/HIR, verified CFG/MIR, explicit ownership and resource budgets, authenticated artifacts, checked native handles, and platform-specific execution evidence. Once that chain is trustworthy, the existing tensor, quantization, scheduler, speculative-decoding, TUI, and Obsidian work can attach to it without multiplying incompatible semantics.

Holy Fitra should next fix P0-01 through P0-05 and P1-01 through P1-14, add the adversarial test families above, and only then claim that State 10 has begun. The current repository is a strong foundation, but the audit found enough concrete safety and correctness gaps that adding more surface capability before boundary repair would increase complexity faster than reliability.

## References

[R1]: https://github.com/niyasayem-glitch/holy-fitra "Holy Fitra GitHub repository"

[R2]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_compiler.py "Holy Fitra Python compiler"

[R3]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/hyperc_language_core.py "HyperIR compatibility frontend"

[R4]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_bootstrap.cpp "Holy Fitra Stage-0 seed compiler"

[R5]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/bootstrap/selfhost_state9.hf "State-9 self-hosted compiler fixture"

[R6]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_jni.cpp "Holy Fitra runtime JNI bridge"

[R7]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_ragged_kernel.c "Ragged attention kernels"

[R8]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_ragged_scheduler.cpp "Ragged scheduler"

[R9]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_android_topology.cpp "Android topology detection"

[R10]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark.cpp "Native device benchmark"

[R11]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_ai_system.py "AI evidence and tool runtime"

[R12]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_telemetry.py "Telemetry implementation"

[R13]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/HOLY_FITRA_FIXED_POINT_SELFHOST_ROADMAP.md "Fixed-point self-hosting roadmap"

[E1]: https://developer.android.com/ndk/guides/jni-tips "Android NDK JNI tips"

[E2]: https://docs.oracle.com/javase/8/docs/technotes/guides/jni/spec/functions.html "Oracle JNI Functions specification"

[E3]: https://developer.android.com/reference/tools/gradle-api/8.3/null/com/android/build/api/dsl/ExternalNativeBuild "Android ExternalNativeBuild API"
