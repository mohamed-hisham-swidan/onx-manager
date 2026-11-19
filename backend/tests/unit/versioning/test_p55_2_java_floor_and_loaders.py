"""Tests for P5.5-2 Java floor, Quilt metadata, Forge bounds, and Paper Fill v3."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.event_bus import EventBus
from app.core.exceptions import UnsupportedForgeVersionError, VersionNotFoundError
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.services.jar_service import (
    SERVER_TYPES_REQUIRING_MANUAL_INSTALL,
    SOFTWARE_METADATA,
    _resolve_quilt_url,
    clear_metadata_cache,
    fetch_forge_versions,
    fetch_quilt_versions,
    resolve_paper_build,
    resolve_quilt_loader_version,
    validate_forge_supported_version,
)
from app.modules.server.domain.value_objects import ServerType
from app.modules.server.infrastructure.providers.docker import resolve_docker_image
from app.modules.versioning.application.loader_ref import derive_loader_ref_from_parts
from app.modules.versioning.domain.lockfile import LoaderRef
from app.modules.versioning.infrastructure.java_floor import (
    map_java_major_to_temurin_tag,
    resolve_java_floor_from_mc_version,
    resolve_java_major,
    temurin_docker_image_for_java_major,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_metadata_cache()


def _mock_aresponse(status: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.__aenter__.return_value = resp
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    return resp


class TestQuiltSupport:
    def test_server_type_quilt_and_display_name(self) -> None:
        assert ServerType.QUILT == "quilt"
        assert ServerType.QUILT.value == "quilt"
        assert ServerType.display_name("quilt") == "Quilt"
        assert ServerType.display_name(ServerType.QUILT) == "Quilt"
        assert "quilt" in SOFTWARE_METADATA
        assert "quilt" in SERVER_TYPES_REQUIRING_MANUAL_INSTALL

    def test_derive_loader_ref_quilt_from_libraries_and_fallback(self, tmp_path: Path) -> None:
        quilt_dir = tmp_path / "libraries" / "org" / "quiltmc" / "quilt-loader"
        (quilt_dir / "0.26.0").mkdir(parents=True)
        (quilt_dir / "0.25.0").mkdir(parents=True)

        ref = derive_loader_ref_from_parts(ServerType.QUILT, "1.20.1", server_root=tmp_path)
        assert ref == LoaderRef(id="quilt", version="0.25.0")

        fallback = derive_loader_ref_from_parts(ServerType.QUILT, "1.20.1")
        assert fallback == LoaderRef(id="quilt", version="1.20.1")

    @pytest.mark.asyncio
    async def test_quilt_version_and_url_resolution(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            game_resp = _mock_aresponse(
                200,
                [
                    {"version": "1.21.1", "stable": True},
                    {"version": "1.20.1", "stable": True},
                    {"version": "24w14potato", "stable": False},
                ],
            )
            loader_resp = _mock_aresponse(
                200,
                [{"loader": {"version": "0.26.3"}}, {"loader": {"version": "0.25.0"}}],
            )
            loader_resp_2 = _mock_aresponse(200, [{"loader": {"version": "0.26.3"}}])
            mock_get.side_effect = [game_resp, loader_resp, loader_resp_2]

            assert await fetch_quilt_versions() == ["1.21.1", "1.20.1"]
            assert await resolve_quilt_loader_version("1.20.1") == "0.26.3"
            assert (
                await _resolve_quilt_url("1.20.1")
                == "https://meta.quiltmc.org/v3/versions/loader/1.20.1/0.26.3/server/json"
            )


class TestForgeSupportedRange:
    @pytest.mark.parametrize("mc_version", ["1.17.1", "1.18.2", "1.19.4", "1.20.1"])
    def test_valid_forge_versions_pass(self, mc_version: str) -> None:
        assert str(validate_forge_supported_version(mc_version)) == mc_version

    @pytest.mark.parametrize("mc_version", ["1.16.5", "1.17.0", "1.20.2", "1.21.1", "26.1"])
    def test_out_of_range_forge_versions_raise(self, mc_version: str) -> None:
        with pytest.raises(UnsupportedForgeVersionError) as exc_info:
            validate_forge_supported_version(mc_version)
        assert exc_info.value.http_status == 422

    @pytest.mark.asyncio
    async def test_fetch_forge_versions_filters_outside_supported_range(self) -> None:
        xml = """
        <metadata>
          <versioning>
            <versions>
              <version>1.21.1-52.0.30</version>
              <version>1.20.2-48.1.0</version>
              <version>1.20.1-47.4.23</version>
              <version>1.17.1-37.1.1</version>
              <version>1.17-36.0.0</version>
              <version>1.16.5-36.2.42</version>
            </versions>
          </versioning>
        </metadata>
        """
        with patch("aiohttp.ClientSession.get") as mock_get:
            resp = _mock_aresponse(200, xml)
            resp.text = AsyncMock(return_value=xml)
            mock_get.return_value = resp

            assert await fetch_forge_versions() == ["1.20.1", "1.17.1"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_mc", ["1.16.5", "1.20.2"])
    async def test_create_server_handler_rejects_unsupported_forge(
        self, tmp_path: Path, bad_mc: str
    ) -> None:
        handler = CreateServerHandler(EventBus())
        cmd = CreateServerCommand(
            name="forge-out-of-range",
            server_type="forge",
            minecraft_version=bad_mc,
            provider="local",
            install_dir=str(tmp_path / "srv"),
        )
        with pytest.raises(UnsupportedForgeVersionError) as exc_info:
            await handler.handle(cmd)
        assert exc_info.value.http_status == 422


class TestPaperFillV3Resolution:
    @pytest.mark.asyncio
    async def test_version_group_resolves_highest_patch_and_highest_stable_build(self) -> None:
        with patch("aiohttp.ClientSession.get") as mock_get:
            project_resp = _mock_aresponse(
                200,
                {
                    "versions": {
                        "26.1": ["26.1.1", "26.1.2"],
                        "1.21": ["1.21.4", "1.21.1"],
                    }
                },
            )
            builds_resp = _mock_aresponse(
                200,
                [
                    {
                        "id": 10,
                        "channel": "STABLE",
                        "java": {"version": {"minimum": 25}},
                        "downloads": {
                            "server:default": {
                                "url": "https://fill-data.papermc.io/v1/objects/10/paper-26.1.2-10.jar",
                                "checksums": {"sha256": "1" * 64},
                                "size": 1000,
                            }
                        },
                    },
                    {
                        "id": 25,
                        "channel": "STABLE",
                        "java": {"version": {"minimum": 25}},
                        "downloads": {
                            "server:default": {
                                "url": "https://fill-data.papermc.io/v1/objects/25/paper-26.1.2-25.jar",
                                "checksums": {"sha256": "2" * 64},
                                "size": 2500,
                            }
                        },
                    },
                    {
                        "id": 99,
                        "channel": "BETA",
                        "downloads": {
                            "server:default": {
                                "url": "https://fill-data.papermc.io/v1/objects/99/paper-26.1.2-99.jar",
                            }
                        },
                    },
                ],
            )
            mock_get.side_effect = [project_resp, builds_resp]

            res = await resolve_paper_build("26.1")
            assert res.mc_version == "26.1.2"
            assert res.build_id == 25
            assert res.channel == "STABLE"
            assert res.sha256 == "2" * 64
            assert res.size == 2500
            assert res.java_min_major == 25

    @pytest.mark.asyncio
    async def test_beta_alpha_rejected_by_default_and_allowed_when_opted_in(self) -> None:
        builds_payload = [
            {
                "id": 42,
                "channel": "BETA",
                "downloads": {
                    "server:default": {
                        "url": "https://fill-data.papermc.io/v1/objects/42/paper-1.21.5-42.jar",
                    }
                },
            },
            {
                "id": 45,
                "channel": "ALPHA",
                "downloads": {
                    "server:default": {
                        "url": "https://fill-data.papermc.io/v1/objects/45/paper-1.21.5-45.jar",
                    }
                },
            },
        ]
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.side_effect = [
                _mock_aresponse(200, {"versions": {"1.21": ["1.21.5"]}}),
                _mock_aresponse(200, builds_payload),
            ]
            with pytest.raises(VersionNotFoundError):
                await resolve_paper_build("1.21.5")

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.side_effect = [
                _mock_aresponse(200, {"versions": {"1.21": ["1.21.5"]}}),
                _mock_aresponse(200, builds_payload),
            ]
            res = await resolve_paper_build("1.21.5", allow_experimental_paper_builds=True)
            assert res.build_id == 45
            assert res.channel == "ALPHA"


class TestJavaFloorResolution:
    @pytest.mark.parametrize(
        ("mc", "expected_major", "expected_tag", "expected_image"),
        [
            ("1.16.5", 8, 8, "eclipse-temurin:8-jre-jammy"),
            ("1.17.1", 16, 17, "eclipse-temurin:17-jre-jammy"),
            ("1.18", 17, 17, "eclipse-temurin:17-jre-jammy"),
            ("1.20.4", 17, 17, "eclipse-temurin:17-jre-jammy"),
            ("1.20.5", 21, 21, "eclipse-temurin:21-jre-jammy"),
            ("1.21.11", 21, 21, "eclipse-temurin:21-jre-jammy"),
            ("26.1", 25, 25, "eclipse-temurin:25-jre"),
            ("26.2.1", 25, 25, "eclipse-temurin:25-jre"),
        ],
    )
    def test_contiguous_table_and_temurin_mapping(
        self,
        mc: str,
        expected_major: int,
        expected_tag: int,
        expected_image: str,
    ) -> None:
        major = resolve_java_floor_from_mc_version(mc)
        assert major == expected_major
        assert map_java_major_to_temurin_tag(major) == expected_tag
        assert temurin_docker_image_for_java_major(major) == expected_image
        assert resolve_docker_image(minecraft_version=mc) == expected_image

    @pytest.mark.asyncio
    async def test_metadata_sources_and_fabric_ignored(self) -> None:
        assert (
            await resolve_java_major(
                "1.21.4",
                mojang_version_json={"javaVersion": {"majorVersion": 21}},
            )
            == 21
        )
        assert (
            await resolve_java_major(
                "26.1",
                loader_id="paper",
                paper_version_json={"version": {"java": {"version": {"minimum": 25}}}},
            )
            == 25
        )
        # Fabric launcherMeta.min_java_version (often stale, e.g. 8) is never consulted.
        assert await resolve_java_major("1.21.1", loader_id="fabric", fetch_remote=False) == 21

    @pytest.mark.asyncio
    async def test_fetch_remote_uses_allowlisted_downloader_and_falls_back(self) -> None:
        manifest = json.dumps(
            {"versions": [{"id": "1.21.4", "url": "https://piston-meta.mojang.com/v1/1.21.4.json"}]}
        ).encode("utf-8")
        version_doc = json.dumps({"javaVersion": {"majorVersion": 21}}).encode("utf-8")

        with patch(
            "app.modules.versioning.infrastructure.java_floor.download_verified_bytes",
            new=AsyncMock(side_effect=[(manifest, None), (version_doc, None)]),
        ):
            assert await resolve_java_major("1.21.4", fetch_remote=True) == 21

        with patch(
            "app.modules.versioning.infrastructure.java_floor.download_verified_bytes",
            new=AsyncMock(
                return_value=(
                    json.dumps({"version": {"java": {"version": {"minimum": 25}}}}).encode("utf-8"),
                    None,
                )
            ),
        ):
            assert await resolve_java_major("26.1", loader_id="paper", fetch_remote=True) == 25

        with patch(
            "app.modules.versioning.infrastructure.java_floor.download_verified_bytes",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ):
            assert await resolve_java_major("1.20.5", loader_id="paper", fetch_remote=True) == 21

    def test_resolve_docker_image_overrides(self) -> None:
        assert (
            resolve_docker_image(
                config={"image": "custom/jre:21", "java_major": 8},
                minecraft_version="26.1",
            )
            == "custom/jre:21"
        )
        assert (
            resolve_docker_image(
                config={"java_major": 25},
                minecraft_version="1.20.4",
            )
            == "eclipse-temurin:25-jre"
        )
