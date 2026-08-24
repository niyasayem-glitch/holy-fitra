# Holy Fitra Model Capsule v1

## Purpose

`holyfitra_model_capsule.py` packages a verified AI pipeline result into one authenticated, content-addressed artifact. A capsule binds an authenticated deployment payload to its canonical execution plan, pipeline receipt, optional tensor/resource contract, and optional local agent-plan receipt.

The capsule is an integration format. It does not claim that the scalar Holy Fitra compiler executes tensors natively or that an Android device has run the capsule.

## Format and trust model

The file begins with a fixed magic value, a canonical JSON index, and an HMAC-SHA-256 tag over that index. The index contains deterministic chunk names, offsets, lengths, and SHA-256 digests. Every payload chunk is verified when it is read.

| Chunk | Required | Meaning |
|---|---:|---|
| `deployment/000000` and later ordered chunks | Yes | Authenticated v2 `.hfbin` deployment payload split into bounded pieces |
| `execution_plan.json` | Yes | Canonical verified execution plan bound to the deployment digest |
| `pipeline_receipt.json` | Yes | Dataset, evaluation, lineage, deployment, and plan identity receipt |
| `resource_contract.json` | No | Canonical tensor shape/dtype/layout/ownership/device/resource contract |
| `agent_receipt.json` | No | Typed local approval, capability, evidence, budget, and zero-side-effect receipt |

The capsule uses a local symmetric HMAC key. It is appropriate for a controlled development boundary where exporter and loader share a protected key. A production distribution boundary still needs public-key signatures, key rotation, revocation, and a registry policy.

## Lazy and chunked behavior

Opening a capsule authenticates only the bounded index. It does not read the deployment chunks. `read_chunk(name)` verifies and caches one requested chunk; `iter_deployment_chunks()` yields verified deployment chunks in canonical order with a bounded LRU cache. Metadata, plan, resource, and agent receipts can therefore be inspected before weight payloads are loaded.

```python
from holyfitra_model_capsule import open_model_capsule

capsule = open_model_capsule("model.hfcaps", signing_key=capsule_key, cache_chunks=4)
plan = capsule.execution_plan_json()                 # loads only plan metadata
for payload in capsule.iter_deployment_chunks():     # verified streaming chunks
    native_runtime.consume(payload)
```

When an exporter supplies both the authenticated deployment key and `stream_block_columns`, the capsule also contains a canonical `holyfitra.layer-stream/v1` index. `open_streamed_mlp()` evaluates the compact two-layer MLP by reading only the current float32 weight block and its bias from authenticated `stream/` chunks. It never calls `deployment_bytes()` or rebuilds the legacy deployment payload. Its cache remains bounded by `cache_chunks` and it validates finite bounded inputs, canonical layer names, canonical block coverage, per-block byte contracts, and the binding between stream and deployment digest.

```python
stream = capsule.open_streamed_mlp()
output = stream.predict(inputs)  # hidden blocks → ReLU → output blocks
```

The streamed evaluator defaults to the host NumPy reference backend for its block math. A caller may explicitly provide `holyfitra_streamed_native.StreamedNativeKernel` to `open_streamed_mlp(native_kernel=...)`; this bridge invokes a bounded C ABI once for each authenticated float32 weight block and keeps loading, digest verification, cache bounds, and bias/activation processing in the capsule layer. `backend_name` reports `numpy-reference`, `native-scalar`, or `native-neon` according to the library actually loaded on the executing host.

| Native ABI property | Contract |
|---|---|
| Entry point | `hf_streamed_f32_block_matvec` accepts one contiguous float32 input row and one row-major `[rows, columns]` weight block. |
| Bounds | It rejects null buffers, wrong ABI versions, short buffers, non-finite values, `rows > 8192`, and `columns > 512`. |
| Portable behavior | Non-AArch64 builds use a scalar reference loop with the same ABI and status codes. |
| ARM64 behavior | The guarded AArch64 path accumulates four output columns with NEON loads and fused multiply-add instructions, then handles remaining columns scalarly. |

The source is part of the Android CMake runtime and the canonical native gate builds its host C regression, runs address/undefined-behavior sanitizer checks during development validation, and cross-compiles an Android ARM64 object. The current evidence is host numerical equivalence plus an AArch64 object/assembly inspection that shows the emitted NEON instructions. It is **not** a measurement of device latency, throughput, thermal behavior, JNI integration, or correctness on a physical ARM64 device.

The Android runtime now exposes `HolyFitraRuntime.streamedBlockMatmul(...)` for one direct-buffer float32 block row. It verifies directness and Kotlin-side capacity bounds before JNI repeats direct-buffer alignment/capacity validation and calls either the explicit scalar baseline or runtime-selected NEON path. This is a direct block primitive for a caller that already controls authenticated capsule loading; it does not move HMAC verification or stream-index trust decisions into JNI.

## Export example

```python
from holyfitra_model_capsule import export_pipeline_capsule

capsule = export_pipeline_capsule(
    verified_pipeline_result,
    "build/model.hfcaps",
    signing_key=capsule_key,
    chunk_bytes=65_536,
    resource_contract=resource_contract,
    agent_receipt=agent_receipt,
    deployment_signing_key=deployment_key,
    stream_block_columns=64,
)
```

The export rejects an inconsistent pipeline result, a changed deployment file, an incompatible resource contract, unsupported chunk sizing, noncanonical metadata, and a too-small signing key. The loader rejects bad magic, invalid index authentication, overlapping or noncanonical chunks, missing required metadata chunks, truncated payloads, and digest mismatch.

## Tensor/resource foundation

`holyfitra_tensor_contracts.py` defines `TensorContract` and `TensorResourceContract`. A contract names tensor shape, dtype, layout, device, ownership mode, memory budget, optional latency deadline, optional energy budget, and required kernel ABI. It verifies an `ExecutionPlan` before it can be included in a capsule.

This is a compiler-facing semantic foundation. It is not a claim that the current scalar LLVM backend lowers these contracts into native tensor instructions yet.

## Validation

The regression suite verifies deterministic capsule output, lazy cache bounds, streamed chunk order, wrong-key rejection, lazy tamper rejection, deployment round trip, execution-plan identity, agent receipt identity, resource-plan compatibility, optional native-scalar/NumPy streamed-output equivalence, and native rejection of invalid input/buffer/shape conditions.
