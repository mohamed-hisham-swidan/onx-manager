from __future__ import annotations

import base64
import json
import logging
import secrets
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from pathlib import Path

from app.core.config import AppSettings
from app.core.exceptions import AuthenticationError, TokenExpiredError

logger = logging.getLogger(__name__)

_private_key: RSAPrivateKey | None = None
_public_key: RSAPublicKey | None = None
_key_id: str | None = None

ACCESS_TOKEN_TTL = 900
REFRESH_TOKEN_TTL_DAYS = 7

_DEFAULT_KEY_PATH = Path("config/jwt_private_key.pem")


def _compute_key_id(pub_key: RSAPublicKey) -> str:
    der = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(der)
    return digest.finalize()[:16].hex()


def init_jwt_from_settings(settings: AppSettings) -> None:
    global _private_key, _public_key, _key_id

    pem_data: bytes | None = None

    if settings.jwt_private_key:
        pem_data = settings.jwt_private_key.encode()
        logger.info("Loading JWT private key from MCS_JWT_PRIVATE_KEY env var")
    elif settings.jwt_private_key_path:
        with open(settings.jwt_private_key_path, "rb") as f:
            pem_data = f.read()
        logger.info("Loading JWT private key from %s", settings.jwt_private_key_path)
    elif _DEFAULT_KEY_PATH.exists():
        with open(_DEFAULT_KEY_PATH, "rb") as f:
            pem_data = f.read()
        logger.info("Loading JWT private key from %s", _DEFAULT_KEY_PATH)

    if pem_data is not None:
        _private_key = serialization.load_pem_private_key(pem_data, password=None)
        _public_key = _private_key.public_key()
    else:
        logger.info(
            "No JWT private key configured (MCS_JWT_PRIVATE_KEY, MCS_JWT_PRIVATE_KEY_PATH, "
            "or %s). Generating and persisting a static key.",
            _DEFAULT_KEY_PATH,
        )
        _private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _public_key = _private_key.public_key()
        _DEFAULT_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        pem = _private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _DEFAULT_KEY_PATH.write_bytes(pem)
        logger.info("Persisted generated JWT private key to %s", _DEFAULT_KEY_PATH)

    _key_id = _compute_key_id(_public_key)
    logger.info("JWT key ID: %s", _key_id)


def _ensure_keys() -> None:
    global _private_key, _public_key, _key_id
    if _private_key is not None and _public_key is not None:
        return
    _private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _public_key = _private_key.public_key()
    _key_id = _compute_key_id(_public_key)


def set_private_key(pem_data: bytes) -> None:
    global _private_key, _public_key, _key_id
    _private_key = serialization.load_pem_private_key(pem_data, password=None)
    _public_key = _private_key.public_key()
    _key_id = _compute_key_id(_public_key)


def set_public_key(pem_data: bytes) -> None:
    global _public_key
    _public_key = serialization.load_pem_public_key(pem_data)


def get_key_id() -> str:
    _ensure_keys()
    return _key_id


def get_jwks() -> dict:
    _ensure_keys()
    pub_numbers = _public_key.public_numbers()
    n_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, "big")
    e_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, "big")
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": _key_id,
                "n": _b64(n_bytes),
                "e": _b64(e_bytes),
            }
        ],
    }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _sign_data(data: bytes) -> bytes:
    _ensure_keys()
    return _private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def _verify_signature(data: bytes, signature: bytes) -> bool:
    _ensure_keys()
    try:
        _public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def create_access_token(
    user_id: str,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    scope: str = "",
    ttl_seconds: int = ACCESS_TOKEN_TTL,
) -> str:
    _ensure_keys()
    header = {"alg": "RS256", "typ": "JWT", "kid": _key_id}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "roles": roles or [],
        "permissions": permissions or [],
        "scope": scope,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    message = f"{header_b64}.{payload_b64}".encode()
    sig = _sign_data(message)
    sig_b64 = _b64(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_access_token(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError("Invalid token format")
    header_b64, payload_b64, sig_b64 = parts
    message = f"{header_b64}.{payload_b64}".encode()
    try:
        sig = _unb64(sig_b64)
    except Exception:
        raise AuthenticationError("Invalid token signature encoding")
    if not _verify_signature(message, sig):
        raise AuthenticationError("Invalid token signature")
    try:
        payload = json.loads(_unb64(payload_b64).decode())
    except Exception:
        raise AuthenticationError("Invalid token payload")
    now = time.time()
    if payload.get("exp", 0) < now:
        raise TokenExpiredError()
    return payload


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def verify_ws_token(token: str) -> dict:
    claims = verify_access_token(token)
    return {
        "user_id": claims["sub"],
        "permissions": set(claims.get("permissions", [])),
    }
