# Holy Fitra Performance Pass

**Date:** 2026-08-22

**Scope:** Native v1 cold-start and bounded million-line compiler paths on the available x86-64 Linux sandbox.

## Result

The first measured bottleneck was the native v1 seed compiler’s cold build. Every fresh v1 process that needed the seed compiler paid for a C++17 compilation of `holyfitra_bootstrap.cpp`. The seed compiler’s optimization level does not determine the optimization level of the generated Holy Fitra program; generated programs continue to link through Clang at `-O2`.

The retained optimization changes the default seed build from `-O2` to `-O0`, while allowing `HOLYFITRA_SEED_OPT=O0|O1|O2|O3` for users who prefer a more optimized seed executable. This is appropriate for a compiler bootstrap binary where cold startup is more important than maximum seed self-execution throughput.

## Measurements

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| Fresh seed compiler build, `-O0` | 0.996 s | same configuration | baseline reference |
| Fresh seed compiler build, `-O1` | 2.214 s | not retained as default | 2.22× slower than O0 |
| Fresh seed compiler build, `-O2` | 2.652 s | not retained as default | 2.66× slower than O0 |
| Twenty v1 checks with one cold seed build, default seed optimization | 2.850 s | 1.413 s | 50.4% lower wall time |
| Million-line sparse seed emission, O2 seed | 4 ms | 9 ms with O0 seed | 5 ms slower for this tiny measured emission path |

The large-source result shows the expected tradeoff: O0 improves bootstrap compilation substantially, while O2 produces a somewhat faster seed execution. The v1 user path is dominated by cold seed construction in the repeated-check scenario, so O0 is retained as the default. Users performing long-running compiler sessions can select `HOLYFITRA_SEED_OPT=O2` or `O3`.

## Retained changes

The v1 driver now exposes `HOLYFITRA_SEED_OPT`, validates the value, reports it through `holyfitra-v1.sh doctor`, and uses the selected level only when compiling the seed compiler. Native output compilation remains `-O2`. The change does not weaken source validation, LLVM verification, cache integrity, process timeout, or package metadata checks.

## Validation

The complete Python suite, Termux-compatible gate, native scheduler gate, bootstrap gate, and deterministic release packager must remain green after this change. The reported measurements are from the x86-64 sandbox. No Android ARM64 phone, Termux ARM64 device, Android NDK build, ART/JNI execution, NEON/SVE runtime measurement, thermal result, or big.LITTLE result is claimed.

## Reproduction

```bash
# Compare seed compiler build levels.
for opt in O0 O1 O2; do
  clang++ -std=c++17 -"$opt" -Wall -Wextra -Werror -pedantic \
    holyfitra_bootstrap.cpp -o "/tmp/holyfitra-seed-$opt"
done

# Select a faster or more optimized v1 seed explicitly.
HOLYFITRA_SEED_OPT=O0 ./holyfitra-v1.sh build bootstrap/hello.hf -o /tmp/hello
HOLYFITRA_SEED_OPT=O2 ./holyfitra-v1.sh build bootstrap/hello.hf -o /tmp/hello-optimized-seed
```
