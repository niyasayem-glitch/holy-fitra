# Holy Fitra Language Evolution Matrix

## Design principle

Holy Fitra should not copy entire languages. It should combine their strongest ideas behind one coherent execution model: **safe ownership, explicit effects, typed uncertainty, shape-aware tensors, deterministic compilation, structured concurrency, proof-carrying optimization, and Android-native deployment**.

> The goal is not maximum syntax. The goal is maximum useful capability per concept, with no hidden authority, hidden allocation, hidden precision loss, or hidden concurrency.

## Feature matrix

| Source family | High-value idea | Holy Fitra decision | Why it fits |
|---|---|---|---|
| C/C++ | Predictable layout, zero-cost abstractions, RAII, direct ABI control | Adopt explicit layouts, `extern` ABI blocks, deterministic destruction, and opt-in unsafe regions | Needed for ARM64 kernels and JNI without making the whole language unsafe |
| Rust | Ownership, borrowing, lifetimes, traits, enums, pattern matching | Adopt resource ownership and borrow modes for tensors, buffers, consent tokens, and receipts; adapt traits as capabilities | Prevents use-after-free, stale KV-cache handles, consent reuse, and accidental buffer aliasing |
| Zig | Explicit allocators, error unions, compile-time execution, simple cross compilation | Adopt explicit allocator parameters, `Result`-style errors, compile-time shape checks, and target profiles | Fits Termux/Android builds and makes memory/target choices visible |
| Go | Typed channels and simple synchronization | Adapt bounded typed channels for model pipelines and scheduler handoff; prohibit unbounded implicit goroutines | Useful for backpressure and predictable AI pipelines |
| Erlang/OTP | Supervision trees and restartable workers | Adopt typed supervisors for model workers, JNI requests, and thermal recovery | Converts native/runtime faults into controlled restart or safe fallback decisions [3] |
| Swift | Structured concurrency, actors, cancellation, explicit `await` | Adopt structured tasks, actor-isolated state, cancellation propagation, and explicit suspension points [4] | Fits speculative decoding, Android requests, and UI/runtime integration |
| Haskell | Algebraic data types, type classes, pure transformations | Adopt sum/product types, exhaustive matching, and pure plan-building functions | Makes `Prediction`, `Claim`, `Fact`, `Option`, `Result`, and policy outcomes explicit |
| Julia | Multiple dispatch | Adapt constrained dispatch for tensor dtype/device/layout combinations | Lets kernel selection be type-directed without runtime string switches [5] |
| Kotlin | Sealed hierarchies and coroutine-friendly Android APIs | Adopt sealed runtime states and typed Android request results | Maps well to JNI status, thermal state, request lifecycle, and safety outcomes [6] |
| Python | Fast experimentation, reflection, notebooks, huge AI ecosystem | Keep as an interop/experimentation layer, not as the trusted compiler core | Preserves access to NumPy/PyTorch/ONNX while native Holy Fitra remains auditable |
| Java/C# | Mature tooling, packages, managed safety, reflection | Adopt package manifests, workspace tooling, debugger-friendly diagnostics, and explicit FFI boundaries | Useful developer experience without importing mandatory GC into kernels |
| TypeScript | Excellent diagnostics, structural typing, language-server ergonomics | Adopt source spans, error recovery, autocomplete-oriented symbol indexes, and JSON tooling | Improves the TUI, REPL, and future language server |
| Lisp/Clojure | Hygienic macros and programmable syntax | Defer unrestricted macros; adopt hygienic compile-time extensions later | Macros are powerful but can undermine auditability and deterministic builds |
| MLIR/LLVM | Extensible multi-level IR and reusable dialects | Adopt dialect-like HyperIR layers: core, tensor, quant, effect, Android, and proof | Prevents one monolithic IR from becoming a bottleneck [7] |
| SQL/dataflow languages | Declarative execution and query planning | Adapt declarative model/pipeline blocks with explicit materialization and privacy boundaries | Helps AI data preparation without hiding costly transfers |
| CUDA/Mojo-like systems | Kernel specialization, tile-level control, accelerator-aware compilation | Adopt explicit kernel contracts, tile shapes, vector lanes, and target capabilities | Directly supports NibbleFlow, ragged attention, NEON/SVE, and future NPU backends |

## Features to implement first

The first implementation wave should add features that increase language expressiveness while remaining compatible with the current compiler:

1. **Control flow:** booleans, comparisons, `if/else`, and explicit return-path checking.
2. **Algebraic result values:** `Result<T, E>` and `Option<T>` at the type-system and runtime-contract level.
3. **Resource modes:** `move`, `borrow`, `borrow_mut`, and `share` annotations for tensors, buffers, consent tokens, and request handles.
4. **Explicit effects:** function declarations that list `io`, `network`, `tool`, `model`, `memory`, and `thermal` effects, checked against capability policies.
5. **Structured concurrency:** typed tasks/channels with cancellation and bounded capacity.
6. **Kernel dispatch traits:** compile-time selection by dtype, device, layout, quantization proof, and thermal policy.
7. **Declarative model blocks:** named layers, calibration data, precision gates, and fallback policy compiled into HyperIR.
8. **Workspace tooling:** formatter, source spans, incremental symbol index, TUI diagnostics, package manifests, and reproducible builds.

## Deferred or rejected features

Holy Fitra should not copy garbage collection into the kernel path, implicit dynamic dispatch in performance-critical code, unrestricted macros, hidden network access, silent quantization, unstructured background tasks, or implicit exception-driven authority. Those features may exist behind explicit interop boundaries but should not be the default language semantics.

## References

[1]: https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html "The Rust Programming Language: Understanding Ownership"
[2]: https://go.dev/tour/concurrency/2 "A Tour of Go: Channels"
[3]: https://www.erlang.org/doc/system/design_principles.html "Erlang/OTP Design Principles"
[4]: https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/ "The Swift Programming Language: Concurrency"
[5]: https://docs.julialang.org/en/v1/manual/methods/ "Julia Documentation: Methods and Multiple Dispatch"
[6]: https://kotlinlang.org/docs/sealed-classes.html "Kotlin Documentation: Sealed Classes and Interfaces"
[7]: https://mlir.llvm.org/ "MLIR: Reusable and Extensible Compiler Infrastructure"
