DESC="""tierbloom v1.0.0 — cross-tier Bloom-filter parity probe. 7th tier-family member. Returns pipe-separated: 78|tier|machine|python|root_hex|bits_set|items|m|k|elapsed_ms."""
import sys
#!/usr/bin/env python3
"""tierbloom v1.0.0 - cross-tier Bloom-filter parity probe (stdlib-only).

7th tier-family member (family: tiermesh, qf_tier, forgestream, tierroot,
tierchain, tierhash, tierbloom). Builds a deterministic Bloom filter over a
self-generated item stream using double-hashing over sha256 digests and
serializes the ENTIRE bit array (16 KiB) to a sha256 root. The root hex must
be IDENTICAL on any tier/architecture (aarch64 local == x86_64 cloud) =>
proves a distributed MEMBERSHIP structure (data-plane state) converges
byte-exactly across tiers.

Env knobs (no CLI args needed for cloud curl-pipe):
  TB_N     seed/epoch anchor (default 20260918)
  TB_M     filter size in BITS (default 131072 = 16 KiB)
  TB_K     number of hash functions (default 7)
  TB_ITEMS number of inserted items (default 2000)
  TB_TIER  tier tag printed in the result line (default unknown)

Output: one line, pipe-separated via chr(124):
  78 <tier>|<machine>|<python>|<root_hex>|<bits_set>|<elapsed_ms>
"""
import hashlib
import os
import platform
import time

SEP = chr(124)


def main() -> int:
    n = int(os.environ.get("TB_N", "20260918"))
    m = int(os.environ.get("TB_M", "131072"))
    k = int(os.environ.get("TB_K", "7"))
    items = int(os.environ.get("TB_ITEMS", "2000"))
    tier = os.environ.get("TB_TIER", "unknown")

    bits = bytearray((m + 7) // 8)
    t0 = time.monotonic()
    for i in range(items):
        item = hashlib.sha256(str(n + i).encode()).digest()
        h1 = int.from_bytes(hashlib.sha256(b"a" + item).digest()[:8], "big")
        h2 = int.from_bytes(hashlib.sha256(b"b" + item).digest()[:8], "big")
        for j in range(k):
            idx = (h1 + j * h2) % m
            bits[idx >> 3] |= 1 << (idx & 7)
    root = hashlib.sha256(bytes(bits)).hexdigest()
    bits_set = sum(1 for byte in bits
                   for shift in range(8) if byte & (1 << shift))
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    print(78, tier, platform.machine(), platform.python_version(),
          root, bits_set, items, m, k, elapsed_ms, sep=SEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
if __name__=="__main__":
    print(forged(sys.argv[1] if len(sys.argv)>1 else ""))
