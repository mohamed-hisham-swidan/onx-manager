from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    kdf = Argon2id(
        salt=salt,
        length=32,
        iterations=2,
        lanes=1,
        memory_cost=19456,
    )
    key = kdf.derive(password.encode())
    return salt.hex() + ":" + key.hex()


def verify_password(password: str, hashed: str) -> bool:
    try:
        salt_hex, key_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        kdf = Argon2id(
            salt=salt,
            length=32,
            iterations=2,
            lanes=1,
            memory_cost=19456,
        )
        kdf.verify(password.encode(), expected_key)
        return True
    except Exception:
        return False


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_api_key(api_key), hashed)


def generate_api_key() -> str:
    return "mcs_" + secrets.token_urlsafe(32)


def generate_encryption_key() -> bytes:
    return Fernet.generate_key()


def encrypt_data(data: bytes, key: bytes) -> bytes:
    f = Fernet(key)
    return f.encrypt(data)


def decrypt_data(token: bytes, key: bytes) -> bytes:
    f = Fernet(key)
    return f.decrypt(token)
