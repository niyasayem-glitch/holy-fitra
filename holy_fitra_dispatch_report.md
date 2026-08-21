# Holy Fitra Android ARM64 Dispatch Runtime

**Component:** Heterogeneous-core work-stealing scheduler  
**Author:** Manus AI  
**Status:** Host-validated C++ prototype; physical Android tuning not yet claimed.

## Executive Summary

The Holy Fitra dispatch runtime now provides a bounded multithreaded scheduler for Android-style big/little ARM64 systems. It combines per-worker work queues, local priority-aware execution, remote stealing, task affinity classes, deadlines, cancellation tokens, bounded backpressure, thermal gates, optional CPU affinity pinning, and topology-derived worker sizing.

The design treats smooth mobile execution as a control problem rather than simply creating one thread per core. Interactive decode work can prefer big cores, background preprocessing can prefer little cores, strict big-core tasks are rejected during critical thermal state, and preferred tasks can safely fall back to an eligible class. Queue capacity prevents unbounded memory growth, while cancellation and deadline checks avoid wasting work that can no longer benefit the user.

The prototype passed the scheduler regression suite, topology detection suite, and AddressSanitizer/UndefinedBehaviorSanitizer execution. A mixed host benchmark completed 20,000 tasks with 20,000 completions, zero queued tasks, 12,349 steals, and approximately 37,711 tasks per second. This is a sandbox x86-64 host measurement, not an Android device result.

## 1. Scheduler Architecture

```text
submitter
   ↓
bounded admission + task contract validation
   ↓
least-loaded eligible worker queue
   ↓
owner executes priority/deadline-selected task
   ↓
idle worker steals eligible work from another queue
   ↓
TaskContext: worker ID, big/little class, cancellation token
   ↓
completion metrics and backpressure state
```

Each worker owns a bounded deque. The owner selects from its queue with priority and deadline awareness. A worker that has no eligible local work scans other workers and steals the highest-value eligible task. The current prototype uses mutex-protected deques to prioritize correctness and straightforward lifecycle behavior; a production version can replace the queue internals with a proven bounded Chase–Lev implementation while preserving the same public contract.

## 2. Task Contract

Every scheduled task declares:

| Field | Purpose |
|---|---|
| Function | Native callable receiving `TaskContext` |
| Core class | Any, big-only, little-only, big-preferred, little-preferred |
| Priority | Background, throughput, latency, interactive |
| Deadline | Optional monotonic nanosecond deadline |
| Cancellation | Shared atomic token checked before execution and by the task |
| Sequence | Scheduler-assigned ordering identity |

The scheduler rejects empty tasks, expired-at-submit deadlines, impossible strict affinity, and strict big-core work during critical thermal state. It returns `Accepted`, `Backpressure`, `Stopped`, or `Rejected` rather than silently dropping work.

## 3. Android Heterogeneous-Core Policy

The topology detector reads online CPU information from Android-style sysfs paths. It prefers `cpu_capacity`, falls back to `cpuinfo_max_freq`, and finally uses a deterministic host fallback when synthetic or host sysfs does not expose useful data.

A topology is divided into little and big groups when the maximum score is materially above the minimum. The tuned configuration uses a conservative worker count:

| Core class | Default tuning |
|---|---|
| Little workers | Approximately half the little-core count, minimum one |
| Big workers | At most two, minimum one when available |
| Queue capacity | 256 by default; lower for interactive-only services |
| Pinning | Enabled for Android deployment after topology validation |
| Big-preferred | Uses big cores when available, falls back to little cores when necessary |
| Little-preferred | Uses little cores first, falls back to big cores when necessary |
| Big-only | Rejected if no eligible big worker exists or thermal state is critical |

The conservative big-worker cap avoids oversubscribing scarce performance cores with multiple model runtimes. A physical device profile may increase this cap only after measuring tail latency, sustained throughput, and thermal response.

## 4. Thermal Policy

The scheduler supports `Normal`, `Warm`, `Hot`, and `Critical` thermal states. The current hard safety rule is that big workers do not execute while the state is `Critical`. Strict big-only submissions are rejected, while preferred-big work can fall back to little workers. This prevents a preference from becoming a deadlock.

A production Android adapter should derive state from a device-specific thermal signal and apply hysteresis. The scheduler should not change profiles on every noisy temperature sample. Recommended policy:

| State | Scheduling behavior |
|---|---|
| Normal | Full worker set and normal precision |
| Warm | Prefer existing assignments; reduce background concurrency if queue pressure rises |
| Hot | Reduce speculative draft length and low-priority parallelism |
| Critical | Disable big-only work, reduce concurrency, use safe precision fallback |

## 5. Work-Stealing Behavior

The local owner uses priority-aware selection. Interactive tasks outrank latency tasks, which outrank throughput and background work. Among equal priorities, tasks with real deadlines outrank untimed work, and earlier deadlines win. Sequence order breaks remaining ties.

Stealing is intentionally constrained by task eligibility. A little worker cannot steal strict big-only work, and a critical thermal state does not allow a big worker to take any task. This is more important than raw steal rate because an incorrect steal can violate device policy or cause cache placement inefficiency.

The runtime reports per-worker steals and executions so a tuning campaign can identify whether queues are imbalanced, affinity is too strict, or the worker count is too high.

## 6. Backpressure and Cancellation

The queue capacity is a hard memory bound. When all eligible queues are full, `submit` returns `Backpressure`. Callers should either yield, await capacity, drop an obsolete speculative task, or select a lower-cost fallback. The benchmark and tests use retry-with-yield only for controlled measurement.

Cancellation is represented by an atomic token. The scheduler checks it before execution, increments cancellation metrics, and passes it into the task context so long-running kernels can check between tiles or decode steps. A production model runtime should connect cancellation to request IDs and ensure native kernels have bounded cancellation points.

## 7. Validation Results

### Scheduler regression

The saved C++ regression suite passed checks for:

| Test area | Result |
|---|---|
| Mixed task completion | Passed |
| Cancellation accounting | Passed |
| Deadline rejection | Passed |
| Critical thermal strict-big rejection | Passed |
| Critical thermal preferred-big fallback | Passed |
| Queue backpressure | Passed |
| Queue drain at shutdown | Passed |

### Topology integration

A synthetic eight-core topology with six little cores and two big cores was detected from `cpu_capacity`. The tuned policy selected three little workers and two big workers. Strict big-only work was rejected at critical thermal state, while preferred-big work was accepted on an eligible little worker.

### Sanitizers

The dispatch regression passed AddressSanitizer and UndefinedBehaviorSanitizer execution in the sandbox build.

### Host benchmark

The mixed workload benchmark used 20,000 short tasks across three little and two big workers. The observed run completed as follows:

| Metric | Observed value |
|---|---:|
| Submitted tasks | 20,000 |
| Completed tasks | 20,000 |
| Elapsed time | 530.347 ms |
| Throughput | 37,711.1 tasks/s |
| Steals | 12,349 |
| Rejected submissions | 0 |
| Queued after shutdown | 0 |

This benchmark is a host x86-64 C++ measurement using synthetic tasks. It does not represent Android performance, energy, thermal behavior, or big/little hardware behavior.

## 8. Android Integration Strategy

The scheduler should live below the NibbleFlow JNI layer and above kernel invocation. A model request creates tasks such as:

```text
prefill block       → big-preferred, throughput priority
single-token decode → big-preferred, interactive priority, deadline
KV-page prefetch    → little-preferred, background priority
quantization proof  → little-preferred, throughput priority
thermal downgrade   → interactive control task
```

The JNI owner should create one scheduler per process or one shared scheduler per model service, not one scheduler per request. Native handles should submit work through request IDs and cancellation tokens. Model buffers remain immutable and shared; per-request activation buffers and KV-cache pages must come from bounded pools.

## 9. Production ARM64 Tuning Sequence

A real device campaign should tune in this order:

1. Detect topology and validate CPU masks.
2. Measure one worker per physical CPU against conservative worker counts.
3. Compare pinned and unpinned execution because Android’s scheduler may outperform manual pinning on some devices.
4. Measure interactive p50, p95, and p99 decode latency separately from throughput.
5. Add thermal hysteresis and sustained 5–15 minute workloads.
6. Vary big-worker cap, little-worker count, queue capacity, and steal interval.
7. Measure battery and thermal state together with tokens per joule.
8. Retain a profile only when numerical output, cancellation, fairness, and thermal gates all pass.

The correct device objective is not maximum instantaneous throughput. It is stable tail latency and useful tokens per joule under sustained thermal limits.

## 10. Remaining Hardening

The current deques are mutex-protected. This is a sound prototype choice but leaves performance available for a production lock-free bounded Chase–Lev deque with carefully audited memory ordering. The runtime also needs a real Android thermal adapter, request deadlines tied to UI frames, structured task errors, queue-age telemetry, native cancellation points inside NibbleFlow tiles, and device-specific proof manifests.

CPU affinity must be treated as a policy option rather than an unquestioned optimization. Manual pinning can interact poorly with Android’s scheduler, power management, and vendor-specific topology. It should be enabled only after measured device validation.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/reference/android/os/PowerManager "Android PowerManager and thermal status APIs"
[3]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[4]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
