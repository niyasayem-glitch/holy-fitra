# HF Native Scalar Dynamic-Input Bridge

## Objective

Add one intentionally narrow native-scalar builtin so a parameterless HF `main` can receive deterministic decimal command-line values without changing source-level function signatures or opening general filesystem, shell, environment, or network access.

The typed builtin contracts are:

```hf
arg_i32(position, fallback)
arg_i64(position, fallback)
```

Each returns the decimal value of command-line argument `position`, excluding the executable name, or returns `fallback` when the argument is absent, malformed, has trailing non-decimal content, or lies outside its signed result range. Both `position` and `fallback` must be integer literals; `position` is bounded to `0..7`. `arg_i32` returns `i32`; `arg_i64` returns `i64`. Both are legal only directly inside `fn main() -> i32` with an explicit `effects [io]` declaration. Existing parameterless `main` programs that use neither builtin retain their prior emitted entry signature.

## Safety and compatibility rules

| Area | Contract |
|---|---|
| Input surface | At most eight positional argv values; no environment, file, network, shell, stdin, or arbitrary address exposure. |
| Parsing | Libc-free base-10 decoders require full-string consumption and signed i32 or i64 bounds before accepting a value. |
| Fallback | A literal fallback provides deterministic behavior for omitted, malformed, or out-of-range input. |
| Effects | `io` is required because process argv is external input; callers cannot hide the capability behind another function. |
| ABI | Only a `main` using either builtin receives hidden C ABI `argc`/`argv` parameters; user source still declares no parameters. |
| Existing programs | No input builtin means no entry-signature change and no cache/schema break. |
| Evidence | Compiler regressions, malformed-input cases, compatibility checks, and a new dynamic-loop host fixture are required. |

The parsers are independently emitted as libc-free LLVM helpers rather than calling `strtoll`. They adopt the same safety outcomes that POSIX documents for decimal conversion: no partial-string acceptance and no accepted result outside the target range. POSIX explains why a caller of `strtoll` must distinguish representability errors, and it defines `ERANGE` for unrepresentable results.[1] The Linux manual likewise records the range condition for `strtoll`.[2] HF enforces i32 directly and uses an i128 accumulator to enforce the full i64 range before narrowing.

> This bridge is a language capability extension, not evidence of a faster execution engine. Runtime claims require the subsequent matched host test, while Android and physical-device behavior remain unmeasured.

## References

[1]: https://pubs.opengroup.org/onlinepubs/9799919799/functions/strtol.html "The Open Group Base Specifications: strtol"
[2]: https://man7.org/linux/man-pages/man3/strtol.3.html "Linux strtol(3) manual"
