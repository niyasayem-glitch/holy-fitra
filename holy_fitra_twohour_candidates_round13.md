# Breakthrough Round 13 — Unified Memory and Zero-Copy Tensor Ownership

The hardware-level Apple unified-memory controller cannot be created in a sandbox-only software project. The concrete software analogue is a shared aligned arena whose tensor views are used by training, inference, and native bridges without repeated allocation or copying.

| Rank | Candidate | Potential breakthrough | Risk | Decision |
|---:|---|---|---|---|
| 1 | Unified aligned tensor arena with zero-copy ndarray/Tensor views | One ownership domain for training, inference, and bridge buffers | Medium | **Selected** |
| 2 | Tensor copy-on-write ownership | Safe mutation without eager copies | Medium | Defer |
| 3 | Shared quantized/reconstructed weight arena | Cross-layer memory reuse | High | Defer |
| 4 | KV-cache arena with compaction | Less fragmentation | Medium | Defer |
| 5 | Lifetime-based activation planner | Reuse dead activation storage | High | Defer |
| 6 | Pinned host/device ABI descriptors | Faster Android bridge handoff | Medium | Defer |
| 7 | NUMA/unified-memory locality hints | Better multicore locality | High on sandbox | Defer |
| 8 | Read-only weight mapping | Prevents accidental training mutation | Low | Defer |
| 9 | Reference-counted tensor leases | Explicit lifetime safety | Medium | Defer |
| 10 | Memory pressure telemetry | Adaptive eviction decisions | Low | Defer |
| 11 | Zero-copy replay-buffer rows | Lower continual-learning copies | Medium | Defer |
| 12 | Slab allocator for tiny tensors | Lower allocator overhead | Low | Defer |
| 13 | Native C++ arena ABI | Android performance | High | Defer |
| 14 | DMA-buf/ION integration | Physical device sharing | High and device-dependent | Defer |
| 15 | Hardware coherent RAM integration | True Apple-style hardware behavior | Impossible in current sandbox | Reject |

## Selection and retention rule

Implement only the software-controllable layer: aligned shared storage, typed views, read-only/read-write ownership, release/coalescing, high-water metrics, and an optional zero-copy `Tensor` constructor. Retain only if aliasing is proven, mutation permissions are enforced, released blocks are reusable, and all existing tests remain green. Measurements must not be described as physical unified RAM.

## Round 13 implementation and evidence

Implemented `holyfitra_memory.py` with a 64-byte-aligned reusable byte arena, typed NumPy views, read-only/read-write ownership, zero-copy aliases, reference-counted physical allocation accounting, release/coalescing, high-water telemetry, and reuse counters. Added `Tensor.from_buffer()` as an opt-in zero-copy path while preserving copy-by-default Tensor construction.

The initial alias accounting was corrected so aliases do not double-count physical live bytes or prematurely return storage to the free list. Focused memory, Tensor, learning, RL, and quantization tests pass **46 tests**. The complete applicable suite passes **121 tests with 0 failures**. Termux-compatible host validation, AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler validation, and ASAN/UBSAN native gates all pass.

The x86-64 sandbox benchmark used a 1024×256 f32 view (1,048,576 bytes). An alias shared the same physical live-byte count before and after aliasing: 1,048,576 bytes. After release, the same arena storage was reused. The ordinary-copy loop measured 0.055424 ms over 100 constructions, while the current zero-copy view wrapper measured 0.132430 ms; therefore this round is retained for memory ownership and allocation reuse, not claimed as a CPU speedup. The software arena is an analogue of unified memory, not physical Apple-style coherent RAM.
