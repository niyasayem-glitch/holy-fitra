# Holy Fitra v1 Release Contract

**Status:** Implementation target

**Purpose:** Define a runnable, reproducible first release without claiming that every planned AI subsystem or fixed-point self-hosting milestone is already complete.

## Release promise

Holy Fitra v1 is a **native-first, bounded, Termux-friendly compiler and runtime distribution**. A clean checkout must be able to build a seed compiler without Python, compile and run the supported scalar Holy Fitra subset, emit and verify LLVM IR, run deterministic project tests, and produce a content-addressed release manifest. Python remains an optional development oracle for advanced AI experiments and differential testing; it is not a dependency of the bootstrap compiler path.

“Self-sustaining” means that the release contains its own seed compiler, runtime contract, test fixtures, build scripts, diagnostics, and reproducibility checks. It does not mean that the compiler can already compile its entire source tree, that all tensor/agent features are native, or that an Android device is available. Those stronger claims require separate evidence.

## v1 supported language

The v1 native language contract covers modules, comments, `i32`, `i64`, `bool`, `void`, string literals, typed function parameters, local declarations, assignments, integer and boolean expressions, comparisons, short-circuit logical operators, direct function calls, `if/else`, `while`, fixed arrays, named structs, field access, bounded dynamic integer arrays through the Stage-0 runtime, and returns. The accepted entry point for an executable is `fn main() -> i32` or `fn main() -> i64` with no parameters.

Unsupported syntax must fail with a stable diagnostic. Tensor planning, quantization, ragged attention, speculative decoding, agent tools, Obsidian integration, and Android JNI are v1 companion subsystems rather than prerequisites for the native scalar compiler’s bootstrap contract. They may be packaged and tested independently, but their presence must never make malformed scalar source valid.

## v1 commands

| Command | Native v1 requirement |
|---|---|
| `holyfitra-bootstrap --help` | Works with no Python runtime. |
| `holyfitra-bootstrap INPUT.hf -o OUTPUT.ll` | Parses, validates, and emits deterministic LLVM text. |
| `holyfitra-bootstrap --target=aarch64-linux-android21 ...` | Emits an AArch64-targeted artifact; this is cross-compilation evidence only. |
| `holyfitra check INPUT.hf` | Validates the source and returns nonzero on any diagnostic. |
| `holyfitra emit-llvm INPUT.hf -o OUTPUT.ll` | Emits only verified native-subset LLVM. |
| `holyfitra build INPUT.hf -o OUTPUT` | Builds an executable only after source and LLVM validation. |
| `holyfitra run INPUT.hf` | Executes with bounded wall-clock and output behavior; unrestricted execution is not implied. |
| `holyfitra test PROJECT` | Runs bounded project tests and fails closed on missing or failed tests. |
| `holyfitra package PROJECT -o MANIFEST` | Produces a deterministic manifest with artifact identity and toolchain metadata. |
| `holyfitra doctor` | Reports available host, Termux, LLVM, Android, and optional-Python capabilities without inflating them. |

The native bootstrap executable is the release foundation. The Python CLI can remain a richer compatibility wrapper during migration, but the release test suite must prove which commands are native-only, Python-assisted, or unavailable.

## Self-sustaining build chain

The release chain is:

```text
checked-in C++17 seed + C11 runtime
        -> holyfitra-bootstrap
        -> native scalar .hf source
        -> verified LLVM IR
        -> host executable or AArch64 object
        -> deterministic manifest and test report
```

The first self-hosting checkpoint is not fixed-point completion. It is a **native bootstrap contract**: the seed builds from a clean checkout, State 1–9 fixtures remain compilable without Python, malformed input fails closed, the generated compiler artifacts are reproducible, and all required diagnostics are available from the native path. State 10 CFG/MIR and complete compiler self-rebuild remain post-v1 milestones unless separately proven.

## Resource and safety boundaries

Every source read, parser arena, emitted module, model, queue, process, test output, telemetry file, and package payload has a bounded limit. Arithmetic is checked before conversion or allocation. Native handles are opaque and lifecycle-checked. Native requests reach one terminal state. The package format records hashes and version information, and verification is required before an artifact is treated as a valid release product.

The v1 safety policy is fail-closed: an invalid source, unsupported construct, stale handle, malformed buffer, invalid numeric value, missing compiler tool, failed test, or non-finite measurement produces a structured error and nonzero status rather than a soft success.

## Platform matrix

| Platform/evidence | v1 meaning |
|---|---|
| x86-64 Linux | Primary host regression and executable validation. |
| Termux host | Required compatibility path using `pkg`, no `sudo`, and no Python dependency for bootstrap. |
| AArch64 target object | Cross-compilation artifact validation only. |
| Android SDK/NDK build | Required before claiming Android package readiness. |
| Physical arm64 Android device | Required before claiming NEON/SVE, big.LITTLE, thermal, latency, or memory results. |
| Fixed-point self-hosting | Not a v1 claim until repeated complete compiler rebuilds stabilize. |

## v1 acceptance gates

A v1 candidate is publishable only when the following are demonstrated from a clean checkout:

1. The seed compiler builds with the documented host or Termux commands and does not import, invoke, or require Python.
2. Positive and negative native fixtures pass, including duplicate names, unknown symbols, invalid types, malformed delimiters, deep nesting, oversized source, invalid returns, and unsupported syntax.
3. LLVM output is checked before linking or execution, and deterministic output comparisons pass across two independent builds.
4. State 1–9 no-Python bootstrap fixtures pass with sanitizer coverage where supported.
5. Cache and package tampering tests fail closed.
6. Runtime, scheduler, ragged, and NibbleFlow host tests pass under strict warnings and ASAN/UBSan.
7. Termux-compatible host validation passes without `sudo`.
8. Release metadata distinguishes host executables, AArch64 artifacts, Android builds, and physical-device measurements.

Android Gradle/NDK packaging and physical-device execution are separate release gates. If the necessary tools or device are unavailable, the candidate must be labeled **v1 host candidate**, not Android-complete v1.

## Post-v1 roadmap

After the host v1 contract is green, the next milestones are canonical frontend unification, typed HIR, verified CFG/MIR, generation-safe Stage-0 ownership handles, generation-tagged JNI handles, authenticated model/deployment envelopes, structured evidence verification, and the complete Stage-1/Stage-2 fixed-point rebuild. New AI capabilities should lower through those contracts rather than create parallel semantics.
