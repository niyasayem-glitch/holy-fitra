# Holy Fitra Adversarial Stress Matrix

**Date:** 2026-08-22

**Repository baseline:** `daadf6a` (`feat: add runnable native v1 host release path`)

## Objective

Exercise the repository until it fails under malformed inputs, concurrency pressure, resource pressure, toolchain variation, lifecycle races, packaging tampering, and platform-boundary assumptions. Every failure must be classified as a source defect, a test-harness defect, an expected fail-closed rejection, or an unavailable platform capability.

## Available evidence

The sandbox provides x86-64 Linux, Clang/Clang++, CMake, LLVM assembler/optimizer tools, Python 3, and standard shell utilities. It does not provide Gradle, Android SDK/NDK, ADB, a physical Android device, QEMU AArch64, Valgrind, or a persistent ARM64 host. Therefore Android packaging/execution, JNI ABI behavior on ART, ARM runtime execution, thermal behavior, and device performance cannot be proven here.

## Stress families

| Family | Adversarial cases | Pass condition |
|---|---|---|
| Python compiler | Empty/garbage source, malformed tokens, deep nesting, huge literals, duplicate declarations, invalid precedence, cache corruption, hostile paths, subprocess timeout | Structured failure, bounded resource use, nonzero status, no false success. |
| Native v1 | Deterministic output, malformed source, oversized source, nesting limit, invalid target/options, missing output parent, nonzero program status | Stable diagnostics, no crash, deterministic output, correct status propagation. |
| Bootstrap | All State 1–9 fixtures, invalid fixtures, repeated outputs, Python absent from PATH, sanitizer runtime, AArch64 object emission | Fixtures pass without Python; malformed inputs fail; artifacts labeled correctly. |
| Native runtime | Invalid enums, null handles, ownership negatives, queue pressure, shutdown, repeated destroy, sanitizer runs | No hang/UAF/double free; terminal status or typed rejection. |
| Scheduler/ragged | Nulls, short capacities, bad offsets, NaN/Inf, overflow dimensions, throwing work, cancellation, queued shutdown, concurrent submissions | Common validator rejects; every request terminates once; no sanitizer report. |
| NibbleFlow | Invalid dimensions, overflow products, NaN/Inf model parameters, short buffers, repeated lifecycle | Typed rejection; finite valid result; no memory error. |
| JNI | Stub syntax, token forgery, stale/wrong-kind handles, buffer alignment/order/capacity, lifecycle races | Host-only syntax/stub checks pass; real JVM/NDK tests explicitly unavailable. |
| Topology/benchmark | CPU ranges, malformed sysfs, missing files, affinity failures, workload overflow, false ISA labels, failed samples | Degraded mode is explicit; metrics/status remain truthful. |
| Packaging/install | Tampered hashes, invalid metadata characters, deterministic archives, isolated user prefix, no sudo/Python | Tampering/rejection is fail-closed; two archives compare equal; install works. |
| Termux | `pkg`-style no-sudo path, shell syntax, host tests, bootstrap and v1 driver | Compatibility gate passes without root or Python on native v1 path. |

## Classification policy

A failure in an unavailable Android/ARM environment is recorded as **not available**, not passed. A sanitizer-clean run proves only the exercised paths. A green fixture bootstrap proves the bounded fixture chain, not complete fixed-point self-hosting. A host scalar fallback is not NEON evidence.
