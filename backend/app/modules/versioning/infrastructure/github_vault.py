"""AES-256-GCM GitHub credential and webhook-secret vault (P5-1).

Every value is encrypted with a fresh 256-bit DEK and a fresh 96-bit nonce.
The DEK is wrapped by the active master KEK and stored with ``kek_version``.
Both the DEK wrap and the value ciphertext use AAD bound to
``(server_id, purpose, kek_version)`` so material can never be transplanted
between servers, purposes, or KEK versions.

The module also generates Ed25519 deploy keypairs and verifies GitHub
HMAC-SHA256 webhook signatures. It never logs or returns raw secrets from
error paths.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.exceptions import (
    CasUnsupportedPlatformError,
    MasterKekVersionMismatchError,
    ValidationError,
    WebhookSignatureError,
)
from app.core.host_state import validate_server_segment
from app.modules.versioning.infrastructure.git_runner import GitCredentials
from app.modules.versioning.infrastructure.models import ServerGitHubConnectionModel
from app.modules.versioning.infrastructure.vault_crypto import (
    MasterKek,
    load_master_kek,
)

_DEK_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_WRAPPED_DEK_BYTES = 60

PURPOSE_PAT = "github_pat"
PURPOSE_SSH_DEPLOY_KEY = "github_ssh_deploy_key"
PURPOSE_WEBHOOK_SECRET = "github_webhook_secret"
ALLOWED_PURPOSES = frozenset(
    {PURPOSE_PAT, PURPOSE_SSH_DEPLOY_KEY, PURPOSE_WEBHOOK_SECRET}
)

AUTH_METHOD_PAT = "pat"
AUTH_METHOD_SSH_DEPLOY_KEY = "ssh_deploy_key"
ALLOWED_AUTH_METHODS = frozenset({AUTH_METHOD_PAT, AUTH_METHOD_SSH_DEPLOY_KEY})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SIGNATURE_RE = re.compile(r"\Asha256=([0-9a-f]{64})\Z")


@dataclass(frozen=True)
class EncryptedSecretEnvelope:
    """Wrapped DEK plus AES-256-GCM ciphertext for one secret value."""

    wrapped_dek: bytes
    kek_version: int
    nonce: bytes
    ciphertext: bytes

    def __repr__(self) -> str:
        return (
            f"EncryptedSecretEnvelope(kek_version={self.kek_version}, "
            "redacted=True)"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class Ed25519DeployKeypair:
    """Generated Ed25519 deploy keypair (private material is redacted in repr)."""

    private_key_pem: str
    public_key_openssh: str
    fingerprint_sha256: str

    def __repr__(self) -> str:
        return (
            f"Ed25519DeployKeypair(fingerprint_sha256={self.fingerprint_sha256!r}, "
            "private_key_pem=***REDACTED***)"
        )

    def __str__(self) -> str:
        return self.__repr__()


def _wrap_aad(server_id: str, purpose: str, kek_version: int) -> bytes:
    return json.dumps(
        {
            "kek_version": kek_version,
            "purpose": f"{purpose}_dek",
            "server_id": server_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _value_aad(server_id: str, purpose: str, kek_version: int) -> bytes:
    return json.dumps(
        {
            "kek_version": kek_version,
            "purpose": f"{purpose}_value",
            "server_id": server_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_purpose(purpose: str) -> str:
    if not isinstance(purpose, str) or purpose not in ALLOWED_PURPOSES:
        raise ValidationError(
            "Unsupported GitHub secret purpose",
            field="purpose",
            details={"purpose": str(purpose)[:64]},
        )
    return purpose


def _validate_plaintext(purpose: str, plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValidationError(
            "GitHub secret value must be a non-empty string",
            field="credential",
            details={"purpose": purpose},
        )
    if "\x00" in plaintext:
        raise ValidationError(
            "GitHub secret value must not contain NUL bytes",
            field="credential",
            details={"purpose": purpose},
        )
    if purpose in (PURPOSE_PAT, PURPOSE_WEBHOOK_SECRET):
        if "\r" in plaintext or "\n" in plaintext:
            raise ValidationError(
                "GitHub secret value must be a single line",
                field="credential",
                details={"purpose": purpose},
            )
    elif purpose == PURPOSE_SSH_DEPLOY_KEY and "PRIVATE KEY" not in plaintext:
        raise ValidationError(
            "SSH deploy key must contain a PRIVATE KEY block",
            field="credential",
            details={"purpose": purpose},
        )
    return plaintext


def encrypt_github_secret(
    server_id: str,
    purpose: str,
    plaintext: str,
    *,
    kek: MasterKek | None = None,
) -> EncryptedSecretEnvelope:
    """Encrypt one GitHub secret with a fresh DEK and nonce."""
    if os.name != "posix":
        raise CasUnsupportedPlatformError(
            "The GitHub secret vault requires a POSIX host"
        )
    segment = validate_server_segment(server_id)
    resolved_purpose = _validate_purpose(purpose)
    value = _validate_plaintext(resolved_purpose, plaintext)
    active_kek = kek or load_master_kek()

    dek = os.urandom(_DEK_BYTES)
    wrap_nonce = os.urandom(_NONCE_BYTES)
    wrapped_dek = wrap_nonce + AESGCM(active_kek.key_bytes).encrypt(
        wrap_nonce,
        dek,
        _wrap_aad(segment, resolved_purpose, active_kek.kek_version),
    )
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(
        nonce,
        value.encode("utf-8"),
        _value_aad(segment, resolved_purpose, active_kek.kek_version),
    )
    return EncryptedSecretEnvelope(
        wrapped_dek=wrapped_dek,
        kek_version=active_kek.kek_version,
        nonce=nonce,
        ciphertext=ciphertext,
    )


def decrypt_github_secret(
    server_id: str,
    purpose: str,
    envelope: EncryptedSecretEnvelope,
    *,
    kek: MasterKek | None = None,
) -> str:
    """Decrypt one GitHub secret, failing closed without leaking material."""
    segment = validate_server_segment(server_id)
    resolved_purpose = _validate_purpose(purpose)
    active_kek = kek or load_master_kek()

    if not isinstance(envelope, EncryptedSecretEnvelope):
        raise ValidationError(
            "Unable to decrypt GitHub secret",
            field="credential",
            details={"purpose": resolved_purpose},
        )
    if envelope.kek_version != active_kek.kek_version:
        raise MasterKekVersionMismatchError(
            stored_kek_version=envelope.kek_version,
            active_kek_version=active_kek.kek_version,
        )
    if (
        len(envelope.wrapped_dek) != _WRAPPED_DEK_BYTES
        or len(envelope.nonce) != _NONCE_BYTES
        or len(envelope.ciphertext) < _TAG_BYTES
    ):
        raise ValidationError(
            "Unable to decrypt GitHub secret",
            field="credential",
            details={"purpose": resolved_purpose},
        )

    try:
        dek = AESGCM(active_kek.key_bytes).decrypt(
            envelope.wrapped_dek[:_NONCE_BYTES],
            envelope.wrapped_dek[_NONCE_BYTES:],
            _wrap_aad(segment, resolved_purpose, active_kek.kek_version),
        )
        plaintext = AESGCM(dek).decrypt(
            envelope.nonce,
            envelope.ciphertext,
            _value_aad(segment, resolved_purpose, active_kek.kek_version),
        )
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "Unable to decrypt GitHub secret",
            field="credential",
            details={"purpose": resolved_purpose},
        ) from exc


def _sanitize_comment(comment: str | None, segment: str) -> str:
    if comment is None:
        return f"onx-manager-{segment}"
    if not isinstance(comment, str):
        raise ValidationError(
            "SSH key comment must be a string",
            field="comment",
        )
    cleaned = comment.strip()
    if not cleaned:
        return f"onx-manager-{segment}"
    if _CONTROL_RE.search(cleaned):
        raise ValidationError(
            "SSH key comment must not contain control characters",
            field="comment",
        )
    return cleaned[:128]


def generate_ed25519_deploy_keypair(
    server_id: str,
    *,
    comment: str | None = None,
) -> Ed25519DeployKeypair:
    """Generate an OpenSSH-format Ed25519 deploy keypair."""
    segment = validate_server_segment(server_id)
    key_comment = _sanitize_comment(comment, segment)

    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key_blob = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    public_key_openssh = f"{public_key_blob} {key_comment}"

    return Ed25519DeployKeypair(
        private_key_pem=private_key_pem,
        public_key_openssh=public_key_openssh,
        fingerprint_sha256=compute_ssh_public_key_fingerprint(public_key_openssh),
    )


def compute_ssh_public_key_fingerprint(public_key_openssh: str) -> str:
    """Return the ``SHA256:<base64-no-padding>`` OpenSSH fingerprint."""
    if not isinstance(public_key_openssh, str):
        raise ValidationError(
            "SSH public key must be a string",
            field="public_key",
        )
    parts = public_key_openssh.strip().split()
    if len(parts) < 2:
        raise ValidationError(
            "SSH public key is malformed",
            field="public_key",
        )
    key_type, encoded = parts[0], parts[1]
    if not key_type.startswith("ssh-") or len(key_type) <= 4:
        raise ValidationError(
            "SSH public key type is unsupported",
            field="public_key",
            details={"key_type": key_type[:32]},
        )
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "SSH public key is not valid base64",
            field="public_key",
        ) from exc
    digest = hashlib.sha256(blob).digest()
    encoded_digest = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded_digest}"


def make_credential_hint(
    auth_method: str,
    *,
    token: str | None = None,
    public_key: str | None = None,
) -> str:
    """Return a masked credential hint safe for API responses."""
    if auth_method == AUTH_METHOD_PAT:
        if not isinstance(token, str) or not token:
            raise ValidationError(
                "PAT token is required to build a credential hint",
                field="credential",
            )
        if len(token) >= 16:
            prefix = ""
            for candidate in ("github_pat_", "ghp_"):
                if token.startswith(candidate):
                    prefix = candidate
                    break
            return f"{prefix}...{token[-4:]}"
        if len(token) >= 8:
            return f"***...{token[-4:]}"
        return "***"

    if auth_method == AUTH_METHOD_SSH_DEPLOY_KEY:
        if not isinstance(public_key, str) or not public_key:
            raise ValidationError(
                "SSH public key is required to build a credential hint",
                field="credential",
            )
        return compute_ssh_public_key_fingerprint(public_key)[:64]

    raise ValidationError(
        "Unsupported GitHub auth method",
        field="auth_method",
        details={"auth_method": str(auth_method)[:32]},
    )


def generate_webhook_secret(num_bytes: int = 32) -> str:
    """Generate a lowercase-hex GitHub webhook secret (at least 32 bytes)."""
    if not isinstance(num_bytes, int) or isinstance(num_bytes, bool) or num_bytes < 32:
        raise ValidationError(
            "Webhook secret length must be at least 32 bytes",
            field="num_bytes",
        )
    return secrets.token_hex(num_bytes)


def _parse_signature_header(signature_header: str | None) -> str | None:
    if not isinstance(signature_header, str):
        return None
    match = _SIGNATURE_RE.match(signature_header)
    if match is None:
        return None
    return match.group(1)


def verify_github_webhook_signature(
    secret: str,
    raw_body: bytes,
    signature_header: str | None,
) -> bool:
    """Constant-time verification of ``X-Hub-Signature-256``."""
    if not isinstance(secret, str) or not secret:
        return False
    if not isinstance(raw_body, (bytes, bytearray)):
        return False
    provided = _parse_signature_header(signature_header)
    if provided is None:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        bytes(raw_body),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def assert_valid_webhook_signature(
    secret: str,
    raw_body: bytes,
    signature_header: str | None,
) -> None:
    """Raise :class:`WebhookSignatureError` when verification fails."""
    if not verify_github_webhook_signature(secret, raw_body, signature_header):
        raise WebhookSignatureError()


def _envelope_from_connection(
    wrapped_dek: object,
    kek_version: object,
    nonce: object,
    ciphertext: object,
    *,
    purpose: str,
) -> EncryptedSecretEnvelope:
    try:
        return EncryptedSecretEnvelope(
            wrapped_dek=bytes(wrapped_dek),  # type: ignore[arg-type]
            kek_version=int(kek_version),  # type: ignore[arg-type]
            nonce=bytes(nonce),  # type: ignore[arg-type]
            ciphertext=bytes(ciphertext),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Unable to decrypt GitHub secret",
            field="credential",
            details={"purpose": purpose},
        ) from exc


def apply_credential_to_connection(
    conn: ServerGitHubConnectionModel,
    *,
    server_id: str,
    auth_method: str,
    secret: str,
    deploy_public_key: str | None = None,
    kek: MasterKek | None = None,
) -> None:
    """Encrypt ``secret`` into the connection's credential columns."""
    segment = validate_server_segment(server_id)
    if auth_method not in ALLOWED_AUTH_METHODS:
        raise ValidationError(
            "Unsupported GitHub auth method",
            field="auth_method",
            details={"auth_method": str(auth_method)[:32]},
        )
    purpose = (
        PURPOSE_PAT if auth_method == AUTH_METHOD_PAT else PURPOSE_SSH_DEPLOY_KEY
    )
    envelope = encrypt_github_secret(
        segment,
        purpose,
        secret,
        kek=kek,
    )

    conn.server_id = segment
    conn.auth_method = auth_method
    conn.wrapped_credential_dek = envelope.wrapped_dek
    conn.kek_version = envelope.kek_version
    conn.credential_nonce = envelope.nonce
    conn.credential_ciphertext = envelope.ciphertext

    if auth_method == AUTH_METHOD_PAT:
        conn.credential_hint = make_credential_hint(
            AUTH_METHOD_PAT, token=secret
        )
        conn.deploy_public_key = None
        return

    if deploy_public_key:
        conn.credential_hint = make_credential_hint(
            AUTH_METHOD_SSH_DEPLOY_KEY,
            public_key=deploy_public_key,
        )
        conn.deploy_public_key = deploy_public_key
    else:
        conn.credential_hint = "***"
        conn.deploy_public_key = None


def decrypt_connection_credential(
    conn: ServerGitHubConnectionModel,
    *,
    kek: MasterKek | None = None,
) -> GitCredentials:
    """Decrypt a connection credential into a transient ``GitCredentials``."""
    segment = validate_server_segment(conn.server_id)
    auth_method = conn.auth_method
    if auth_method not in ALLOWED_AUTH_METHODS:
        raise ValidationError(
            "Unsupported GitHub auth method",
            field="auth_method",
            details={"auth_method": str(auth_method)[:32]},
        )
    purpose = (
        PURPOSE_PAT if auth_method == AUTH_METHOD_PAT else PURPOSE_SSH_DEPLOY_KEY
    )
    envelope = _envelope_from_connection(
        conn.wrapped_credential_dek,
        conn.kek_version,
        conn.credential_nonce,
        conn.credential_ciphertext,
        purpose=purpose,
    )
    plaintext = decrypt_github_secret(segment, purpose, envelope, kek=kek)
    if auth_method == AUTH_METHOD_PAT:
        return GitCredentials(auth_method="pat", token=plaintext)
    return GitCredentials(
        auth_method="ssh_deploy_key",
        ssh_private_key=plaintext,
    )


def apply_webhook_secret_to_connection(
    conn: ServerGitHubConnectionModel,
    *,
    server_id: str,
    webhook_secret: str,
    kek: MasterKek | None = None,
) -> None:
    """Encrypt a webhook secret into the connection's webhook columns."""
    segment = validate_server_segment(server_id)
    envelope = encrypt_github_secret(
        segment,
        PURPOSE_WEBHOOK_SECRET,
        webhook_secret,
        kek=kek,
    )
    conn.server_id = segment
    conn.wrapped_webhook_dek = envelope.wrapped_dek
    conn.webhook_kek_version = envelope.kek_version
    conn.webhook_nonce = envelope.nonce
    conn.webhook_ciphertext = envelope.ciphertext
    conn.webhook_enabled = True


def decrypt_connection_webhook_secret(
    conn: ServerGitHubConnectionModel,
    *,
    kek: MasterKek | None = None,
) -> str | None:
    """Decrypt the optional webhook secret, or return ``None`` if unset."""
    if (
        conn.wrapped_webhook_dek is None
        or conn.webhook_kek_version is None
        or conn.webhook_nonce is None
        or conn.webhook_ciphertext is None
    ):
        return None
    segment = validate_server_segment(conn.server_id)
    envelope = _envelope_from_connection(
        conn.wrapped_webhook_dek,
        conn.webhook_kek_version,
        conn.webhook_nonce,
        conn.webhook_ciphertext,
        purpose=PURPOSE_WEBHOOK_SECRET,
    )
    return decrypt_github_secret(
        segment,
        PURPOSE_WEBHOOK_SECRET,
        envelope,
        kek=kek,
    )


def clear_webhook_secret_on_connection(
    conn: ServerGitHubConnectionModel,
) -> None:
    """Remove all webhook secret material from a connection row."""
    conn.wrapped_webhook_dek = None
    conn.webhook_kek_version = None
    conn.webhook_nonce = None
    conn.webhook_ciphertext = None
    conn.webhook_enabled = False


class GitHubVault:
    """Namespaced access to the module-level GitHub vault helpers."""

    EncryptedSecretEnvelope = EncryptedSecretEnvelope
    Ed25519DeployKeypair = Ed25519DeployKeypair

    encrypt_secret = staticmethod(encrypt_github_secret)
    decrypt_secret = staticmethod(decrypt_github_secret)
    generate_deploy_keypair = staticmethod(generate_ed25519_deploy_keypair)
    compute_fingerprint = staticmethod(compute_ssh_public_key_fingerprint)
    make_credential_hint = staticmethod(make_credential_hint)
    generate_webhook_secret = staticmethod(generate_webhook_secret)
    verify_webhook_signature = staticmethod(verify_github_webhook_signature)
    assert_valid_webhook_signature = staticmethod(assert_valid_webhook_signature)
    apply_credential_to_connection = staticmethod(apply_credential_to_connection)
    decrypt_connection_credential = staticmethod(decrypt_connection_credential)
    apply_webhook_secret_to_connection = staticmethod(
        apply_webhook_secret_to_connection
    )
    decrypt_connection_webhook_secret = staticmethod(
        decrypt_connection_webhook_secret
    )
    clear_webhook_secret_on_connection = staticmethod(
        clear_webhook_secret_on_connection
    )


__all__ = [
    "ALLOWED_AUTH_METHODS",
    "ALLOWED_PURPOSES",
    "AUTH_METHOD_PAT",
    "AUTH_METHOD_SSH_DEPLOY_KEY",
    "Ed25519DeployKeypair",
    "EncryptedSecretEnvelope",
    "GitHubVault",
    "PURPOSE_PAT",
    "PURPOSE_SSH_DEPLOY_KEY",
    "PURPOSE_WEBHOOK_SECRET",
    "apply_credential_to_connection",
    "apply_webhook_secret_to_connection",
    "assert_valid_webhook_signature",
    "clear_webhook_secret_on_connection",
    "compute_ssh_public_key_fingerprint",
    "decrypt_connection_credential",
    "decrypt_connection_webhook_secret",
    "decrypt_github_secret",
    "encrypt_github_secret",
    "generate_ed25519_deploy_keypair",
    "generate_webhook_secret",
    "make_credential_hint",
    "verify_github_webhook_signature",
]
