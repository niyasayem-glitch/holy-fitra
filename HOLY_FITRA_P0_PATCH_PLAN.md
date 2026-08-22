# Holy Fitra P0 Remediation Patch Plan

**Author:** Manus AI
**Date:** 2026-08-22
**Repository baseline:** State 9, private `master` branch
**Objective:** Eliminate the five P0 blockers identified in the deep repository audit without weakening the no-Python bootstrap, Termux compatibility, sanitizer coverage, or honest Android-evidence policy.

## Implementation status as of 2026-08-22

The remediation work is retained as a **validated partial P0 implementation**, not a P0 closure. The following table records only evidence actually obtained in this checkout.

| Blocker | Current evidence | Status |
|---|---|---|
| P0-01 Android project | `android-lib` now contains a Gradle library descriptor, manifest, Kotlin source set, and CMake graph. The native graph configured and linked three host `.so` targets with a JNI stub. No Gradle wrapper, Android SDK/NDK, APK/AAR build, or device load was available in the sandbox. | **Partial; Android build unverified** |
| P0-02 JNI handles | Runtime and NibbleFlow JNI now use opaque monotonic registry tokens, shared ownership, lifecycle leases, direct-buffer checks, and serialized owner teardown. Strict host syntax checks with a JNI stub passed. No real-JNI/NDK or JVM race test was available. Tokens are not yet generation-tagged slot handles. | **Partial; generation/race evidence open** |
| P0-03 ragged ABI | Q/K/V/output capacities and offset count are present; common validation runs at kernel and scheduler boundaries; adaptive chunk arithmetic, exact offset subviews, exception completion, and queued shutdown drain are covered by host tests and ASAN/UBSan. Finite-input policy and ARM execution remain open. | **Substantially hardened; not closed** |
| P0-04 Stage-0 ownership | A pthread-protected pointer/kind live-resource registry makes managed releases idempotent and rejects stale operations; bootstrap, ASAN/UBSan, and State 1–9 gates pass. This is explicitly Bridge 1, not generation-safe ABI-v2 ownership lowering. | **Bridge partial; ABI-v2 open** |
| P0-05 HyperIR/frontend routing | Explicit frontend selection replaced source-substring routing; bounded source reads and fail-closed diagnostics reject garbage, trailing text, duplicates, and incomplete declarations. The compatibility frontend is still line-oriented and is not yet the canonical parser shared with Stage-0/State-9. | **Partial; parser unification open** |

After the remediation edits, the Python suite reports **155 passing tests**. The bootstrap no-Python path passes through State 9, Termux-compatible host validation passes, native ASAN/UBSan regressions pass, and AArch64 emission remains an artifact-only result. These results do not satisfy the Android Gradle/device or full generation-checked JNI completion definitions below.

## 1. Scope and P0 blockers

The five blockers are cross-cutting. They must be fixed as a coordinated safety release rather than as isolated one-line changes.

| ID | Blocker | Primary risk | Definition of fixed |
|---|---|---|---|
| P0-01 | Android integration is not a buildable Android project | No reproducible APK/AAB or JNI device validation | A clean checkout can sync, compile, package, load, and smoke-test the arm64 Android library. |
| P0-02 | JNI runtime/request handles are raw unsynchronized pointers | Use-after-free, double-destroy, stale-handle dereference, lifecycle races | Handles are opaque, generation-checked, thread-safe, idempotently destroyed, and never expose native addresses to Kotlin/Java. |
| P0-03 | Ragged attention has no buffer lengths and ARM paths lack common validation | Out-of-bounds reads/writes, ARM-only crashes, invalid numerical state | Every buffer has a length, one validator runs before every kernel, all ISA paths share safety checks, and scheduler requests terminate on all outcomes. |
| P0-04 | Stage-0 runtime ownership is not enforced | Double-free, use-after-free, wrong-kind resource use | Owned resources have explicit state/lifetime enforcement, invalid release is rejected or safely idempotent, and compiler lowering has one destruction path. |
| P0-05 | HyperIR compatibility frontend silently accepts malformed source | Invalid programs become valid plans; downstream evidence is untrustworthy | A complete parser rejects every unknown token/construct, consumes the complete input, and frontend selection is explicit rather than heuristic. |

## 2. Non-negotiable invariants

The patch series should begin by documenting and testing these invariants. Every later implementation must preserve them.

| Invariant | Required behavior | Failure behavior |
|---|---|---|
| **Fail closed** | Invalid source, ABI values, dimensions, buffers, manifests, and handles never enter execution | Return a typed error or structured diagnostic; never silently continue. |
| **No raw FFI ownership** | Java/Kotlin and Holy Fitra code receive opaque handles, not native addresses | Reject stale, wrong-kind, forged, or already-destroyed handles. |
| **Length-before-pointer-arithmetic** | Native code proves all sizes and products before deriving element addresses | Return `INVALID_ARGUMENT` or `RESOURCE_LIMIT`; do not dereference. |
| **One terminal request outcome** | Every submitted task decrements its group exactly once | `Completed`, `Cancelled`, `DeadlineMissed`, `Failed`, or `Stopped`; never an indefinite wait. |
| **Verified lowering** | LLVM emission is preceded by AST/HIR/MIR verification and LLVM IR verification | Do not link or execute unverified IR. |
| **Single language definition** | Frontends share tokens, grammar, AST, diagnostics, and feature declarations | Ambiguous or unsupported source is rejected, not routed by substring. |
| **Bounded resources** | Source, tensors, archives, queues, logs, buffers, and subprocesses have explicit limits | Deterministic error before allocation or execution exceeds a budget. |
| **Honest evidence** | Host fallback, AArch64 cross-build, and physical Android execution are separate states | Reports must not label artifacts or fallbacks as device measurements. |

## 3. Recommended patch topology

Use small commits with independently testable boundaries. Do not mix the Android project scaffold with semantic changes, because a packaging failure should be easy to distinguish from a runtime failure.

| Commit | Scope | Depends on | Retention gate |
|---:|---|---|---|
| 1 | Add shared error/status codes, ABI version, resource-limit constants, and test utilities | None | Existing tests remain green. |
| 2 | Add the real Android library and benchmark module layout | 1 | Clean Gradle sync and native compilation on a pinned toolchain. |
| 3 | Replace JNI pointer handles with opaque generation-checked handles | 1 | Lifecycle race tests and ASAN/UBSan pass. |
| 4 | Add checked direct-buffer descriptors and JNI boundary validation | 1, 3 | Malformed-buffer tests reject without crash. |
| 5 | Extend ragged ABI with lengths and implement common preflight validation | 1, 4 | Scalar/NEON/SVE differential and malformed-buffer tests pass. |
| 6 | Make scheduler completion and shutdown failure-safe | 1, 5 | Throwing callback, cancellation, and shutdown tests terminate. |
| 7 | Migrate Stage-0 resource builtins to checked ownership handles | 1 | Bootstrap fixtures and ownership-negative tests pass. |
| 8 | Replace HyperIR line scanning with a fail-closed parser | 1 | Malformed-source corpus rejects deterministically. |
| 9 | Remove source-substring frontend selection and add differential fixtures | 2, 7, 8 | Python/Stage-0/State-9 diagnostics and AST expectations agree where supported. |
| 10 | Integrate all gates, update documentation, and publish the safety release | 2–9 | Full regression, sanitizer, Termux, Android build, and honest artifact report pass. |

Each commit should be built from a clean checkout in CI. Temporary probes belong under tests or are deleted before publication; no generated binaries, APKs, cache artifacts, or device logs should be committed unless explicitly designated as release fixtures.

## 4. P0-01 — Make Android integration a real reproducible project

### 4.1 Target layout

Choose one canonical Android library module and make every existing Kotlin/native fragment part of that module. The proposed layout is:

```text
android/
  settings.gradle.kts
  build.gradle.kts
  gradle.properties
  holyfitra-runtime/
    build.gradle.kts
    proguard-rules.pro
    src/main/AndroidManifest.xml
    src/main/java/com/holyfitra/runtime/HolyFitraRuntime.kt
    src/main/java/com/holyfitra/runtime/NibbleFlow.kt
    src/main/cpp/CMakeLists.txt
    src/main/cpp/holy_fitra_jni.cpp
    src/main/cpp/nibbleflow_jni.cpp
    src/main/cpp/holy_fitra_runtime.cpp
    src/main/cpp/holy_fitra_dispatch.cpp
    src/main/cpp/nibbleflow_android.cpp
    src/main/cpp/nibbleflow_kernel.c
    src/main/cpp/holy_fitra_ragged_kernel.c
    src/main/cpp/include/...
  holyfitra-benchmark/
    build.gradle.kts
    src/main/AndroidManifest.xml
    src/main/java/com/holyfitra/benchmark/HolyFitraBenchmark.kt
    src/main/cpp/CMakeLists.txt
    src/main/cpp/holy_fitra_device_benchmark.cpp
    src/main/cpp/holy_fitra_device_benchmark_jni.cpp
```

The exact directory name may differ, but the principle is mandatory: every `externalNativeBuild.cmake.path` must resolve relative to its own module build file, as required by the Android Gradle API [3]. The current loose root Gradle fragments should either become module build files or be removed to prevent two competing packaging stories.

### 4.2 Build configuration

Pin the Android Gradle Plugin, Gradle wrapper, Kotlin plugin, compile SDK, build tools, and NDK revision. Use `minSdk 26` only if all native APIs and ABI assumptions support it. Restrict release ABIs to `arm64-v8a` initially, but make the unsupported-ABI behavior explicit rather than silently selecting a scalar host fallback.

The runtime module should export one library name and one ABI version. The NibbleFlow and benchmark libraries should be separate only if they have independent lifecycle and versioning requirements. If they remain separate, add explicit packaging tests proving that their `.so` names match the `System.loadLibrary` calls in Kotlin.

Add a minimal manifest with no unnecessary permissions. Native code must not assume filesystem access, thermal sysfs availability, or unrestricted threads. The Android module should expose a small smoke-test activity or instrumented test only in the test application, not in the library manifest.

### 4.3 Required build/test tasks

| Task | Expected result |
|---|---|
| `./gradlew :holyfitra-runtime:assembleDebug` | Produces an arm64 debug AAR and native `.so`. |
| `./gradlew :holyfitra-runtime:assembleRelease` | Produces a release AAR with symbols policy documented. |
| `./gradlew :holyfitra-benchmark:assembleDebug` | Benchmark module compiles independently. |
| `./gradlew lint test` | Kotlin/API checks pass. |
| Instrumented `abiVersion` test | Library loads and returns the expected ABI version. |
| Instrumented lifecycle test | Create/submit/wait/cancel/destroy/close works repeatedly. |
| Clean-checkout build | No root-local files, Python packages, or sandbox artifacts are required. |

The root CMake/Clang build remains useful for host tests, but its outputs must be labeled host artifacts. Android build success must be reported separately from AArch64 object emission.

## 5. P0-02 — Replace raw JNI pointers with opaque, thread-safe handles

### 5.1 Handle model

Introduce a native handle registry shared by the runtime and JNI boundary. Java/Kotlin receives a `jlong` token, never a cast pointer. A token should contain a nonzero slot index, generation, and kind. One practical 64-bit layout is 32 bits for slot, 24 bits for generation, and 8 bits for kind; the exact layout is internal but must be documented and tested.

The registry should contain:

```cpp
struct HandleEntry {
    uint32_t generation;
    HandleKind kind;
    HandleState state;              // Live, Closing, Destroyed
    std::shared_ptr<void> object;
    std::mutex mutex;
    uint32_t in_flight = 0;
};
```

The global registry mutex protects slot lookup and generation changes. The entry mutex protects object state and in-flight operations. Handle lookup must validate token nonzero, slot bounds, kind, generation, and state before returning a temporary strong reference. A destroyed slot increments generation before reuse, making stale tokens fail deterministically.

Do not return an internal `shared_ptr` object directly through JNI. The registry owns the lifetime while an operation holds a strong reference. Every operation increments `in_flight` after successful lookup and decrements it through an RAII guard.

### 5.2 Runtime lifecycle

`nativeCreate` allocates a runtime entry and returns a token. If topology detection, scheduler creation, model setup, or `NewGlobalRef` fails, it must clean up all partially initialized resources and return a Java exception or a zero token with a pending typed error.

`nativeClose` transitions the runtime from `Live` to `Closing` atomically. It rejects new submissions, cancels outstanding requests, waits for in-flight operations, destroys the scheduler, deletes global references, and finally marks the entry `Destroyed`. Repeated close is a no-op or returns `ALREADY_CLOSED`; it must not dereference the old object.

Requests hold a strong reference to the runtime entry until they reach a terminal state. `nativeDestroyRequest` transitions the request exactly once and either waits for completion or returns a documented asynchronous-destroy result. A request cannot outlive the runtime without an explicit detached ownership mode.

Native worker threads must not retain or share a `JNIEnv*`. If callbacks into Java are added later, store a `JavaVM*`, attach/detach each worker correctly, and use global references for retained classes/objects. Android’s JNI guidance explicitly states that `JNIEnv` is thread-local and that retained objects require global references [1] [2]. The preferred design here is no Java callback from native workers.

### 5.3 JNI error discipline

Add a single boundary helper:

```cpp
JniResult<T> with_native_boundary(JNIEnv* env, ...);
```

It must catch native exceptions, convert them to stable Java exception classes, check for pending JNI exceptions after calls that can throw, and never allow a C++ exception across the JNI boundary. Use a stable error taxonomy such as `INVALID_ARGUMENT`, `STALE_HANDLE`, `WRONG_HANDLE_KIND`, `CLOSED`, `RESOURCE_LIMIT`, `TIMEOUT`, `CANCELLED`, and `INTERNAL`.

Kotlin should use an `AtomicLong`/`AtomicBoolean` state and synchronize close against submission at the wrapper level for good diagnostics, but native state remains authoritative. Every public Kotlin method must reject use after close before entering JNI and still handle a native `CLOSED` response due to races.

### 5.4 Direct-buffer descriptors

Create a single native descriptor for every direct buffer:

```cpp
struct DirectBufferView {
    void* address;
    uint64_t bytes;
    uint64_t elements;
    uint32_t element_size;
};
```

Validation must check the Java object is non-null, direct, addressable, capacity is nonnegative, capacity is divisible by the element size, address alignment is sufficient, required bytes fit within capacity, and any required native byte-order contract is satisfied. Check the result of every `NewGlobalRef`; null means fail with `OUT_OF_MEMORY` and no partially registered request.

Do not infer output dimensions only from model metadata if the output buffer’s actual capacity can be queried. Pass explicit expected byte counts from Kotlin/native model descriptors and reject mismatches before starting work.

## 6. P0-03 — Make ragged attention memory-safe and scheduler-complete

### 6.1 ABI extension

Version the ragged ABI and add explicit extents. Prefer byte lengths or 64-bit element counts over implicit assumptions:

```c
typedef struct hf_ragged_attention_batch_v2 {
    const float *q;
    uint64_t q_elements;
    const float *k;
    uint64_t k_elements;
    const float *v;
    uint64_t v_elements;
    float *output;
    uint64_t output_elements;
    const int32_t *offsets;
    uint64_t offsets_count;
    int32_t sequence_count;
    int32_t d_model;
} hf_ragged_attention_batch_v2;
```

Keep a versioned compatibility adapter only if existing callers must survive. The adapter must require caller-provided lengths; it must not guess them. Old pointer-only callers should be rejected as unsupported rather than routed into an unsafe legacy implementation.

### 6.2 Shared preflight validator

Implement `hf_validate_ragged_batch_v2` once and call it from scalar, NEON, SVE, and scheduler entry points. The validator must:

1. Reject null batch or required pointers.
2. Reject nonpositive `sequence_count`/`d_model` and values above configured maxima.
3. Check `offsets_count >= sequence_count + 1` without integer overflow.
4. Check every offset is nonnegative, monotonic according to the empty-sequence policy, and no greater than total token capacity.
5. Check the final offset fits within q/k/v/output extents after checked multiplication by `d_model`.
6. Check all pointer arithmetic products and additions in 64-bit arithmetic before conversion to `size_t`.
7. Apply a finite-input policy. If NaN/Inf is not supported, reject it before computation; otherwise define propagation semantics and test them.
8. Check output extent separately because output may be smaller than q/k/v.

The kernel must perform no pointer arithmetic before validation succeeds. All ISA entry points must call the same validator; the current ARM-only null-check asymmetry must disappear.

### 6.3 Numerical stability and ISA consistency

Fix SVE normalization so a zero, NaN, or non-finite normalizer cannot cause an unconditional divide. Use the same finite/empty behavior in scalar, NEON, and SVE paths. Add a reference implementation and compare each ISA path within a documented tolerance across d_model tails, sequence lengths of 1 and large values, and mixed ragged offsets.

Report the executed ISA separately from the compiled function name. On x86, the fallback must report `scalar_fallback`, not `neon`. Hardware feature detection must use architecture/runtime feature checks and must never infer NEON from the existence of a topology list.

### 6.4 Scheduler integration

The scheduler must validate the complete batch before creating tasks. Each chunk should carry an offsets subview whose count is exactly `(last - first) + 1`, while q/k/v/output extents remain the full validated extents and the global token coordinate convention is documented.

Wrap each task body with a completion guard that calls `finish_once` on every path, including exceptions. `finish_once` should record the first failure, preserve cancellation/deadline state, decrement `remaining` exactly once, and notify waiters. The scheduler must catch all exceptions at the task boundary and convert them to `Failed`.

Shutdown must transition to `Stopping`, reject new work, drain queued tasks, invoke their cancellation/failure callbacks, wait for running workers, and transition to `Stopped`. A request submitted before shutdown must reach a terminal result; `wait(0)` must never hang indefinitely because a queue entry was discarded.

Add checked arithmetic to adaptive chunking and fixed chunk calculation. Clamp maximum sequences per task and total estimated work. Treat overflow as `RESOURCE_LIMIT`, not as a wrapped estimate.

## 7. P0-04 — Enforce Stage-0 ownership and safe resource lifetimes

### 7.1 Ownership design decision

Do not continue expanding raw `ptr`-typed owned resources. Introduce an ABI-v2 distinction between borrowed views and owned handles. The preferred end state is generation-checked integer handles for dynamic arrays, files, buffers, and owned strings, with `string_view`/borrowed pointer values used only within a statically bounded call.

If an immediate integer-handle migration would block State-10 CFG/MIR work, land a staged bridge:

| Stage | Change | Safety level |
|---|---|---|
| Bridge 1 | Add resource headers, kind, state, generation, and a registry; released shells remain as tombstones so stale references cannot dereference freed payloads | Removes ordinary double-free/UAF on managed resources, but retains pointer ABI temporarily. |
| Bridge 2 | Add compiler types for `owned_string`, `string_view`, `array_handle`, `file_handle`, and `buffer_handle` | Makes ownership visible to semantic analysis. |
| ABI v2 | Lower owned handles to generation-checked `i64` tokens and borrowed views to explicit non-owning values | Removes raw native addresses from generated user-facing resource values. |

The final release gate should require ABI v2 for new code. A pointer-ABI compatibility shim may exist only behind an unsafe, explicitly named feature and must not be used by the bootstrap compiler.

### 7.2 Runtime state machine

Every resource must carry `kind`, `generation`, `state`, `size`, and an ownership/refcount policy. Operations validate kind and state before use. A normal release transitions `Live → Released` exactly once. Releasing a released handle returns `ALREADY_RELEASED` or succeeds idempotently according to the API contract; it must never call `free` twice.

For token handles, the registry removes the live payload and increments generation before slot reuse. For the temporary pointer bridge, retain a bounded tombstone table and return `STALE_HANDLE` for released resources. Wrong-kind use must be rejected before accessing resource-specific fields.

File operations must define whether `read_all` borrows the file or consumes it. Buffer `finish` must define whether the buffer remains usable. String slices must define whether the result is owned. These rules should be encoded in builtin signatures and in the MIR ownership checker, not left in comments.

### 7.3 Compiler lowering

Add ownership facts to typed HIR/MIR: `Owned`, `Borrowed`, `Moved`, `Released`, and `Invalid`. Every owning builtin consumes or returns a fact according to its signature. The verifier must reject use after move, release of a borrowed value, double release, and paths where an owned value is neither transferred nor released unless the language explicitly permits process-lifetime ownership.

Lower destruction through one cleanup mechanism per function, preferably a synthesized exit block or cleanup ladder in MIR. This prevents early returns and branch exits from producing multiple frees or leaks. Do not implement cleanup by textual emitter heuristics.

### 7.4 Tests

Add native and generated-program tests for successful create/use/release, double release, use after release, wrong-kind handle, null/zero handle, release on every return path, branch-only allocation, loop allocation, and allocation failure. Run these under ASAN, UBSan, and a leak detector. Add a deterministic resource-limit test proving the runtime rejects rather than overcommits memory.

## 8. P0-05 — Replace HyperIR line scanning with a fail-closed parser

### 8.1 Parser architecture

Replace the recognized-line loop in `hyperc_language_core.py` with the same token/span model used by the canonical Holy Fitra grammar. The parser must tokenize the entire input, preserve line/column spans, parse a module header, capability declarations, function signatures, budgets, tensor declarations, operations, and closing delimiters, and require EOF after the final construct.

Every token must be consumed by a grammar production. Unknown lines, malformed bodies, duplicate declarations, missing delimiters, trailing junk, invalid capability scopes, and unsupported operations must produce structured diagnostics. A source file containing no functions must be invalid unless the language explicitly defines declaration-only modules.

The parser should build an intermediate representation first and only mutate `HyperModule` after the complete parse succeeds or after diagnostics are deliberately accumulated. This avoids partially valid modules whose plans contain only the subset that happened to parse before an error.

### 8.2 Explicit frontend selection

Delete the substring heuristic from `check_file` and `holyfitra_benchmark.py`. Use one of these explicit mechanisms:

1. A project manifest field such as `frontend = "native"` or `frontend = "hyperir"`.
2. A module header such as `language holyfitra.native` or `language holyfitra.hyperir`.
3. A command-line override that is required when the manifest/header is absent.

If legacy auto-detection must remain temporarily, it must tokenize and detect a unique grammar marker, emit an ambiguity warning, and never select HyperIR merely because `Tensor`, `capability`, or `budget` appears in a comment, string, or identifier. The migration should make explicit configuration the default before removing compatibility mode.

### 8.3 Semantic validation

After parsing, validate module structure: unique module name, unique function names, unique parameters and locals, valid tensor dimensions, valid devices/layouts, capability scope containment, budget units, operation input/output types, and complete function bodies. Do not turn exceptions into a soft result for benchmark or compilation success.

The compatibility frontend should return `valid=false` and a nonzero CLI exit status for any error. Benchmark commands should distinguish `not_run`, `failed_validation`, and `completed`; an error field must not be treated as a successful measurement.

### 8.4 Differential compatibility tests

Create a shared fixture corpus with valid and invalid examples. For supported constructs, compare Python native, HyperIR, Stage-0, and State-9 diagnostics and normalized AST/HIR snapshots. Where a frontend intentionally does not support a feature, it must emit a stable `UNSUPPORTED_FEATURE` diagnostic rather than silently accepting or routing it elsewhere.

Minimum malformed corpus:

| Fixture | Expected result |
|---|---|
| Empty source | Structured error. |
| Garbage text | Structured error; no functions emitted. |
| Valid function plus trailing garbage | Structured error at trailing token. |
| Unterminated capability/function/body | Structured error with opening-span note. |
| Duplicate function/parameter/local | Stable duplicate-declaration diagnostic. |
| Invalid Tensor shape/device/layout | Structured type/shape diagnostic. |
| Unknown operation | Unsupported-operation diagnostic. |
| Comment/string containing `Tensor` | Native frontend remains selected. |
| `pub fn` in a frontend without visibility support | Explicit unsupported-feature error. |

## 9. Cross-blocker integration details

### 9.1 ABI versioning

Add a single ABI version constant to the native headers, generated Kotlin constants, package/deployment metadata, and benchmark JSON. Increment it for the handle and ragged-buffer changes. `nativeAbiVersion()` must be callable without a runtime handle and must report the exact major/minor version. Reject mismatched clients before creating a runtime.

### 9.2 Error propagation

Use one error representation at each boundary:

| Boundary | Representation |
|---|---|
| Holy Fitra runtime | `HF_Status` enum plus optional bounded message. |
| C++ scheduler | `TaskResult` plus internal error code. |
| JNI | Java exception class plus stable error code/message. |
| Kotlin | sealed `HolyFitraError` or checked result wrapper. |
| Python frontend | `Diagnostic` records and nonzero CLI status. |
| Benchmark JSON | `completed`, `status`, `errors[]`, and finite metrics only. |

Do not expose raw `str(error)` or unbounded native exception messages across an API without a length cap.

### 9.3 Documentation updates

Update the Android integration document to show the actual module paths and Gradle commands. Update the fixed-point roadmap to state that P0 hardening is a prerequisite for State 10. Update runtime/API docs with ownership, handle, buffer, cancellation, and ABI rules. Keep the explicit distinction between AArch64 cross-compilation and physical Android execution.

## 10. Validation matrix and release gates

The P0 patch is retained only if all rows pass from a clean checkout.

| Area | Required validation |
|---|---|
| Existing regression | `python3 -m unittest`; `python3 -m compileall -q .`; shell syntax checks. |
| HyperIR fail-closed | Malformed corpus rejects; garbage never returns `valid=true`; explicit frontend routing tests pass. |
| Native compiler | Duplicate parameters reject; LLVM verifier runs before link; identifier mangling tests pass. |
| Stage-0 ownership | Bootstrap State 1–9 fixtures pass; ownership negative tests pass under ASAN/UBSan/leak detection. |
| JNI handles | Multithreaded close/submit/stats/cancel/destroy stress; stale/wrong-kind/double-destroy tests; no sanitizer report. |
| JNI buffers | Misaligned, sliced, non-native-order, too-small, zero, oversized, and null buffers reject without crash. |
| Ragged kernels | Length/offset fuzz corpus; scalar/NEON/SVE differential tests; ARM-target compilation; no pointer arithmetic before validation. |
| Scheduler | Throwing task, queue shutdown, cancellation, deadline, backpressure, and wait termination tests. |
| Android packaging | Clean Gradle sync, debug/release AAR, native `.so` load, ABI/version test, instrumented lifecycle smoke test. |
| Termux | `bash termux-build.sh --host-tests`; no `sudo`; no Python dependency in bootstrap path. |
| Cross-compilation | AArch64 objects are nonempty and verified, but reported as artifacts only. |
| Reproducibility | Two clean builds have identical normalized metadata and deterministic compiler artifacts where promised. |
| Resource limits | Oversized source, tensor, model, ragged batch, queue, archive, and telemetry inputs fail before allocation/execution. |

For fuzzing, begin with libFuzzer or a bounded Python/native corpus for parsers and validators. Run ThreadSanitizer on the scheduler/handle registry where the platform supports it. ASAN/UBSan alone will not prove race freedom.

## 11. Rollout and rollback strategy

Land each patch behind a feature flag only when an ABI migration could disrupt existing callers. The safe sequence is to add ABI-v2 entry points beside v1, migrate Kotlin and bootstrap-generated calls, run dual-path differential tests, then remove or quarantine v1. Never silently reinterpret v1 pointer values as v2 integer handles.

If the Android project scaffold fails, revert only the packaging commit; host compiler/runtime work remains testable. If handle or ragged ABI changes fail sanitizer tests, keep the new status/error types but revert the ABI switch and continue under a disabled experimental flag. If the HyperIR parser changes compatibility behavior, preserve the old parser only as an explicitly named legacy mode with fail-closed errors; do not restore heuristic routing.

A release candidate must include a generated compatibility report listing ABI version, compiler version, native library hashes, supported ABIs, enabled kernels, and test-gate results. The report must contain no claim of physical Android execution unless an actual device test was performed.

## 12. Completion definition

The five P0 blockers are fixed only when all of the following are true:

1. A clean checkout builds the Android runtime and benchmark modules through Gradle, and Kotlin loads the expected native libraries.
2. No public JNI method accepts or returns a raw native address; stale and concurrent handle operations fail deterministically.
3. Every ragged buffer carries an extent, all kernel paths share validation, and malformed inputs cannot reach pointer arithmetic.
4. Every Stage-0 owned resource has an enforced lifetime and a single cleanup path in generated programs.
5. HyperIR parses the complete source and rejects all unknown constructs; frontend selection no longer uses substring heuristics.
6. The existing 153-test Python suite and all bootstrap/Termux gates remain green.
7. New adversarial, sanitizer, race, Android build, and cross-frontend differential tests pass.
8. Reports distinguish host execution, AArch64 artifact generation, and physical Android measurements.

Only after these conditions are met should State 10 proceed with CFG/MIR construction. The most important architectural outcome is a single verified chain from source grammar to typed HIR/MIR to checked native ABI; additional AI features should attach to that chain rather than create new independent safety contracts.

## References

[1]: https://developer.android.com/ndk/guides/jni-tips "Android NDK JNI tips"

[2]: https://docs.oracle.com/javase/8/docs/technotes/guides/jni/spec/functions.html "Oracle JNI Functions specification"

[3]: https://developer.android.com/reference/tools/gradle-api/8.3/null/com/android/build/api/dsl/ExternalNativeBuild "Android ExternalNativeBuild API"

[4]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/HOLY_FITRA_DEEP_AUDIT_2026-08-22.md "Holy Fitra deep audit"

[5]: https://github.com/niyasayem-glitch/holy-fitra/blob/master/HOLY_FITRA_FIXED_POINT_SELFHOST_ROADMAP.md "Holy Fitra fixed-point self-hosting roadmap"
