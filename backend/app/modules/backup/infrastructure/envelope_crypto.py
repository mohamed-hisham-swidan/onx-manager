"""Chunked 64 KiB AES-256-GCM envelope encryption for P7-1 Tier-2 backups (OD-v8.7-7)."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import secrets
import struct
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import AppSettings
from app.core.exceptions import MasterKekInvalidError, MasterKekMissingError, ValidationError
from app.core.security_files import ensure_private_key_permissions
from app.modules.versioning.infrastructure.vault_crypto import MasterKek, load_master_kek

ENVELOPE_MAGIC = b"ONXENV2\x00"
ENVELOPE_FORMAT_VERSION = 1
DEFAULT_CHUNK_SIZE = 65536
_HEADER_PREFIX_FMT = ">8sBI"
_CHUNK_HEADER_FMT = ">IB"
_MAX_HEADER_BYTES = 65536


class BackupEncryptionError(Exception):
    """Raised when Tier-2 envelope encryption or decryption fails."""


def requires_archive_encryption(*, has_class_c: bool, storage_backend: str = "local") -> bool:
    """OD-v8.7-7: Mandatory encryption when Class C is present or target is S3."""
    return bool(has_class_c) or str(storage_backend or "").strip().lower() == "s3"


def load_or_create_master_kek(
    settings: AppSettings | None = None,
    *,
    kek_file_path: Path | None = None,
    allow_create: bool = False,
) -> MasterKek:
    """Load the active Master KEK via ``vault_crypto``, or auto-create a 0600 KEK if allowed."""
    try:
        return load_master_kek(settings)
    except (MasterKekMissingError, MasterKekInvalidError) as exc:
        if not allow_create or kek_file_path is None:
            raise BackupEncryptionError(str(exc)) from exc

    target = Path(kek_file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        raw = secrets.token_bytes(32)
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, f"1:{raw.hex()}\n".encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
    ensure_private_key_permissions(target)
    try:
        text = target.read_text(encoding="utf-8").strip()
        version_str, _, material = text.partition(":")
        key_bytes = bytes.fromhex(material if material else version_str)
        kek_version = int(version_str) if material else 1
        if len(key_bytes) != 32:
            raise BackupEncryptionError("Generated KEK file has invalid length")
        return MasterKek(kek_version=kek_version, key_bytes=key_bytes)
    except BackupEncryptionError:
        raise
    except Exception as exc:
        raise BackupEncryptionError(f"Failed to load KEK file '{target}': {exc}") from exc


def _wrap_aad() -> bytes:
    return ENVELOPE_MAGIC + bytes([ENVELOPE_FORMAT_VERSION])


def _chunk_nonce(prefix4: bytes, chunk_index: int) -> bytes:
    return prefix4 + struct.pack(">Q", chunk_index)


def _chunk_aad(chunk_index: int, is_final: bool) -> bytes:
    return ENVELOPE_MAGIC + struct.pack(
        ">BQB", ENVELOPE_FORMAT_VERSION, chunk_index, 1 if is_final else 0
    )


class EnvelopeBackupCipher:
    """KEK-wrapped DEK + 64 KiB chunked AES-256-GCM stream cipher."""

    def __init__(self, kek: MasterKek, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        if len(kek.key_bytes) != 32:
            raise ValidationError("Master KEK must be 32 bytes")
        if chunk_size <= 0 or chunk_size > 16 * 1024 * 1024:
            raise ValidationError("chunk_size must be between 1 and 16 MiB")
        self._kek = kek
        self._chunk_size = chunk_size

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def encrypt_stream(self, src: BinaryIO, dst: BinaryIO) -> int:
        """Encrypt ``src`` into ``dst`` and return total bytes written."""
        dek = secrets.token_bytes(32)
        wrap_nonce = secrets.token_bytes(12)
        stream_prefix = secrets.token_bytes(4)

        wrapped_dek = AESGCM(self._kek.key_bytes).encrypt(wrap_nonce, dek, _wrap_aad())
        header_obj = {
            "kek_version": self._kek.kek_version,
            "wrap_nonce": base64.b64encode(wrap_nonce).decode("ascii"),
            "wrapped_dek": base64.b64encode(wrapped_dek).decode("ascii"),
            "chunk_size": self._chunk_size,
            "stream_nonce_prefix": base64.b64encode(stream_prefix).decode("ascii"),
        }
        header_bytes = json.dumps(
            header_obj, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        prefix = struct.pack(
            _HEADER_PREFIX_FMT, ENVELOPE_MAGIC, ENVELOPE_FORMAT_VERSION, len(header_bytes)
        )

        dst.write(prefix)
        dst.write(header_bytes)
        written = len(prefix) + len(header_bytes)

        data_cipher = AESGCM(dek)
        chunk_index = 0
        current = src.read(self._chunk_size)
        if not current:
            ct = data_cipher.encrypt(_chunk_nonce(stream_prefix, 0), b"", _chunk_aad(0, True))
            frame = struct.pack(_CHUNK_HEADER_FMT, len(ct), 1) + ct
            dst.write(frame)
            return written + len(frame)

        while current:
            nxt = src.read(self._chunk_size)
            is_final = len(nxt) == 0
            ct = data_cipher.encrypt(
                _chunk_nonce(stream_prefix, chunk_index),
                current,
                _chunk_aad(chunk_index, is_final),
            )
            frame = struct.pack(_CHUNK_HEADER_FMT, len(ct), 1 if is_final else 0) + ct
            dst.write(frame)
            written += len(frame)
            chunk_index += 1
            current = nxt
        return written

    def decrypt_stream(self, src: BinaryIO, dst: BinaryIO) -> int:
        """Decrypt ``src`` into ``dst``, verifying final-chunk tag and rejecting truncation."""
        prefix_len = struct.calcsize(_HEADER_PREFIX_FMT)
        prefix_raw = src.read(prefix_len)
        if len(prefix_raw) != prefix_len:
            raise BackupEncryptionError("Truncated encrypted archive header prefix")
        magic, version, header_len = struct.unpack(_HEADER_PREFIX_FMT, prefix_raw)
        if magic != ENVELOPE_MAGIC or version != ENVELOPE_FORMAT_VERSION:
            raise BackupEncryptionError("Invalid encrypted archive magic or format version")
        if header_len <= 0 or header_len > _MAX_HEADER_BYTES:
            raise BackupEncryptionError("Invalid encrypted archive header length")

        header_raw = src.read(header_len)
        if len(header_raw) != header_len:
            raise BackupEncryptionError("Truncated encrypted archive header payload")
        try:
            header = json.loads(header_raw.decode("utf-8"))
            wrap_nonce = base64.b64decode(header["wrap_nonce"], validate=True)
            wrapped_dek = base64.b64decode(header["wrapped_dek"], validate=True)
            stream_prefix = base64.b64decode(header["stream_nonce_prefix"], validate=True)
            if len(wrap_nonce) != 12 or len(stream_prefix) != 4:
                raise ValueError("Invalid nonce size")
        except Exception as exc:
            raise BackupEncryptionError(f"Malformed encrypted archive header: {exc}") from exc

        try:
            dek = AESGCM(self._kek.key_bytes).decrypt(wrap_nonce, wrapped_dek, _wrap_aad())
        except InvalidTag as exc:
            raise BackupEncryptionError(
                "Failed to unwrap archive DEK (wrong KEK or tampered header)"
            ) from exc

        data_cipher = AESGCM(dek)
        chunk_hdr_len = struct.calcsize(_CHUNK_HEADER_FMT)
        chunk_index = 0
        saw_final = False
        total_plain = 0

        while True:
            chunk_hdr = src.read(chunk_hdr_len)
            if not chunk_hdr:
                break
            if len(chunk_hdr) != chunk_hdr_len:
                raise BackupEncryptionError("Truncated chunk header in encrypted archive")
            if saw_final:
                raise BackupEncryptionError("Unexpected trailing data after final encrypted chunk")
            ct_len, final_flag = struct.unpack(_CHUNK_HEADER_FMT, chunk_hdr)
            if ct_len < 16 or final_flag not in (0, 1):
                raise BackupEncryptionError("Invalid chunk length or final flag")
            ct = src.read(ct_len)
            if len(ct) != ct_len:
                raise BackupEncryptionError("Truncated ciphertext chunk in encrypted archive")
            is_final = final_flag == 1
            try:
                plain = data_cipher.decrypt(
                    _chunk_nonce(stream_prefix, chunk_index),
                    ct,
                    _chunk_aad(chunk_index, is_final),
                )
            except InvalidTag as exc:
                raise BackupEncryptionError(
                    f"Integrity verification failed at chunk {chunk_index}"
                ) from exc
            dst.write(plain)
            total_plain += len(plain)
            chunk_index += 1
            if is_final:
                saw_final = True

        if not saw_final:
            raise BackupEncryptionError(
                "Encrypted archive stream ended without authenticated final chunk"
            )
        return total_plain

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        import io

        src = io.BytesIO(plaintext)
        dst = io.BytesIO()
        self.encrypt_stream(src, dst)
        return dst.getvalue()

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        import io

        src = io.BytesIO(ciphertext)
        dst = io.BytesIO()
        self.decrypt_stream(src, dst)
        return dst.getvalue()

    def encrypt_file(self, src_path: Path, dst_path: Path) -> int:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst_path.with_name(f".{dst_path.name}.enc.tmp")
        try:
            with src_path.open("rb") as src, tmp_path.open("wb") as dst:
                written = self.encrypt_stream(src, dst)
                dst.flush()
                with contextlib.suppress(OSError):
                    os.fsync(dst.fileno())
            os.replace(tmp_path, dst_path)
            return written
        except Exception:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    def decrypt_file(self, src_path: Path, dst_path: Path) -> int:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst_path.with_name(f".{dst_path.name}.dec.tmp")
        try:
            with src_path.open("rb") as src, tmp_path.open("wb") as dst:
                written = self.decrypt_stream(src, dst)
                dst.flush()
                with contextlib.suppress(OSError):
                    os.fsync(dst.fileno())
            os.replace(tmp_path, dst_path)
            return written
        except Exception:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise
