# Holy Fitra Quick Start

Holy Fitra is currently a **working prototype/research language**, not yet a self-hosted compiler. The Python frontend parses source, performs tensor/effect checks, lowers the program to HyperIR, and emits a deterministic compile plan. The Python, C/C++, and Kotlin components provide the AI runtime and Android deployment layers.

## 1. Prepare the workspace

```bash
cd /home/ubuntu/hyperc_llvm
python3 --version
clang --version
```

For the current prototype, run commands from `/home/ubuntu/hyperc_llvm` so imports resolve correctly.

## 2. Write a Holy Fitra source file

Create `hello.hf`:

```holyfitra
module hello.mobile

capability PublicRead {
    allow files.read("/data/public/")
    deny files.write
}

fn project(x: Tensor<[1, 64], f16, device=neon>) -> Tensor<[1, 32], f16> {
    budget memory <= 64 MiB
    let w: Tensor<[64, 32], f16, device=neon>
    let y = matmul(x, w)
}
```

The implemented frontend currently supports these constructs:

| Construct | Example | Meaning |
|---|---|---|
| Module | `module hello.mobile` | Names the compilation unit |
| Capability policy | `capability PublicRead { ... }` | Declares allowed and denied effects |
| Allow rule | `allow files.read("/data/public/")` | Allows a scoped operation |
| Deny rule | `deny files.write` | Denies an operation |
| Function | `fn project(...) -> Tensor<...>` | Declares a typed function |
| Tensor type | `Tensor<[1, 64], f16, device=neon>` | Shape, dtype, and target device |
| Layout | `Tensor<[1, 64], f16, device=neon, layout=row_major>` | Optional memory layout |
| Budget | `budget memory <= 64 MiB` | Adds a function resource budget |
| Tensor declaration | `let w: Tensor<[64, 32], f16>` | Declares a tensor value |
| Matrix multiplication | `let y = matmul(x, w)` | Creates a checked HyperIR matmul |

The current parser uses `matmul(x, w)` for the executable frontend. The architecture examples may also show `x @ w`; the `@` spelling is part of the planned surface syntax but is not the safest spelling for the current Python parser.

Tensor matmul dimensions must be provably compatible. For `A: Tensor<[M, K], ...>` and `B: Tensor<[K, N], ...>`, the result is inferred as `Tensor<[M, N], ...>`.

## 3. Compile Holy Fitra source to HyperIR

Use the frontend from Python:

```bash
python3 - <<'PY'
from hyperc_language_core import compile_source

source = open("hello.hf", encoding="utf-8").read()
plan = compile_source(source)

print("valid:", plan["valid"])
print("module:", plan["module"])
print("HyperIR digest:", plan["hyperir_digest"])
print("lowered plan:", plan["lowered_plan"])
print("diagnostics:", plan["diagnostics"])
PY
```

A compact one-liner is:

```bash
python3 -c 'from hyperc_language_core import compile_source; import json; print(json.dumps(compile_source(open("hello.hf").read()), indent=2, default=str))'
```

The frontend does not yet execute tensor values from `.hf` files. It validates declarations and builds HyperIR. Use the Python AI runtime modules for numerical execution.

You can also run the built-in demonstrations:

```bash
python3 hyperc_language_core.py
python3 hyperc_hyperir.py
```

Invalid programs return structured diagnostics rather than silently compiling. For example, a matmul whose inner dimensions do not match produces a `HYPER...` diagnostic and `valid: false`.

## 4. Run the AI runtime components

The current AI features are exposed as Python reference/runtime modules. Each module contains an executable demonstration:

```bash
python3 hyperc_nn.py
python3 hyperc_transformer.py
python3 hyperc_proof_quant.py
python3 hyperc_adaptive_speculative.py
```

The main responsibilities are:

| Module | Use |
|---|---|
| `hyperc_nn.py` | Tensor values, dense layers, ReLU, MSE autodiff, CPU/LLVM inference |
| `hyperc_transformer.py` | Multi-head self-attention, causal masking, layer normalization, GELU FFN, and KV cache |
| `hyperc_proof_quant.py` | Chooses int4, int8, or f16 only when calibration error gates pass |
| `hyperc_awq.py`, `hyperc_gptq.py`, `hyperc_hybrid_quant.py` | Calibration-aware quantization strategies |
| `hyperc_speculative.py` | Draft/target speculative decoding with transactional KV-cache commit/rollback |
| `hyperc_adaptive_speculative.py` | EWMA acceptance tracking, draft-length adaptation, and thermal-aware control |

For a numerical Python program, import the relevant classes and construct tensors or model specifications directly. The `.hf` frontend and these runtime APIs are currently separate layers; the planned compiler integration will connect typed Holy Fitra functions to runtime kernels.

## 5. Use privacy, consent, evidence, and execution contracts

Run the demonstrations:

```bash
python3 holy_fitra_runtime.py
python3 holy_fitra_execution_plan.py
```

The runtime is designed so an AI action carries more than ordinary function arguments. It can carry privacy-flow labels, a linear consent token, authority/capability information, an intent-firewall decision, an evidence class, a resource budget, replay information, and a reversible receipt.

Conceptually, use the runtime in this order:

```text
request intent
  -> verify capability and consent
  -> classify data flow and evidence
  -> enforce memory/energy/deadline budgets
  -> choose a deterministic kernel and precision
  -> execute
  -> return output plus proof/receipt
  -> commit or reverse the action
```

The important distinction is that a model prediction should not automatically be represented as a fact or an externally authorized action. The runtime separates uncertainty/evidence classes and requires policy checks before sensitive effects.

## 6. Run the LLVM/AOT subset

The lower-level prototype compiler handles its supported integer-function subset and emits LLVM/AOT artifacts:

```bash
python3 hyperc_llvm.py
python3 hyperc_batch.py
```

This path is separate from the richer tensor frontend. The intended architecture is:

```text
Holy Fitra source
  -> parser and semantic checks
  -> HyperIR
  -> proof-carrying execution plan
  -> LLVM/AOT or native Android kernel
```

The current implementation has the first three pieces in prototype form and native kernels/runtime pieces for Android. A complete self-hosted Holy Fitra compiler is still a future milestone.

## 7. Use the Android ARM64 runtime

The Android path consists of packed int4 NibbleFlow kernels, ragged attention kernels, the work-stealing scheduler, JNI, and Kotlin wrappers.

Validate the NibbleFlow native path on the host:

```bash
python3 validate_nibbleflow.py
```

The Android application links the native runtime through the checked-in `android-lib` Gradle library module. Its authoritative native graph is:

```text
android-lib/src/main/cpp/CMakeLists.txt
```

When an Android SDK/NDK and Gradle wrapper are available, build the module with:

```bash
./gradlew :android-lib:assembleRelease
```

The Kotlin-facing APIs are under `android-lib/src/main/java/`:

```text
android-lib/src/main/java/org/holyfitra/NibbleFlow.kt
android-lib/src/main/java/org/holyfitra/HolyFitraRuntime.kt
android-lib/src/main/java/com/holyfitra/benchmark/HolyFitraBenchmark.kt
```

A typical Android flow is:

```kotlin
val runtime = HolyFitraRuntime.create(/* runtime configuration */)
val request = runtime.submitMatvec(/* packed int4 model, input, dimensions */)
val result = request.await()
request.cancel()       // when cancellation is required
runtime.close()
```

Use `HolyFitraBenchmark` to collect p50, p95, p99 latency, throughput, and thermal observations. The native benchmark executable, when built by the NDK project, is run as:

```bash
./holy_fitra_device_benchmark_test
```

The benchmark must be run on a physical ARM64 Android device to make claims about NEON/SVE dispatch, big.LITTLE placement, frequency scaling, or thermal throttling. Host x86-64 results are only smoke tests and algorithmic comparisons.

## 8. Run the regression suite

The core Python tests can be run with:

```bash
python3 -m unittest -v \
  test_language_core.py \
  test_hyperir.py \
  test_package.py \
  test_holy_fitra_runtime.py \
  test_holy_fitra_execution_plan.py \
  test_holy_fitra_ragged.py \
  test_holy_fitra_dynamic_prefill.py
```

The native ragged scheduler test is built with Clang and C++17. The exact build command may vary with the local CMake/NDK configuration; the repository contains the scheduler test source and Android CMake integration.

## 9. Recommended first project

Start with a small model projection rather than a complete language application. Write a `.hf` module containing a capability policy, a memory budget, one tensor function, and one dimensionally valid `matmul`. Compile it to a HyperIR plan. Then implement the numerical execution in `hyperc_nn.py` or `hyperc_transformer.py`, select a proof-carrying precision with `hyperc_proof_quant.py`, and finally move the validated model to the NibbleFlow/Kotlin Android path.

This staged workflow is intentional: **the frontend proves structure and policy, the runtime executes numerical work, and the Android layer supplies optimized native kernels and scheduling**.

## Current status

Holy Fitra is usable today as a prototype toolchain and runtime stack, but it is not yet a single command such as `holyfitra build app.hf`. The practical command sequence is therefore:

```bash
# 1. Author and validate Holy Fitra syntax
python3 -c 'from hyperc_language_core import compile_source; print(compile_source(open("hello.hf").read()))'

# 2. Run AI reference implementations
python3 hyperc_nn.py
python3 hyperc_transformer.py

# 3. Validate precision and decoding systems
python3 hyperc_proof_quant.py
python3 hyperc_adaptive_speculative.py

# 4. Run safety/execution-contract demonstrations
python3 holy_fitra_execution_plan.py

# 5. Validate the native int4 path
python3 validate_nibbleflow.py
```

The next major compiler milestone is a self-hosted driver that accepts `.hf` files, invokes the parser and HyperIR verifier, lowers supported operations to LLVM or Android native kernels, links the runtime, and produces a runnable package.
