#!/usr/bin/env python3
"""tiercodec v1.0.0 - cross-tier CODEC determinism probe (11th tier-family member).

Designed divergence-risk plane: compressed BYTES depend on the linked C library
(zlib vs zlib-ng, libbz2, liblzma versions), not just on Python version. Proves
whether the compression plane renders byte-identical across architectures.
  A = zlib.compress levels 1/6/9 of 256 KiB xorshift64 stream -> H(blobs)
  B = bz2.compress levels 1/9 -> H(blobs)
  C = lzma.compress XZ presets 0/6 + FORMAT_ALONE -> H(blobs)
  D = integrity: every blob decompresses back to the exact original (rt=1)

Output one pipe-separated line:
  TC|tier|machine|python|libc|hA|hB|hC|rt|elapsed_ms

Usage: TC_TIER=local python3 tiercodec.py
Env: TC_TIER overrides tier label (default local).
"""
import bz2
import hashlib
import lzma
import os
import platform
import time
import zlib

tier = os.environ.get("TC_TIER", "local")
t0 = time.time()


def xorshift64_stream(nbytes):
    x = 0x9E3779B97F4A7C15
    buf = bytearray()
    while len(buf) < nbytes:
        x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 7
        x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
        buf += x.to_bytes(8, "little")
    return bytes(buf[:nbytes])


def h(blobs):
    hh = hashlib.sha256()
    for b_ in blobs:
        hh.update(len(b_).to_bytes(4, "big"))
        hh.update(b_)
    return hh.hexdigest()


data = xorshift64_stream(262144)
rt_ok = True

# ---- A: zlib levels 1/6/9 ----
za = [zlib.compress(data, l) for l in (1, 6, 9)]
hA = h(za)
for b_ in za:
    if zlib.decompress(b_) != data:
        rt_ok = False

# ---- B: bz2 levels 1/9 ----
zb = [bz2.compress(data, l) for l in (1, 9)]
hB = h(zb)
for b_ in zb:
    if bz2.decompress(b_) != data:
        rt_ok = False

# ---- C: lzma XZ presets 0/6 + FORMAT_ALONE ----
zc = [lzma.compress(data, preset=p) for p in (0, 6)]
zc.append(lzma.compress(data, format=lzma.FORMAT_ALONE))
hC = h(zc)
for b_ in zc:
    if lzma.decompress(b_) != data:
        rt_ok = False

rt = 1 if rt_ok else 0
elapsed_ms = int((time.time() - t0) * 1000)
libc = platform.libc_ver()[0] or "unknown"
print("TC|%s|%s|%s|%s|%s|%s|%s|%d|%d" % (
    tier, platform.machine(), platform.python_version(), libc, hA, hB, hC, rt, elapsed_ms))