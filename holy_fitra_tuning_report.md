# Holy Fitra Tuning Report

## Scope

This tuning pass targeted the measured compiler and AI calibration paths while preserving ownership contracts, effect call graphs, proof-carrying quantization, HyperIR, TUI/REPL, native kernels, scheduler, JNI, Android APIs, packaging, and Termux support.

## Retained optimizations

| Area | Optimization | Guard |
|---|---|---|
| LLVM emission | Hoisted whole-program semantic validation out of per-function emission | Compiler and full regression tests |
| Native builds | Added content-addressed native artifact reuse keyed by source and target digest | First-build/cache-hit regression test and executable output check |
| Quantization | Added batched calibration matrix multiplication for int4, int8, and f16 candidates | Row-wise parity tests and proof gates |
| Quantization fallback | Cached float32 representation inside `Float16Matrix` | Float16 batched-output parity test |
| Validation tooling | Added tuning profiler and Termux coverage for quantization tuning | Python compile, shell syntax, native/sanitizer gates |

## Measurements

The initial compiler profiler reported approximately:

```text
warm emit LLVM median:    0.043 ms
native cold build:       80.9 ms
kernel contract median:  0.0015 ms
```

After validation hoisting, warm LLVM emission measured approximately:

```text
warm emit LLVM median:    0.024 ms
```

That is an observed reduction of roughly 45% for the measured two-function fixture. The fixture is small and host-only; it is not a 50,000-line or Android-device claim.

The integrated benchmark’s proof-carrying quantization path changed from an earlier observed approximately `6.61 ms` to approximately `4.52 ms` on the same sandbox-style demo shape after the batched calibration change. This is an observed host measurement, not a physical Android result. The optimized path preserved the selected `int4` precision and verified proof.

The final benchmark smoke run continued to pass for native compilation, proof-carrying quantization, and ragged attention. The ragged reference error remained approximately `1.79e-7` in the tuning fixture.

## Validation

The final tuning gates passed:

- 84 Python tests.
- Compiler, control-flow, ownership, effect graph, task metadata, contract, TUI, REPL, HyperIR, package, runtime, ragged, dynamic-prefill, smooth-runtime, and quantization-tuning tests.
- Python bytecode compilation for all modified Python modules.
- Bash syntax validation for Termux setup and build scripts.
- NibbleFlow numerical and AArch64 object validation.
- Ragged attention numerical and NEON/SVE object validation.
- AddressSanitizer and UndefinedBehaviorSanitizer scheduler integration.
- Contract CLI and benchmark dashboard smoke tests.

## Boundaries

The native artifact cache is content-addressed but currently local to each project’s `.holyfitra/cache` directory. Physical Android benchmark results still require a connected ARM64 device. The measured compiler fixture is small; large-project incremental performance remains a separate benchmark milestone. No optimization silently weakens safety or quantization quality gates.
