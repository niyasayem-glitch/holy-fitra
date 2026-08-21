# Making Holy Fitra Self-Hosted Without Python

## Executive answer

Holy Fitra should become self-hosted through a **three-stage bootstrap chain**:

```text
Stage 0: small external seed compiler written in C++ or LLVM IR
    ↓ compiles
Stage 1: Holy Fitra compiler written in Holy Fitra
    ↓ compiles itself
Stage 2: self-hosted Holy Fitra compiler executable
```

The existing Python compiler should remain as a **reference compiler and migration oracle**, but it must stop being required to build or run the production Holy Fitra compiler. The first non-Python bootstrap compiler should be a small, auditable C++ seed compiler because the repository already has Clang, C++17 native code, LLVM emission, Termux support, and ARM64 cross-compilation infrastructure.

A self-hosted compiler does not mean that every tool in the ecosystem must be written in Holy Fitra immediately. It means the compiler that translates Holy Fitra source into native code can compile itself without invoking Python. The AI training libraries, model tools, TUI, and research utilities can migrate later.

## 1. Define the exact self-hosting boundary

There are three different claims that are often confused.

| Claim | Meaning | Required for self-hosting? |
|---|---|---:|
| Holy Fitra has a separate syntax | `.hf` source is not Python source | No, already true |
| Holy Fitra has a native compiler | `.hf` is translated to LLVM/native code | Partly true today |
| Holy Fitra compiler is self-hosted | The compiler executable is built from Holy Fitra source without Python | **Yes, this is the target** |
| Entire AI ecosystem is Holy Fitra-native | Training, agents, TUI, deployment, and kernels are all Holy Fitra | No, later milestone |

The first target should therefore be a **self-hosted compiler core**, not a self-hosted version of every current Python module.

The final command should eventually look like this:

```bash
./holyfitra check app.hf
./holyfitra emit-llvm app.hf -o app.ll
./holyfitra build app.hf -o app --target=aarch64-linux-android21
```

The `holyfitra` executable in that command must be a native Holy Fitra compiler binary. Python may still exist in the repository for benchmarks, migration tests, documentation tooling, or optional AI utilities, but it must not be required for those compiler commands.

## 2. Use a non-Python Stage 0 seed compiler

Because the current compiler is Python-hosted, Holy Fitra cannot immediately compile its own compiler without a seed. A seed compiler is normal in language development. The critical decision is what the seed is allowed to be.

For this project, the recommended Stage 0 compiler is `holyfitra_bootstrap.cpp`. It should be a small C++17 executable that supports only the restricted subset needed to compile the first Holy Fitra compiler. It should not attempt to implement the full AI language, tensor runtime, Android runtime, or advanced optimization system.

| Stage 0 property | Recommendation |
|---|---|
| Implementation language | C++17, with no Python dependency |
| Output | Canonical LLVM IR or a compact internal object format lowered to LLVM |
| Parser | Hand-written lexer and recursive-descent parser |
| Type system | `bool`, signed integers, `usize`, pointers/slices, structs, functions, `void` |
| Control flow | Blocks, `if`, `while`, `return`, local bindings |
| Memory | Explicit arenas and slices; no garbage collector initially |
| Error handling | Structured `Result`-like error values and source spans |
| Target | x86-64 first, AArch64 object generation immediately after |
| Dependencies | C++ standard library and Clang/LLVM command-line tools only |
| Forbidden dependency | Python, Python packages, Python subprocesses, Python-generated compiler files |

The seed compiler should be intentionally boring. It needs to compile a compiler, not run a transformer. A small seed is easier to audit, port to Termux, cross-compile to AArch64, and eventually replace.

The first seed language subset could look like this:

```holyfitra
struct Span {
    start: usize
    end: usize
}

fn lex(source: borrow [u8]) -> Result[TokenBuffer, Diagnostic] {
    // bootstrap-compatible implementation
}

fn parse_program(tokens: borrow TokenBuffer) -> Result[Program, Diagnostic] {
    // bootstrap-compatible implementation
}

fn emit_llvm(program: borrow Program, target: borrow [u8]) -> Result[String, Diagnostic] {
    // bootstrap-compatible implementation
}
```

The exact syntax can evolve, but the bootstrap subset must be frozen before the Stage 1 compiler is written. Otherwise, Stage 0 will continuously grow until it becomes a second full compiler.

## 3. Build the Holy Fitra compiler in Holy Fitra

The first self-hosted compiler should be a new compiler core rather than a line-by-line translation of the Python file. The current `holyfitra_compiler.py` is valuable as a semantic reference, but its implementation style is optimized for rapid prototyping and Python convenience.

The new compiler should be split into explicit modules:

```text
compiler/
  source.hf       // public compiler entry point
  span.hf         // source locations and ranges
  diagnostics.hf  // structured errors and warnings
  lexer.hf        // UTF-8/ASCII tokenization
  parser.hf       // recursive-descent parser
  ast.hf          // syntax tree
  types.hf        // type identities and ownership modes
  resolver.hf     // names, modules, imports, function maps
  effects.hf      // direct/transitive effect graph
  hir.hf          // typed high-level IR
  mir.hf          // control-flow and ownership-oriented IR
  llvm.hf         // canonical LLVM text/object emission
  cache.hf        // digest-keyed incremental cache
  driver.hf       // CLI, files, targets, subprocesses
  main.hf         // compiler executable entry point
```

The compiler should initially compile only the existing scalar language subset. Tensor syntax, QAT, agents, and model-development features should be integrated after the compiler reaches a stable self-hosting fixed point.

## 4. Introduce a real compiler IR boundary

The existing Python compiler has an AST and direct LLVM emission. That is sufficient for a prototype, but self-hosting needs a stable intermediate representation so the compiler can evolve without coupling parsing directly to backend string generation.

The recommended pipeline is:

```text
Source
  ↓
Tokens
  ↓
AST
  ↓ name resolution
Typed HIR
  ↓ ownership/effect validation
MIR
  ↓ control-flow lowering
Backend IR
  ↓
LLVM IR
  ↓
object/executable
```

### HIR

HIR should represent user-level functions, typed calls, hybrid declarations, effects, ownership modes, and source spans. It should still be easy to inspect and diagnose.

### MIR

MIR should represent basic blocks, explicit branches, local values, calls, returns, ownership transitions, cancellation checks, and reducer boundaries. This is where sequential and parallel hybrid semantics should become explicit.

A parallel hybrid should lower conceptually to:

```text
branch_task left(input)
branch_task right(input)
await ordered_results [left, right]
reduced = call combine(left_result, right_result)
return reduced
```

The first self-hosted backend does not need to spawn native threads immediately. It should first preserve the semantics and emit deterministic direct calls. Later, a scheduler-aware MIR lowering can turn `branch_task` into submissions to the Holy Fitra work-stealing runtime.

### Canonical serialization

Every IR should have a canonical text or binary representation with:

| Requirement | Purpose |
|---|---|
| Explicit schema version | Reject stale caches and incompatible artifacts |
| Stable field ordering | Reproducible digests |
| Explicit integer widths | Prevent host-dependent behavior |
| Source spans | Preserve diagnostics |
| Effect metadata | Preserve safety checks |
| Target metadata | Prevent cross-target cache collisions |
| Stable symbol IDs | Avoid name-order instability |

This enables the Python compiler, C++ Stage 0 compiler, and Holy Fitra Stage 1 compiler to compare their outputs during migration.

## 5. Minimal standard library needed for the compiler

The compiler cannot be self-hosted if the language lacks basic host capabilities. The first standard library should be small and deterministic.

| Standard-library area | Minimum functions |
|---|---|
| Bytes and strings | Length, indexing, slicing, comparison, UTF-8 validation, formatting |
| Collections | Dynamic array, fixed array, hash map, ordered map, string builder |
| Files | Read file, write file, atomic replace, metadata, directory creation |
| Paths | Join, normalize, extension, parent, canonical display |
| Diagnostics | Source spans, severity, error lists, formatted messages |
| Process | Spawn Clang/LLVM, capture stdout/stderr, exit status |
| Time | Monotonic clock for benchmarks and diagnostics |
| Hashing | SHA-256 or a deterministic project hash |
| Memory | Arena allocation, aligned allocation, explicit release |
| Concurrency | Later: threads, futures, cancellation tokens, bounded queues |

The compiler should use arenas for AST/HIR/MIR allocation during the first implementation. Arena allocation is simpler than ownership-heavy general-purpose memory management and fits compiler lifetimes well: most compiler objects live until compilation ends.

The standard library should not depend on Python-compatible behavior. For example, file iteration order, hash-map iteration order, integer overflow behavior, string encoding, and path normalization must be explicitly specified.

## 6. The bootstrap chain

The complete bootstrap should use reproducible stages.

### Stage 0: external seed

`holyfitra_bootstrap.cpp` is compiled with the system C++ compiler:

```bash
clang++ -std=c++17 -O2 holyfitra_bootstrap.cpp -o hf0
```

`hf0` supports only the bootstrap subset and compiles the Holy Fitra compiler sources into `hf1`.

```bash
./hf0 compiler/main.hf -o hf1.ll
clang -O2 hf1.ll -o hf1
```

At this point, `hf1` is a native compiler whose implementation is written in Holy Fitra, but it was compiled by the external C++ seed.

### Stage 1: self-rebuild

The newly created compiler compiles its own source:

```bash
./hf1 compiler/main.hf -o hf2
```

`hf2` should be functionally equivalent to `hf1`. The compiler must then compile a corpus of ordinary Holy Fitra programs and produce equivalent diagnostics, IR, and objects.

### Stage 2: fixed-point verification

The self-hosting claim becomes credible when repeated rebuilds stabilize:

```text
hf0 → hf1
hf1 → hf2
hf2 → hf3
```

The canonical compiler artifact, compiler IR, and output for a fixed corpus should be identical or equivalent according to a documented normalization rule. Differences in timestamps, temporary paths, UUIDs, or unordered metadata must not appear in compiler output.

## 7. Migration strategy from the current Python compiler

The Python compiler should remain active during migration. It becomes the oracle rather than the production compiler.

| Migration step | Python role | New compiler role |
|---|---|---|
| 1 | Reference behavior | Stage 0 compiles lexer/parser skeleton |
| 2 | Differential oracle | Stage 1 compiles scalar compiler core |
| 3 | Regression oracle | Stage 1 compiles itself |
| 4 | Optional tooling | Self-hosted compiler becomes default |
| 5 | Historical implementation | Python compiler is archived or retained only for research |

For every language feature, the migration harness should run both compilers on the same source and compare:

```text
accepted/rejected status
error code and source span
canonical AST or HIR
canonical effect graph
canonical LLVM IR
native object symbol list
program exit behavior
```

The comparison should allow documented differences in diagnostic wording, but not differences in semantics. A source program accepted by one compiler and rejected by the other is a migration failure until explicitly explained.

## 8. How to handle LLVM without Python

The self-hosted compiler does not need to implement a complete machine-code backend immediately. It can emit canonical LLVM IR text and invoke Clang/LLVM as external native tools.

That means the final architecture can be:

```text
Holy Fitra compiler executable
  ├── lexer/parser/type checker written in Holy Fitra
  ├── HIR/MIR written in Holy Fitra
  ├── LLVM text emitter written in Holy Fitra
  └── process API invokes clang/llc/llvm-as
```

This is still self-hosted because Python is not required. Clang and LLVM are normal backend dependencies, similar to how many language implementations use an external assembler, linker, or system library.

Later, Holy Fitra can use the LLVM C API or a native LLVM library binding if textual emission becomes a bottleneck. That should not be the first step. Canonical LLVM text is easier to debug, compare, cache, and validate during bootstrap.

## 9. Verification gates for self-hosting

Self-hosting must have stronger gates than ordinary feature development.

| Gate | Required result |
|---|---|
| Python-independent build | Compiler build succeeds with Python removed from `PATH` |
| Stage-0 build | C++ seed builds the first Holy Fitra compiler |
| Self-rebuild | Stage 1 compiles its own source successfully |
| Fixed-point rebuild | Stage 2 and Stage 3 outputs are stable or canonically equivalent |
| Differential semantics | Python and self-hosted compilers agree on accepted programs and diagnostics |
| Negative tests | Both compilers reject invalid types, effects, ownership, reducers, and return paths |
| LLVM validity | `llvm-as` or Clang accepts every emitted module |
| Native execution | Host scalar programs run with expected exit values |
| AArch64 artifact | Representative programs cross-compile to non-empty ARM64 objects |
| Cache reproducibility | Cache identity includes source, target, compiler schema, and backend version |
| Sanitizers | Stage 0 and native runtime pass ASAN/UBSAN where applicable |
| Termux | The bootstrap process works without `sudo` and with Termux-compatible tools |
| Python absence | No generated compiler command, build script, or compiler executable imports Python |

A practical no-Python test should run in a restricted environment:

```bash
env -i \
  PATH=/usr/bin:/bin \
  HOME="$PWD/.bootstrap-home" \
  ./hf1 check examples/hello.hf
```

The build should also scan generated compiler dependencies and reject accidental Python subprocesses or Python-specific paths.

## 10. Recommended implementation order

The first implementation milestone should not attempt full self-hosting. It should establish the seed boundary and compile a tiny Holy Fitra program.

### Milestone A: Stage-0 seed compiler

Create:

```text
bootstrap/holyfitra_bootstrap.cpp
bootstrap/bootstrap_subset.hf
bootstrap/test_bootstrap_subset.hf
bootstrap/README.md
```

The seed should compile functions, integers, local bindings, arithmetic, returns, and direct calls. It should emit valid LLVM for x86-64 and AArch64. Add tests for malformed syntax and wrong types immediately.

### Milestone B: Holy Fitra compiler core skeleton

Write a small Holy Fitra compiler that can parse itself as data. It should initially support only:

```text
bytes, strings, arrays, structs, functions, loops, if, return, file reads, file writes
```

It should emit a canonical token stream or AST dump before it emits complete LLVM. This makes debugging the bootstrap much easier.

### Milestone C: Self-host the scalar frontend

Port the lexer, parser, AST, type checker, resolver, effect graph, and scalar LLVM emitter. Keep the current Python compiler as the differential oracle. Do not port tensors or agents yet.

### Milestone D: Add the driver and cache

Implement file paths, target selection, SHA-256 identity, cache schema, atomic writes, diagnostics, and Clang process invocation in Holy Fitra. The self-hosted compiler should then be able to replace the current Python CLI for `check`, `emit-llvm`, and `build`.

### Milestone E: Fixed-point and cross-target verification

Compile the compiler with itself repeatedly, compare artifacts, and cross-compile the compiler to AArch64. Only after these gates pass should the self-hosted executable become the repository’s default compiler command.

## 11. What should not be done

The project should not translate the entire Python compiler line by line. That would preserve Python-specific assumptions, dynamic containers, exception-driven control flow, and hidden allocation behavior.

The project should not self-host the entire AI platform before the compiler core is stable. Training, transformer, deployment, and agent modules can remain Python reference implementations while the scalar compiler reaches a reproducible fixed point.

The project should not claim self-hosting merely because a Python script generates native code. The correct proof requires the compiler source itself to be compiled by a non-Python seed and then compiled by its own output.

The project should not make native parallel hybrid lowering create unrestricted threads. The future lowering should submit typed branch tasks to the existing bounded scheduler, propagate cancellation and deadlines, and reduce results deterministically.

## 12. The most important architectural decision

The most important decision is to freeze a **minimal bootstrap subset** and a **stable compiler IR contract** before implementing the self-hosted compiler. Without those boundaries, the seed compiler will expand indefinitely and the project will never reach a fixed point.

The recommended first concrete task is:

> Implement `holyfitra_bootstrap.cpp`, a no-Python C++17 Stage-0 compiler that supports the minimal scalar subset and emits canonical LLVM IR for x86-64 and AArch64.

Once that exists, the next task is to write `compiler/main.hf` in the restricted Holy Fitra subset and use `hf0` to build the first self-hosted compiler. The current Python compiler remains the oracle until `hf1` and its self-rebuild pass all semantic, artifact, reproducibility, Termux, sanitizer, and AArch64 gates.

## Final target

The final architecture should look like this:

```text
holyfitra compiler source (.hf)
        ↓
self-hosted native Holy Fitra compiler
        ↓
HIR/MIR + effect/resource verification
        ↓
LLVM IR
        ↓
Clang/LLVM backend
        ↓
x86-64 executable / AArch64 Android object
        ↓
Holy Fitra native runtime, scheduler, kernels, and model artifacts
```

Python can remain useful for experimentation and migration tests, but it must no longer be a hidden requirement for compiling Holy Fitra itself.
