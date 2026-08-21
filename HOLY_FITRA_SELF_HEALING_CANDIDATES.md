# Holy Fitra Self-Healing Candidate Matrix

## Audit result

The current checkout is healthy at the test level: Python compilation, shell syntax, and the complete unittest discovery pass. The latest discovery count is **172 tests with 0 failures**. The self-healing pass therefore focuses on latent correctness and maintenance risks rather than pretending that a failing test exists.

| Rank | Candidate | Failure prevented | Risk | Decision |
|---:|---|---|---|---|
| 1 | Version the native LLVM cache schema and include the schema in cache identity | Stale artifacts surviving compiler-emitter changes | Low | **Select** |
| 2 | Add structural validation for compiler function calls before indexing parameter lists | Malformed calls causing `IndexError` or partial diagnostics instead of fail-closed compiler errors | Low | **Select** |
| 3 | Add explicit source/module consistency checks to project workflows | Building the wrong entry or silently treating a file as a project | Low | **Select** |
| 4 | Harden `holyfitra test` against zero-test ambiguity and target mismatch | A project appearing healthy without executing any tests; cross-target execution misuse | Low | **Select** |
| 5 | Add canonical compiler-state health report | Silent drift in Python/compiler/LLVM/runtime versions | Low | Select |
| 6 | Add native short-circuit and mutable-loop differential snapshots | Regression in CFG semantics hidden by exit-code-only testing | Low | Select |
| 7 | Add module import graph and cycle detection | Multi-file projects compiling incomplete dependency sets | Medium/high | Defer to semantic-core wave |
| 8 | Add structured diagnostic codes to the Python native compiler | Automation/editor users depending on unstable exception text | Medium | Defer |
| 9 | Add type/symbol arena snapshots to Stage-0 | Fixed-point comparisons lacking semantic evidence | Medium/high | Defer |
| 10 | Add LLVM verifier invocation after emission | Backend text errors reaching Clang with weak attribution | Low/medium | Select after cache repairs |
| 11 | Add compiler-source digest to cache key | Same schema with changed emitter source reusing artifacts | Medium | Select if deterministic source hashing is stable |
| 12 | Add deterministic test timeouts and output capture policy | Hung or noisy language tests blocking CI | Low | Included in #4 |
| 13 | Add overflow-aware integer semantics | Host-dependent arithmetic behavior | Medium/high | Defer to language specification wave |
| 14 | Add ownership/borrow state checking to native locals | Unsafe mutation through borrowed values | High | Defer |
| 15 | Add fail-closed package/runtime ABI compatibility checks | Running artifacts against incompatible runtimes | Medium | Defer |

## Selected repair set

The selected set is deliberately narrow. Cache identity and schema repair protects reproducible builds. Call-shape validation prevents internal exceptions from malformed source. Project consistency and test-runner hardening improve the user-facing language workflow without changing source semantics. These changes can be validated by existing tests plus focused negative fixtures.

The larger module graph, semantic snapshots, structured diagnostics, verifier integration, ownership, and ABI work remain planned follow-up waves. They are not being hidden inside this self-healing pass because each deserves a separate language contract and migration corpus.
