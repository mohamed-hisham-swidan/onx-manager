from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.storage.encryption import (
    BackupEncryption,
    build_backup_encryption,
    load_or_create_backup_key,
)
from app.modules.storage.local import LocalStorage
from app.modules.storage.s3 import S3Storage


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

    def test_encrypt_decrypt_stream_round_trip(self) -> None:
        enc = BackupEncryption()
        chunks = [b"chunk1: hello ", b"chunk2: world ", b"chunk3: 1234567890"]
        encrypted = list(enc.encrypt_stream(chunks))
        # First element must be the 12-byte nonce header
        assert len(encrypted) == len(chunks) + 1
        assert len(encrypted[0]) == 12

        decrypted = list(enc.decrypt_stream(encrypted))
        assert decrypted == chunks

    def test_encrypt_stream_nonce_uniqueness(self) -> None:
        enc = BackupEncryption()
        chunks = [b"identical data chunk 1", b"identical data chunk 2"]
        enc_run1 = list(enc.encrypt_stream(chunks))
        enc_run2 = list(enc.encrypt_stream(chunks))

        # The random nonces must differ
        assert enc_run1[0] != enc_run2[0]
        # The encrypted data chunks must also differ due to unique nonces
        assert enc_run1[1] != enc_run2[1]
        assert enc_run1[2] != enc_run2[2]

        # But both decrypt back to the original chunks
        assert list(enc.decrypt_stream(enc_run1)) == chunks
        assert list(enc.decrypt_stream(enc_run2)) == chunks

    def test_decrypt_stream_empty(self) -> None:
        enc = BackupEncryption()
        assert list(enc.decrypt_stream([])) == []
        # Header only (empty payload)
        encrypted = list(enc.encrypt_stream([]))
        assert len(encrypted) == 1
        assert list(enc.decrypt_stream(encrypted)) == []


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


class TestS3Storage:
    @pytest.fixture
    def mock_s3_client(self):
        client = AsyncMock()
        client.put_object = AsyncMock()
        body_mock = AsyncMock()
        body_mock.read = AsyncMock(return_value=b"retrieved content")
        client.get_object = AsyncMock(return_value={"Body": body_mock})
        client.delete_object = AsyncMock()
        client.head_object = AsyncMock(
            return_value={
                "ContentLength": 100,
                "ETag": '"etag123"',
                "LastModified": "2026-09-02T00:00:00Z",
            }
        )
        return client

    @pytest.fixture
    def mock_session(self, mock_s3_client):
        session = MagicMock()
        # session.client(...) returns an async context manager yielding mock_s3_client
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_s3_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        session.client = MagicMock(return_value=cm)
        return session

    @pytest.mark.asyncio
    async def test_s3_write_uses_context_manager_client(
        self, mock_session, mock_s3_client
    ) -> None:
        storage = S3Storage(
            bucket="test-bucket",
            endpoint_url="https://s3.example.com",
            prefix="my-prefix",
            session=mock_session,
        )

        res = await storage.write("backup.tar.gz", b"binary data")

        # Verify session.client was called as async context manager
        mock_session.client.assert_called_once_with("s3", endpoint_url="https://s3.example.com")
        mock_session.client.return_value.__aenter__.assert_awaited_once()
        mock_session.client.return_value.__aexit__.assert_awaited_once()

        # Verify put_object was called on the yielded client (not on the context manager)
        mock_s3_client.put_object.assert_awaited_once()
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "my-prefix/backup.tar.gz"
        assert call_kwargs["Body"] == b"binary data"
        assert res.size_bytes == len(b"binary data")

    @pytest.mark.asyncio
    async def test_s3_read_uses_context_manager_client(
        self, mock_session, mock_s3_client
    ) -> None:
        storage = S3Storage(
            bucket="test-bucket",
            endpoint_url="https://s3.example.com",
            prefix="my-prefix",
            session=mock_session,
        )

        data = await storage.read("backup.tar.gz")
        assert data == b"retrieved content"

        mock_s3_client.get_object.assert_awaited_once_with(
            Bucket="test-bucket",
            Key="my-prefix/backup.tar.gz",
        )

    @pytest.mark.asyncio
    async def test_s3_delete_uses_context_manager_client(
        self, mock_session, mock_s3_client
    ) -> None:
        storage = S3Storage(
            bucket="test-bucket",
            endpoint_url="https://s3.example.com",
            prefix="my-prefix",
            session=mock_session,
        )

        success = await storage.delete("backup.tar.gz")
        assert success is True

        mock_s3_client.delete_object.assert_awaited_once_with(
            Bucket="test-bucket",
            Key="my-prefix/backup.tar.gz",
        )

    def test_s3_missing_aioboto3_raises_import_error(self) -> None:
        storage = S3Storage(bucket="test-bucket")
        # When aioboto3 is not installed and no session was injected
        with pytest.raises(ImportError, match="aioboto3 is required for S3 storage"):
            _ = storage._session
