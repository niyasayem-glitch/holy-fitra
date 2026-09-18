#!/usr/bin/env python3
"""tierdigest v1.0.0 - cross-tier CRYPTO-DIGEST determinism probe (9th tier-family member).

Three planes, all stdlib hashlib/hmac (OpenSSL-backed, RFC-standardized):
  A = HMAC-SHA256 chain, 300 iterations over growing payload
  B = PBKDF2-HMAC-SHA256, 10000 iterations, fixed salt, dklen=64
  C = SHA-256 full digest of 1 MiB deterministic xorshift64 stream

Output one pipe-separated line:
  TD|tier|machine|python|libc|hA|hB|hC|elapsed_ms

Usage: TD_TIER=local python3 tierdigest.py
Env: TD_TIER overrides tier label (default local).
"""
import hashlib
import hmac
import os
import platform
import time

tier = os.environ.get("TD_TIER", "local")
t0 = time.time()

# ---- A: HMAC-SHA256 chain ----
key = bytes(range(256))
msg = b"tierdigest-v1-genesis-2026-09-18"
ha = hashlib.sha256(b"tierdigest-seed-A").digest()
for i in range(300):
    ha = hmac.new(key, msg + ha + bytes([i % 251]), hashlib.sha256).digest()
hA = ha.hex()

# ---- B: PBKDF2-HMAC-SHA256 (RFC 8018, deterministic across OpenSSL versions) ----
salt = bytes([7, 13, 42, 99, 3, 17, 88, 5, 1, 9, 111, 222, 33, 44, 55, 66])
hB = hashlib.pbkdf2_hmac("sha256", b"tierdigest-passphrase-v1", salt, 10000, dklen=64).hex()

# ---- C: SHA-256 of 1 MiB xorshift64 stream (little-endian, arch-independent) ----
x = 0x9E3779B97F4A7C15
buf = bytearray()
for _ in range(131072):
    x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 7
    x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
    buf += x.to_bytes(8, "little")
hC = hashlib.sha256(bytes(buf)).hexdigest()

elapsed_ms = int((time.time() - t0) * 1000)
libc = platform.libc_ver()[0] or "unknown"
print("TD|%s|%s|%s|%s|%s|%s|%s|%d" % (
    tier, platform.machine(), platform.python_version(), libc, hA, hB, hC, elapsed_ms))