# Holy Fitra fixed-point self-hosting and general LLVM-lowering roadmap

## 1. Objective

Holy Fitra should reach a **real fixed point** in which the compiler’s lexer, parser, semantic analysis, typed intermediate representation, LLVM emitter, command-line driver, diagnostics, and compiler runtime are written in Holy Fitra and can be rebuilt by a previously generated Holy Fitra compiler without Python.

The target is not merely “a Holy Fitra program that emits a small LLVM example.” The target is a reproducible compiler chain:

```text
Stage-0 C++ seed
    │ compiles
    ▼
Stage-1 compiler written in Holy Fitra
    │ recompiles the same source
    ▼
Stage-2 compiler written in Holy Fitra
    │ canonical outputs compare equal
    ▼
Fixed point: semantic snapshots, HIR/MIR, LLVM text, and normalized artifacts stabilize
```

A fixed point must be established in layers. Executable hashes alone are insufficient because linkers, paths, timestamps, and platform metadata can differ. Holy Fitra should compare canonical compiler products first, then compare normalized native artifacts as a secondary check.

## 2. Current starting point

The current repository already contains a C++17 Stage-0 seed compiler, a self-hosted lexer/parser fixture, a bounded dynamic-array and file runtime, a byte-buffer/string-builder ABI, a deterministic symbol-table foundation, canonical type-checker primitives, and a small LLVM text-emitter fixture. The Python-hosted compiler remains the functional language oracle and user-facing implementation.

| Existing capability | Status | Meaning for the roadmap |
|---|---|---|
| Stage-0 lexer/parser/type checking | Implemented in C++ | Can compile the current seed-supported subset without Python |
| Holy Fitra lexer/parser source | Implemented as fixture | Parser logic has crossed into the language, but is not yet the compiler driver |
| Dynamic arrays and file reads | Implemented | Compiler state can be represented in bounded integer arenas and source files can be loaded |
| `buf` and atomic text output | Implemented | Self-hosted diagnostics and LLVM text no longer require fixed-size output buffers |
| Symbol-table foundation | Implemented as fixture | Deterministic probing and parent scopes are proven, but not connected to AST nodes |
| Type-checker foundation | Implemented as fixture | Primitive rules and call contracts are proven, but full AST typing is not connected |
| LLVM emitter fixture | Implemented as fixture | Text creation, atomic write, assembly, and execution are proven for one module |
| Python compiler | Functional oracle | Supplies differential expectations during migration; it must not remain in the final bootstrap path |
| Full fixed-point rebuild | Not implemented | The principal remaining architectural milestone |

## 3. Non-negotiable invariants

The self-hosted compiler should preserve the following invariants in every pass:

1. **No hidden Python dependency.** The final Stage-1 compile, check, emit, build, test, and package path must work with Python absent from `PATH` and from the environment.
2. **Stable IDs.** Token, AST node, symbol, scope, type, HIR value, MIR block, diagnostic, and module IDs are assigned deterministically from source and declaration order.
3. **Bounded memory.** Every arena and dynamic array has an explicit budget. Capacity exhaustion is a compiler diagnostic, not silent resizing or process corruption.
4. **No unchecked indexing.** Every integer handle is range-checked before use. `TYPE_ERROR` and invalid symbol IDs propagate errors without creating secondary memory faults.
5. **No semantic side effects during checking.** Type checking and effect checking inspect metadata; they do not execute file operations, model calls, network calls, or agent tools.
6. **Canonical output.** JSON, symbol snapshots, type snapshots, HIR/MIR, diagnostics, and LLVM text use stable ordering, normalized paths, deterministic whitespace, and explicit schema versions.
7. **Fail-closed safety.** Ownership, mutability, initialization, capability, effect, resource, quantization, and model contracts reject malformed or ambiguous input.
8. **Source-span preservation.** Every user-facing error retains a stable source span and diagnostic code from parser through backend.
9. **Backend verification.** Every generated LLVM module is assembled or verified before it is considered a successful compiler output.
10. **No inflated platform claims.** AArch64 object emission is artifact validation; physical Android measurements require a real device and must remain separately reported.

## 4. Target compiler architecture

The compiler should be split into independently serializable stages:

```text
module loader
    ▼
source buffer + canonical path
    ▼
lexer: token arena with kind/start/length/line/column
    ▼
parser: AST arena and child lists
    ▼
declaration collector: modules, structs, functions, builtins
    ▼
resolver: scopes, symbols, imports, visibility
    ▼
type checker: canonical type IDs and expression annotations
    ▼
ownership/effect/resource checker
    ▼
HIR: source-oriented typed operations
    ▼
MIR: explicit CFG, locals, memory, calls, checks, and terminators
    ▼
optimization and target contracts
    ▼
LLVM emitter
    ▼
LLVM verifier/assembler
    ▼
linker and runtime packaging
```

The key boundary is **typed HIR to CFG-based MIR**. HIR retains source-level meaning and diagnostics. MIR makes control flow and machine-relevant operations explicit. LLVM lowering then becomes a mechanical backend rather than a second semantic checker.

## 5. Roadmap phases

### Phase A — Canonical compiler data model

**Goal:** make every semantic object representable in bounded, deterministic arenas.

Implement the following in Holy Fitra:

| Component | Required representation |
|---|---|
| Token arena | Parallel `dyn<i32>` columns for kind, start, length, line, column, and auxiliary value |
| AST arena | Node kind, child range, left/right links, name span, source span, symbol ID, and type ID |
| Child storage | One bounded child-list arena with explicit first/count ranges |
| Symbol arena | Kind, name span/hash, type ID, scope ID, declaration node, flags, and declaration order |
| Scope arena | Parent, kind, depth, owner symbol, bucket base, and bucket capacity |
| Type arena | Kind, structural operands, count, flags, source name span, and canonical hash |
| Diagnostic arena | Stable code, severity, source span, message ID, related symbol/node, and insertion order |

**Acceptance criteria:** repeated runs over the same source produce byte-identical snapshots; malformed IDs fail with stable diagnostics; all arena growth is bounded and tested at capacity boundaries.

### Phase B — Real self-hosted frontend

**Goal:** replace the fixture frontend with a compiler frontend that produces a persistent AST arena.

Refactor the current self-hosted lexer/parser into modules with explicit interfaces:

```text
lex(source) -> TokenSnapshot
parse(tokens) -> ASTSnapshot | diagnostics
```

Add source offsets and lengths to the existing lexer. Parse all Stage-1 constructs: modules, structs, functions, parameters, locals, assignments, control flow, expressions, arrays, structs, fields, indexes, and calls. Preserve source spans on every AST node.

Do not perform name lookup during parsing. The parser should only make structural decisions and record unresolved names as AST references.

**Acceptance criteria:** positive fixtures produce canonical AST snapshots; negative fixtures produce parser diagnostics rather than aborts; the self-hosted snapshot matches a Python-oracle snapshot after normalization.

### Phase C — Connected symbol and type passes

**Goal:** turn the existing symbol-table and type-checker foundations into the actual semantic compiler.

Implement the passes in this order:

1. Predeclare all module-level structs and functions.
2. Resolve primitive, array, dynamic, struct, and function types into interned type IDs.
3. Build function and block scopes with deterministic parent links.
4. Declare parameters and locals at their source positions.
5. Resolve names and attach symbol IDs to AST nodes.
6. Resolve calls and attach callee symbols.
7. Infer and check expression types.
8. Check assignment mutability and definite initialization.
9. Check branch and loop conditions.
10. Check definite returns and function signatures.

Use `TYPE_ERROR=0` as an absorbing error type. The checker should record the first diagnostic for an invalid node, propagate `TYPE_ERROR`, and continue where safe to provide bounded diagnostics without cascading memory failures.

**Acceptance criteria:** the self-hosted semantic snapshots match the Python compiler for the Stage-1 subset; duplicate names, unknown names, invalid handles, bad calls, invalid operators, immutable assignments, uninitialized reads, and missing returns all fail closed with stable codes and spans.

### Phase D — Structured diagnostics and compiler runtime

**Goal:** make the self-hosted compiler usable from the terminal and automation.

Implement a small standard library layer over the existing runtime:

| Capability | Requirement |
|---|---|
| Strings | Length, byte access, comparison, and bounded concatenation through `buf` |
| Paths | Canonical relative paths, root containment, and deterministic module names |
| Files | Bounded reads, atomic writes, and clear error results |
| Diagnostics | Stable code-to-message table, source excerpt, caret range, and notes |
| Collections | Bounded integer vectors, maps, and sorted deterministic views |
| Process driver | Clang/LLVM invocation with captured exit status and bounded output |
| Time/telemetry | Monotonic measurements used only for diagnostics and optimization, never identity |

Diagnostics must be a structured intermediate product before formatting. The same diagnostic records should support CLI output, JSON output, tests, and editor integration.

**Acceptance criteria:** `check` works without Python, diagnostics match golden files, output paths are safe, and failed subprocesses cannot be reported as successful builds.

### Phase E — Typed HIR

**Goal:** create a stable semantic IR that is independent of LLVM syntax.

Define HIR records such as:

```text
HIRModule {
    module_id
    canonical_path
    imports
    declarations
    diagnostics
}

HIRFunction {
    symbol_id
    parameters
    return_type_id
    effects
    body_nodes
    source_span
}

HIRNode =
    constant | local_read | local_write | call | unary | binary |
    compare | short_circuit | aggregate | field | index |
    branch | loop | return
```

HIR must retain type IDs, symbol IDs, source spans, and explicit ownership/effect metadata. It should not contain target-specific registers, LLVM labels, or platform-dependent layout assumptions.

Serialize HIR canonically and compare it before attempting native code generation.

**Acceptance criteria:** every accepted Stage-1 AST node lowers to typed HIR; no HIR node has an unresolved symbol or `TYPE_ERROR`; invalid programs stop before backend lowering; repeated HIR snapshots are identical.

### Phase F — CFG-based MIR

**Goal:** make evaluation order, control flow, memory, and safety checks explicit.

Lower HIR to MIR with explicit basic blocks and terminators:

```text
MIROperation =
    const | alloca | load | store | address_of |
    unary | binary | compare | call |
    bounds_check | null_check | capability_check |
    branch | jump | return | unreachable

MIRTerminator =
    jump | conditional_branch | return | unreachable
```

Short-circuit operators must become conditional control flow. Array indexing must carry a bounds-check operation unless proven safe. Mutable locals must use explicit stores. Calls must carry resolved signature IDs and effect summaries.

Later extensions can add task submission, cancellation, ordered reducers, tensor operations, quantized kernels, and model resource checks without changing the parser.

**Acceptance criteria:** MIR is in SSA-ready or explicit-local form, every block has one terminator, no operation references an invalid value, and control-flow verification catches malformed graphs before LLVM emission.

### Phase G — General LLVM lowering

**Goal:** lower the complete Stage-1 MIR subset to valid LLVM IR.

Implement the emitter in layers rather than as a single large printer.

#### G1. Module and type lowering

Implement canonical lowering for:

| Holy Fitra type | LLVM representation |
|---|---|
| `i32` | `i32` |
| `i64` | `i64` |
| `bool` | `i1` |
| `void` | `void` |
| `string` | `ptr` in the seed ABI, later a length/data view where needed |
| `buf`/opaque handles | `ptr` with typed builtin signatures |
| fixed arrays | LLVM array types |
| structs | named `%struct.Name` types |
| `dyn<i32>` | opaque runtime pointer handle |
| function types | canonical LLVM function signatures |

Do not lower a value by guessing its type from expression text. Every MIR value must carry a verified type ID.

#### G2. Constants and aggregates

Implement integer, boolean, string, fixed-array, and struct constants. String emission must escape all bytes deterministically. Aggregate field order must follow declaration order, not source-map iteration order.

#### G3. Locals and memory

Emit entry-block allocas, parameter stores, loads, stores, and address calculations. Keep alloca placement deterministic. Reject invalid l-values before emission.

#### G4. Arithmetic and comparisons

Lower typed arithmetic with explicit signedness rules. Reject division by zero when statically known; otherwise retain defined runtime behavior or emit a checked operation according to the language contract. Comparisons must use the correct LLVM predicate for the source type.

#### G5. Control flow

Lower `if`, `while`, short-circuit `&&`/`||`, returns, and unreachable blocks. Generate labels from deterministic block IDs. Verify that every block is terminated exactly once and that phi predecessors match the control-flow graph.

#### G6. Calls and ABI contracts

Lower direct user calls and builtins only after signature verification. Validate argument count, lowered types, calling convention, and return handling. Keep runtime declarations in a canonical ABI table shared by the emitter and package metadata.

#### G7. Bounds and safety checks

Lower array/index checks, null-handle checks, ownership transitions, capability checks, and resource contracts as explicit MIR operations or runtime calls. Safety checks must not disappear because optimization is enabled unless a proof record authorizes their removal.

#### G8. Target lowering

Emit a target triple and ABI metadata from a validated target configuration. Start with x86-64 and AArch64 object generation. Keep NEON/SVE and Android-specific kernel selection behind target contracts; object generation is not device execution evidence.

**Acceptance criteria:** every Stage-1 MIR fixture produces LLVM accepted by `llvm-as` or Clang, representative host executables run with expected results, AArch64 objects are non-empty, and LLVM verifier failures are reported as compiler diagnostics rather than process crashes.

### Phase H — Module graph and native driver

**Goal:** compile real multi-file projects without Python.

Implement:

1. Canonical project-root discovery.
2. Relative module/import resolution.
3. Path normalization and escape rejection.
4. Duplicate module and import-cycle diagnostics.
5. Deterministic topological order.
6. Per-module token/AST/semantic/HIR cache entries.
7. Content and compiler-ABI digests.
8. Atomic artifact publication.
9. `check`, `emit-llvm`, `build`, `run`, `test`, `package`, and `doctor` in the self-hosted driver.

The Python CLI can initially remain as a compatibility wrapper, but the no-Python driver must become independently executable before fixed-point claims are made.

**Acceptance criteria:** multi-file positive projects compile in deterministic order; cycles and missing modules fail with stable diagnostics; changing one module invalidates only the correct dependency closure; cache corruption is recovered safely.

### Phase I — Stage-1 bootstrap and fixed point

**Goal:** prove the compiler can compile itself and stabilize.

Use a three-way comparison:

| Comparison | Purpose |
|---|---|
| Stage-0 vs Python oracle | Detect semantic migration errors |
| Stage-1 vs Stage-0 expectations | Prove the generated compiler behaves correctly |
| Stage-1 vs Stage-2 canonical products | Prove fixed-point stability |

The fixed-point harness should:

1. Build the C++ Stage-0 seed.
2. Use Stage-0 to compile all compiler-core `.hf` sources.
3. Link the Stage-1 compiler with the bootstrap runtime.
4. Run Stage-1 to compile the same compiler-core source set.
5. Normalize and compare token, AST, symbol, type, diagnostic, HIR, MIR, and LLVM outputs.
6. Recompile with Stage-2.
7. Repeat until all canonical products match or a bounded iteration limit is reached.
8. Compare normalized executable metadata separately.
9. Run the full negative suite through both Stage-1 and Stage-2.

A fixed point should require at least two consecutive identical rebuild rounds, not one successful self-rebuild.

**Acceptance criteria:** Stage-1 compiles its own source, Stage-2 compiles the same source, all canonical snapshots are byte-identical across two rounds, and the same invalid programs produce the same diagnostic codes/spans.

## 6. Recommended immediate implementation order

The highest-leverage sequence is:

| Order | Work item | Why now |
|---:|---|---|
| 1 | Add token metadata columns to the self-hosted frontend | Names and diagnostics cannot be deterministic without source references |
| 2 | Build the AST arena and canonical snapshot writer | Connects parsing to all later passes |
| 3 | Replace fixture symbol-table logic with AST-driven declaration collection | Establishes real semantic identity |
| 4 | Connect the canonical type arena to expressions/statements | Converts the type-checker fixture into a compiler pass |
| 5 | Add structured diagnostic records and golden files | Prevents semantic failures from becoming ad hoc strings |
| 6 | Lower typed AST to HIR | Creates a backend-independent semantic boundary |
| 7 | Lower HIR to verified CFG MIR | Makes control flow and safety explicit |
| 8 | Implement module graph and builtins | Required for a multi-file compiler driver |
| 9 | Implement general Stage-1 LLVM lowering | The emitter should consume verified MIR, not raw AST |
| 10 | Build the no-Python driver and fixed-point harness | Only now can fixed-point self-hosting be measured honestly |

The next concrete coding slice should be **token metadata plus AST arena plus canonical snapshots**, not additional AI surface syntax. AI-native tensors, evidence, quantization, and agents should attach to HIR/MIR after the scalar fixed point is stable.

## 7. Validation gates for every milestone

Every retained milestone should pass the applicable gates below:

| Gate | Required result |
|---|---|
| Unit regression | All existing Python tests pass with zero failures |
| Self-hosted fixture | Positive fixtures execute correctly under Stage-0 and Stage-1 where available |
| Negative semantics | Invalid source fails with stable code and source span |
| LLVM verification | Generated IR assembles/verifies before execution |
| Native execution | Host fixtures return expected statuses and outputs |
| Sanitizers | ASAN/UBSan pass; ThreadSanitizer is added once concurrent MIR/runtime paths exist |
| AArch64 | Cross-compiled objects are non-empty and ABI checks pass |
| Determinism | Repeated snapshots and emitted text are byte-identical |
| Termux | No `sudo`, no Python dependency in the bootstrap path, and shell gate passes |
| Package integrity | Digests, manifests, paths, sizes, and runtime ABI metadata validate |
| Android claims | Device measurements are reported only when an actual Android device is used |

## 8. Explicit definition of “done”

Holy Fitra may claim **fully fixed-point self-hosting** only when all of the following are true:

1. The C++ Stage-0 seed compiles the complete Holy Fitra compiler source without Python.
2. The resulting Stage-1 compiler performs lexing, parsing, semantic analysis, HIR/MIR lowering, LLVM emission, linking, testing, and packaging.
3. Stage-1 recompiles the complete compiler source and produces Stage-2.
4. Stage-1 and Stage-2 canonical semantic and backend products match for at least two consecutive rounds.
5. Multi-file imports, visibility, cycles, caches, diagnostics, and project commands work without Python.
6. The complete Stage-1 language subset has general LLVM lowering, not only hand-authored emitter fixtures.
7. Safety, ownership, initialization, effect, capability, and resource checks remain enforced after lowering.
8. x86-64 execution and AArch64 artifact validation pass; Android device results are separately measured or explicitly unavailable.
9. The regression suite includes positive, negative, boundary, deterministic, sanitizer, and differential tests.

Until these conditions are met, the accurate description is **Stage-0 bootstrap with self-hosted frontend, semantic-core, and emitter foundations**, not a fully self-hosted compiler.
