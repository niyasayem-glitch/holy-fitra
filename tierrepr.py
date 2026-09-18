#!/usr/bin/env python3
"""tierrepr v1.0.0 — cross-tier REPRESENTATION determinism probe (10th tier-family member).

Proves that not only raw computation but the TEXTUAL/CANONICAL RENDERING of values is
byte-identical across architectures. Three planes:
  A: repr/str/format rendering of floats (correctly-rounded shortest text)
     — specials (inf, -inf, +/-0.0, extremes, subnormals) + seeded-random values, 5 renderings each
  B: canonical JSON serialization (sort_keys=True, ensure_ascii=True, compact separators)
     of a nested structure containing floats, unicode, bools, None, bigint, lists
  C: canonical encodings — Decimal (60-digit ctx), Fraction arithmetic, struct >Q pack,
     base64/hex of fixed bytes, itertools permutation slice, unicode_escape encoding

All randomness seeded identically (random.Random(20260918)); every step is pure-Python or
correctly-rounded stdlib → expected byte-exact parity across architectures.

Output (one pipe-separated line, full 64-hex):
89|tier|machine|python|libc|hA|hB|hC|root|elapsed_ms
"""
import base64
import decimal
import fractions
import hashlib
import itertools
import json
import math
import os
import platform
import random
import struct
import time

TIER = os.environ.get("TB_TIER", "local")


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> None:
    t0 = time.perf_counter()
    rng = random.Random(20260918)

    # ---- Plane A: float rendering ----
    vals = [
        0.0, -0.0, 1.0, -1.0, math.inf, -math.inf, math.pi, math.e,
        1e-300, -1e-308, 1e308, 1.7976931348623157e308, 5e-324,
        2.2250738585072014e-308, 3.141592653589793, 2.718281828459045,
        1e-16, 1e16, 123456789.123456789, -42.0, 0.1, 0.2, 0.3,
    ]
    vals += [rng.random() * 1e6 - 5e5 for _ in range(500)]
    vals += [rng.uniform(-1e300, 1e300) for _ in range(200)]
    parts = []
    for v in vals:
        parts.append(repr(v))
        parts.append(str(v))
        parts.append(format(v, ".17g"))
        parts.append(format(v, ".6f"))
        parts.append(format(v, ".3e"))
    a = "|".join(parts).encode("utf-8", "surrogatepass")

    # ---- Plane B: canonical JSON ----
    s = {
        "nested": {
            "list": [1.5, -0.0, 3.141592653589793, 1e-16, "he\u0301llo\u00e9\u4e2d\u6587", [True, False, None]],
            "obj": {"z": 1, "a": [1, 2, 3], "m": {"k": "v", "j": 0.25}},
        },
        "big": 123456789012345678901234567890,
        "f": [rng.random() * 100 for _ in range(50)],
        "tiny": -1.5e-200,
        "ratio": 22 / 7,
    }
    b = json.dumps(s, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")

    # ---- Plane C: canonical encodings ----
    decimal.getcontext().prec = 60
    D = decimal.Decimal
    c1 = str(D(1) / D(7) * D(355) / D(113))
    c2 = str(sum(D(i).sqrt() for i in range(1, 101)))
    F = fractions.Fraction
    c3 = str(F(1, 7) + F(3, 11) * F(5, 13) - F(7, 17) ** 2)
    c4 = struct.pack(">Q", 2**63 + 12345).hex()
    c5 = base64.b64encode(bytes(range(256))).decode("ascii")
    c6 = base64.b16encode(hashlib.sha256(b"representations are deterministic").digest()).decode("ascii")
    c7 = str(list(itertools.islice(itertools.permutations("0123456789"), 1000, 1010)))
    c8 = "fi\ufb01\uff46\uff4cutter \u2014 \u00bd\u00b2\u00b3".encode("unicode_escape").decode("ascii")
    c = "|".join([c1, c2, c3, c4, c5, c6, c7, c8]).encode("ascii")

    hA, hB, hC = h(a), h(b), h(c)
    root = h((hA + hB + hC).encode("ascii"))
    el = int((time.perf_counter() - t0) * 1000)
    mach = platform.machine()
    pyv = platform.python_version()
    libc = platform.libc_ver()[0] or "unknown"
    print("|".join(["89", TIER, mach, pyv, libc, hA, hB, hC, root, str(el)]))


if __name__ == "__main__":
    main()