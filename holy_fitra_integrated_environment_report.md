# Holy Fitra Integrated Environment Upgrade

## Scope

Holy Fitra has been expanded beyond the initial compiler slice into an integrated terminal development environment. The new layer is dependency-free and uses Python's standard library so it can run on Termux without Textual, Rich, or another heavyweight UI framework.

## New capabilities

| Capability | Implementation |
|---|---|
| Terminal UI | `holyfitra_tui.py` with curses navigation, source preview, inspection results, benchmark action, and keyboard controls |
| Noninteractive TUI | `holyfitra tui PATH --snapshot` for CI, SSH, logs, and terminals without a real TTY |
| Interactive REPL | `holyfitra_repl.py` with project loading, multiline source buffering, checking, HyperIR planning, LLVM emission, and native build commands |
| Environment doctor | `holyfitra doctor` reports Python, Termux, Clang, LLVM, CMake, NumPy, curses, Android NDK, and backend readiness |
| Benchmark dashboard | `holyfitra bench PATH --repeats N` reports compiler timing, HyperIR/native digest, proof-carrying quantization, and ragged-attention error |
| Workspace browser | Recursively discovers `.hf` files, supports selection, source inspection, and project-level state |
| Termux validation | `termux-build.sh --host-tests` now includes UI tests, doctor, snapshot mode, benchmark smoke, NibbleFlow, ragged attention, and native scheduler checks |

## TUI controls

The interactive TUI is opened with:

```bash
holyfitra tui .
```

`j`/`k` or arrow keys select files. `c` inspects compiler diagnostics, `p` refreshes the plan summary, `b` runs the benchmark dashboard, `r` refreshes the workspace, and `q` or Escape exits. The snapshot mode is deterministic and suitable for automation:

```bash
holyfitra tui . --snapshot
```

## REPL commands

The REPL is opened with:

```bash
holyfitra repl
```

The supported commands are `/help`, `/project PATH`, `/source`, `/check`, `/plan [OUTPUT]`, `/llvm OUTPUT`, `/build OUTPUT`, `/show`, `/clear`, and `/quit`. Source is buffered explicitly after `/source`; ordinary input is not passed to a shell. This keeps the interactive environment safe from accidental command execution.

## Validation

The final integrated gate passed:

```text
67 Python tests: passed
TUI snapshot: passed
REPL command loop: passed
Doctor report: passed
Benchmark dashboard: passed
Termux script syntax: passed
Termux-compatible host validation: passed
NibbleFlow validation: passed
Ragged attention validation: passed
Native scheduler integration: passed
AddressSanitizer/UndefinedBehaviorSanitizer scheduler gate: passed
```

The benchmark dashboard is explicitly a local development diagnostic. It does not claim physical Android performance, thermal behavior, or device-specific NEON/SVE throughput.

## Remaining boundary

This is a substantially more complete developer environment, but Holy Fitra is still not a finished self-hosted programming language. The next compiler milestones remain full tensor pointer/shape ABI lowering, richer control flow and data types, dependency-aware incremental compilation, native ownership/effect enforcement, language-server functionality, and direct Android NDK library packaging. The TUI and REPL now make those systems inspectable and usable while they continue to mature.
