#!/usr/bin/env python3
"""tierchain v1.0.0 - cross-tier CHAINED-commitment probe (5th tier-traversal family member).

Computation class: ordered state transition (federated ledger append / distributed
checkpoint use-case). Each tier's output commitment feeds the NEXT tier's seed, so a
multi-tier run forms a verifiable CHAIN: cloud cannot compute H2 without receiving H1.

  genesis seed = 20260918 (constant)
  seed = int(prev_hex[:8], 16)   (bound to 32 bits, cross-version deterministic)
  fold(seed, n): MT19937 stream (random.Random, canonical BE packing) folded into
                 running sha256 -> 64-hex commitment

Usage:  python3 tierchain.py <tier> [prev-hex] [n]
  tier     local|cloud|gpu  (label only)
  prev-hex 0 or empty = genesis pass (prints H1); else transition pass (prints H2)
  n        stream length (default 1000000)

Output (one line, pipe-separated, quote-free):
  TIERCHAIN|<tier>|<n>|<prev8>|<new8>|<full64>
"""

import sys
import hashlib
import random

GENESIS = 20260918


def fold(seed, n):
    r = random.Random(seed)
    h = hashlib.sha256()
    h.update(b"tierchain-v1")
    for _ in range(n):
        h.update(r.getrandbits(32).to_bytes(4, "big"))
    return h.hexdigest()


def main():
    args = sys.argv[1:]
    tier = args[0] if len(args) > 0 else "local"
    prev = args[1] if len(args) > 1 else ""
    n = int(args[2]) if len(args) > 2 else 1000000
    if prev in ("", "0"):
        seed = GENESIS
        prev8 = "GENESIS"
    else:
        seed = int(prev[:8], 16)
        prev8 = prev[:8]
    h = fold(seed, n)
    print("TIERCHAIN|%s|%d|%s|%s|%s" % (tier, n, prev8, h[:8], h))


main()