# Holy Fitra development lanes

Holy Fitra uses two development lanes so ambitious experiments do not destabilize the public `master` branch.

## Safe lane

Ordinary bug fixes, documentation changes, bounded performance improvements, tests, and compatibility work belong on `master` or a `safe/<topic>` branch. Every push and pull request runs `.github/workflows/holyfitra-ci.yml`, which installs the package, checks Python and shell syntax, and runs the complete native and Termux-compatible validation gate.

A safe change is eligible for `master` only when the validation workflow is green. The existing repository rule remains evidence-based: a green host/Termux gate does not prove physical Android ARM64 execution, so Android-specific claims still require the separate device evidence protocol.

## High-risk lane

Changes that alter compiler semantics, native memory ownership, ABI boundaries, scheduler behavior, security policy, model-training behavior, generated-code permissions, or deployment formats should start from an isolated branch whose name begins with `high-risk/`:

```bash
git fetch origin
git switch -c high-risk/experiment-name origin/master
# make and test the experiment
git add -A
git commit -m 'experiment: describe the high-risk change'
git push -u origin high-risk/experiment-name
```

High-risk branches are validated by the same CI workflow, but they do not enter `master` merely because a local command passed. Promotion is explicit and requires the GitHub Actions workflow `Promote high-risk Holy Fitra change` to be dispatched with the exact confirmation value `PROMOTE` and a reason:

```bash
gh workflow run promote-high-risk.yml \
  --ref master \
  -f source_branch=high-risk/experiment-name \
  -f confirmation=PROMOTE \
  -f reason='Explain the expected benefit and the risk reviewed.'
```

The promotion workflow checks out the high-risk branch, runs syntax checks, the full Python suite, the native Termux gate, deterministic release packaging, and the bounded 300-iteration high-risk plan-engine campaign. The campaign must report 300 iterations with 300 correctness, safety, determinism, and retained results. Only if all checks pass does it create or reuse a pull request and squash-merge the branch into `master`.
 If the branch name or confirmation is invalid, the workflow fails without touching `master`.

## Promotion rules

| Change type | Branch | Required gate | Promotion |
|---|---|---|---|
| Documentation, tests, bounded UX, portability, and low-risk fixes | `master` or `safe/<topic>` | Normal validation workflow | Merge or publish to `master` after green CI |
| Compiler semantics, C/C++ ABI, JNI, scheduler, security, model learning, deployment, or self-modification changes | `high-risk/<topic>` | Normal validation plus explicit high-risk promotion workflow | Squash-merge into `master` only after all gates pass |
| Android device, thermal, NEON/SVE, or big.LITTLE claims | Any branch | Android SDK/NDK and physical-device evidence | Never infer from host CI; publish only with device evidence |

## Important boundary

Automated tests can reject many regressions, but they cannot prove that a risky change is correct for every model, device, or workload. High-risk promotion therefore validates the branch and records the reason, source commit, and pull request. Human review remains appropriate for security, destructive behavior, credential handling, external side effects, and changes whose tests do not cover the claimed behavior.
