# Holy Fitra HD Stress and Termux Assessment

## Scope

This receipt assesses the current HD stale-review guard and Holy Fitra regression path under bounded sequential stress. It also records the decision not to embed or copy Termux into Pix Studio at this stage. No provider request, secret read, Android shell, device test, or Termux command was performed.

## HD workspace-digest profile

The exact reviewed-plan feature deliberately hashes every eligible workspace file before applying a saved plan. On the real HF repository, the policy admitted 39 files totaling 258,115 bytes. Across 100 sequential digest rounds, latency was 37.2941 ms minimum, 41.5203 ms mean, 46.5507 ms p95, and 54.2898 ms maximum.

This is expected linear work for a safety gate whose purpose is to catch a changed workspace. It is not retained as a candidate for unsound caching: caching that misses file additions, deletions, or content changes could let HD apply a review that the user did not inspect. The measured local cost is materially smaller than any intended remote-provider planning round, but no provider latency was measured or claimed.

## Sequential stress results

| Workload | Result | Boundary |
|---|---:|---|
| HD and lower-level agent focused regression | 25 consecutive passing runs | Exercises plan review, explicit apply, validation, rollback, protected files, visible diffs, and reviewed packets using deterministic test clients. |
| Complete Holy Fitra suite | 5 consecutive passing runs | Each run passed the current **312** tests; host-side regression evidence only. |
| Aggregate sequential suite runs | 30/30 completed without a test failure | This is not concurrency, memory-limit, Android, device, provider, security-penetration, or general-performance proof. |

## Termux decision

The official `termux-app` project is GPLv3-only and its working shell depends on Android application, bootstrap, package, signing, and platform-process behavior. A direct copy would be a separate license/distribution and custom-native-build decision, not an Expo feature. Pix Studio therefore retains its constrained local project terminal. See [`TERMUX_INTEGRATION_ASSESSMENT_2026-08-26.md`](../holyfitra-mobile/TERMUX_INTEGRATION_ASSESSMENT_2026-08-26.md) in the companion project for the source links and companion-app handoff requirements.

## Retained improvements and non-claims

The retained improvements are: HD’s exact reviewed-plan stale-workspace guard, its existing transactional validation/rollback controls, and the terminal’s redundant string-work reduction. No upgrade grants autonomous looping, arbitrary command execution, secret access, provider tool access, an embedded Linux environment, full Termux compatibility, or physical-device capability.
