from __future__ import annotations

import re
import statistics
from pathlib import Path


def parse_samples(path: Path) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for line in path.read_text().splitlines():
        row: dict[str, float | str] = {}
        for key, value in re.findall(r"(\w+)=([^\s]+)", line):
            row[key] = value if key == "engine" else float(value)
        rows.append(row)
    return rows


def mean(values: list[float]) -> float:
    return statistics.fmean(values)


native = parse_samples(Path("/tmp/hf_large_benchmark/native_samples.txt"))
python_rows = parse_samples(Path("/tmp/hf_large_benchmark/python_samples.txt"))
if len(native) != len(python_rows) or not native:
    raise SystemExit("missing matched benchmark samples")

for native_row, python_row in zip(native, python_rows):
    if native_row["macs"] != python_row["macs"]:
        raise SystemExit("fixture MAC counts differ")
    for key in ("output_sum", "output_weighted"):
        if abs(float(native_row[key]) - float(python_row[key])) > 1e-6:
            raise SystemExit(f"checksum mismatch for {key}")

native_ms = [float(row["avg_batch_ms"]) for row in native]
python_ms = [float(row["avg_batch_ms"]) for row in python_rows]
macs = float(native[0]["macs"])
native_mean = mean(native_ms)
python_mean = mean(python_ms)
print(
    "samples=" + str(len(native))
    + f" native_mean_ms={native_mean:.6f}"
    + f" native_min_ms={min(native_ms):.6f}"
    + f" native_max_ms={max(native_ms):.6f}"
    + f" python_mean_ms={python_mean:.6f}"
    + f" python_min_ms={min(python_ms):.6f}"
    + f" python_max_ms={max(python_ms):.6f}"
    + f" native_vs_python_speedup={python_mean / native_mean:.2f}x"
    + f" native_gmac_per_s={(macs / (native_mean / 1000.0)) / 1e9:.3f}"
    + f" python_gmac_per_s={(macs / (python_mean / 1000.0)) / 1e9:.6f}"
    + " checksums=exact_within_1e-6"
)
