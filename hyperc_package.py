#!/usr/bin/env python3
"""HyperPackage prototype for verified HyperC distribution artifacts."""
from __future__ import annotations

import hashlib
import hmac
import json
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


@dataclass
class HyperPackage:
    name: str
    version: str
    target: str
    predecessor: str | None = None
    files: list[PackageFile] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None

    def canonical_payload(self) -> bytes:
        payload = {
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "predecessor": self.predecessor,
            "files": [file.__dict__ for file in sorted(self.files, key=lambda item: item.path)],
            "metadata": self.metadata,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()

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
        path.write_text(json.dumps(self.to_jsonable(), indent=2, sort_keys=True))

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
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise PackageError(f"file escapes package root: {relative_path}") from exc
        if not candidate.is_file():
            raise PackageError(f"file does not exist: {relative_path}")
        content = candidate.read_bytes()
        self.package.files.append(PackageFile(relative_path, hashlib.sha256(content).hexdigest(), len(content), kind))

    def set_metadata(self, **metadata: Any) -> None:
        self.package.metadata.update(metadata)

    def build(self) -> HyperPackage:
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
