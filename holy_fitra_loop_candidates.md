# Holy Fitra Brainstorm Loop — Candidate Selection

## Baseline

The current host baseline completed the device benchmark smoke run with 8/8 successful iterations, 12/12 Python ragged and dynamic-prefill tests, and the ragged scheduler integration test. The small fixture measured approximately 0.062 ms p50 and 0.110 ms p99, with 333,131 tokens/s. These values are host-only and are not Android performance claims.

## Candidates

| Candidate | Potential | Risk | Decision |
|---|---:|---:|---|
| Precompute and reuse execution-plan dispatch objects | High | Medium | Defer; current benchmark plan is already reused |
| Allocation-free ragged chunk execution | High | Low | **Selected** |
| Per-worker KV-page locality hints | High | Medium | Defer until physical-device cache data exists |
| Dynamic task sizing from measured work | High | Medium | Defer to next loop |
| Persistent JNI batch handles | High | Medium | Defer; requires Android lifecycle test |
| Fused Q/K/V projection plus ragged attention | Very high | High | Defer until projection layout is integrated |
| Thermal hysteresis and frequency feedback | High | Medium | Already represented; requires device sensors |

## Selected Optimization

The existing ragged scheduler bridge allocated a temporary `std::vector<int32_t>` of local offsets inside every worker task. The kernel does not require local offsets: global packed pointers and a pointer to the correct global offset subarray are already sufficient. The selected change removes that worker-side allocation and preserves global token coordinates.

## Gate

Retain only if all of the following pass:

1. Scalar output equivalence remains unchanged.
2. Ragged sequence isolation remains unchanged.
3. Scheduler completion and cancellation callbacks remain correct.
4. AddressSanitizer and UndefinedBehaviorSanitizer remain clean.
5. Host latency does not regress beyond measurement noise.
6. No task-path dynamic allocation remains for offset rebasing.
