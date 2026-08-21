# Holy Fitra Production Toolchain Upgrade

## Executive Summary

Holy Fitra now has a real user-facing compiler driver rather than only a Python API prototype. The new `holyfitra` command performs tokenization, recursive-descent parsing, typed scalar semantic checking, deterministic LLVM IR emission, native Clang linking, project initialization, HyperIR planning for tensor/effect programs, content-addressed compiler caching, and signed package-manifest creation.

The existing AI and Android stack was preserved and repaired where the repository snapshot had missing Python modules. Neural-network tensors/autodiff, transformer reference attention, quantized matrices, AWQ-style calibration, Android preallocated buffers, proof-carrying quantization, ragged attention, scheduling, JNI-facing native components, and package integrity now pass the available validation gates.

## New user-facing commands

| Command | Result |
|---|---|
| `holyfitra init demo` | Creates `holyfitra.toml` and `src/main.hf` |
| `holyfitra check source.hf` | Parses and validates native or legacy tensor/effect source |
| `holyfitra plan tensor.hf -o plan.json` | Emits a verified HyperIR execution plan |
| `holyfitra emit-llvm source.hf -o source.ll` | Emits LLVM IR, optionally with `--target=aarch64-linux-android21` |
| `holyfitra build source.hf -o app` | Compiles and links a native host executable |
| `holyfitra run source.hf` | Builds and executes a zero-argument `main` |
| `holyfitra package project -o app.hfpkg.json` | Creates an integrity-checked package manifest |

The command is available from the repository launcher and through editable installation from `pyproject.toml`:

```bash
cd /home/ubuntu/hyperc_llvm
sudo pip3 install -e .
holyfitra --help
```

## Native language subset

The first native executable subset supports:

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

Supported native types are currently `i32`, `i64`, and `void`. Supported expressions include integer literals, variables, function calls, parentheses, addition, subtraction, multiplication, and integer division. The compiler performs unknown-name checks, duplicate-function checks, argument-count/type checks, return-type checks, declaration checks, division-by-zero checks for constant expressions, and compile-time constant folding.

## Tensor and safety path

Tensor/effect source continues to use the existing HyperIR frontend. For example:

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

The plan includes diagnostics, HyperIR digest, effects, budgets, and the selected lowered kernel. The native LLVM backend and tensor HyperIR backend are intentionally separate until tensor pointer/shape ABI lowering is completed.

## Restored AI modules

The repository snapshot referenced several AI modules that were absent. The following compatible implementations were restored without changing the existing proof and safety contracts:

| Module | Capability |
|---|---|
| `hyperc_nn.py` | Typed tensor wrapper, dense layer, ReLU, MSE, reverse-mode autodiff |
| `hyperc_transformer.py` | Transformer spec, KV cache, scaled causal decode, GELU, identity-attention verifier helper |
| `hyperc_quantized_transformer.py` | Packed int4 and int8 matrices, quantized attention and feed-forward wrappers |
| `hyperc_awq.py` | Calibration-aware matrix wrapper with measured reconstruction MSE |
| `hyperc_android_transformer.py` | Preallocated Android-style key/value/output buffers and memory accounting |

The proof selector now evaluates int4, int8, and f16 candidates using the existing quality gates and correctly reports storage bytes and reconstruction error.

## Validation evidence

The following gates passed during this upgrade:

| Gate | Result |
|---|---|
| New compiler/project/package tests | Passed |
| Legacy language frontend tests | Passed |
| HyperIR and proof-quantization tests | Passed |
| Runtime, execution-plan, ragged, dynamic-prefill, smooth-runtime, and package tests | 63 tests passed in 0.460 seconds in the bounded suite |
| Native compiler smoke program | Returned exit code 42 as expected |
| Project-generated native program | Returned exit code 0 as expected |
| HyperIR tensor plan JSON parsing | Passed |
| Proof quantization demo | Passed with verified int4 candidate |
| Hybrid quantization demo | Passed with measured quality-gated fallback |
| NibbleFlow host validation | Passed |
| Ragged attention native validation | Passed; scalar and NEON fallback max error approximately `2.98e-7` |
| Native scheduler integration | Passed |
| AddressSanitizer/UndefinedBehaviorSanitizer ragged scheduler gate | Passed |
| Existing native runtime/topology/batch/device benchmark binaries | Passed |
| Physical Android device execution | Not performed |

One requested test filename, `test_holy_fitra_fabric.py`, is not present in the repository snapshot; the corresponding runtime/fabric functionality is covered by the available runtime and execution-plan tests.

## Important status boundary

This is a substantial transition from prototype-only use to a real executable compiler toolchain, but it is not yet the final self-hosted Holy Fitra compiler. The compiler is currently implemented in Python and emits LLVM IR for a deliberately safe scalar subset. Tensor source produces verified HyperIR plans, while native tensor ABI lowering, full control flow, pattern matching, richer numeric types, borrow/ownership analysis, and a self-hosted compiler implementation remain future milestones.

The Android native stack is also preserved as a separate deployment layer. A physical device is still required to validate actual ARM64 NEON/SVE behavior, big.LITTLE placement, frequency scaling, and thermal throttling.

## Next engineering milestones

The highest-value next steps are to add native tensor handles and ABI-stable runtime calls to LLVM lowering, implement control flow and structured data types, move the lexer/parser into a self-hosted or native frontend for sub-second incremental builds, add dependency-aware project compilation, and connect `holyfitra package` to Android NDK library/model artifacts with signed rollback lineage.
