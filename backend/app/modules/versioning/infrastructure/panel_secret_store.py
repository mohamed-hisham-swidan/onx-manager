"""Encrypted panel-level integration secrets (P5.5).

The CurseForge API key is never stored in ``config/settings.yaml``. It lives in
``panel_integration_secrets`` encrypted with a fresh 256-bit DEK per record.
When a master KEK is configured the DEK is wrapped by it
(``encryption_mode="master_kek_v1"``); in Simple mode a panel-local ``0600``
key at ``<host_state_dir>/.onx-integration.key`` wraps the DEK
(``encryption_mode="panel_local_key_v1"``).

AAD binds every record to ``(encryption_mode, integration_key, kek_version)``
so ciphertext cannot be transplanted between integrations, modes, or KEK
versions. Status helpers return only ``configured``/``source``/``hint`` and
never plaintext.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppSettings
from app.core.exceptions import (
    MasterKekInvalidError,
    MasterKekMissingError,
    MasterKekVersionMismatchError,
    SecurityPermissionError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, resolve_host_state_layout
from app.modules.versioning.infrastructure.models import PanelIntegrationSecretModel
from app.modules.versioning.infrastructure.vault_crypto import MasterKek, load_master_kek

CURSEFORGE_API_KEY_NAME = "curseforge_api_key"
ALLOWED_INTEGRATION_KEYS = frozenset({CURSEFORGE_API_KEY_NAME})
ENCRYPTION_MODE_MASTER_KEK = "master_kek_v1"
ENCRYPTION_MODE_PANEL_LOCAL = "panel_local_key_v1"
_LOCAL_KEY_FILENAME = ".onx-integration.key"

_DEK_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_WRAPPED_DEK_BYTES = 60
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class PanelSecretEnvelope:
    """Wrapped DEK plus AES-256-GCM ciphertext for one integration secret."""

    encryption_mode: str
    wrapped_dek: bytes
    kek_version: int
    nonce: bytes
    ciphertext: bytes
    key_hint: str

    def __repr__(self) -> str:
        return (
            "PanelSecretEnvelope("
            f"encryption_mode={self.encryption_mode!r}, "
            f"kek_version={self.kek_version}, "
            "ciphertext=***REDACTED***)"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class PanelSecretStatus:
    configured: bool
    source: Literal["panel", "env", "none"]
    hint: str | None = None


def _aad(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _wrap_aad(integration_key: str, encryption_mode: str, kek_version: int) -> bytes:
    return _aad(
        {
            "encryption_mode": encryption_mode,
            "integration_key": integration_key,
            "kek_version": kek_version,
            "purpose": "panel_integration_secret_dek",
        }
    )


def _value_aad(integration_key: str, encryption_mode: str, kek_version: int) -> bytes:
    return _aad(
        {
            "encryption_mode": encryption_mode,
            "integration_key": integration_key,
            "kek_version": kek_version,
            "purpose": "panel_integration_secret_value",
        }
    )


def make_api_key_hint(secret: str) -> str:
    """Return a masked hint; never the key itself."""
    if isinstance(secret, str) and len(secret) >= 8:
        return f"***...{secret[-4:]}"
    return "***"


def _validate_integration_key(integration_key: str) -> str:
    if not isinstance(integration_key, str) or integration_key not in ALLOWED_INTEGRATION_KEYS:
        raise ValidationError(
            "Unsupported panel integration key",
            field="integration_key",
            details={"integration_key": str(integration_key)[:64]},
        )
    return integration_key


def _validate_plaintext(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValidationError(
            "Integration secret value must be a non-empty string",
            field="secret",
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in plaintext):
        raise ValidationError(
            "Integration secret value must be a single line without control characters",
            field="secret",
        )
    return plaintext


def _layout_root(layout: HostStateLayout | None, settings: AppSettings | None) -> Path:
    resolved = layout or resolve_host_state_layout(settings)
    return resolved.root


def _decode_local_key(raw: bytes) -> bytes:
    text = raw.strip()
    try:
        text_value = text.decode("ascii")
    except UnicodeDecodeError:
        text_value = ""
    if len(text_value) == 64 and all(ch in _HEX_CHARS for ch in text_value):
        return bytes.fromhex(text_value)
    if len(raw) == _DEK_BYTES:
        return raw
    raise MasterKekInvalidError(
        "Panel integration key file must contain 32 bytes or 64 hex characters",
        field="panel_integration_key",
    )


def _is_posix_host() -> bool:
    return os.name == "posix"


def _read_local_key(path: Path) -> bytes:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise MasterKekInvalidError(
            "Panel integration key file could not be inspected",
            field="panel_integration_key",
        ) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise SecurityPermissionError(
            f"Panel integration key {path} must be a regular non-symlink file"
        )
    reparse_attr = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if getattr(st, "st_file_attributes", 0) & reparse_attr:
        raise SecurityPermissionError(
            f"Panel integration key {path} must not be a reparse point"
        )
    if _is_posix_host() and (st.st_mode & 0o077) != 0:
        raise SecurityPermissionError(
            f"Insecure file permissions on panel integration key {path} "
            f"(mode {oct(st.st_mode & 0o777)}, expected 0600)"
        )

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise MasterKekInvalidError(
            "Panel integration key file could not be opened",
            field="panel_integration_key",
        ) from exc
    try:
        st = os.fstat(fd)
        if _is_posix_host() and (stat.S_IMODE(st.st_mode) & 0o077):
            raise SecurityPermissionError(
                f"Insecure file permissions on panel integration key {path}"
            )
        raw = os.read(fd, 4096)
    finally:
        os.close(fd)
    return _decode_local_key(raw)


def _load_or_create_local_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        return _read_local_key(path)
    except FileNotFoundError:
        pass

    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | getattr(os, "O_EXCL", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return _read_local_key(path)
    except OSError as exc:
        raise SecurityPermissionError(
            f"Failed to create panel integration key {path}: errno={exc.errno}"
        ) from exc

    try:
        if _is_posix_host() and hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.write(fd, secrets.token_hex(_DEK_BYTES).encode("ascii"))
        os.fsync(fd)
    except OSError as exc:
        raise SecurityPermissionError(
            f"Failed to write panel integration key {path}: errno={exc.errno}"
        ) from exc
    finally:
        os.close(fd)
    return _read_local_key(path)


def _load_active_wrapping_key(
    layout: HostStateLayout | None = None,
    settings: AppSettings | None = None,
    kek: MasterKek | None = None,
) -> tuple[str, int, bytes]:
    """Resolve the active wrapping key, mode, and version.

    Only a *missing* master KEK falls back to the panel-local key. A corrupt or
    insecure KEK raises without silently weakening encryption.
    """
    if kek is not None:
        return (ENCRYPTION_MODE_MASTER_KEK, kek.kek_version, kek.key_bytes)
    try:
        master = load_master_kek(settings)
    except MasterKekMissingError:
        root = _layout_root(layout, settings)
        return (
            ENCRYPTION_MODE_PANEL_LOCAL,
            1,
            _load_or_create_local_key(root / _LOCAL_KEY_FILENAME),
        )
    return (ENCRYPTION_MODE_MASTER_KEK, master.kek_version, master.key_bytes)


def _load_key_for_mode(
    encryption_mode: str,
    *,
    layout: HostStateLayout | None,
    settings: AppSettings | None,
    kek: MasterKek | None,
) -> tuple[int, bytes]:
    if encryption_mode == ENCRYPTION_MODE_MASTER_KEK:
        master = kek or load_master_kek(settings)
        return master.kek_version, master.key_bytes
    if encryption_mode == ENCRYPTION_MODE_PANEL_LOCAL:
        return (
            1,
            _load_or_create_local_key(
                _layout_root(layout, settings) / _LOCAL_KEY_FILENAME
            ),
        )
    raise ValidationError(
        "Unsupported panel integration encryption mode",
        field="encryption_mode",
        details={"encryption_mode": str(encryption_mode)[:32]},
    )


def encrypt_panel_secret(
    integration_key: str,
    plaintext: str,
    *,
    layout: HostStateLayout | None = None,
    settings: AppSettings | None = None,
    kek: MasterKek | None = None,
) -> PanelSecretEnvelope:
    """Encrypt one integration secret with a fresh DEK and nonce."""
    key = _validate_integration_key(integration_key)
    value = _validate_plaintext(plaintext)
    mode, kek_version, wrapping_key = _load_active_wrapping_key(layout, settings, kek)

    dek = os.urandom(_DEK_BYTES)
    wrap_nonce = os.urandom(_NONCE_BYTES)
    wrapped_dek = wrap_nonce + AESGCM(wrapping_key).encrypt(
        wrap_nonce,
        dek,
        _wrap_aad(key, mode, kek_version),
    )
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(
        nonce,
        value.encode("utf-8"),
        _value_aad(key, mode, kek_version),
    )
    return PanelSecretEnvelope(
        encryption_mode=mode,
        wrapped_dek=wrapped_dek,
        kek_version=kek_version,
        nonce=nonce,
        ciphertext=ciphertext,
        key_hint=make_api_key_hint(value),
    )


def decrypt_panel_secret(
    integration_key: str,
    envelope: PanelSecretEnvelope,
    *,
    layout: HostStateLayout | None = None,
    settings: AppSettings | None = None,
    kek: MasterKek | None = None,
) -> str:
    """Decrypt one integration secret, failing closed without leaking material."""
    key = _validate_integration_key(integration_key)
    if not isinstance(envelope, PanelSecretEnvelope):
        raise ValidationError(
            "Unable to decrypt panel integration secret",
            field="secret",
        )
    active_version, wrapping_key = _load_key_for_mode(
        envelope.encryption_mode,
        layout=layout,
        settings=settings,
        kek=kek,
    )
    if envelope.encryption_mode == ENCRYPTION_MODE_MASTER_KEK and (
        envelope.kek_version != active_version
    ):
        raise MasterKekVersionMismatchError(
            stored_kek_version=envelope.kek_version,
            active_kek_version=active_version,
        )
    if (
        len(envelope.wrapped_dek) != _WRAPPED_DEK_BYTES
        or len(envelope.nonce) != _NONCE_BYTES
        or len(envelope.ciphertext) < _TAG_BYTES
    ):
        raise ValidationError(
            "Unable to decrypt panel integration secret",
            field="secret",
        )

    try:
        dek = AESGCM(wrapping_key).decrypt(
            envelope.wrapped_dek[:_NONCE_BYTES],
            envelope.wrapped_dek[_NONCE_BYTES:],
            _wrap_aad(key, envelope.encryption_mode, envelope.kek_version),
        )
        plaintext = AESGCM(dek).decrypt(
            envelope.nonce,
            envelope.ciphertext,
            _value_aad(key, envelope.encryption_mode, envelope.kek_version),
        )
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "Unable to decrypt panel integration secret",
            field="secret",
        ) from exc


def _row_envelope(row: PanelIntegrationSecretModel) -> PanelSecretEnvelope:
    return PanelSecretEnvelope(
        encryption_mode=str(row.encryption_mode),
        wrapped_dek=bytes(row.wrapped_dek),
        kek_version=int(row.kek_version or 1),
        nonce=bytes(row.nonce),
        ciphertext=bytes(row.ciphertext),
        key_hint=str(row.key_hint) if row.key_hint is not None else "***",
    )


async def set_panel_secret(
    session: AsyncSession,
    integration_key: str,
    plaintext: str,
    *,
    layout: HostStateLayout | None = None,
    settings: AppSettings | None = None,
    kek: MasterKek | None = None,
) -> PanelSecretStatus:
    """Encrypt and upsert one panel integration secret."""
    key = _validate_integration_key(integration_key)
    envelope = encrypt_panel_secret(
        key, plaintext, layout=layout, settings=settings, kek=kek
    )
    now = datetime.now(UTC)
    row = await session.get(PanelIntegrationSecretModel, key)
    if row is None:
        session.add(
            PanelIntegrationSecretModel(
                integration_key=key,
                encryption_mode=envelope.encryption_mode,
                wrapped_dek=envelope.wrapped_dek,
                kek_version=envelope.kek_version,
                nonce=envelope.nonce,
                ciphertext=envelope.ciphertext,
                key_hint=envelope.key_hint,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        row.encryption_mode = envelope.encryption_mode
        row.wrapped_dek = envelope.wrapped_dek
        row.kek_version = envelope.kek_version
        row.nonce = envelope.nonce
        row.ciphertext = envelope.ciphertext
        row.key_hint = envelope.key_hint
        row.updated_at = now
    await session.commit()
    return PanelSecretStatus(configured=True, source="panel", hint=envelope.key_hint)


async def delete_panel_secret(
    session: AsyncSession,
    integration_key: str,
) -> bool:
    key = _validate_integration_key(integration_key)
    result = await session.execute(
        delete(PanelIntegrationSecretModel).where(
            PanelIntegrationSecretModel.integration_key == key
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def get_panel_secret_status(
    session: AsyncSession,
    integration_key: str,
    *,
    settings: AppSettings | None = None,
) -> PanelSecretStatus:
    """Return only configured/source/hint — never the plaintext secret."""
    key = _validate_integration_key(integration_key)
    row = await session.get(PanelIntegrationSecretModel, key)
    if row is not None:
        return PanelSecretStatus(
            configured=True,
            source="panel",
            hint=str(row.key_hint) if row.key_hint is not None else "***",
        )
    env_value = ((settings or AppSettings()).curseforge_api_key or "").strip()
    if env_value:
        return PanelSecretStatus(
            configured=True,
            source="env",
            hint=make_api_key_hint(env_value),
        )
    return PanelSecretStatus(configured=False, source="none", hint=None)


async def resolve_curseforge_api_key(
    session: AsyncSession | None = None,
    *,
    layout: HostStateLayout | None = None,
    settings: AppSettings | None = None,
    kek: MasterKek | None = None,
) -> str | None:
    """Resolve the CurseForge key from the DB first, then the environment."""
    if session is not None:
        row = await session.get(PanelIntegrationSecretModel, CURSEFORGE_API_KEY_NAME)
        if row is not None:
            return decrypt_panel_secret(
                CURSEFORGE_API_KEY_NAME,
                _row_envelope(row),
                layout=layout,
                settings=settings,
                kek=kek,
            )
    env_value = ((settings or AppSettings()).curseforge_api_key or "").strip()
    return env_value or None


__all__ = [
    "ALLOWED_INTEGRATION_KEYS",
    "CURSEFORGE_API_KEY_NAME",
    "ENCRYPTION_MODE_MASTER_KEK",
    "ENCRYPTION_MODE_PANEL_LOCAL",
    "PanelSecretEnvelope",
    "PanelSecretStatus",
    "decrypt_panel_secret",
    "delete_panel_secret",
    "encrypt_panel_secret",
    "get_panel_secret_status",
    "make_api_key_hint",
    "resolve_curseforge_api_key",
    "set_panel_secret",
]
