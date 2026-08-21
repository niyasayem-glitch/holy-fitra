# Holy Fitra Deterministic Name Resolution Across Nested Blocks

## 1. Goal

The self-hosted resolver must map every identifier occurrence to exactly one stable symbol ID, or produce one deterministic diagnostic. It must work with the current Stage-0 constraints: immutable source strings, bounded `dyn<i32>` storage, no general pointers, no hash-map primitive, and fail-closed memory behavior.

> **Resolver invariant:** lookup is a pure function of the source bytes, declaration order, lexical scope chain, namespace, and compiler configuration. Repeated runs over identical source must produce identical symbol IDs, bucket layouts, diagnostics, and snapshots.

The resolver should not infer types, execute calls, or emit LLVM. Its responsibility is only to create scopes, declare symbols, and attach resolved symbol IDs to AST name and call nodes.

## 2. Namespaces and resolution policy

Use explicit namespaces so a type name cannot accidentally resolve as a local value. The initial namespaces are:

| Namespace | Contents | Examples |
|---|---|---|
| `VALUE` | Functions, parameters, locals, mutable bindings, builtins | `main`, `x`, `hf_dyn_i32_get32` |
| `TYPE` | Struct names and future aliases | `Pair`, `Tensor` |
| `FIELD` | Struct fields, resolved only through a base struct type | `Pair.first` |

There is no overload resolution in the first self-hosted core. Two value symbols with the same name in one scope are a duplicate declaration. A child scope may shadow a value in an ancestor scope, but a declaration never shadows another symbol in the same scope.

For a value occurrence, lookup order is:

```text
current block scope
    → parent block scopes
        → function scope
            → module scope
                → builtin value scope
```

For a type occurrence, the same lexical chain is searched in the `TYPE` namespace, followed by the module type scope and builtin type scope. Fields are not searched lexically; the type checker resolves `base.field` against the field table of the base struct.

## 3. Integer IDs and arena storage

All persistent compiler objects use integer IDs. `-1` means “not found”; `0` is reserved for an invalid/error object where appropriate. IDs are assigned by append order, never by hash-bucket position.

### 3.1 Symbol columns

The symbol arena uses parallel integer arrays. Each logical row has the same `symbol_id` index in every column.

| Column | Meaning |
|---|---|
| `symbol_kind` | Module, struct, field, function, builtin, parameter, local, or future alias |
| `symbol_namespace` | `VALUE`, `TYPE`, or `FIELD` |
| `symbol_name_start` | Byte offset into the immutable source string |
| `symbol_name_length` | Identifier byte length |
| `symbol_name_hash` | Deterministic non-negative hash |
| `symbol_scope_id` | Defining scope |
| `symbol_type_id` | Declared or resolved type, or `TYPE_ERROR` |
| `symbol_decl_node` | AST declaration node |
| `symbol_flags` | Mutable, initialized, builtin, exported, or future ownership bits |
| `symbol_order` | Declaration sequence number |

The arrays are allocated with a declared symbol budget and prefilled to that logical capacity. The compiler maintains `symbol_count` separately. This avoids requiring a dynamic-array shrink operation during checkpoint rollback and makes every indexed write bounds-checkable.

### 3.2 Scope columns

Each lexical scope receives one `scope_id`.

| Column | Meaning |
|---|---|
| `scope_parent` | Parent scope ID, or `-1` at the root |
| `scope_kind` | Builtin, module, function, block, loop, or future task/effect scope |
| `scope_depth` | Root depth `0`, increasing by one per nesting level |
| `scope_bucket_base` | First bucket index assigned to this scope |
| `scope_bucket_capacity` | Number of buckets in this scope |
| `scope_owner_symbol` | Function/block symbol that owns the scope |
| `scope_order` | Creation order for deterministic snapshots |

The resolver keeps `current_scope_id` while walking a function body. An AST node receives the scope in which it occurs, allowing later passes to reproduce lookup without reconstructing the tree walk.

### 3.3 Bucket storage

All scope hash tables share one preallocated `scope_buckets` array. Empty buckets contain `-1`; occupied buckets contain a `symbol_id`. The logical range for scope `s` is:

```text
[scope_bucket_base[s], scope_bucket_base[s] + scope_bucket_capacity[s])
```

Each scope should use a power-of-two capacity when the language gains bit operations. Until then, use a positive modulo operation based on integer division. The table capacity must be at least twice the expected number of declarations in that scope, with an explicit load-factor ceiling such as 70%.

The table is not resized during resolution. If the configured budget or load factor is insufficient, the compiler emits `HF6001` rather than silently changing layout.

## 4. Deterministic hashing

Use a fixed, seed-independent byte hash. A Stage-0-compatible version can keep values non-negative and bounded at every step:

```text
HASH_MOD = 1_000_003
hash = 17
for each byte b in name[start : start + length]:
    hash = hash * 31 + b
    hash = hash - (hash / HASH_MOD) * HASH_MOD
return hash
```

Because `hash` remains in `[0, HASH_MOD)`, the multiplication stays within safe `i32` range for the chosen modulus and table indexing never depends on signed overflow. The hash is only a collision accelerator; equality always performs length and byte comparison.

The table probe function is:

```text
base = scope_bucket_base[scope_id]
capacity = scope_bucket_capacity[scope_id]
start = hash - (hash / capacity) * capacity
for probe = 0 .. capacity - 1:
    slot = start + probe
    if slot >= capacity:
        slot = slot - capacity
    bucket = base + slot
    symbol_id = scope_buckets[bucket]
    if symbol_id == -1:
        return (NOT_FOUND, bucket)
    if symbol_name_hash[symbol_id] == hash
       and symbol_name_length[symbol_id] == length
       and source_bytes_equal(symbol_id, start, length):
        return (symbol_id, bucket)
return (TABLE_FULL, -1)
```

`source_bytes_equal` compares the stored declaration span against the occurrence span byte by byte. It must check both offsets and lengths before calling `hf_string_byte32`; invalid spans produce a compiler resource or source-integrity diagnostic rather than an unsafe runtime read.

## 5. Scope creation and destruction

### 5.1 Entering a scope

`scope_push(kind, owner_symbol, declaration_budget)` performs these steps:

1. Validate that `scope_count` is below the configured maximum.
2. Choose a deterministic bucket capacity from `declaration_budget`, for example the smallest allowed capacity whose load factor is below 70%.
3. Reserve a contiguous range in `scope_buckets`.
4. Fill every bucket in that range with `-1`.
5. Append the scope columns at `scope_count`.
6. Set `scope_parent[new_scope] = current_scope_id`.
7. Set `scope_depth[new_scope] = scope_depth[parent] + 1`, or zero for the root.
8. Set `current_scope_id = new_scope`.
9. Increment `scope_count`.

The operation is deterministic because bucket capacity depends only on the declaration budget and the scope is created in AST traversal order. A scope owns no heap pointers; it owns only integer ranges in the shared arrays.

### 5.2 Leaving a scope

`scope_pop()` validates that the current scope is not the root, records the parent, and sets `current_scope_id` to that parent. It does not clear the child buckets. The child scope becomes unreachable from future lexical lookups, while keeping its records available for diagnostics, AST annotations, and canonical snapshots.

This non-destructive behavior is intentional. It prevents ID reuse and makes repeated builds stable. Memory is reclaimed only when the entire compilation arena is discarded.

## 6. Declaration algorithm

A declaration is visible only after its declaration point. This avoids accidental self-reference in an initializer and matches the simplest lexical rule for the first compiler core.

```text
symbol_declare(scope_id, namespace, name_start, name_length,
               kind, declared_type, decl_node, flags):
    validate scope_id and source span
    hash = name_hash(source, name_start, name_length)

    (existing, slot) = find_in_scope(scope_id, namespace,
                                     hash, name_start, name_length)
    if existing != NOT_FOUND:
        emit HF2001 duplicate declaration
        add note pointing to symbol_decl_node[existing]
        return ERROR_SYMBOL
    if slot == -1:
        emit HF6001 scope symbol-table capacity exceeded
        return ERROR_SYMBOL

    if symbol_count >= symbol_capacity:
        emit HF6001 compiler symbol budget exceeded
        return ERROR_SYMBOL

    symbol = symbol_count
    symbol_kind[symbol] = kind
    symbol_namespace[symbol] = namespace
    symbol_name_start[symbol] = name_start
    symbol_name_length[symbol] = name_length
    symbol_name_hash[symbol] = hash
    symbol_scope_id[symbol] = scope_id
    symbol_type_id[symbol] = declared_type
    symbol_decl_node[symbol] = decl_node
    symbol_flags[symbol] = flags
    symbol_order[symbol] = symbol_count
    scope_buckets[slot] = symbol
    symbol_count = symbol_count + 1
    return symbol
```

The declaration pass should predeclare all module-level structs and functions before checking any function body. This permits forward function calls and mutually recursive functions without source-order exceptions. Local declarations remain sequential: check the initializer first, then insert the local symbol, then mark it initialized.

For an explicitly uninitialized `var`, insert the symbol with `INITIALIZED = false`. A later read produces `HF3001` until an assignment marks it initialized. A `let` is inserted as immutable and initialized only after its initializer has passed type checking.

## 7. Lookup algorithm across nested blocks

The resolver receives the occurrence node’s `scope_id`, namespace, source span, and optional expected symbol kind.

```text
resolve_name(start_scope, namespace, name_start, name_length):
    hash = name_hash(source, name_start, name_length)
    scope = start_scope

    while scope != -1:
        (symbol, slot) = find_in_scope(scope, namespace,
                                       hash, name_start, name_length)
        if symbol != NOT_FOUND:
            return symbol
        if slot == TABLE_FULL:
            emit HF6001 internal table exhaustion
            return ERROR_SYMBOL
        scope = scope_parent[scope]

    if namespace == VALUE:
        (builtin, slot) = find_in_scope(builtin_scope, VALUE,
                                         hash, name_start, name_length)
        if builtin != NOT_FOUND:
            return builtin

    emit HF2001 unknown name
    return ERROR_SYMBOL
```

The important property is that lookup searches the entire current scope before moving outward. It never returns the first matching bucket from a parent while an inner scope still contains a same-named symbol. Since each scope has its own table, shadowing is naturally implemented by the first successful scope in the chain.

Calls use the same `VALUE` lookup but require the resulting symbol kind to be `FUNCTION` or `BUILTIN`. Type syntax uses the `TYPE` namespace. Field access bypasses lexical lookup and performs a deterministic linear or hashed search within the canonical field list of the resolved struct type.

## 8. Nested-block example

Consider:

```holyfitra
fn demo(x: i32) -> i32 {
    let value: i32 = x
    if value > 0 {
        let value: i32 = 2
        let inner: i32 = value
        return inner
    }
    return value
}
```

The scopes and symbols are:

| Scope ID | Parent | Kind | Symbols |
|---:|---:|---|---|
| `0` | `-1` | module | `demo` |
| `1` | `0` | function | parameter `x` |
| `2` | `1` | function body | local `value` |
| `3` | `2` | `if` block | shadowing `value`, local `inner` |

Resolution is deterministic:

| Occurrence | Starting scope | Result |
|---|---:|---|
| parameter `x` initializer | `2` | search `2`, then `1`; resolves to symbol in `1` |
| inner `value` initializer | `3` | resolves to shadowing symbol in `3` |
| `inner` return | `3` | resolves to symbol in `3` |
| final `value` return | `2` | resolves to outer symbol in `2`; scope `3` is not searched because it is not an ancestor of the final statement |

The child `value` never modifies or replaces the parent bucket. It is a separate symbol in scope `3`, which is why leaving the block automatically restores the parent binding.

## 9. Checkpoints and rollback

Normal lexical traversal does not need rollback, but speculative parsing and future import or attribute handling will. Rollback must restore logical state without reusing IDs.

Maintain a checkpoint record:

| Field | Meaning |
|---|---|
| `checkpoint_symbol_count` | Symbol count at checkpoint |
| `checkpoint_scope_count` | Scope count at checkpoint |
| `checkpoint_bucket_log_count` | Number of bucket writes recorded |
| `checkpoint_current_scope` | Current scope at checkpoint |
| `checkpoint_diagnostic_count` | Diagnostic count at checkpoint |

Every bucket overwrite records `(bucket_index, old_symbol_id)` in an append-only change log. `scope_push` records the old logical arena counts and fills new buckets through the same log mechanism.

```text
checkpoint = begin_checkpoint()
try speculative declarations or parsing
if success:
    commit(checkpoint)
else:
    rollback(checkpoint)
```

Rollback walks the bucket log backward, restores each old bucket value, restores the logical counts and current scope, and truncates the logical diagnostic count. The underlying `dyn<i32>` arrays need not shrink; stale rows are unreachable because all passes honor the restored logical counts. Symbol IDs created after the checkpoint are never reused, which prevents references from silently changing identity. A later canonical serializer may omit unreachable rows or retain them with an explicit transaction epoch, but it must use one policy consistently.

## 10. Complexity and bounded behavior

Let `L` be identifier length, `D` the lexical depth, and `P` the maximum probe count in one scope.

| Operation | Expected cost | Worst-case bound |
|---|---:|---:|
| Hash a name | `O(L)` | `O(L)` |
| Declare in current scope | `O(L + P)` | `O(L + capacity)` |
| Resolve a name | `O(L + D·P)` | `O(L + D·capacity)` |
| Enter scope | `O(bucket_capacity)` for initialization | Same, bounded by budget |
| Leave scope | `O(1)` | `O(1)` |
| Rollback | `O(number of changed buckets)` | Bounded by checkpoint budget |

The compiler should enforce maximum lexical depth, maximum symbols, maximum scopes, maximum bucket capacity, maximum identifier length, and maximum diagnostics. Exceeding any bound produces `HF6001`; it must not resize unpredictably or continue with corrupted semantic state.

## 11. Diagnostic rules

| Situation | Code | Primary span | Related note |
|---|---|---|---|
| Unknown name | `HF2001` | Identifier occurrence | None |
| Duplicate same-scope declaration | `HF2001` | New declaration | Previous declaration span |
| Invalid type/value namespace | `HF2001` | Identifier occurrence | Expected namespace |
| Read before declaration | `HF2001` | Use occurrence | Declaration-point rule |
| Read before initialization | `HF3001` | Identifier occurrence | Declaration span |
| Assignment to `let` | `HF3001` | Assignment target | Immutable declaration span |
| Scope table full | `HF6001` | Current declaration | Scope budget and capacity |
| Symbol arena full | `HF6001` | Current declaration | Compiler symbol budget |
| Corrupt source span | `HF6001` | AST/token node | Internal source-integrity note |

Diagnostics are sorted by primary source offset, primary end offset, code, and emission order. The resolver should emit one primary diagnostic for an invalid name and attach `ERROR_SYMBOL` so later passes can continue without cascades.

## 12. Validation fixtures

The resolver is ready for implementation when these fixtures are available:

| Fixture | Expected result |
|---|---|
| Nested shadowing | Inner use resolves to inner symbol; outer use resolves to outer symbol |
| Outer capture | Inner block resolves a parameter and outer local correctly |
| Same-scope duplicate | Reject with `HF2001` and previous-declaration note |
| Child-scope shadowing | Accept when policy allows; symbol IDs remain distinct |
| Scope escape | Name declared in a block is unknown after the block |
| Use before declaration | Reject before declaration point |
| Forward function call | Accept after top-level predeclaration |
| Unknown function call | `HF2001` or `HF5001` according to failure stage |
| Type/value namespace separation | Reject using a struct name as a value and vice versa |
| Builtin fallback | Resolve runtime builtin only after lexical/module lookup fails |
| Hash collision | Resolve by hash plus length plus byte equality, never hash alone |
| Bucket saturation | Fail closed with `HF6001` |
| Checkpoint rollback | Speculative symbols and bucket writes disappear logically after rollback |
| Deterministic repeat | Two runs produce identical symbol IDs, bucket arrays, and diagnostics |

The most important regression is a three-level shadowing fixture that checks both semantic results and serialized symbol records. Exit-code-only tests are insufficient; the resolver must expose a canonical snapshot for comparison.

## 13. Implementation order

1. Add source-span token metadata and a bounded `name_hash`/`source_bytes_equal` helper.
2. Add prefilled parallel symbol, scope, and bucket arenas with logical counts.
3. Implement scope push/pop and module/builtin root scopes.
4. Implement namespace-aware declaration and lookup.
5. Add top-level predeclaration for structs and functions.
6. Add sequential local declaration and initialization tracking.
7. Attach symbol IDs to AST name, call, declaration, and field nodes.
8. Add deterministic diagnostics and canonical symbol/scope snapshots.
9. Add checkpoints and rollback before implementing speculative grammar features.
10. Differential-test against the Python/C++ semantic oracle, then run the no-Python, sanitizer, AArch64-object, and Termux gates.

This algorithm keeps the first self-hosted resolver simple enough for Stage 0 while providing the exact extension points needed later for imports, overload-free function resolution, capability scopes, effect scopes, tensor/model namespaces, and resource-contract checking.
