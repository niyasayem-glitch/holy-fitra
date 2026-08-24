# Holy Fitra self-hosting architecture

Holy Fitra has a **verified Stage-0** seed compiler written in C++17. It parses a bounded scalar language subset, validates it, emits textual LLVM IR, and can be built without Python. The current self-hosting states 1–9 are deterministic Holy Fitra milestone programs that validate frontend, symbols, typing, diagnostics, module loading, typed HIR, retained ASTs, and imported-call checks.

They are not yet a fixed-point compiler artifact. A fixed-point claim requires a linked Stage-1 compiler built from Holy Fitra source, recompiled by its own output until its compiler artifact and canonical output stabilize under reproducible checks.

## Package layers

| Layer | Contents | Verified command | Boundary |
| --- | --- | --- | --- |
| `basic` preset | `src/main.hf`, test, v1 manifest | `holyfitra-v1.sh check .` | Scalar Stage-0 subset only. |
| `selfhost-core` preset | Buildable entry plus explicit compiler-core units | `holyfitra-v1.sh test .` | Units are not linked into Stage-1 yet. |
| Manifest v2 | Source entry hash and whole source-tree digest | `holyfitra-v1.sh package .` | A manifest, not a source archive. |
| Portable bundle | Source tree, Stage-0 toolchain, runtime, manifest, build guide | `holyfitra-v1.sh bundle . -o project.tar.gz` | No Android NDK, APK, or physical-device execution evidence. |

The v1 toolchain treats a directory with `src/main.hf` as a project entry. This lets the same structured project work on Linux and Termux while keeping direct `.hf` input support for small experiments.
