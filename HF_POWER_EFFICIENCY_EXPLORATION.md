# HF Power and Efficiency Exploration

## Evidence-first objective

HF already spans a compiler, self-hosting path, HyperIR contracts, native INT4 runtime, Android packaging, supervised agents, and learning surfaces. The next improvement must increase useful work per request without treating host compilation or remote packaging as mobile-device proof.

## Candidate decision record

| Rank | Candidate | Expected gain | Verification surface | Decision |
|---:|---|---|---|---|
| 1 | Parallel micro-batch matvec completion behind one public request | Uses the existing worker scheduler for independent batch rows while retaining one completion/cancellation handle. | Native batch-equivalence test, cancellation/deadline guard tests, host benchmark. | **Select** |
| 2 | Priority-bucket scheduler queues | Could reduce linear queue scans in large backlogs. | Scheduler fairness, deadline, shutdown, and contention tests. | Defer; higher semantic risk. |
| 3 | Targeted worker wakeups | Could reduce idle wakeups under queue pressure. | Scheduler stress plus latency benchmark. | Defer; requires careful work-availability ownership. |
| 4 | Tensor shape/dtype canonical checking | Strengthens HF language power and safer lowering. | Parser/type golden tests. | Defer; larger language-design cohort. |
| 5 | Incremental module cache invalidation | Cuts repeated compilation work. | Cache correctness and reproducibility fixtures. | Defer; compiler cache already exists and needs broader audit first. |
| 6 | Native asynchronous task handles in language lowering | Improves language expressiveness. | Effect/type tests and lowering snapshots. | Defer; semantic design, not a short efficiency patch. |
| 7 | Learned thermal/scheduler policy | May improve device behavior. | Physical-device campaign required. | Reject for now; no measured device evidence. |
| 8 | GPU/accelerator backend | Potentially large throughput gain. | Stable ABI, device instrumentation, hardware-specific tests. | Defer; no validated backend/hardware target. |
| 9 | Direct on-phone LLVM compilation | Stronger mobile workflow. | Full Android compiler lifecycle and device evidence. | Reject for now; Pix Studio remains a local editor and host handoff tool. |
| 10 | Unrestricted autonomous agent execution | More automation surface. | Policy/replay/security test matrix. | Reject; conflicts with supervised workspace and evidence controls. |

## Selected cohort: parallel micro-batch completion

`hf_runtime_submit_matvec_batch` currently takes one scheduler slot and iterates every batch row serially. Each row is independent because it receives disjoint input/output strides. The selected change will split only sufficiently large batches into a bounded number of scheduler tasks while keeping one public request. It must preserve byte-for-byte numerical equivalence for the existing NibbleFlow matvec path, propagate cancellation/deadline/failure once, and fall back to the current serial shape for small batches or unavailable worker capacity.

> Host numerical and scheduler results establish only host-native correctness and a host benchmark. They do **not** establish Android ART/JNI lifecycle behavior, NEON throughput, big.LITTLE efficiency, thermal behavior, or physical-device stability.

## Cross-checks

Android’s performance guidance recommends moving long work off the UI thread, avoiding excessive thread creation, and sizing work to available CPU resources rather than assuming more threads are always faster. oneDNN’s thread-pool guidance uses a bounded job count of `min(work items, thread count)` and distributes contiguous ranges to each job. HF will follow the same bounded-range principle by reusing its existing scheduler, limiting the fan-out to independent rows and available work, and retaining a serial fallback for small batches. [1] [2]

## References

[1]: https://developer.android.com/topic/performance/threads "Android Developers: Better performance through threading"
[2]: https://uxlfoundation.github.io/oneDNN/dev_guide_threadpool.html "oneDNN: Using Threadpool-based Threading"

## Validation result

The implementation now reserves all planned micro-batch completion slots before submitting any range, preventing an early-finishing worker from exposing the shared request as complete while another range is still pending. An initial 100-run host stress loop exposed that race as a numerical mismatch; the corrected implementation passed a further 100 consecutive native batch-regression runs and an address/undefined-behavior sanitizer run.

The existing 2,048-row fused benchmark was sampled 20 times from preserved pre-change and corrected host binaries. Mean fused latency was **6.306 ms** before and **2.119 ms** after the bounded range implementation, a **2.97× host-only reduction** for this synthetic zero-weight fixture. The benchmark reported two or three completed range tasks depending on host scheduling. This is not an Android, ART/JNI, NEON, big.LITTLE, thermal, or physical-device claim.

The default host CMake target compiled the modified runtime source but could not link its Android JNI source because this sandbox lacks `jni.h`. That host-environment limitation is separate from the existing Android NDK build gate; no Android build or device result is claimed here.
