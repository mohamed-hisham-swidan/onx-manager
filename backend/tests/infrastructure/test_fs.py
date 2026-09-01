from __future__ import annotations

import tempfile
from pathlib import Path

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
