# ARM64 Typed-i64 Validation Gate

## Current evidence status

The typed-i64 input bridge **has passed AArch64 user-mode emulation** but is **not yet physical-ARM64 runtime-validated**. On 2026-08-25, the x86_64 sandbox installed QEMU user-mode 8.2.2, the GNU AArch64 Linux sysroot, and an AArch64 cross toolchain. HF emitted AArch64 LLVM IR for the portable fixture, Clang linked an ELF whose machine header is `AArch64`, and QEMU passed all seven cases. The result is emulator-only: it validates the emitted AArch64 Linux code path under QEMU, not real CPU, Android Bionic, Termux, APK, JNI, NEON/I8MM, thermal, or device behavior.

`adb devices -l` still listed no connected device, and the repository has no self-hosted ARM runner. Its Android workflow targets `arm64-v8a`, but runs on GitHub-hosted `ubuntu-22.04` and explicitly says physical-device execution is not performed. It is valid packaging/cross-compilation evidence, not device execution evidence.

## Prepared real-hardware fixture

`validate_hf_i64_arm64.sh` executes only when `uname -m` is `aarch64` or `arm64`; otherwise it exits `77` with a machine-readable `not-run` receipt. On a real Termux or ARM64 Linux environment with `python3` and `clang`, it compiles `language_benchmarks/hf_arm64_i64_input.hf` locally and verifies seven cases:

| Case | Input | Expected process exit |
|---|---|---:|
| Missing value | none | 7 (fallback) |
| Maximum i64 | `9223372036854775807` | 11 |
| Minimum i64 | `-9223372036854775808` | 12 |
| Negative value | `-9` | 13 |
| Positive overflow | `9223372036854775808` | 7 (fallback) |
| Negative overflow | `-9223372036854775809` | 7 (fallback) |
| Trailing content | `12x` | 7 (fallback) |

Run it from a checked-out repository on the ARM64 device:

```sh
chmod +x validate_hf_i64_arm64.sh
./validate_hf_i64_arm64.sh
```

A `passed` JSON receipt names the machine and locally reported device model. Only that receipt from a matching ARM64 runtime can close this gate. It still does not establish Android APK/JNI lifecycle, NEON/I8MM performance, thermal behavior, or general device stability.

## QEMU emulation receipt

Run the reproducible user-mode check on an x86 Linux environment with QEMU, Clang, and the GNU AArch64 sysroot:

```sh
./validate_hf_i64_qemu_aarch64.sh
```

The runner emits an AArch64 ELF from the same HF source, executes the seven cases through `qemu-aarch64 -L /usr/aarch64-linux-gnu`, and returns a `passed` receipt with `"evidence":"emulator-only"`. Its result is intentionally not interchangeable with the real-hardware Termux/Linux receipt above.
