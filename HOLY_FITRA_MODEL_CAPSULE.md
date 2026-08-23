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

`load_deployment()` currently reconstructs the full compact MLP deployment in memory because the current Python reference runtime needs both dense layers. The chunk iterator is the compatible bridge for future native per-layer and streaming runtimes; it does not yet make MLP inference out-of-core.

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
)
```

The export rejects an inconsistent pipeline result, a changed deployment file, an incompatible resource contract, unsupported chunk sizing, noncanonical metadata, and a too-small signing key. The loader rejects bad magic, invalid index authentication, overlapping or noncanonical chunks, missing required metadata chunks, truncated payloads, and digest mismatch.

## Tensor/resource foundation

`holyfitra_tensor_contracts.py` defines `TensorContract` and `TensorResourceContract`. A contract names tensor shape, dtype, layout, device, ownership mode, memory budget, optional latency deadline, optional energy budget, and required kernel ABI. It verifies an `ExecutionPlan` before it can be included in a capsule.

This is a compiler-facing semantic foundation. It is not a claim that the current scalar LLVM backend lowers these contracts into native tensor instructions yet.

## Validation

The regression suite verifies deterministic capsule output, lazy cache bounds, streamed chunk order, wrong-key rejection, lazy tamper rejection, deployment round trip, execution-plan identity, agent receipt identity, and resource-plan compatibility.
