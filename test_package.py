#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hyperc_package import HyperPackageBuilder, PackageError


class PackageTests(unittest.TestCase):
    def test_build_sign_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.hc").write_text("module package_test\n")
            builder = HyperPackageBuilder("p", "1.0.0", "android.arm64", predecessor="old-digest")
            builder.add_file(root, "main.hc", "source")
            package = builder.build()
            package.sign_hmac(b"secret")
            self.assertTrue(package.verify_hmac(b"secret"))
            self.assertFalse(package.verify_hmac(b"wrong"))
            self.assertEqual(package.verify_files(root), [])
            self.assertEqual(package.predecessor, "old-digest")

    def test_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file_path = root / "model.bin"
            file_path.write_bytes(b"trusted")
            builder = HyperPackageBuilder("p", "1.0.0", "cpu")
            builder.add_file(root, "model.bin", "model")
            package = builder.build()
            package.sign_hmac(b"secret")
            file_path.write_bytes(b"tampered")
            self.assertTrue(any("hash mismatch" in error for error in package.verify_files(root)))
            # The manifest remains authentic; the payload verifier detects that
            # the bytes no longer match the signed manifest entry.
            self.assertTrue(package.verify_hmac(b"secret"))

    def test_path_escape_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").write_text("a")
            builder = HyperPackageBuilder("p", "1.0.0", "cpu")
            with self.assertRaises(PackageError):
                builder.add_file(root, "../outside", "source")
            builder.add_file(root, "a", "source")
            builder.package.files.append(builder.package.files[0])
            with self.assertRaises(PackageError):
                builder.build()


if __name__ == "__main__":
    unittest.main(verbosity=2)
