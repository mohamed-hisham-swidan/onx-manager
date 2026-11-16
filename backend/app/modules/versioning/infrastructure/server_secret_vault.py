"""Per-record encrypted ``server_secrets`` vault (P3-3, H3).

Every ``store_secret(server_id, key_name, value)`` call creates a fresh 256-bit
DEK and a fresh 96-bit nonce. The DEK is wrapped by the active master KEK and
stored with ``kek_version``; the value is encrypted with AES-256-GCM and AAD
bound to ``(server_id, key_name, kek_version)`` so a ciphertext can never be
transplanted between servers, keys, or KEK versions.

Committed files reference values as ``${ONX_SECRET_<KEY_NAME>}``. Clean Export
resolves those placeholders from this vault during Step 5. A server with no
stored secrets never needs the KEK, which keeps Simple-mode and empty Clean
Export flows fully KEK-free.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import (
    CasUnsupportedPlatformError,
    MasterKekVersionMismatchError,
    ValidationError,
)
from app.core.host_state import (
    HostStateLayout,
    resolve_host_state_layout,
    validate_server_segment,
)
from app.modules.versioning.infrastructure.class_c_snapshot import (
    _LedgerRunner,
    _run_async,
)
from app.modules.versioning.infrastructure.models import ServerSecretModel
from app.modules.versioning.infrastructure.secret_scanner import assert_no_secrets
from app.modules.versioning.infrastructure.vault_crypto import load_master_kek

SECRET_PLACEHOLDER_PREFIX = "${ONX_SECRET_"
SECRET_PLACEHOLDER_SUFFIX = "}"
_KEY_NAME_RE = re.compile(r"\A[A-Za-z0-9_]{1,128}\Z")

_DEK_BYTES = 32
_NONCE_BYTES = 12
_WRAPPED_DEK_BYTES = _NONCE_BYTES + _DEK_BYTES + 16


@dataclass(frozen=True)
class SecretExtractionResult:
    key_name: str
    placeholder: str
    relpath: str
    content: bytes
    replaced_count: int = 0

    @property
    def updated_content(self) -> bytes:
        return self.content


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aad(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _wrap_aad(server_id: str, key_name: str, kek_version: int) -> bytes:
    return _aad(
        {
            "kek_version": kek_version,
            "key_name": key_name,
            "purpose": "server_secret_dek",
            "server_id": server_id,
        }
    )


def _value_aad(server_id: str, key_name: str, kek_version: int) -> bytes:
    return _aad(
        {
            "kek_version": kek_version,
            "key_name": key_name,
            "purpose": "server_secret_value",
            "server_id": server_id,
        }
    )


def normalize_key_name(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValidationError("Secret key name must be a string", field="key_name")
    key_name = raw.strip().upper()
    if not _KEY_NAME_RE.match(key_name):
        raise ValidationError(
            "Secret key name must match [A-Za-z0-9_]{1,128}",
            field="key_name",
        )
    return key_name


def _validate_secret_value(secret_value: object) -> str:
    if not isinstance(secret_value, str):
        raise ValidationError("Secret value must be a string", field="secrets")
    if not secret_value:
        raise ValidationError("Secret value must not be empty", field="secrets")
    if any(ch in secret_value for ch in ("\x00", "\n", "\r")):
        raise ValidationError(
            "Secret value contains a forbidden control character",
            field="secrets",
        )
    return secret_value


def derive_secret_key_name(relpath: str, key_path: str) -> str:
    """Return a deterministic uppercase ``[A-Z0-9_]`` key name for a location."""
    raw = f"{relpath}:{key_path}" if key_path else str(relpath)
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    if not sanitized:
        sanitized = "SECRET"
    if len(sanitized) > 128:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
        sanitized = f"{sanitized[:119]}_{digest}"
    return normalize_key_name(sanitized)


def placeholder_for(key_name: str) -> str:
    return f"{SECRET_PLACEHOLDER_PREFIX}{normalize_key_name(key_name)}{SECRET_PLACEHOLDER_SUFFIX}"


class ServerSecretVault:
    """Store and resolve ``${ONX_SECRET_*}`` values in ``server_secrets``."""

    def __init__(
        self,
        layout: HostStateLayout | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._layout = layout or resolve_host_state_layout()
        self._ledger = _LedgerRunner(
            self._layout,
            session_factory=session_factory,
            sync_session_factory=sync_session_factory,
        )

    @property
    def _is_async(self) -> bool:
        return self._ledger.mode == "async"

    def close(self) -> None:
        self._ledger.close()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def store_secret(self, server_id: str, key_name: str, secret_value: str) -> None:
        if os.name != "posix":
            raise CasUnsupportedPlatformError(
                "The server secret vault requires a POSIX host"
            )
        segment = validate_server_segment(server_id)
        name = normalize_key_name(key_name)
        value = _validate_secret_value(secret_value)
        kek = load_master_kek()

        dek = os.urandom(_DEK_BYTES)
        wrap_nonce = os.urandom(_NONCE_BYTES)
        wrapped_dek = wrap_nonce + AESGCM(kek.key_bytes).encrypt(
            wrap_nonce,
            dek,
            _wrap_aad(segment, name, kek.kek_version),
        )
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(
            nonce,
            value.encode("utf-8"),
            _value_aad(segment, name, kek.kek_version),
        )
        now = _utcnow()
        values = {
            "wrapped_dek": wrapped_dek,
            "kek_version": kek.kek_version,
            "nonce": nonce,
            "ciphertext": ciphertext,
            "updated_at": now,
        }

        if self._is_async:
            factory = self._ledger.async_factory

            async def _store() -> None:
                async with factory() as session:
                    row = (
                        await session.execute(
                            select(ServerSecretModel).where(
                                ServerSecretModel.server_id == segment,
                                ServerSecretModel.key_name == name,
                            )
                        )
                    ).scalar_one_or_none()
                    if row is None:
                        session.add(
                            ServerSecretModel(
                                id=uuid.uuid4().hex,
                                server_id=segment,
                                key_name=name,
                                created_at=now,
                                **values,
                            )
                        )
                    else:
                        for field, field_value in values.items():
                            setattr(row, field, field_value)
                    await session.commit()

            _run_async(_store)
            return

        with self._ledger.sync_session() as session:
            row = session.execute(
                select(ServerSecretModel).where(
                    ServerSecretModel.server_id == segment,
                    ServerSecretModel.key_name == name,
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    ServerSecretModel(
                        id=uuid.uuid4().hex,
                        server_id=segment,
                        key_name=name,
                        created_at=now,
                        **values,
                    )
                )
            else:
                for field, field_value in values.items():
                    setattr(row, field, field_value)
            session.commit()

    def delete_secret(self, server_id: str, key_name: str) -> bool:
        segment = validate_server_segment(server_id)
        name = normalize_key_name(key_name)
        if self._is_async:
            factory = self._ledger.async_factory

            async def _delete() -> bool:
                async with factory() as session:
                    result = await session.execute(
                        delete(ServerSecretModel).where(
                            ServerSecretModel.server_id == segment,
                            ServerSecretModel.key_name == name,
                        )
                    )
                    await session.commit()
                    return bool(result.rowcount)

            return _run_async(_delete)

        with self._ledger.sync_session() as session:
            result = session.execute(
                delete(ServerSecretModel).where(
                    ServerSecretModel.server_id == segment,
                    ServerSecretModel.key_name == name,
                )
            )
            session.commit()
        return bool(result.rowcount)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_server_secrets(self, server_id: str) -> dict[str, str]:
        segment = validate_server_segment(server_id)
        rows: list[tuple[str, bytes, int, bytes, bytes]]
        if self._is_async:
            factory = self._ledger.async_factory

            async def _load() -> list[tuple[str, bytes, int, bytes, bytes]]:
                async with factory() as session:
                    found = (
                        (
                            await session.execute(
                                select(ServerSecretModel)
                                .where(ServerSecretModel.server_id == segment)
                                .order_by(ServerSecretModel.key_name)
                            )
                        )
                        .scalars()
                        .all()
                    )
                return [
                    (
                        str(row.key_name),
                        bytes(row.wrapped_dek),
                        int(row.kek_version or 1),
                        bytes(row.nonce),
                        bytes(row.ciphertext),
                    )
                    for row in found
                ]

            rows = _run_async(_load)
        else:
            with self._ledger.sync_session() as session:
                found = (
                    session.execute(
                        select(ServerSecretModel)
                        .where(ServerSecretModel.server_id == segment)
                        .order_by(ServerSecretModel.key_name)
                    )
                    .scalars()
                    .all()
                )
            rows = [
                (
                    str(row.key_name),
                    bytes(row.wrapped_dek),
                    int(row.kek_version or 1),
                    bytes(row.nonce),
                    bytes(row.ciphertext),
                )
                for row in found
            ]

        if not rows:
            return {}

        kek = load_master_kek()
        secrets: dict[str, str] = {}
        for key_name, wrapped_dek, kek_version, nonce, ciphertext in rows:
            if kek_version != kek.kek_version:
                raise MasterKekVersionMismatchError(
                    stored_kek_version=kek_version,
                    active_kek_version=kek.kek_version,
                )
            if (
                len(wrapped_dek) != _WRAPPED_DEK_BYTES
                or len(nonce) != _NONCE_BYTES
                or len(ciphertext) < 16
            ):
                raise ValidationError(
                    "Unable to decrypt server secret",
                    field="secrets",
                    details={"key_name": key_name},
                )
            try:
                dek = AESGCM(kek.key_bytes).decrypt(
                    wrapped_dek[:_NONCE_BYTES],
                    wrapped_dek[_NONCE_BYTES:],
                    _wrap_aad(segment, key_name, kek_version),
                )
                plaintext = AESGCM(dek).decrypt(
                    nonce,
                    ciphertext,
                    _value_aad(segment, key_name, kek_version),
                )
            except (InvalidTag, ValueError) as exc:
                raise ValidationError(
                    "Unable to decrypt server secret",
                    field="secrets",
                    details={"key_name": key_name},
                ) from exc
            try:
                secrets[key_name] = plaintext.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(
                    "Unable to decrypt server secret",
                    field="secrets",
                    details={"key_name": key_name},
                ) from exc
        return secrets

    # ------------------------------------------------------------------
    # Extraction helper
    # ------------------------------------------------------------------

    def extract_secret_from_bytes(
        self,
        server_id: str,
        relpath: str,
        content: bytes,
        *,
        secret_value: str,
        key_name: str | None = None,
        key_path: str = "",
    ) -> SecretExtractionResult:
        value = _validate_secret_value(secret_value)
        resolved_key = (
            normalize_key_name(key_name)
            if key_name is not None
            else derive_secret_key_name(relpath, key_path)
        )
        self.store_secret(server_id, resolved_key, value)
        placeholder = placeholder_for(resolved_key)
        literal = value.encode("utf-8")
        updated = content.replace(literal, placeholder.encode("utf-8"))
        replaced_count = content.count(literal)
        assert_no_secrets(relpath, updated)
        return SecretExtractionResult(
            key_name=resolved_key,
            placeholder=placeholder,
            relpath=relpath,
            content=updated,
            replaced_count=replaced_count,
        )


def extract_secret_from_bytes(
    server_id: str,
    relpath: str,
    content: bytes,
    *,
    secret_value: str,
    key_name: str | None = None,
    key_path: str = "",
    vault: ServerSecretVault | None = None,
) -> SecretExtractionResult:
    """Module-level extraction helper backed by a default vault."""
    service = vault or ServerSecretVault()
    try:
        return service.extract_secret_from_bytes(
            server_id,
            relpath,
            content,
            secret_value=secret_value,
            key_name=key_name,
            key_path=key_path,
        )
    finally:
        if vault is None:
            service.close()


__all__ = [
    "SECRET_PLACEHOLDER_PREFIX",
    "SECRET_PLACEHOLDER_SUFFIX",
    "SecretExtractionResult",
    "ServerSecretVault",
    "derive_secret_key_name",
    "extract_secret_from_bytes",
    "normalize_key_name",
    "placeholder_for",
]
