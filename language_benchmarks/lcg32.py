#!/usr/bin/env python3
from __future__ import annotations

import sys

if len(sys.argv) != 3:
    raise SystemExit(2)

iterations = int(sys.argv[1]) & 0xFFFFFFFF
state = int(sys.argv[2]) & 0xFFFFFFFF
for _ in range(iterations):
    state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
print(f"result={state}")
