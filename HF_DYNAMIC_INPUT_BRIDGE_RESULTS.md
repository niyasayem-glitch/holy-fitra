# HF Dynamic-Input Bridge Result

## Retained capability

HF now supports bounded native-scalar expressions:

```hf
arg_i32(position, fallback)
arg_i64(position, fallback)
```

The bridge accepts at most eight positional decimal argv values and is available only directly in `fn main() -> i32 effects [io]`. Both operands are literals and each function returns its named signed type. A missing argument, malformed decimal string, trailing content, or out-of-range value produces the specified fallback. The i64 helper accumulates in i128 so it can reject values outside `[-9223372036854775808, 9223372036854775807]` before narrowing. The user source remains parameterless; only a `main` that uses an input builtin receives the hidden native C ABI `argc` and `argv` parameters. Existing parameterless programs keep their former ABI.

The emitted helpers are self-contained LLVM rather than copied parsers or a general process API. They reject user-defined builtin names, do not expose filesystem, environment, shell, standard input, or network access, and preserve explicit `io` effect declaration. The compiler suite now contains malformed, out-of-range, negative, missing-input, compatibility, reserved-name, and i64-boundary tests; all 40 compiler tests passed. The i64 signed-boundary scenario passed 20 consecutive fresh test rounds, and the existing i32 dynamic workload still passed after the extension.

## Matched host exercise

The new bridge enables a dynamic argv-driven LCG32 loop. C, C++, Node.js, CPython, and HF received the same decimal iteration count (`10,000,000`) and seed (`123456789`) in rotated order across nine host samples. Timing is whole-process wall time, so it includes startup as well as the loop. C, C++, Node.js, and CPython each printed and matched the full expected unsigned result `2950074261`. HF’s i32 return is observable only through the process exit status, so HF was checked against the expected low byte (`149`) in every run.

| Runtime | Mean wall time | Relative to C | Result evidence |
|---|---:|---:|---|
| C / Clang | 1.811 ms | 1.000× | Full unsigned result in 9/9 runs |
| Holy Fitra native scalar | 1.969 ms | 1.087× | Expected exit-code low byte in 9/9 runs |
| C++ / Clang | 2.404 ms | 1.327× | Full unsigned result in 9/9 runs |
| Node.js / V8 | 30.978 ms | 17.103× | Full unsigned result in 9/9 runs |
| Python / CPython | 800.146 ms | 441.766× | Full unsigned result in 9/9 runs |

HF completed this fixture within 8.7% of the C process-wall mean. That difference is not treated as proof of a general speed ranking: the sample count is small, timing includes startup, C++ has a different standard-library startup path, and HF’s full 32-bit final state is not externally printed. The result proves the retained input bridge can drive a nonconstant host loop under the declared exit-code check; it does **not** prove a universal execution advantage, Android behavior, ARM64 throughput, device thermal behavior, or full-width HF numerical equality.

## Remaining gate

The next correctness improvement is a separately scoped, effect-gated full-width result or checksum receipt that does not contaminate loop timing. The next performance improvement remains architecture-specific kernel and compiler work, with module-level cache, Android NDK, and physical-device gates kept separate.

## References

[1]: https://pubs.opengroup.org/onlinepubs/9799919799/functions/strtol.html "The Open Group Base Specifications: strtol"
[2]: https://man7.org/linux/man-pages/man3/strtol.3.html "Linux strtol(3) manual"
