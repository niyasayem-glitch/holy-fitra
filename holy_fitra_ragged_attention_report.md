# Holy Fitra True Ragged ARM64 Attention

**Feature:** Padding-free causal attention kernels using packed sequences and offset-driven traversal.  
**Status:** Host numerical validation and AArch64 NEON/SVE object generation completed; physical Android execution remains pending.

## Executive Summary

True ragged attention removes padding from the attention inner loop by storing all sequences contiguously and using CSR-style offsets to define sequence boundaries. Every query row traverses only its own causal key range:

```text
sequence_start ≤ key ≤ query_row
```

There is no padded sequence dimension, no batch-wide maximum length in the inner loop, and no cross-sequence attention. The implementation uses an online softmax so it does not need a per-row score buffer. This makes the kernel suitable for dynamic transformer prefill after Holy Fitra’s packed micro-batch stage.

Validation passed four Python ragged-attention tests, host C numerical equivalence, AArch64 NEON object emission, and AArch64 SVE object emission.

## 1. ABI

The native ABI is:

```c
typedef struct hf_ragged_attention_batch {
    const float *q;
    const float *k;
    const float *v;
    float *output;
    const int32_t *offsets;
    int32_t sequence_count;
    int32_t d_model;
} hf_ragged_attention_batch;
```

The packed Q, K, V, and output arrays have shape:

```text
[total_tokens, d_model]
```

The offsets array has length `sequence_count + 1`:

```text
offsets[0] = 0
offsets[i + 1] > offsets[i]
offsets[sequence_count] = total_tokens
```

Sequence `s` occupies the half-open range:

```text
[offsets[s], offsets[s + 1])
```

The ABI intentionally has no padded length field. A padded length is not needed by the kernel and would encourage accidental padding-dependent logic.

## 2. Causal Traversal

For sequence `s`, the kernel loads:

```c
start = offsets[s];
end = offsets[s + 1];

for (row = start; row < end; ++row) {
    for (key = start; key <= row; ++key) {
        // causal attention
    }
}
```

This gives each sequence independent causal attention. A token in one request can never attend to another request, even when the two requests are adjacent in packed memory.

The total attention work is:

```text
Σ sequence_length² × d_model
```

rather than:

```text
batch_size × padded_max_length² × d_model
```

## 3. Online Softmax

A conventional implementation computes and stores all scores for a row before applying softmax. The ragged kernel instead uses online softmax state:

```text
m = running maximum score
s = running normalization sum
acc[d] = running weighted value accumulator
```

For each causal key score `x`, it updates:

```text
new_m = max(m, x)
old_factor = exp(m - new_m)
new_factor = exp(x - new_m)
acc = acc × old_factor + value × new_factor
s = s × old_factor + new_factor
m = new_m
```

The output is `acc / s`. This avoids a score scratch buffer and keeps the kernel’s memory traffic focused on Q, K, V, and output.

## 4. NEON Implementation

The NEON path uses four float lanes for:

- Q/K dot products.
- Value accumulation.
- Online-softmax rescaling.
- Final normalization.

The key traversal remains scalar over real causal keys, but the hidden dimension is vectorized in four-float chunks. Tail dimensions are handled by a scalar remainder loop. No token padding is inserted to satisfy the vector width.

This is the correct first ARM64 implementation because it preserves exact offsets and makes tail behavior obvious. Later tuning can use multiple query rows per tile or packed K/V tiles when profiling demonstrates a benefit.

## 5. SVE Implementation

The SVE path uses vector-length-agnostic predicates:

```c
svbool_t pg = svwhilelt_b32(index, d_model);
```

It advances by `svcntw()` and masks the final hidden-dimension iteration. This avoids assuming a fixed SVE vector width and allows the same source to target devices with different SVE widths.

The SVE path must still be compiled and dispatched only when the device exposes SVE. A binary must not execute SVE instructions on a NEON-only Android CPU.

## 6. Runtime Dispatch

Holy Fitra should dispatch according to verified device and plan metadata:

| Condition | Kernel |
|---|---|
| SVE available and layout compatible | `holy_fitra_ragged_attention_sve` |
| NEON available and layout compatible | `holy_fitra_ragged_attention_neon` |
| Otherwise | `holy_fitra_ragged_attention_scalar` |

The plan identity should include:

```text
model hash
layout hash
d_model
precision
ABI version
NEON/SVE feature mask
thermal profile
```

A cached SVE plan must never be reused on a NEON-only device.

## 7. Validation Results

| Validation | Result |
|---|---|
| Ragged sequence isolation | Passed |
| Causal boundary semantics | Passed |
| No-padding work accounting | Passed |
| Malformed offsets rejection | Passed |
| Dispatch priority | Passed |
| Python regression suite | **4/4 passed** |
| Host C scalar error | `2.98e-7` maximum |
| Host NEON entry error | `2.98e-7` maximum; host fallback path |
| AArch64 NEON object | Emitted successfully |
| AArch64 SVE object | Emitted successfully |

The test fixture used six sequences with lengths `[1, 2, 5, 8, 13, 17]` and 46 total tokens. The emitted AArch64 objects were ELF64 relocatables with the expected scalar, NEON, and SVE symbols.

## 8. Android Integration

The JNI layer should pass direct buffers for Q, K, V, output, and offsets. Native validation must check:

1. Every pointer is non-null.
2. `sequence_count` and `d_model` are positive.
3. Offsets are monotonic and within the packed token count.
4. The final offset equals the supplied total-token count.
5. Byte-capacity multiplication cannot overflow.
6. The plan’s ABI and CPU feature mask match the current device.
7. The KV-cache lease generation matches the request.

The best Android memory layout is packed token-major Q/K/V for initial deployment. A later kernel-specific layout may tile the hidden dimension or interleave K/V, but that layout must be represented explicitly in the plan identity.

## 9. Performance Strategy

The ragged kernel removes padding work, but it does not guarantee that every batch is faster. Very short sequences can be dominated by function-call and softmax overhead. A production policy should compare:

```text
ragged work = Σ Lᵢ² × d_model
padded work = B × max(Lᵢ)² × d_model
```

and include calibrated launch, synchronization, and cache-locality costs. Ragged execution is most valuable when sequence lengths vary significantly or when padding waste is high.

For Android, the next optimization stages are:

| Stage | Goal |
|---|---|
| 1 | Benchmark NEON and SVE on physical devices |
| 2 | Add two-query or four-query output tiling |
| 3 | Add K/V cache-page locality grouping |
| 4 | Fuse Q/K/V projection with ragged attention where layouts permit |
| 5 | Add deadline-aware ragged micro-batch splitting |
| 6 | Add int8/int4 K/V variants with proof-carrying accuracy gates |

## 10. Production Boundaries

The sandbox validates scalar numerical correctness and confirms that both AArch64 object paths compile. It does not execute the NEON or SVE objects on ARM64 hardware. Physical Android validation must measure p50/p95/p99 latency, energy per token, thermal throttling, SVE availability, memory bandwidth, and behavior under cancellation.

## References

[1]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
[2]: https://developer.arm.com/documentation/102476/latest "Arm Scalable Vector Extension"
[3]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[4]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
