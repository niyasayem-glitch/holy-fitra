# Breakthrough Round 14 — Cache-Aware Training/Inference Memory Sharing

Round 13 established one reusable arena. Round 14 extends it into a content-addressed shared tensor pool: identical read-only inference weights share one physical arena allocation, while training obtains an explicit writable materialization rather than silently mutating shared inference state.

| Rank | Candidate | Potential breakthrough | Risk | Decision |
|---:|---|---|---|---|
| 1 | Content-addressed shared tensor pool with copy-on-write training boundary | Deduplicates identical weights across inference layers and sessions | Medium | **Selected** |
| 2 | Shared quantized reconstruction cache across matrices | Lower repeated weight footprint | High integration risk | Defer |
| 3 | Replay buffer backed by unified arena | Removes continual-learning row copies | Medium | Defer |
| 4 | Shared optimizer master weights | Training/inference parameter reuse | High mutation risk | Defer |
| 5 | Activation cache interning | Cross-request reuse | High correctness risk | Defer |
| 6 | Digest-keyed KV cache pages | Duplicate prefix reuse | Medium | Defer |
| 7 | Copy-on-write model snapshots | Cheap evaluation checkpoints | Medium | Defer |
| 8 | Weight residency leases | Memory-pressure eviction | Medium | Defer |
| 9 | F16/F32 shared conversion cache | Reduce duplicate precision buffers | Medium | Defer |
| 10 | Parameter slab packing | Fewer small allocations | Low/medium | Defer |
| 11 | Shared read-only Android JNI buffers | Lower bridge copies | Medium | Defer |
| 12 | Shared arena-backed calibration data | Lower calibration footprint | Low | Defer |
| 13 | Cross-process shared memory | Multi-worker inference | High and platform-specific | Defer |
| 14 | Hardware page-table sharing | True unified memory behavior | Not available in sandbox | Reject |
| 15 | Automatic mutable aliasing | Maximum apparent reuse | Unsafe and violates ownership | Reject |

## Retention rule

Retain only if identical arrays share physical bytes, mutable training materialization is isolated, read-only ownership is enforced, pool accounting remains correct after release, and all existing regression/native/Termux gates pass. This is software cache sharing, not hardware unified RAM.

## Round 14 implementation and evidence

Implemented `holyfitra_tensor_pool.py`, a content-addressed shared tensor pool backed by the round 13 arena. Identical read-only inference tensors share one physical allocation. A training caller must use `materialize_for_training()`, which returns an isolated writable copy and leaves inference bytes unchanged. Explicit key collisions are rejected, and all handles release through the pool’s reference-counted arena accounting.

The focused round 14 suite passes **5 tests**; the complete applicable suite passes **126 tests with 0 failures**. Termux-compatible host validation, AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler validation, and ASAN/UBSAN native gates pass.

For a 1024×256 f32 weight (1,048,576 bytes), two identical inference handles had physical bytes 1,048,576 and logical bytes 2,097,152, deduplicating 1,048,576 bytes. The training materialization was 1,048,576 bytes and mutating it did not change inference data. After all handles were released, the arena returned to zero live bytes.

## Round 14 retention decision

Retain the shared tensor pool. It provides software unified-memory sharing between inference sessions while making the training mutation boundary explicit and safe. It is a memory-footprint breakthrough, not a CPU-speed claim or hardware unified-RAM implementation.
