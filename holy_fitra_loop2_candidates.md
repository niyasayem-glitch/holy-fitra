# Holy Fitra Autonomous Loop 2

## Baseline

The retained allocation-free global-offset path passed the ragged, dynamic-prefill, and scheduler tests. The latest host smoke run measured p50 `0.0411 ms`, p99 `0.0766 ms`, and `492,062 tokens/s` for the small fixture. Because the fixture is short and host scheduling is noisy, the next candidate is evaluated primarily by correctness, task balance, and repeated-run behavior.

## Candidate Ranking

| Candidate | Expected impact | Risk | Decision |
|---|---:|---:|---|
| Work-estimate-based task sizing | High on variable lengths | Low | **Selected** |
| KV-page locality hints | High on real devices | Medium | Defer |
| Persistent JNI benchmark handle | High across JNI calls | Medium | Defer |
| Fused projection plus ragged attention | Very high | High | Defer |
| Frequency-aware chunk resizing | High under throttling | Medium | Defer |

## Gate

The selected candidate must preserve exact output, cancellation completion, scheduler shutdown, sanitizer cleanliness, and fixed-size behavior. Adaptive mode must never create an empty chunk or starve a long sequence.
