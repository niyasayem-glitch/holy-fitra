#!/usr/bin/env python3
"""tierroot v1.0.0 — cross-tier Merkle-root commitment probe (stdlib-only).

Deterministic, arch-independent computation class: build a binary Merkle
tree over N leaves derived from a seeded MT19937 byte stream (canonical
big-endian packing), SHA-256 leaves, canonical left-right concat hashing
up to the root. The root hex must be IDENTICAL on any tier/architecture
(aarch64 local, x86_64 cloud, GPU host) => a portable commitment usable
for distributed checkpoints / federated provenance.

Env knobs (no CLI args needed for cloud curl-pipe):
  TR_N     number of leaves (default 120000)
  TR_BS    raw bytes per leaf preimage (default 32)
  TR_SEED  MT19937 seed (default 7)
  TR_TIER  tier tag printed in the result line (default unknown)

Output: one line, pipe-separated via chr(124):
  TIERROOT <tier>|<machine>|<python>|<ncpu>|<nleaves>|<blocksize>|<root16>|<bytes>|<hashes>|<height>|<elapsed_s>|<words_per_s>
"""
import hashlib
import math
import os
import platform
import random
import struct
import time

SEP = chr(124)


def main() -> int:
    n = int(os.environ.get("TR_N", "120000"))
    bs = int(os.environ.get("TR_BS", "32"))
    seed = int(os.environ.get("TR_SEED", "7"))
    tier = os.environ.get("TR_TIER", "unknown")

    rng = random.Random(seed)

    def next_block() -> bytes:
        # 8 x 32-bit BE-packed ints -> 32-byte canonical block (arch-independent)
        return b"".join(struct.pack(">I", rng.getrandbits(32)) for _ in range(8))

    t0 = time.monotonic()
    total_bytes = n * bs
    # generate full stream once, split into leaf preimages
    stream = bytearray(total_bytes)
    for i in range(0, total_bytes, 32):
        stream[i : i + 32] = next_block()

    # leaves: sha256 of each bs-byte chunk
    level = [
        hashlib.sha256(stream[i : i + bs]).digest()
        for i in range(0, total_bytes, bs)
    ]
    hashes = len(level)
    height = 1
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(hashlib.sha256(left + right).digest())
        level = nxt
        hashes += len(level)
        height += 1
    root = level[0].hex()[:16]
    elapsed = time.monotonic() - t0
    wps = total_bytes / elapsed if elapsed > 0 else 0.0

    print(
        88,
        tier,
        platform.machine(),
        platform.python_version(),
        os.cpu_count(),
        n,
        bs,
        root,
        total_bytes,
        hashes,
        height,
        round(elapsed, 3),
        round(wps, 1),
        sep=SEP,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())