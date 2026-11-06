from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from app.modules.server.infrastructure.fs import LocalFileSystem


def test_local_filesystem_write_and_read_text() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.txt")
        fs.write_text(path, "hello world")
        assert fs.read_text(path) == "hello world"
        assert fs.exists(path)
        assert fs.is_file(path)


def test_local_filesystem_write_and_read_binary() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.bin")
        data = b"\x00\x01\x02\xff"
        fs.write_binary(path, data)
        assert fs.read_binary(path) == data
        assert fs.size(path) == 4


def test_local_filesystem_ensure_dir() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        dir_path = str(Path(tmp) / "a" / "b" / "c")
        fs.ensure_dir(dir_path)
        assert fs.is_dir(dir_path)
        assert fs.exists(dir_path)


def test_local_filesystem_list_dir() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "f1.txt").write_text("1")
        Path(tmp, "f2.txt").write_text("2")
        Path(tmp, "sub").mkdir()
        entries = fs.list_dir(tmp)
        names = {e.name for e in entries}
        assert "f1.txt" in names
        assert "f2.txt" in names
        assert "sub" in names


def test_local_filesystem_delete_file() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "delete_me.txt")
        fs.write_text(path, "delete me")
        assert fs.exists(path)
        fs.delete(path)
        assert not fs.exists(path)


def test_local_filesystem_delete_file_permission_error_on_persistent_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fs = LocalFileSystem()
    target_file = tmp_path / "locked.txt"
    target_file.write_text("cannot delete")

    def mock_unlink(_path_obj: Path) -> None:
        raise PermissionError("Access denied")

    monkeypatch.setattr(Path, "unlink", mock_unlink)

    with pytest.raises(PermissionError, match="File could not be completely removed"):
        fs.delete(str(target_file))

    assert target_file.exists()


def test_local_filesystem_delete_dir() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        dir_path = str(Path(tmp) / "subdir")
        fs.ensure_dir(dir_path)
        fs.write_text(str(Path(dir_path) / "nested.txt"), "nested")
        fs.delete(dir_path)
        assert not fs.exists(dir_path)


def test_local_filesystem_copy() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        src = str(Path(tmp) / "src.txt")
        dst = str(Path(tmp) / "dst.txt")
        fs.write_text(src, "copy me")
        fs.copy(src, dst)
        assert fs.read_text(dst) == "copy me"


def test_local_filesystem_chmod() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "exec.sh")
        fs.write_text(path, "#!/bin/sh")
        fs.chmod(path, 0o755)
        import os
        import sys

        mode = os.stat(path).st_mode
        if sys.platform != "win32":
            assert mode & 0o111


def test_local_filesystem_walk() -> None:
    fs = LocalFileSystem()
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "a.txt").write_text("a")
        Path(tmp, "sub").mkdir()
        Path(tmp, "sub", "b.txt").write_text("b")
        Path(tmp, "sub", "c.txt").write_text("c")
        files = fs.walk(tmp)
        assert len(files) == 3


def test_write_text_atomic_writes_utf8_and_replaces_existing(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.txt"
    dest.write_text("old content", encoding="utf-8")

    fs.write_text_atomic(str(dest), "héllo ☃")

    assert dest.read_bytes() == "héllo ☃".encode()
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_binary_atomic_fsyncs_file_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    dest.write_bytes(b"old")
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def recording_replace(src: str, dst: str) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)

    fs.write_binary_atomic(str(dest), b"new")

    assert "fsync" in events
    assert events.index("fsync") < events.index("replace")


@pytest.mark.skipif(os.name != "posix", reason="parent directory fsync is POSIX-only")
def test_write_binary_atomic_fsyncs_parent_directory_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    directory_fsyncs: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    fs.write_binary_atomic(str(dest), b"new")

    assert directory_fsyncs, "expected the parent directory to be fsynced"


def test_write_binary_atomic_handles_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    content = b"abcdefghij"
    real_write = os.write

    def short_write(fd: int, data: memoryview) -> int:
        chunk = bytes(memoryview(data)[:3])
        return real_write(fd, chunk)

    monkeypatch.setattr(os, "write", short_write)

    fs.write_binary_atomic(str(dest), content)

    assert dest.read_bytes() == content


def test_write_binary_atomic_closes_fd_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    opened: list[int] = []
    closed: list[int] = []
    real_mkstemp = tempfile.mkstemp
    real_close = os.close

    def recording_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        opened.append(fd)
        return fd, path

    def recording_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def failing_write(_fd: int, _data: memoryview) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr(tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(os, "close", recording_close)
    monkeypatch.setattr(os, "write", failing_write)

    with pytest.raises(OSError, match="simulated write failure"):
        fs.write_binary_atomic(str(dest), b"new")

    assert opened
    assert opened[0] in closed


def test_write_binary_atomic_leaves_destination_untouched_when_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    dest.write_bytes(b"original")

    def failing_fsync(_fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="simulated fsync failure"):
        fs.write_binary_atomic(str(dest), b"new")

    assert dest.read_bytes() == b"original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_binary_atomic_closes_before_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    events: list[str] = []
    real_close = os.close
    real_unlink = os.unlink

    def recording_close(fd: int) -> None:
        events.append("close")
        real_close(fd)

    def recording_unlink(path: str) -> None:
        events.append("unlink")
        real_unlink(path)

    def failing_fsync(_fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "close", recording_close)
    monkeypatch.setattr(os, "unlink", recording_unlink)
    monkeypatch.setattr(os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="simulated fsync failure"):
        fs.write_binary_atomic(str(dest), b"new")

    assert "close" in events
    assert "unlink" in events
    assert events.index("close") < events.index("unlink")


@pytest.mark.skipif(os.name != "posix", reason="parent directory fsync is POSIX-only")
def test_write_binary_atomic_parent_fsync_failure_after_replace_keeps_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    dest.write_bytes(b"old")
    real_fsync = os.fsync
    unlinked: list[str] = []
    real_unlink = os.unlink

    def recording_unlink(path: str) -> None:
        unlinked.append(path)
        real_unlink(path)

    def failing_parent_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated parent directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "unlink", recording_unlink)
    monkeypatch.setattr(os, "fsync", failing_parent_fsync)

    with pytest.raises(OSError, match="simulated parent directory fsync failure"):
        fs.write_binary_atomic(str(dest), b"new")

    assert dest.read_bytes() == b"new"
    assert unlinked == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_binary_atomic_close_error_does_not_mask_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = LocalFileSystem()
    dest = tmp_path / "config.bin"
    dest.write_bytes(b"original")
    real_close = os.close
    real_mkstemp = tempfile.mkstemp
    opened_fds: list[int] = []

    def recording_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        opened_fds.append(fd)
        return fd, path

    def failing_close(fd: int) -> None:
        real_close(fd)
        if fd in opened_fds:
            raise OSError("simulated close failure")

    def failing_write(_fd: int, _data: memoryview) -> int:
        raise RuntimeError("simulated original write failure")

    monkeypatch.setattr(tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(os, "close", failing_close)
    monkeypatch.setattr(os, "write", failing_write)

    with pytest.raises(RuntimeError, match="simulated original write failure"):
        fs.write_binary_atomic(str(dest), b"new")

    assert dest.read_bytes() == b"original"
    assert list(tmp_path.glob("*.tmp")) == []
