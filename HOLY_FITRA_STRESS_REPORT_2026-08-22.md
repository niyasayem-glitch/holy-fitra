# Holy Fitra Adversarial Stress Report

**Date:** 2026-08-22

**Baseline:** `daadf6a` (`feat: add runnable native v1 host release path`)

## Executive result

The stress campaign exercised the compiler, native seed, bootstrap fixtures, scheduler, ragged attention validator, NibbleFlow ABI, AI evidence contracts, cache paths, installer, deterministic packager, Termux host path, JNI syntax boundary, and host CMake graph. It found and fixed four real fail-open or resource-safety defects. The post-fix host gates passed. The result is stronger host software, not proof of Android execution or complete fixed-point self-hosting.

## Confirmed defects found and fixed

| Area | Failure observed | Retained fix |
|---|---|---|
| Native seed compiler | A fixed array dimension of `999999999` reached LLVM and timed out under a five-second bound. | Added a one-million-element v1 fixed-array limit and permanent regression coverage. |
| Native/Python semantic validation | Statements after `return` were skipped, allowing malformed or type-invalid unreachable code. Python duplicate parameters were also accepted. | Both validators now continue checking unreachable statements and reject duplicate parameters. Expression depth now fails with a structured diagnostic instead of raw recursion failure. |
| Python LLVM cache | A tampered persistent LLVM payload with a matching outer digest was accepted because its content was not authenticated. | Bumped cache schema to 3 and added an `llvm_sha256` integrity field verified before reuse. |
| Native executable cache | A modified cached executable was silently copied back to the requested output. | Added a validated SHA-256 sidecar for native artifacts; missing, malformed, or mismatched sidecars force a rebuild. |
| Ragged attention | NaN/Infinity q/k/v values could produce invalid numerical state without rejection. | Added a finite scan over the logical q/k/v extent and permanent NaN/Infinity rejection tests. |
| AI evidence | NaN/Infinity confidence and verifier thresholds bypassed ordinary range checks. | Added finite numeric validation for evidence confidence and verifier thresholds with regression tests. |

## Stress evidence

| Gate | Result |
|---|---|
| Python unit suite | 220 tests passed. |
| Python compileall | Passed. |
| Compiler stress harness | 12 cases passed, including malformed/deep/oversized source, duplicate parameters, unreachable code, LLVM cache tampering, and executable cache tampering. |
| Repeated compiler/v1 runs | 20 consecutive compiler stress and v1 driver runs passed. |
| Bootstrap | Three repeated State-1–9 runs passed. Invalid fixtures rejected. Deterministic seed LLVM output matched byte-for-byte. |
| Isolated no-Python bootstrap | Passed with a native-only PATH after correcting the harness environment to include `cmp`. |
| Termux host gate | Passed. |
| Native strict tests | Dispatch, topology, NibbleFlow, ragged scheduler, runtime, and batch runtime passed with strict warnings. |
| Ragged fuzz | 100,000 malformed/finite/non-finite cases passed under ASAN/UBSan; only safe valid cases reached the scalar kernel. |
| NibbleFlow fuzz | 100,000 malformed model cases passed under ASAN/UBSan. |
| Scheduler stress | 10 repeated concurrent submission/shutdown/exception runs passed under ASAN/UBSan; ThreadSanitizer run passed. |
| JNI boundary | Strict host syntax passed using the isolated JNI stub. |
| Android native graph | Host CMake produced three non-empty shared libraries using the JNI stub. |
| Installer | Isolated no-sudo, no-Python user-prefix install, build, run, and package passed. |
| Release archive | Two independently generated archives were byte-identical; extracted archive regression passed. |

## Evidence boundaries

The sandbox does not contain Gradle, Android SDK/NDK, ADB, QEMU AArch64, or a physical Android device. Consequently, Android Gradle configuration, AAR/APK packaging, ART/JNI loading, ARM64 runtime execution, NEON/SVE behavior, big.LITTLE placement, thermal throttling, latency, and memory-bandwidth measurements remain **not available**, not passed.

The native-only bootstrap path proves the checked-in State-1–9 fixture chain and the v1 scalar subset. It does not prove that the complete compiler can compile itself to a fixed point. Canonical grammar unification, State-10 CFG/MIR, generation-safe Stage-0 and JNI handles, authenticated deployment envelopes, and full AI-native lowering remain open work.

## Reproduction commands

```bash
python3 -m unittest -q
python3 stress_holyfitra_compiler.py
bash bootstrap/test_bootstrap.sh
bash termux-build.sh --host-tests
./test_holyfitra_v1.sh
```

The stress harnesses are intentionally bounded and deterministic. They should be treated as regression tools, not as a claim of exhaustive proof against all possible inputs.
