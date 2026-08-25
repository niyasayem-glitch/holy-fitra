# HF Native Scalar Dynamic-Input Bridge

## Objective

Add one intentionally narrow native-scalar builtin so a parameterless HF `main` can receive deterministic decimal command-line values without changing source-level function signatures or opening general filesystem, shell, environment, or network access.

The builtin contract is:

```hf
arg_i32(position, fallback)
```

It returns the decimal value of command-line argument `position`, excluding the executable name, or returns `fallback` when the argument is absent, malformed, has trailing non-decimal content, or lies outside signed 32-bit range. Both `position` and `fallback` must be integer literals. `position` is bounded to `0..7`. The builtin is legal only directly inside `fn main() -> i32` with an explicit `effects [io]` declaration. Existing parameterless `main` programs that do not use `arg_i32` retain their prior emitted entry signature.

## Safety and compatibility rules

| Area | Contract |
|---|---|
| Input surface | At most eight positional argv values; no environment, file, network, shell, stdin, or arbitrary address exposure. |
| Parsing | A libc-free base-10 decoder requires full-string consumption and signed-32-bit bounds before accepting a value. |
| Fallback | A literal fallback provides deterministic behavior for omitted, malformed, or out-of-range input. |
| Effects | `io` is required because process argv is external input; callers cannot hide the capability behind another function. |
| ABI | Only a `main` using the builtin receives hidden C ABI `argc`/`argv` parameters; user source still declares no parameters. |
| Existing programs | No input builtin means no entry-signature change and no cache/schema break. |
| Evidence | Compiler regressions, malformed-input cases, compatibility checks, and a new dynamic-loop host fixture are required. |

The parser is independently emitted as a libc-free LLVM helper rather than calling `strtoll`. It adopts the same safety outcomes that POSIX documents for decimal conversion: no partial-string acceptance and no accepted result outside the target range. POSIX explains why a caller of `strtoll` must distinguish representability errors, and it defines `ERANGE` for unrepresentable results.[1] The Linux manual likewise records the range condition for `strtoll`.[2] HF enforces the narrower i32 bound directly before returning a value.

> This bridge is a language capability extension, not evidence of a faster execution engine. Runtime claims require the subsequent matched host test, while Android and physical-device behavior remain unmeasured.

## References

[1]: https://pubs.opengroup.org/onlinepubs/9799919799/functions/strtol.html "The Open Group Base Specifications: strtol"
[2]: https://man7.org/linux/man-pages/man3/strtol.3.html "Linux strtol(3) manual"
