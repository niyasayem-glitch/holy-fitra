#!/usr/bin/env python3
"""Generate bounded million-line Holy Fitra stress corpora."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TOTAL_LINES = 1_000_000
NEAR_LIMIT_LINES = 220_000


def write_sparse(path: Path) -> None:
    footer = "module million_sparse\nfn main() -> i32 {\n    return 0\n}\n"
    comment_lines = TOTAL_LINES - footer.count("\n")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n" * comment_lines)
        handle.write(footer)


def write_dense(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("module million_dense\n")
        for index in range(TOTAL_LINES - 2):
            handle.write(f"fn f{index}() -> i32 {{ return 0 }}\n")
        handle.write("fn main() -> i32 { return 0 }\n")


def write_near_limit(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("module near_limit\n")
        for index in range(NEAR_LIMIT_LINES - 2):
            handle.write(f"fn f{index}() -> i32 {{ return 0 }}\n")
        handle.write("fn main() -> i32 { return 0 }\n")


def describe(path: Path) -> dict[str, object]:
    data = path.stat()
    with path.open("rb") as handle:
        lines = sum(1 for _ in handle)
    return {"path": str(path), "bytes": data.st_size, "lines": lines}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sparse = args.output_dir / "million_sparse.hf"
    dense = args.output_dir / "million_dense.hf"
    near_limit = args.output_dir / "near_limit_dense.hf"
    write_sparse(sparse)
    write_dense(dense)
    write_near_limit(near_limit)
    print(json.dumps({"sparse": describe(sparse), "dense": describe(dense), "near_limit": describe(near_limit)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
