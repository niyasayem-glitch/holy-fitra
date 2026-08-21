# Holy Fitra Stage-0 Bootstrap Compiler

`holyfitra_bootstrap.cpp` is the first no-Python seed compiler for the self-hosting effort. It is intentionally smaller than the main Python-hosted compiler and emits textual LLVM IR for the bootstrap scalar subset.

## Supported subset

The seed supports modules, functions, `i32`, `i64`, `bool`, and `void`, typed parameters, local `let`/`var` bindings, arithmetic, comparisons, logical operators, unary operators, calls, `if`/`else`, `while`, expression statements, and returns.

It deliberately does not yet support tensors, effects, tasks, hybrid functions, imports, strings, arrays, structs, pointers, generics, or file/process APIs. Those features belong to the next self-hosted compiler-core stage.

## Build without Python

```bash
clang++ -std=c++17 -O2 -Wall -Wextra -pedantic \
  holyfitra_bootstrap.cpp -o holyfitra_bootstrap
```

Emit LLVM for the host:

```bash
./holyfitra_bootstrap bootstrap/hello.hf -o /tmp/hello.ll
clang -O2 /tmp/hello.ll -o /tmp/hello
/tmp/hello
```

Emit AArch64-targeted LLVM and an ARM64 object:

```bash
./holyfitra_bootstrap --target=aarch64-linux-android21 \
  bootstrap/hello.hf -o /tmp/hello.aarch64.ll
clang --target=aarch64-linux-android21 -c \
  /tmp/hello.aarch64.ll -o /tmp/hello.aarch64.o
```

Run the no-Python gate:

```bash
bootstrap/test_bootstrap.sh
```

The gate checks native host execution, invalid diagnostics, AArch64 object generation, strict warnings, and operation with Python removed from the environment and `PATH`.

## Self-hosting boundary

This seed is a Stage-0 compiler, not yet the complete self-hosted compiler. The next stage is `compiler/main.hf`, a Holy Fitra compiler core written in the minimal language. Stage 0 must compile that source into a native Stage-1 compiler. Stage 1 must then compile its own source repeatedly until the compiler artifact and canonical output reach a reproducible fixed point.

Python remains a migration oracle during this process, but the final `holyfitra` compiler command must not require Python to parse, validate, emit LLVM, or invoke the native backend.
