# Holy Fitra Proof-Carrying Execution Plan

**Breakthrough:** A deterministic execution plan that binds AI quality, kernel identity, precision, memory, energy, core policy, thermal state, deadline, fallback lineage, and runtime receipt into one verifiable artifact.  
**Author:** Manus AI  
**Status:** Host-validated Python prototype; native Android runtime integration path defined separately.

## Executive Summary

The new breakthrough is the **Proof-Carrying Execution Plan**. Holy Fitra no longer needs to choose quantization, kernel, scheduler policy, and resource behavior as disconnected runtime decisions. A `PlanCompiler` evaluates candidate kernels against calibration quality, ABI, memory, energy, thermal, core, priority, and deadline constraints. It emits a deterministic `ExecutionPlan` with a cryptographic identity and explicit fallback lineage.

Before execution, the plan verifies its digest and invariants. After execution, an `ExecutionReceipt` verifies that the runtime used the declared model, kernel, precision, core policy, quality bound, memory bound, and energy bound. A verified cache stores only plans whose identities and contents remain consistent.

This creates a shared contract between quantization, NibbleFlow, Android dispatch, and Holy Fitra’s safety model:

> **A fast path is not valid merely because it is fast. It is valid only when its quality, authority, resource, hardware, and provenance claims are all carried and verified together.**

## The Unification Gap

The earlier system could select an int4 or int8 kernel, schedule work on big or little cores, and validate model quality, but those choices were not yet one artifact. A later runtime change could theoretically use a different kernel or core preference than the calibration result assumed. The execution plan closes that gap.

| Decision | Previously separate | Now bound into plan |
|---|---|---|
| Precision | Quantization backend | `Precision` plus calibration MSE |
| Kernel | NibbleFlow dispatch | Kernel name and ABI |
| Quality | Calibration report | Proof hash and MSE gate |
| Memory | Runtime allocation | Declared memory bound |
| Energy | Scheduler estimate | Declared energy budget and receipt |
| Cores | Android dispatch | Big/little policy mapping |
| Thermal | Runtime policy | Thermal state in plan identity |
| Deadline | Scheduler task | Deadline in plan identity |
| Fallback | Implicit branch | Ordered fallback lineage |
| Cache | Generic artifact cache | Digest-verified plan cache |

## Plan Compilation

A plan is compiled from `KernelCandidate` records:

```python
KernelCandidate(
    name="nibbleflow.int8.neon",
    precision=Precision.INT8,
    abi_version=1,
    calibration_mse=0.006,
    max_mse=0.05,
    memory_bytes=17408,
    estimated_energy=1.2,
    proof_hash="proof-int8",
)
```

The compiler rejects a candidate if its ABI is incompatible, its proof is missing, its calibration error exceeds either the candidate gate or request gate, its memory exceeds the budget, its energy estimate exceeds the budget, its core policy is unavailable, or it is unsafe under critical thermal state.

The candidate order is deterministic. Therefore the same model hash, candidate list, constraints, and metadata produce the same plan ID. This makes plan compilation cacheable and suitable for reproducibility tests.

## Precision Fallback

The demo presents an int4 candidate with calibration MSE `0.08` against a gate of `0.05`, followed by int8 at `0.006`. The compiler refuses int4 and selects int8. This is an explicit quality-gated fallback rather than silent degradation.

```text
int4 candidate fails quality gate
  → int8 candidate passes quality, memory, energy, and ABI gates
  → emit int8 plan
  → carry remaining accepted candidates as fallback lineage
```

A production compiler should preserve rejected candidates in an audit record with the exact rejection reason, while keeping only valid alternatives in executable fallback lineage.

## Native Runtime Mapping

Every plan exposes stable fields for the integrated C runtime:

```json
{
  "core_class": 3,
  "priority": 3,
  "deadline_ns": 0
}
```

These map directly to the existing Holy Fitra runtime ABI:

| Plan value | Native ID |
|---|---:|
| `ANY` | 0 |
| `BIG_ONLY` | 1 |
| `LITTLE_ONLY` | 2 |
| `BIG_PREFERRED` | 3 |
| `LITTLE_PREFERRED` | 4 |

The plan compiler selects big-preferred for interactive and latency work under normal thermal state, and little-preferred under critical thermal state. The native runtime can therefore receive the plan’s verified fields rather than independently reconstructing policy.

## Execution Receipts

An `ExecutionReceipt` binds the actual run to the plan:

```text
plan ID
model hash
selected kernel
selected precision
selected core policy
measured MSE
measured memory
measured energy
success
execution timestamp
```

Receipt verification fails if the kernel changes, the model changes, the observed MSE exceeds the proof bound, memory exceeds the plan bound, energy exceeds the plan estimate, the selected core violates the policy, or the plan digest has been tampered with.

This enables post-run auditing and safe autonomous optimization. A new candidate can be retained only if it produces a valid receipt and passes regression gates.

## Verified Plan Cache

`VerifiedPlanCache` stores plans by their digest but re-verifies the plan on retrieval. If a cached plan is mutated after insertion, retrieval fails. This prevents a cache from turning a previously verified execution artifact into an unverified runtime decision.

Production cache keys should include the compiler version, device profile, kernel binary hash, model hash, calibration hash, and plan schema. The plan ID should be signed when it crosses a package or process boundary.

## Validation

The adversarial suite passed **9/9 tests**:

| Test | Result |
|---|---|
| Int4 quality-gate fallback to int8 | Passed |
| Deterministic plan digest | Passed |
| Plan tamper detection | Passed |
| Kernel identity receipt binding | Passed |
| Memory bound receipt verification | Passed |
| Energy bound receipt verification | Passed |
| Critical thermal big-only rejection | Passed |
| Resource-budget refusal | Passed |
| ABI mismatch refusal | Passed |
| Cache revalidation | Passed |
| Native request field mapping | Passed |

The demo selected `nibbleflow.int8.neon`, generated a stable plan ID, verified the cached plan, and validated its execution receipt.

## Integration with Holy Fitra

The execution plan should become a first-class HyperIR attribute:

```text
matvec
  inputs: x, packed_weights, scales
  execution_plan: plan_id
  proof: proof_hash
  effect: scheduler_request(core=big_preferred, priority=interactive)
```

The Android JNI layer should accept a plan manifest or plan ID rather than independently accepting arbitrary precision and core arguments. The runtime should look up the verified plan, map its native request fields, execute only the declared kernel, and emit a receipt.

The NibbleFlow package manifest should carry the plan schema, model hash, packed layout, kernel ABI, proof hash, and device constraints. The package loader should reject plans whose kernel binary or model hash no longer matches.

## Why This Is a Major Breakthrough

This mechanism turns performance optimization into a form of **verifiable compilation**. A faster kernel cannot silently replace a slower one. A smaller quantization profile cannot silently cross an accuracy gate. A hot-device fallback cannot silently violate a core policy. An autonomous optimizer can propose candidates, but it can retain only plans whose proof, receipt, resource use, and regression record all pass.

The same plan system can govern:

| Holy Fitra operation | Plan payload |
|---|---|
| NibbleFlow matvec | Precision, packed layout, kernel ABI, core policy |
| Transformer decode | KV-cache mode, draft length, thermal profile |
| Speculative decoding | Draft/target plan, acceptance gate, cache transaction |
| Model memory | Retention, privacy, evidence, energy budget |
| Tool action | Capability, consent, deadline, reversible receipt |
| Package update | Artifact hashes, proof dependencies, rollback lineage |

## Production Boundaries

The current plan compiler is a Python prototype. It does not yet sign manifests, measure energy on Android, prove calibration mathematically, or enforce native kernel identity at the C ABI boundary. Those are the next hardening tasks.

A plan’s energy estimate is currently a declared candidate property; physical Android deployment must measure energy and thermal response. A calibration MSE is not a complete task-quality guarantee; production gates should include task-level perplexity, exact-match, or application-specific quality metrics.

The native runtime must also accept and verify a serialized plan ID before execution. Until that integration is complete, the current native API remains more permissive than the proof-carrying design described here.

## Next Implementation Order

1. Add a plan-manifest parser and signature verifier to the C++ runtime.
2. Require a verified plan ID in `hf_runtime_submit_matvec`.
3. Bind the NibbleFlow kernel binary hash and ABI to the plan.
4. Record runtime receipts in the Holy Fitra replay chain.
5. Add physical Android energy and thermal measurements.
6. Let autonomous optimization retain only receipt-verified plans.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[3]: https://llvm.org/docs/LangRef.html "LLVM Language Reference Manual"
[4]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
