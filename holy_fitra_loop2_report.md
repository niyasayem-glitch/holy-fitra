# Holy Fitra Autonomous Improvement Loop 2

**Selected breakthrough:** Adaptive quadratic-work ragged task sizing  
**Status:** Retained after correctness and sanitizer gates.

## Problem

Fixed `sequences_per_task` values create uneven work when sequence lengths vary. Attention work grows approximately with the square of sequence length. A task containing one 192-token sequence can be much more expensive than a task containing four short sequences, even though both contain the same number of sequence IDs.

## Implementation

The scheduler now supports:

```cpp
plan.adaptive_chunking = true;
plan.target_work_per_task = 30000;
```

For each sequence, the scheduler estimates:

```text
sequence_work = length² × d_model
```

It groups consecutive sequences until the target work budget would be exceeded. A long sequence remains a valid singleton and can never be starved. Fixed-size chunking remains available for compatibility.

## Validation

| Gate | Result |
|---|---|
| Ragged numerical regression | Passed |
| Dynamic-prefill regression | 12/12 passed |
| Scheduler integration | Passed |
| Cancellation and completion | Passed |
| AddressSanitizer | Passed |
| UndefinedBehaviorSanitizer | Passed |
| Fixed-size compatibility | Passed |
| Adaptive variable-length benchmark | Completed |

## Measured Host Benchmark

The benchmark used sequence lengths:

```text
[2, 3, 4, 8, 16, 32, 48, 64, 96, 128, 160, 192]
```

| Mode | Mean completion time |
|---|---:|
| Fixed four sequences per task | 1.154 ms |
| Adaptive quadratic-work chunks | 0.587 ms |
| Observed improvement | approximately 49.1% lower |

This result is a host measurement for a small synthetic kernel workload. It demonstrates improved task balance but is not a Snapdragon or MediaTek performance claim.

## Why It Works

Fixed chunking can place the longest sequences together, creating a long-tail worker. Adaptive chunking gives work stealing tasks with more comparable quadratic cost. Big cores can receive large work through the existing placement policy, while little cores can process smaller tasks without waiting behind a single oversized chunk.

## Next Candidate

The next autonomous candidate is a **thermal-aware target-work controller**. When thermal state becomes warm or hot, the controller should reduce target work per task and increase little-core preference. When the device is normal and deadlines have slack, it can increase target work to reduce scheduler overhead. The controller must use hysteresis so it does not oscillate between policies.
