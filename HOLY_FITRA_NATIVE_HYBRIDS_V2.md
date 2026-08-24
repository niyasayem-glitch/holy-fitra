# Holy Fitra Native Hybrids v2

## Purpose

This enhancement expands the validated native scalar subset with reusable, typed **built-in hybrid reducers**, a static **inspection command**, and a `hybrid` project starter. It is intentionally constrained to constructs that the existing parser, semantic validator, and LLVM emitter can represent and test.

## Language additions

```hf
hybrid parallel fn ensemble(x: i32) -> i32
    using [left_score, right_score]
    reduce builtin sum
    workers=2
```

| Built-in reducer | Accepted branch and result type | Native lowering |
|---|---|---|
| `sum` | `i32` or `i64` | Deterministic integer addition tree |
| `product` | `i32` or `i64` | Deterministic integer multiplication tree |
| `min` | `i32` or `i64` | Signed comparison and select tree |
| `max` | `i32` or `i64` | Signed comparison and select tree |
| `all` | `bool` | Boolean `and` tree |
| `any` | `bool` | Boolean `or` tree |

The reducer is explicit (`reduce builtin <name>`), branch input signatures must match the hybrid input signature, each branch must return the reducer type, and workers remain bounded between 1 and 32. User-defined reducers retain the existing `reduce <function>` syntax and strict typed-parameter checks.

## Command additions

`holyfitra inspect <source-or-project>` performs parsing and native semantic validation, then emits JSON containing the module, effective effects, tasks, hybrid topology, selected reducer, and lowering contract. It does not build, execute, call a provider, write source, or run a device test.

`holyfitra init --template hybrid` creates a local starter that demonstrates typed branch functions, a built-in reducer, an explicit model/memory effect set, and a deterministic scalar `main` function.

## Evidence boundaries

The scalar LLVM emitter generates deterministic **branch calls followed by a reducer**. The `workers` annotation is a validated concurrency contract and metadata for runtime-aware hosts; this change does **not** prove native threads are launched by the emitted scalar IR. The existing Python hybrid runtime remains the separately implemented host-parallel execution surface. Stage-0 self-hosted states are not changed by this native frontend addition, so it does not claim fixed-point self-hosting of the new syntax.
