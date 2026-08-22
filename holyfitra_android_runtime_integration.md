# Holy Fitra End-to-End Android JNI/NDK Integration

**Runtime:** Holy Fitra  
**Native library:** `libholyfitra_runtime.so`  
**Target ABI:** `arm64-v8a`  
**Status:** Host JNI syntax/link validation and native integration tests passed; physical Android packaging and device execution still require an Android NDK build and ARM64 device.

## 1. What Is Integrated

The end-to-end runtime now connects five layers:

```text
Kotlin application
    ↓
HolyFitraRuntime.kt
    ↓ JNI direct ByteBuffers and request handles
holy_fitra_jni.cpp
    ↓
holy_fitra_runtime.cpp
    ↓
Holy Fitra heterogeneous scheduler
    ↓
NibbleFlow validation and fused int4 kernel
```

The application can create one native runtime handle, submit asynchronous matvec requests, wait with a timeout, cancel requests, update thermal state, inspect scheduler statistics, and close the runtime safely.

## 2. Recommended Android Source Layout

```text
app/src/main/cpp/
    CMakeLists.txt
    nibbleflow_kernel.c
    nibbleflow_android.h
    nibbleflow_android.cpp
    holy_fitra_dispatch.h
    holy_fitra_dispatch.cpp
    holy_fitra_android_topology.h
    holy_fitra_android_topology.cpp
    holy_fitra_runtime.h
    holy_fitra_runtime.cpp
    holy_fitra_jni.cpp
app/src/main/java/org/holyfitra/
    HolyFitraRuntime.kt
app/src/main/assets/models/
    decoder.nf4
    decoder.nf4.json
```

The provided artifacts currently live under `hyperc_llvm/` and can be copied into the Android module’s `src/main/cpp` and Kotlin source directories.

## 3. Native Lifecycle

The lifecycle is intentionally explicit:

```text
model buffers allocated or mapped
  → model metadata validated
  → topology detected
  → scheduler created
  → native runtime handle published
  → requests submitted
  → requests waited or cancelled
  → runtime close waits for scheduler workers
  → global JNI buffer references released
```

`nativeCreate` validates direct model buffers and NibbleFlow dimensions before creating the scheduler. The JNI handle stores global references to packed weights, scales, and optional bias. This keeps the backing direct buffers alive while native code uses their addresses.

`nativeClose` destroys the runtime first, which waits for worker threads and outstanding tasks, then releases global buffer references. This ordering prevents a worker from observing a freed model buffer.

## 4. Kotlin API

The central API is:

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
    )
    request.use { pending ->
        val status = pending.waitFor(timeoutMs = 1000)
        check(status == HolyFitraRuntime.Status.OK)
    }
}
```

All inference buffers are direct `ByteBuffer` instances. This avoids array pinning and makes native byte capacities unambiguous. Use `ByteBuffer.order(ByteOrder.nativeOrder())` and keep buffers alive for the request and runtime lifetimes.

## 5. JNI Request Semantics

`nativeSubmitMatvec` creates a request handle and global references to its input and output buffers. The native scheduler owns the task execution, while the request handle owns the Java buffer references.

The request supports:

| API | Behavior |
|---|---|
| `waitFor(0)` | Wait indefinitely |
| `waitFor(n)` | Wait up to `n` milliseconds and return `TIMEOUT` if incomplete |
| `cancel()` | Mark the request cancelled before it begins or at its next cancellation point |
| `close()` | Cancel, wait for completion, release global references, and free native request state |

Cancellation and deadline-skipping use explicit scheduler completion callbacks so a request cannot remain permanently unfinished when work is rejected before entering the kernel.

## 6. Status Model

The native status enum distinguishes data errors from lifecycle outcomes:

| Status | Meaning |
|---|---|
| `OK` | Matvec completed successfully |
| `INVALID_ARGUMENT` | Null handle or invalid pointer/buffer |
| `BUFFER_TOO_SMALL` | Model, input, or output capacity insufficient |
| `UNSUPPORTED_ABI` | Model/kernel ABI mismatch |
| `OVERFLOW` | Dimension arithmetic overflow |
| `KERNEL_FAILURE` | Native runtime or scheduling failure |
| `CANCELLED` | Request was cancelled before execution |
| `DEADLINE_MISSED` | Request missed its declared deadline |
| `TIMEOUT` | Wait ended before the request completed |

The Kotlin wrapper maps these values into a typed enum rather than forcing callers to parse error strings.

## 7. CMake and Gradle Integration

The integrated CMake target is `holyfitra_runtime`. It builds:

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

The Android Gradle configuration should select `arm64-v8a`, use a pinned NDK/CMake version, and package the shared library normally:

```kotlin
android {
    defaultConfig {
        minSdk = 26
        ndk { abiFilters += listOf("arm64-v8a") }
        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DANDROID_STL=c++_static",
                    "-DCMAKE_BUILD_TYPE=Release"
                )
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
}
```

The repository’s authoritative module is `android-lib/`; its complete library configuration is in `android-lib/build.gradle.kts`, with native targets in `android-lib/src/main/cpp/CMakeLists.txt`. When the Android SDK/NDK and Gradle wrapper are available, build it with `./gradlew :android-lib:assembleRelease`. The code block above is a conceptual integration example, not a second build entry point.

## 8. Model Asset Loading

A production model file should contain a versioned header followed by packed weights, scales, and optional bias. The header should include:

```text
magic
schema version
ABI version
in_dim
out_dim
group_size
packed byte count
scale count
bias count
model hash
calibration hash
kernel profile
quality gate
```

The initialization sequence should be:

```text
open asset
  → verify file hash and signature
  → parse dimensions and counts
  → validate NibbleFlow layout
  → map or copy direct buffers
  → create runtime handle
  → run deterministic self-test
  → publish runtime to application code
```

Do not publish the handle before the self-test passes. If int4 quality or kernel validation fails, select the int8 or float16 fallback profile.

## 9. Thermal Integration

The Android application or a platform adapter should map device thermal signals into:

```kotlin
runtime.setThermal(HolyFitraRuntime.ThermalState.HOT)
```

Recommended policy:

| Android state | Holy Fitra action |
|---|---|
| Normal | Full scheduler and normal speculation |
| Warm | Preserve interactive work; reduce background concurrency |
| Hot | Reduce draft length, prefer little cores for background tasks |
| Critical | Reject strict big-only tasks and use safe precision fallback |

Thermal samples should be debounced and passed through hysteresis. Do not change scheduler policy on every noisy sensor event.

## 10. Threading and Memory Rules

Create one runtime per process or model service, not one runtime per request. Reuse input, output, and KV-cache buffers. Do not allocate Java or native memory inside the repeated matvec path. Use bounded queue capacity so memory pressure produces explicit backpressure rather than unbounded task accumulation.

A request’s input and output buffers must not be mutated or reused until its request is complete or destroyed. The JNI global references protect lifetime, but they do not protect against application-level data races.

## 11. Host Validation Completed

The host validation compiled and executed:

- `nibbleflow_kernel.c` as C.
- The Android runtime wrapper and scheduler as C++17 with pthreads.
- The JNI bridge against installed host JNI headers.
- A shared `libholyfitra_runtime.so` containing the integrated native components.
- A runtime integration smoke test using a zero-weight model, asynchronous submission, completion wait, output verification, thermal update, and stats inspection.

The host test confirmed ABI version `1`, successful asynchronous matvec completion, correct zero output, and valid runtime statistics.

## 12. Android Validation Still Required

The sandbox cannot claim physical Android deployment. A real device or emulator must validate:

1. Gradle/CMake compilation with the pinned Android NDK.
2. `arm64-v8a` library loading through `System.loadLibrary`.
3. Direct buffer addresses and capacities from Android ART.
4. JNI global-reference lifecycle during configuration changes.
5. Scheduler CPU affinity masks and topology detection.
6. NibbleFlow native-versus-reference numerical equivalence.
7. Cancellation, timeout, close, and thermal transitions.
8. Sustained p50/p95/p99 latency, throughput, memory, battery, and thermal behavior.
9. Int4-to-int8/f16 fallback when proof or self-test gates fail.

## References

[1]: https://developer.android.com/ndk/guides/cmake "CMake in Android Studio"
[2]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[3]: https://docs.oracle.com/en/java/javase/17/docs/specs/jni/functions.html "Java Native Interface Functions"
[4]: https://developer.android.com/reference/android/os/PowerManager "Android PowerManager and thermal status APIs"
