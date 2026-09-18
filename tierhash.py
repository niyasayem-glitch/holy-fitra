#!/usr/bin/env python3
"""tierhash v1.0.0 - time-anchored cross-tier hash-chain commitment probe (stdlib-only).

6th tier-family member (family: tiermesh, qf_tier, forgestream, tierroot,
tierchain, tierhash). Deterministic chain of SHA-256 links: each link hashes
the previous digest concatenated with the decimal bytes of (SEED+i). The
final root hex must be IDENTICAL on any tier/architecture (aarch64 local,
x86_64 cloud) => a portable time-anchored commitment usable for distributed
provenance / append-only checkpoints.

Env knobs (no CLI args needed for cloud curl-pipe):
  TH_N     seed/epoch anchor (default 20260918)
  TH_L     chain length in links (default 500)
  TH_TIER  tier tag printed in the result line (default unknown)

Output: one line, pipe-separated via chr(124):
  77 <tier>|<machine>|<python>|<root_hex>|<elapsed_ms>
"""
import hashlib
import os
import platform
import time

SEP = chr(124)


def main() -> int:
    n = int(os.environ.get("TH_N", "20260918"))
    length = int(os.environ.get("TH_L", "500"))
    tier = os.environ.get("TH_TIER", "unknown")

    h = str(n).encode()
    t0 = time.monotonic()
    for i in range(length):
        h = hashlib.sha256(h + str(n + i).encode()).digest()
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    print(77, tier, platform.machine(), platform.python_version(),
          h.hex(), elapsed_ms, sep=SEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())