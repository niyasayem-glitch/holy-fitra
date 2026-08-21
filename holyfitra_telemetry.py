#!/usr/bin/env python3
"""Small append-only telemetry store for the Holy Fitra live dashboard."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


TELEMETRY_NAME = "telemetry.jsonl"


def normalize_root(root: Path) -> Path:
    root = root.resolve()
    if not (root / "holyfitra.toml").is_file() and (root.parent / "holyfitra.toml").is_file():
        return root.parent
    return root


def telemetry_path(root: Path) -> Path:
    root = normalize_root(root)
    configured = os.environ.get("HOLYFITRA_TELEMETRY")
    if configured:
        return Path(configured).expanduser().resolve()
    return root / ".holyfitra" / TELEMETRY_NAME


def record_event(root: Path, event: str, **fields: Any) -> Path:
    path = telemetry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "event": event, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def read_events(root: Path, limit: int = 500) -> list[dict[str, Any]]:
    path = telemetry_path(root)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle.readlines()[-limit:]:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
    except OSError:
        return []
    return events


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    compile_events = [event for event in events if event.get("event") == "compile"]
    quant_events = [event for event in events if event.get("event") == "quantization"]
    compile_hits = sum(1 for event in compile_events if event.get("cache_hit"))
    compile_misses = sum(1 for event in compile_events if not event.get("cache_hit"))
    compile_latencies = [float(event["elapsed_ms"]) for event in compile_events if "elapsed_ms" in event]
    quant_latencies = [float(event["elapsed_ms"]) for event in quant_events if "elapsed_ms" in event]
    last_quant = quant_events[-1] if quant_events else {}
    last_compile = compile_events[-1] if compile_events else {}
    return {
        "event_count": len(events),
        "compile": {
            "events": len(compile_events),
            "cache_hits": compile_hits,
            "cache_misses": compile_misses,
            "hit_rate": (compile_hits / len(compile_events)) if compile_events else None,
            "last_ms": compile_latencies[-1] if compile_latencies else None,
            "mean_ms": (sum(compile_latencies) / len(compile_latencies)) if compile_latencies else None,
            "last_digest": last_compile.get("digest"),
        },
        "quantization": {
            "events": len(quant_events),
            "last_ms": quant_latencies[-1] if quant_latencies else None,
            "mean_ms": (sum(quant_latencies) / len(quant_latencies)) if quant_latencies else None,
            "precision": last_quant.get("precision"),
            "proof_verified": last_quant.get("proof_verified"),
            "fallback": last_quant.get("fallback"),
            "layer_error": last_quant.get("layer_error"),
        },
        "last_ts": events[-1].get("ts") if events else None,
    }
