from __future__ import annotations

import tempfile
from pathlib import Path

from app.modules.server.infrastructure.scanner import (
    FilesystemScanner,
    _detect_server_type,
    _dir_looks_like_server,
    _read_properties,
    parse_dirname_for_id,
)


class TestFilesystemScanner:
    async def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            scanner = FilesystemScanner(root_dir=tmp)
            results = await scanner.scan()
        assert results == []

    async def test_scan_detects_server_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "my-server-a1b2c3d4"
            srvd.mkdir()
            (srvd / "server.jar").write_text("fake jar")
            (srvd / "server.properties").write_text("server-port=25565\nlevel-name=world\n")
            (srvd / "world").mkdir()
            (srvd / "eula.txt").write_text("eula=true")

            scanner = FilesystemScanner(root_dir=tmp)
            results = await scanner.scan()

        assert len(results) == 1
        assert results[0].dirname == "my-server-a1b2c3d4"
        assert results[0].has_server_jar is True
        assert results[0].has_world_dir is True
        assert results[0].has_server_properties is True
        assert results[0].has_eula is True
        assert results[0].detected_type == "vanilla"

    async def test_scan_skips_non_server_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "not-a-server").mkdir()
            (Path(tmp) / "empty-dir").mkdir()
            (Path(tmp) / "readme.txt").write_text("hello")

            scanner = FilesystemScanner(root_dir=tmp)
            results = await scanner.scan()

        assert len(results) == 0

    async def test_detect_paper_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "paper-srv"
            srvd.mkdir()
            (srvd / "server.jar").write_text("")
            (srvd / "paper.yml").write_text("")
            assert _detect_server_type(srvd) == "paper"

    async def test_detect_spigot_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "spigot-srv"
            srvd.mkdir()
            (srvd / "spigot.yml").write_text("")
            assert _detect_server_type(srvd) == "spigot"


class TestDirLooksLikeServer:
    def test_valid_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "srv"
            srvd.mkdir()
            (srvd / "server.jar").write_text("")
            (srvd / "world").mkdir()
            assert _dir_looks_like_server(srvd)

    def test_no_jar(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "srv"
            srvd.mkdir()
            (srvd / "world").mkdir()
            assert not _dir_looks_like_server(srvd)

    def test_no_world_no_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "srv"
            srvd.mkdir()
            (srvd / "server.jar").write_text("")
            assert not _dir_looks_like_server(srvd)


class TestParseDirname:
    def test_full_uuid(self):
        assert (
            parse_dirname_for_id("be193e92e2aa4728a0854cad9e37cca1")
            == "be193e92e2aa4728a0854cad9e37cca1"
        )

    def test_slug_with_uuid(self):
        assert parse_dirname_for_id("my-server-be193e92") == "be193e92"

    def test_no_match(self):
        assert parse_dirname_for_id("random") is None


class TestReadProperties:
    def test_reads_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            props = Path(tmp) / "server.properties"
            props.write_text("server-port=25565\nlevel-name=myworld\ngamemode=survival\n")
            result = _read_properties(props)
        assert result["server-port"] == "25565"
        assert result["level-name"] == "myworld"
        assert result["gamemode"] == "survival"

    def test_skips_comments_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            props = Path(tmp) / "server.properties"
            props.write_text("# comment\n\nserver-port=25565\n")
            result = _read_properties(props)
        assert result["server-port"] == "25565"
        assert "comment" not in result
