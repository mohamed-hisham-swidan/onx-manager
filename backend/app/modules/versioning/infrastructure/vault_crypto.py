"""Master KEK loading for the Advanced Class-C and secret vaults (P3-3).

The Class-C snapshot vault and the ``server_secrets`` table are encrypted with
AES-256-GCM. A single operator-supplied 256-bit master key (KEK) wraps the
per-snapshot and per-secret data encryption keys.

Key sources and precedence
--------------------------
1. ``ONX_MASTER_KEK_FILE`` (preferred) — a ``0600`` regular file containing
   either 32 raw bytes, 64 hex characters, base64 of exactly 32 bytes, or a
   versioned ``<kek_version>:<material>`` string.
2. ``ONX_MASTER_KEK`` — the same text encodings supplied through the
   environment.

When both are set the file wins and a warning is logged. The warning never
contains key material. Simple-mode operation does not load the KEK at all, so
it works unchanged when both sources are unset.

Permission policy (L4)
----------------------
On POSIX the KEK file must be a regular, non-symlink file with no group/other
permission bits. The check runs *before* any ``chmod`` attempt so an insecure
file fails closed instead of being silently repaired. ``allow_insecure_keys``
never weakens this check.

Operator runbook (M1 / M5)
--------------------------
Generate the key once (for example ``openssl rand -hex 32``), store it on a
``0600`` file, keep an encrypted offline backup, and verify that the file is
readable before enabling Advanced mode. Losing the KEK permanently destroys
recoverability of every ``FORMAT_VERSION = 2`` Class-C snapshot and every
extracted ``${ONX_SECRET_*}`` value.

Before upgrading a pre-P3 installation to ``b1e2100000027``:

1. List open refresh journals (``terminal = 0``) and settle/reconcile each one.
2. Remove pre-P3 plain snapshot directories whose ``manifest.json`` has
   ``format_version = 1``.
3. Run the migration.

Deleting a v1 snapshot referenced by a *historical terminal* journal forfeits
pre-P3 triad rollback to that snapshot, because v1 plain snapshots are no
longer readable after this release.

This module never logs keys, decoded bytes, wrapped DEKs, or plaintext.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import logging
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from app.core.config import AppSettings
from app.core.exceptions import (
    MasterKekInvalidError,
    MasterKekMissingError,
    SecurityPermissionError,
)
from app.core.security_files import ensure_private_key_permissions

logger = logging.getLogger(__name__)

KEK_BYTES = 32
_KEK_VERSION_RE = re.compile(r"\A[1-9][0-9]*\Z")
_HEX_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_BASE64_TEXT_RE = re.compile(r"\A[A-Za-z0-9+/=_-]+\Z")


@dataclass(frozen=True)
class MasterKek:
    """An active master key and its operator-visible version."""

    kek_version: int
    key_bytes: bytes

    def __repr__(self) -> str:
        return f"MasterKek(kek_version={self.kek_version}, key_bytes=***REDACTED***)"

    def __str__(self) -> str:
        return self.__repr__()


def _redact(text: object) -> str:
    del text
    return "***REDACTED***"


def _decode_material(material: str) -> bytes | None:
    if _HEX_RE.match(material):
        try:
            decoded = bytes.fromhex(material)
        except ValueError:
            return None
        return decoded if len(decoded) == KEK_BYTES else None
    if not _BASE64_TEXT_RE.match(material):
        return None
    candidates: list[bytes] = []
    padded = material + "=" * (-len(material) % 4)
    with contextlib.suppress(binascii.Error, ValueError):
        candidates.append(base64.b64decode(padded, validate=True))
    with contextlib.suppress(binascii.Error, ValueError):
        candidates.append(base64.b64decode(padded, altchars=b"-_", validate=True))
    for candidate in candidates:
        if len(candidate) == KEK_BYTES:
            return candidate
    return None


def _parse_text(raw: str, *, source: str) -> MasterKek:
    text = raw.strip()
    if not text:
        raise MasterKekInvalidError(
            "Master KEK is empty",
            field="master_kek",
        )

    kek_version = 1
    material = text
    if ":" in text:
        version_text, _, remainder = text.partition(":")
        if not _KEK_VERSION_RE.match(version_text):
            raise MasterKekInvalidError(
                "Master KEK version is invalid",
                field="master_kek",
                details={"source": source},
            )
        kek_version = int(version_text)
        material = remainder.strip()

    decoded = _decode_material(material)
    if decoded is None:
        raise MasterKekInvalidError(
            "Master KEK must be 64 hex characters or base64 of exactly 32 bytes",
            field="master_kek",
            details={"source": source},
        )
    return MasterKek(kek_version=kek_version, key_bytes=decoded)


def _read_kek_file(path: Path) -> bytes:
    if os.name != "posix":
        try:
            return path.read_bytes()
        except OSError as exc:
            raise MasterKekInvalidError(
                "Master KEK file could not be read",
                field="master_kek_file",
            ) from exc

    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise MasterKekInvalidError(
            "Master KEK file does not exist",
            field="master_kek_file",
        ) from exc
    except OSError as exc:
        raise MasterKekInvalidError(
            "Master KEK file could not be inspected",
            field="master_kek_file",
        ) from exc

    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise SecurityPermissionError(
            f"Master KEK file {path} must be a regular non-symlink file"
        )
    # Fail closed BEFORE ensure_private_key_permissions(): that helper attempts
    # os.chmod(0o600), which would silently repair a broadly-readable file.
    if (st.st_mode & 0o077) != 0:
        raise SecurityPermissionError(
            f"Insecure file permissions on KEK file {path} "
            f"(mode {oct(st.st_mode & 0o777)}, expected 0600)"
        )
    ensure_private_key_permissions(path, allow_insecure=False)

    try:
        return path.read_bytes()
    except OSError as exc:
        raise MasterKekInvalidError(
            "Master KEK file could not be read",
            field="master_kek_file",
        ) from exc


def _parse_file_bytes(raw: bytes) -> MasterKek:
    if len(raw) == KEK_BYTES:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            return MasterKek(kek_version=1, key_bytes=raw)
        if not _BASE64_TEXT_RE.match(text.strip()):
            return MasterKek(kek_version=1, key_bytes=raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MasterKekInvalidError(
            "Master KEK file has an unsupported encoding",
            field="master_kek_file",
        ) from exc
    return _parse_text(text, source="file")


def load_master_kek(settings: AppSettings | None = None) -> MasterKek:
    """Load and validate the active master KEK, lazily on first vault use."""
    settings_obj = settings if settings is not None else AppSettings()
    kek_file = (
        os.environ.get("ONX_MASTER_KEK_FILE") or settings_obj.master_kek_file
    ).strip()
    kek_env = (os.environ.get("ONX_MASTER_KEK") or settings_obj.master_kek).strip()

    if kek_file and kek_env:
        logger.warning(
            "Both ONX_MASTER_KEK_FILE and ONX_MASTER_KEK are set; "
            "using ONX_MASTER_KEK_FILE (%s) and ignoring ONX_MASTER_KEK",
            kek_file,
        )

    if kek_file:
        return _parse_file_bytes(_read_kek_file(Path(kek_file)))
    if kek_env:
        return _parse_text(kek_env, source="env")
    raise MasterKekMissingError(
        "Master KEK is not configured; set ONX_MASTER_KEK_FILE or ONX_MASTER_KEK"
    )


__all__ = ["KEK_BYTES", "MasterKek", "load_master_kek"]
