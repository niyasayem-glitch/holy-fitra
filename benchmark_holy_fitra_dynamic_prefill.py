#!/usr/bin/env python3
from __future__ import annotations

import time
import numpy as np

from holy_fitra_dynamic_prefill import DynamicPrefillPacker, SequenceRequest, ToyCausalPrefill


def main() -> int:
    rng = np.random.default_rng(21)
    lengths = [int(value) for value in rng.integers(8, 64, size=96)]
    requests = [SequenceRequest(f"r{i}", rng.standard_normal((length, 32)).astype(np.float32)) for i, length in enumerate(lengths)]
    model = ToyCausalPrefill(32)
    packer = DynamicPrefillPacker(bucket_width=8, max_tokens=1024, max_sequences=16)
    batches = packer.pack(requests)
    single_start = time.perf_counter()
    single = {request.request_id: model.single(request.tokens) for request in requests}
    single_ms = (time.perf_counter() - single_start) * 1000.0
    batch_start = time.perf_counter()
    fused = {}
    for batch in batches:
        fused.update(model.packed_bucket(batch))
    fused_ms = (time.perf_counter() - batch_start) * 1000.0
    max_error = max(float(np.max(np.abs(single[key] - fused[key]))) for key in single)
    total_tokens = sum(lengths)
    padded_tokens = sum(batch.batch_size * batch.padded_length for batch in batches)
    print({"sequences": len(requests), "batches": len(batches), "total_tokens": total_tokens, "padded_tokens": padded_tokens, "padding_overhead": padded_tokens / total_tokens, "single_ms": single_ms, "fused_ms": fused_ms, "speedup": single_ms / fused_ms, "max_error": max_error})
    return 0 if max_error < 1e-4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
