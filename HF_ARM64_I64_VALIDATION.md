# ARM64 Typed-i64 Validation Gate

## Current evidence status

The typed-i64 input bridge is **not yet ARM64 runtime-validated**. This task inspected the available execution paths on 2026-08-25: the active sandbox is `x86_64`, no QEMU AArch64 runtime or AArch64 cross-compiler/sysroot is installed, and `adb devices -l` listed no connected device. The repository has no self-hosted runner. Its Android workflow targets `arm64-v8a`, but runs on GitHub-hosted `ubuntu-22.04` and explicitly says physical-device execution is not performed. It is valid packaging/cross-compilation evidence, not ARM64 execution evidence.

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
