from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.modules.plugin.infrastructure.sandbox import (
    FilesystemSandbox,
    NetworkSandbox,
    Sandbox,
)


class TestFilesystemSandbox:
    def test_resolve_path_within_plugin_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            resolved = sandbox.resolve_path("test.txt")
            assert resolved.resolve().is_relative_to(Path(tmp).resolve())

    def test_read_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("hello.txt", b"world")
            data = sandbox.read_file("hello.txt")
            assert data == b"world"

    def test_read_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            with pytest.raises(FileNotFoundError):
                sandbox.read_file("nonexistent.txt")

    def test_delete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("temp.txt", b"data")
            sandbox.delete_file("temp.txt")
            assert not sandbox.file_exists("temp.txt")

    def test_list_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("a.txt", b"a")
            sandbox.write_file("b.txt", b"b")
            files = sandbox.list_files()
            assert "a.txt" in files
            assert "b.txt" in files

    def test_path_escape_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            with pytest.raises(PermissionError):
                sandbox.resolve_path("../etc/passwd")

    def test_allowed_path_outside_plugin_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as allowed:
            sandbox = FilesystemSandbox(tmp, allowed_paths=[allowed])
            allowed_file = os.path.join(allowed, "shared.txt")
            with open(allowed_file, "w") as f:
                f.write("data")
            resolved = sandbox.resolve_path(os.path.join(allowed, "shared.txt"))
            assert os.path.exists(str(resolved))

    def test_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("exists.txt", b"yep")
            assert sandbox.file_exists("exists.txt")
            assert not sandbox.file_exists("nope.txt")


class TestNetworkSandbox:
    def test_allows_without_restrictions(self) -> None:
        sandbox = NetworkSandbox()
        assert sandbox.check_connection("example.com", 443)

    def test_blocks_unauthorized_host(self) -> None:
        sandbox = NetworkSandbox(allowed_hosts=["api.example.com"])
        assert sandbox.check_connection("api.example.com", 443)
        assert not sandbox.check_connection("evil.com", 443)

    def test_blocks_unauthorized_port(self) -> None:
        sandbox = NetworkSandbox(allowed_ports=[443])
        assert sandbox.check_connection("example.com", 443)
        assert not sandbox.check_connection("example.com", 80)

    def test_url_check(self) -> None:
        sandbox = NetworkSandbox(allowed_hosts=["api.example.com"])
        assert sandbox.check_url("https://api.example.com/v1/data")
        assert not sandbox.check_url("https://evil.com/hack")


class TestSandbox:
    def test_creates_both_sandboxes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Sandbox(
                plugin_dir=tmp,
                permissions={
                    "filesystem": {"paths": []},
                    "network": {"hosts": ["example.com"], "ports": [443]},
                },
            )
            assert sandbox.filesystem is not None
            assert sandbox.network is not None
            assert sandbox.network.check_connection("example.com", 443)
