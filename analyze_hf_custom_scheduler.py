from __future__ import annotations

import re
import statistics
from pathlib import Path


def parse(path: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for line in Path(path).read_text().splitlines():
        fields = {key: float(value) for key, value in re.findall(r"(\w+)=([^\s]+)", line)}
        if fields.get("completed") != 20000 or fields.get("queued") != 0 or fields.get("rejected") != 0:
            raise SystemExit(f"unexpected benchmark state: {line}")
        rows.append(fields)
    return rows


prior = parse("/tmp/hf_custom_scheduler_prior.txt")
custom = parse("/tmp/hf_custom_scheduler_lane.txt")
if len(prior) != 20 or len(custom) != 20:
    raise SystemExit("missing paired scheduler samples")
prior_tps = [row["tasks_per_second"] for row in prior]
custom_tps = [row["tasks_per_second"] for row in custom]
ratios = [after / before for before, after in zip(prior_tps, custom_tps)]
print(
    f"pairs={len(ratios)}"
    f" prior_mean_tps={statistics.fmean(prior_tps):.1f}"
    f" custom_mean_tps={statistics.fmean(custom_tps):.1f}"
    f" prior_median_tps={statistics.median(prior_tps):.1f}"
    f" custom_median_tps={statistics.median(custom_tps):.1f}"
    f" paired_speedup_geomean={statistics.geometric_mean(ratios):.3f}x"
    f" custom_faster_pairs={sum(after > before for before, after in zip(prior_tps, custom_tps))}/{len(ratios)}"
    f" prior_mean_stolen={statistics.fmean(row['stolen'] for row in prior):.1f}"
    f" custom_mean_stolen={statistics.fmean(row['stolen'] for row in custom):.1f}"
)
