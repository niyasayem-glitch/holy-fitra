# NibbleFlow Fused ARM64 Kernel Report

**Project:** Holy Fitra  
**Kernel family:** NibbleFlow  
**Status:** Host numerical validation and AArch64 object emission validated; physical Android execution not yet performed.

## Executive Summary

NibbleFlow is a fused int4 weight-only matrix-vector kernel family designed for Android ARM64 autoregressive decoding. It uses an output-tiled packed layout so four output channels share each input-pair access pattern. The kernel fuses packed nibble loading, signed int4 decoding, integer-style dot accumulation, per-group scaling, and bias addition inside one ABI call.

The implementation includes a Python packer and reference matvec, a portable scalar C implementation, an AArch64 NEON implementation, a stable C ABI, manifest metadata, native shared-library generation, and freestanding Android-targeted object generation. Six randomized shape cases, including odd input dimensions, odd output dimensions, non-power-of-two group sizes, and tail groups, passed native-versus-reference comparison with maximum absolute errors from `0` to approximately `9.54e-7`.

The generated object is an ELF64 relocatable file with **AArch64 machine type**, exported `nibbleflow_int4_f32_ref`, `nibbleflow_int4_f32`, and `nibbleflow_abi_version` symbols, and a size of **2,688 bytes** in the current build.

## 1. Packed Layout

NibbleFlow uses the following logical layout:

```text
packed[tile_out][group][pair_of_inputs][lane_out]
scale [tile_out][group][lane_out]
```

The default output tile is four lanes. Each packed byte contains two signed int4 weights:

```text
low nibble  = input index 2p
high nibble = input index 2p + 1
```

Signed decoding uses two’s-complement nibble interpretation:

```text
0..7  →  0..7
8..15 → -8..-1
```

For an output matrix with `out_dim` rows and `in_dim` columns:

| Quantity | Formula |
|---|---|
| Groups | `ceil(in_dim / group_size)` |
| Pairs per group | `group_size / 2` |
| Output tiles | `ceil(out_dim / 4)` |
| Packed bytes | `output_tiles × groups × pairs_per_group × 4` |
| Scale count | `output_tiles × groups × 4` |

The layout is intentionally output-tiled. During batch-1 decode, a kernel can load one input pair and update four output accumulators while reading four adjacent packed bytes and four scales.

## 2. C ABI

The stable ABI is:

```c
void nibbleflow_int4_f32(
    const float* input,
    const uint8_t* packed,
    const float* scales,
    const float* bias,
    float* output,
    int32_t in_dim,
    int32_t out_dim,
    int32_t group_size
);
```

The reference entry point has the same signature:

```c
void nibbleflow_int4_f32_ref(...);
```

The ABI version is exposed through:

```c
int32_t nibbleflow_abi_version(void);
```

The current ABI version is `1`. A production ABI should additionally bind alignment requirements, supported group sizes, accumulator semantics, NaN behavior, required CPU features, and manifest fingerprints.

## 3. Kernel Execution Strategy

### Portable reference path

The reference path processes one output channel at a time. It decodes each nibble, multiplies by the corresponding input value, accumulates within a group, multiplies by that group’s scale, and adds bias. It is intentionally straightforward and acts as the numerical oracle.

### AArch64 NEON path

The AArch64 path processes four output channels per tile. It uses NEON vector accumulators and a fused structure:

```text
load four packed bytes
  → decode low/high signed nibbles
  → broadcast two input values
  → multiply four output lanes
  → accumulate group contribution
  → multiply four per-lane scales
  → accumulate across groups
  → add four bias values
  → store valid output lanes
```

The implementation handles incomplete final output tiles and incomplete final input groups using explicit bounds checks. It is freestanding for object generation, so it does not require the host libc or a complete Android sysroot when emitting a relocatable object.

## 4. Proof and Manifest Metadata

Each packed matrix can emit a manifest containing:

```json
{
  "schema": "holy-fitra.nibbleflow/v1",
  "abi_version": 1,
  "kernel": "nibbleflow.int4.f32",
  "packed_dtype": "u8",
  "scale_dtype": "f32",
  "signed_quant": true,
  "nibble_order": "low_input_even_high_input_odd",
  "tile_order": "output_tile_group_pair_lane"
}
```

A production proof should extend this with the original weight hash, calibration hash, quantization algorithm, group size, kernel binary hash, compiler version, target CPU features, maximum calibration error, task-level quality gate, and device profile.

## 5. Validation Results

The validation harness generated randomized matrices and compared the native shared-library result with the Python reference:

| Output × input | Group size | Packed bytes | Native max absolute error | Result |
|---:|---:|---:|---:|---|
| 1 × 1 | 2 | 4 | 0 | Passed |
| 3 × 5 | 2 | 12 | 8.94e-8 | Passed |
| 7 × 19 | 6 | 96 | 4.77e-7 | Passed |
| 8 × 32 | 8 | 128 | 2.38e-7 | Passed |
| 11 × 37 | 10 | 240 | 9.54e-7 | Passed |
| 17 × 65 | 16 | 800 | 9.54e-7 | Passed |

All numerical cases passed the `1e-6` maximum-error gate.

The generated AArch64 object was inspected as follows:

| Property | Result |
|---|---|
| File type | ELF64 relocatable |
| Endianness | Little-endian |
| Machine | AArch64 |
| Object size | 2,688 bytes |
| Reference symbol | Present |
| NEON kernel symbol | Present |
| ABI version symbol | Present |

## 6. What the Kernel Fuses

NibbleFlow deliberately fuses the operations that otherwise create bandwidth and dispatch overhead:

| Operation | Separate implementation cost | NibbleFlow treatment |
|---|---|---|
| Nibble unpacking | Temporary int8 values or scalar decode | Inline signed-nibble decode |
| Dot product | Repeated matrix-library calls | Accumulation inside tile loop |
| Dequantization | Reconstructed float matrix | Scale applied per group in registers |
| Bias | Separate output pass | Added before store |
| Tail handling | Padding or separate kernels | Bounded final group/tile logic |
| Dispatch | Multiple framework operators | One stable ABI call |

## 7. Android Integration Plan

The Android integration should provide three variants:

| Variant | Use case |
|---|---|
| `nibbleflow_int4_f32_ref` | Debugging, differential testing, unsupported CPU |
| `nibbleflow_int4_f32` scalar fallback | Portable native execution |
| `nibbleflow_int4_f32` NEON | ARM64 production decode |

The runtime should select the NEON path only after CPU feature detection and ABI verification. A quantization proof should bind the selected kernel profile. If the device lacks the required feature or a differential self-test fails, the runtime should fall back to int8 or float16 rather than silently using an unverified int4 path.

## 8. Performance Work Still Required

The current implementation validates layout, correctness, and object emission. It does not claim a device speedup. The AArch64 object has not been executed on a physical Android device or an AArch64 emulator in this cycle.

The next optimization pass should:

1. Replace temporary scalar `bytes` and `q` arrays in the NEON loop with direct vector loads or compiler-recognized lane construction.
2. Add an input-activation packing mode when repeated decode shapes justify it.
3. Add a two-output-tile unroll variant to hide load latency.
4. Add an int4 × f16 or int4 × bf16 activation variant where supported.
5. Add outlier sidecar lanes for calibration-sensitive channels.
6. Add batch-prefill kernels separate from batch-1 decode.
7. Validate alignment, cache behavior, and tail paths on real ARM64 hardware.
8. Measure sustained latency, energy, thermal response, and quality—not only first-call latency.

## 9. Limitations and Claims

The Python reference and native x86-64 shared library provide host numerical evidence. The AArch64 compilation and ELF inspection provide target-object evidence. Neither is physical Android execution. The current report therefore claims **host numerical correctness and AArch64 object generation**, but makes no claim about Android latency, energy, thermal stability, or accelerator throughput.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
[3]: https://llvm.org/docs/ClangCommandLineReference.html "Clang Command-Line Reference"
