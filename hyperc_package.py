#!/usr/bin/env python3
"""HyperPackage prototype for verified HyperC distribution artifacts."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageFile:
    path: str
    sha256: str
    size: int
    kind: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not self.path or path.is_absolute() or "\x00" in self.path or any(part in {"", ".", ".."} for part in path.parts):
            raise PackageError("package file path must be a normalized relative path")
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise PackageError("package file hash must be lowercase SHA-256")
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 0 or not self.kind:
            raise PackageError("package file size or kind is invalid")


@dataclass
class HyperPackage:
    name: str
    version: str
    target: str
    predecessor: str | None = None
    files: list[PackageFile] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.version or not self.target or not isinstance(self.metadata, dict):
            raise PackageError("package identity or metadata is invalid")

    def canonical_payload(self) -> bytes:
        payload = {
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "predecessor": self.predecessor,
            "files": [file.__dict__ for file in sorted(self.files, key=lambda item: item.path)],
            "metadata": self.metadata,
        }
        try:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        except (TypeError, ValueError) as error:
            raise PackageError("package metadata is not canonical JSON") from error

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_payload()).hexdigest()

    def sign_hmac(self, secret: bytes) -> str:
        if not secret:
            raise PackageError("signing secret cannot be empty")
        self.signature = hmac.new(secret, self.canonical_payload(), hashlib.sha256).hexdigest()
        return self.signature

    def verify_hmac(self, secret: bytes) -> bool:
        if not self.signature or not secret:
            return False
        expected = hmac.new(secret, self.canonical_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "schema": "hyperc.package/v1",
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "predecessor": self.predecessor,
            "files": [file.__dict__ for file in sorted(self.files, key=lambda item: item.path)],
            "metadata": self.metadata,
            "digest": self.digest(),
            "signature": self.signature,
        }

    def write_manifest(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(self.to_jsonable(), indent=2, sort_keys=True, allow_nan=False) + "\n")
        temporary.replace(path)

    def verify_files(self, root: Path) -> list[str]:
        errors: list[str] = []
        for file in self.files:
            candidate = (root / file.path).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                errors.append(f"path escapes package root: {file.path}")
                continue
            if not candidate.is_file():
                errors.append(f"missing package file: {file.path}")
                continue
            actual_size = candidate.stat().st_size
            actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual_size != file.size:
                errors.append(f"size mismatch: {file.path}")
            if actual_hash != file.sha256:
                errors.append(f"hash mismatch: {file.path}")
        return errors


class HyperPackageBuilder:
    def __init__(self, name: str, version: str, target: str, predecessor: str | None = None):
        self.package = HyperPackage(name, version, target, predecessor)

    def add_file(self, root: Path, relative_path: str, kind: str) -> None:
        raw_path = Path(relative_path)
        if not relative_path or raw_path.is_absolute() or "\x00" in relative_path or any(part in {"", ".", ".."} for part in raw_path.parts):
            raise PackageError(f"file path is not normalized and relative: {relative_path}")
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise PackageError(f"file escapes package root: {relative_path}") from exc
        if not candidate.is_file():
            raise PackageError(f"file does not exist: {relative_path}")
        content = candidate.read_bytes()
        normalized = candidate.relative_to(root.resolve()).as_posix()
        self.package.files.append(PackageFile(normalized, hashlib.sha256(content).hexdigest(), len(content), kind))

    def set_metadata(self, **metadata: Any) -> None:
        self.package.metadata.update(metadata)

    def build(self) -> HyperPackage:
        try:
            self.package.canonical_payload()
        except PackageError:
            raise
        paths = [file.path for file in self.package.files]
        if len(paths) != len(set(paths)):
            raise PackageError("duplicate package file")
        if not self.package.files:
            raise PackageError("package must contain at least one file")
        return self.package


def demo(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "main.hc"
    source.write_text("module demo\n")
    builder = HyperPackageBuilder("demo", "0.1.0", "android.arm64")
    builder.add_file(root, "main.hc", "source")
    builder.set_metadata(compiler="hyperc-prototype", reproducible=True)
    package = builder.build()
    package.sign_hmac(b"demo-secret")
    return {"manifest": package.to_jsonable(), "file_errors": package.verify_files(root), "signature_valid": package.verify_hmac(b"demo-secret")}


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        print(json.dumps(demo(Path(directory)), indent=2, sort_keys=True))
