# Holy Fitra v1 Host Candidate Evidence

**Candidate:** Holy Fitra v1.0.0-host

**Evidence date:** 2026-08-22

**Repository state:** Working tree changes pending publication after the prior P0 remediation commit.

## Release scope

This candidate is a **native-first host release** for the bounded scalar Holy Fitra subset. It contains a C++17 seed compiler, C11 Stage-0 runtime, a no-Python shell driver, a no-sudo installer, deterministic source packaging, negative source-limit tests, and Termux-compatible host integration.

The candidate does not claim a complete fixed-point compiler, general Stage-10 CFG/MIR, complete AI-native lowering, Android package execution, or physical-device performance. Python remains an optional development/oracle environment and is not required by the v1 driver’s check, emit, build, run, test, package, or seed-build path.

## Implemented release surface

| Component | Evidence |
|---|---|
| Native seed | `holyfitra_bootstrap.cpp` builds with strict C++17 warnings, exposes `--version`, bounds source bytes to 8 MiB, limits tokens and parser nesting, and emits LLVM text. |
| v1 driver | `holyfitra-v1.sh` provides `doctor`, `version`, `build-seed`, `check`, `emit`, `build`, `run`, `test`, and `package`. LLVM is compiled through Clang before linking or acceptance. |
| Installation | `install-holyfitra-v1.sh` installs into a user-selected prefix without `sudo` and uses an absolute launcher to avoid symlink-root errors. |
| Release packaging | `make-holyfitra-v1-release.sh` runs the v1 regression, bundles the native release sources and fixtures, and creates a deterministic gzip archive with explicit host/device metadata. |
| Termux | `termux-build.sh` now includes v1 shell syntax and driver regression checks while preserving the existing `pkg`/no-`sudo` workflow. |
| Documentation | `HOLY_FITRA_V1_RELEASE_SPEC.md` defines supported commands, safety invariants, acceptance gates, and evidence boundaries. |

## Validation evidence

The following gates passed from the checkout:

```text
python3 -m unittest -q                 passed
python3 -m compileall -q .             passed
bash -n all changed shell scripts     passed
bash bootstrap/test_bootstrap.sh      passed
bash termux-build.sh --host-tests     passed
./test_holyfitra_v1.sh                 passed
isolated no-Python v1 path             passed
user-prefix installer test             passed
two archive byte comparison            passed
```

The Python suite contains 155 tests at the current post-P0 baseline. Native v1 regression covers deterministic LLVM emission, executable exit status, malformed source rejection, deep expression nesting rejection, oversized source rejection, project-test failure semantics, and package metadata. The isolated no-Python run used a PATH containing native utilities and no Python executable.

## Artifact status

The release archive is generated with sorted entries, normalized timestamps, numeric owner/group values, and `gzip -n`. Its metadata records:

```text
python_required=false
android_execution=false
aarch64_status=artifact-only
fixed_point_self_hosting=false
```

A real AArch64 compilation remains an artifact check. It is not a device execution or benchmark result.

## Known boundaries before calling this Android-complete or fixed-point-complete

The sandbox has no Android SDK/NDK, Gradle wrapper/toolchain, ADB, or physical arm64 Android device. Therefore no Android AAR/APK build, ART library load, JNI device smoke test, NEON/SVE measurement, big.LITTLE placement result, thermal result, latency result, or memory-bandwidth result is claimed.

The seed compiler is self-contained for the documented v1 scalar subset, but it does not yet compile the complete compiler implementation. State 1–9 no-Python fixtures remain green; repeated complete Stage-1/Stage-2 byte-stable rebuilds are not proven. Canonical parser unification, typed HIR, verified CFG/MIR, generation-safe Stage-0 handles, generation-tagged JNI handles, and authenticated AI/deployment evidence remain post-candidate work.

## Reproduction

From a clean checkout with Clang available:

```bash
./holyfitra-v1.sh doctor
./test_holyfitra_v1.sh
./make-holyfitra-v1-release.sh dist/holyfitra-v1.0.0-host.tar.gz
```

For Termux, install the required packages through the existing `termux-setup.sh`, then run `bash termux-build.sh --host-tests`. No `sudo` command is part of the native v1 path.
