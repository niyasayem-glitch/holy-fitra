# HF Custom Priority-Lane Scheduler Design

## Goal

Replace the current queue’s repeated full scans and lock-taking queue-size probes with a bounded scheduler structure designed around HF’s actual contracts. This is not a generic scheduler import. It must preserve HF’s priority, earliest-deadline, core-class, thermal, cancellation, shutdown, and batch-receipt expectations.

## Queue model

Each worker owns four bounded FIFO lanes, one per `Priority` value. Every lane has an atomic depth hint for admission and wake checks, while its task storage remains mutex-protected for safe task ownership and shutdown draining. Submission picks the worker with the lowest compatible hinted depth, then appends to the matching priority lane. Owner pop and stealing inspect priority lanes from `Interactive` down to `Background`; within one lane, a bounded earliest-deadline selection preserves HF’s deadline precedence without scanning unrelated priority classes.

| Invariant | Required behavior |
|---|---|
| Capacity | The total of all worker lanes stays at or below `queue_capacity`; a full compatible worker yields `Backpressure`. |
| Priority | Higher priority is always considered before a lower priority. |
| Deadline | Within equal priority, a timed task outranks untimed work and the earliest deadline wins. |
| Core class and thermal state | Existing `BigOnly`, `LittleOnly`, preference behavior, and critical thermal gating remain unchanged. |
| Cancellation and failure | A cancelled, deadline-missed, or throwing task must execute the same callback path and keep request completion observable. |
| Shutdown | Queued tasks are drained exactly once through their cancellation callback; no task is stranded. |
| Receipts | The runtime’s planned/admitted/terminal/rejected batch receipt rules remain unchanged. |

## Measurement contract

The custom path is retained only if it passes all current scheduler and batch-runtime regressions, targeted lane-order and capacity tests, 100 repeated shutdown/cancellation stress rounds, and sanitizer checks. It must then improve the 20,000-task dispatch benchmark in a 20-sample interleaved comparison. A lower mean without at least 60% faster paired samples is insufficient. Results remain host-only; Android worker placement and thermal benefits require device evidence.

## August 2026 result: rejected on the host dispatch gate

The implementation was independently written for HF, not imported from another scheduler. It first used four mutex-protected priority deques with per-lane and total atomic depth hints. A second candidate replaced each lane with an HF-specific deadline/sequence heap, retaining a full-lane fallback only when thermal or core-class state made the heap top incompatible. Both versions preserved the scheduler API and passed the targeted priority/earliest-deadline test, the existing scheduler regression, the batch-runtime regression, 100 all-priority multi-producer shutdown/thermal stress rounds, and ASan/UBSan scheduler plus stress runs.

| Candidate | Baseline mean tasks/s | Candidate mean tasks/s | Paired geometric speed | Faster pairs | Decision |
|---|---:|---:|---:|---:|---|
| Priority FIFO lanes with intra-lane scan | 60,167.5 | 34,163.5 | 0.569x | 0/20 | Reject |
| Priority lanes with deadline/sequence heap fast path | 59,364.0 | 35,101.2 | 0.592x | 0/20 | Reject |

Neither candidate improved the fixed 20,000-task host dispatch workload or reached the required 60% faster-pair threshold. The experimental scheduler source was restored to the previously validated implementation; no priority-lane runtime change is retained. The added targeted priority-order regression and all-priority stress coverage remain useful checks of the existing contract. These results identify a host benchmark outcome only. They do not establish a cause, Android scheduling behavior, big.LITTLE placement, thermal behavior, or device performance.
