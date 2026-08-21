# Holy Fitra

Holy Fitra is an AI-native programming language and runtime stack inspired by HolyC. It combines a fast native compiler path, typed tensor/effect planning, proof-carrying quantization, speculative decoding, privacy and consent contracts, ragged ARM64 attention, heterogeneous scheduling, JNI, and Android-facing Kotlin APIs.

The repository now includes a real command-line compiler driver for a native scalar subset. Tensor/effect source is lowered into verified HyperIR plans, while the AI and Android runtime layers provide numerical execution and optimized native kernels.

## Quick start on Linux or Termux

```bash
git clone https://github.com/niyasayem-glitch/holy-fitra.git
cd holy-fitra
bash termux-setup.sh --dry-run   # inspect packages without installing
python3 holyfitra_compiler.py --help
```

On a normal Linux host:

```bash
sudo pip3 install -e .
holyfitra --help
```

On Termux, run:

```bash
bash termux-setup.sh
source "$HOME/.local/bin/holyfitra-env" 2>/dev/null || true
```

The setup script uses Termux `pkg` packages rather than `sudo`, installs Python/Clang/LLVM/CMake tooling, and prefers the Termux NumPy package when available.

## Terminal development environment

Holy Fitra now includes a dependency-free terminal UI and REPL designed for Termux as well as Linux terminals. The TUI uses Python's standard `curses` module, so it does not require Textual or Rich.

Open the interactive workspace:

```bash
holyfitra tui .
```

The TUI supports file navigation with `j`/`k` or arrow keys, `c` to inspect the selected source, `p` to refresh its HyperIR/native plan summary, `r` to refresh the workspace, and `q` or Escape to exit. For scripts, CI, SSH sessions, and terminals without a real TTY, use the deterministic snapshot mode:

```bash
holyfitra tui . --snapshot
```

Start the interactive REPL:

```bash
holyfitra repl
```

Inside the REPL, `/help`, `/project PATH`, `/source`, `/check`, `/plan`, `/llvm OUTPUT`, `/build OUTPUT`, `/show`, `/clear`, and `/quit` are available. Source is never sent to a shell; it is buffered and passed through the compiler or HyperIR planner.

Inspect the current environment:

```bash
holyfitra doctor
```

Run the development benchmark dashboard:

```bash
holyfitra bench . --repeats 5 -o holyfitra-benchmark.json
```

The dashboard reports cold/warm frontend timing, HyperIR operation counts or native digests, proof-carrying precision selection, and ragged-attention reference error. These are local development diagnostics, not physical-device performance claims.

The doctor reports Python, Termux detection, Clang, LLVM, CMake, NumPy, curses, Android NDK, and backend readiness without claiming that a physical Android device is present.

## Create and build a project

```bash
holyfitra init hello --name hello
holyfitra check hello
holyfitra build hello -o hello/app
./hello/app
```

The generated source is:

```holyfitra
module hello

fn main() -> i32 {
    return 0
}
```

## Native language subset

The current native LLVM backend supports `i32`, `i64`, and `void`, typed function parameters, local declarations, function calls, integer arithmetic, returns, comments, constant folding, and deterministic content/target caching.

```holyfitra
module arithmetic

fn add(a: i32, b: i32) -> i32 {
    let c = a + b
    return c
}

fn main() -> i32 {
    return add(40, 2)
}
```

Compile and run:

```bash
holyfitra check arithmetic.hf
holyfitra emit-llvm arithmetic.hf -o arithmetic.ll
holyfitra build arithmetic.hf -o arithmetic
./arithmetic
```

For AArch64-oriented LLVM output:

```bash
holyfitra emit-llvm arithmetic.hf \
  --target=aarch64-linux-android21 \
  -o arithmetic.android.ll
```

A complete Android executable still requires the Android NDK/sysroot or the Android application’s CMake toolchain. Termux can compile the host-side native runtime and emit target IR, but Termux itself is not a replacement for the NDK when producing APK-linked native libraries.

## Evolving native language features

The native frontend now supports booleans, comparisons, logical operators, structured `if/else` blocks, path-sensitive return checking, compile-time constant folding, and explicit function effects.

```holyfitra
module safe_infer

fn infer(score: i32) -> i32 effects [model, memory] {
    if score >= 80 {
        return 1
    } else {
        return 0
    }
}

fn main() -> i32 {
    return infer(90)
}
```

Supported effect names are `io`, `network`, `tool`, `model`, `memory`, `thermal`, `random`, and `unsafe`. Unknown or duplicate effects are rejected. Effects are preserved in compiler diagnostics and LLVM metadata; later compiler phases will enforce effect capability propagation across call graphs.

## Ownership and AI safety contracts

Holy Fitra now exposes explicit ownership modes for function parameters:

```holyfitra
fn inspect(x: borrow i32) -> i32 {
    return x
}

fn update(x: borrow_mut i32) -> i32 {
    return x + 1
}
```

The available modes are `owned`, `borrow`, `borrow_mut`, and `shared`. The compiler rejects multiple `borrow_mut` parameters in one function and preserves ownership metadata in diagnostics and LLVM comments. This is the first layer of a future lifetime checker for tensor buffers, KV caches, consent tokens, and native request handles.

Structured task metadata can be attached to a function:

```holyfitra
fn decode(x: borrow i32) -> i32 effects [model, memory] task [async, priority=5, deadline_ms=50, capacity=4, supervised] {
    return x
}
```

Task metadata is explicit and bounded. It records asynchronous intent, priority, deadline, capacity, cancellation, and supervision policy without creating hidden threads. The compiler validates positive capacity/deadlines and emits the metadata for later lowering into the Android scheduler and structured runtime.

The runtime contract layer is available through:

```bash
holyfitra contracts
```

It validates `Option`/`Result` exclusivity, ownership generations, bounded task specifications, supervisor child uniqueness, cancellation/deadline metadata, uncertainty evidence provenance, and int4 kernel proof requirements. It also emits deterministic kernel specialization identities for operation, dtype, device, layout, shape, proof, and fallback precision. The implementation is in `holyfitra_contracts.py` and is intentionally deterministic: it does not create hidden threads, access the network, or execute models.

Native function checking now computes a call graph and transitive effect closure. If `decode` declares `[model, memory]`, every safe caller must also declare those effects; `unsafe` is the explicit escape hatch. The JSON output includes `call_graph` and `effective_effects`, making safety review inspectable in the TUI, REPL, and CI.

## Tensor, capability, and HyperIR planning

```holyfitra
module tensor_demo

capability PublicRead {
    allow files.read("/data/public/")
    deny files.write
}

fn infer(x: Tensor<[1, 4], f16, device=neon>) -> Tensor<[1, 4], f16> {
    budget memory <= 32 MiB
    let w: Tensor<[4, 4], int4, device=neon>
    let y = matmul(x, w)
}
```

Use:

```bash
holyfitra check tensor_demo.hf
holyfitra plan tensor_demo.hf -o tensor_demo.plan.json
```

The plan contains validation diagnostics, budgets, effects, HyperIR digest, and selected kernel lowering. The tensor planner and scalar LLVM backend are deliberately separate until the tensor pointer/shape ABI is completed.

## AI runtime demonstrations

```bash
python3 hyperc_nn.py
python3 hyperc_transformer.py
python3 hyperc_proof_quant.py
python3 hyperc_hybrid_quant.py --tokens 32 --calibration-samples 64
python3 hyperc_adaptive_speculative.py
python3 holy_fitra_runtime.py
python3 holy_fitra_execution_plan.py
```

The AI stack includes dense layers and autodiff, transformer attention and KV caching, int4/int8/f16 selection with calibration gates, adaptive speculative decoding, privacy-flow and consent contracts, reversible receipts, and deterministic execution plans.

## Native and Android validation

```bash
python3 validate_nibbleflow.py
python3 validate_holy_fitra_ragged.py
bash termux-build.sh --host-tests
```

The Android NDK integration is represented by `CMakeLists.txt`, `CMakeLists_benchmark.txt`, JNI sources, and Kotlin wrappers. Physical ARM64 Android validation is required for real NEON/SVE, big.LITTLE, frequency, and thermal claims.

## Package a project

```bash
export HOLYFITRA_PACKAGE_SECRET='store this outside the repository'
holyfitra package hello \
  --version 0.1.0 \
  --target android.arm64 \
  -o hello.hfpkg.json
```

The package manifest is content-addressed and can be verified with the existing `hyperc_package.py` API. Do not commit signing secrets.

## Test suite

```bash
python3 -m unittest -v \
  test_holyfitra_compiler.py \
  test_language_core.py \
  test_hyperir.py \
  test_package.py \
  test_holy_fitra_runtime.py \
  test_holy_fitra_execution_plan.py \
  test_holy_fitra_ragged.py \
  test_holy_fitra_dynamic_prefill.py \
  test_smooth_runtime.py
```

Native scheduler tests require Clang and the ragged kernel object. `termux-build.sh --host-tests` performs this build on Termux or Linux.

## Current boundary

Holy Fitra is beyond a documentation-only prototype: it has an installable CLI that parses, checks, plans, emits LLVM, links native executables, initializes projects, caches compilation, and creates signed package manifests. The remaining major compiler milestone is a self-hosted frontend with full tensor ABI lowering, richer control flow and data types, dependency-aware incremental compilation, and direct Android NDK library packaging.
