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

## Deep hardening continuation — 2026-08-22

A second adversarial pass found and repaired additional confirmed boundary flaws:

| Subsystem | Confirmed flaw | Retained repair |
|---|---|---|
| HyperIR tensor types | Tensor compatibility ignored dtype, allowing unsafe mixed-dtype operations | Compatibility now requires matching dtype, device, layout, and compatible shape |
| HyperIR attention | Query and key head dimensions were not checked | Rank-4 attention validation now requires matching head dimensions and valid Q/K/V sequence dimensions |
| HyperIR evidence/proofs | NaN confidence and proof metrics could bypass comparisons | Evidence confidence and quantization metrics must be finite and non-negative |
| HyperIR capabilities | Scope prefix matching over-granted names such as `/publicity` for `/public` | Exact, slash-delimited, and explicit wildcard matching are separated |
| HyperIR serialization | `default=str` could silently change unsupported attributes into identity-bearing strings | Canonical digest and JSON output now use strict finite JSON and fail closed |
| Ragged attention | Mutated payloads retained stale digests; non-finite values and int32 offset overflow were not rejected | Payload digest is reverified, values are finite float32, offsets use int64, and work arithmetic is Python-integer bounded |
| Dynamic prefill | Non-finite requests, duplicate IDs, invalid policy values, and stale packed batches were accepted | Requests, policies, packed offsets, digests, and token state are validated before execution |
| Speculative decoding | Invalid logits/probabilities, boolean counts, invalid plans, and vocabulary mismatch were under-validated | Model distributions, plans, cache capacity, generation counts, and residual sampling now fail closed |
| Android buffers | Boolean dimensions, excessive preallocation, malformed KV entries, and NaN values were accepted | Strict positive integer dimensions, a bounded token capacity, shape checks, and finite KV writes are enforced |
| Hybrid execution | Malformed reducer type tuples, effects, and floating worker counts could fail during execution | Metadata and reducer type specifications are validated before launch |
| Shared contracts | NaN evidence, boolean task capacities, invalid deadlines, and non-finite kernel budgets were accepted | Contract constructors and kernel verification now enforce finite, typed, bounded values |

Focused and complete validation after this continuation passed **153 Python tests with 0 failures**. The Termux-compatible host gate passed, the no-Python bootstrap gate passed, sanitizer checks passed, native numerical checks passed, AArch64 object generation passed, and compile/shell checks passed. No physical Android execution is claimed.

The previously recorded 201-test figure in the earlier audit section belongs to an earlier repository state and should not be used as the current count; the current working-tree gate is 153 tests. Architectural gaps remain: full fixed-point self-hosting, coverage-guided fuzzing, ThreadSanitizer concurrency stress, complete tensor ABI lowering, and physical Android-device validation.

## Self-hosting ABI continuation — 2026-08-22

The Stage-0 seed now exposes a distinct `buf` type backed by a bounded C runtime string builder. Appends are atomic on capacity failure, signed i32 formatting is checked, `hf_buf_finish` returns an owned copy, and buffers require explicit release. The self-hosted symbol-table fixture uses bounded dynamic arrays with deterministic linear probing, collision handling, duplicate-binding rejection, and parent-scope lookup. Buffer and symbol-table fixtures passed host execution, sanitizer/runtime checks, and non-empty AArch64 object emission. The complete repository matrix passed 153 Python tests with 0 failures, the no-Python bootstrap gate passed, and the Termux-compatible host gate passed. This is a self-hosting foundation milestone, not a claim of fixed-point compilation; type checking, LLVM emission, and Stage-1 rebuild remain unfinished.

## Self-hosted semantic-core continuation — 2026-08-22

The Stage-0 no-Python path now includes executable Holy Fitra code for bounded symbol-table behavior and canonical type-checker primitives. The type checker enforces stable primitive IDs, identity or i32-to-i64 widening only, exact arithmetic/comparison/logical rules, return-value presence, and call arity/argument checks over dynamic-array signatures. Deliberate collision, duplicate binding, invalid operator, invalid call-count, and void-return cases are exercised by fixtures. The complete matrix passed 153 Python tests with 0 failures; bootstrap, runtime ASAN/UBSan, AArch64 object, compile, shell, and Termux gates passed. This does not yet constitute fixed-point self-hosting: AST semantic annotation, LLVM emission, and Stage-1 rebuild remain incomplete.

## Self-hosted emitter continuation — 2026-08-22

A bounded atomic `hf_write_text` runtime primitive and a Stage-0-compilable emitter fixture now establish the output side of the no-Python path. The emitter builds canonical LLVM text with `buf`, writes and round-trips it, and the generated module assembles and executes with exit status 42. Null input, capacity, temporary-file cleanup, and round-trip contents are covered by sanitizer-backed runtime tests. The complete applicable matrix passed 153 Python tests with 0 failures, the expanded bootstrap suite, ASAN/UBSan, AArch64 object, compile, shell, and Termux gates. The fixture is not yet a general self-hosted compiler; AST-driven lowering, diagnostics, and Stage-1 fixed-point rebuilding remain unfinished.

## State-1 canonical data-model continuation — 2026-08-22

The no-Python bootstrap path now includes a State-1 fixture that records token kind/start/length/line/column/auxiliary metadata and constructs a bounded AST arena with child ranges, name spans, source spans, symbol IDs, and type IDs. It emits canonical token and AST snapshots through the bounded buffer and atomic-write ABI, verifies round trips, and compares repeated runs byte-for-byte. The complete matrix passed 153 Python tests with 0 failures, the expanded bootstrap suite, runtime ASAN/UBSan, AArch64 object generation, compile/shell checks, and the Termux-compatible host gate. This remains a data-model proof; the real self-hosted parser, semantic passes, and general LLVM lowering are not yet connected to the arena.

## State-2 real-parser continuation — 2026-08-22

State 2 replaces hand-authored AST construction with a real Stage-0-compilable Holy Fitra parser. It lexes source with bounded token metadata, parses a typed function containing a mutable declaration, return statement, name, integer literals, and binary expression, and stores the result in a bounded AST arena with child ranges and source spans. It writes canonical AST snapshots, verifies repeated byte-identical output, and rejects malformed source without aborting. The complete matrix passed 153 Python tests with 0 failures, the expanded bootstrap suite, runtime ASAN/UBSan, AArch64 artifact generation, compile/shell checks, and the Termux-compatible host gate. The parser is not yet connected to the symbol/type semantic passes or general LLVM lowering.

## State-3 semantic integration continuation — 2026-08-22

Declaration collection, deterministic scope chaining, name resolution, and canonical type annotation now execute over parser-produced AST node IDs. State 3 verifies stable function/local symbol assignment, nested lookup, duplicate-binding rejection, unknown-name rejection, and parsed `bool`/`i32` assignment rejection. It also fixed child-range staging for block and module members and closed owned snapshot-string leaks with `hf_string_free`; the semantic fixture passes ASAN/UBSan leak detection. The complete matrix passed 153 Python tests with 0 failures, the expanded bootstrap suite, semantic sanitizer checks, AArch64 artifact generation, compile/shell checks, and the Termux-compatible host gate. Structured semantic diagnostics, HIR/MIR, and general LLVM lowering remain incomplete.

## State-4 structured diagnostics continuation — 2026-08-22

State 4 adds a bounded diagnostic arena with stable code, severity, source-span, and message-ID columns. Diagnostics are generated only after real parser and semantic failure results for unknown names, duplicate declarations, and type mismatches. Deterministic text and JSON serializers are written and read back atomically; JSON was independently parsed as valid, and repeated artifacts were byte-identical. Invalid record fields fail closed. The complete matrix passed 153 Python tests with 0 failures, the expanded bootstrap suite, State-4 ASAN/UBSan leak checks, AArch64 artifact generation, compile/shell checks, and the Termux-compatible host gate. The records are not yet wired into a complete self-hosted multi-file CLI or HIR pipeline.

## State-5 module-driver continuation — 2026-08-22

State 5 adds deterministic module identities, explicit graph traversal states, export/import tables, public/private visibility checks, cycle detection, and missing-target diagnostics. Adversarial execution found and repaired repeated cycle reporting by introducing terminal error states; export lookup also compares name length with the stable hash. The raw-byte buffer ABI is bounds-checked and sanitizer-tested. The complete matrix passed 153 Python tests with 0 failures, the expanded no-Python bootstrap suite, State-5 ASAN/UBSan, deterministic graph snapshots, AArch64 artifact generation, compile/shell checks, and the Termux-compatible host gate. A filesystem-backed multi-file import parser and HIR integration remain incomplete.
