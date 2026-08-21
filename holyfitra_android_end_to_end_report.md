# Holy Fitra End-to-End Android JNI/NDK Integration Report

**Author:** Manus AI  
**Native library:** `libholyfitra_runtime.so`  
**Target:** Android `arm64-v8a`  
**Status:** Host-integrated and JNI-link validated; physical Android packaging and device execution remain required.

## Executive Summary

Holy Fitra now has an end-to-end native integration path that combines the NibbleFlow int4 kernel, model validation, Android-style heterogeneous dispatch, asynchronous request handles, cancellation, timeout and deadline semantics, thermal control, JNI direct-buffer ownership, Kotlin APIs, and NDK/CMake packaging.

The central native object is `hf_holyfitra_runtime`. It owns a validated NibbleFlow model view and a scheduler. Applications submit asynchronous matvec requests through JNI. Each request retains global references to its direct input and output buffers, carries core preference, priority, and deadline metadata, and can be waited on, cancelled, or destroyed safely. Runtime shutdown destroys the scheduler before releasing model buffer references, preventing workers from touching freed native memory.

The host validation compiled and executed the integrated runtime test, syntax-checked and linked the JNI bridge with host JNI headers, and produced an 88 KB shared native library containing the integrated components.

## Integrated Components

| Component | Responsibility |
|---|---|
| `nibbleflow_kernel.c` | Portable and AArch64 fused int4 matvec |
| `nibbleflow_android.h/.cpp` | Model layout, ABI, capacity, and status validation |
| `holy_fitra_dispatch.h/.cpp` | Bounded heterogeneous work-stealing scheduler |
| `holy_fitra_android_topology.h/.cpp` | Android sysfs capacity/frequency topology detection |
| `holy_fitra_runtime.h/.cpp` | C runtime handle, async requests, cancellation, waits, stats |
| `holy_fitra_jni.cpp` | Java/Kotlin bridge and global-buffer lifecycle |
| `HolyFitraRuntime.kt` | Typed Kotlin API and resource-safe wrappers |
| `CMakeLists.txt` | NDK shared-library build graph |
| `holyfitra_android_build.gradle.kts` | Android arm64-v8a Gradle configuration |

## Runtime Lifecycle

```text
Kotlin direct model buffers
  → JNI validates direct addresses and byte capacities
  → NibbleFlow model layout validation
  → topology detection and scheduler creation
  → native handle published
  → async matvec request submitted
  → scheduler chooses eligible worker
  → NibbleFlow kernel executes
  → request completion status published
  → Kotlin waits, cancels, or closes request
  → runtime close drains scheduler and releases global refs
```

The model buffers are not copied by the native handle. JNI creates global references to the original direct buffers, so their Java objects remain alive while native pointers are in use. Input and output buffers receive the same per-request lifetime protection until the request is destroyed.

## Native Request API

The key C function is:

```c
hf_status hf_runtime_submit_matvec(
    hf_holyfitra_runtime *runtime,
    const float *input,
    size_t input_count,
    float *output,
    size_t output_count,
    int core_class,
    int priority,
    uint64_t deadline_ns,
    hf_runtime_request **request
);
```

The request is asynchronous. `hf_runtime_wait(request, timeout_ms)` returns `HF_TIMEOUT` when a bounded wait expires and returns `HF_OK`, `HF_CANCELLED`, or `HF_DEADLINE_MISSED` when execution reaches a terminal state. `hf_runtime_request_destroy` cancels, waits indefinitely, and frees the request only after its worker callback has completed.

The scheduler has explicit cancellation and deadline completion hooks. This prevents a skipped task from leaving a request permanently unfinished, which is a critical lifecycle invariant for JNI callers.

## JNI Buffer Contract

The bridge accepts direct `ByteBuffer` instances for all model and activation data. This is deliberate: `GetDirectBufferCapacity` provides an unambiguous byte capacity, and the native ABI can derive float counts by dividing by `sizeof(float)`.

| Buffer | Native interpretation |
|---|---|
| Packed weights | `uint8_t` byte array |
| Scales | `float32` byte array |
| Bias | Optional `float32` byte array |
| Input | `float32` byte array |
| Output | Writable `float32` byte array |

The Kotlin wrapper provides `directBytes()` and `directFloats()` helpers. Applications should allocate these buffers once and reuse them across decode steps. They must not mutate or reuse input/output memory until the associated request has completed or been destroyed.

## Kotlin Usage

```kotlin
val runtime = HolyFitraRuntime.create(
    packed = packedWeights,
    scales = scales,
    bias = bias,
    inDim = 4096,
    outDim = 4096,
    groupSize = 32,
    queueCapacity = 256,
    pinThreads = true,
)

runtime.use {
    val request = it.submitMatvec(
        input = input,
        output = output,
        coreClass = HolyFitraRuntime.CoreClass.BIG_PREFERRED,
        priority = HolyFitraRuntime.Priority.INTERACTIVE,
        deadlineNs = 0L,
    )
    request.use { pending ->
        check(pending.waitFor(1000) == HolyFitraRuntime.Status.OK)
    }
}
```

`HolyFitraRuntime` also exposes `setThermal()` and `stats()`. A platform adapter should call `setThermal()` only after debouncing Android thermal signals, and should use stats to report queue depth, completions, cancellations, deadlines, rejections, steals, NEON availability, and ABI version.

## Build Integration

The NDK CMake target packages the complete native graph:

```cmake
add_library(holyfitra_runtime SHARED
    nibbleflow_kernel.c
    nibbleflow_android.cpp
    holy_fitra_dispatch.cpp
    holy_fitra_android_topology.cpp
    holy_fitra_runtime.cpp
    holy_fitra_jni.cpp
)
```

The Gradle module selects `arm64-v8a`, uses external CMake, pins CMake version `3.22.1`, and uses static libc++ packaging. The exact NDK version should be pinned by the application’s build configuration for reproducibility.

## Validation Evidence

| Validation | Result |
|---|---|
| Native runtime integration smoke test | Passed |
| NibbleFlow output verification | Passed |
| Scheduler topology integration | Passed in prior runtime validation |
| Runtime ABI and status path | Passed |
| JNI source compile with host JNI headers | Passed |
| Integrated host shared library link | Passed |
| Integrated native sanitizer test | Passed |
| Host shared-library artifact | 88 KB |

The test model uses zero-packed int4 weights, so the expected output is exactly zero. It verifies runtime creation, asynchronous submission, completion wait, output correctness, thermal state update, and stats ABI.

## Android Device Validation Still Required

The sandbox cannot claim a complete Android deployment. A real Android build/device campaign must verify:

1. NDK/CMake compilation with the pinned toolchain.
2. `arm64-v8a` APK/AAB packaging.
3. `System.loadLibrary("holyfitra_runtime")` on ART.
4. Direct buffer addresses and capacities on Android.
5. JNI global-reference cleanup across configuration and activity lifecycles.
6. Big/little topology detection and CPU affinity behavior.
7. NibbleFlow numerical differential tests on device.
8. Request cancellation and runtime close under concurrent load.
9. p50, p95, and p99 latency under sustained thermal load.
10. Battery, memory, thermal, and tokens-per-joule measurements.
11. Int4 proof failure and int8/f16 fallback behavior.

## Production Hardening Priorities

The current integrated runtime is a strong prototype, but production work remains. The scheduler’s deques are mutex-protected and should be replaced only after an audited bounded lock-free implementation is available. The model asset format needs a versioned binary header and signed manifest. JNI should eventually expose structured native error objects rather than only status IDs and exception strings. The runtime also needs a durable request ID, queue-age metrics, secure model-page mapping, and an Android thermal adapter with hysteresis.

The most important safety rule is already present: runtime shutdown waits for worker completion before releasing model references. The next rule should be proof binding: the selected NibbleFlow kernel, quantization calibration, model hash, and device profile must be verified before the runtime enters `READY` state.

## References

[1]: https://developer.android.com/ndk/guides/cmake "CMake in Android Studio"
[2]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[3]: https://docs.oracle.com/en/java/javase/17/docs/specs/jni/functions.html "Java Native Interface Functions"
[4]: https://developer.android.com/reference/android/os/PowerManager "Android PowerManager and thermal status APIs"
[5]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
