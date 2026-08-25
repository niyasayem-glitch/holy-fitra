from __future__ import annotations

import re
import statistics
from pathlib import Path


def values(path: str) -> list[float]:
    result: list[float] = []
    for line in Path(path).read_text().splitlines():
        match = re.search(r"avg_batch_ms=([^\s]+)", line)
        if not match:
            raise SystemExit(f"missing timing in {path}")
        result.append(float(match.group(1)))
    return result


prior = values("/tmp/hf_avx2_kernel/interleaved_prior.txt")
avx2 = values("/tmp/hf_avx2_kernel/interleaved_avx2.txt")
if len(prior) != 20 or len(avx2) != 20:
    raise SystemExit("missing paired samples")
ratios = [before / after for before, after in zip(prior, avx2)]
print(
    f"pairs={len(ratios)}"
    f" prior_mean_ms={statistics.fmean(prior):.6f}"
    f" avx2_mean_ms={statistics.fmean(avx2):.6f}"
    f" prior_median_ms={statistics.median(prior):.6f}"
    f" avx2_median_ms={statistics.median(avx2):.6f}"
    f" paired_speedup_geomean={statistics.geometric_mean(ratios):.3f}x"
    f" avx2_faster_pairs={sum(after < before for before, after in zip(prior, avx2))}/{len(ratios)}"
)
