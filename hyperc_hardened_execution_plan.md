# HyperC Hardened Execution Plan

**Author:** Manus AI  
**Status:** Engineering baseline for the next implementation cycle  
**Scope:** Compiler, HyperIR, AI runtime, quantization, Android deployment, safety, reproducibility, and optimization governance.

## 1. Hardened Mission

HyperC should become an **AI-native, ahead-of-time compiled systems language** whose performance features are subordinate to explicit correctness and safety contracts. The project must not optimize an invalid graph, silently degrade model quality, claim Android performance from x86-64 measurements, or allow model-generated text to acquire authority merely because it resembles an instruction.

The project is therefore governed by one rule:

> **No optimization, deployment artifact, or benchmark claim is retained unless its preconditions, evidence, and rollback path are explicit.**

The implementation target is not “maximum features.” It is a compiler/runtime where every important transformation has a typed contract, a measurable budget, a deterministic validation procedure, and a safe failure mode.

## 2. Current-State Audit

The existing prototype is strong enough to serve as a research foundation, but several contracts are still advisory rather than production-hard.

| Area | Current capability | Failure mode that must be closed |
|---|---|---|
| HyperIR | Tensor, effect, evidence, cache, and quantization prototypes | SSA ownership, symbolic shape unification, effect ordering, and manifest signatures are incomplete |
| Quantization | int4/int8/f16 selection with calibration MSE gates | Proof does not yet bind weights, kernel binary, evaluator version, task corpus, or hardware target |
| Evidence | Prediction/Claim/Fact types | Structural flow is not enough; provenance, freshness, contradiction, verifier identity, and explicit upgrade evidence are required |
| Capabilities | Scoped allow/deny policy | Path canonicalization, symlink traversal, confused-deputy prevention, process isolation, and approval replay are missing |
| KV cache | Transactional begin/append/commit/rollback | Transaction identity, ownership, page checksums, concurrent access, cancellation, and stale-handle rejection are incomplete |
| Speculation | Exact greedy prototype and sampling path | Distributional equivalence, RNG reproducibility, repaired-token accounting, and adaptive-policy hysteresis need stronger gates |
| Native lowering | LLVM and AArch64 object emission | Generated objects are not proof of device execution, ABI compatibility, timing, or thermal behavior |
| Optimization loop | Candidate retention with regression gates | Baselines, statistical confidence, artifact provenance, and automatic rollback need to be mandatory |
| Benchmarking | x86-64 simulation and cross-backend comparison | Measurements can be misread as Android claims; workload, compiler flags, thermal state, and variance need formal records |

## 3. Non-Negotiable Invariants

### 3.1 Compiler and IR invariants

Every value must have a unique definition, every use must dominate that definition, and every operation must declare its input, output, shape, layout, device, precision, memory effect, and failure behavior. A graph with unresolved symbolic dimensions may be represented during parsing but must not reach native lowering without a resolved specialization or an explicit runtime-check plan.

An optimization may not change observable numerical behavior outside its declared tolerance. The tolerance must be attached to the operation or proof certificate rather than hidden in a test script. Integer overflow, NaN handling, signed-zero behavior, aliasing, and out-of-bounds access must each have defined semantics.

### 3.2 Quantization invariants

A quantization manifest must bind the exact weight fingerprint, calibration-data fingerprint, calibration algorithm and version, evaluator version, selected precision, group layout, kernel fingerprint, target device features, and quality thresholds. A proof is invalid if any bound input changes.

The compiler must reject a candidate when a layer gate, task gate, safety gate, or kernel compatibility gate fails. It may promote int4 to int8 or float16, but it may not silently lower the gate. A task-quality gate must report confidence intervals when the evaluation corpus is finite; a single favorable sample is not sufficient for release.

### 3.3 Cache and speculation invariants

A cache transaction must have a unique nonce, owner, parent version, capacity reservation, and terminal state. Append, commit, and rollback operations must reject stale or foreign transaction handles. A committed cache must contain exactly the tokens visible to the caller, never speculative tokens that were not returned.

Greedy speculation must be exactly equivalent to target-only decoding under the declared tokenizer, numerical mode, and tie-breaking rule. Sampling speculation must be validated against the target distribution using a reproducible statistical test suite, not only example outputs. On cancellation, exception, memory pressure, or thermal abort, the cache must return to the last committed version.

### 3.4 Safety and evidence invariants

Model output is data by default. It cannot grant capabilities, change policy, approve an action, or redefine a verifier. Tool execution requires a capability issued outside the model output, a canonicalized scope, provenance, an audit identifier, and an approval rule appropriate to the risk level.

An evidence upgrade must require an explicit verifier operation. The result must include source identity, retrieval time, content hash, verifier version, and contradiction status. A `Fact` cannot be created merely by relabeling a `Prediction`.

### 3.5 Reproducibility invariants

Every benchmark and optimization candidate must record source commit, compiler version, flags, hardware identity, operating-system version, dependency lockfile, model hash, seed, input corpus hash, thermal state, warmup policy, and statistical summary. A result without provenance may be used for exploration but cannot be used for retention or a public performance claim.

## 4. Threat Model

HyperC must explicitly defend against malformed source, malicious model files, poisoned calibration data, prompt injection, unauthorized tool calls, corrupted memory-mapped pages, stale cache handles, compiler miscompilation, resource exhaustion, thermal oscillation, and misleading benchmarks.

The trusted computing base should be kept small. The parser, type checker, proof verifier, capability broker, manifest verifier, and runtime memory manager are trusted. Model weights, prompts, calibration corpora, generated tool arguments, plugins, and downloaded kernels are untrusted until verified.

| Threat | Required defense | Failure behavior |
|---|---|---|
| Malformed or adversarial source | Parser fuzzing, bounded recursion, explicit resource limits | Reject compilation with structured diagnostics |
| Malicious model/manifest | Signed manifest, hash verification, size limits, schema validation | Refuse load; never partially execute |
| Prompt injection | Data/instruction separation and capability broker | Treat injected instruction as untrusted text |
| Path traversal or symlink escape | Canonical path resolution, allowed-root descriptors, no string-only checks | Deny effect and audit the rejection |
| Tool confused deputy | Capability scoped to caller, resource, operation, and approval | Require reauthorization |
| Quantization poisoning | Calibration provenance, held-out evaluation, robust statistics | Promote precision or reject artifact |
| Cache corruption | Versioned pages, checksums, transaction nonce, replay tests | Roll back to last valid commit |
| Compiler miscompilation | Differential reference execution and sanitizer builds | Do not retain candidate |
| Resource exhaustion | Memory, token, time, file, network, and thermal budgets | Cancel safely and preserve committed state |
| Benchmark manipulation | Fixed protocol, repeated runs, variance reporting, signed records | Mark result exploratory only |

## 5. Dependency-Ordered Roadmap

### Stage 0: Reproducible foundation

Before adding features, create a locked development environment, a single test command, deterministic seeds, artifact directories, and machine-readable result schemas. Every test must distinguish `pass`, `fail`, `skip`, and `not_run`. Missing optional dependencies must not appear as code regressions.

**Gate:** A clean environment can rebuild the LLVM artifacts and run the complete host regression suite from one command.

### Stage 1: Harden HyperIR contracts

Implement explicit SSA value ownership, symbolic dimension constraints, effect ordering, alias annotations, resource lifetimes, and structured diagnostics. Add a verifier that rejects unknown operations, duplicate definitions, use-before-definition, unresolved dimensions at lowering, undeclared writes, and invalid evidence upgrades.

**Gate:** Fuzzed malformed graphs produce deterministic rejection; valid graphs have stable digests; no existing neural, transformer, quantization, or speculative test regresses.

### Stage 2: Harden manifests and proof-carrying quantization

Define a versioned manifest schema. Bind weight, calibration, evaluator, kernel, compiler, and device fingerprints. Implement int4 → int8 → f16 promotion, held-out validation, confidence intervals, and an explicit refusal state. Add a manifest verifier independent from the selector that can validate an artifact after transport.

**Gate:** Changing any bound input invalidates the proof. Every selected layer has a passing proof or an explicit fallback. No failed layer is silently deployed.

### Stage 3: Harden memory and KV-cache semantics

Replace list-based cache state with versioned pages and transaction handles. Add capacity reservation, checksums, cancellation, stale-handle rejection, page ownership, and deterministic replay. Separate prefill, decode, speculative, and recovery transactions.

**Gate:** Randomized sequences of append, rollback, commit, cancellation, and capacity failure preserve the committed-token invariant. Exact greedy output matches target-only decoding.

### Stage 4: Implement and verify native kernels

Develop NibbleFlow as an actual fused ARM64 kernel family rather than only a lowering label. Maintain reference, portable scalar, and NEON implementations. Validate ABI, alignment, tails, signed nibble decoding, accumulation width, NaN policy, and output layout.

**Gate:** Device or emulator execution passes numerical differential tests across adversarial shapes and shows statistically significant improvement against the portable baseline. If device execution is unavailable, mark performance as unverified and retain only correctness artifacts.

### Stage 5: Adaptive scheduling and thermal control

Use a bounded policy state with hysteresis, cooldown periods, minimum dwell time, and monotonic emergency behavior. Feed it rolling latency, acceptance, memory pressure, battery, and thermal signals, but never let a transient sample trigger rapid profile oscillation.

**Gate:** The policy improves sustained throughput or energy under a documented thermal workload without exceeding latency, quality, or memory budgets. Every profile transition is replayable from the event log.

### Stage 6: Capability-secure AI effects

Implement a broker process or equivalent isolation boundary. Normalize file and URI scopes, bind capabilities to an invocation identity, require explicit approval for high-risk effects, and log both accepted and denied actions. Add network egress, secret access, subprocess, and package-install policies.

**Gate:** Prompt-injection and path-traversal suites demonstrate that untrusted model text cannot expand authority. Denied actions have no side effects.

### Stage 7: Integrated developer workspace

Only after the contracts are stable should HyperC expose live compilation, tensor inspection, effect tracing, cache visualization, profiling, package signing, and deployment commands. The workspace must show proof status and benchmark provenance rather than hiding them behind a “successful build” message.

**Gate:** One command can build, test, verify manifests, produce a signed package, and generate a reproducibility record. Any failed gate blocks packaging.

## 6. Test and Benchmark Governance

The test system must have four layers. Unit tests validate local types and algorithms. Property tests generate shapes, transaction histories, policies, and numerical edge cases. Differential tests compare optimized kernels and graphs against trusted references. System tests exercise the full compiler/runtime under resource pressure, cancellation, malformed inputs, and hostile model output.

| Test class | Examples | Required frequency |
|---|---|---|
| Unit | Tensor shape, dtype, evidence, capability, proof schema | Every change |
| Property | Random matmul shapes, cache histories, path scopes, quantization groups | Every merge |
| Differential | Scalar vs NEON, float vs quantized, target-only vs speculative | Every kernel or runtime change |
| Fuzz | Parser, manifest, graph verifier, tool arguments, memory pages | Nightly and before release |
| System | Android package, thermal run, offline agent, cancellation, low memory | Release candidates |
| Reproducibility | Clean rebuild, fixed seeds, artifact hashes, replay logs | Every release |

Benchmarks must report median, p95, variance, warmup, token count, model size, peak memory, estimated traffic, energy proxy where available, and error against a declared reference. Results from x86-64, ARM emulator, and physical ARM64 must be separate categories. No simulated Android result may be phrased as a physical-device result.

## 7. Optimization and Rollback Protocol

Every optimization candidate is built in an isolated worktree or artifact namespace. It receives a candidate ID and records its baseline. The candidate must pass compilation, unit tests, differential tests, safety tests, and resource limits before performance is measured. Performance promotion requires a predefined improvement margin and repeated measurements with confidence intervals.

If any correctness, safety, quality, memory, or reproducibility gate fails, the candidate is discarded automatically. If a later regression is discovered, the manifest registry must support instant rollback to the last signed known-good artifact. Optimization must never overwrite the only known-good version.

| Decision | Action |
|---|---|
| Correctness failure | Reject immediately |
| Safety-policy failure | Reject and preserve audit record |
| Quality-gate failure | Promote precision or reject |
| Performance neutral | Do not retain unless it reduces memory or energy without regressions |
| Performance improvement with high variance | Repeat; do not promote yet |
| Device-only failure | Disable device profile; retain portable fallback |
| Missing provenance | Mark exploratory; do not release |

## 8. Release Levels

HyperC should use explicit maturity labels instead of a single ambiguous “working” status.

| Level | Meaning | Allowed claims |
|---|---|---|
| Prototype | Contract or algorithm exists | Functional behavior on stated fixtures only |
| Host-validated | Reproducible x86-64 tests pass | Host correctness and measured host performance |
| Cross-compiled | AArch64 artifact emitted | Artifact generation, not device performance |
| Emulator-validated | AArch64 execution passes | Emulator correctness and emulator performance |
| Device-validated | Physical Android device passes | Device-specific correctness and measured performance |
| Release-candidate | Signed artifacts, security, reproducibility, and rollback pass | Deployment within declared device matrix |

The current HyperC status is **host-validated for the new HyperIR, adaptive speculation, proof selector, LLVM prototypes, and existing regression suite; cross-compiled for selected AArch64 objects; not yet device-validated**.

## 9. Immediate Implementation Queue

The next implementation cycle must follow this order:

| Priority | Work item | Completion evidence |
|---:|---|---|
| 1 | Add a versioned HyperIR schema and independent verifier | Invalid graph corpus rejected deterministically |
| 2 | Add manifest signatures and complete fingerprint binding | Tampering tests invalidate proofs |
| 3 | Replace cache list semantics with nonce/versioned transactions | Stale, foreign, cancelled, and overflow transactions fail safely |
| 4 | Add property and differential testing harness | Randomized graph, cache, quantization, and speculation corpus passes |
| 5 | Implement real NibbleFlow ARM64 kernel | Emulator/device numerical equivalence and measured speedup |
| 6 | Add capability broker isolation | Prompt-injection and path-traversal tests show zero unauthorized effects |
| 7 | Add sustained thermal benchmark protocol | Profile transitions and rollback are replayable |
| 8 | Build integrated package/release command | One-command signed, reproducible, gated artifact |

## 10. Definition of Done

HyperC is ready for a first serious release only when the following statements are simultaneously true:

1. The compiler rejects invalid shapes, effects, evidence upgrades, capabilities, cache transitions, manifests, and resource budgets before execution.
2. Every optimized kernel and quantized layer has a reproducible differential or quality proof bound to the exact artifact inputs.
3. Speculative decoding preserves exact greedy semantics and has a statistically validated sampling mode.
4. Model-generated output cannot grant itself authority or escape canonical capability scopes.
5. Resource exhaustion, cancellation, thermal pressure, and corrupted artifacts fail closed and preserve the last committed state.
6. Host, emulator, and physical-device measurements are clearly separated and reproducible.
7. Optimization candidates are isolated, measured against signed baselines, and automatically rolled back on regression.
8. A clean checkout can rebuild, test, verify, package, and reproduce the release artifact with one documented command.

Until all eight conditions pass, HyperC should be treated as a research prototype with host-validated components, not as a production-safe programming language or Android performance product.

## References

[1]: https://llvm.org/docs/LangRef.html "LLVM Language Reference Manual"
[2]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[3]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[4]: https://owasp.org/www-project-top-ten/ "OWASP Top Ten"
