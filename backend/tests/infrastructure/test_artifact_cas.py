"""Tests for ArtifactCas (host-level SHA-256 CAS)."""

from __future__ import annotations

import concurrent.futures
import errno
import hashlib
import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest

import app.modules.versioning.infrastructure.artifact_cas as cas_module
from app.core.exceptions import (
    CasBlobNotFoundError,
    CasContainmentError,
    CasCorruptionError,
    CasInvalidDigestError,
    CasInvalidSourceError,
    CasWriteError,
    InsufficientStorageError,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas

HELLO_BYTES = b"hello world\n"
HELLO_SHA256 = hashlib.sha256(HELLO_BYTES).hexdigest()
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


# --- 1. Digest Validation ---


@pytest.mark.parametrize(
    "bad_digest",
    [
        "..",
        "/",
        "a/b",
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "",
        12345,
        None,
    ],
)
def test_digest_validation_methods(tmp_path: Path, bad_digest: Any) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    with pytest.raises(CasInvalidDigestError):
        cas.has(bad_digest)
    with pytest.raises(CasInvalidDigestError):
        cas.open_blob(bad_digest)
    with pytest.raises(CasInvalidDigestError):
        cas.blob_path(bad_digest)


# --- 2. Put Bytes and File ---


def test_put_bytes_and_file_known_sha(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = cas.put_bytes(HELLO_BYTES)
    assert digest == HELLO_SHA256
    assert cas.has(digest)

    with cas.open_blob(digest) as f:
        assert f.read() == HELLO_BYTES

    src = tmp_path / "src_hello.txt"
    src.write_bytes(HELLO_BYTES)
    digest_f = cas.put_file(src)
    assert digest_f == HELLO_SHA256


def test_put_zero_byte_file(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    empty_src = tmp_path / "empty.txt"
    empty_src.write_bytes(b"")

    digest = cas.put_file(empty_src)
    assert digest == EMPTY_SHA256
    assert cas.has(digest)
    with cas.open_blob(digest) as f:
        assert f.read() == b""


def test_put_5mib_file(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    data = b"X" * (5 * 1024 * 1024)
    expected_digest = hashlib.sha256(data).hexdigest()

    src = tmp_path / "large.bin"
    src.write_bytes(data)

    digest = cas.put_file(src)
    assert digest == expected_digest

    target_path = cas.blob_path(digest)
    assert target_path == cas.root / "sha256" / digest[:2] / digest
    assert target_path.exists()
    assert target_path.stat().st_size == len(data)


# --- 3. Deduplication and Idempotency ---


def test_dedupe_put_twice(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest1 = cas.put_bytes(HELLO_BYTES)
    blob = cas.blob_path(digest1)
    st1 = blob.stat()

    time.sleep(0.01)
    digest2 = cas.put_bytes(HELLO_BYTES)
    st2 = blob.stat()

    assert digest1 == digest2
    assert (st1.st_ino, st1.st_mtime_ns) == (st2.st_ino, st2.st_mtime_ns)

    # put_file dedupe leaves no .part
    src = tmp_path / "src.txt"
    src.write_bytes(HELLO_BYTES)
    digest3 = cas.put_file(src)
    assert digest3 == digest1
    tmp_dir = cas.root / ".tmp"
    assert len(list(tmp_dir.glob("*.part"))) == 0


# --- 4. Atomicity ---


def test_atomicity_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    def fail_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EIO, "Simulated replace disk error")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(CasWriteError):
        cas.put_bytes(HELLO_BYTES)

    # Temp file removed, no final blob
    assert not (cas.root / "sha256" / HELLO_SHA256[:2] / HELLO_SHA256).exists()
    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0


def test_atomicity_fsync_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    def fail_fsync(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EIO, "Simulated fsync error")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(CasWriteError):
        cas.put_bytes(HELLO_BYTES)

    assert not (cas.root / "sha256" / HELLO_SHA256[:2] / HELLO_SHA256).exists()
    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0


# --- 5. Disk Full (ENOSPC) ---


def test_enospc_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    def fail_write(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", fail_write)
    with pytest.raises(InsufficientStorageError) as exc_info:
        cas.put_bytes(HELLO_BYTES)
    assert exc_info.value.code == "INSUFFICIENT_STORAGE"

    assert not (cas.root / "sha256" / HELLO_SHA256[:2] / HELLO_SHA256).exists()
    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0


# --- 6. Concurrency ---


def test_concurrent_same_payload(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    payload = b"CONCURRENT_CONTENT_" * 1000

    def worker() -> str:
        return cas.put_bytes(payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(8)))

    expected = hashlib.sha256(payload).hexdigest()
    assert all(r == expected for r in results)
    with cas.open_blob(expected) as f:
        assert f.read() == payload
    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0


def test_concurrent_different_payloads(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    def worker(i: int) -> tuple[int, str]:
        data = f"payload_{i}".encode()
        return i, cas.put_bytes(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(worker, range(8)))

    for i, digest in results.items():
        data = f"payload_{i}".encode()
        assert digest == hashlib.sha256(data).hexdigest()
        with cas.open_blob(digest) as f:
            assert f.read() == data


# --- 7. Corruption and Quarantine ---


def test_corruption_detection_and_quarantine(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = cas.put_bytes(HELLO_BYTES)

    blob = cas.blob_path(digest)
    # Corrupt the blob on disk
    os.chmod(blob, 0o600)
    blob.write_bytes(b"corrupted content")
    os.chmod(blob, 0o400)

    # has is cheap existence
    assert cas.has(digest) is True

    # open_blob must detect corruption
    with pytest.raises(CasCorruptionError) as exc_info:
        cas.open_blob(digest)
    assert exc_info.value.code == "CAS_CORRUPTION"

    # put_bytes with the original content should quarantine and replace
    digest_new = cas.put_bytes(HELLO_BYTES)
    assert digest_new == digest

    # Verify blob is healthy again
    with cas.open_blob(digest) as f:
        assert f.read() == HELLO_BYTES

    # Verify quarantine directory has the corrupt blob
    q_dir = cas.root / "quarantine" / "sha256" / digest[:2]
    assert q_dir.exists()
    q_files = list(q_dir.glob(f"{digest}.*"))
    assert len(q_files) == 1
    assert q_files[0].read_bytes() == b"corrupted content"


# --- 8. Containment and Symlinks ---


def test_symlinked_root_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real_cas"
    real_root.mkdir()
    sym_root = tmp_path / "sym_cas"
    sym_root.symlink_to(real_root)

    cas = ArtifactCas(sym_root)
    with pytest.raises(CasContainmentError):
        cas.put_bytes(HELLO_BYTES)
    with pytest.raises(CasContainmentError):
        cas.open_blob(HELLO_SHA256)
    with pytest.raises(CasContainmentError):
        cas.blob_path(HELLO_SHA256)
    with pytest.raises(CasContainmentError):
        cas.has(HELLO_SHA256)


def test_symlink_final_blob_rejected(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = HELLO_SHA256
    cas.blob_path(digest)  # derive path

    # Create prefix dir and symlink to outside file
    prefix_dir = cas.root / "sha256" / digest[:2]
    prefix_dir.mkdir(parents=True, mode=0o700)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret file")

    target = prefix_dir / digest
    target.symlink_to(outside)

    with pytest.raises(CasContainmentError):
        cas.open_blob(digest)

    with pytest.raises(CasContainmentError):
        cas.put_bytes(HELLO_BYTES)

    assert outside.read_bytes() == b"secret file"


def test_missing_root_behavior(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "nonexistent_cas")
    assert cas.has(HELLO_SHA256) is False
    with pytest.raises(CasBlobNotFoundError):
        cas.open_blob(HELLO_SHA256)


def test_root_is_a_file_rejected(tmp_path: Path) -> None:
    file_root = tmp_path / "file_root"
    file_root.write_bytes(b"not a dir")

    cas = ArtifactCas(file_root)
    with pytest.raises(CasCorruptionError):
        cas.put_bytes(HELLO_BYTES)


def test_put_file_symlink_rejected(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    real_src = tmp_path / "real.txt"
    real_src.write_bytes(HELLO_BYTES)
    sym_src = tmp_path / "sym.txt"
    sym_src.symlink_to(real_src)

    with pytest.raises(CasInvalidSourceError):
        cas.put_file(sym_src)


# --- 9. Permissions ---


def test_permissions_enforced(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = cas.put_bytes(HELLO_BYTES)

    root_stat = cas.root.stat()
    assert stat.S_IMODE(root_stat.st_mode) == 0o700

    sha_stat = (cas.root / "sha256").stat()
    assert stat.S_IMODE(sha_stat.st_mode) == 0o700

    prefix_stat = (cas.root / "sha256" / digest[:2]).stat()
    assert stat.S_IMODE(prefix_stat.st_mode) == 0o700

    tmp_stat = (cas.root / ".tmp").stat()
    assert stat.S_IMODE(tmp_stat.st_mode) == 0o700

    blob_stat = cas.blob_path(digest).stat()
    assert stat.S_IMODE(blob_stat.st_mode) == 0o400


# --- 10. Stale Temp Cleanup ---


def test_stale_temp_cleanup(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    cas.put_bytes(HELLO_BYTES)

    tmp_dir = cas.root / ".tmp"
    old_part = tmp_dir / "old.part"
    old_part.write_bytes(b"old")
    # Set mtime to 2 days ago
    old_time = time.time() - 172800
    os.utime(old_part, (old_time, old_time))

    new_part = tmp_dir / "new.part"
    new_part.write_bytes(b"new")

    sym_part = tmp_dir / "sym.part"
    outside = tmp_path / "outside_stale.txt"
    outside.write_bytes(b"keep me")
    sym_part.symlink_to(outside)
    # Set symlink mtime to 2 days ago
    os.utime(sym_part, (old_time, old_time), follow_symlinks=False)

    cleaned = cas.cleanup_stale_temp(max_age_seconds=86400.0)
    assert cleaned == 2
    assert not old_part.exists()
    assert new_part.exists()
    assert outside.exists()
    assert not sym_part.exists(follow_symlinks=False)


# --- 11. Streaming ---


def test_streaming_chunk_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    monkeypatch.setattr(cas_module, "_CHUNK_SIZE", 7)

    data = b"0123456789" * 10
    src = tmp_path / "stream_src.txt"
    src.write_bytes(data)

    digest = cas.put_file(src)
    assert digest == hashlib.sha256(data).hexdigest()

    with cas.open_blob(digest) as f:
        assert f.read() == data


# --- 12. API Purity ---


def test_constructor_no_disk_io(tmp_path: Path) -> None:
    cas_path = tmp_path / "no_io_cas"
    cas = ArtifactCas(cas_path)
    assert not cas_path.exists()
    assert cas.root.is_absolute()


def test_error_secrecy_cas() -> None:
    bad_digest = "g" * 64
    cas = ArtifactCas(Path("/tmp/nonexistent"))
    with pytest.raises(CasInvalidDigestError) as exc_info:
        cas.has(bad_digest)
    assert exc_info.value.digest == "g" * 64
    assert exc_info.value.details["digest"] == "g" * 64


def test_invalid_digest_10k_chars_bounded(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    long_digest = "a" * 10000
    with pytest.raises(CasInvalidDigestError) as exc_info:
        cas.has(long_digest)
    assert len(exc_info.value.digest) <= 128
    assert len(exc_info.value.details["digest"]) <= 128
    assert len(str(exc_info.value)) < 1000


def test_put_file_short_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    real_write = os.write

    def one_byte_write(fd: int, data: bytes) -> int:
        if not data:
            return 0
        return real_write(fd, data[:1])

    monkeypatch.setattr(os, "write", one_byte_write)
    src = tmp_path / "short_src.txt"
    payload = b"short_writes_regression_content_12345"
    src.write_bytes(payload)

    digest = cas.put_file(src)
    assert digest == hashlib.sha256(payload).hexdigest()
    with cas.open_blob(digest) as f:
        assert f.read() == payload


def test_write_zero_bytes_cleans_up_put_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    def zero_write(_fd: int, _data: bytes) -> int:
        return 0

    monkeypatch.setattr(os, "write", zero_write)
    with pytest.raises(CasWriteError):
        cas.put_bytes(HELLO_BYTES)

    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0
    assert not (cas.root / "sha256" / HELLO_SHA256[:2] / HELLO_SHA256).exists()


def test_write_zero_bytes_cleans_up_put_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    src = tmp_path / "zero_src.txt"
    src.write_bytes(HELLO_BYTES)

    def zero_write(_fd: int, _data: bytes) -> int:
        return 0

    monkeypatch.setattr(os, "write", zero_write)
    with pytest.raises(CasWriteError):
        cas.put_file(src)

    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0
    assert not (cas.root / "sha256" / HELLO_SHA256[:2] / HELLO_SHA256).exists()


def test_put_file_source_mutated_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    src = tmp_path / "mutated_src.txt"
    src.write_bytes(b"initial_content")

    first_pass = True
    real_read = os.read

    def mutating_read(fd: int, n: int) -> bytes:
        chunk = real_read(fd, n)
        if not first_pass and chunk:
            return b"different_mutated_content"
        return chunk

    real_lseek = os.lseek

    def hook_lseek(fd: int, pos: int, how: int) -> int:
        nonlocal first_pass
        first_pass = False
        return real_lseek(fd, pos, how)

    monkeypatch.setattr(os, "read", mutating_read)
    monkeypatch.setattr(os, "lseek", hook_lseek)

    with pytest.raises(CasWriteError):
        cas.put_file(src)

    expected_digest = hashlib.sha256(b"initial_content").hexdigest()
    assert len(list((cas.root / ".tmp").glob("*.part"))) == 0
    assert not (cas.root / "sha256" / expected_digest[:2] / expected_digest).exists()


def test_blob_path_symlinked_prefix_and_dangling_final(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = HELLO_SHA256

    prefix_dir = cas.root / "sha256" / digest[:2]
    prefix_dir.parent.mkdir(parents=True, mode=0o700)
    real_prefix = tmp_path / "real_prefix"
    real_prefix.mkdir(mode=0o700)
    prefix_dir.symlink_to(real_prefix)

    with pytest.raises(CasContainmentError):
        cas.blob_path(digest)

    prefix_dir.unlink()
    prefix_dir.mkdir(mode=0o700)
    dangling = prefix_dir / digest
    dangling.symlink_to(tmp_path / "nonexistent_target")

    with pytest.raises(CasContainmentError):
        cas.blob_path(digest)


def test_root_under_symlinked_ancestor_rejected(tmp_path: Path) -> None:
    real_base = tmp_path / "real_base"
    real_base.mkdir()
    a_link = tmp_path / "a_link"
    a_link.symlink_to(real_base)

    cas_root = a_link / "sub" / "cas"
    cas = ArtifactCas(cas_root)
    with pytest.raises(CasContainmentError):
        cas.put_bytes(HELLO_BYTES)
    assert not (real_base / "sub").exists()


def test_cleanup_stale_temp_symlinked_tmp_raises(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    cas.put_bytes(HELLO_BYTES)

    tmp_dir = cas.root / ".tmp"
    for p in tmp_dir.glob("*"):
        p.unlink()
    tmp_dir.rmdir()

    outside = tmp_path / "outside_dir"
    outside.mkdir()
    tmp_dir.symlink_to(outside)

    with pytest.raises(CasContainmentError):
        cas.cleanup_stale_temp()


def test_quarantine_replace_failure_leaves_corrupt_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = cas.put_bytes(HELLO_BYTES)
    blob = cas.blob_path(digest)
    os.chmod(blob, 0o600)
    blob.write_bytes(b"corrupt")
    os.chmod(blob, 0o400)

    def fail_quarantine_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EIO, "Simulated quarantine replace failure")

    monkeypatch.setattr(os, "replace", fail_quarantine_replace)
    with pytest.raises(CasWriteError):
        cas.put_bytes(HELLO_BYTES)

    # Corrupt blob is left untouched (fail closed)
    assert blob.exists()
    assert blob.read_bytes() == b"corrupt"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX mkfifo required")
def test_fifo_final_path_fails_closed_without_hanging(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    digest = HELLO_SHA256
    prefix_dir = cas.root / "sha256" / digest[:2]
    prefix_dir.mkdir(parents=True, mode=0o700)
    fifo_path = prefix_dir / digest
    os.mkfifo(fifo_path)

    # has() is False for non-regular
    assert cas.has(digest) is False

    # open_blob raises CasCorruptionError without hanging
    with pytest.raises(CasCorruptionError):
        cas.open_blob(digest)

    # put_bytes raises CasCorruptionError without hanging
    with pytest.raises(CasCorruptionError):
        cas.put_bytes(HELLO_BYTES)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX mkfifo required")
def test_fifo_source_put_file_fails_closed_without_hanging(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    fifo_src = tmp_path / "src.fifo"
    os.mkfifo(fifo_src)

    with pytest.raises(CasInvalidSourceError):
        cas.put_file(fifo_src)


def test_put_bytes_bytearray_mutation_resilient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    buf = bytearray(b"original data for cas")
    orig_snapshot = bytes(buf)
    expected_digest = hashlib.sha256(orig_snapshot).hexdigest()

    real_write = os.write

    def mutating_write(fd: int, data: Any) -> int:
        buf[0] = ord(b"Z")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", mutating_write)
    ret_digest = cas.put_bytes(buf)
    assert ret_digest == expected_digest
    with cas.open_blob(ret_digest) as f:
        assert f.read() == orig_snapshot


def test_umask_077_permissions(tmp_path: Path) -> None:
    old_umask = os.umask(0o077)
    try:
        cas = ArtifactCas(tmp_path / "cas_umask")
        digest_bytes = cas.put_bytes(HELLO_BYTES)

        src_file = tmp_path / "src.txt"
        src_file.write_bytes(b"src file content")
        digest_file = cas.put_file(src_file)

        # Check directories are 0700
        assert stat.S_IMODE(cas.root.stat().st_mode) == 0o700
        assert stat.S_IMODE((cas.root / "sha256").stat().st_mode) == 0o700
        assert stat.S_IMODE((cas.root / "sha256" / digest_bytes[:2]).stat().st_mode) == 0o700
        assert stat.S_IMODE((cas.root / "sha256" / digest_file[:2]).stat().st_mode) == 0o700
        assert stat.S_IMODE((cas.root / ".tmp").stat().st_mode) == 0o700

        # Check committed blobs are 0400
        assert stat.S_IMODE(cas.blob_path(digest_bytes).stat().st_mode) == 0o400
        assert stat.S_IMODE(cas.blob_path(digest_file).stat().st_mode) == 0o400
    finally:
        os.umask(old_umask)
