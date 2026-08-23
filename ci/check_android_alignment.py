#!/usr/bin/env python3
"""Verify Android native-library architecture and 16 KB ELF load alignment."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

LOAD_RE = re.compile(r"^\s*LOAD\s+.*\s(0x[0-9a-fA-F]+)\s*$")
MACHINE_RE = re.compile(r"Machine:\s+AArch64")


def inspect(readelf: Path, library: Path) -> tuple[int, list[str]]:
    result = subprocess.run(
        [str(readelf), "-h", "-lW", str(library)],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"llvm-readelf failed for {library}: {result.stderr.strip()}")
    if not MACHINE_RE.search(result.stdout):
        raise RuntimeError(f"{library} is not an AArch64 ELF")
    alignments = [
        int(match.group(1), 16)
        for line in result.stdout.splitlines()
        if (match := LOAD_RE.match(line))
    ]
    if not alignments:
        raise RuntimeError(f"{library} has no PT_LOAD program headers")
    invalid = [hex(value) for value in alignments if value < 0x4000 or value % 0x4000 != 0]
    if invalid:
        raise RuntimeError(f"{library} has non-16KB PT_LOAD alignment: {invalid}")
    return len(alignments), [hex(value) for value in alignments]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readelf", type=Path, required=True)
    parser.add_argument("libraries", type=Path, nargs="+")
    args = parser.parse_args()
    total = 0
    for library in args.libraries:
        count, alignments = inspect(args.readelf, library)
        total += count
        print(f"16k-aligned: {library} LOAD={alignments}")
    print(f"verified_libraries={len(args.libraries)} verified_load_segments={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
