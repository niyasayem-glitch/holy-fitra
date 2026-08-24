# Adapter Residency Lanes

## Purpose and boundary

This wave adds a deterministic contract for selecting compact adapter payloads alongside an immutable signed base deployment. It does **not** execute a new adapter in the native Android kernel, claim device-memory savings, or claim quality improvement. The initial result is a verified capsule format and host-side residency ledger that a future JNI/runtime path can consume.

## Contract layers

| Layer | Responsibility | Fail-closed rule |
|---|---|---|
| Adapter artifact | Binds an adapter ID, base deployment digest, payload digest, byte size, target dimensions, rank, alpha, and mode | Any identity, dimensions, payload-size, or base mismatch rejects the artifact. |
| Residency policy | Declares maximum resident bytes, maximum adapters, maximum active lanes, age limit, and allowed modes | The policy must be bounded, canonical, and bound to the exact base deployment digest. |
| Residency ledger | Admits, touches, activates, deactivates, evicts, and rolls back artifacts deterministically | Protected or active artifacts cannot be evicted; every post-operation state stays within policy limits. |
| Receipt | Captures resident ordering, active lane order, policy ID, and deterministic receipt ID | A receipt is an audit artifact, never proof of physical mobile execution. |
| Capsule binding | Authenticates policy, catalog, and individual adapter payload chunks through the existing signed capsule index | Optional data preserves compatibility with earlier capsule versions. |

## Residency semantics

The ledger uses least-recently-used eviction only for inactive and unprotected adapters. Activating an adapter requires it to be resident; it is then placed in a deterministic activation order. A rollback discards the requested active lane and restores the previous active tuple only when every prior artifact is still resident. Admission, activation, deactivation, and rollback return structured decisions containing an action, reason, evictions, active lanes, and final resource state.

An adapter catalog is bound to a single base deployment digest. The payload digest is checked before a capsule exposes the artifact, so a catalog cannot silently point to a different payload. Adapters are metadata-only at this stage: their declared low-rank dimensions and byte budgets are checked, but no claim is made that the current streamed MLP or Android kernel applies them.

## Acceptance gates

1. Canonical policy/artifact round trips and malformed-input rejection.
2. Deterministic admission, LRU eviction, protection, activation limits, and rollback tests.
3. Authenticated capsule export/open/tamper checks for policy, catalog, and payload chunks.
4. Full Termux-compatible native/regression suite, strict diff checks, remote validation, and Android package workflow.
