from __future__ import annotations

import re
import statistics
from pathlib import Path


def parse(path: str) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for line in Path(path).read_text().splitlines():
        row: dict[str, float | str] = {}
        for key, value in re.findall(r"(\w+)=([^\s]+)", line):
            row[key] = value if key == "engine" else float(value)
        rows.append(row)
    return rows


before = parse("/tmp/hf_large_benchmark/hf_native_stronger_samples.txt")
after = parse("/tmp/hf_tile_kernel/native_tile_samples.txt")
openblas = parse("/tmp/hf_large_benchmark/openblas_samples.txt")
if not before or len(before) != len(after) or len(after) != len(openblas):
    raise SystemExit("missing matched samples")

for rows in (before, after, openblas):
    for row in rows:
        if abs(float(row["output_sum"]) - float(before[0]["output_sum"])) > 1e-6:
            raise SystemExit("output sum mismatch")
        if abs(float(row["output_weighted"]) - float(before[0]["output_weighted"])) > 1e-6:
            raise SystemExit("weighted checksum mismatch")

before_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in before)
after_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in after)
openblas_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in openblas)
macs = float(before[0]["macs"])
print(
    f"samples={len(before)}"
    f" before_mean_ms={before_mean:.6f}"
    f" after_mean_ms={after_mean:.6f}"
    f" speedup={before_mean / after_mean:.3f}x"
    f" before_gmac_per_s={(macs / (before_mean / 1000.0)) / 1e9:.3f}"
    f" after_gmac_per_s={(macs / (after_mean / 1000.0)) / 1e9:.3f}"
    f" openblas_gap_after={after_mean / openblas_mean:.2f}x"
    " checksums=exact_within_1e-6"
)
