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


original = parse("/tmp/hf_large_benchmark/hf_native_stronger_samples.txt")
batch = parse("/tmp/hf_batch_kernel/native_batch_samples.txt")
openblas = parse("/tmp/hf_large_benchmark/openblas_samples.txt")
if not original or len(original) != len(batch) or len(batch) != len(openblas):
    raise SystemExit("missing matched samples")
for rows in (original, batch, openblas):
    for row in rows:
        if abs(float(row["output_sum"]) - float(original[0]["output_sum"])) > 1e-6 or abs(float(row["output_weighted"]) - float(original[0]["output_weighted"])) > 1e-6:
            raise SystemExit("checksum mismatch")

original_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in original)
batch_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in batch)
openblas_mean = statistics.fmean(float(row["avg_batch_ms"]) for row in openblas)
macs = float(original[0]["macs"])
print(
    f"samples={len(original)}"
    f" original_mean_ms={original_mean:.6f}"
    f" batch_kernel_mean_ms={batch_mean:.6f}"
    f" speedup_vs_original={original_mean / batch_mean:.3f}x"
    f" batch_kernel_gmac_per_s={(macs / (batch_mean / 1000.0)) / 1e9:.3f}"
    f" openblas_gap_after={batch_mean / openblas_mean:.2f}x"
    " checksums=exact_within_1e-6"
)
