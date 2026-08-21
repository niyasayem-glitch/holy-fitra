# Holy Fitra Self-Hosted Symbol Table and Type Checker Architecture

## 1. Objective and design boundary

The next self-hosting milestone is not a direct jump from token recognition to a complete LLVM emitter. The compiler needs an explicit semantic middle layer that turns source tokens into stable names, scopes, types, and diagnostics. The symbol table and type checker should therefore be designed as a deterministic compiler service with no Python dependency and with representations that can be emitted by the current Stage-0 seed.

> **Core invariant:** every accepted source construct must resolve to a stable symbol ID and a canonical type ID before LLVM lowering begins. Every unresolved or unsafe construct must fail closed with a source span and a stable diagnostic code.

The current Stage-0 constraints shape the design. Holy Fitra supports `dyn<i32>`, fixed arrays, named structs, strings, read-only file handles, functions, control flow, source-file I/O, and source spans. It does not yet provide general pointers, arbitrary dynamic element types, imports, generics, effects, or a general byte-buffer ABI. Consequently, the first self-hosted semantic core should use integer IDs, source-span references, and columnar `dyn<i32>` storage rather than pointer-rich object graphs.

| Constraint | Architectural response |
|---|---|
| Only bounded `dyn<i32>` dynamic storage is available | Store records in parallel integer arrays or fixed-stride packed arrays |
| Source strings are read-only and byte access is bounded | Refer to names by source start/length/hash; copy text only when the future string-builder ABI exists |
| No general pointers or maps | Use integer handles and deterministic open-addressing tables |
| Stage-0 has fixed arrays and structs but limited heap composition | Use small structs for local logic, IDs for persistent compiler state |
| Diagnostics already have spans and stable families | Store diagnostic records as integer columns and sort deterministically |
| `&&` and `||` now short-circuit | Type checking and future effect checking must preserve lazy RHS semantics |
| AArch64 validation is artifact-only | Keep the semantic core architecture-independent and avoid device claims |

## 2. Compiler-core data flow

The semantic pipeline should be split into stable, testable passes rather than one recursive function that simultaneously parses, resolves, infers, and emits code.

```text
source file
    │
    ▼
lexer ──► token columns: kind/start/length/aux
    │
    ▼
parser ──► AST arena: node kind/children/span/name reference
    │
    ▼
declaration collector ──► module, struct, function, and builtin symbols
    │
    ▼
scope builder ──► lexical scopes, parameters, locals, fields
    │
    ▼
name resolver ──► symbol IDs attached to AST nodes
    │
    ▼
type checker ──► canonical type IDs attached to expressions/declarations
    │
    ▼
contract/effect checker ──► later capability and resource validation
    │
    ▼
canonical IR / LLVM emitter
```

The parser should not perform semantic lookup except for structural decisions. The type checker should not emit LLVM. This separation makes the eventual Stage-1 fixed-point comparison meaningful: token streams, AST records, symbol tables, type annotations, diagnostics, and LLVM text can each be compared independently.

## 3. Token and AST representation required by semantic passes

The current frontend stores only token kinds. That is sufficient to recognize `aggregates.hf`, but insufficient for symbol identity because two identifiers have the same token kind. The next frontend revision should retain token metadata in parallel arrays:

| Token column | Meaning |
|---|---|
| `token_kind` | Keyword, identifier, integer, string, punctuation, operator, or EOF |
| `token_start` | Zero-based byte offset into the source string |
| `token_length` | Byte length of the lexeme |
| `token_aux` | Integer literal value, string delimiter flag, or reserved metadata |
| `token_line` | One-based source line for diagnostics |
| `token_column` | One-based display column for diagnostics |

A packed representation is also possible: a fixed stride of six integers per token. Parallel columns are recommended first because they make field access explicit and reduce accidental stride arithmetic. The existing parser can continue to expose `token_at_kind`; new semantic code can call `token_name_equal(source, token_id, text)` and `token_span(token_id)`.

The parser should emit an AST arena rather than immediately discarding structure. Each node receives an integer `node_id`. The arena stores fixed columns such as `node_kind`, `node_first_child`, `node_child_count`, `node_left`, `node_right`, `node_name_start`, `node_name_length`, `node_span_start`, `node_span_end`, and later `node_symbol_id` and `node_type_id`. Child lists can be stored in one `node_children` dynamic array. This is a compact equivalent of the C++ prototype’s recursive AST objects, but it is self-hostable using only `dyn<i32>`.

The AST must include at least the following node kinds before type checking begins: module, struct declaration, field declaration, function declaration, parameter, block, let/var declaration, assignment, return, if, while, expression statement, integer, boolean, string, name, unary, binary, call, array literal, struct literal, field access, and index access.

## 4. Canonical type arena

Types should be represented by integer `type_id` handles. Primitive IDs must be reserved and stable across compiler versions so that serialized type annotations remain comparable.

| Type ID range | Type |
|---:|---|
| `0` | `TYPE_ERROR`; absorbs an earlier error without hiding the original diagnostic |
| `1` | `i32` |
| `2` | `i64` |
| `3` | `bool` |
| `4` | `void` |
| `5` | `string` |
| `6` | `file` |
| `7` | `dyn<i32>` |
| `8+` | Interned arrays, structs, and function types |

The type arena is a set of parallel columns:

| Column | Purpose |
|---|---|
| `type_kind` | Primitive, array, struct, function, error, or future tensor/evidence kind |
| `type_a` | Element type, struct symbol ID, or function parameter-list ID |
| `type_b` | Function return type or secondary metadata |
| `type_count` | Array length or function parameter count |
| `type_flags` | Mutability, ownership, nullable-handle, or future effect flags |
| `type_name_start` / `type_name_length` | Optional source reference for named types |
| `type_hash` | Canonical structural hash used for interning |

The arena must intern structurally identical types. For example, every occurrence of `[3]i32` must resolve to one type ID, and every reference to the same struct declaration must use the same struct type ID. Interning prevents inconsistent comparisons and makes fixed-point output stable.

Type equality should be exact in the first semantic core. There should be no implicit narrowing, no implicit conversion from `bool` to integer, and no implicit conversion between handles. Integer literals may carry a temporary literal state so that `let x: i64 = 1` can be accepted without weakening ordinary expression typing; the checker should materialize the expected type at the declaration boundary.

## 5. Symbol record and scope architecture

Symbols are also integer handles. A symbol record should be stored in parallel arrays so the type checker can update annotations without pointer mutation.

| Symbol column | Meaning |
|---|---|
| `symbol_kind` | Module, struct, field, function, parameter, local, builtin, or type alias later |
| `symbol_name_start` / `symbol_name_length` | Borrowed name span in source |
| `symbol_name_hash` | Deterministic hash of the name bytes |
| `symbol_type_id` | Declared or resolved type |
| `symbol_scope_id` | Defining lexical scope |
| `symbol_decl_node` | AST node containing the declaration |
| `symbol_flags` | Mutable, initialized, exported, builtin, or future ownership/effect bits |
| `symbol_order` | Declaration order for deterministic serialization |

Names should initially remain borrowed from the source buffer. Equality is `length + hash + byte comparison`, not pointer identity. This avoids a premature string-interning dependency and keeps names valid for the lifetime of one compilation unit. A later cross-module cache can intern names into a content-addressed string table.

Each lexical scope receives a `scope_id` and these fields:

| Scope field | Purpose |
|---|---|
| `scope_parent` | Enclosing scope or `-1` for module scope |
| `scope_kind` | Module, function, block, loop, or future task/effect scope |
| `scope_bucket_base` | Start of this scope’s hash-table bucket range |
| `scope_bucket_capacity` | Power-of-two bucket count |
| `scope_depth` | Lexical depth for diagnostics and deterministic lookup |
| `scope_owner_symbol` | Function or block declaration that owns the scope |

The first implementation should use deterministic open addressing. The compiler estimates capacity from declaration count, allocates a bounded bucket array, fills empty buckets with `-1`, and uses linear probing. A bucket stores a symbol ID; the symbol record carries the hash and source span needed for collision verification. Lookup starts in the current scope and walks `scope_parent` until module scope. Duplicate declaration checking searches only the current scope, while ordinary resolution searches outward.

The implementation must never silently resize beyond a declared bound. If a scope’s load factor would exceed the configured limit, compilation fails with a resource diagnostic rather than becoming nondeterministic. This is important for Android memory contracts and for reproducible fixed-point builds.

## 6. Required symbol-table operations

The self-hosted API should expose small operations with explicit failure results rather than hidden global mutation.

```text
symbol_table_init(source, token_count, declaration_budget)
scope_push(kind, owner_symbol) -> scope_id
scope_pop() -> bool
symbol_declare(scope_id, name_start, name_length, kind, type_id, flags) -> symbol_id
symbol_lookup(scope_id, name_start, name_length) -> symbol_id or -1
symbol_lookup_type(scope_id, name_start, name_length) -> type_id or TYPE_ERROR
symbol_mark_initialized(symbol_id)
symbol_is_mutable(symbol_id) -> bool
scope_snapshot() -> checkpoint_id
scope_rollback(checkpoint_id)
scope_commit(checkpoint_id)
```

The checkpoint operations are valuable for speculative parsing, future imports, and error recovery. They should record only the lengths of append-only arrays and the changed bucket positions. A rollback must restore bucket contents and array lengths exactly; it must not rely on a garbage collector or pointer invalidation behavior.

## 7. Semantic passes

### Pass 0: initialize the type universe and builtins

Create the primitive type IDs, register runtime builtins, and predeclare compiler-reserved names. Builtins such as `hf_dyn_i32_new`, `hf_dyn_i32_push`, `hf_dyn_i32_get32`, `hf_dyn_i32_set32`, `hf_string_len32`, and `hf_read_text` must be represented as ordinary function symbols with a builtin flag. This lets ordinary call checking validate their arguments through the same path as user functions.

### Pass 1: collect top-level declarations

Walk the module AST and declare all structs and functions before checking bodies. This permits forward references and mutual function calls without requiring source-order hacks. Duplicate module, struct, and function names are diagnosed here. The pass records declaration order but does not yet resolve field or parameter types.

### Pass 2: resolve type syntax and signatures

Resolve each struct field type, function parameter type, and return type into canonical type IDs. Struct names must already exist from Pass 1. Recursive structs should be rejected initially unless represented through an explicitly supported handle type; this avoids infinite type construction in the first implementation.

Function symbols receive a canonical function type containing parameter-list ID, parameter count, return type ID, and future effect summary. Duplicate parameter names are rejected within a function scope.

### Pass 3: build lexical scopes and bind declarations

For each function, create a function scope, declare parameters, then recursively create block scopes. `let` and `var` declarations are inserted into the current scope at their declaration point. A name is not visible before its declaration unless the language explicitly introduces hoisting later. Each local symbol stores its mutability and initialization state.

The scope builder should attach a provisional symbol ID to every name declaration and maintain a node-to-scope mapping. This makes later diagnostics precise and prevents the type checker from reconstructing lexical context.

### Pass 4: resolve expression names and calls

Resolve every name expression through the current scope chain. A name that is not found produces `HF2001` and receives `TYPE_ERROR` so checking can continue. A call expression must resolve to a function symbol; calling a variable or type name is an `HF5001` error.

Calls are checked for exact arity, argument type compatibility, and builtin handle contracts. The checker must not evaluate or execute calls. It only annotates the AST with the callee symbol and result type.

### Pass 5: infer and check expression types

Expression checking is recursive and returns a type ID. It also stores the type ID on the AST node.

| Expression | Required rule |
|---|---|
| Integer literal | Temporary integer-literal type; materialize to expected `i32`/`i64` when valid |
| Boolean literal | `bool` |
| String literal | `string` |
| Name | Type of resolved symbol; reject uninitialized local |
| Unary `-` | `i32` or `i64`; reject `bool` and handles |
| Unary `!` | `bool` only |
| Arithmetic | Matching integer types; no silent narrowing |
| Comparisons | Matching scalar operands; result `bool` |
| `&&`, `||` | Both operands `bool`; result `bool`; RHS remains semantically lazy |
| Array literal | Non-empty elements with one compatible element type; result interned fixed array type |
| Struct literal | Named struct exists; fields are known, unique, and type-compatible |
| Field access | Base must be a known struct; field must exist |
| Index access | Base must be fixed array or supported dynamic handle; index must be integer |
| Call | Callee must be function; exact arity and argument compatibility |

The checker should distinguish an `HF3001` type mismatch from an `HF4001` invalid array/index operation and `HF5001` function/argument failure. It should report one primary error per invalid node and propagate `TYPE_ERROR` upward to avoid cascades.

### Pass 6: check statements and control flow

Statement checking validates declaration initializers, assignment mutability, return types, branch conditions, loop conditions, and termination. A `var` may be assigned after declaration; a `let` may not. Assignments should be represented as l-values later so field and array-element mutation can be checked without special cases.

The first control-flow analysis need only track whether a block definitely returns. It should reject a non-void function with a path that falls through. A loop should not be considered definitely returning unless the language later adds a proven infinite-loop construct. `if` returns definitely only when both branches exist and both definitely return.

## 8. Diagnostics and error recovery

Diagnostics should be first-class records rather than formatted strings. Store columns for `code`, `severity`, `primary_start`, `primary_end`, `secondary_start`, `secondary_end`, `symbol_id`, and `message_kind`. Message text can initially be selected from a stable code/message table; a future byte-buffer ABI can render the final text.

Diagnostics must be emitted in deterministic order: primary source start, primary source end, code, then insertion order. Duplicate diagnostics for the same node and code should be suppressed. The checker should cap the number of diagnostics and fail closed when the cap is exceeded, reporting a final `too many diagnostics` record rather than consuming unbounded memory.

The initial code families remain:

| Code | Meaning |
|---|---|
| `HF1001` | Parser or malformed syntax |
| `HF2001` | Unknown, duplicate, or invalid name |
| `HF3001` | Type, return, mutability, or operand error |
| `HF4001` | Array, index, field, or aggregate-shape error |
| `HF5001` | Function, call, builtin, or argument error |
| `HF6001` | Compiler resource or bounded-memory failure |
| `HF7001` | Capability/effect violation when that layer is added |

A diagnostic must never include an untrusted source-derived string by raw pointer. It should refer to source spans and message IDs. The renderer can later reproduce the current C++ format: `path:line:column: error[CODE]`, source excerpt, caret range, and notes.

## 9. Safety and determinism invariants

The semantic core must be stricter than the runtime it feeds. It should enforce the following invariants:

1. **No invalid IDs.** Every symbol, scope, type, node, and token ID is checked before array access.
2. **No unchecked capacity growth.** All dynamic arrays have explicit budgets derived from source size and compiler configuration.
3. **No pointer identity.** Name equality uses bounded hash plus source-byte comparison.
4. **No use before initialization.** A local symbol’s initialization bit is checked at every read.
5. **No mutation through immutable bindings.** `let` and non-mutable fields reject assignment.
6. **No implicit dangerous conversion.** Integer narrowing, handle conversion, and boolean/integer coercion fail closed.
7. **No speculative-state leakage.** Parser and symbol checkpoints either commit completely or restore all changed state.
8. **No evaluation during checking.** Calls, model execution, file operations, and tool operations are never executed by the checker.
9. **No eager safety bypass.** Type checking preserves the language’s short-circuit semantics and later effect checking must respect RHS reachability.
10. **Deterministic output.** Symbol IDs, type IDs, diagnostics, and serialized tables follow source/declaration order and stable hash rules.

## 10. Fixed-point Stage-1 integration

The fixed-point path should proceed in four measurable stages.

| Stage | Input | Output | Proof |
|---|---|---|---|
| Stage 0 | C++17 seed plus Holy Fitra source | Stage-1 compiler executable | Seed compiles all compiler-core sources without Python |
| Stage 1 | Stage-1 compiler source | Stage-2 compiler executable | Stage 1 compiles the same source and produces canonical tables |
| Fixed point A | Stage 1 and Stage 2 outputs | Canonical symbol/type/diagnostic snapshots | Snapshots are byte-identical |
| Fixed point B | Repeated Stage-1 rebuild | Native/LLVM artifacts | Compiler artifact and emitted LLVM digest stabilize |

The comparison should not rely only on executable hashes because timestamps, paths, or linker metadata can differ. Compare canonical token metadata, AST records, symbol records, type records, diagnostic records, and normalized LLVM text. Only after those match should artifact identity be considered a fixed-point success.

The Python compiler remains a migration oracle during this process. It may generate expected snapshots and differential-test the self-hosted implementation, but the final no-Python gate must compile, type-check, emit, and invoke the native backend without importing Python.

## 11. Recommended implementation sequence

| Milestone | Implementation | Gate |
|---|---|---|
| M0 | Add token start/length columns and source-span helpers | Existing frontend still parses all fixtures; token snapshot is deterministic |
| M1 | Add AST arena and child-list storage | Parser snapshot matches repeated runs; malformed inputs remain fail-closed |
| M2 | Add primitive type arena and builtin function symbols | Builtin calls type-check; invalid handle calls are rejected |
| M3 | Add scope stack and deterministic open-addressing symbol table | Duplicate and unknown-name fixtures pass with stable IDs |
| M4 | Add struct/function signature resolution | Forward calls, fields, and parameter types resolve deterministically |
| M5 | Add expression and statement type checking | Positive aggregate fixture and negative type/mutability fixtures pass |
| M6 | Add diagnostic record storage and renderer | Error output matches stable golden files without Python |
| M7 | Add bounded byte-buffer/string-builder ABI | Self-hosted diagnostics and future LLVM text output no longer need fixed buffers |
| M8 | Implement the current-subset LLVM emitter in Holy Fitra | Stage-0 compiles `compiler/main.hf` into a native Stage-1 compiler |
| M9 | Run differential and fixed-point rebuilds | Canonical semantic snapshots and normalized LLVM reach fixed point |

The most practical first coding milestone is **M0 plus M2**: retain token spans while introducing the canonical primitive type arena and builtin signatures. M3 can then resolve names without waiting for the complete emitter. The byte-buffer ABI should arrive before M6/M8 so diagnostics and LLVM text emission do not become the self-hosting bottleneck.

## 12. Final architectural principle

The self-hosted compiler should be an **ID-based, arena-backed, deterministic semantic machine**. Source text remains immutable; tokens and AST nodes point into it by spans; symbols and types are stable integer handles; scopes are bounded hash tables; diagnostics are structured records; and every pass is explicit about its memory and failure contract. This architecture fits the current Stage-0 subset while leaving clean extension points for effects, tensors, uncertainty types, model/resource contracts, and Android-specific compilation policies.
