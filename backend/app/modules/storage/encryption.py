from __future__ import annotations

import hashlib
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


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

        counter = 0
        for chunk in chunks:
            chunk_nonce = counter.to_bytes(12, "big")
            counter += 1
            encrypted = aesgcm.encrypt(chunk_nonce, chunk, b"")
            yield encrypted

    def decrypt_stream(self, encrypted_chunks: Any) -> Any:
        aesgcm = AESGCM(self._key)
        counter = 0

        for chunk in encrypted_chunks:
            if counter == 0:
                counter += 1
                continue
            chunk_nonce = counter.to_bytes(12, "big")
            counter += 1
            yield aesgcm.decrypt(chunk_nonce, chunk, b"")

    def checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def key_as_hex(self) -> str:
        return self._key.hex()
