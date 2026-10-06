from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.security_files import ensure_private_key_permissions

_DEFAULT_KEY_PATH = Path("config/backup_encryption_key.bin")


def load_or_create_backup_key(
    path: str | None = None,
    allow_insecure: bool | None = None,
) -> bytes:
    """Load the 32-byte AES key from disk, generating and persisting it if missing.

    Mirrors the JWT key persistence pattern in app.modules.auth.infrastructure.jwt:
    if the key file exists it is read back; otherwise a new key is generated and
    written to disk so it survives process restarts. Calling this repeatedly
    without deleting the file returns the same key.
    """
    if path:
        key_path = Path(path)
    else:
        candidates = [
            Path("config/backup_encryption_key.bin"),
            Path("backend/config/backup_encryption_key.bin"),
        ]
        key_path = next((c for c in candidates if c.exists()), _DEFAULT_KEY_PATH)

    if key_path.exists():
        ensure_private_key_permissions(key_path, allow_insecure=allow_insecure)
        data = key_path.read_bytes()
        if len(data) != 32:
            raise ValueError(
                f"Backup encryption key file {key_path} must contain exactly 32 bytes "
                f"(found {len(data)})"
            )
        return data

    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix="backup_key_",
        suffix=".tmp",
        dir=key_path.parent,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        ensure_private_key_permissions(tmp_path_str, allow_insecure=allow_insecure)
        os.replace(tmp_path_str, key_path)
    except Exception:
        if os.path.exists(tmp_path_str):
            os.unlink(tmp_path_str)
        raise
    return key


def build_backup_encryption(
    path: str | None = None,
    allow_insecure: bool | None = None,
) -> BackupEncryption:
    return BackupEncryption(key=load_or_create_backup_key(path, allow_insecure=allow_insecure))


class BackupEncryption:
    def __init__(self, key: bytes | None = None) -> None:
        if key is not None and len(key) not in (32,):
            raise ValueError("Key must be 32 bytes for AES-256")
        self._key = key or os.urandom(32)

    @classmethod
    def generate_key(cls) -> bytes:
        return AESGCM.generate_key(bit_length=256)

    @classmethod
    def from_key_bytes(cls, key: bytes) -> BackupEncryption:
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes")
        return cls(key=key)

    @classmethod
    def from_key_hex(cls, key_hex: str) -> BackupEncryption:
        key = bytes.fromhex(key_hex)
        return cls(key=key)

    @property
    def key(self) -> bytes:
        return bytes(self._key)

    def encrypt(self, data: bytes, aad: bytes | None = None) -> bytes:
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, aad or b"")
        return nonce + ciphertext

    def decrypt(self, encrypted_data: bytes, aad: bytes | None = None) -> bytes:
        aesgcm = AESGCM(self._key)
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        return aesgcm.decrypt(nonce, ciphertext, aad or b"")

    def encrypt_stream(self, chunks: Any) -> Any:
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(12)
        yield nonce

        for i, chunk in enumerate(chunks):
            idx_bytes = i.to_bytes(12, "big")
            chunk_nonce = bytes(a ^ b for a, b in zip(nonce, idx_bytes, strict=True))
            encrypted = aesgcm.encrypt(chunk_nonce, chunk, b"")
            yield encrypted

    def decrypt_stream(self, encrypted_chunks: Any) -> Any:
        aesgcm = AESGCM(self._key)
        iterator = iter(encrypted_chunks)
        try:
            nonce_base = next(iterator)
        except StopIteration:
            return

        for i, chunk in enumerate(iterator):
            idx_bytes = i.to_bytes(12, "big")
            chunk_nonce = bytes(a ^ b for a, b in zip(nonce_base, idx_bytes, strict=True))
            yield aesgcm.decrypt(chunk_nonce, chunk, b"")

    def checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def key_as_hex(self) -> str:
        return self._key.hex()
