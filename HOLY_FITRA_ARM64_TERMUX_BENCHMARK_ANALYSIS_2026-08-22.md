# Holy Fitra v1 ARM64 and Termux Benchmark Analysis

**Analysis date:** 2026-08-22

**Repository:** [`niyasayem-glitch/holy-fitra`](https://github.com/niyasayem-glitch/holy-fitra)

## Executive conclusion

There is **no physical Android-device performance dataset** in the v1 repository or current sandbox. The available evidence consists of Termux-compatible host validation, AArch64 relocatable-object cross-compilation, host JNI/CMake checks, and a separate simulated-Android CPU benchmark whose own output identifies the host as x86-64. These are useful engineering gates, but they cannot establish Snapdragon/MediaTek latency, NEON/SVE throughput, big.LITTLE placement, thermal throttling, energy per token, or Android ART/JNI behavior.

The v1 release should therefore be described as **ARM64-targeted and Termux-compatible at the host/tooling level**, not as physically benchmarked on ARM64 Android. The distinction is explicit in the release evidence: `android_execution=false` and `aarch64_status=artifact-only`.[^host]

## Evidence inventory

| Evidence source | What it proves | What it does not prove |
|---|---|---|
| `bash termux-build.sh --host-tests` | The CLI, Python development suite, numerical validators, bootstrap path, native ragged host test, v1 driver, and project workflow pass on the current host. | It does not run inside Termux on a phone and does not measure Android CPU performance. |
| `bootstrap/test_bootstrap.sh` AArch64 outputs | The seed fixtures and State-1–9 sources cross-compile into non-empty `aarch64-linux-android21` object files. | It does not execute those objects, load an APK, or exercise an ARM core. |
| Checked-in AArch64 objects | `file`/ELF headers identify relocatable AArch64 objects for ragged NEON/SVE and NibbleFlow. | Object type and size are not runtime speed, correctness on a specific ARM implementation, or proof that the selected path executes. |
| Host JNI syntax and CMake graph | JNI-facing C++ is syntactically compatible with the isolated header stub and the native graph produces host shared libraries. | It does not validate the real JNI ABI, ART global-reference behavior, Android linker, Gradle/AAR packaging, or device execution. |
| Android ragged benchmark implementation | The intended metrics and protocol exist: p50/p95/p99, throughput, scheduler counts, thermal samples, frequency signals, and checksum. | No recorded physical run is present. The benchmark remains an unexecuted device harness. |
| `e2e_android_benchmark.py` | Host-side algorithmic comparison infrastructure exists for float/int8/int4, PyTorch, and ONNX-style paths. | Its code explicitly labels the result as a simulated Android CPU approximation on sandbox x86-64, not a phone benchmark. |

## Termux result analysis

The latest rerun of `bash termux-build.sh --host-tests` passed. The gate exercised the Python development suite, NibbleFlow and ragged numerical validators, optional native ragged scheduler compilation/execution, the general CLI, doctor/contracts/TUI snapshot, project initialization and benchmark commands, the State-1–9 bootstrap, and the native v1 regression. It ended with `Holy Fitra Termux-compatible validation passed.`

This is a **workflow-compatibility result**. The script is run from the x86-64 sandbox and invokes host `python3`, Clang, and the repository’s shell entry points. It does not test Android’s Bionic libc, Termux’s actual package repository, phone filesystem permissions, ARM CPU frequency behavior, or Android process scheduling. Therefore the accurate interpretation is: “the Termux-oriented, no-sudo command path is host-validated,” not “the program has measured Termux phone performance.”[^termux]

## ARM64 artifact result analysis

The latest rerun of `bootstrap/test_bootstrap.sh` passed the State-1–9 fixture gates, diagnostics, runtime sanitizer, and no-Python help check. It emitted non-empty AArch64 object-size summaries, including **89,392 bytes for the State-9 fixture**, **62,304 bytes for State 8**, and **49,936 bytes for State 4**. The checked-in ragged NEON/SVE and NibbleFlow object files were independently identified as `ELF 64-bit LSB relocatable, ARM aarch64` on the x86-64 host.

These results demonstrate that Clang accepted the requested AArch64 target and produced relocatable artifacts. They do not establish instruction selection quality, runtime correctness, cache behavior, scheduler affinity, or throughput. Object size is especially weak as a performance proxy: a smaller object can be faster, slower, or simply contain less code. The benchmark guide correctly requires a physical ARM64 device for latency, frequency, thermal, and energy conclusions.[^guide]

## Intended physical-device benchmark protocol

The checked-in Android benchmark is methodologically sound as a starting harness. It validates dimensions and iteration bounds, constructs deterministic ragged workloads, warms the scheduler, records per-request completion latency, calculates p50/p95/p99 and mean, tracks successful iterations and failures, records scheduler submissions/completions/cancellations/deadline misses/rejections/steals, samples thermal zones and current frequency when readable, updates thermal policy, and includes a checksum to prevent dead-code elimination.[^source]

A real device campaign should record the manufacturer/model, SoC, Android and kernel versions, RAM, battery and charging state, screen state, ambient conditions, build fingerprint, ABI, thermal-zone availability, CPU-capacity source, and exact Git commit. Each configuration should have an idle baseline, warm-up, and measured phase, with at least three independent runs. Cold, warm, and sustained-hot runs must not be mixed in one comparison.

The minimum configuration matrix should include scalar versus NEON, little-preferred versus big-preferred policy, thermal feedback enabled versus disabled, and `sequences_per_task` values of 1, 4, and 8. Each run should retain raw JSON, configuration, checksum, failure count, scheduler counters, temperature/frequency samples, and the exact APK/native library hash.

## Current release assessment

| Claim | Assessment |
|---|---|
| “Holy Fitra v1 is Termux-friendly.” | **Supported for the host workflow.** The no-sudo/native driver and Termux-compatible gate pass. |
| “Holy Fitra v1 compiles for ARM64 Android.” | **Partially supported.** AArch64 object artifacts are produced; full Gradle/NDK packaging is unavailable in the sandbox. |
| “Holy Fitra v1 runs on Android ARM64.” | **Unproven.** No APK/AAR, ART load, JNI device smoke test, or physical phone run is recorded. |
| “Holy Fitra v1 is faster on Snapdragon/MediaTek.” | **Unsupported.** No physical latency or throughput measurements exist. |
| “Holy Fitra v1 has thermal throttling behavior data.” | **Unsupported.** The code can sample generic Linux thermal/frequency files, but no device sample exists. |
| “The simulated Android benchmark is Android performance.” | **False.** It is explicitly an x86-64 host approximation. |

## Required next evidence before ARM64 performance claims

The next milestone is not another host optimization pass; it is a reproducible device-evidence campaign. A physical ARM64 Android environment must first produce a real Gradle/NDK build and installable APK/AAR. Then the JNI library must load through ART, direct buffers must be exercised, and the benchmark must emit complete JSON with nonzero failure detection and a nonzero checksum. Only after that should p50/p95/p99, throughput, thermal, and energy comparisons be published.

Until those steps are completed, the correct v1 label remains **`1.0.0-host` with ARM64 artifacts and Termux-compatible host validation**. No Android benchmark number should be invented from the current evidence.

## References

[^host]: [Holy Fitra v1 host-candidate evidence report](https://github.com/niyasayem-glitch/holy-fitra/blob/master/HOLY_FITRA_V1_HOST_CANDIDATE_REPORT.md)
[^termux]: [Termux build and host-validation gate](https://github.com/niyasayem-glitch/holy-fitra/blob/master/termux-build.sh)
[^guide]: [Holy Fitra Android NDK benchmark guide](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holyfitra_device_benchmark_guide.md)
[^source]: [Holy Fitra Android device benchmark implementation](https://github.com/niyasayem-glitch/holy-fitra/blob/master/holy_fitra_device_benchmark.cpp)
