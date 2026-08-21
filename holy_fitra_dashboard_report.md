# Holy Fitra Live Dashboard Report

## Implemented dashboard

Holy Fitra now has a real-time, dependency-free TUI dashboard backed by append-only JSONL telemetry at `.holyfitra/telemetry.jsonl`. The dashboard polls telemetry once per second by default and supports a configurable `--watch-interval`.

```bash
holyfitra tui . --watch-interval 1.0
```

For Termux, SSH, CI, and non-TTY sessions:

```bash
holyfitra tui . --snapshot
```

## Monitored signals

| Signal | Source | Dashboard fields |
|---|---|---|
| Native compiler activity | `holyfitra build` | event count, cache hits, misses, hit rate, digest, last/mean latency |
| Quantization calibration | `holyfitra bench` proof demo | event count, precision, calibration latency, layer error, proof verification, fallback state |
| Workspace state | TUI workspace | discovered `.hf` files, source preview, compiler mode, diagnostics, HyperIR digest |
| Runtime safety | existing compiler/runtime contracts | effect graph, ownership modes, task metadata, quantization proof status |

Telemetry emitted from `src/` is normalized to the project root when `holyfitra.toml` is present, so compiler and benchmark events appear in the same dashboard.

## Safety boundaries

The telemetry system only writes and reads JSONL records. It does not execute shell commands, access the network, expose secrets, or change compiler decisions. It tolerates malformed/truncated lines and limits dashboard reads to a bounded recent-event window. The environment variable `HOLYFITRA_TELEMETRY` can redirect records to an explicit path.

## End-to-end example

```bash
holyfitra init dashboard_demo --name dashboard_demo
holyfitra build dashboard_demo -o dashboard_demo/app
holyfitra build dashboard_demo -o dashboard_demo/app
holyfitra bench dashboard_demo --repeats 5
holyfitra tui dashboard_demo
```

The first identical build normally records a cache miss. The second records a cache hit. The benchmark records the proof-selected precision and calibration result. The curses dashboard refreshes these values without restarting the process.

## Validation

The dashboard wave passed 88 Python tests, Python bytecode compilation, dashboard snapshot smoke tests, compiler cache-hit telemetry, quantization proof telemetry, Termux shell syntax, NibbleFlow validation, ragged attention validation, native scheduler integration, and AddressSanitizer/UndefinedBehaviorSanitizer scheduler gates.
