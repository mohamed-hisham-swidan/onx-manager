"""P5.5-1 encrypted panel secret store and CurseForge adapter tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppSettings
from app.core.exceptions import (
    CorruptedDownloadError,
    CurseForgeApiKeyMissingError,
    DownloadError,
    ManualDownloadRequiredError,
    MasterKekVersionMismatchError,
    NotFoundError,
    SecurityPermissionError,
    UnsupportedForgeVersionError,
    ValidationError,
)
from app.core.persistence.base import Base
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthVersionRecord,
)
from app.modules.versioning.application.modpack_lockfile_builder import (
    build_lockfile_from_install_plan,
)
from app.modules.versioning.domain.lockfile import Origin
from app.modules.versioning.infrastructure import curseforge_adapter
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.curseforge_adapter import (
    download_curseforge_plan_files,
    parse_curseforge_zip,
    resolve_manual_download_upload,
)
from app.modules.versioning.infrastructure.download_allowlist import (
    VerifiedDownloadResult,
)
from app.modules.versioning.infrastructure.modpack_parser import (
    InstallPlan,
    InstallPlanFile,
    ManualDownloadBlocker,
)
from app.modules.versioning.infrastructure.panel_secret_store import (
    CURSEFORGE_API_KEY_NAME,
    ENCRYPTION_MODE_MASTER_KEK,
    ENCRYPTION_MODE_PANEL_LOCAL,
    decrypt_panel_secret,
    delete_panel_secret,
    encrypt_panel_secret,
    get_panel_secret_status,
    make_api_key_hint,
    resolve_curseforge_api_key,
    set_panel_secret,
)

CDN = "https://edge.forgecdn.net/files/1/2/file.jar"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _write_kek(path: Path) -> Path:
    path.write_text("ab" * 32, encoding="ascii")
    os.chmod(path, 0o600)
    return path


def _settings(tmp_path: Path, **kwargs: object) -> AppSettings:
    values = {
        "host_state_dir": str(tmp_path / "host-state"),
        "servers_data_dir": str(tmp_path / "servers"),
    }
    values.update(kwargs)
    return AppSettings(**values)


async def _session_engine(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'secrets.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )


class TestPanelSecretStoreCrypto:
    def test_master_kek_roundtrip_and_aad(self, tmp_path: Path) -> None:
        kek_file = _write_kek(tmp_path / "master.kek")
        settings = _settings(tmp_path, master_kek_file=str(kek_file))
        envelope = encrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, "cf-secret-value", settings=settings
        )
        assert envelope.encryption_mode == ENCRYPTION_MODE_MASTER_KEK
        assert envelope.key_hint == "***...alue"
        assert decrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, envelope, settings=settings
        ) == "cf-secret-value"

        with pytest.raises(MasterKekVersionMismatchError):
            decrypt_panel_secret(
                CURSEFORGE_API_KEY_NAME,
                dataclasses.replace(envelope, kek_version=99),
                settings=settings,
            )

        tampered = dataclasses.replace(
            envelope,
            ciphertext=envelope.ciphertext[:-1] + bytes([envelope.ciphertext[-1] ^ 0x01]),
        )
        with pytest.raises(ValidationError, match="Unable to decrypt"):
            decrypt_panel_secret(CURSEFORGE_API_KEY_NAME, tampered, settings=settings)

    def test_panel_local_key_created_0600_and_fail_closed(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        envelope = encrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, "local-secret", settings=settings
        )
        assert envelope.encryption_mode == ENCRYPTION_MODE_PANEL_LOCAL
        key_path = Path(settings.host_state_dir) / ".onx-integration.key"
        assert key_path.exists()
        if os.name == "posix":
            assert stat.S_IMODE(key_path.stat().st_mode) & 0o077 == 0
        assert decrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, envelope, settings=settings
        ) == "local-secret"

        if os.name == "posix":
            os.chmod(key_path, 0o644)
            with pytest.raises(SecurityPermissionError):
                encrypt_panel_secret(
                    CURSEFORGE_API_KEY_NAME, "another-secret", settings=settings
                )

    def test_api_key_hint_never_leaks_key(self) -> None:
        assert make_api_key_hint("abcdefgh") == "***...efgh"
        assert make_api_key_hint("short") == "***"
        assert "abcdefgh" not in make_api_key_hint("abcdefgh")

    def test_envelope_repr_is_redacted(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        envelope = encrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, "super-secret-key", settings=settings
        )
        assert "super-secret-key" not in repr(envelope)
        assert "***REDACTED***" in repr(envelope)

    def test_appsettings_repr_redacts_curseforge_key(self) -> None:
        settings = AppSettings(curseforge_api_key="super-secret-key")
        assert "super-secret-key" not in repr(settings)

    def test_panel_local_key_non_posix_works_without_fchmod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.versioning.infrastructure import panel_secret_store

        monkeypatch.setattr(panel_secret_store, "_is_posix_host", lambda: False)
        settings = _settings(tmp_path)
        envelope = encrypt_panel_secret(
            CURSEFORGE_API_KEY_NAME, "win-secret", settings=settings
        )
        assert envelope.encryption_mode == ENCRYPTION_MODE_PANEL_LOCAL
        assert (
            decrypt_panel_secret(
                CURSEFORGE_API_KEY_NAME, envelope, settings=settings
            )
            == "win-secret"
        )

class TestPanelSecretStoreDatabase:
    @pytest.mark.asyncio
    async def test_set_status_and_resolve(self, tmp_path: Path) -> None:
        engine, factory = await _session_engine(tmp_path)
        try:
            settings = _settings(tmp_path)
            async with factory() as session:
                status = await set_panel_secret(
                    session,
                    CURSEFORGE_API_KEY_NAME,
                    "panel-secret-1234",
                    settings=settings,
                )
                assert status.configured is True
                assert status.source == "panel"
                assert status.hint == "***...1234"

                fetched = await get_panel_secret_status(
                    session, CURSEFORGE_API_KEY_NAME, settings=settings
                )
                assert fetched.configured is True
                assert fetched.source == "panel"
                assert "panel-secret-1234" not in repr(fetched)

                resolved = await resolve_curseforge_api_key(
                    session, settings=settings
                )
                assert resolved == "panel-secret-1234"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_env_fallback_and_db_precedence(self, tmp_path: Path) -> None:
        engine, factory = await _session_engine(tmp_path)
        try:
            env_settings = _settings(
                tmp_path, curseforge_api_key="env-secret-5678"
            )
            async with factory() as session:
                status = await get_panel_secret_status(
                    session, CURSEFORGE_API_KEY_NAME, settings=env_settings
                )
                assert status.configured is True
                assert status.source == "env"
                assert status.hint == "***...5678"
                assert await resolve_curseforge_api_key(
                    session, settings=env_settings
                ) == "env-secret-5678"

            async with factory() as session:
                await set_panel_secret(
                    session,
                    CURSEFORGE_API_KEY_NAME,
                    "panel-wins-9999",
                    settings=env_settings,
                )
                status = await get_panel_secret_status(
                    session, CURSEFORGE_API_KEY_NAME, settings=env_settings
                )
                assert status.source == "panel"
                assert await resolve_curseforge_api_key(
                    session, settings=env_settings
                ) == "panel-wins-9999"

            async with factory() as session:
                deleted = await delete_panel_secret(session, CURSEFORGE_API_KEY_NAME)
                assert deleted is True
                status = await get_panel_secret_status(
                    session, CURSEFORGE_API_KEY_NAME, settings=env_settings
                )
                assert status.source == "env"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_no_secret_configured(self, tmp_path: Path) -> None:
        engine, factory = await _session_engine(tmp_path)
        try:
            async with factory() as session:
                status = await get_panel_secret_status(
                    session, CURSEFORGE_API_KEY_NAME, settings=_settings(tmp_path)
                )
                assert status.configured is False
                assert status.source == "none"
                assert status.hint is None
                assert await resolve_curseforge_api_key(
                    session, settings=_settings(tmp_path)
                ) is None
        finally:
            await engine.dispose()


class _CfResponse:
    def __init__(self, status: int, payload: object | None = None) -> None:
        self.status = status
        self._payload = payload if payload is not None else {}

    async def __aenter__(self) -> _CfResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def json(self, content_type: str | None = None) -> object:
        del content_type
        return self._payload


class _CfSession:
    def __init__(self, responses: list[_CfResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: object) -> _CfResponse:
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


class _FakeModrinth:
    def __init__(
        self,
        client_only: set[str] | None = None,
        matched: dict[str, ModrinthVersionRecord] | None = None,
    ) -> None:
        self.client_only = client_only or set()
        self.matched = matched or {}

    async def classify_client_only_jars_by_sha512(
        self, hashes: list[str]
    ) -> tuple[set[str], dict, dict]:
        return (self.client_only & set(hashes), self.matched, {})


def _manifest(
    *,
    mc: str = "1.20.1",
    loaders: tuple[str, ...] = ("forge-47.2.0",),
    files: tuple[tuple[int, int, bool], ...] = ((10, 100, True),),
    name: str = "CF Pack",
) -> dict:
    return {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": name,
        "version": "1.0",
        "minecraft": {
            "version": mc,
            "modLoaders": [
                {"id": loader, "primary": index == 0}
                for index, loader in enumerate(loaders)
            ],
        },
        "files": [
            {"projectID": project_id, "fileID": file_id, "required": required}
            for project_id, file_id, required in files
        ],
        "overrides": "overrides",
    }


def _cf_meta(
    file_id: int,
    name: str,
    data: bytes,
    *,
    download_url: str | None = CDN,
) -> dict:
    return {
        "id": file_id,
        "modId": 500,
        "fileName": name,
        "fileLength": len(data),
        "hashes": [{"value": _sha1(data), "algo": 1}],
        "downloadUrl": download_url,
    }


def _write_cf_zip(
    path: Path, manifest: dict, overrides: dict[str, bytes] | None = None
) -> Path:
    entries = {"manifest.json": json.dumps(manifest).encode("utf-8")}
    entries.update(overrides or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def _verified(data: bytes) -> VerifiedDownloadResult:
    return VerifiedDownloadResult(
        sha256=_sha256(data),
        sha512=_sha512(data),
        sha1=_sha1(data),
        size=len(data),
        final_url=CDN,
        redirect_count=0,
    )


class TestCurseForgeParse:
    @pytest.mark.asyncio
    async def test_missing_api_key_is_409(self, tmp_path: Path) -> None:
        archive = _write_cf_zip(tmp_path / "pack.zip", _manifest())
        with pytest.raises(CurseForgeApiKeyMissingError) as exc:
            await parse_curseforge_zip(archive, api_key="   ")
        assert exc.value.http_status == 409
        assert exc.value.http_status != 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_rejected_api_key_is_409(
        self, tmp_path: Path, status: int
    ) -> None:
        archive = _write_cf_zip(tmp_path / "pack.zip", _manifest())
        session = _CfSession([_CfResponse(status)])
        with pytest.raises(CurseForgeApiKeyMissingError) as exc:
            await parse_curseforge_zip(
                archive, api_key="bad-key", cf_http_client=session
            )
        assert exc.value.http_status == 409

    @pytest.mark.asyncio
    @pytest.mark.parametrize("version", ["1.20.2", "1.16.5"])
    async def test_forge_range_rejected(
        self, tmp_path: Path, version: str
    ) -> None:
        archive = _write_cf_zip(
            tmp_path / "forge.zip", _manifest(mc=version)
        )
        with pytest.raises(UnsupportedForgeVersionError):
            await parse_curseforge_zip(archive, api_key="key")

    @pytest.mark.asyncio
    async def test_null_download_url_becomes_blocker(self, tmp_path: Path) -> None:
        data = b"blocked-file"
        manifest = _manifest(files=((10, 100, True),))
        archive = _write_cf_zip(tmp_path / "blocked.zip", manifest)
        session = _CfSession(
            [
                _CfResponse(
                    200,
                    {
                        "data": [
                            _cf_meta(100, "blocked.jar", data, download_url=None)
                        ]
                    },
                )
            ]
        )
        plan, blobs = await parse_curseforge_zip(
            archive, api_key="key", cf_http_client=session
        )
        assert blobs == {}
        assert plan.files == ()
        assert len(plan.manual_blockers) == 1
        blocker = plan.manual_blockers[0]
        assert blocker.blocker_type == "manual_download_required"
        assert blocker.reason == "download_url_null"
        assert blocker.path == "mods/blocked.jar"
        assert blocker.expected_size == len(data)
        assert blocker.expected_sha1 == _sha1(data)
        assert blocker.webpage_url.endswith("/projects/10/files/100")
        assert plan.has_unresolved_blockers is True

    @pytest.mark.asyncio
    async def test_happy_parse_reuses_override_rules(self, tmp_path: Path) -> None:
        data = b"mod-data"
        manifest = _manifest(files=((10, 100, True),))
        archive = _write_cf_zip(
            tmp_path / "pack.zip",
            manifest,
            {
                "overrides/config/a.toml": b"a-value",
                "overrides/config/b.toml": b"b-value",
                "overrides/mods/ov.jar": b"ov",
                "overrides/run.sh": b"#!/bin/sh\n",
            },
        )
        session = _CfSession(
            [_CfResponse(200, {"data": [_cf_meta(100, "foo.jar", data)]})]
        )
        plan, blobs = await parse_curseforge_zip(
            archive, api_key="key", cf_http_client=session, modrinth_client=_FakeModrinth()
        )
        assert plan.source == "curseforge"
        assert plan.mc_version == "1.20.1"
        assert plan.loader_id == "forge"
        assert plan.loader_version == "47.2.0"
        assert plan.version_label == "CF Pack"
        assert [f.path for f in plan.files] == ["mods/foo.jar"]
        assert plan.files[0].origin == Origin.CURSEFORGE_UNCLASSIFIED
        assert plan.files[0].downloads == (CDN,)
        assert plan.files[0].sha512 is None
        assert blobs["config/a.toml"] == b"a-value"
        assert blobs["config/b.toml"] == b"b-value"
        assert blobs["mods/ov.jar"] == b"ov"
        assert "run.sh" in plan.discarded_paths

    @pytest.mark.asyncio
    async def test_optional_skipped_when_disabled(self, tmp_path: Path) -> None:
        data = b"optional-data"
        manifest = _manifest(files=((10, 100, False),))
        archive = _write_cf_zip(tmp_path / "optional.zip", manifest)
        session = _CfSession(
            [_CfResponse(200, {"data": [_cf_meta(100, "opt.jar", data)]})]
        )
        plan, _ = await parse_curseforge_zip(
            archive,
            api_key="key",
            cf_http_client=session,
            install_optional_server_files=False,
        )
        assert plan.skipped_optional_files == ("mods/opt.jar",)
        assert plan.files == ()

    @pytest.mark.asyncio
    async def test_optional_env_server_and_skip_and_dir_mode(
        self, tmp_path: Path
    ) -> None:
        opt_data = b"optional-data"
        readme_data = b"readme"
        big_size = 17 * 1024 * 1024
        manifest = _manifest(files=((10, 100, False), (20, 200, True)))
        archive = tmp_path / "cf-edge.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
            dir_info = zipfile.ZipInfo("overrides/config")
            dir_info.external_attr = (stat.S_IFDIR | 0o755) << 16
            zf.writestr(dir_info, b"")
            zf.writestr("overrides/resourcepacks/big.zip", b"P" * big_size)

        session = _CfSession(
            [
                _CfResponse(
                    200,
                    {
                        "data": [
                            _cf_meta(100, "opt.jar", opt_data),
                            _cf_meta(200, "readme.txt", readme_data),
                        ]
                    },
                )
            ]
        )
        plan, blobs = await parse_curseforge_zip(
            archive,
            api_key="key",
            cf_http_client=session,
            install_optional_server_files=True,
        )
        assert [f.path for f in plan.files] == ["mods/opt.jar"]
        assert plan.files[0].optional is True
        assert plan.files[0].env_server == "optional"
        assert "mods/readme.txt" in plan.discarded_paths
        assert "skipped_path:mods/readme.txt" in plan.warnings
        assert len(blobs["resourcepacks/big.zip"]) == big_size
        assert "config" not in blobs


class TestCurseForgeDownloads:
    @pytest.mark.asyncio
    async def test_cdn_401_becomes_blocker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = InstallPlan(
            source="curseforge",
            project_id="local",
            version_id="local",
            version_label="Pack",
            index_sha256="a" * 64,
            mc_version="1.20.1",
            loader_id="forge",
            loader_version="47.2.0",
            files=(
                InstallPlanFile(
                    path="mods/blocked.jar",
                    sha1="b" * 40,
                    size=10,
                    downloads=(CDN,),
                    origin=Origin.CURSEFORGE_UNCLASSIFIED,
                ),
            ),
            overrides=(),
        )

        async def fake_download(*_args: object, **_kwargs: object) -> object:
            raise DownloadError(CDN, 401)

        monkeypatch.setattr(
            curseforge_adapter, "download_verified_to_cas", fake_download
        )
        updated, downloaded = await download_curseforge_plan_files(
            plan, ArtifactCas(tmp_path / "cas")
        )
        assert downloaded == {}
        assert updated.files == ()
        assert len(updated.manual_blockers) == 1
        assert updated.manual_blockers[0].reason == "cdn_http_401"
        assert updated.manual_blockers[0].blocker_type == "manual_download_required"

    @pytest.mark.asyncio
    async def test_client_only_filter_and_origins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client_data = b"client-jar"
        matched_data = b"matched-jar"
        unknown_data = b"unknown-jar"
        plan = InstallPlan(
            source="curseforge",
            project_id="local",
            version_id="local",
            version_label="Pack",
            index_sha256="a" * 64,
            mc_version="1.20.1",
            loader_id="forge",
            loader_version="47.2.0",
            files=tuple(
                InstallPlanFile(
                    path=f"mods/{name}.jar",
                    sha1=_sha1(data),
                    size=len(data),
                    downloads=(f"https://edge.forgecdn.net/files/{name}.jar",),
                    origin=Origin.CURSEFORGE_UNCLASSIFIED,
                )
                for name, data in (
                    ("client", client_data),
                    ("matched", matched_data),
                    ("unknown", unknown_data),
                )
            ),
            overrides=(),
        )

        async def fake_download(
            url: str, _cas: ArtifactCas, **_kwargs: object
        ) -> VerifiedDownloadResult:
            data = {
                "https://edge.forgecdn.net/files/client.jar": client_data,
                "https://edge.forgecdn.net/files/matched.jar": matched_data,
                "https://edge.forgecdn.net/files/unknown.jar": unknown_data,
            }[url]
            return _verified(data)

        record = ModrinthVersionRecord(
            version_id="ver-1",
            project_id="proj-1",
            name="Matched",
            version_number="1.0",
            version_type="release",
            game_versions=("1.20.1",),
            loaders=("forge",),
            environment="server_only",
            files=(),
            dependencies=(),
        )
        fake_client = _FakeModrinth(
            client_only={_sha512(client_data)},
            matched={_sha512(matched_data): record},
        )
        monkeypatch.setattr(
            curseforge_adapter, "download_verified_to_cas", fake_download
        )
        updated, downloaded = await download_curseforge_plan_files(
            plan,
            ArtifactCas(tmp_path / "cas"),
            modrinth_client=fake_client,
        )
        assert len(downloaded) == 3
        assert [f.path for f in updated.files] == [
            "mods/matched.jar",
            "mods/unknown.jar",
        ]
        matched = next(f for f in updated.files if f.path == "mods/matched.jar")
        assert matched.origin == Origin.CURSEFORGE
        assert matched.project_id == "proj-1"
        assert matched.version_id == "ver-1"
        unknown = next(f for f in updated.files if f.path == "mods/unknown.jar")
        assert unknown.origin == Origin.CURSEFORGE_UNCLASSIFIED
        assert unknown.project_id is None
        assert unknown.version_id is None
        assert updated.skipped_client_files == ("mods/client.jar",)
        assert updated.skipped_client_override_jars == ("mods/client.jar",)
        assert "skipped_client_override_jar:mods/client.jar" in updated.warnings


@pytest.mark.skipif(
    os.name != "posix",
    reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
)
class TestManualDownloadUpload:
    def _plan(self, data: bytes) -> InstallPlan:
        return InstallPlan(
            source="curseforge",
            project_id="local",
            version_id="local",
            version_label="Pack",
            index_sha256="a" * 64,
            mc_version="1.20.1",
            loader_id="forge",
            loader_version="47.2.0",
            files=(),
            overrides=(),
            manual_blockers=(
                ManualDownloadBlocker(
                    path="mods/manual.jar",
                    filename="manual.jar",
                    project_id=10,
                    file_id=100,
                    webpage_url="https://www.curseforge.com/projects/10/files/100",
                    expected_size=len(data),
                    expected_sha1=_sha1(data),
                    reason="download_url_null",
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_wrong_size_and_sha1_rejected(
        self, tmp_path: Path
    ) -> None:
        data = b"manual-data"
        plan = self._plan(data)
        cas = ArtifactCas(tmp_path / "cas")
        with pytest.raises(CorruptedDownloadError):
            await resolve_manual_download_upload(
                plan, path="mods/manual.jar", data=b"short", cas=cas
            )
        with pytest.raises(CorruptedDownloadError):
            await resolve_manual_download_upload(
                plan, path="mods/manual.jar", data=b"MANUAL-DATA", cas=cas
            )
        assert not cas.has(_sha256(data))
        assert plan.has_unresolved_blockers is True

    @pytest.mark.asyncio
    async def test_valid_upload_clears_blocker_and_stores(
        self, tmp_path: Path
    ) -> None:
        data = b"manual-data"
        plan = self._plan(data)
        cas = ArtifactCas(tmp_path / "cas")
        updated, result = await resolve_manual_download_upload(
            plan, path="mods/manual.jar", data=data, cas=cas
        )
        assert result is not None
        assert result.sha256 == _sha256(data)
        assert cas.has(_sha256(data))
        assert updated.has_unresolved_blockers is False
        assert updated.manual_blockers[0].resolved is True
        assert updated.manual_blockers[0].resolved_sha256 == _sha256(data)
        assert [f.path for f in updated.files] == ["mods/manual.jar"]
        assert updated.files[0].origin == Origin.CURSEFORGE_UNCLASSIFIED

    @pytest.mark.asyncio
    async def test_client_only_upload_is_dropped(
        self, tmp_path: Path
    ) -> None:
        data = b"client-only-upload"
        plan = self._plan(data)
        cas = ArtifactCas(tmp_path / "cas")
        updated, result = await resolve_manual_download_upload(
            plan,
            path="mods/manual.jar",
            data=data,
            cas=cas,
            modrinth_client=_FakeModrinth(client_only={_sha512(data)}),
        )
        assert result is None
        assert updated.manual_blockers[0].resolved is True
        assert updated.files == ()
        assert not cas.has(_sha256(data))
        assert updated.skipped_client_files == ("mods/manual.jar",)
        assert updated.skipped_client_override_jars == ("mods/manual.jar",)
        assert "skipped_client_override_jar:mods/manual.jar" in updated.warnings

    @pytest.mark.asyncio
    async def test_wrong_lookup_and_missing_selector(
        self, tmp_path: Path
    ) -> None:
        data = b"manual-data"
        plan = self._plan(data)
        cas = ArtifactCas(tmp_path / "cas")
        with pytest.raises(ValidationError):
            await resolve_manual_download_upload(plan, data=data, cas=cas)
        with pytest.raises(NotFoundError):
            await resolve_manual_download_upload(
                plan, file_id=999, data=data, cas=cas
            )

    @pytest.mark.asyncio
    async def test_builder_refuses_unresolved_blockers(
        self, tmp_path: Path
    ) -> None:
        data = b"manual-data"
        plan = self._plan(data)
        with pytest.raises(ManualDownloadRequiredError):
            build_lockfile_from_install_plan(
                plan,
                cas=ArtifactCas(tmp_path / "cas"),
                downloaded_files={},
                override_blobs={},
            )
