from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    build: int
    channel: str
    download_url: str
    sha256: str
    size_bytes: int


def _parse_manifest(payload: bytes) -> UpdateManifest:
    if not payload or len(payload) > 16_384:
        raise ValueError("Update manifest size is invalid.")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Update manifest is not valid UTF-8 JSON.") from exc
    required = {"version", "build", "channel", "download_url", "sha256", "size_bytes"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("Update manifest fields do not match the signed schema.")
    version = str(raw["version"])
    channel = str(raw["channel"])
    digest = str(raw["sha256"])
    if not _SEMVER.fullmatch(version):
        raise ValueError("Update version is not semantic versioning.")
    if channel not in {"stable", "beta"}:
        raise ValueError("Update channel is not allowed.")
    if not _SHA256.fullmatch(digest):
        raise ValueError("Update SHA-256 is invalid.")
    if not isinstance(raw["build"], int) or isinstance(raw["build"], bool) or raw["build"] < 1:
        raise ValueError("Update build number is invalid.")
    size = raw["size_bytes"]
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 1_000_000_000:
        raise ValueError("Update package size is invalid.")
    url = urlsplit(str(raw["download_url"]))
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.port not in {None, 443}
        or url.fragment
    ):
        raise ValueError("Update URL must be credential-free HTTPS on port 443.")
    return UpdateManifest(version, raw["build"], channel, url.geturl(), digest, size)


def verify_signed_manifest(
    payload: bytes,
    signature_base64: str,
    public_key_base64: str,
) -> UpdateManifest:
    """Verify exact manifest bytes before parsing any update instructions."""
    try:
        signature = base64.b64decode(signature_base64, validate=True)
        public_key = base64.b64decode(public_key_base64, validate=True)
        if len(signature) != 64 or len(public_key) != 32:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Update manifest signature is invalid.") from exc
    return _parse_manifest(payload)


def verify_download(path: Path, manifest: UpdateManifest) -> bool:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        if candidate.stat().st_size != manifest.size_bytes:
            return False
        digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == manifest.sha256
    except OSError:
        return False
