# Holy Fitra Real-Language Architecture Roadmap

## Strategic decision

Holy Fitra becomes a real programming language by making the compiler core independent, typed, deterministic, self-hosted, and usable for ordinary software before adding more AI-specific surface area. The existing AI runtime stack remains valuable, but it should consume stable language contracts rather than define the compiler architecture.

The production architecture is ranked by how much of the language gap it closes, how directly it supports Stage-1 self-hosting, and whether it can be validated without physical Android hardware.

| Rank | Architecture investment | Language value | Risk | Decision |
|---:|---|---|---|---|
| 1 | Self-hosted source, AST, symbol, scope, and type core | Turns syntax recognition into semantic compilation and creates the foundation for every feature | Medium | **Implement first** |
| 2 | Typed HIR and explicit CFG-based MIR | Decouples language semantics from LLVM and makes ownership, effects, hybrids, and optimization composable | High | Implement after semantic core |
| 3 | Canonical LLVM emitter in Holy Fitra | Produces the first real Stage-1 compiler executable | High | Implement after HIR/MIR slice |
| 4 | Deterministic byte/string builder and compiler standard library | Enables diagnostics, canonical IR text, paths, files, and module metadata without fixed buffers | Medium | Implement alongside semantic core |
| 5 | Module/import graph and visibility system | Makes multi-file projects and package-scale programs possible | Medium | Implement before Stage-1 fixed point |
| 6 | Native driver with target selection, Clang invocation, cache, and atomic artifacts | Replaces Python for `check`, `emit-llvm`, `build`, and `run` | Medium | Implement after emitter slice |
| 7 | Stable diagnostics protocol and formatter | Makes the language usable by humans, editors, CI, and automated agents | Low/medium | Implement early |
| 8 | Ownership, mutability, initialization, and borrow validation | Makes memory and AI buffer safety part of the language rather than conventions | High | Implement after basic type checking |
| 9 | Effects, capabilities, resource contracts, and bounded task semantics | Makes model, tool, network, thermal, and unsafe actions statically visible | High | Implement after HIR/MIR |
| 10 | Standard collections and deterministic package format | Supports real applications and reproducible dependency builds | Medium | Implement after modules |
| 11 | Incremental module cache and parallel compilation | Targets large projects and sub-second rebuilds | Medium/high | Implement after canonical module graph |
| 12 | Formatter, linter, REPL, test runner, and language-server protocol | Makes Holy Fitra pleasant and practical for developers | Medium | Implement after native driver |
| 13 | First-class AI types: tensor, quantized tensor, evidence, prediction, claim, fact | Brings AI safety and performance contracts into source semantics | High | Implement after stable scalar language |
| 14 | Model-development DSL and resource-aware lowering | Makes training, LoRA, QAT, pruning, export, and deployment language-native | Very high | Long-term |
| 15 | Self-optimizing compiler and Android profile-guided backend | Uses telemetry, ARM64 topology, thermal gates, and workload profiles for optimization | Very high | Long-term |

## The real compiler pipeline

```text
.hf source files
    │
    ▼
module loader and dependency graph
    │
    ▼
lexer + source spans + token metadata
    │
    ▼
parser + AST arena
    │
    ▼
name resolver + deterministic scope chains
    │
    ▼
canonical type arena + type checker
    │
    ▼
ownership / initialization / effects / resource checks
    │
    ▼
typed HIR
    │
    ▼
CFG-based MIR with explicit calls, branches, tasks, cancellation, and reducers
    │
    ▼
optimization and target contracts
    │
    ▼
canonical LLVM text
    │
    ▼
Clang/LLVM assembler and linker
    │
    ▼
native executable, shared library, or Android artifact
```

The key architectural rule is that AI features enter at typed HIR/MIR boundaries. A quantized matrix is not a special parser shortcut; it is a typed resource-bearing value. A model call is not an untracked function call; it carries effects, memory/thermal contracts, and quality gates. An agent tool invocation is not an arbitrary side effect; it requires a capability in the effect environment.

## What “real language” means for Holy Fitra

A real Holy Fitra installation must support the following ordinary-language workflow without Python:

```bash
holyfitra new my_app
cd my_app
holyfitra check
holyfitra test
holyfitra build --release
holyfitra run
holyfitra package
```

`holyfitra check` must load all imported modules, resolve names across module boundaries, type-check the complete graph, and report stable diagnostics. `holyfitra build` must compile through typed HIR/MIR to LLVM and invoke the platform backend. `holyfitra test` must compile and run deterministic test functions in isolated processes. `holyfitra package` must include source or canonical IR, module metadata, compiler schema, target, runtime ABI, and content digest.

## Stage-1 language-core scope

Stage 1 should deliberately target an ordinary but useful subset:

| Area | Stage-1 requirement |
|---|---|
| Declarations | Modules, structs, functions, constants, locals, mutable locals |
| Types | `i32`, `i64`, `bool`, `string`, fixed arrays, `dyn<i32>`, structs, function signatures |
| Expressions | Literals, names, calls, unary/binary operators, short-circuit logic, arrays, structs, indexing, fields |
| Statements | Blocks, `let`, `var`, assignment, `if/else`, `while`, `return`, expression statements |
| Semantics | Lexical scopes, shadowing policy, initialization, exact type equality, definite returns |
| Modules | Imports, visibility, duplicate/cycle detection, deterministic graph order |
| Backend | Canonical LLVM text for x86-64 and AArch64 object generation |
| Tools | Check, emit, build, run, test, package, doctor |
| Runtime | Files, bytes, strings, arrays, process invocation, atomic output, monotonic clock |

Tensors, effects, hybrids, evidence types, and model contracts should be added only after this subset reaches a self-rebuild fixed point. They will then be implemented as language extensions over the same type, effect, and resource mechanisms.

## Immediate selected implementation wave

The first concrete wave is **Semantic Core v1**:

1. Extend the Stage-0/self-hosted frontend token stream with source offsets, lengths, lines, and columns.
2. Add an AST arena and canonical node serialization.
3. Add interned primitive, array, struct, handle, and function type IDs.
4. Add deterministic symbol and scope arenas using open addressing.
5. Add module-level predeclaration and local name resolution.
6. Add exact expression/statement type checking and definite initialization.
7. Emit typed HIR snapshots before attempting full LLVM emission.
8. Add golden positive/negative fixtures and differential comparison against the Python compiler.

This wave creates the first semantic compiler rather than another syntax demo. It should be implemented with a bounded compiler runtime and tested through the existing no-Python, sanitizer, AArch64-object, and Termux gates.

## HIR/MIR boundary

The first HIR should preserve source-oriented semantics:

```text
HIRFunction {
    symbol_id
    parameter_symbol_ids
    parameter_type_ids
    return_type_id
    effect_set
    body_hir_nodes
    source_span
}
```

MIR then makes execution explicit:

```text
MIRBlock {
    block_id
    operations
    terminator
}

MIROperation =
    const | load_local | store_local | call | binary | compare |
    branch | return | bounds_check | capability_check |
    task_submit | await | ordered_reduce
```

This boundary allows the same typed source to target ordinary LLVM, Android ARM64 kernels, the bounded work-stealing scheduler, or an interpreter/debug backend without changing the parser or resolver.

## Completion gates

The language upgrade is complete only when all of these are true:

| Gate | Required evidence |
|---|---|
| Native compiler | Stage-0 compiles Holy Fitra compiler source to a runnable Stage-1 binary |
| Self-rebuild | Stage 1 compiles its own source successfully |
| Fixed point | Repeated compiler, symbol/type snapshot, HIR/MIR, LLVM, and artifact outputs stabilize |
| Multi-file | Import graph resolves, caches, and diagnoses cycles deterministically |
| Diagnostics | Golden source spans and stable codes match the semantic oracle |
| Backend | LLVM validates and representative x86-64/AArch64 objects are non-empty |
| Safety | Invalid ownership, effects, handles, initialization, and resource budgets fail closed |
| Tooling | `check`, `test`, `build`, `run`, `package`, and `doctor` work without Python |
| Termux | Bootstrap and ordinary project workflow work without `sudo` |
| AI integration | AI-native features use the same type/effect/resource contracts rather than bypassing them |

## Strategic conclusion

Holy Fitra should not become “a Python compiler with more syntax.” It should become a small deterministic systems language whose compiler, standard library, semantic IR, and toolchain are written in Holy Fitra, while its AI and Android layers consume explicit typed contracts. The shortest credible route is semantic core first, HIR/MIR second, native driver third, fixed point fourth, and AI language extensions afterward.
