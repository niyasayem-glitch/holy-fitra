#!/usr/bin/env python3
"""tierfloat v1.0.0 - cross-tier IEEE-754 floating-point determinism probe (stdlib-only).

8th tier-family member (family: tiermesh, qf_tier, forgestream, tierroot,
tierchain, tierhash, tierbloom, tierfloat). Probes WHERE cross-arch parity
holds in the FLOAT plane and where it can BREAK:

  PLANE A (arithmetic): + - * / ladder over exactly-representable binary
    values. IEEE-754 correctly-rounded ops MUST produce identical bit
    patterns on any conforming arch (aarch64 vs x86_64) => parity expected.

  PLANE B (transcendentals / libm): cos/sin/exp/log/pow/sqrt at fixed args.
    libm implementations are NOT bit-pinned across libcs (bionic/glibc/
    musl) or glibc versions => this is the FIRST tier probe that may
    legitimately DIVERGE. A divergence is a FINDING (it maps the boundary
    of tier-parity), not a failure. Raw repr() values are printed so any
    divergence is visible and diagnosable.

  PLANE C (summation): naive vs Kahan-compensated sum of a fixed 100001-term
    float series. Correctly-rounded adds => parity expected; Kahan detects
    cancellation drift deterministically.

Env knobs:
  TF_PLANE  which planes to run: A, B, C, or ABC (default ABC)
  TF_TIER   tier tag printed in the result line (default unknown)

Output: one line, pipe-separated via chr(124):
  88 <tier>|<machine>|<python>|<libc>|<hA>|<hB>|<hC>|<naive>|<kahan>|<cos>|<sin>|<exp>|<log>|<pow>|<sqrt>|<elapsed_ms>
"""
import hashlib
import math
import os
import platform
import struct
import time

SEP = chr(124)


def f2u(f: float) -> int:
    """Big-endian IEEE-754 bit pattern of a double (arch-independent)."""
    return int.from_bytes(struct.pack(">d", f), "big")


def h_update_double(h, f):
    h.update(f2u(f).to_bytes(8, "big"))


def plane_a() -> str:
    # Deterministic arithmetic ladder. All initial operands are exactly
    # representable binary fractions; intermediate results are correctly
    # rounded by IEEE-754 on every tier.
    acc = 1.0
    for i in range(1, 4097):
        acc += float(i) / 8.0          # exact binary fraction
        acc -= float(i % 17) / 16.0    # exact binary fraction
        acc *= 1.25                    # exact binary fraction
        if i % 64 == 0:
            acc /= 2.0
        acc -= float(i % 5) * 0.03125  # exact binary fraction
    h = hashlib.sha256()
    h_update_double(h, acc)
    for i in range(64):
        h_update_double(h, acc + float(i) * 0.125)
    return h.hexdigest()


def plane_b():
    args = [
        0.12345678901234567,
        1.2345678901234567,
        12.345678901234567,
        0.0078125,
        2.718281828459045,
        0.6931471805599453,
    ]
    vals = [
        math.cos(args[0]),
        math.sin(args[1]),
        math.exp(args[2] / 10.0),
        math.log(args[3] + 1.0),
        math.pow(args[4], args[5]),
        math.sqrt(args[1] * 2.0),
    ]
    h = hashlib.sha256()
    for v in vals:
        h_update_double(h, v)
    return h.hexdigest(), vals


def plane_c():
    # Fixed 100001-term float series; naive and Kahan-compensated.
    naive = 0.0
    kahan = 0.0
    comp = 0.0
    for i in range(1, 100002):
        term = float(i) / float(i + 1)
        naive += term
        y = term - comp
        t = kahan + y
        comp = (t - kahan) - y
        kahan = t
    h = hashlib.sha256()
    h_update_double(h, naive)
    h_update_double(h, kahan)
    return h.hexdigest(), naive, kahan


def main() -> int:
    planes = os.environ.get("TF_PLANE", "ABC").upper()
    tier = os.environ.get("TF_TIER", "unknown")
    t0 = time.monotonic()

    ha = plane_a() if "A" in planes else "skip"
    hb, bvals = plane_b() if "B" in planes else ("skip", [])
    hc, naive, kahan = plane_c() if "C" in planes else ("skip", 0.0, 0.0)

    libc = platform.libc_ver()[0] or "unknown"
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    bv = [repr(v) for v in bvals] + [""] * (6 - len(bvals))
    print(88, tier, platform.machine(), platform.python_version(), libc,
          ha, hb, hc, repr(naive), repr(kahan),
          bv[0], bv[1], bv[2], bv[3], bv[4], bv[5], elapsed_ms, sep=SEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())