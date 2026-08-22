# Holy Fitra adversarial self-healing audit

## Scope

This audit inspected compiler semantics, self-hosting, AI numerics, quality gates, agent safety, memory ownership, privacy runtime contracts, package publication, Obsidian integration, native kernels, Android-target artifacts, CLI workflows, and test coverage. Confirmed defects were repaired only when a deterministic regression could be added. Design gaps are reported separately from defects.

## Confirmed flaws repaired

| Area | Confirmed weakness | Retained repair |
|---|---|---|
| Execution plans | NaN/Inf quality, energy, or measurement values could defeat ordinary comparisons; unsuccessful receipts were not explicitly rejected | Finite non-negative validation for candidates, constraints, plans, and receipts; unsuccessful receipts fail closed |
| Deployment artifacts | Manifest structure, dimensions, byte counts, dtypes, quantization bits, and scales were not fully cross-checked | Canonical array order, exact shapes, exact storage sizes, supported dtypes, finite positive scales, and broadcast compatibility are verified |
| Agent runtime | `tuple(actions)` materialized an unbounded iterator before checking the step budget | Actions are consumed only up to `max_steps`, and every action is type-checked before execution |
| Tool registry | Malformed argument and grant containers could reach handlers | Arguments must be dictionaries and grants must be frozen sets |
| Tensor runtime | Empty/non-finite tensors, incompatible matrix shapes, malformed backward gradients, and zero-size Dense layers were not rejected explicitly | Finite non-empty tensors, two-dimensional compatible matrix multiplication, finite shape-matched gradients, and positive Dense dimensions are required |
| Memory arena | `np.prod(..., int64)` could overflow before capacity checks for adversarially large shapes | Python arbitrary-precision shape products are used before byte-capacity validation |
| Training | Adam could partially update earlier parameters before a later invalid parameter failed | All moment, update, and parameter proposals are validated first and committed transactionally |
| Replay/data | Replay shape drift, non-finite replay state, invalid finite configuration values, and malformed dataset batches were not uniformly rejected | Finite values, fixed shapes, strict integer controls, and non-empty batches are enforced |
| Privacy/runtime | Privacy release permits were effectively reusable; NaN expiry signals could create non-expiring tokens; unknown thermal states could select an unsafe profile; governed memory could accept non-finite lifetimes | Thread-safe single-use permits, exact expiry boundaries, finite signals, known thermal states, validated profiles, and finite memory lifetimes |
| Intent firewall | A command-like intent could be authorized merely by matching a caller capability, even if its effect was not configured | Requested command effects must be present in the firewall configuration |
| Quantization | NaN thresholds, boolean axes, empty quality arrays, malformed payloads, and invalid scales were not uniformly rejected | Finite thresholds, strict axes and bit widths, non-empty quality arrays, canonical packed payload checks, and finite positive scales |
| Package publishing | Raw paths and arbitrary metadata could undermine canonical package identity; manifest writing was non-atomic | Normalized relative paths, validated hashes/sizes/kinds, strict JSON canonicalization, and atomic manifest replacement |

## Validation evidence

The final matrix was run after all retained repairs:

| Gate | Result |
|---|---:|
| Complete Python regression suite | **201 tests, 0 failures** |
| Termux-compatible host gate | **143 tests passed** |
| No-Python bootstrap gate | Passed |
| Self-hosted lexer/parser execution | Passed |
| Bootstrap sanitizer checks | Passed |
| AArch64 LLVM/object artifact checks | Passed |
| Native kernel numerical checks | Passed |
| Python compileall | Passed |
| Shell syntax checks | Passed |
| `git diff --check` | Passed |

No physical Android execution, thermal measurement, energy measurement, or device benchmark was performed. AArch64 results are cross-compilation artifacts from the x86-64 sandbox.

## Remaining design gaps, not silently classified as bugs

Holy Fitra is not yet a fixed-point self-hosted compiler. The Stage-0 C++ seed can compile the self-hosted lexer/parser, but the Holy Fitra symbol table, type checker, HIR, and LLVM emitter are not yet complete enough to rebuild the entire compiler. The native user-facing compiler remains Python-hosted.

The scalar native backend still has a deliberately bounded language subset and does not yet lower the tensor ABI directly into the ordinary language. The AI runtime is broad but remains a reference/runtime stack rather than a complete compiler-native tensor programming environment.

The Obsidian adapter supports deterministic local Markdown, Wikilinks, backlinks, provenance, Canvas, and Bases exports, but not the complete Obsidian YAML type system, Dataview formulas, embeds, transclusion rendering, aliases, or live CLI/REST/MCP operation. No private vault was accessed during the audit.

The project still needs coverage-guided fuzzing, concurrency stress under ThreadSanitizer, formal IR verification at every native emission boundary, physical Android device validation, and a complete package-manifest reader/verifier command. These are explicit next milestones.

## Retention decision

All repairs listed above passed focused tests and the complete applicable regression matrix. They are retained for publication. No benchmark number is generalized from the sandbox to Android hardware.
