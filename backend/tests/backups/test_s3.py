"""Consolidated tests for local/S3 storage backends, key/stream encryption, and CoW probe."""

from __future__ import annotations

import builtins
import hashlib
import importlib
import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import StorageCowUnavailableError
from app.modules.storage.encryption import (
    BackupEncryption,
    build_backup_encryption,
    load_or_create_backup_key,
)
from app.modules.storage.local import LocalStorage
from app.modules.storage.s3 import S3Storage
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe


class TestLocalStorage:
    async def test_write_read_exists_delete_list_info_copy(self, tmp_path: Path) -> None:
        storage = LocalStorage(str(tmp_path))
        data = b"hello world"
        assert not await storage.exists("test.txt")

        res = await storage.write("test.txt", data)
        assert res.success and res.size_bytes == len(data)
        assert await storage.exists("test.txt")
        assert await storage.read("test.txt") == data

        info = await storage.info("test.txt")
        assert info is not None and info.size_bytes == len(data) and not info.is_directory

        copy_res = await storage.copy("test.txt", "copy.txt")
        assert copy_res.success and await storage.read("copy.txt") == data
        assert len(await storage.list_files("")) == 2

        assert await storage.delete("test.txt") is True
        assert not await storage.exists("test.txt")

    async def test_path_traversal_and_missing_read_rejected(self, tmp_path: Path) -> None:
        storage = LocalStorage(str(tmp_path))
        with pytest.raises(ValueError, match="Path traversal"):
            await storage.write("../outside.txt", b"data")
        with pytest.raises(FileNotFoundError):
            await storage.read("nonexistent.txt")

    async def test_stream_write_and_read(self, tmp_path: Path) -> None:
        storage = LocalStorage(str(tmp_path))

        async def chunk_gen():
            yield b"hello "
            yield b"world "
            yield b"stream"

        res = await storage.stream_write("stream.txt", chunk_gen())
        assert res.size_bytes == 18
        assert res.checksum == hashlib.sha256(b"hello world stream").hexdigest()

        read_chunks = [chunk async for chunk in storage.stream_read("stream.txt", chunk_size=5)]
        assert b"".join(read_chunks) == b"hello world stream"
        assert len(read_chunks) == 4


class TestBackupEncryptionAndKeyLoader:
    def test_encrypt_decrypt_aad_wrong_key_and_checksum(self) -> None:
        enc1 = BackupEncryption()
        enc2 = BackupEncryption()
        data = b"secret minecraft data"

        from cryptography.exceptions import InvalidTag

        ct = enc1.encrypt(data, aad=b"backup-job-123")
        assert ct != data
        assert enc1.decrypt(ct, aad=b"backup-job-123") == data
        with pytest.raises(InvalidTag):
            enc2.decrypt(ct, aad=b"backup-job-123")

        key = BackupEncryption.generate_key()
        assert len(key) == 32
        from_bytes = BackupEncryption.from_key_bytes(key)
        from_hex = BackupEncryption.from_key_hex(key.hex())
        assert bytes.fromhex(from_bytes.key_as_hex()) == key
        assert from_hex.decrypt(from_bytes.encrypt(b"test")) == b"test"

        assert len(enc1.checksum(data)) == 64
        assert enc1.checksum(data) != enc1.checksum(b"different")

        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            BackupEncryption(key=b"too-short")

    def test_stream_encryption_roundtrip_and_nonce_uniqueness(self) -> None:
        enc = BackupEncryption()
        chunks = [b"chunk1: hello ", b"chunk2: world ", b"chunk3: 1234567890"]
        run1 = list(enc.encrypt_stream(chunks))
        run2 = list(enc.encrypt_stream(chunks))

        assert len(run1) == len(chunks) + 1 and len(run1[0]) == 12
        assert run1[0] != run2[0] and run1[1] != run2[1]
        assert list(enc.decrypt_stream(run1)) == chunks
        assert list(enc.decrypt_stream(run2)) == chunks

        assert list(enc.decrypt_stream([])) == []
        empty_enc = list(enc.encrypt_stream([]))
        assert len(empty_enc) == 1 and list(enc.decrypt_stream(empty_enc)) == []

    def test_key_loader_persists_reloads_validates_and_sets_0600(self, tmp_path: Path) -> None:
        key_path = tmp_path / "backup_encryption_key.bin"
        first = load_or_create_backup_key(str(key_path))
        assert len(first) == 32 and key_path.read_bytes() == first
        assert load_or_create_backup_key(str(key_path)) == first

        if sys.platform != "win32":
            assert (os.stat(key_path).st_mode & 0o777) == 0o600

        enc1 = build_backup_encryption(str(key_path))
        enc2 = build_backup_encryption(str(key_path))
        assert enc1.key == enc2.key == first

        short_path = tmp_path / "short.bin"
        short_path.write_bytes(b"too-short")
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            load_or_create_backup_key(str(short_path))


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
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_s3_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.client = MagicMock(return_value=cm)
        return session

    async def test_s3_write_read_delete_use_context_manager(
        self, mock_session, mock_s3_client
    ) -> None:
        storage = S3Storage(
            bucket="test-bucket",
            endpoint_url="https://s3.example.com",
            prefix="my-prefix",
            session=mock_session,
        )

        res = await storage.write("backup.tar.gz", b"binary data")
        mock_session.client.assert_called_once_with("s3", endpoint_url="https://s3.example.com")
        assert mock_s3_client.put_object.call_args.kwargs["Bucket"] == "test-bucket"
        assert mock_s3_client.put_object.call_args.kwargs["Key"] == "my-prefix/backup.tar.gz"
        assert res.size_bytes == len(b"binary data")

        assert await storage.read("backup.tar.gz") == b"retrieved content"
        mock_s3_client.get_object.assert_awaited_once_with(
            Bucket="test-bucket", Key="my-prefix/backup.tar.gz"
        )

        assert await storage.delete("backup.tar.gz") is True
        mock_s3_client.delete_object.assert_awaited_once_with(
            Bucket="test-bucket", Key="my-prefix/backup.tar.gz"
        )

    async def test_s3_exists_distinguishes_404_from_access_errors(
        self, mock_session, mock_s3_client
    ) -> None:
        err_404 = Exception("Not found")
        err_404.response = {"Error": {"Code": "404", "Message": "Not Found"}}  # type: ignore[attr-defined]
        mock_s3_client.head_object = AsyncMock(side_effect=err_404)
        storage = S3Storage(bucket="b", session=mock_session)
        assert await storage.exists("test.txt") is False

        err_denied = Exception("Access Denied")
        err_denied.response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}  # type: ignore[attr-defined]
        mock_s3_client.head_object = AsyncMock(side_effect=err_denied)
        with pytest.raises(Exception, match="Access Denied"):
            await storage.exists("test.txt")

    def test_s3_session_creation_and_missing_aioboto3(self) -> None:
        storage = S3Storage(bucket="test-bucket")
        with (
            patch.dict("sys.modules", {"aioboto3": None}),
            pytest.raises(ImportError, match="aioboto3 is required for S3 storage"),
        ):
            _ = storage._session

        mock_aioboto3 = MagicMock()
        mock_session_inst = MagicMock()
        mock_aioboto3.Session = MagicMock(return_value=mock_session_inst)
        with patch.dict("sys.modules", {"aioboto3": mock_aioboto3}):
            s3 = S3Storage(
                bucket="test-bucket",
                access_key_id="test-key",
                secret_access_key="test-secret",
                region="us-west-2",
            )
            assert s3._session == mock_session_inst
            mock_aioboto3.Session.assert_called_once_with(
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",
                region_name="us-west-2",
            )

    async def test_s3_delete_and_info_log_warning_on_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_session = MagicMock()
        mock_client = AsyncMock()
        mock_client.delete_object.side_effect = RuntimeError("network glitch")
        mock_client.head_object.side_effect = RuntimeError("network glitch")
        mock_session.client.return_value.__aenter__.return_value = mock_client

        storage = S3Storage(bucket="test-bucket", session=mock_session)
        with caplog.at_level(logging.WARNING):
            assert await storage.delete("file.txt") is False
            assert "Failed to delete S3 key file.txt" in caplog.text
            assert await storage.info("file.txt") is None
            assert "Failed to get info for S3 key file.txt" in caplog.text


class TestStorageCapabilityProbe:
    def test_probe_success_and_failure_412(self, tmp_path: Path) -> None:
        with patch.object(StorageCapabilityProbe, "probe_path", return_value=True):
            assert StorageCapabilityProbe.probe_path(tmp_path) is True
            StorageCapabilityProbe.assert_supports_reflink(tmp_path)

        with patch.object(StorageCapabilityProbe, "probe_path", return_value=False):
            assert StorageCapabilityProbe.probe_path(tmp_path) is False
            with pytest.raises(StorageCowUnavailableError) as exc_info:
                StorageCapabilityProbe.assert_supports_reflink(tmp_path)
            err = exc_info.value
            assert err.http_status == 412
            assert err.code == "STORAGE_COW_UNAVAILABLE"
            assert "Btrfs or ZFS" in err.message
            assert str(tmp_path) in err.message or err.details.get("path") == str(tmp_path)

    def test_real_filesystem_probe_cleans_up_temp_files(self, tmp_path: Path) -> None:
        res = StorageCapabilityProbe.probe_path(tmp_path)
        assert isinstance(res, bool)
        probe_dir = tmp_path / ".onx" / "probe"
        assert not (probe_dir / "probe_src.bin").exists()
        assert not (probe_dir / "probe_dst.bin").exists()

    def test_probe_imports_without_fcntl_for_windows(self, tmp_path: Path) -> None:
        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "fcntl":
                raise ImportError("No module named 'fcntl' (simulated Windows)")
            return real_import(name, *args, **kwargs)

        module_name = "app.modules.versioning.infrastructure.storage_probe"
        with patch.object(builtins, "__import__", side_effect=fake_import):
            saved = sys.modules.pop(module_name, None)
            try:
                module = importlib.import_module(module_name)
            finally:
                sys.modules.pop(module_name, None)
                if saved is not None:
                    sys.modules[module_name] = saved
        assert module.fcntl is None
        assert isinstance(module.StorageCapabilityProbe.probe_path(tmp_path), bool)
