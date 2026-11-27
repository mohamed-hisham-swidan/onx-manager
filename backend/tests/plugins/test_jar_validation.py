from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import traceback
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import InvalidJarError
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.core.security import generate_api_key, hash_api_key, hash_password
from app.modules.auth.infrastructure.models import ApiKeyModel, RoleModel, UserModel, UserRoleModel
from app.modules.plugin.infrastructure.jar_metadata_parser import (
    parse_jar_metadata,
    parse_jar_version,
    validate_addon_jar,
)
from app.modules.server.application.services.jar_service import validate_jar
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21, parse_lockfile
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.compatibility import (
    PLACEHOLDER_ARTIFACT,
    VerificationMode,
    is_fakeplayer_artifact_usable,
    resolve_verification_strategy,
)
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.plugin_artifact import (
    GITHUB_LATEST_RELEASE_URL,
    MAX_PLUGIN_ARTIFACT_SIZE_BYTES,
    ArtifactFailure,
    ReleaseAsset,
    clear_release_cache,
    ensure_plugin_artifact,
    fetch_release_metadata,
    stage_plugin_artifact,
)
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_env import resolve_test_docker_image
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestSpec,
)
from tests.helpers import build_test_app

TEST_JAR_DIGEST = "8de459b662d5598687fa177e6962ea98782a210ee4be17cf49f3e49830509618"


def _make_jar_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("utf-8") if isinstance(content, str) else content)
    return buf.getvalue()


def _write_jar(path: Path, files: dict[str, str | bytes]) -> None:
    path.write_bytes(_make_jar_bytes(files))


def _make_dummy_jar(path: Path, content: bytes = b"dummy content") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        zf.writestr("payload.dat", content * 100 + b"0" * (1024 * 1024 + 1024))
    data = path.read_bytes()
    assert len(data) >= 1048576
    validate_jar(str(path))
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestJarMetadataParser:
    @pytest.mark.parametrize(
        ("files", "expected_version"),
        [
            ({"plugin.yml": "name: TestPlugin\nversion: 1.4.2\n"}, "1.4.2"),
            ({"paper-plugin.yml": "name: PaperPlugin\nversion: 2.0.0-rc1\n"}, "2.0.0-rc1"),
            ({"fabric.mod.json": '{"id": "test", "version": "0.15.0+1.20"}'}, "0.15.0+1.20"),
            ({"quilt.mod.json": '{"id": "quilt_test", "version": "1.0.1"}'}, "1.0.1"),
            ({"META-INF/mods.toml": '[[mods]]\nmodId = "testmod"\nversion = "2.1.0"\n'}, "2.1.0"),
            (
                {
                    "META-INF/mods.toml": (
                        '[[mods]]\nmodId = "testmod"\nversion = "${file.jarVersion}"\n'
                    ),
                    "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 3.4.5\n",
                },
                "3.4.5",
            ),
            (
                {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 5.6.7\n"},
                "5.6.7",
            ),
            ({"mcmod.info": '[{"modid": "legacy", "version": "1.7.10-1.0"}]'}, "1.7.10-1.0"),
            ({"some_other_file.txt": "hello"}, None),
        ],
    )
    def test_parse_jar_version_descriptors(
        self, tmp_path: Path, files: dict[str, str], expected_version: str | None
    ) -> None:
        jar = tmp_path / "test.jar"
        _write_jar(jar, files)
        assert parse_jar_version(str(jar)) == expected_version

    def test_corrupted_jar_handling(self, tmp_path: Path) -> None:
        bad_jar = tmp_path / "corrupt.jar"
        bad_jar.write_bytes(b"not a real zip file")
        assert parse_jar_version(str(bad_jar)) is None
        with pytest.raises(InvalidJarError):
            parse_jar_metadata(str(bad_jar))
        with pytest.raises(InvalidJarError):
            parse_jar_metadata(b"raw non-zip bytes")

    def test_parse_fabric_forge_and_neoforge_metadata(self, tmp_path: Path) -> None:
        fab = tmp_path / "sodium.jar"
        _write_jar(
            fab,
            {
                "fabric.mod.json": (
                    '{"id": "sodium", "name": "Sodium", "version": "0.5.8", '
                    '"environment": "client", "authors": ["jellysquid3"], '
                    '"contact": {"homepage": "https://modrinth.com/mod/sodium"}, '
                    '"depends": {"fabricloader": ">=0.15.0", "minecraft": "~1.20.4"}}'
                )
            },
        )
        fab_meta = parse_jar_metadata(str(fab))
        assert fab_meta.mod_id == "sodium"
        assert fab_meta.loader == "fabric"
        assert fab_meta.is_client_only is True
        assert fab_meta.warning and "Client-only mod detected" in fab_meta.warning
        assert {"fabricloader", "minecraft"}.issubset(fab_meta.dependencies)

        forge = tmp_path / "jei.jar"
        _write_jar(
            forge,
            {
                "META-INF/mods.toml": (
                    '[[mods]]\nmodId = "jei"\ndisplayName = "Just Enough Items"\n'
                    'version = "15.3.0.4"\nauthors = "mezz"\n'
                    'displayURL = "https://curseforge.com/minecraft/mc-mods/jei"\n'
                    '[[dependencies.jei]]\nmodId = "forge"\nmandatory = true\n'
                )
            },
        )
        forge_meta = parse_jar_metadata(str(forge))
        assert forge_meta.mod_id == "jei" and forge_meta.loader == "forge"
        assert "forge" in forge_meta.dependencies

        neo = tmp_path / "neo.jar"
        _write_jar(
            neo,
            {
                "META-INF/neoforge.mods.toml": (
                    '[[mods]]\nmodId = "neomod"\ndisplayName = "Neo Mod"\n'
                    'version = "1.0.0"\nclientSideOnly = true\n'
                )
            },
        )
        neo_meta = parse_jar_metadata(str(neo))
        assert neo_meta.loader == "neoforge" and neo_meta.is_client_only is True

    def test_universal_multiloader_quilt_and_paper_deps(self, tmp_path: Path) -> None:
        univ = tmp_path / "universal.jar"
        _write_jar(
            univ,
            {
                "fabric.mod.json": '{"id": "chunky", "name": "Chunky", "version": "1.4.0"}',
                "plugin.yml": "name: Chunky\nversion: 1.4.0\nmain: org.popcraft.chunky.ChunkyBukkit\n",
            },
        )
        assert parse_jar_metadata(str(univ)).loader == "fabric"
        assert parse_jar_metadata(str(univ), preferred_server_type="paper").loader == "bukkit"

        proxy_bytes = _make_jar_bytes(
            {
                "plugin.yml": "name: UniversalPlugin\nversion: 1.0.0\n",
                "velocity-plugin.json": json.dumps(
                    {"id": "universal", "name": "UniversalPlugin", "version": "1.0.0"}
                ),
            }
        )
        assert (
            validate_addon_jar("Universal.jar", proxy_bytes, server_type="velocity").loader
            == "velocity"
        )

        mod_bytes = _make_jar_bytes(
            {
                "fabric.mod.json": json.dumps({"id": "mymod", "name": "MyMod", "version": "1.0.0"}),
                "META-INF/neoforge.mods.toml": (
                    '[[mods]]\nmodId="mymod"\nversion="1.0.0"\ndisplayName="MyMod"\n'
                ),
            }
        )
        assert (
            validate_addon_jar("MyMod.jar", mod_bytes, server_type="neoforge").loader == "neoforge"
        )

        quilt_bytes = _make_jar_bytes(
            {
                "quilt.mod.json": json.dumps(
                    {
                        "schema_version": 1,
                        "quilt_loader": {
                            "id": "qmod",
                            "version": "2.0.0",
                            "metadata": {"name": "QuiltMod"},
                        },
                    }
                )
            }
        )
        meta_q = validate_addon_jar("QuiltMod.jar", quilt_bytes, server_type="quilt")
        assert meta_q.loader == "quilt" and meta_q.mod_id == "qmod"

        paper_bytes = _make_jar_bytes(
            {
                "paper-plugin.yml": (
                    "name: PaperPlugin\nversion: 1.0.0\n"
                    "dependencies:\n  server:\n    Vault:\n      required: true\n"
                    "    OptDep:\n      required: false\n"
                )
            }
        )
        assert validate_addon_jar(
            "PaperPlugin.jar", paper_bytes, server_type="paper"
        ).dependencies == ["Vault"]


async def _seed_admin_header() -> dict[str, str]:
    raw_key = generate_api_key()
    async with database._session_factory() as session:
        session.add(
            RoleModel(
                id="r-jar-admin",
                name="admin",
                description="Admin",
                permissions='["admin:full"]',
            )
        )
        session.add(
            UserModel(
                id="u-jar-admin",
                username="jaradmin",
                email="jaradmin@test.local",
                password_hash=hash_password("AdminPass123!"),
                display_name="Jar Admin",
                is_active=True,
                all_servers_access=True,
            )
        )
        await session.flush()
        session.add(UserRoleModel(user_id="u-jar-admin", role_id="r-jar-admin"))
        session.add(
            ApiKeyModel(
                id="ak-jar-admin",
                user_id="u-jar-admin",
                name="jar-admin-key",
                prefix=raw_key[:8],
                key_hash=hash_api_key(raw_key),
                permissions="admin:full",
                is_revoked=False,
            )
        )
        await session.commit()
    return {"Authorization": f"Bearer {raw_key}"}


async def _seed_server(server_id: str, root: Path, *, mode: str = "simple") -> None:
    async with database._session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name="Plugin Upload Test Server",
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=25565,
                java_args="-Xmx1G",
                mode=mode,
            )
        )
        await session.commit()


class TestPluginJarUploadAPI:
    async def test_simple_plugin_upload_validates_descriptors_and_rejects_bad_jars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
        monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
        app, _, _, _ = build_test_app()

        root = tmp_path / "simple-jar-srv"
        root.mkdir(parents=True)
        await _seed_server("srv-simple-jar", root, mode="simple")
        header = await _seed_admin_header()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for fname, payload in (
                ("not-a-jar.txt", b"hello"),
                ("fake.jar", b"plain text not zip"),
                (
                    "nodesc.jar",
                    _make_jar_bytes({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\n"}),
                ),
                (
                    "velocity.jar",
                    _make_jar_bytes(
                        {
                            "velocity-plugin.json": json.dumps(
                                {"id": "vel", "name": "Vel", "version": "3.1.0"}
                            )
                        }
                    ),
                ),
            ):
                resp = await client.post(
                    "/api/v1/servers/srv-simple-jar/plugins/upload",
                    files={"file": (fname, io.BytesIO(payload), "application/java-archive")},
                    headers=header,
                )
                assert resp.status_code == 422
                assert resp.json()["code"] == "INVALID_PLUGIN_JAR"
                assert not (root / "plugins" / fname).exists()

            for fname, files, expected_loader in (
                (
                    "bukkit-plugin.jar",
                    {"plugin.yml": "name: BukkitTest\nversion: 1.0.0\nmain: com.example.Main\n"},
                    "bukkit",
                ),
                (
                    "paper-plugin.jar",
                    {
                        "paper-plugin.yml": "name: PaperTest\nversion: 2.0.0\nmain: com.example.Paper\n"
                    },
                    "paper",
                ),
            ):
                ok_resp = await client.post(
                    "/api/v1/servers/srv-simple-jar/plugins/upload",
                    files={
                        "file": (
                            fname,
                            io.BytesIO(_make_jar_bytes(files)),
                            "application/java-archive",
                        )
                    },
                    headers=header,
                )
                assert ok_resp.status_code == 201
                assert ok_resp.json()["loader"] == expected_loader
                assert (root / "plugins" / fname).is_file()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX-only Git branch/worktree API tests")
    async def test_advanced_branch_plugin_upload_validates_and_ingests_to_cas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
        monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
        app, _, _, _ = build_test_app()

        root = tmp_path / "adv-jar-srv"
        root.mkdir(parents=True)
        (root / "server.properties").write_text("motd=Hello\nserver-port=25565\n", encoding="utf-8")
        await _seed_server("srv-adv-jar", root, mode="advanced")

        layout = ensure_host_state_layout()
        lockfile = LockfileV21(
            format=2,
            mc="1.20.4",
            loader=LoaderRef(id="paper", version="499"),
            base_overrides={},
            files=(),
        )
        GitRepositoryService(layout).initialize("srv-adv-jar", root, lockfile)
        GitBranchService(layout).create_branch("srv-adv-jar", root, "dev")
        header = await _seed_admin_header()

        valid_jar = _make_jar_bytes(
            {"paper-plugin.yml": "name: BranchPaperPlugin\nversion: 1.2.3\nmain: com.ex.Main\n"}
        )
        bad_jar = _make_jar_bytes({"readme.txt": "not a plugin"})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            main_resp = await client.post(
                "/api/v1/servers/srv-adv-jar/plugins/upload",
                params={"branch": "main"},
                files={
                    "file": (
                        "BranchPaperPlugin.jar",
                        io.BytesIO(valid_jar),
                        "application/java-archive",
                    )
                },
                headers=header,
            )
            assert main_resp.status_code == 409

            bad_resp = await client.post(
                "/api/v1/servers/srv-adv-jar/plugins/upload",
                params={"branch": "dev"},
                files={"file": ("Invalid.jar", io.BytesIO(bad_jar), "application/java-archive")},
                headers=header,
            )
            assert bad_resp.status_code == 422
            dev_lock_path = root / ".onx" / "worktrees" / "dev" / "onx-jars.lock.json"
            assert len(parse_lockfile(dev_lock_path.read_bytes()).files) == 0

            ok_resp = await client.post(
                "/api/v1/servers/srv-adv-jar/plugins/upload",
                params={"branch": "dev"},
                files={
                    "file": (
                        "BranchPaperPlugin.jar",
                        io.BytesIO(valid_jar),
                        "application/java-archive",
                    )
                },
                headers=header,
            )
            assert ok_resp.status_code == 201
            payload = ok_resp.json()
            assert payload["name"] == "BranchPaperPlugin"
            assert payload["loader"] == "paper"
            assert ArtifactCas(layout.cas).has(payload["checksum"])
            assert [f.path for f in parse_lockfile(dev_lock_path.read_bytes()).files] == [
                "plugins/BranchPaperPlugin.jar"
            ]
            assert not (root / "plugins" / "BranchPaperPlugin.jar").exists()


class _MockResponseContext:
    def __init__(
        self, status: int, headers: dict[str, str] | None = None, data: bytes = b""
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._data = data
        self.read_called = False

    @property
    def content(self):
        ctx = self

        class _Reader:
            async def read(self, _n: int = -1):
                if ctx.read_called:
                    return b""
                ctx.read_called = True
                return ctx._data

        return _Reader()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass


class _SingleReadContent:
    def __init__(self, data: bytes, delay: float = 0.0) -> None:
        self._data = data
        self._delay = delay

    async def read(self, _n: int = -1) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        data, self._data = self._data, b""
        return data


def _mock_json_session(payload: object = None, status: int = 200, headers: dict | None = None):
    resp = AsyncMock(status=status, headers=headers or {}, json=AsyncMock(return_value=payload))
    cm = AsyncMock(__aenter__=AsyncMock(return_value=resp))
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = cm
    return session


def _mock_stream_session(data: bytes, *, delay: float = 0.0):
    def make_cm(*_args, **_kwargs):
        resp = AsyncMock(status=200, headers={}, content=_SingleReadContent(data, delay=delay))
        return AsyncMock(__aenter__=AsyncMock(return_value=resp))

    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = make_cm
    return session


def _setup_test_spec(tmp_path: Path, test_id: str = "t-fp-fix2b") -> tuple[TestSpec, Path]:
    server_dir = tmp_path / "server"
    server_dir.mkdir(parents=True, exist_ok=True)
    commit = ServerCommit(
        id=f"c-{test_id}",
        server_id="srv-fix2b",
        message="test commit",
        manifest=CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "server-port=25565\n"},
        ),
    )
    spec = TestSpec(
        test_id=test_id,
        server_id="srv-fix2b",
        server_dir=str(server_dir),
        commit=commit,
        bot_config=BotVerificationConfig(bot_count=5, bot_tech=BotTech.FAKEPLAYER_NEXT),
    )
    return spec, server_dir / ".onx" / "tests" / test_id


class TestPluginArtifactVerification:
    async def test_fetch_release_metadata_happy_path_and_ttl_cache(self) -> None:
        clear_release_cache()
        payload = {
            "tag_name": "v0.4.4",
            "assets": [
                {
                    "name": "fakeplayer-0.4.4.jar",
                    "browser_download_url": (
                        "https://github.com/yigemingzii/minecraft-fakeplayer-next/"
                        "releases/download/v0.4.4/fakeplayer-0.4.4.jar"
                    ),
                    "size": 1848353,
                    "digest": f"sha256:{TEST_JAR_DIGEST}",
                }
            ],
        }
        session = _mock_json_session(payload)
        asset = await fetch_release_metadata(session=session)
        assert isinstance(asset, ReleaseAsset)
        assert asset.name == "fakeplayer-0.4.4.jar"
        assert asset.sha256 == TEST_JAR_DIGEST
        assert asset.version_label == "0.4.4"

        cached = await fetch_release_metadata(session=session)
        assert isinstance(cached, ReleaseAsset)
        assert session.get.call_count == 1

    async def test_fetch_release_metadata_asset_count_failures(self) -> None:
        for assets in (
            [
                {
                    "name": "fakeplayer-0.4.4.jar",
                    "browser_download_url": "https://github.com/fake1.jar",
                    "size": 1000,
                    "digest": f"sha256:{TEST_JAR_DIGEST}",
                },
                {
                    "name": "fakeplayer-0.4.4-all.jar",
                    "browser_download_url": "https://github.com/fake2.jar",
                    "size": 2000,
                    "digest": f"sha256:{TEST_JAR_DIGEST}",
                },
            ],
            [
                {
                    "name": "source.zip",
                    "browser_download_url": "https://github.com/source.zip",
                    "size": 1000,
                }
            ],
        ):
            clear_release_cache()
            res = await fetch_release_metadata(
                session=_mock_json_session({"tag_name": "v0.4.4", "assets": assets})
            )
            assert isinstance(res, ArtifactFailure)
            assert "no unique fakeplayer jar asset" in res.reason

    async def test_ensure_plugin_artifact_cache_hit_corrupt_repair_and_concurrency(
        self, tmp_path: Path
    ) -> None:
        jar_bytes = _make_dummy_jar(tmp_path / "source.jar", b"content-miss")
        digest = _sha256(jar_bytes)
        asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://github.com/yigemingzii/releases/fakeplayer.jar",
            sha256=digest,
            size=len(jar_bytes),
            version_label="0.4.4",
        )
        session = _mock_stream_session(jar_bytes)
        cached_path = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=session)
        assert isinstance(cached_path, Path) and cached_path.exists()
        assert session.get.call_count == 1

        session.get.reset_mock()
        assert (
            await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=session)
            == cached_path
        )
        assert session.get.call_count == 0

        # Poison cache -> re-downloads
        cached_path.write_bytes(b"corrupted-data")
        repaired = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=session)
        assert isinstance(repaired, Path) and repaired.read_bytes() == jar_bytes

        # Concurrent downloads leave no .part files
        conc_dir = tmp_path / "conc"
        conc_session = _mock_stream_session(jar_bytes, delay=0.01)
        r1, r2 = await asyncio.gather(
            ensure_plugin_artifact(data_root=conc_dir, asset=asset, session=conc_session),
            ensure_plugin_artifact(data_root=conc_dir, asset=asset, session=conc_session),
        )
        assert isinstance(r1, Path) and isinstance(r2, Path)
        assert list(conc_dir.glob("**/*.part")) == []

    async def test_ensure_plugin_artifact_validates_jar_and_cleans_part(
        self, tmp_path: Path
    ) -> None:
        bad_bytes = b"PK\x03\x04fakeplayer-placeholder-too"
        bad_asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://github.com/fakeplayer.jar",
            sha256=_sha256(bad_bytes),
            size=len(bad_bytes),
            version_label="0.4.4",
        )
        res = await ensure_plugin_artifact(
            data_root=tmp_path, asset=bad_asset, session=_mock_stream_session(bad_bytes)
        )
        assert isinstance(res, ArtifactFailure) and "invalid jar" in res.reason
        assert list(tmp_path.glob("**/*.part")) == []

    async def test_ensure_plugin_artifact_allowed_redirects_and_200(self, tmp_path: Path) -> None:
        jar_bytes = _make_dummy_jar(tmp_path / "source.jar", b"content-redirect")
        digest = _sha256(jar_bytes)

        for idx, (start_url, redirect_url, expected_url) in enumerate(
            [
                (
                    "https://github.com/yigemingzii/releases/download/v0.4.4/fakeplayer-0.4.4.jar",
                    "https://release-assets.githubusercontent.com/123/uuid?sig=S3CR3T&jwt=S3CR3T",
                    "https://release-assets.githubusercontent.com/123/uuid?sig=S3CR3T&jwt=S3CR3T",
                ),
                (
                    "https://github.com/fakeplayer.jar",
                    "https://release-assets.githubusercontent.com:443/fakeplayer.jar?sig=S3CR3T",
                    "https://release-assets.githubusercontent.com:443/fakeplayer.jar?sig=S3CR3T",
                ),
                (
                    "https://github.com/release/download",
                    "/downloads/fakeplayer-0.4.4.jar?sig=S3CR3T",
                    "https://github.com/downloads/fakeplayer-0.4.4.jar?sig=S3CR3T",
                ),
            ]
        ):
            asset = ReleaseAsset(
                name="fakeplayer-0.4.4.jar",
                download_url=start_url,
                sha256=digest,
                size=len(jar_bytes),
                version_label="0.4.4",
            )

            def mock_get(
                url: str,
                _start: str = start_url,
                _redir: str = redirect_url,
                _exp: str = expected_url,
                **_kwargs: object,
            ):
                if url == _start:
                    return _MockResponseContext(302, {"Location": _redir})
                if url == _exp:
                    return _MockResponseContext(200, data=jar_bytes)
                raise ValueError(f"Unexpected url: {url}")

            session = MagicMock(spec=aiohttp.ClientSession)
            session.get.side_effect = mock_get
            res = await ensure_plugin_artifact(
                data_root=tmp_path / f"case-{idx}", asset=asset, session=session
            )
            assert isinstance(res, Path) and res.read_bytes() == jar_bytes

    @pytest.mark.parametrize(
        ("redirect_url", "expected_reason"),
        [
            (
                "https://evil.example/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T",
                "download redirect host not allowed: evil.example",
            ),
            (
                "http://release-assets.githubusercontent.com/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T",
                None,
            ),
            (
                "https://github.com.evil.example/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T",
                "download redirect host not allowed: github.com.evil.example",
            ),
            (
                "https://user@release-assets.githubusercontent.com/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T",
                None,
            ),
            (
                "https://release-assets.githubusercontent.com:8443/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T",
                None,
            ),
        ],
    )
    async def test_redirect_blocks_untrusted_targets_and_redacts_secrets(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        redirect_url: str,
        expected_reason: str | None,
    ) -> None:
        jar_bytes = _make_dummy_jar(tmp_path / "source.jar", b"content-redir")
        asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://github.com/fakeplayer.jar",
            sha256=_sha256(jar_bytes),
            size=len(jar_bytes),
            version_label="0.4.4",
        )
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.side_effect = lambda *_args, **_kw: _MockResponseContext(
            302, {"Location": redirect_url}
        )

        with caplog.at_level("DEBUG"):
            res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=session)

        assert isinstance(res, ArtifactFailure)
        if expected_reason is not None:
            assert res.reason == expected_reason
        for tok in ("sig=", "jwt=", "?"):
            assert tok not in res.reason
        assert "S3CR3T" not in caplog.text

    @pytest.mark.parametrize(
        "case",
        [
            "no digest",
            "malformed digest",
            "404",
            "403",
            "429",
            "500",
            "network error",
            "timeout",
            "invalid JSON",
            "metadata redirect",
            "digest mismatch",
            "size cap",
            "host not allowed",
            "too many redirects",
            "no location",
            "unsupported 3xx",
        ],
    )
    async def test_artifact_failure_matrix_never_leaks_urls_or_secrets(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str
    ) -> None:
        clear_release_cache()
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        jar_bytes = _make_dummy_jar(tmp_path / "source.jar", b"matrix-dummy")
        digest = _sha256(jar_bytes)
        secret_url = "https://github.com/fakeplayer.jar?token=SECRET&sig=S3CR3T&jwt=JWT_TOKEN"
        asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://github.com/fakeplayer.jar",
            sha256=digest,
            size=len(jar_bytes),
            version_label="0.4.4",
        )

        if case == "no digest":
            mock_session = _mock_json_session(
                {
                    "tag_name": "v0.4.4",
                    "assets": [
                        {
                            "name": "fakeplayer-0.4.4.jar",
                            "browser_download_url": secret_url,
                            "size": 100,
                        }
                    ],
                }
            )
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "malformed digest":
            mock_session = _mock_json_session(
                {
                    "tag_name": "v0.4.4",
                    "assets": [
                        {
                            "name": "fakeplayer-0.4.4.jar",
                            "browser_download_url": secret_url,
                            "size": 100,
                            "digest": "invalid",
                        }
                    ],
                }
            )
            failure = await fetch_release_metadata(session=mock_session)
        elif case in ("404", "403", "429", "500"):
            mock_session = _mock_json_session(status=int(case))
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "network error":
            mock_session.get.side_effect = aiohttp.ClientConnectionError("Connection failed")
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "timeout":
            mock_session.get.side_effect = TimeoutError()
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "invalid JSON":
            r = AsyncMock(status=200, json=AsyncMock(side_effect=ValueError("bad json")))
            mock_session.get.return_value = AsyncMock(__aenter__=AsyncMock(return_value=r))
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "metadata redirect":
            mock_session = _mock_json_session(
                status=302, headers={"Location": "https://api.github.com/other?token=SECRET"}
            )
            failure = await fetch_release_metadata(session=mock_session)
        elif case == "digest mismatch":
            mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(
                200, data=b"wrong"
            )
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=asset, session=mock_session
            )
            assert list(tmp_path.glob("**/*.part")) == []
        elif case == "size cap":
            large = ReleaseAsset(
                name="fakeplayer-0.4.4.jar",
                download_url="https://github.com/fakeplayer.jar",
                sha256=digest,
                size=MAX_PLUGIN_ARTIFACT_SIZE_BYTES + 1,
                version_label="0.4.4",
            )
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=large, session=mock_session
            )
            assert mock_session.get.call_count == 0
        elif case == "host not allowed":
            bad = ReleaseAsset(
                name="fakeplayer-0.4.4.jar",
                download_url="https://evil.example.com/fakeplayer.jar?token=SECRET&sig=S3CR3T",
                sha256=digest,
                size=100,
                version_label="0.4.4",
            )
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=bad, session=mock_session
            )
            assert mock_session.get.call_count == 0
        elif case == "too many redirects":
            mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(
                302, {"Location": "https://github.com/redir"}
            )
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=asset, session=mock_session
            )
        elif case == "no location":
            mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(302, {})
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=asset, session=mock_session
            )
        else:
            mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(
                300, {"Location": "https://github.com/other"}
            )
            failure = await ensure_plugin_artifact(
                data_root=tmp_path, asset=asset, session=mock_session
            )

        with caplog.at_level("DEBUG"):
            assert isinstance(failure, ArtifactFailure)
            assert failure.details is None or "http" not in failure.details.lower()
            for tok in ("http://", "https://", "sig=", "jwt=", "?", "SECRET", "S3CR3T"):
                assert tok not in repr(failure)
                assert tok not in str(failure)
                assert tok not in caplog.text

    def test_stage_plugin_artifact_sanitization_and_pinned_behaviors(self, tmp_path: Path) -> None:
        cache_jar = tmp_path / "artifacts" / "fakeplayer.jar"
        _make_dummy_jar(cache_jar, b"real-jar-bits")
        test_dir = tmp_path / "test_dir"
        plugins_dir = test_dir / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "fakeplayer-old-stale.jar").write_bytes(b"old")
        (plugins_dir / "EssentialsX-2.20.1.jar").write_bytes(b"keep-me")

        staged = stage_plugin_artifact(
            cached=cache_jar,
            test_dir=test_dir,
            version_label="0.4.4",
            asset_name="../../fake player 0.4.4.jar",
        )
        assert staged.exists()
        assert list(plugins_dir.glob("fakeplayer*.jar")) == [staged]
        assert (plugins_dir / "EssentialsX-2.20.1.jar").exists()

        for raw_name in (
            "../x.jar",
            r"..\x.jar",
            "/etc/passwd.jar",
            "a b.jar",
            "плагин-é.jar",
            "a" * 300 + ".jar",
            "myplugin",
            "bad\x00\x07name.jar",
            "",
            ".jar",
            "   ",
            "...jar",
        ):
            s = stage_plugin_artifact(
                cached=cache_jar,
                test_dir=tmp_path / "san",
                version_label="0.4.4",
                asset_name=raw_name,
            )
            assert s.resolve().parent == (tmp_path / "san" / "plugins").resolve()
            assert re.match(r"^[A-Za-z0-9._-]+\.jar$", s.name)
            assert len(s.name) <= 100 and not s.name.startswith(".")

        pinned_dir = tmp_path / "pinned"
        assert stage_plugin_artifact(
            cached=cache_jar, test_dir=pinned_dir, asset_name="x.jar"
        ).name == ("fakeplayer-x.jar")
        assert (
            stage_plugin_artifact(
                cached=cache_jar, test_dir=pinned_dir, asset_name="плагин.jar"
            ).name
            == "fakeplayer.jar"
        )
        capped = stage_plugin_artifact(
            cached=cache_jar, test_dir=pinned_dir, asset_name="a" * 300 + ".jar"
        )
        assert len(capped.name) == 100 and capped.name.endswith(".jar")

    async def test_runner_artifact_failure_downgrades_and_success_stages(
        self, tmp_path: Path
    ) -> None:
        # 1. Artifact failure downgrades to SMOKE_TEST
        runner_fail = DockerTestExecutionRunner()
        spec_fail, test_dir_fail = _setup_test_spec(tmp_path / "fail", test_id="t-fail")
        docker_env_fail: dict[str, str] = {}
        docker_cmd_fail: list[str] = []

        def mock_sub_fail(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "docker" in cmd and "run" in cmd:
                docker_cmd_fail.extend(cmd)
                for i, arg in enumerate(cmd):
                    if arg == "-e" and i + 1 < len(cmd):
                        k, _, v = cmd[i + 1].partition("=")
                        docker_env_fail[k] = v
                for k in kwargs.get("env") or {}:
                    if k.startswith("RCON_"):
                        docker_env_fail[f"PROC_{k}"] = "1"
                logs_dir = test_dir_fail / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (logs_dir / "latest.log").write_text(
                    "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n", encoding="utf-8"
                )
                return MagicMock(returncode=0, stdout="container-123\n", stderr="")
            if "inspect" in cmd_str:
                if "{{.State.Running}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                if "{{range .NetworkSettings.Networks}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
                return MagicMock(
                    returncode=0,
                    stdout='[{"State": {"ExitCode": 0, "OOMKilled": false}}]\n',
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="ok\n", stderr="")

        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=mock_sub_fail),
            patch(
                "app.modules.versioning.infrastructure.plugin_artifact.ensure_plugin_artifact",
                AsyncMock(return_value=ArtifactFailure("release asset has no digest")),
            ),
            patch.object(
                runner_fail, "_persist_test_outcome", new_callable=AsyncMock
            ) as mock_persist,
        ):
            handle = await runner_fail.run_test(spec_fail)
            res = await handle.wait_for_completion()

        assert res is not None
        assert (
            res.failure_reason
            == "pre-launch step failed: artifact staging/check: release asset has no digest"
        )
        assert "MODRINTH_PROJECTS" not in docker_env_fail
        assert not any(k.startswith(("RCON_", "PROC_RCON_")) for k in docker_env_fail)
        expected_img, _ = resolve_test_docker_image(minecraft_version="1.21.1", strategy=None)
        assert any(expected_img in a for a in docker_cmd_fail)
        assert mock_persist.await_args.kwargs["evidence_bundle"]["assertions"][
            "strategy_downgraded_from"
        ] == ("fakeplayer_next")

        # 2. Artifact success keeps FULL_BOT and stages JAR before docker run
        runner_ok = DockerTestExecutionRunner()
        spec_ok, test_dir_ok = _setup_test_spec(tmp_path / "ok", test_id="t-ok")
        cached_jar = tmp_path / "cached_fakeplayer.jar"
        _make_dummy_jar(cached_jar, b"verified-real-plugin")
        jar_present = False
        docker_env_ok: dict[str, str] = {}

        def mock_sub_ok(cmd, **_kwargs):
            nonlocal jar_present
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "docker" in cmd and "run" in cmd:
                for i, arg in enumerate(cmd):
                    if arg == "-e" and i + 1 < len(cmd):
                        k, _, v = cmd[i + 1].partition("=")
                        docker_env_ok[k] = v
                jar_present = bool(list((test_dir_ok / "plugins").glob("fakeplayer*.jar")))
                logs_dir = test_dir_ok / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (logs_dir / "latest.log").write_text(
                    "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n"
                    "[fakeplayer] Enabling fakeplayer v0.4.4\n"
                    "[fakeplayer] Enabled in 15296 ms\n",
                    encoding="utf-8",
                )
                return MagicMock(returncode=0, stdout="container-123\n", stderr="")
            if "inspect" in cmd_str:
                if "{{.State.Running}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                if "{{range .NetworkSettings.Networks}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
                return MagicMock(
                    returncode=0,
                    stdout='[{"State": {"ExitCode": 0, "OOMKilled": false}}]\n',
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="OK\n", stderr="")

        strats: list = []
        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=mock_sub_ok),
            patch(
                "app.modules.versioning.infrastructure.test_runner.resolve_verification_strategy",
                side_effect=lambda *a, **kw: (
                    s := resolve_verification_strategy(*a, **kw),
                    strats.append(s),
                )[0],
            ),
            patch(
                "app.modules.versioning.infrastructure.plugin_artifact.ensure_plugin_artifact",
                AsyncMock(return_value=cached_jar),
            ),
            patch.object(runner_ok, "_persist_test_outcome", new_callable=AsyncMock),
        ):
            res_ok = await (await runner_ok.run_test(spec_ok)).wait_for_completion()

        assert res_ok is not None and res_ok.passed is True
        assert strats[-1].mode == VerificationMode.FULL_BOT
        assert strats[-1].driver == "fakeplayer_next"
        assert jar_present is True
        assert docker_env_ok.get("MODRINTH_PROJECTS") == "commandapi"

    @pytest.mark.parametrize("mode", ["redirect", "network_error"])
    async def test_secret_propagation_redacted_end_to_end(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: str
    ) -> None:
        runner = DockerTestExecutionRunner()
        spec, test_dir = _setup_test_spec(tmp_path / mode, test_id=f"t-sec-{mode}")
        fake_asset_url = "https://github.com/releases/download/v0.4.4/fakeplayer-0.4.4.jar"
        secret_url = "https://evil.example/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"
        meta_payload = {
            "tag_name": "v0.4.4",
            "assets": [
                {
                    "name": "fakeplayer-0.4.4.jar",
                    "browser_download_url": fake_asset_url,
                    "size": 1848353,
                    "digest": f"sha256:{TEST_JAR_DIGEST}",
                }
            ],
        }

        def mock_get(url: str, **_kwargs: object):
            if url == GITHUB_LATEST_RELEASE_URL:
                resp = AsyncMock(status=200, headers={}, json=AsyncMock(return_value=meta_payload))
                return AsyncMock(__aenter__=AsyncMock(return_value=resp))
            if url == fake_asset_url:
                if mode == "redirect":
                    return _MockResponseContext(302, {"Location": secret_url})
                raise aiohttp.ClientConnectionError(f"Cannot connect to host {secret_url}")
            raise ValueError(f"Unexpected URL: {url}")

        def mock_subprocess(cmd, **_kwargs: object):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "docker" in cmd and "run" in cmd:
                logs_dir = test_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (logs_dir / "latest.log").write_text(
                    "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n", encoding="utf-8"
                )
                return MagicMock(returncode=0, stdout="container-123\n", stderr="")
            if "inspect" in cmd_str:
                if "{{.State.Running}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="true\n", stderr="")
                if "{{range .NetworkSettings.Networks}}" in cmd_str:
                    return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
                return MagicMock(
                    returncode=0,
                    stdout='[{"State": {"ExitCode": 0, "OOMKilled": false}}]\n',
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="container-123\n", stderr="")

        captured_failures: list[ArtifactFailure] = []
        captured_excs: list[BaseException] = []
        orig_ensure = ensure_plugin_artifact
        orig_downgrade = runner._downgrade_to_smoke

        async def spied_ensure(*args, **kwargs):
            r = await orig_ensure(*args, **kwargs)
            if isinstance(r, ArtifactFailure):
                captured_failures.append(r)
            return r

        def capture_downgrade(step_name, exc, *args, **kwargs):
            captured_excs.append(exc)
            return orig_downgrade(step_name, exc, *args, **kwargs)

        clear_release_cache()
        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
            patch("subprocess.run", side_effect=mock_subprocess),
            patch("aiohttp.ClientSession.get", side_effect=mock_get),
            patch(
                "app.modules.versioning.infrastructure.plugin_artifact.ensure_plugin_artifact",
                side_effect=spied_ensure,
            ),
            patch.object(runner, "_downgrade_to_smoke", side_effect=capture_downgrade),
            patch.object(runner, "_persist_runtime", new_callable=AsyncMock),
            patch.object(runner, "_persist_test_status", new_callable=AsyncMock),
            patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock) as mock_persist,
            caplog.at_level("DEBUG"),
        ):
            res = await (await runner.run_test(spec)).wait_for_completion()

        assert res is not None and res.failure_reason is not None
        evidence_str = json.dumps(mock_persist.await_args.kwargs.get("evidence_bundle") or {})
        assert len(captured_failures) == 1
        for record in caplog.records:
            if record.exc_info and record.exc_info[1] is not None:
                captured_excs.append(record.exc_info[1])
        assert len(captured_excs) >= 1

        for tok in ("S3CR3T", "sig=", "jwt=", "?"):
            assert tok not in res.failure_reason
            assert tok not in evidence_str
            assert tok not in caplog.text
            assert tok not in str(captured_failures[0])
            assert tok not in repr(captured_failures[0])
            for exc in captured_excs:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                assert tok not in str(exc) and tok not in repr(exc) and tok not in tb

    def test_placeholder_artifact_rejected(self, tmp_path: Path) -> None:
        ph = tmp_path / "fakeplayer-placeholder.jar"
        ph.write_bytes(PLACEHOLDER_ARTIFACT)
        usable, reason = is_fakeplayer_artifact_usable(ph)
        assert usable is False
        assert reason is not None and "placeholder" in reason.lower()
