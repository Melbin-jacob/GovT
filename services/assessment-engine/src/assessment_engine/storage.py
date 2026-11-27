"""Evidence file store: content-addressed files on the evidence volume.

With a service key (``ASSESSMENT_EVIDENCE_KEY``, base64 of 32 bytes) each file is
encrypted with AES-256-GCM (random 12-byte nonce stored in front of the ciphertext, the
file's SHA-256 as associated data). Without one, files rely on the volume's encryption at
rest (platform). Contents are never logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class StorageError(RuntimeError):
    pass


def parse_key(key: str) -> bytes | None:
    if not key:
        return None
    try:
        raw = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise StorageError("ASSESSMENT_EVIDENCE_KEY must be base64") from exc
    if len(raw) != 32:
        raise StorageError("ASSESSMENT_EVIDENCE_KEY must decode to 32 bytes (AES-256)")
    return raw


class EvidenceStore:
    def __init__(self, root: Path, key: bytes | None) -> None:
        self.root = root
        self.key = key

    @property
    def encrypted(self) -> bool:
        return self.key is not None

    def _path(self, sha256: str) -> Path:
        suffix = ".enc" if self.key else ".bin"
        return self.root / sha256[:2] / f"{sha256}{suffix}"

    def put(self, data: bytes) -> tuple[str, str]:
        """Store bytes; returns (sha256 of the plain bytes, relative path)."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = data
            if self.key:
                nonce = os.urandom(12)
                payload = nonce + AESGCM(self.key).encrypt(nonce, data, digest.encode())
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, path)
        return digest, str(path.relative_to(self.root))

    def get(self, relative: str, sha256: str) -> bytes:
        payload = (self.root / relative).read_bytes()
        if relative.endswith(".enc"):
            if not self.key:
                raise StorageError("evidence is encrypted but no ASSESSMENT_EVIDENCE_KEY is set")
            try:
                data = AESGCM(self.key).decrypt(payload[:12], payload[12:], sha256.encode())
            except InvalidTag as exc:
                raise StorageError("evidence file failed authentication (wrong key?)") from exc
        else:
            data = payload
        if hashlib.sha256(data).hexdigest() != sha256:
            raise StorageError("evidence file does not match its hash")
        return data
