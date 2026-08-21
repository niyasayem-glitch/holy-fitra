# Holy Fitra: Prototype-to-Programming-Language Audit

## Executive assessment

Holy Fitra already has more than a toy syntax demo. It has a Python-hosted native scalar compiler, LLVM emission, persistent caches, task/effect metadata, hybrid-function contracts, AI runtime modules, Android-oriented native kernels, and a C++17 no-Python bootstrap seed. However, it is not yet a complete programming language system because the user-facing compiler remains Python-hosted, the native language subset is narrow, modules are labels rather than a module graph, semantic analysis is mostly local and dictionary-based, and the compiler has no stable HIR/MIR boundary or fixed-point self-rebuild.

The correct transition is not to port every AI module into Holy Fitra immediately. The production target is a **real self-hosted scalar language and toolchain first**, with AI-native types and runtimes layered on top of a stable compiler core.

## What is real today

| Area | Current state | Evidence boundary |
|---|---|---|
| Native syntax | Lexer and recursive-descent parser for a scalar subset | Python tests and Stage-0 fixtures |
| Native backend | Textual LLVM emission and Clang linking | x86-64 execution and AArch64 object generation |
| Runtime contracts | Effects, ownership metadata, tasks, hybrids, reducers | Validation and generated metadata; not all runtime semantics are native yet |
| Self-hosting | C++17 Stage-0 seed compiles and runs a Holy Fitra lexer/parser | No-Python bootstrap gate passes |
| AI runtime | Training, quantization, agents, memory, kernels, scheduler | Mostly Python/C++/Kotlin modules and focused tests |
| Developer workflow | `check`, `build`, `run`, `emit-llvm`, `init`, `package`, `tui`, `repl`, `bench`, `doctor` | Python CLI |
| Reproducibility | Content-addressed LLVM/native caches and deterministic runtime components | Regression/native gates |

## What still makes it a prototype

| Gap | Why it matters | Required language-level fix |
|---|---|---|
| Python is the installed compiler entrypoint | `holyfitra` still resolves to `holyfitra_compiler:main`; Python remains required for production compiler commands | Produce a native Stage-1 `holyfitra` executable and make Python optional migration tooling |
| The native frontend is a narrow subset | It lacks the full statement, expression, aggregate, import, and standard-library surface expected from a general language | Freeze a language specification and implement the self-hosted AST/type/resolver pipeline |
| `module` is mostly a label | There is no import graph, visibility, cycle policy, or dependency compilation | Add module manifests, import resolution, visibility, graph diagnostics, and per-module caches |
| Native type representation is shallow | Python `Type` is primarily a name/mode pair; native LLVM supports only scalar integer/bool types | Add interned type IDs for arrays, structs, strings, handles, function types, ownership, and future AI types |
| Name resolution is local and dictionary-based | There is no self-hosted deterministic scope arena, shadowing model, or canonical symbol IDs | Implement the planned arena-backed scope chain and symbol table |
| Direct AST-to-LLVM coupling | Backend changes force parser/validator changes and make fixed-point comparison weak | Introduce typed HIR and control-flow MIR before LLVM emission |
| Diagnostics are not a stable compiler protocol | Native errors are mostly free-form Python exception strings; the C++ seed has richer spans than the Python native path | Use structured diagnostic records with stable codes, spans, notes, ordering, and golden snapshots |
| Imports and standard library are absent | A language cannot scale beyond single-file examples without files, paths, collections, formatting, and process APIs | Build a small deterministic compiler standard library and module driver |
| Control-flow and mutation are incomplete | The Python native parser primarily handles `let`, `return`, and `if`; loops and assignments are not the complete stable language contract | Add `while`, assignments, l-values, definite initialization, and control-flow analysis |
| Effects and tasks are metadata-heavy | Effects are checked transitively, but task metadata and hybrid declarations are not yet a complete typed runtime model in the native language | Lower effects/tasks/hybrids through HIR/MIR contracts and bounded runtime interfaces |
| Cache is mainly file-content based | It does not yet represent module dependencies, compiler schema, standard library version, or canonical semantic artifacts | Add module graph digests, schema/version inputs, AST/HIR/MIR snapshots, and atomic cache manifests |
| Packaging is source-manifest oriented | It does not yet produce a native compiler/runtime distribution with target-aware standard libraries | Define a versioned toolchain layout and target runtime bundles |
| AI features are separate subsystems | Models, evidence, quantization, and agents are not yet first-class language constructs | Add them only after scalar type/effect/resource contracts are stable |
| Fixed-point proof is absent | Stage 0 can compile a frontend, but Stage 1 has not compiled the compiler itself | Build `compiler/main.hf`, then compare repeated compiler, IR, diagnostics, and object outputs |

## Non-negotiable language contracts

### 1. Language semantics must be specified before feature expansion

Holy Fitra needs a versioned language contract covering lexical rules, declaration visibility, operator precedence, short-circuit behavior, integer widths and overflow, mutability, ownership modes, string encoding, array indexing, module visibility, error behavior, and effect propagation. Any behavior not specified becomes a future compatibility hazard.

### 2. The compiler must be a real native executable

The production command must eventually be a native executable that can perform `check`, `emit-llvm`, `build`, `run`, and module dependency compilation without importing Python. Python remains an oracle, benchmark harness, and migration tool only.

### 3. Every semantic object needs a stable identity

Tokens, AST nodes, symbols, types, HIR values, MIR blocks, diagnostics, and cache records require deterministic IDs and canonical serialization. Source order, not hash-table order or pointer address, controls stable identity.

### 4. Fail closed on invalid programs and invalid resources

Unknown names, duplicate declarations, type mismatches, invalid handles, resource-budget exhaustion, unsupported target features, and malformed caches must stop compilation with structured diagnostics. Silent fallback is forbidden for compiler correctness and AI safety.

### 5. The backend boundary must be explicit

The self-hosted frontend must produce typed HIR and MIR before LLVM. LLVM text remains the initial backend because it is inspectable and easy to cross-compile, but it must consume a stable semantic representation rather than raw parser nodes.

### 6. Modules are part of the language, not a CLI convention

A module system requires import syntax, source resolution, visibility, cycle detection, public/private declarations, module-level symbol tables, dependency digests, and deterministic compilation order. A `module` declaration alone is insufficient.

### 7. Standard library behavior must be deterministic

File ordering, path normalization, string encoding, map iteration, integer overflow, time sources, process status, and environment access must be specified. Compiler code must use explicit arenas, bounded collections, byte buffers, and atomic file writes.

### 8. AI-native features must use the language contracts

Tensors, effects, uncertainty types, model/resource budgets, quantization quality gates, and speculative decoding must be expressed through typed values and capabilities. They should not bypass ordinary name resolution, ownership, diagnostics, or deterministic cache rules.

### 9. The migration oracle must be differential, not authoritative forever

The Python compiler should compile the same corpus and provide expected accepted/rejected status, diagnostics, canonical AST/HIR, effect graph, LLVM, and native behavior. Once Stage 1 reaches fixed point, the self-hosted compiler becomes authoritative and Python can be archived or retained as research tooling.

### 10. Every retained language feature needs a gate

A feature is complete only when it has positive fixtures, negative fixtures, deterministic snapshots, native execution where applicable, LLVM validation, AArch64 object generation, sanitizer coverage, Termux compatibility, and a documented Android-validation boundary.

## The real-language target architecture

```text
holyfitra executable
├── driver and module graph
├── source/bytes/path standard library
├── lexer with source spans
├── parser and AST arena
├── deterministic resolver and symbol tables
├── interned type arena and type checker
├── effect/ownership/resource checker
├── typed HIR
├── control-flow MIR
├── canonical serializer and incremental cache
├── LLVM text emitter
└── Clang/LLVM process and target adapter
```

The AI platform remains a layered ecosystem:

```text
Holy Fitra language core
    ├── tensor/model/evidence standard types
    ├── quantization and deployment contracts
    ├── agent/effect/capability runtime
    └── Android ARM64 kernels and bounded scheduler
```

This separation prevents model-runtime complexity from blocking compiler self-hosting while still giving the language a clear path to first-class AI support.

## Production-language milestone sequence

| Milestone | Deliverable | Exit criterion |
|---|---|---|
| L0 | Freeze language contract and canonical formats | Versioned spec plus migration corpus |
| L1 | Self-hosted source/span/token/AST core | Stage 0 compiles token and AST snapshots |
| L2 | Self-hosted symbols, scopes, and type checker | Positive/negative semantic corpus matches the oracle |
| L3 | Typed HIR and MIR | Control flow, ownership, effects, and hybrids have explicit IR |
| L4 | Self-hosted LLVM backend | Stage 0 builds a native compiler from Holy Fitra source |
| L5 | Native driver and standard library | Native compiler supports check, emit, build, run, modules, and cache |
| L6 | Stage-1 self-rebuild | Stage 1 compiles its own source |
| L7 | Fixed-point verification | Repeated compiler/IR/object outputs stabilize |
| L8 | AI-native language layer | Tensor, evidence, model, quantization, and capability features use the stable core |

## Immediate implementation choice

The highest-leverage next implementation is **L1 + the first slice of L2**: add source-span token metadata, an AST arena, canonical primitive/function type IDs, and deterministic module/function/local symbol resolution. This is more valuable than adding another model primitive because it creates the semantic substrate required by every later language feature.

The first self-hosted compiler should not attempt to port the entire 1,197-line Python compiler. It should be a smaller, explicit compiler core that proves language semantics, deterministic IR, native compilation, and fixed-point rebuilding. The AI runtime can continue to use its existing Python, C++, and Kotlin implementations while the language core becomes real.
