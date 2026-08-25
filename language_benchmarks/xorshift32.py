#!/usr/bin/env python3
from __future__ import annotations

import sys
import time


if len(sys.argv) != 3:
    raise SystemExit(2)

iterations = int(sys.argv[1])
state = int(sys.argv[2]) & 0xFFFFFFFF
started = time.perf_counter_ns()
for _ in range(iterations):
    state ^= (state << 13) & 0xFFFFFFFF
    state &= 0xFFFFFFFF
    state ^= state >> 17
    state &= 0xFFFFFFFF
    state ^= (state << 5) & 0xFFFFFFFF
    state &= 0xFFFFFFFF
print(f"result={state} loop_ns={time.perf_counter_ns() - started}")
