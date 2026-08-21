# NibbleFlow Android JNI/NDK Integration Guide

**Project:** Holy Fitra  
**Kernel:** NibbleFlow int4 weight-only matvec  
**Current status:** Host native API validated; Android JNI compilation and physical device execution remain to be performed with an Android NDK toolchain/device.

## 1. Runtime Architecture

The Android deployment should use four layers:

```text
Kotlin/Java API
    ↓ JNI lifecycle bridge
C++ runtime validation and dispatch
    ↓ stable C ABI
NibbleFlow scalar or NEON kernel
    ↓
packed int4 weights + float32 scales + optional bias
```

The Java/Kotlin layer should not pass raw native pointers. It passes direct buffers to a native handle created by `nativeCreate`. The native handle stores global references to those buffers so the Java garbage collector cannot reclaim them while the kernel is using their addresses.

## 2. Native ABI

The public runtime API is defined in `nibbleflow_android.h`:

```c
typedef struct hf_nibbleflow_model {
    const uint8_t *packed;
    size_t packed_bytes;
    const float *scales;
    size_t scale_count;
    const float *bias;
    size_t bias_count;
    int32_t in_dim;
    int32_t out_dim;
    int32_t group_size;
    uint32_t abi_version;
} hf_nibbleflow_model;

hf_status hf_nibbleflow_validate_model(const hf_nibbleflow_model *model);
hf_status hf_nibbleflow_matvec(
    const hf_nibbleflow_model *model,
    const float *input,
    size_t input_count,
    float *output,
    size_t output_count
);
```

The runtime validates dimensions, even group size, ABI version, packed byte count, scale count, optional bias count, and input/output capacities before invoking the kernel.

## 3. Android Project Layout

A practical Android library module can use:

```text
app/src/main/cpp/
    CMakeLists.txt
    nibbleflow_kernel.c
    nibbleflow_android.cpp
    nibbleflow_android.h
    nibbleflow_jni.cpp
app/src/main/java/org/holyfitra/
    NibbleFlow.kt
app/src/main/assets/models/
    decoder.nf4
    decoder.nf4.json
```

The binary asset should contain a versioned header followed by packed bytes, scales, and optional bias. The manifest should contain the NibbleFlow layout, ABI version, model hash, calibration hash, selected group size, kernel profile, and quality proof.

## 4. CMake Configuration

The provided `CMakeLists.txt` builds a shared library:

```cmake
add_library(holyfitra_nibbleflow SHARED
    nibbleflow_kernel.c
    nibbleflow_android.cpp
    nibbleflow_jni.cpp
)

target_compile_options(holyfitra_nibbleflow PRIVATE
    -O3
    -ffunction-sections
    -fdata-sections
    -fvisibility=hidden
)

target_link_options(holyfitra_nibbleflow PRIVATE
    -Wl,--gc-sections
)
```

The Android Gradle module should select only the required ABI for the first deployment:

```kotlin
android {
    defaultConfig {
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_static")
            }
        }
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }
}
```

The exact Android Gradle Plugin and NDK versions should be pinned in the project so the generated ABI and compiler flags are reproducible.

## 5. Kotlin Usage

The provided `NibbleFlow.kt` wrapper uses direct buffers:

```kotlin
val packed = NibbleFlow.directBytes(packedByteCount)
val scales = NibbleFlow.directFloats(scaleCount)
val bias = NibbleFlow.directFloats(outDim)
val input = NibbleFlow.directFloats(inDim)
val output = NibbleFlow.directFloats(outDim)

NibbleFlow.create(
    packed = packed,
    scales = scales,
    bias = bias,
    inDim = inDim,
    outDim = outDim,
    groupSize = groupSize,
).use { kernel ->
    kernel.matvec(input, output)
}
```

The buffers must remain alive for the entire native handle lifetime. The native bridge creates global references to the buffers, and `close()` releases them. The wrapper should be used with Kotlin’s `use` block or an equivalent lifecycle owner.

## 6. Direct Buffer Rules

The JNI bridge uses `GetDirectBufferAddress` and `GetDirectBufferCapacity`. Therefore:

| Buffer | Required representation |
|---|---|
| Packed weights | Direct `ByteBuffer`, native byte order |
| Scales | Direct `FloatBuffer` backed by a direct buffer |
| Bias | Optional direct `FloatBuffer` |
| Input | Direct `FloatBuffer` |
| Output | Direct writable `FloatBuffer` |

Do not pass heap arrays to the current JNI API. If a Java/Kotlin caller has arrays, copy them into pooled direct buffers before inference. For repeated decoding, allocate these buffers once and reuse them rather than allocating per token.

## 7. Model Asset Loading

For small models, copy the asset into a direct buffer once during initialization. For larger models, prefer a file descriptor or memory-mapped asset path and validate the file hash before exposing its pages to the kernel.

The recommended initialization sequence is:

```text
open asset
  → read and validate header
  → verify model and calibration hashes
  → verify ABI and layout
  → map or copy packed weights
  → map scales and bias
  → create native handle
  → run one deterministic self-test
  → publish ready state
```

Do not publish a model handle before the self-test passes. If validation fails, select an int8 or float16 fallback profile rather than attempting an unverified int4 call.

## 8. NEON Dispatch

The C runtime exposes `hf_nibbleflow_has_neon()`. For an `arm64-v8a` Android process, AArch64 NEON is part of the normal architecture baseline, but runtime dispatch remains useful for diagnostics and future profile selection.

The production dispatcher should select among:

| Profile | Condition | Behavior |
|---|---|---|
| `neon.int4.f32` | ABI, layout, and proof pass | NibbleFlow fused kernel |
| `scalar.int4.f32` | NEON profile unavailable or self-test fails | Portable native kernel |
| `int8.f32` | Int4 proof or quality gate fails | Int8 fallback |
| `f16` | Int8 proof or kernel fails | Float16 fallback |

Kernel selection must be bound to the quantization proof. A device may not silently choose a different kernel whose numerical behavior was not evaluated.

## 9. Threading and Lifecycle

The kernel call itself should be synchronous and allocation-free. A higher-level inference runtime can use a dedicated worker thread, but the JNI handle should not be shared for concurrent writes unless it is explicitly synchronized.

Recommended lifecycle:

```text
CREATED → VALIDATING → READY → RUNNING → CLOSED
                       ↘ FAILED
```

`close()` must be idempotent. Calls after close must fail before touching native memory. For Android configuration changes, the model handle should live in a lifecycle-aware native owner or be reconstructed from verified assets.

## 10. JNI Error Handling

The bridge returns a small status enum and throws Java exceptions for invalid buffers or invalid model creation. Production code should map statuses to structured errors:

| Status | Meaning | Fallback |
|---|---|---|
| `HF_INVALID_ARGUMENT` | Null, malformed, or unsupported input | Caller correction |
| `HF_BUFFER_TOO_SMALL` | Asset or activation buffer is undersized | Reload or reallocate |
| `HF_UNSUPPORTED_ABI` | Manifest/kernel mismatch | Select compatible profile |
| `HF_OVERFLOW` | Dimension arithmetic overflow | Reject model |
| `HF_KERNEL_FAILURE` | Native execution failure | Safe fallback and audit |

Never continue with partially initialized native handles.

## 11. Validation Strategy

### Host validation

The current host smoke test compiles the C kernel separately, links the C++ runtime wrapper, executes a zero-weight case, checks ABI version `1`, verifies successful matvec, and confirms undersized packed storage returns `HF_BUFFER_TOO_SMALL`.

### AArch64 object validation

The kernel can be emitted without a complete Android libc sysroot using a freestanding Clang command. The resulting object must be inspected for:

```text
ELF64 + AArch64 machine + expected symbols + expected ABI
```

This confirms object generation only.

### Android device validation

A physical or emulator test must verify:

1. JNI library loading for `arm64-v8a`.
2. Direct-buffer addresses and capacities.
3. Model initialization and self-test.
4. Native versus reference output over random and adversarial shapes.
5. Repeated decode without allocations in the hot path.
6. Cancellation and close behavior.
7. Sustained latency, thermal state, memory pressure, and battery impact.
8. Int4 fallback to int8/f16 when a proof or self-test fails.

No sandbox result should be described as physical Android performance.

## 12. Recommended Production Enhancements

The next implementation steps are to add a versioned binary asset header, memory-mapped model pages, signed manifest verification, asynchronous page prefetch, pooled direct buffers, JNI critical-section profiling, ARM64 self-tests on a device matrix, and a C ABI that carries proof and profile IDs alongside the tensor dimensions.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/ndk/guides/cmake "CMake in Android Studio"
[3]: https://docs.oracle.com/en/java/javase/17/docs/specs/jni/functions.html "Java Native Interface Functions"
[4]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
