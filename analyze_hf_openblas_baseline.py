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


hf_rows = parse_samples(Path("/tmp/hf_large_benchmark/hf_native_stronger_samples.txt"))
blas_rows = parse_samples(Path("/tmp/hf_large_benchmark/openblas_samples.txt"))
if len(hf_rows) != len(blas_rows) or not hf_rows:
    raise SystemExit("missing matched benchmark samples")

for hf_row, blas_row in zip(hf_rows, blas_rows):
    if hf_row["macs"] != blas_row["macs"]:
        raise SystemExit("fixture MAC counts differ")
    for key in ("output_sum", "output_weighted"):
        if abs(float(hf_row[key]) - float(blas_row[key])) > 1e-6:
            raise SystemExit(f"checksum mismatch for {key}")

hf_ms = [float(row["avg_batch_ms"]) for row in hf_rows]
blas_ms = [float(row["avg_batch_ms"]) for row in blas_rows]
hf_mean = statistics.fmean(hf_ms)
blas_mean = statistics.fmean(blas_ms)
macs = float(hf_rows[0]["macs"])
print(
    f"samples={len(hf_rows)}"
    f" hf_mean_ms={hf_mean:.6f}"
    f" hf_min_ms={min(hf_ms):.6f}"
    f" hf_max_ms={max(hf_ms):.6f}"
    f" openblas_mean_ms={blas_mean:.6f}"
    f" openblas_min_ms={min(blas_ms):.6f}"
    f" openblas_max_ms={max(blas_ms):.6f}"
    f" openblas_vs_hf_speedup={hf_mean / blas_mean:.2f}x"
    f" hf_gmac_per_s={(macs / (hf_mean / 1000.0)) / 1e9:.3f}"
    f" openblas_gmac_per_s={(macs / (blas_mean / 1000.0)) / 1e9:.3f}"
    " checksums=exact_within_1e-6"
)
