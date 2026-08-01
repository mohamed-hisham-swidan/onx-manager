from __future__ import annotations

import os
import tempfile

import pytest

from app.modules.storage.base import StorageBackend
from app.modules.storage.encryption import (
    BackupEncryption,
    build_backup_encryption,
    load_or_create_backup_key,
)
from app.modules.storage.local import LocalStorage


class TestLocalStorage:
    @pytest.fixture
    def temp_dir(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.mark.asyncio
    async def test_write_and_read(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        data = b"hello world"
        result = await storage.write("test.txt", data)
        assert result.success
        assert result.size_bytes == len(data)

        read_data = await storage.read("test.txt")
        assert read_data == data

    @pytest.mark.asyncio
    async def test_exists(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        assert not await storage.exists("nonexistent.txt")
        await storage.write("exists.txt", b"data")
        assert await storage.exists("exists.txt")

    @pytest.mark.asyncio
    async def test_delete(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        await storage.write("del.txt", b"data")
        assert await storage.exists("del.txt")
        result = await storage.delete("del.txt")
        assert result
        assert not await storage.exists("del.txt")

    @pytest.mark.asyncio
    async def test_list_files(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        await storage.write("a.txt", b"aaa")
        await storage.write("b.txt", b"bbb")

        files = await storage.list_files("")
        assert len(files) == 2

    @pytest.mark.asyncio
    async def test_info(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        await storage.write("info.txt", b"test data")
        info = await storage.info("info.txt")
        assert info is not None
        assert info.size_bytes == 9
        assert not info.is_directory

    @pytest.mark.asyncio
    async def test_copy(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        await storage.write("src.txt", b"source data")
        result = await storage.copy("src.txt", "dst.txt")
        assert result.success
        assert await storage.exists("dst.txt")
        assert await storage.read("dst.txt") == b"source data"

    @pytest.mark.asyncio
    async def test_path_traversal_prevention(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        with pytest.raises(ValueError, match="Path traversal"):
            await storage.write("../outside.txt", b"data")

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, temp_dir: str) -> None:
        storage = LocalStorage(temp_dir)
        with pytest.raises(FileNotFoundError):
            await storage.read("nonexistent.txt")


class TestBackupEncryption:
    def test_encrypt_decrypt(self) -> None:
        enc = BackupEncryption()
        data = b"secret minecraft data"
        encrypted = enc.encrypt(data)
        decrypted = enc.decrypt(encrypted)
        assert decrypted == data
        assert encrypted != data

    def test_encrypt_with_aad(self) -> None:
        enc = BackupEncryption()
        data = b"data with context"
        aad = b"backup-job-123"
        encrypted = enc.encrypt(data, aad=aad)
        decrypted = enc.decrypt(encrypted, aad=aad)
        assert decrypted == data

    def test_decrypt_wrong_key_fails(self) -> None:
        enc1 = BackupEncryption()
        enc2 = BackupEncryption()
        data = b"secret"
        encrypted = enc1.encrypt(data)
        with pytest.raises(Exception):
            enc2.decrypt(encrypted)

    def test_generate_key(self) -> None:
        key = BackupEncryption.generate_key()
        assert len(key) == 32

    def test_from_key_bytes(self) -> None:
        key = BackupEncryption.generate_key()
        enc = BackupEncryption.from_key_bytes(key)
        data = b"test"
        encrypted = enc.encrypt(data)
        decrypted = enc.decrypt(encrypted)
        assert decrypted == data

    def test_from_key_hex(self) -> None:
        key = BackupEncryption.generate_key()
        enc1 = BackupEncryption.from_key_bytes(key)
        enc2 = BackupEncryption.from_key_hex(key.hex())
        data = b"test"
        assert enc2.decrypt(enc1.encrypt(data)) == data

    def test_checksum(self) -> None:
        enc = BackupEncryption()
        data = b"test data"
        cs = enc.checksum(data)
        assert len(cs) == 64
        assert cs == enc.checksum(data)
        assert cs != enc.checksum(b"different")

    def test_key_as_hex(self) -> None:
        enc = BackupEncryption()
        key_hex = enc.key_as_hex()
        assert len(key_hex) == 64
        assert bytes.fromhex(key_hex) == enc.key

    def test_invalid_key_length(self) -> None:
        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            BackupEncryption(key=b"too-short")


class TestBackupKeyLoader:
    def test_generates_persists_and_reloads_same_key(self, tmp_path) -> None:
        key_path = os.path.join(str(tmp_path), "backup_encryption_key.bin")
        first = load_or_create_backup_key(key_path)
        assert len(first) == 32

        assert os.path.exists(key_path)
        with open(key_path, "rb") as f:
            assert f.read() == first

        second = load_or_create_backup_key(key_path)
        assert second == first

    def test_uses_existing_key_without_overwriting(self, tmp_path) -> None:
        key_path = os.path.join(str(tmp_path), "existing.bin")
        with open(key_path, "wb") as f:
            f.write(b"x" * 32)
        loaded = load_or_create_backup_key(key_path)
        assert loaded == b"x" * 32

    def test_rejects_wrong_sized_key_file(self, tmp_path) -> None:
        key_path = os.path.join(str(tmp_path), "short.bin")
        with open(key_path, "wb") as f:
            f.write(b"too-short")
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            load_or_create_backup_key(key_path)

    def test_build_backup_encryption_uses_persisted_key(self, tmp_path) -> None:
        key_path = os.path.join(str(tmp_path), "key.bin")
        enc1 = build_backup_encryption(key_path)
        enc2 = build_backup_encryption(key_path)
        assert enc1.key == enc2.key
