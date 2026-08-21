# Holy Fitra Ragged Attention Scheduler Integration

**Feature:** Work-stealing execution of true ragged attention on Android heterogeneous cores.  
**Status:** Host-integrated and sanitizer-validated; physical Android ARM64 execution remains pending.

## Executive Summary

The ragged attention kernel is now integrated into the Holy Fitra work-stealing scheduler as a first-class sequence-aware workload. The scheduler does not receive a generic opaque callback only; it receives a verified ragged batch plan containing kernel kind, core policy, priority, deadline, KV generation, and sequence-chunk size.

The runtime splits a packed ragged batch into sequence chunks. Each chunk becomes one scheduler task with:

```text
one kernel invocation
one core-affinity policy
one priority/deadline
one cancellation boundary
one group-completion contribution
```

The result preserves packed offsets and never adds token padding. Work stealing remains available when a preferred core class is unavailable, while thermal policy can downgrade placement and kernel selection safely.

## 1. Scheduler Task Model

A `RaggedDispatchPlan` contains:

| Field | Purpose |
|---|---|
| `kernel` | Scalar, NEON, or SVE entry point |
| `core_class` | Big/little affinity preference |
| `priority` | Background, throughput, latency, or interactive scheduling |
| `deadline_ns` | Scheduler deadline admission |
| `kv_generation` | Cache ownership generation carried with the plan |
| `sequences_per_task` | Ragged sequence chunk granularity |
| `allow_kernel_fallback` | Whether safe downgrade is permitted |

The scheduler’s existing `Task.sequence` field records the first sequence index of each chunk. This preserves useful sequence identity for tracing and metrics without changing the core scheduler ABI.

## 2. Chunking Strategy

Given `sequence_count` and `sequences_per_task`, the bridge submits:

```text
chunk 0: sequences [0, k)
chunk 1: sequences [k, 2k)
...
```

For each chunk, it creates local offsets relative to the chunk’s token base:

```text
local_offsets[i] = global_offsets[first + i] - global_offsets[first]
```

The Q/K/V/output pointers are advanced to the chunk’s first token. The kernel therefore receives a compact self-contained ragged batch, and its inner loop remains:

```text
for row in [local_offsets[s], local_offsets[s + 1]):
    for key in [local_offsets[s], row]:
        ...
```

No sequence can attend across a chunk boundary because each chunk’s offsets begin at zero and end at its local token count.

## 3. Big.LITTLE Placement Policy

The dispatch policy is deliberately conservative:

| Condition | Kernel | Default placement |
|---|---|---|
| SVE available, non-critical thermal, compatible hidden size | SVE | Big-preferred |
| NEON available, compatible hidden size | NEON | Big-preferred for large work, little-preferred for small work |
| No vector capability or incompatible hidden size | Scalar | Little-preferred |
| Critical thermal state | NEON or scalar fallback | Little-preferred |
| Interactive priority | Any compatible vector kernel | Big-preferred unless thermal critical |

The scheduler may still steal work when the preferred core class is busy or unavailable. Strict big-only placement should be reserved for explicit latency-critical plans; ordinary ragged tasks use preferred placement so thermal transitions do not strand work.

## 4. Work Estimation

The ragged work estimate is based on:

```text
Σ sequence_length² × d_model
```

This estimate controls placement and chunk size. Large work is placed preferentially on big cores. Smaller chunks or interactive requests remain eligible for little cores to reduce contention and energy use.

A production cost model should add measured terms for:

```text
kernel launch
scheduler admission
KV-page locality
L2/L3 cache behavior
thermal frequency state
```

## 5. Cancellation and Deadlines

Cancellation is group-scoped. The request owns one cancellation token shared by all sequence chunks. Each task checks cancellation before invoking its kernel. If a queued task is cancelled, the scheduler calls its cancellation callback and decrements group completion. If a deadline prevents execution, the deadline callback records the failure and also decrements completion.

This prevents the classic asynchronous bug where one rejected chunk leaves the parent request waiting forever.

The current wait API distinguishes:

```text
Completed
Cancelled
DeadlineMissed
Failed
Timeout
```

## 6. KV-Cache Locality

The `kv_generation` field binds a dispatch plan to the expected KV-cache generation. The next production version should additionally carry page-range metadata per chunk:

```text
chunk → sequence IDs → KV page spans → scheduler task
```

The scheduler can then prefer workers whose previous task touched nearby pages. This should be a soft locality preference, never a correctness requirement, because work stealing must remain possible.

## 7. Validation Results

| Validation | Result |
|---|---|
| Ragged chunk scheduler integration | Passed |
| Scalar reference equivalence | Passed |
| NEON entry equivalence on host fallback | Passed |
| Sequence chunk offset rebasing | Passed |
| Work-stealing-compatible submission | Passed |
| SVE/NEON thermal selection policy | Passed |
| Big-preferred versus little-preferred policy | Passed |
| Cancellation completion | Passed |
| AddressSanitizer/UndefinedBehaviorSanitizer | Passed |

The integration test used eight ragged sequences with lengths `[1, 2, 3, 5, 7, 8, 4, 6]`, eight hidden dimensions, and two sequences per scheduler task. The scheduler executed all chunks and matched the scalar ragged reference within the test tolerance.

## 8. Android Deployment

The Android JNI runtime should construct a verified `RaggedDispatchPlan` before submission. The plan identity should include:

```text
model hash
ragged layout hash
ABI version
d_model
kernel kind
CPU feature mask
thermal state
KV generation
core policy
```

The JNI layer should keep Q, K, V, output, offsets, and page metadata direct buffers alive until the group request completes. It must reject non-direct buffers, invalid offset ranges, integer multiplication overflow, stale KV generations, and incompatible SVE plans before scheduler submission.

## 9. Future Optimizations

The next optimization is to precompute local offset arrays in the packer instead of allocating one vector inside each scheduler task. This would make task execution allocation-free. The following step is to add a bounded per-worker ragged-task arena so chunk metadata can be recycled without global allocation.

A further improvement is sequence-length-aware chunking. Group long sequences into smaller task groups and short sequences into larger groups so work stealing has similar task cost. This avoids making one worker process a very long ragged chunk while other workers become idle.

## Production Boundaries

The sandbox validates scheduler integration, offset rebasing, host scalar behavior, cancellation, and object-compatible kernel entry points. It does not execute NEON or SVE instructions on physical Android hardware. Device validation must measure core frequency, thermal throttling, p99 latency, energy per token, KV-page locality, and scheduler steal behavior under sustained mixed workloads.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[3]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
[4]: https://developer.arm.com/documentation/102476/latest "Arm Scalable Vector Extension"
