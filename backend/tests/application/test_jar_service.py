from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    VersionNotFoundError,
)
from app.modules.server.application.services.jar_service import (
    SERVER_TYPES_REQUIRING_MANUAL_INSTALL,
    _resolve_bukkit_url,
    _resolve_fabric_url,
    _resolve_paper_url,
    _resolve_purpur_url,
    _resolve_spigot_url,
    _resolve_vanilla_url,
    download_server_jar,
    fetch_bukkit_versions,
    fetch_fabric_versions,
    fetch_paper_versions,
    fetch_purpur_versions,
    fetch_spigot_versions,
    fetch_vanilla_versions,
    validate_jar,
)


def _mock_aresponse(status: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.__aenter__.return_value = resp
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    return resp


class TestURLResolvers:
    @pytest.mark.asyncio
    async def test_vanilla_success(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            manifest_resp = _mock_aresponse(200, {
                "versions": [
                    {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                ],
            })
            version_resp = _mock_aresponse(200, {
                "downloads": {
                    "server": {"sha1": "abc123"},
                },
            })
            mock_get.side_effect = [manifest_resp, version_resp]

            url = await _resolve_vanilla_url("1.21")

            assert "abc123" in url
            assert url.startswith("https://piston-data.mojang.com")

    @pytest.mark.asyncio
    async def test_vanilla_version_not_found(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {"versions": []})
            mock_get.return_value = resp

            with pytest.raises(VersionNotFoundError, match="1.99"):
                await _resolve_vanilla_url("1.99")

    @pytest.mark.asyncio
    async def test_vanilla_no_server_download(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            manifest_resp = _mock_aresponse(200, {
                "versions": [
                    {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                ],
            })
            version_resp = _mock_aresponse(200, {"downloads": {}})
            mock_get.side_effect = [manifest_resp, version_resp]

            with pytest.raises(VersionNotFoundError):
                await _resolve_vanilla_url("1.21")

    @pytest.mark.asyncio
    async def test_paper_success(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {
                "builds": [{"build": 420}, {"build": 427}],
            })
            mock_get.return_value = resp

            url = await _resolve_paper_url("1.21")

            assert "builds/427/downloads/paper-1.21-427.jar" in url

    @pytest.mark.asyncio
    async def test_paper_no_builds(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {"builds": []})
            mock_get.return_value = resp

            with pytest.raises(VersionNotFoundError, match="not found for paper"):
                await _resolve_paper_url("1.21")

    @pytest.mark.asyncio
    async def test_fabric_success(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, [
                {"loader": {"version": "0.16.10"}, "launcher": {"version": "1.0.1"}},
            ])
            mock_get.return_value = resp

            url = await _resolve_fabric_url("1.21")

            assert "loader/1.21/0.16.10/1.0.1/server/jar" in url

    @pytest.mark.asyncio
    async def test_fabric_no_loaders(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, [])
            mock_get.return_value = resp

            with pytest.raises(VersionNotFoundError, match="fabric"):
                await _resolve_fabric_url("1.21")

    @pytest.mark.asyncio
    async def test_purpur_direct_url(self) -> None:
        url = await _resolve_purpur_url("1.21")
        assert url == "https://api.purpurmc.org/v2/purpur/1.21/latest/download"

    @pytest.mark.asyncio
    async def test_spigot_direct_url(self) -> None:
        url = await _resolve_spigot_url("1.21")
        assert url == "https://download.getbukkit.org/spigot/spigot-1.21.jar"

    @pytest.mark.asyncio
    async def test_bukkit_direct_url(self) -> None:
        url = await _resolve_bukkit_url("1.21")
        assert url == "https://download.getbukkit.org/craftbukkit/craftbukkit-1.21.jar"

    @pytest.mark.asyncio
    async def test_vanilla_http_error(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(500, None)
            mock_get.return_value = resp

            with pytest.raises(DownloadError):
                await _resolve_vanilla_url("1.21")


class TestValidateJar:
    def test_valid_zip(self, tmp_path: Path) -> None:
        jar_path = tmp_path / "server.jar"
        jar_path.write_bytes(b"PK\x03\x04" + b"\x00" * (1024 * 1024))
        validate_jar(str(jar_path))

    def test_too_small(self, tmp_path: Path) -> None:
        jar_path = tmp_path / "tiny.jar"
        jar_path.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        with pytest.raises(CorruptedDownloadError, match="too small"):
            validate_jar(str(jar_path))

    def test_not_zip(self, tmp_path: Path) -> None:
        jar_path = tmp_path / "fake.jar"
        jar_path.write_bytes(b"\x00" * (1024 * 1024 + 50))
        with pytest.raises(CorruptedDownloadError, match="header"):
            validate_jar(str(jar_path))

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(CorruptedDownloadError, match="not found"):
            validate_jar(str(tmp_path / "nonexistent.jar"))

    def test_empty_file(self, tmp_path: Path) -> None:
        jar_path = tmp_path / "empty.jar"
        jar_path.write_bytes(b"")
        with pytest.raises(CorruptedDownloadError, match="too small"):
            validate_jar(str(jar_path))

    def test_exact_min_size(self, tmp_path: Path) -> None:
        jar_path = tmp_path / "minimal.jar"
        size = 1024 * 1024
        jar_path.write_bytes(b"PK\x03\x04" + b"\x00" * (size - 4))
        validate_jar(str(jar_path))


class TestFetchVersions:
    @pytest.mark.asyncio
    async def test_vanilla_versions(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {
                "versions": [
                    {"id": "1.21", "type": "release"},
                    {"id": "1.21-rc1", "type": "snapshot"},
                    {"id": "1.20.4", "type": "release"},
                ],
            })
            mock_get.return_value = resp

            versions = await fetch_vanilla_versions()
            assert "1.21" in versions
            assert "1.20.4" in versions

    @pytest.mark.asyncio
    async def test_paper_versions(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {"versions": ["1.21", "1.20.4"]})
            mock_get.return_value = resp

            versions = await fetch_paper_versions()
            assert "1.21" in versions

    @pytest.mark.asyncio
    async def test_purpur_versions(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {"versions": ["1.21", "1.20.4"]})
            mock_get.return_value = resp

            versions = await fetch_purpur_versions()
            assert "1.21" in versions

    @pytest.mark.asyncio
    async def test_fabric_versions(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, [
                {"version": "1.21", "stable": True},
            ])
            mock_get.return_value = resp

            versions = await fetch_fabric_versions()
            assert "1.21" in versions

    @pytest.mark.asyncio
    async def test_spigot_versions(self) -> None:
        versions = await fetch_spigot_versions()
        assert "1.21.4" in versions

    @pytest.mark.asyncio
    async def test_bukkit_versions(self) -> None:
        versions = await fetch_bukkit_versions()
        assert "1.21.4" in versions

    @pytest.mark.asyncio
    async def test_vanilla_http_error_returns_empty(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(500, None)
            mock_get.return_value = resp

            versions = await fetch_vanilla_versions()
            assert versions == []


class TestDownloadServerJar:
    @pytest.mark.asyncio
    async def test_forge_returns_dest_path(self) -> None:
        with patch("app.modules.server.application.services.jar_service.local_fs") as mock_fs:
            result = await download_server_jar(
                server_id="test-forge-1",
                server_type="forge",
                minecraft_version="1.21",
            )
            assert result is not None
            assert "test-forge-1" in result

    @pytest.mark.asyncio
    async def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown server type"):
            await download_server_jar(
                server_id="test-1",
                server_type="unknown_type",
                minecraft_version="1.21",
            )

    @pytest.mark.asyncio
    async def test_version_not_found(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, {"versions": []})
            mock_get.return_value = resp

            with pytest.raises(VersionNotFoundError):
                await download_server_jar(
                    server_id="test-1",
                    server_type="vanilla",
                    minecraft_version="1.99",
                )

    @pytest.mark.asyncio
    async def test_download_success(self) -> None:
        class AsyncChunkReader:
            def __init__(self, data: bytes):
                self._data = data
                self._offset = 0

            async def read(self, n: int = -1) -> bytes:
                if self._offset >= len(self._data):
                    return b""
                chunk = self._data[self._offset : self._offset + n]
                self._offset += len(chunk)
                return chunk

        jar_bytes = b"PK\x03\x04" + b"\x00" * (1024 * 1024)

        with (
            patch("aiohttp.ClientSession.get") as mock_get,
            patch("app.modules.server.application.services.jar_service.local_fs") as mock_fs,
        ):
            manifest_resp = _mock_aresponse(200, {
                "versions": [
                    {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                ],
            })
            version_resp = _mock_aresponse(200, {
                "downloads": {"server": {"sha1": "abc123"}},
            })
            download_resp = _mock_aresponse(200, None)

            reader = AsyncChunkReader(jar_bytes)
            download_resp.content.read = reader.read

            mock_get.side_effect = [
                manifest_resp, version_resp,
                download_resp, download_resp, download_resp,
            ]

            mock_fs.exists.return_value = True
            mock_fs.size.return_value = len(jar_bytes)
            mock_fs.read_binary.return_value = jar_bytes

            result = await download_server_jar(
                server_id="test-123",
                server_type="vanilla",
                minecraft_version="1.21",
            )

            assert result is not None
            assert "test-123" in result

    @pytest.mark.asyncio
    async def test_corrupted_jar_detected(self) -> None:
        class AsyncChunkReader:
            def __init__(self, data: bytes):
                self._data = data
                self._offset = 0

            async def read(self, n: int = -1) -> bytes:
                if self._offset >= len(self._data):
                    return b""
                chunk = self._data[self._offset : self._offset + n]
                self._offset += len(chunk)
                return chunk

        with (
            patch("aiohttp.ClientSession.get") as mock_get,
            patch("app.modules.server.application.services.jar_service.local_fs") as mock_fs,
        ):
            manifest_resp = _mock_aresponse(200, {
                "versions": [
                    {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                ],
            })
            version_resp = _mock_aresponse(200, {
                "downloads": {"server": {"sha1": "abc123"}},
            })
            download_resp = _mock_aresponse(200, None)

            truncated = b"truncated data"
            reader = AsyncChunkReader(truncated)
            download_resp.content.read = reader.read

            mock_get.side_effect = [
                manifest_resp, version_resp,
                download_resp, download_resp, download_resp,
            ]

            mock_fs.exists.return_value = True
            mock_fs.size.return_value = len(truncated)
            mock_fs.read_binary.return_value = truncated

            with pytest.raises(CorruptedDownloadError):
                await download_server_jar(
                    server_id="test-corrupt",
                    server_type="vanilla",
                    minecraft_version="1.21",
                )

    @pytest.mark.asyncio
    async def test_manual_install_types_listed(self) -> None:
        assert "forge" in SERVER_TYPES_REQUIRING_MANUAL_INSTALL
