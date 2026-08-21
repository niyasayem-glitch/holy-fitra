# Holy Fitra Dynamic Transformer Prefill

**Feature:** Packed variable-length prefill with bucketed micro-batches and adaptive fused/scalar execution.  
**Author:** Manus AI  
**Status:** Host-validated NumPy prototype; Android ARM64 kernel integration remains the next deployment step.

## Executive Summary

The fused batch mechanism now supports dynamic transformer prefill without forcing every request to use the same sequence length. Holy Fitra packs variable-length sequences into length buckets, stores tokens contiguously, records exact offsets and lengths, enforces token and sequence budgets, assigns non-overlapping KV-cache leases, and chooses between fused padded attention and scalar execution using an adaptive cost policy.

The implementation preserves the key invariant:

```text
packed_prefill(requests) == independent_prefill(request) for every request
```

The test suite passed **8/8 tests** with maximum batched-versus-single output error of `2.38e-7` in the demo fixture.

## 1. Packed Sequence Representation

A `PackedMicroBatch` contains:

| Field | Meaning |
|---|---|
| `tokens` | One contiguous `[total_tokens, d_model]` array |
| `offsets` | Prefix offsets with length `batch_size + 1` |
| `lengths` | Exact sequence lengths |
| `padded_length` | Maximum length used by padded fused attention |
| `bucket_id` | Ceiling length bucket identifier |
| `deadline_ns` | Earliest deadline among member requests |
| `digest` | Stable identity of request IDs and token bytes |
| `kv_leases` | Per-sequence reserved cache ranges |

For request lengths `[3, 7, 9]`, packed storage uses:

```text
offsets = [0, 3, 10, 19]
lengths = [3, 7, 9]
tokens  = [request0 tokens][request1 tokens][request2 tokens]
```

No sequence is reconstructed by scanning padding. The offsets are sufficient to recover each original sequence exactly.

## 2. Bucketed Micro-Batching

Requests are sorted by length bucket, priority, and deadline. A bucket is defined by:

```text
bucket_id = ceil(sequence_length / bucket_width)
```

The packer flushes a micro-batch when any condition occurs:

1. A new request belongs to a different length bucket.
2. The sequence-count limit is reached.
3. The actual token budget would be exceeded.

A single sequence longer than the token budget is allowed as an oversized singleton so it can make progress instead of being permanently rejected. This behavior is explicit and test-covered.

## 3. Adaptive Fused or Scalar Execution

Padding-free packing and padded fused attention have different costs. Fusing every request is not always optimal, especially when lengths differ widely. `AdaptivePrefillPolicy` estimates:

```text
scalar work = sum(length_i²) + scalar_launch_cost × batch_size
fused work  = batch_size × padded_length² + fused_launch_cost
```

It chooses fused execution only when:

- The batch contains enough sequences.
- Padding overhead is below the configured maximum.
- Estimated fused work is lower than scalar work.

The launch costs are calibration parameters. On Android, they should be measured per model, kernel, and device profile rather than treated as universal constants.

## 4. Transformer Attention Semantics

The prototype uses causal self-attention. The fused path constructs padded `[batch, padded_length, d_model]` tensors and applies two masks:

```text
causal mask: future positions are invisible
valid-key mask: padding cannot be attended to
valid-query mask: padded query rows produce zero output
```

The scalar and fused outputs are compared only over each request’s real length. Padded rows are never exposed as model output.

## 5. KV-Cache Ownership

Each request receives a `KVLease`:

```text
(request_id, start_token, length, generation)
```

The `KVPagePool` guarantees that active leases do not overlap and rejects allocations that exceed capacity. When all leases are released, the pool resets its used cursor and advances its generation. The generation helps detect stale cache ownership in a production implementation.

For a real transformer, each lease should map to pages containing K/V tensors rather than only token ranges. The same ownership model still applies:

```text
request → page range → batch row → transformer layer writes
```

## 6. Cancellation and Deadlines

Cancelled or expired requests are rejected during packing. A packed batch carries the earliest member deadline. Before execution, the scheduler can reject the whole batch if its deadline is already missed. During execution, the batch should be split at cancellation boundaries or use a per-sequence active mask when the backend supports it.

The safe policy is:

| Condition | Action |
|---|---|
| Cancelled before packing | Reject request |
| Deadline expired before packing | Reject request |
| Cancelled before execution | Exclude request from batch |
| Cancelled during fused execution | Stop at the next sequence boundary |
| Interactive deadline near | Prefer smaller micro-batch |
| Thermal critical | Reduce token budget and prefer scalar/smaller fused batches |

## 7. Validation Results

The dynamic prefill suite passed eight tests:

| Test | Result |
|---|---|
| Exact packed offsets | Passed |
| Token and sequence limits | Passed |
| Exact causal-attention differential output | Passed |
| Non-overlapping KV leases | Passed |
| KV lease reuse after release | Passed |
| Cancelled request rejection | Passed |
| Expired request rejection | Passed |
| Invalid dtype and capacity rejection | Passed |
| Adaptive padding-aware policy | Passed |

The demo processed six variable-length sequences in four micro-batches with maximum error `2.38e-7` and 71 active KV tokens.

## 8. Host Benchmark Interpretation

A host Python benchmark with 96 random sequences of lengths 8–63 produced:

```text
sequences: 96
batches: 10
total tokens: 3504
padded tokens: 3808
padding ratio: 1.0868
maximum error: 8.34e-7
```

The NumPy fused implementation measured 7.76 ms versus 5.61 ms for the scalar fixture. This is not a failure of the architecture; it demonstrates that the adaptive policy must be calibrated to actual backend launch and matrix costs. The Python implementation’s vectorization and memory behavior differ from an Android ARM64 fused kernel.

The architecture therefore does not claim that every dynamic batch is faster. It claims that Holy Fitra can choose the path using measured cost profiles rather than blindly padding or blindly serializing.

## 9. Android ARM64 Integration

The next native API should carry packed metadata alongside a contiguous activation buffer:

```c
struct hf_prefill_batch {
    const float *tokens;
    const int32_t *offsets;
    const int32_t *lengths;
    size_t sequence_count;
    size_t total_tokens;
    size_t d_model;
    uint64_t deadline_ns;
    uint64_t plan_id_hash;
};
```

The Android JNI layer should use direct buffers for tokens, offsets, lengths, and output. The native runtime should validate monotonic offsets, `offsets[0] == 0`, `offsets[last] == total_tokens`, exact length agreement, and byte-capacity multiplication before scheduling.

On ARM64, the best production design is likely a hybrid:

```text
packed token storage for memory and transfer efficiency
+ bucket-local tiled kernels for compute
+ page-based KV cache leases
+ adaptive micro-batch splitting for deadlines
```

## 10. Further Breakthrough Opportunities

The next optimization is **deadline-aware continuous batching**. Instead of packing only once, Holy Fitra can maintain a short queueing window, admit compatible requests, and close a micro-batch when either the token budget or deadline slack is exhausted.

A second optimization is **ragged attention without padding**. Bucketed padding is simple and portable, but a true ragged kernel can use offsets directly and avoid padded query/key/value storage. That requires more complex kernel scheduling and careful causal-mask indexing.

A third optimization is **KV-page-aware batching**. The scheduler can group requests whose KV pages are physically nearby, improving cache locality and reducing TLB pressure while respecting privacy and request ownership.

## Production Boundaries

The current prototype validates algorithmic packing and exactness on the host. It does not yet execute a full Android transformer, use a physical KV-page allocator, or measure ARM64 thermal and memory-bandwidth behavior. Device deployment must validate p50/p95/p99 prefill latency, memory overhead from padding, cache-page locality, energy per prompt token, and cancellation latency.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[3]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
[4]: https://docs.oracle.com/en/java/javase/17/docs/specs/jni/functions.html "Java Native Interface Functions"
