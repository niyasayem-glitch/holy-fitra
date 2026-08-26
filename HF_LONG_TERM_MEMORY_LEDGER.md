# Holy Fitra Long-Term Evidence Ledger

## Purpose

This repository-local ledger is the durable, reviewable fallback for Holy Fitra decisions, implementation receipts, rejected experiments, and evidence boundaries. Each entry is designed to be safe to synchronize into the connected long-term Mem workspace once authorization is available.

It is not a replacement for the user’s connected long-term memory. It is a version-controlled queue and provenance record that prevents an unavailable connector from silently losing context or producing unsupported memory claims.

## Mem synchronization status

| Field | Value |
|---|---|
| Requested use | Long-term retrieval of prior HF decisions and persistence of validated outcomes |
| Attempt date | 2026-08-26 |
| Current status | Blocked by `permission_denied: 403 Forbidden` when reading connector configuration and listing Mem operations |
| Claims avoided | No claim that Mem was read, written, continuously synchronized, or queried successfully |
| Recovery action | Reauthorize the connected Mem workspace, then retrieve prior HF entries before writing the unsynced records below |

## Entry schema

| Field | Meaning |
|---|---|
| `id` | Stable, date-prefixed ledger identifier |
| `status` | `validated`, `rejected`, `blocked`, or `planned` |
| `scope` | Specific compiler, runtime, AI, or integration surface |
| `decision` | What was retained, rejected, or deferred |
| `evidence` | Exact tests, receipts, artifacts, and commit IDs |
| `boundary` | What the evidence does not establish |
| `sync` | Mem synchronization state and safe future action |

## Unsynced entries

### `HF-2026-08-26-MEM-001`

| Field | Value |
|---|---|
| Status | `blocked` |
| Scope | Connected Mem long-term project ledger |
| Decision | Use Mem for retrieval before major HF work and for persistence after validated work; use this local ledger only as a temporary fallback. |
| Evidence | Both connector configuration lookup and Mem operation discovery returned `permission_denied: 403 Forbidden`. |
| Boundary | This does not prove the Mem workspace is absent, empty, misconfigured, or permanently unavailable. |
| Sync | Pending successful authorization and tool discovery. |

### `HF-2026-08-26-LANG-005`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Deterministic native module imports |
| Decision | Retained relative `.hf` imports with canonical root containment, dependency-first assembly, graph diagnostics, import-aware cache identity, check/inspect visibility, and package inclusion. |
| Evidence | Commit `7ccf395`; 45 focused compiler tests; 118 compiler/core tests; transitive host execution; AArch64 Android-21 object gate. |
| Boundary | Does not establish Bionic linking, APK integration, device execution, dynamic loading, or qualified module namespaces. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-AI-001`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Supervised AI coding-agent plan review |
| Decision | Retained a deterministic review receipt that binds each proposed write to its SHA-256 digest, requires at least one allowlisted validation after the final write, requires any `finish` action to be last, and rejects invalid plans before workspace mutation. |
| Evidence | Focused AI agent/provider/campaign suite: 22 tests passed. Full Holy Fitra regression suite: 286 tests passed. |
| Boundary | No external model was called for this receipt. The gate does not prove model correctness, guarantee a passing validation command detects every defect, authorize automatic writes, or provide continuous background memory synchronization. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-LANG-006`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Explicit signed and unsigned native scalar conversions |
| Decision | Retained `u32`/`u64` types and explicit `to_i32`/`to_u32`/`to_i64`/`to_u64` intrinsics. Same-width signedness changes preserve bits; widening uses `sext` or `zext`; direct-literal range checks apply; runtime 64-to-32 narrowing is rejected. |
| Evidence | Focused compiler suite: 46 tests passed. Full Holy Fitra regression suite: 287 tests passed. The persisted fixture emitted an AArch64 Android-21 object. |
| Boundary | No runtime checked casts, unsigned input bridge, unsigned hybrid reducers, Bionic link, APK, JNI, or device execution is established. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-MODEL-001`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Deterministic local token language-model baseline |
| Decision | Retained `holyfitra local-lm`: UTF-8 byte tokenization, one begin token, causal next-byte bigram training, deterministic greedy generation, checksum-bound NumPy checkpoints, and evaluation receipts. |
| Evidence | 5 focused local-model tests passed; full HF suite passed 292 tests. CLI training/evaluation on repository README and capability documents produced corpus digest `c134ce5aa4f2cda768704485170a16d50c4dfc597cf7bc364606c60210e39935`, model digest `84507886cc2028fe8b071b468f646ead87a49b118e1885948c443badce71527e`, 28,646 transitions, and in-corpus mean NLL `2.624217972399485`. |
| Boundary | This is a 257-token, one-token-context bigram baseline. It does not demonstrate held-out quality, natural-language understanding, coding, reasoning, long context, transformer attention, quantization quality, tool use, multimodality, Qwen parity, or device performance. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-MODEL-002`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Bounded sparse local n-gram context expansion |
| Decision | Retained `holyfitra local-lm train --order 2` through `--order 4`, with sparse bounded contexts, hierarchical interpolation from global to longest observed context, deterministic greedy decode, and tamper-detecting checkpoints. |
| Evidence | Focused local-model suite: 6 tests passed. On the matched current repository-document corpus (2 documents, 28,855 transitions, digest `7352350aefb7778ee19e6f1427887f5fde69c72f03c443732231e83de7c34a5b`), order-1 NLL was `2.6247765502432703` and order-2 NLL was `1.6327421523496604`: absolute reduction `0.9920343978936099`, relative reduction `37.79500383%`. |
| Boundary | This is an in-corpus NLL comparison only. It does not establish held-out quality, generalization, natural-language understanding, coding, reasoning, transformer equivalence, Qwen parity, resource efficiency, or device performance. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-MODEL-003`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Bounded trainable causal embedding-attention local model |
| Decision | Retained an opt-in single-head causal byte-attention reference with learned embeddings, positions, `Q/K/V/O`, residual output, deterministic SGD, bounded architecture, causal-mask proof, and digest-checked checkpoints. Rejected it as the default NLL model. |
| Evidence | Focused attention/local-model suites: 10 tests passed. Causal invariance test confirms future tokens do not change prior logits. The 16-width, 16-context, 9,744-parameter, 12-epoch configuration reached in-corpus NLL `2.623819122090098` on the 28,905-transition corpus digest `ff31abb84e39ba90ebc9a3e7cadf64e7b88406d824adb8916fa93a1c5ee160d0`; retained order-2 n-gram NLL was `1.6326092371555752` on the same corpus. |
| Boundary | The attention baseline does not establish a production transformer, attention throughput, held-out quality, generalization, language understanding, coding, reasoning, multimodality, Qwen parity, Android execution, or device performance. |
| Sync | Pending Mem authorization. |

### `HF-2026-08-26-AI-002`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | HD supervised coding copilot and Obsidian-compatible second brain |
| Decision | Retained `holyfitra hd <workspace> <goal> [--vault <vault>] [--apply]` as a thin supervised facade over the existing transactional coding agent and local `ObsidianVaultIndex`. HD emits a retrieval digest plus vault-relative note provenance and delegates plan review, explicit apply, allowlisted validation, and rollback receipts to the established agent controls. |
| Evidence | Focused HD plus Obsidian suites: 12 tests passed. Full Holy Fitra regression suite: 302 tests passed. CLI help and machine-readable capability checks passed. Provider-plan context was tested only with a deterministic fake client; no external provider was called. |
| Boundary | This does not establish live Obsidian synchronization, an external Obsidian connector, Mem synchronization, provider correctness, autonomous background code changes, arbitrary shell/network access, source deletion, or unrestricted model control. A successful check remains evidence only for that check. |
| Sync | Pending Mem authorization. Do not claim this entry has been sent to or retrieved from Mem. |

### `HF-2026-08-26-AI-003`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | HD provider adapters and local credential isolation |
| Decision | Retained verified HD paths for the existing Gemini and OpenRouter providers plus new Cerebras, Groq, and Cohere providers. Retained an explicit `--provider-env` loader for an ignored local `hd.providers.env` file, a tracked value-free template, an allowlist of provider-only variables, and supervised-workspace protection for the credential filename. |
| Evidence | Focused AI provider, agent, HD, and compiler suites: 72 tests passed. Full Holy Fitra regression suite: 307 tests passed. Provider discovery listed Cerebras, Groq, and Cohere; CLI help exposed `--provider-env`. No actual credential value or external provider call was used during validation. |
| Boundary | This does not verify user credentials, provider billing/quota, model availability, response quality, external connector synchronization, or autonomous code application. Three screenshot values could not be safely attributed from prefix alone and were intentionally not implemented as guessed providers. |
| Sync | Pending Mem authorization. The ledger stores no credential values, prompts, or user source code. |

### `HF-2026-08-26-AI-004`

| Field | Value |
|---|---|
| Status | `validated` |
| Scope | Interactive HD advice, visible change previews, and bounded foreground build campaigns |
| Decision | Retained read-only HD advice, pre-apply per-file unified-diff receipts, and an explicitly approved campaign mode limited to three independent foreground cycles. Campaign cycles use the existing plan review, explicit apply, command allowlist, validation, and rollback transaction and stop on the first non-applied receipt. |
| Evidence | Focused HD, agent, and compiler suites: 66 tests passed. Full Holy Fitra regression suite: 311 tests passed. CLI help exposed `--mode`, `--rounds`, and `--approve-campaign`. Deterministic fake-provider regressions covered advice no-mutation, visible create/modify diffs, explicit campaign consent, bounded stopping, and failed-validation rollback. |
| Boundary | This does not establish a live persistent chat service, provider correctness, user-visible Pix Studio integration, background autonomy, an infinite loop, arbitrary tool access, or provider execution. Campaign approval is bounded and foreground-only. |
| Sync | Pending Mem authorization. No provider key, prompt, or user source is stored in this ledger. |

## Logging protocol

Before a major HF wave, retrieve the latest relevant long-term entry if Mem access is authorized. After a retained or rejected wave, append one compact entry with exact commit, test counts, and boundaries. Do not store credentials, user source code, provider prompts, or unverified performance claims. Do not present local logging as automatic background synchronization.
