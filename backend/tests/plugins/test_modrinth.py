from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    UntrustedDownloadHostError,
)
from app.core.persistence.db import database
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.plugin.application.commands.install_modrinth_plugin import (
    InstallModrinthPluginCommand,
    InstallModrinthPluginHandler,
)
from app.modules.plugin.infrastructure.providers import (
    ModrinthProvider,
    build_plugin_catalog_provider,
    validate_plugin_providers,
)
from app.modules.plugin.infrastructure.providers import modrinth as modrinth_module
from app.modules.plugin.infrastructure.providers.base import (
    PluginFile,
    PluginVersionInfo,
    PluginVersionsPage,
)
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthProjectMeta,
    ModrinthVersionRecord,
)
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, PluginId, ServerId
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import (
    ALL_NORMATIVE_DOWNLOAD_HOSTS,
    DEFAULT_ALLOWED_DOWNLOAD_HOSTS,
    GITHUB_REDIRECT_ASSET_HOSTS,
    download_verified_bytes,
    download_verified_to_cas,
    normalize_allowed_host,
    validate_download_url,
)
from tests.helpers import build_test_app

CDN = "https://cdn.modrinth.com/data/abc/versions/1/file.jar"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _make_jar_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for fname, content in files.items():
            zf.writestr(fname, content.encode("utf-8") if isinstance(content, str) else content)
    return buf.getvalue()


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, _size: int = -1) -> bytes:
        body, self._body = self._body, b""
        return body


class _FakeResponse:
    def __init__(self, status: int, *, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(body)

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def get(self, url: str, *, allow_redirects: bool = True) -> _FakeResponse:
        self.calls.append((url, allow_redirects))
        return self._responses.pop(0)


class _JsonResponse:
    def __init__(
        self,
        status: int,
        payload: object | None = None,
        headers: dict | None = None,
    ) -> None:
        self.status = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    async def __aenter__(self) -> _JsonResponse:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    async def json(self) -> object:
        return self._payload


class _JsonSession:
    def __init__(self, responses: list[_JsonResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_kwargs: object) -> _JsonResponse:
        self.calls.append((method, url))
        return self._responses.pop(0)


class TestCatalogProviderFactory:
    def test_validate_and_build_provider(self) -> None:
        assert validate_plugin_providers("modrinth") == ["modrinth"]
        assert validate_plugin_providers(" Modrinth ") == ["modrinth"]

        assert isinstance(build_plugin_catalog_provider(), ModrinthProvider)
        assert isinstance(build_plugin_catalog_provider(name="modrinth"), ModrinthProvider)
        assert isinstance(
            build_plugin_catalog_provider(settings=AppSettings(plugin_providers="modrinth")),
            ModrinthProvider,
        )

        for bad_value, match in (
            ("", "at least one provider"),
            ("modrinth,modrinth", "exactly one provider"),
            ("curseforge", "Unknown plugin catalog provider"),
            ("modrinth,curseforge", "curseforge"),
        ):
            with pytest.raises(ValueError, match=match):
                validate_plugin_providers(bad_value)
            with pytest.raises(ValueError, match=match):
                build_plugin_catalog_provider(settings=AppSettings(plugin_providers=bad_value))

        with pytest.raises(ValueError, match="Unknown plugin catalog provider"):
            build_plugin_catalog_provider(name="curseforge")


class TestModrinthProvider:
    async def test_search_facets_loaders_dual_types_and_injection_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        captured_params: dict = {}

        async def mock_get_json(_path: str, params: dict | None = None) -> dict:
            nonlocal captured_params
            captured_params = params or {}
            return {
                "hits": [
                    {
                        "project_id": "proj-1",
                        "slug": "paper-plugin",
                        "title": "Paper Plugin",
                        "all_project_types": ["plugin"],
                        "categories": ["paper", "purpur", "economy"],
                        "client_side": "unsupported",
                        "server_side": "required",
                        "date_modified": "2025-01-01T00:00:00Z",
                        "color": 123456,
                    },
                    {
                        "project_id": "proj-2",
                        "slug": "fabric-mod",
                        "title": "Fabric Mod",
                        "all_project_types": ["mod"],
                    },
                    {
                        "project_id": "luckperms",
                        "slug": "luckperms",
                        "title": "LuckPerms",
                        "project_type": "mod",
                        "categories": ["paper", "spigot", "fabric", "forge"],
                        "downloads": 1000,
                        "follows": 100,
                    },
                ],
                "total_hits": 10,
            }

        monkeypatch.setattr(provider, "_get_json", mock_get_json)

        page = await provider.search("worldedit")
        assert [item.project_id for item in page.items] == ["proj-1", "luckperms"]
        assert page.total_hits == 10
        assert page.items[0].loaders == ["paper", "purpur"]
        assert page.items[0].client_side == "unsupported"
        assert set(page.items[1].project_types) == {"plugin", "mod"}
        assert "project_type:plugin" in captured_params["facets"]
        assert "categories:paper" in captured_params["facets"]

        mod_page = await provider.search("sodium", project_type="mod", loader="NeoForge")
        assert [item.project_id for item in mod_page.items] == ["proj-2", "luckperms"]
        assert '["categories:neoforge"]' in captured_params["facets"]

        # Sort & game_version facets, and invalid loader/game_version ignored safely
        await provider.search(
            query="essentials",
            project_type="plugin",
            loader="paper",
            sort="downloads",
            game_version="1.21.1",
        )
        assert captured_params["index"] == "downloads"
        facets = json.loads(captured_params["facets"])
        assert ["categories:paper", "categories:spigot", "categories:bukkit"] in facets
        assert ["versions:1.21.1"] in facets

        await provider.search(
            "worldedit", loader='"categories:paper"],["evil', game_version='1.21"]'
        )
        raw_facets = captured_params["facets"]
        assert "evil" not in raw_facets
        assert "categories:paper" in raw_facets
        parsed_facets = json.loads(raw_facets)
        assert not any(
            isinstance(group, list) and any(item.startswith("versions:") for item in group)
            for group in parsed_facets
        )

    async def test_search_missing_total_hits_defaults_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        monkeypatch.setattr(provider, "_get_json", AsyncMock(return_value={"hits": []}))
        page = await provider.search("worldedit")
        assert page.items == []
        assert page.total_hits == 0

    async def test_get_project_resolves_team_author_and_followers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        payloads = {
            "/project/proj-2": {
                "id": "proj-2",
                "slug": "team-project",
                "title": "Team Project",
                "team": "team-abc",
                "followers": 7100,
                "follows": 0,
                "client_side": "optional",
                "server_side": "required",
            },
            "/team/team-abc/members": [
                {"role": "Member", "user": {"username": "Contributor"}},
                {"role": "Owner", "user": {"username": "OwnerName"}},
            ],
        }

        async def mock_get_json(path: str, _params: dict | None = None) -> dict | list:
            return payloads[path]

        monkeypatch.setattr(provider, "_get_json", mock_get_json)
        project = await provider.get_project("proj-2")
        assert project.author == "OwnerName"
        assert project.follows == 7100
        assert project.client_side == "optional"

        async def failing_team_get_json(path: str, _params: dict | None = None) -> dict:
            if path.startswith("/project/"):
                return {"id": "proj-3", "team": "team-xyz"}
            raise DownloadError(path, 500)

        monkeypatch.setattr(provider, "_get_json", failing_team_get_json)
        fallback = await provider.get_project("proj-3")
        assert fallback.author == ""

    async def test_get_project_versions_slicing_and_changelog_deps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()

        async def mock_versions(_path: str, _params: dict | None = None) -> list[dict]:
            return [
                {
                    "id": f"v{i}",
                    "project_id": "proj-1",
                    "name": f"v{i}",
                    "version_number": f"{i}.0.0",
                    "changelog": "## Fixed\n- Memory leak" if i == 0 else "",
                    "dependencies": (
                        [
                            {"project_id": "dep-req-1", "dependency_type": "required"},
                            {"project_id": "dep-req-1", "dependency_type": "required"},
                            {"project_id": "dep-opt-1", "dependency_type": "optional"},
                            {"version_id": "ver-only", "dependency_type": "required"},
                            {"project_id": "dep-req-2", "dependency_type": "required"},
                        ]
                        if i == 0
                        else []
                    ),
                }
                for i in range(25)
            ]

        monkeypatch.setattr(provider, "_get_json", mock_versions)
        all_page = await provider.get_project_versions("proj-1")
        assert all_page.total == 25
        assert all_page.items[0].changelog == "## Fixed\n- Memory leak"
        assert all_page.items[0].required_dependencies == ["dep-req-1", "dep-req-2"]

        sliced = await provider.get_project_versions("proj-1", limit=10, offset=10)
        assert len(sliced.items) == 10
        assert sliced.items[0].version_id == "v10"
        assert sliced.items[-1].version_id == "v19"

    async def test_ttl_cache_and_429_and_404_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ModrinthProvider.clear_cache()
        provider = ModrinthProvider()
        calls = 0

        class _Client:
            def __init__(self, statuses: list[int]) -> None:
                self._statuses = statuses

            def get(self, _url: str, **_kwargs: object):
                nonlocal calls
                calls += 1
                status = self._statuses.pop(0)

                class _Resp:
                    def __init__(self, st: int) -> None:
                        self.status = st
                        self.headers = {"Retry-After": "2"} if st == 429 else {}

                    async def json(self) -> dict:
                        return {"hits": [], "total_hits": 0, "id": "p1"}

                    async def text(self) -> str:
                        return "rate limited" if self.status == 429 else ""

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *_args: object) -> bool:
                        return False

                return _Resp(status)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: _Client([200, 200]))
        await provider.search(query="worldedit")
        await provider.search(query="worldedit")
        assert calls == 1

        ModrinthProvider.clear_cache()
        await provider.search(query="worldedit")
        assert calls == 2
        ModrinthProvider.clear_cache()

        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: _Client([429, 200]))
        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)
        data = await provider._get_json("/project/p1")
        assert data["id"] == "p1"
        assert sleeps and sleeps[0] >= 2.0

        attempts = 0

        async def mock_do_get_json(_self, _client, url: str, _params: object) -> dict:
            nonlocal attempts
            attempts += 1
            raise DownloadError(url, 404)

        monkeypatch.setattr(ModrinthProvider, "_do_get_json", mock_do_get_json)
        with pytest.raises(DownloadError) as exc_info:
            await provider._get_json("/project/nonexistent")
        assert exc_info.value.status == 404
        assert attempts == 1
        ModrinthProvider.clear_cache()

    async def test_download_host_validation_parallel_ranges_and_no_404_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        for bad_url in ("https://evil.com/malicious.jar", "http://cdn.modrinth.com/file.jar"):
            with pytest.raises(DownloadError, match="not a valid Modrinth domain"):
                await provider.download(bad_url)

        payload = b"A" * 400_000 + b"B" * 400_000 + b"C" * 160_000
        captured_calls: list[tuple[str | None, aiohttp.ClientTimeout]] = []

        class _ChunkContent:
            def __init__(self, data: bytes) -> None:
                self._chunks = [data[i : i + 65536] for i in range(0, len(data), 65536)] + [b""]

            async def read(self, _n: int) -> bytes:
                return self._chunks.pop(0)

        class _RangeResp:
            def __init__(self, data: bytes, headers: dict[str, str]) -> None:
                self.status = 206
                self.content = _ChunkContent(data)
                self.headers = headers

            async def __aenter__(self) -> _RangeResp:
                return self

            async def __aexit__(self, *_args: object) -> bool:
                return False

        from unittest.mock import MagicMock

        def fake_range_get(_url: str, **kwargs: object) -> _RangeResp:
            headers = kwargs.get("headers") or {}
            range_hdr = headers["Range"]  # type: ignore[index]
            captured_calls.append((range_hdr, kwargs["timeout"]))  # type: ignore[arg-type]
            start_s, end_s = range_hdr.removeprefix("bytes=").split("-")
            start, end = int(start_s), min(len(payload) - 1, int(end_s))
            return _RangeResp(
                payload[start : end + 1],
                {"Content-Range": f"bytes {start}-{end}/{len(payload)}"},
            )

        range_session = MagicMock(spec=aiohttp.ClientSession)
        range_session.get.side_effect = fake_range_get
        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: range_session)
        result = await provider.download("https://cdn.modrinth.com/data/abc/VeinMiner.jar")
        assert result == payload
        assert len(captured_calls) > 1
        for _hdr, timeout in captured_calls:
            assert timeout.total is None
            assert timeout.sock_read == modrinth_module.MODRINTH_DOWNLOAD_READ_TIMEOUT_SECONDS

        dl_calls = 0

        async def _fake_do_download(_client, url: str) -> bytes:
            nonlocal dl_calls
            dl_calls += 1
            raise DownloadError(url, 404)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: object())
        monkeypatch.setattr(provider, "_do_download", _fake_do_download)
        with pytest.raises(DownloadError) as exc_info:
            await provider.download("https://cdn.modrinth.com/data/missing.jar")
        assert exc_info.value.status == 404
        assert dl_calls == 1

    async def test_marketplace_router_returns_404(self) -> None:
        app, _, _, _ = build_test_app()
        token = create_access_token(
            user_id="test",
            roles=["admin", "owner"],
            permissions=["admin:full", "plugin:manage", "global.settings"],
        )

        async def mock_get_project(_self, project_id: str) -> object:
            raise DownloadError(f"https://api.modrinth.com/v2/project/{project_id}", 404)

        with patch.object(ModrinthProvider, "get_project", mock_get_project):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/marketplace/projects/missing-plugin",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 404


class TestModrinthBatchAndRateLimit:
    @staticmethod
    def _hash(index: int, length: int = 128) -> str:
        return f"{index:0{length}x}"

    async def test_batch_hash_and_id_chunking_never_searches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        calls: list[tuple[str, str, dict, dict]] = []

        async def fake_request(
            method: str,
            path: str,
            *,
            json_body: dict | None = None,
            params: dict | None = None,
            **_kwargs: object,
        ) -> dict | list:
            calls.append((method, path, json_body or {}, params or {}))
            return {} if method == "POST" else []

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        hashes = [self._hash(i) for i in range(450)]
        ids = [f"v{i}" for i in range(450)]

        await provider.lookup_version_files_by_hashes(hashes)
        await provider.lookup_version_updates_by_hashes(
            hashes, loaders=["fabric"], game_versions=["1.21.4"]
        )
        await provider.get_versions_by_ids(ids)
        await provider.get_projects_by_ids(ids)

        assert [len(c[2]["hashes"]) for c in calls if c[1] == "/version_files"] == [200, 200, 50]
        upd_calls = [c for c in calls if c[1] == "/version_files/update"]
        assert [len(c[2]["hashes"]) for c in upd_calls] == [200, 200, 50]
        assert upd_calls[0][2]["loaders"] == ["fabric"]
        assert upd_calls[0][2]["game_versions"] == ["1.21.4"]
        assert [len(json.loads(c[3]["ids"])) for c in calls if c[1] == "/versions"] == [
            200,
            200,
            50,
        ]
        assert [len(json.loads(c[3]["ids"])) for c in calls if c[1] == "/projects"] == [
            200,
            200,
            50,
        ]
        assert all(c[1] != "/search" for c in calls)

    async def test_client_only_environment_and_project_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        d1, d2, d3 = self._hash(1), self._hash(2), self._hash(3)

        async def fake_request(
            _method: str, _path: str, *, json_body: dict | None = None, **_kwargs: object
        ) -> dict:
            req_hashes = (json_body or {}).get("hashes", [])
            if d1 in req_hashes:
                return {
                    d1: {
                        "id": "ver-1",
                        "project_id": "proj-1",
                        "name": "Version",
                        "version_number": "1.0",
                        "version_type": "release",
                        "game_versions": ["1.20.1"],
                        "loaders": ["fabric"],
                        "environment": "client_only",
                        "server_side": "required",
                        "files": [],
                        "dependencies": [],
                    }
                }
            return {
                d2: {
                    "id": "ver-2",
                    "project_id": "proj-2",
                    "name": "Version",
                    "version_number": "1.0",
                    "version_type": "release",
                    "game_versions": ["1.20.1"],
                    "loaders": ["fabric"],
                    "server_side": "unsupported",
                    "files": [],
                    "dependencies": [],
                }
            }

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        assert (await provider.lookup_version_files_by_hashes([d1]))[
            d1
        ].environment == "client_only"
        assert (await provider.lookup_version_files_by_hashes([d2]))[d2].environment is None

        async def fake_lookup(_hashes: object, *, algorithm: str = "sha512") -> dict:
            del algorithm
            return {
                d3: ModrinthVersionRecord(
                    version_id="ver-3",
                    project_id="proj-3",
                    name="Version",
                    version_number="1.0",
                    version_type="release",
                    game_versions=("1.20.1",),
                    loaders=("fabric",),
                    environment=None,
                    files=(),
                    dependencies=(),
                )
            }

        async def fake_projects(_ids: object) -> dict:
            return {
                "proj-3": ModrinthProjectMeta(
                    project_id="proj-3",
                    slug="proj",
                    title="Project",
                    project_type="mod",
                    client_side="required",
                    server_side="unsupported",
                    loaders=("fabric",),
                    game_versions=("1.20.1",),
                )
            }

        monkeypatch.setattr(provider, "lookup_version_files_by_hashes", fake_lookup)
        monkeypatch.setattr(provider, "get_projects_by_ids", fake_projects)
        client_only, matched, projects = await provider.classify_client_only_jars_by_sha512([d3])
        assert client_only == {d3}
        assert d3 in matched
        assert projects["proj-3"].server_side == "unsupported"

    async def test_rate_limit_retries_backoff_exhaustion_400_and_remaining_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)

        session_retry = _JsonSession(
            [
                _JsonResponse(429, headers={"Retry-After": "0"}),
                _JsonResponse(429, headers={"Retry-After": "0"}),
                _JsonResponse(200, payload={"ok": True}),
            ]
        )
        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: session_retry)
        assert await provider._request_json_with_ratelimit("GET", "/versions") == {"ok": True}
        assert sleeps == [1.0, 2.0]

        sleeps.clear()
        monkeypatch.setattr(
            modrinth_module,
            "get_http_client",
            lambda: _JsonSession([_JsonResponse(429, headers={"Retry-After": "0"})] * 4),
        )
        with pytest.raises(DownloadError) as exc:
            await provider._request_json_with_ratelimit("GET", "/versions", max_retries=3)
        assert exc.value.status == 429

        sleeps.clear()
        monkeypatch.setattr(
            modrinth_module, "get_http_client", lambda: _JsonSession([_JsonResponse(400)])
        )
        with pytest.raises(DownloadError) as exc_400:
            await provider._request_json_with_ratelimit("GET", "/projects")
        assert exc_400.value.status == 400
        assert sleeps == []

        sleeps.clear()
        monkeypatch.setattr(
            modrinth_module,
            "get_http_client",
            lambda: _JsonSession(
                [
                    _JsonResponse(
                        200,
                        payload={},
                        headers={"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "30"},
                    ),
                    _JsonResponse(200, payload={}),
                ]
            ),
        )
        await provider._request_json_with_ratelimit("GET", "/versions")
        await provider._request_json_with_ratelimit("GET", "/versions")
        assert sleeps and sleeps[0] > 0


class TestDownloadAllowList:
    def test_normative_hosts_and_github_release_rules(self) -> None:
        assert len(ALL_NORMATIVE_DOWNLOAD_HOSTS) == 20
        assert len(DEFAULT_ALLOWED_DOWNLOAD_HOSTS) == 16
        assert "api.purpurmc.org" in DEFAULT_ALLOWED_DOWNLOAD_HOSTS

        for host in sorted(DEFAULT_ALLOWED_DOWNLOAD_HOSTS):
            validated = validate_download_url(f"https://{host}/path/file.bin")
            assert validated.host == host
            assert validated.is_github_release_origin is False

        gh = validate_download_url("https://github.com/owner/repo/releases/download/v1.0/thing.jar")
        assert gh.host == "github.com"
        assert gh.is_github_release_origin is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo/raw/main/thing.jar",
            "https://github.com/owner/repo/archive/refs/heads/main.zip",
            "https://github.com/owner/repo/releases/download/../etc/passwd",
            "https://github.com/owner/repo/releases/download/%2e%2e/thing.jar",
            "http://cdn.modrinth.com/file.jar",
            "https://user:pass@cdn.modrinth.com/file.jar",
            "https://cdn.modrinth.com:8443/file.jar",
            "https://127.0.0.1/file.jar",
            "https://[::1]/file.jar",
            "https://2130706433/file.jar",
            "https://0x7f000001/file.jar",
            "https://unlisted.example.com/file.jar",
        ],
    )
    def test_invalid_and_ssrf_urls_rejected(self, url: str) -> None:
        with pytest.raises(UntrustedDownloadHostError):
            validate_download_url(url)

    @pytest.mark.parametrize("host", sorted(GITHUB_REDIRECT_ASSET_HOSTS))
    def test_github_asset_hosts_require_release_redirect(self, host: str) -> None:
        with pytest.raises(UntrustedDownloadHostError) as exc:
            validate_download_url(f"https://{host}/owner/repo/asset")
        assert exc.value.reason == "github_asset_host_requires_release_redirect"

        validated = validate_download_url(
            f"https://{host}/owner/repo/asset", from_github_release=True
        )
        assert validated.host == host

    def test_extra_allowed_hosts_and_normalization(self) -> None:
        assert normalize_allowed_host("CDN.Modrinth.COM.") == "cdn.modrinth.com"
        with pytest.raises(UntrustedDownloadHostError):
            normalize_allowed_host("*.modrinth.com")

        validated = validate_download_url(
            "https://mirror.example.com/file.jar",
            extra_allowed_hosts=["mirror.example.com"],
        )
        assert validated.host == "mirror.example.com"
        with pytest.raises(UntrustedDownloadHostError):
            validate_download_url(
                "https://mirror.example.com/file.jar",
                extra_allowed_hosts=["1.2.3.4"],
            )
        with pytest.raises(UntrustedDownloadHostError):
            validate_download_url(
                "http://mirror.example.com/file.jar",
                extra_allowed_hosts=["mirror.example.com"],
            )

    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    async def test_verified_download_to_cas_redirects_and_integrity_checks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cas = ArtifactCas(tmp_path / "cas")
        body = b"verified-content"
        session = _FakeSession([_FakeResponse(200, body=body)])
        res = await download_verified_to_cas(
            CDN,
            cas,
            expected_size=len(body),
            expected_sha512=_sha512(body),
            expected_sha1=_sha1(body),
            expected_sha256=_sha256(body),
            client=session,
        )
        assert res.size == len(body) and cas.has(_sha256(body))
        assert session.calls == [(CDN, False)]

        # Validated GitHub release redirect
        gh_body = b"github-asset"
        gh_session = _FakeSession(
            [
                _FakeResponse(
                    302, headers={"Location": "https://release-assets.githubusercontent.com/asset"}
                ),
                _FakeResponse(200, body=gh_body),
            ]
        )
        gh_res = await download_verified_to_cas(
            "https://github.com/owner/repo/releases/download/v1/thing.jar", cas, client=gh_session
        )
        assert gh_res.redirect_count == 1 and cas.has(gh_res.sha256)

        # Unlisted redirect & too many redirects
        with pytest.raises(UntrustedDownloadHostError):
            await download_verified_to_cas(
                CDN,
                cas,
                client=_FakeSession(
                    [_FakeResponse(302, headers={"Location": "https://evil.example.com/file"})]
                ),
            )
        with pytest.raises(DownloadError, match="Too many redirects"):
            await download_verified_to_cas(
                CDN,
                cas,
                client=_FakeSession(
                    [
                        _FakeResponse(302, headers={"Location": f"https://cdn.modrinth.com/hop{i}"})
                        for i in range(6)
                    ]
                ),
            )

        # Hash mismatch, size mismatch, oversized stream must not pollute CAS
        bad_body = b"corrupted-stream"
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_sha512="0" * 128,
                client=_FakeSession([_FakeResponse(200, body=bad_body)]),
            )
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_size=len(bad_body) + 10,
                client=_FakeSession([_FakeResponse(200, body=bad_body)]),
            )
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_size=4,
                client=_FakeSession([_FakeResponse(200, body=bad_body)]),
            )
        assert not cas.has(_sha256(bad_body))

        # Transient 503 retry succeeds
        async def _no_sleep(_sec: float) -> None:
            return None

        monkeypatch.setattr(
            "app.modules.versioning.infrastructure.download_allowlist.asyncio.sleep", _no_sleep
        )
        retry_body = b"retry-success"
        retry_session = _FakeSession([_FakeResponse(503), _FakeResponse(200, body=retry_body)])
        retry_res = await download_verified_to_cas(
            CDN, cas, expected_sha256=_sha256(retry_body), max_retries=3, client=retry_session
        )
        assert cas.has(retry_res.sha256) and len(retry_session.calls) == 2

    async def test_download_verified_bytes_variant(self) -> None:
        body = b"bytes"
        data, result = await download_verified_bytes(
            CDN, expected_sha256=_sha256(body), client=_FakeSession([_FakeResponse(200, body=body)])
        )
        assert data == body and result.sha1 == _sha1(body)


def _version(
    version_number: str = "2.21.0",
    filename: str = "EssentialsX.jar",
    loaders: list[str] | None = None,
    *,
    sha1: str = "deadbeef",
    sha512: str = "",
) -> PluginVersionInfo:
    return PluginVersionInfo(
        version_id="ver-1",
        project_id="proj-1",
        name="EssentialsX",
        version_number=version_number,
        game_versions=["1.21"],
        loaders=loaders or ["paper"],
        files=[
            PluginFile(
                url="https://cdn.modrinth.com/data/proj-1/ver-1/EssentialsX.jar",
                filename=filename,
                size_bytes=1024,
                sha1=sha1,
                sha512=sha512,
                primary=True,
            )
        ],
        date_published="2025-01-01T00:00:00Z",
    )


class _FakeInstallProvider:
    name = "modrinth"

    def __init__(
        self,
        version: PluginVersionInfo | None = None,
        jar_bytes: bytes | None = None,
    ) -> None:
        self._version = version
        self._jar_bytes = jar_bytes
        self.downloaded_url: str | None = None

    async def get_project_versions(self, _project_id: str, **_kwargs: object) -> PluginVersionsPage:
        return PluginVersionsPage(
            items=[self._version] if self._version else [],
            total=1 if self._version else 0,
        )

    async def get_version(self, _version_id: str) -> PluginVersionInfo:
        assert self._version is not None
        return self._version

    async def get_project(self, _project_id: str) -> object:
        class _Proj:
            icon_url = None

        return _Proj()

    async def download(
        self,
        url: str,
        expected_sha1: str | None = None,
        expected_sha512: str | None = None,
    ) -> bytes:
        del expected_sha1, expected_sha512
        self.downloaded_url = url
        if self._jar_bytes is not None:
            return self._jar_bytes
        return _make_jar_bytes(
            {"plugin.yml": "name: EssentialsX\nversion: 2.21.0\nmain: com.example.Main\n"}
        )


async def _create_server(
    server_id: str, root_path: str, server_type: ServerType = ServerType.PAPER
) -> None:
    deployment = ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path=root_path,
        working_directory=".",
    )
    async with database.session_factory() as session:
        server = Server.create(
            server_id=ServerId(server_id),
            name=f"Server {server_id}",
            server_type=server_type,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=deployment,
        )
        await SQLServerRepository(session).save(server)
        await session.commit()


class TestInstallModrinthPlugin:
    async def test_install_paper_plugin_and_non_semver_version(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        await _create_server("srv-mr-1", str(tmp_path / "srv-mr-1"))
        provider = _FakeInstallProvider(_version(version_number="v2.21-RC1"))
        res = await InstallModrinthPluginHandler(event_bus, provider=provider).handle(
            InstallModrinthPluginCommand(server_id="srv-mr-1", project_id="proj-1")
        )
        assert res.success is True
        assert res.data["source"] == "modrinth"
        assert res.data["filename"] == "EssentialsX.jar"
        assert provider.downloaded_url is not None

        async with database.session_factory() as session:
            plugin = await SQLPluginRepository(session).get(PluginId(res.data["plugin_id"]))
            assert plugin.display_version == "v2.21-RC1"
            assert plugin.external_project_id == "proj-1"
            assert plugin.checksum == "deadbeef"

    async def test_install_routes_to_mods_for_fabric(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "srv-mr-fab"
        await _create_server("srv-mr-fab", str(srv_dir), ServerType.FABRIC)
        jar = _make_jar_bytes(
            {"fabric.mod.json": '{"id": "mod", "name": "Downloaded Mod", "version": "1.0.0"}'}
        )
        provider = _FakeInstallProvider(
            _version(version_number="1.0.0", filename="mod.jar", loaders=["fabric"]),
            jar_bytes=jar,
        )
        res = await InstallModrinthPluginHandler(event_bus, provider=provider).handle(
            InstallModrinthPluginCommand(
                server_id="srv-mr-fab",
                project_id="proj-1",
                version_id="ver-1",
                minecraft_version="1.21",
            )
        )
        assert res.success is True
        assert res.data["loader"] == "fabric"
        assert (srv_dir / "mods" / "mod.jar").exists()
        assert not (srv_dir / "plugins" / "mod.jar").exists()

    async def test_install_rejects_invalid_states_and_payloads(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        # No deployment
        await _create_server("srv-mr-nodep", str(tmp_path / "srv-mr-nodep"))
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            srv = await repo.get(ServerId("srv-mr-nodep"))
            srv.update_deployment(
                ServerDeployment(
                    location_type=LocationType.LOCAL, root_path="", working_directory="."
                )
            )
            await repo.save(srv)
            await session.commit()
        res_nodep = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version())
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-nodep", project_id="proj-1"))
        assert res_nodep.success is False and res_nodep.error_code == "NO_DEPLOYMENT"

        # Vanilla unsupported
        await _create_server("srv-mr-van", str(tmp_path / "srv-mr-van"), ServerType.VANILLA)
        res_van = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version())
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-van", project_id="proj-1"))
        assert res_van.success is False and res_van.error_code == "PLUGINS_UNSUPPORTED"

        # No compatible version / incompatible explicit version
        srv_dir = tmp_path / "srv-mr-checks"
        await _create_server("srv-mr-checks", str(srv_dir))
        res_nover = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(None)
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-checks", project_id="proj-1"))
        assert res_nover.error_code == "NO_COMPATIBLE_VERSION"

        res_incompat = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version(loaders=["fabric"]))
        ).handle(
            InstallModrinthPluginCommand(
                server_id="srv-mr-checks", project_id="proj-1", version_id="ver-1"
            )
        )
        assert res_incompat.error_code == "NO_COMPATIBLE_VERSION"

        # Path traversal filename, invalid extension, missing checksums
        res_trav = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version(filename="../../../etc/evil.jar"))
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-checks", project_id="proj-1"))
        assert res_trav.error_code == "INVALID_FILENAME"

        res_ext = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version(filename="malicious.sh"))
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-checks", project_id="proj-1"))
        assert res_ext.error_code == "INVALID_FILENAME"

        res_hash = await InstallModrinthPluginHandler(
            event_bus, provider=_FakeInstallProvider(_version(sha1="", sha512=""))
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-checks", project_id="proj-1"))
        assert res_hash.error_code == "DOWNLOAD_FAILED"

        # Fabric-only JAR bytes rejected before disk write on Paper even if tagged paper
        fabric_bytes = _make_jar_bytes(
            {"fabric.mod.json": '{"id": "fabric-only", "name": "FabricOnly", "version": "1.0.0"}'}
        )
        res_leak = await InstallModrinthPluginHandler(
            event_bus,
            provider=_FakeInstallProvider(
                _version(filename="FabricOnly.jar"), jar_bytes=fabric_bytes
            ),
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-checks", project_id="proj-1"))
        assert res_leak.error_code == "NO_COMPATIBLE_VERSION"
        assert not (srv_dir / "plugins" / "FabricOnly.jar").exists()

    async def test_universal_jar_records_compatible_loader_on_paper(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        await _create_server("srv-mr-univ", str(tmp_path / "srv-mr-univ"), ServerType.PAPER)
        univ_bytes = _make_jar_bytes(
            {
                "fabric.mod.json": '{"id": "viaversion", "name": "ViaVersion", "version": "5.0.0"}',
                "plugin.yml": "name: ViaVersion\nversion: 5.0.0\nmain: com.viaversion.ViaPlugin\n",
            }
        )
        res = await InstallModrinthPluginHandler(
            event_bus,
            provider=_FakeInstallProvider(
                _version(filename="ViaVersion.jar", loaders=["fabric", "paper", "spigot"]),
                jar_bytes=univ_bytes,
            ),
        ).handle(InstallModrinthPluginCommand(server_id="srv-mr-univ", project_id="proj-1"))
        assert res.success is True
        assert res.data["loader"] in ("paper", "spigot", "bukkit")
        assert res.data["loader"] != "fabric"
