from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.update_policy import verify_download, verify_signed_manifest


class UpdatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        public = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.public_key = base64.b64encode(public).decode("ascii")
        self.package = b"signed Misha package"
        self.manifest = {
            "version": "0.2.0",
            "build": 2,
            "channel": "stable",
            "download_url": "https://releases.example.test/Misha.zip",
            "sha256": hashlib.sha256(self.package).hexdigest(),
            "size_bytes": len(self.package),
        }

    def _signed(self, changes=None):
        payload = json.dumps({**self.manifest, **(changes or {})}, sort_keys=True).encode()
        signature = base64.b64encode(self.private_key.sign(payload)).decode("ascii")
        return payload, signature

    def test_exact_signed_manifest_and_download_hash_are_required(self):
        payload, signature = self._signed()
        manifest = verify_signed_manifest(payload, signature, self.public_key)
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "Misha.zip"
            package.write_bytes(self.package)
            self.assertTrue(verify_download(package, manifest))
            package.write_bytes(self.package + b"tampered")
            self.assertFalse(verify_download(package, manifest))

    def test_tampered_manifest_wrong_key_and_unsafe_url_fail_closed(self):
        payload, signature = self._signed()
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_signed_manifest(payload + b" ", signature, self.public_key)
        other_public = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_signed_manifest(
                payload, signature, base64.b64encode(other_public).decode("ascii")
            )
        unsafe_payload, unsafe_signature = self._signed(
            {"download_url": "http://127.0.0.1/update.zip"}
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            verify_signed_manifest(unsafe_payload, unsafe_signature, self.public_key)

    def test_unknown_fields_and_unbounded_packages_are_rejected(self):
        payload, signature = self._signed({"unexpected": True})
        with self.assertRaisesRegex(ValueError, "fields"):
            verify_signed_manifest(payload, signature, self.public_key)
        payload, signature = self._signed({"size_bytes": 1_000_000_001})
        with self.assertRaisesRegex(ValueError, "size"):
            verify_signed_manifest(payload, signature, self.public_key)


if __name__ == "__main__":
    unittest.main()
