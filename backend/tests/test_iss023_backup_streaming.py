from __future__ import annotations

import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.encryption import BackupEncryption
from app.services.backup_orchestrator import BackupSaga


@pytest.mark.asyncio
async def test_write_tar_runs_off_event_loop_concurrently() -> None:
    """ISS-023: Verify _write_tar doesn't block the event loop."""
    orchestrator = BackupSaga(MagicMock())
    backup_id = BackupJobId("b1234567-89ab-cdef-0123-456789abcdef")
    server_id = ServerId("srv-test-1")

    concurrent_task_ran = False

    async def background_coroutine():
        nonlocal concurrent_task_ran
        await asyncio.sleep(0.01)
        concurrent_task_ran = True

    def slow_tar(tar_path, *_args, **_kwargs):
        # Simulate CPU/IO work in background thread
        time.sleep(0.05)
        with open(tar_path, "wb") as f:
            f.write(b"dummy-tar-content")

    with (
        patch.object(
            orchestrator, "_resolve_server_dir", AsyncMock(return_value=("/tmp/srv", "world"))
        ),
        patch.object(orchestrator, "_write_tar", side_effect=slow_tar),
    ):
        compress_fn = orchestrator._compress(backup_id, server_id)
        await asyncio.gather(compress_fn(), background_coroutine())

    assert concurrent_task_ran is True, "Background coroutine must run concurrently"
    orchestrator._cleanup_temp_dir()


@pytest.mark.asyncio
async def test_encrypt_and_upload_use_chunked_reads() -> None:
    """ISS-023: Verify _encrypt and _upload exercise chunked file reads."""
    orchestrator = BackupSaga(MagicMock())
    backup_id = BackupJobId("b1234567-89ab-cdef-0123-456789abcdef")
    encryption = BackupEncryption()

    temp_dir = tempfile.mkdtemp()
    tar_path = os.path.join(temp_dir, "test.tar.gz")
    # Write 192KB (3 x 64KB chunks)
    data = b"X" * (192 * 1024)
    with open(tar_path, "wb") as f:
        f.write(data)

    orchestrator._temp_dir = temp_dir
    orchestrator._tar_path = tar_path

    # Track chunked read calls
    read_calls: list[int] = []
    orig_open = open

    def instrumented_open(file, mode="r", *args, **kwargs):
        f = orig_open(file, mode, *args, **kwargs)
        if "rb" in mode:
            orig_read = f.read

            def chunked_read(size=-1):
                read_calls.append(size)
                return orig_read(size)

            f.read = chunked_read
        return f

    with patch("builtins.open", side_effect=instrumented_open):
        encrypt_fn = orchestrator._encrypt(backup_id, encryption)
        await encrypt_fn()

    # Verify that f.read was called with 64KB chunks (65536)
    chunk_reads = [s for s in read_calls if s == 64 * 1024]
    assert len(chunk_reads) >= 3, f"Expected chunked reads of 64KB, got calls: {read_calls}"

    # Now verify _upload also uses chunked reads
    upload_reads: list[int] = []

    def instrumented_upload_open(file, mode="r", *args, **kwargs):
        f = orig_open(file, mode, *args, **kwargs)
        if "rb" in mode:
            orig_read = f.read

            def chunked_read(size=-1):
                upload_reads.append(size)
                return orig_read(size)

            f.read = chunked_read
        return f

    storage = MagicMock()
    storage.write = AsyncMock()

    with patch("builtins.open", side_effect=instrumented_upload_open):
        upload_fn = orchestrator._upload(backup_id, storage, encryption)
        await upload_fn()

    upload_chunk_reads = [s for s in upload_reads if s == 64 * 1024]
    assert len(upload_chunk_reads) >= 3, (
        f"Expected chunked reads during upload, got: {upload_reads}"
    )
    assert storage.write.called

    orchestrator._cleanup_temp_dir()
