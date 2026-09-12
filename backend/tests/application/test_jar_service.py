from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    VersionNotFoundError,
)
from app.modules.server.application.services.jar_service import (
    SERVER_TYPES_REQUIRING_MANUAL_INSTALL,
    _fetch_xml_with_retries,
    _parse_forge_metadata,
    _parse_neoforge_metadata,
    _resolve_bukkit_url,
    _resolve_fabric_url,
    _resolve_forge_url,
    _resolve_neoforge_url,
    _resolve_paper_url,
    _resolve_purpur_url,
    _resolve_spigot_url,
    _resolve_vanilla_url,
    clear_metadata_cache,
    download_server_jar,
    fetch_bukkit_versions,
    fetch_fabric_versions,
    fetch_forge_versions,
    fetch_neoforge_versions,
    fetch_paper_versions,
    fetch_purpur_versions,
    fetch_spigot_versions,
    fetch_vanilla_versions,
    forge_installer_url,
    forge_requires_installer,
    forge_universal_url,
    neoforge_installer_url,
    neoforge_requires_installer,
    neoforge_universal_url,
    resolve_forge_build,
    resolve_neoforge_build,
    validate_jar,
)
from app.modules.server.domain.runtime_exceptions import (
    MetadataFetchError,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> Generator[None, None, None]:
    clear_metadata_cache()
    yield
    clear_metadata_cache()


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
            manifest_resp = _mock_aresponse(
                200,
                {
                    "versions": [
                        {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                    ],
                },
            )
            version_resp = _mock_aresponse(
                200,
                {
                    "downloads": {
                        "server": {"sha1": "abc123"},
                    },
                },
            )
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
            manifest_resp = _mock_aresponse(
                200,
                {
                    "versions": [
                        {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                    ],
                },
            )
            version_resp = _mock_aresponse(200, {"downloads": {}})
            mock_get.side_effect = [manifest_resp, version_resp]

            with pytest.raises(VersionNotFoundError):
                await _resolve_vanilla_url("1.21")

    @pytest.mark.asyncio
    async def test_paper_success(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(
                200,
                [
                    {
                        "id": 427,
                        "downloads": {
                            "server:default": {
                                "url": "https://fill-data.papermc.io/v1/objects/abc/paper-1.21-427.jar",
                            },
                        },
                    },
                ],
            )
            mock_get.return_value = resp

            url = await _resolve_paper_url("1.21")

            assert url == "https://fill-data.papermc.io/v1/objects/abc/paper-1.21-427.jar"

    @pytest.mark.asyncio
    async def test_paper_no_builds(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, [])
            mock_get.return_value = resp

            with pytest.raises(VersionNotFoundError, match="not found for paper"):
                await _resolve_paper_url("1.21")

    @pytest.mark.asyncio
    async def test_fabric_success(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(
                200,
                [
                    {"loader": {"version": "0.16.10"}, "launcher": {"version": "1.0.1"}},
                ],
            )
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
            resp = _mock_aresponse(
                200,
                {
                    "versions": [
                        {"id": "1.21", "type": "release"},
                        {"id": "1.21-rc1", "type": "snapshot"},
                        {"id": "1.20.4", "type": "release"},
                        {"id": "1.20.1", "type": "release"},
                    ],
                },
            )
            mock_get.return_value = resp

            versions = await fetch_vanilla_versions()
            assert versions == ["1.21", "1.20.4", "1.20.1"]

    @pytest.mark.asyncio
    async def test_paper_versions(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(
                200,
                {
                    "versions": {
                        "1.21": ["1.21.5", "1.21.4", "1.21"],
                        "1.20": ["1.20.6"],
                    },
                },
            )
            mock_get.return_value = resp

            versions = await fetch_paper_versions()
            assert "1.21.5" in versions
            assert "1.20.6" in versions
            assert versions[:3] == ["1.21.5", "1.21.4", "1.21"]

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
            resp = _mock_aresponse(
                200,
                [
                    {"version": "1.21", "stable": True},
                    {"version": "1.21.1", "stable": True},
                    {"version": "24w14", "stable": False},
                    {"version": "1.20.4", "stable": True},
                ],
            )
            mock_get.return_value = resp

            versions = await fetch_fabric_versions()
            assert versions == ["1.21", "1.21.1", "1.20.4"]

    @pytest.mark.asyncio
    async def test_forge_versions_unique_mc_newest_first(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <latest>26.2-65.1.2</latest>
            <versions>
              <version>1.21.1-52.0.30</version>
              <version>1.21.1-52.0.29</version>
              <version>1.20.4-49.1.0</version>
              <version>26.2-65.1.2</version>
              <version>1.21-51.0.33</version>
              <version>1.21.8-58.0.3</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, xml)
            resp.text = AsyncMock(return_value=xml)
            mock_get.return_value = resp

            versions = await fetch_forge_versions()

            # "26.2-65.1.2" is Forge's unified artifact revision, not a
            # Minecraft version — it must not appear in the MC version list.
            assert versions == ["1.21.8", "1.21.1", "1.21", "1.20.4"]

    @pytest.mark.asyncio
    async def test_forge_versions_http_error_returns_empty(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(500, None)
            mock_get.return_value = resp

            versions = await fetch_forge_versions()
            assert versions == []

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


class TestForgeBuildResolution:
    def test_parse_metadata(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.20.1-47.4.23</version>
              <version>1.9-12.16.1.1938-1.9.0</version>
              <version>26.2-65.1.2</version>
            </versions>
          </versioning>
        </metadata>
        """
        entries = _parse_forge_metadata(xml)
        assert [e.version for e in entries] == [
            "1.20.1-47.4.23",
            "1.9-12.16.1.1938-1.9.0",
            "26.2-65.1.2",
        ]
        assert entries[0].minecraft == "1.20.1"
        assert entries[0].build == (47, 4, 23)
        assert entries[1].minecraft == "1.9"
        assert entries[2].minecraft == "26.2"

    @pytest.mark.asyncio
    async def test_resolve_highest_numeric_build(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.21.1-52.0.2</version>
              <version>1.21.1-52.0.10</version>
              <version>1.21.1-52.0.3</version>
            </versions>
          </versioning>
        </metadata>
        """
        entry_list = _parse_forge_metadata(xml)
        assert await resolve_forge_build("1.21.1", entries=entry_list) == "1.21.1-52.0.10"

    @pytest.mark.asyncio
    async def test_resolve_unknown_version_returns_none(
        self,
    ) -> None:
        assert await resolve_forge_build("9.9.9", entries=[]) is None

    @pytest.mark.asyncio
    async def test_resolve_fetches_when_no_entries(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.20.1-47.4.1</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch(
            "app.modules.server.application.services.jar_service.aiohttp.ClientSession.get"
        ) as mock_get:
            resp = _mock_aresponse(200, xml)
            resp.text = AsyncMock(return_value=xml)
            mock_get.return_value = resp
            assert await resolve_forge_build("1.20.1") == "1.20.1-47.4.1"

    def test_forge_requires_installer(self) -> None:
        assert forge_requires_installer("1.17")
        assert forge_requires_installer("1.20.1")
        assert not forge_requires_installer("1.16.5")
        assert not forge_requires_installer("1.12.2")
        assert forge_requires_installer("not-a-version")

    def test_forge_artifact_urls(self) -> None:
        assert forge_universal_url("1.12.2-14.23.5.2860") == (
            "https://maven.minecraftforge.net/net/minecraftforge/forge/"
            "1.12.2-14.23.5.2860/forge-1.12.2-14.23.5.2860-universal.jar"
        )
        assert forge_installer_url("1.20.1-47.4.23") == (
            "https://maven.minecraftforge.net/net/minecraftforge/forge/"
            "1.20.1-47.4.23/forge-1.20.1-47.4.23-installer.jar"
        )

    @pytest.mark.asyncio
    async def test_resolve_forge_url_universal(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.16.5-36.2.42</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch(
            "app.modules.server.application.services.jar_service.aiohttp.ClientSession.get"
        ) as mock_get:
            resp = _mock_aresponse(200, xml)
            resp.text = AsyncMock(return_value=xml)
            mock_get.return_value = resp
            url = await _resolve_forge_url("1.16.5")
            assert url.endswith("forge-1.16.5-36.2.42-universal.jar")

    @pytest.mark.asyncio
    async def test_resolve_forge_url_version_missing(self) -> None:
        with patch(
            "app.modules.server.application.services.jar_service.aiohttp.ClientSession.get"
        ) as mock_get:
            resp = _mock_aresponse(200, "<metadata/>")
            resp.text = AsyncMock(return_value="<metadata/>")
            mock_get.return_value = resp
            with pytest.raises(VersionNotFoundError, match="forge"):
                await _resolve_forge_url("1.99.9")

    @pytest.mark.asyncio
    async def test_resolve_ignores_unified_pseudo_version(self) -> None:
        """Forge's new unified artifact revision (26.x-65.x) is not a real
        Minecraft version and must never resolve to a build."""
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>26.2-65.1.2</version>
              <version>1.21.11-61.2.1</version>
            </versions>
          </versioning>
        </metadata>
        """
        entries = _parse_forge_metadata(xml)
        assert await resolve_forge_build("26.2", entries=entries) is None
        assert await resolve_forge_build("1.21.11", entries=entries) == "1.21.11-61.2.1"

    def test_is_real_forge_minecraft(self) -> None:
        from app.modules.server.application.services.jar_service import _is_real_forge_minecraft

        assert _is_real_forge_minecraft("1.21.11")
        assert _is_real_forge_minecraft("1.9")
        assert not _is_real_forge_minecraft("26.2")
        assert not _is_real_forge_minecraft("26.1.2")
        assert not _is_real_forge_minecraft("not-a-version")


class TestNeoForgeBuildResolution:
    def test_parse_metadata_modern(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>26.2.0.64</version>
              <version>26.1.2.97</version>
              <version>20.4.167</version>
              <version>21.1.248</version>
              <version>21.0.167</version>
              <version>20.2.12-beta</version>
              <version>0.25w14craftmine</version>
            </versions>
          </versioning>
        </metadata>
        """
        entries = _parse_neoforge_metadata(xml, is_forge_artifact=False)
        assert len(entries) == 6
        assert entries[0].minecraft == "26.2"
        assert entries[0].version == "26.2.0.64"
        assert entries[0].build == (26, 2, 0, 64)
        assert entries[1].minecraft == "26.1"
        assert entries[2].minecraft == "1.20.4"
        assert entries[3].minecraft == "1.21.1"
        assert entries[4].minecraft == "1.21.0"
        assert entries[5].minecraft == "1.20.2"

    def test_parse_metadata_legacy_forge_artifact(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.20.1-47.1.106</version>
            </versions>
          </versioning>
        </metadata>
        """
        entries = _parse_neoforge_metadata(xml, is_forge_artifact=True)
        assert len(entries) == 1
        assert entries[0].minecraft == "1.20.1"
        assert entries[0].version == "1.20.1-47.1.106"
        assert entries[0].build == (47, 1, 106)

    @pytest.mark.asyncio
    async def test_resolve_highest_numeric_build(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>20.4.2</version>
              <version>20.4.251</version>
              <version>20.4.3</version>
            </versions>
          </versioning>
        </metadata>
        """
        entry_list = _parse_neoforge_metadata(xml)
        assert await resolve_neoforge_build("1.20.4", entries=entry_list) == "20.4.251"

    @pytest.mark.asyncio
    async def test_resolve_unknown_version_returns_none(self) -> None:
        assert await resolve_neoforge_build("9.9.9", entries=[]) is None

    def test_neoforge_requires_installer(self) -> None:
        assert neoforge_requires_installer("1.21.1")
        assert neoforge_requires_installer("1.20.1")

    def test_neoforge_artifact_urls(self) -> None:
        assert neoforge_installer_url("21.1.248") == (
            "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.248/neoforge-21.1.248-installer.jar"
        )
        assert neoforge_installer_url("1.20.1-47.1.106") == (
            "https://maven.neoforged.net/releases/net/neoforged/forge/1.20.1-47.1.106/forge-1.20.1-47.1.106-installer.jar"
        )
        assert neoforge_universal_url("21.1.248") == (
            "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.248/neoforge-21.1.248-universal.jar"
        )
        assert neoforge_universal_url("1.20.1-47.1.106") == (
            "https://maven.neoforged.net/releases/net/neoforged/forge/1.20.1-47.1.106/forge-1.20.1-47.1.106-universal.jar"
        )

    @pytest.mark.asyncio
    async def test_resolve_neoforge_url(self) -> None:
        xml_neo = "<metadata><versioning><versions><version>21.1.248</version></versions></versioning></metadata>"
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, xml_neo)
            resp.text = AsyncMock(return_value=xml_neo)
            mock_get.return_value = resp
            url = await _resolve_neoforge_url("1.21.1")
            assert url.endswith("neoforge-21.1.248-universal.jar")

    @pytest.mark.asyncio
    async def test_resolve_neoforge_url_version_missing(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, "<metadata/>")
            resp.text = AsyncMock(return_value="<metadata/>")
            mock_get.return_value = resp
            with pytest.raises(VersionNotFoundError, match="neoforge"):
                await _resolve_neoforge_url("1.99.9")

    @pytest.mark.asyncio
    async def test_fetch_neoforge_versions(self) -> None:
        xml_neo = """
        <metadata>
          <versioning>
            <versions>
              <version>26.2.0.64</version>
              <version>20.4.167</version>
              <version>21.1.248</version>
              <version>21.0.167</version>
            </versions>
          </versioning>
        </metadata>
        """
        xml_forge = """
        <metadata>
          <versioning>
            <versions>
              <version>1.20.1-47.1.106</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp_neo = _mock_aresponse(200, xml_neo)
            resp_neo.text = AsyncMock(return_value=xml_neo)
            resp_forge = _mock_aresponse(200, xml_forge)
            resp_forge.text = AsyncMock(return_value=xml_forge)
            mock_get.side_effect = [resp_neo, resp_forge]

            versions = await fetch_neoforge_versions()
            assert versions == ["26.2", "1.21.1", "1.21.0", "1.20.4", "1.20.1"]


class TestDownloadServerJar:
    @pytest.mark.asyncio
    async def test_forge_returns_dest_path(self) -> None:
        with patch("app.modules.server.application.services.jar_service.local_fs"):
            result = await download_server_jar(
                server_id="test-forge-1",
                server_type="forge",
                minecraft_version="1.21",
            )
            assert result is not None
            assert "test-forge-1" in result

    @pytest.mark.asyncio
    async def test_legacy_forge_downloads_universal_jar(self) -> None:
        jar_bytes = b"PK\x03\x04" + b"\x00" * (1024 * 1024)
        entries = _parse_forge_metadata(
            "<metadata><versioning><version>1.16.5-36.2.42</version></versioning></metadata>"
        )
        mock_download = AsyncMock(return_value=jar_bytes)
        with (
            patch(
                "app.modules.server.application.services.jar_service._fetch_forge_metadata",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "app.modules.server.application.services.jar_service._do_download",
                new=mock_download,
            ),
            patch("app.modules.server.application.services.jar_service.local_fs") as mock_fs,
        ):
            mock_fs.exists.return_value = True
            mock_fs.size.return_value = len(jar_bytes)
            mock_fs.read_binary.return_value = jar_bytes

            result = await download_server_jar(
                server_id="test-forge-legacy",
                server_type="forge",
                minecraft_version="1.16.5",
            )
            assert result is not None
            universal_url = (
                "https://maven.minecraftforge.net/net/minecraftforge/forge/"
                "1.16.5-36.2.42/forge-1.16.5-36.2.42-universal.jar"
            )
            assert universal_url in [c.args[0] for c in mock_download.await_args_list]
            mock_fs.write_binary_atomic.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_server_jar_downloads_once_on_success(self) -> None:
        """Regression: the retry loop must stop after the first successful
        download instead of re-downloading on every attempt."""
        jar_bytes = b"PK\x03\x04" + b"\x00" * (1024 * 1024)
        entries = _parse_forge_metadata(
            "<metadata><versioning><version>1.16.5-36.2.42</version></versioning></metadata>"
        )
        mock_download = AsyncMock(return_value=jar_bytes)
        with (
            patch(
                "app.modules.server.application.services.jar_service._fetch_forge_metadata",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "app.modules.server.application.services.jar_service._do_download",
                new=mock_download,
            ),
            patch("app.modules.server.application.services.jar_service.local_fs") as mock_fs,
        ):
            mock_fs.exists.return_value = True
            mock_fs.size.return_value = len(jar_bytes)
            mock_fs.read_binary.return_value = jar_bytes

            await download_server_jar(
                server_id="test-once",
                server_type="forge",
                minecraft_version="1.16.5",
            )

            assert mock_download.await_count == 1
            mock_fs.write_binary_atomic.assert_called_once()

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
            manifest_resp = _mock_aresponse(
                200,
                {
                    "versions": [
                        {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                    ],
                },
            )
            version_resp = _mock_aresponse(
                200,
                {
                    "downloads": {"server": {"sha1": "abc123"}},
                },
            )
            download_resp = _mock_aresponse(200, None)

            reader = AsyncChunkReader(jar_bytes)
            download_resp.content.read = reader.read

            mock_get.side_effect = [
                manifest_resp,
                version_resp,
                download_resp,
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
            manifest_resp = _mock_aresponse(
                200,
                {
                    "versions": [
                        {"id": "1.21", "type": "release", "url": "https://example.com/1.21.json"},
                    ],
                },
            )
            version_resp = _mock_aresponse(
                200,
                {
                    "downloads": {"server": {"sha1": "abc123"}},
                },
            )
            download_resp = _mock_aresponse(200, None)

            truncated = b"truncated data"
            reader = AsyncChunkReader(truncated)
            download_resp.content.read = reader.read

            mock_get.side_effect = [
                manifest_resp,
                version_resp,
                download_resp,
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
        assert "neoforge" in SERVER_TYPES_REQUIRING_MANUAL_INSTALL

    @pytest.mark.asyncio
    async def test_neoforge_returns_dest_path(self) -> None:
        with patch("app.modules.server.application.services.jar_service.local_fs"):
            result = await download_server_jar(
                server_id="test-neoforge-1",
                server_type="neoforge",
                minecraft_version="1.21.1",
            )
            assert result is not None
            assert "test-neoforge-1" in result


class TestMetadataCacheAndRetries:
    def setup_method(self) -> None:
        clear_metadata_cache()

    def teardown_method(self) -> None:
        clear_metadata_cache()

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_duplicate_network_calls(self) -> None:
        xml_forge = """
        <metadata>
          <versioning>
            <versions>
              <version>1.20.1-47.4.23</version>
              <version>1.20.1-47.4.24</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch(
            "app.modules.server.application.services.jar_service._fetch_xml_with_retries",
            AsyncMock(return_value=xml_forge),
        ) as mock_fetch:
            # 1. Wizard fetches versions:
            versions = await fetch_forge_versions()
            assert versions == ["1.20.1"]
            assert mock_fetch.call_count == 1

            # 2. Provisioning resolves build:
            build = await resolve_forge_build("1.20.1")
            assert build == "1.20.1-47.4.24"
            # Zero duplicate network calls!
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expiry_triggers_new_fetch(self) -> None:
        xml_forge = "<metadata><versioning><versions><version>1.20.1-47.4.23</version></versions></versioning></metadata>"
        with (
            patch(
                "app.modules.server.application.services.jar_service._fetch_xml_with_retries",
                AsyncMock(return_value=xml_forge),
            ) as mock_fetch,
            patch("time.monotonic") as mock_time,
        ):
            mock_time.return_value = 1000.0
            await fetch_forge_versions()
            assert mock_fetch.call_count == 1

            # Time moves forward past 300s TTL (e.g. +301s)
            mock_time.return_value = 1301.1
            await resolve_forge_build("1.20.1")
            assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_metadata_cache(self) -> None:
        xml_forge = "<metadata><versioning><versions><version>1.20.1-47.4.23</version></versions></versioning></metadata>"
        with patch(
            "app.modules.server.application.services.jar_service._fetch_xml_with_retries",
            AsyncMock(return_value=xml_forge),
        ) as mock_fetch:
            await fetch_forge_versions()
            assert mock_fetch.call_count == 1

            clear_metadata_cache("forge")
            await resolve_forge_build("1.20.1")
            assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_xml_with_retries_recovers_after_transient_error(self) -> None:
        with (
            patch("aiohttp.ClientSession.get") as mock_get,
            patch("asyncio.sleep", AsyncMock()) as mock_sleep,
        ):
            fail_resp = _mock_aresponse(500)
            ok_resp = _mock_aresponse(200)
            ok_resp.text = AsyncMock(return_value="<xml>ok</xml>")

            mock_get.side_effect = [fail_resp, ok_resp]

            result = await _fetch_xml_with_retries("https://example.com/maven-metadata.xml")
            assert result == "<xml>ok</xml>"
            assert mock_sleep.call_count == 1
            mock_sleep.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_fetch_xml_with_retries_raises_metadata_fetch_error_on_exhaustion(self) -> None:
        with (
            patch("aiohttp.ClientSession.get") as mock_get,
            patch("asyncio.sleep", AsyncMock()),
        ):
            mock_get.side_effect = aiohttp.ClientError("connection refused")

            with pytest.raises(MetadataFetchError) as exc_info:
                await _fetch_xml_with_retries(
                    "https://example.com/maven-metadata.xml", max_retries=2
                )

            assert "Failed to fetch metadata" in str(exc_info.value)
            assert "connection refused" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_server_jar_retry_exhaustion_logs_and_raises(self) -> None:
        with (
            patch(
                "app.modules.server.application.services.jar_service._resolve_download_url_async",
                AsyncMock(return_value="https://example.com/paper.jar"),
            ),
            patch(
                "app.modules.server.application.services.jar_service._do_download",
                side_effect=DownloadTimeoutError("https://example.com/paper.jar", 30),
            ),
            patch("asyncio.sleep", AsyncMock()) as mock_sleep,
            patch("app.modules.server.application.services.jar_service.logger") as mock_logger,
        ):
            with pytest.raises(DownloadTimeoutError) as exc_info:
                await download_server_jar(
                    server_id="test-retry-exhaust",
                    server_type="paper",
                    minecraft_version="1.21",
                )

            assert mock_sleep.call_count == 2
            mock_logger.error.assert_called_once()
            err_msg = mock_logger.error.call_args[0][0]
            assert "permanently failed" in err_msg
            assert exc_info.value.details["url"] == "https://example.com/paper.jar"
            assert exc_info.value.details["timeout_seconds"] == 30

    @pytest.mark.asyncio
    async def test_download_server_jar_streaming_part_file_and_atomic_rename(
        self, tmp_path: Path
    ) -> None:
        jar_bytes = b"PK\x03\x04" + b"\x00" * (1024 * 1024)
        dest_file = tmp_path / "server.jar"
        deployment = MagicMock()
        deployment.root_path = str(tmp_path)
        deployment.jar_path.return_value = str(dest_file)

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
            patch(
                "app.modules.server.application.services.jar_service._resolve_download_url_async",
                AsyncMock(return_value="https://example.com/stream.jar"),
            ),
            patch("aiohttp.ClientSession.get") as mock_get,
        ):
            resp = _mock_aresponse(200, None)
            reader = AsyncChunkReader(jar_bytes)
            resp.content.read = reader.read
            mock_get.return_value = resp

            result = await download_server_jar(
                server_id="test-stream",
                server_type="paper",
                minecraft_version="1.21",
                deployment=deployment,
            )

            assert result == str(dest_file)
            assert dest_file.exists()
            assert dest_file.read_bytes() == jar_bytes
            assert not Path(str(dest_file) + ".part").exists()

    @pytest.mark.asyncio
    async def test_download_server_jar_cleans_up_part_on_error(
        self, tmp_path: Path
    ) -> None:
        dest_file = tmp_path / "server.jar"
        deployment = MagicMock()
        deployment.root_path = str(tmp_path)
        deployment.jar_path.return_value = str(dest_file)

        class FailingChunkReader:
            def __init__(self):
                self.calls = 0

            async def read(self, n: int = -1) -> bytes:
                self.calls += 1
                if self.calls == 1:
                    return b"some-partial-data"
                raise TimeoutError("connection stalled")

        with (
            patch(
                "app.modules.server.application.services.jar_service._resolve_download_url_async",
                AsyncMock(return_value="https://example.com/fail.jar"),
            ),
            patch("aiohttp.ClientSession.get") as mock_get,
            patch("asyncio.sleep", AsyncMock()),
        ):
            resp = _mock_aresponse(200, None)
            reader = FailingChunkReader()
            resp.content.read = reader.read
            mock_get.return_value = resp

            with pytest.raises(DownloadTimeoutError):
                await download_server_jar(
                    server_id="test-fail-clean",
                    server_type="paper",
                    minecraft_version="1.21",
                    deployment=deployment,
                )

            assert not Path(str(dest_file) + ".part").exists()
            assert not dest_file.exists()
