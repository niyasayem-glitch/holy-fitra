# Holy Fitra Cross-Layer Performance Breakthrough

**Breakthrough:** Fused batch execution across JNI, request management, scheduling, and NibbleFlow inference.  
**Author:** Manus AI  
**Status:** Host-validated native prototype; physical Android ARM64 performance not claimed.

## Executive Summary

The latest Holy Fitra breakthrough removes repeated work across the complete mobile inference path. Instead of submitting one scheduler request for every vector, crossing JNI repeatedly, allocating one request state per vector, and waking the scheduler for every matvec, the runtime now supports one **fused batch request** containing many strided vectors.

The batch request validates the model and buffer contract once, enters the scheduler once, retains the input and output buffers once through JNI, and executes the NibbleFlow kernel repeatedly inside one cancellation-aware task. This preserves zero-copy semantics while amortizing scheduler and JNI overhead.

On the sandbox host, a 2,048-vector deterministic workload measured:

| Execution path | Time |
|---|---:|
| 2,048 individual asynchronous requests | 63.053 ms |
| One fused batch request | 10.821 ms |
| Observed host speedup | **5.83×** |

The arithmetic kernel and model data were unchanged. The improvement comes from reducing control-plane overhead, not from pretending that the kernel itself became 5.83× faster.

## The Repeated-Work Problem

The previous path looked like this:

```text
for every vector:
    allocate request state
    submit scheduler task
    choose worker
    wake or steal
    call NibbleFlow
    wait
    release request state
```

This path is safe but inefficient when many independent vectors are available. It repeatedly pays for control-plane operations that do not contribute to matrix arithmetic.

The new path is:

```text
validate one batch
  → allocate one request state
  → submit one scheduler task
  → choose one eligible worker
  → execute NibbleFlow over all strided vectors
  → one completion notification
```

## Native API

The new C API is:

```c
hf_status hf_runtime_submit_matvec_batch(
    hf_holyfitra_runtime *runtime,
    const float *input,
    size_t batch_count,
    size_t input_stride,
    float *output,
    size_t output_stride,
    int core_class,
    int priority,
    uint64_t deadline_ns,
    hf_runtime_request **request
);
```

The strides are expressed in float elements. Each row uses:

```text
input + row * input_stride
output + row * output_stride
```

The runtime rejects zero batches, null pointers, undersized strides, and multiplication overflow before allocating a task. The task checks cancellation between vectors, so a long batch remains interruptible.

## JNI and Kotlin Integration

The JNI bridge adds `nativeSubmitMatvecBatch`. It validates that the input and output are direct `ByteBuffer` objects, checks the total byte capacity using 64-bit arithmetic, retains global references for the request lifetime, and forwards the validated strided batch to the native runtime.

The Kotlin API adds:

```kotlin
fun submitMatvecBatch(
    input: ByteBuffer,
    batchCount: Int,
    inputStrideFloats: Int,
    output: ByteBuffer,
    outputStrideFloats: Int,
    coreClass: CoreClass = CoreClass.ANY,
    priority: Priority = Priority.THROUGHPUT,
    deadlineNs: Long = 0L,
): Request
```

This is intended for prompt prefill blocks, batched classifier requests, multiple beam candidates, grouped speculative proposals, and other workloads where vectors share a model and execution policy.

## Correctness Invariant

Fused execution must be equivalent to repeated single execution:

```text
fused(input[0..B-1]) == map(single_matvec, input[0..B-1])
```

The differential test uses a strided input and output layout, runs 16 vectors individually, runs the same 16 vectors as one fused request, and compares every output element. It also verifies that an overflowing batch count is rejected before submission.

## Validation Results

| Validation | Result |
|---|---|
| Fused batch differential test | Passed |
| Strided input/output handling | Passed |
| Overflow rejection | Passed |
| Asynchronous wait and request cleanup | Passed |
| AddressSanitizer/UndefinedBehaviorSanitizer | Passed |
| JNI bridge compilation with host JNI headers | Passed |
| Integrated shared-library link | Passed |
| 2,048-vector host benchmark | Passed |
| Host observed speedup | 5.83× |

The host benchmark used a deterministic zero-weight NibbleFlow fixture. It validates control-plane amortization but does not represent physical Android thermal, battery, cache, or ARM64 NEON behavior.

## Why This Is a Breakthrough

Holy Fitra’s earlier optimizations focused mainly on individual kernels and individual requests. The fused batch path recognizes that **the control plane is part of the inference system**. A highly optimized kernel can still be dominated by JNI, queue, synchronization, and request-lifecycle overhead when invoked too frequently.

This design creates a reusable boundary for future fusion:

| Future fusion | Control-plane work removed |
|---|---|
| Transformer prefill batch | One scheduler request per token/block |
| Beam search | One JNI call per candidate |
| Speculative decoding | One request per draft token |
| KV-cache page operations | Repeated allocation and wakeups |
| Quantized layer sequence | Separate dispatch between compatible kernels |
| JNI model service | Repeated direct-buffer validation |

## Safety and Cancellation

The batch task checks cancellation before each vector. If cancellation arrives, it returns `HF_CANCELLED` and completes the request. If the scheduler rejects the task because of backpressure or shutdown, the request state is freed immediately and the caller receives an explicit failure status.

The JNI bridge keeps direct input and output buffers alive with global references until the request is destroyed. This protects native pointer lifetime but does not authorize the application to mutate those buffers concurrently. Application code must treat them as borrowed immutable input and exclusive output until completion.

## Android Deployment Strategy

On Android, the batch path should be used selectively:

| Workload | Recommended path |
|---|---|
| Single interactive decode token | Single matvec request |
| Prompt prefill block | Fused batch request |
| Multiple independent user requests | Batch only when latency budget allows |
| Speculative candidate verification | Fused batch request |
| Thermal critical state | Smaller batches or single interactive path |
| Memory pressure | Reuse bounded buffers and reduce batch size |

Batch size must be tuned against p50/p95/p99 latency, not only throughput. A very large batch can improve arithmetic efficiency but harm interactive responsiveness and thermal stability. The scheduler should support deadline-aware batch splitting in a future phase.

## Next Breakthrough Opportunities

The next highest-leverage extension is **adaptive micro-batching**: group requests for a short bounded window, fuse them when the queue contains compatible plans, and split or bypass batching when an interactive deadline is near. The batching key should include plan ID, model pointer, precision, layout, core policy, thermal profile, and stride.

A second extension is kernel-level multi-output tiling: process several output rows or vectors in one NibbleFlow NEON loop to improve register reuse. This must be validated against the existing scalar and single-vector kernels and gated by model layout and device features.

## Production Boundaries

The current implementation has host validation and JNI syntax/link validation. It does not yet measure physical Android speed, energy, thermal throttling, or ARM64 cache behavior. A device campaign must compare single and fused paths under sustained workloads and verify that the batch speedup survives Android scheduling, CPU affinity, memory bandwidth, and thermal limits.

## References

[1]: https://developer.android.com/ndk/guides/cmake "CMake in Android Studio"
[2]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[3]: https://docs.oracle.com/en/java/javase/17/docs/specs/jni/functions.html "Java Native Interface Functions"
[4]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
