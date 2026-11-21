from __future__ import annotations

import os
import stat
import struct
from pathlib import Path

import pytest

from app.modules.backup.infrastructure.envelope_crypto import (
    ENVELOPE_FORMAT_VERSION,
    ENVELOPE_MAGIC,
    BackupEncryptionError,
    EnvelopeBackupCipher,
    load_or_create_master_kek,
    requires_archive_encryption,
)
from app.modules.versioning.infrastructure.vault_crypto import MasterKek


def test_envelope_multichunk_roundtrip_and_tamper_resistance() -> None:
    kek = MasterKek(kek_version=1, key_bytes=b"\x11" * 32)
    wrong_kek = MasterKek(kek_version=1, key_bytes=b"\x22" * 32)
    cipher = EnvelopeBackupCipher(kek, chunk_size=65536)

    # 2.5 chunks (> 160 KiB)
    plaintext = os.urandom(65536 * 2 + 12345)
    encrypted = cipher.encrypt_bytes(plaintext)
    assert encrypted.startswith(ENVELOPE_MAGIC + bytes([ENVELOPE_FORMAT_VERSION]))
    assert cipher.decrypt_bytes(encrypted) == plaintext

    # Wrong KEK fails closed
    with pytest.raises(BackupEncryptionError, match="unwrap"):
        EnvelopeBackupCipher(wrong_kek).decrypt_bytes(encrypted)

    # Truncated final chunk fails closed
    with pytest.raises(BackupEncryptionError, match="(Truncated|final chunk)"):
        cipher.decrypt_bytes(encrypted[:-20])

    # Trailing garbage after final chunk fails closed
    with pytest.raises(BackupEncryptionError, match="trailing"):
        cipher.decrypt_bytes(encrypted + b"\x00\x00\x00\x20\x01" + b"\xaa" * 32)

    # Corrupt byte in ciphertext fails authentication
    mutated = bytearray(encrypted)
    mutated[-5] ^= 0xFF
    with pytest.raises(BackupEncryptionError, match="Integrity"):
        cipher.decrypt_bytes(bytes(mutated))


def test_envelope_empty_and_chunk_reorder_detection() -> None:
    kek = MasterKek(kek_version=1, key_bytes=b"\x33" * 32)
    cipher = EnvelopeBackupCipher(kek, chunk_size=64)
    assert cipher.decrypt_bytes(cipher.encrypt_bytes(b"")) == b""

    # Reorder chunk 0 and chunk 1
    enc = cipher.encrypt_bytes(b"A" * 64 + b"B" * 64)
    hdr_prefix_len = struct.calcsize(">8sBI")
    _, _, hdr_len = struct.unpack(">8sBI", enc[:hdr_prefix_len])
    pos = hdr_prefix_len + hdr_len
    c0_len, _ = struct.unpack(">IB", enc[pos : pos + 5])
    c0 = enc[pos : pos + 5 + c0_len]
    pos2 = pos + 5 + c0_len
    c1_len, _ = struct.unpack(">IB", enc[pos2 : pos2 + 5])
    c1 = enc[pos2 : pos2 + 5 + c1_len]
    swapped = enc[:pos] + c1 + c0
    with pytest.raises(BackupEncryptionError, match="(Integrity|trailing)"):
        cipher.decrypt_bytes(swapped)


def test_mandatory_encryption_policy_and_kek_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ONX_MASTER_KEK", raising=False)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)

    assert requires_archive_encryption(has_class_c=True, storage_backend="local") is True
    assert requires_archive_encryption(has_class_c=False, storage_backend="s3") is True
    assert requires_archive_encryption(has_class_c=False, storage_backend="local") is False

    kek_path = tmp_path / "keys" / "master.kek"
    kek = load_or_create_master_kek(kek_file_path=kek_path, allow_create=True)
    assert len(kek.key_bytes) == 32
    mode = stat.S_IMODE(kek_path.stat().st_mode)
    assert mode == 0o600
