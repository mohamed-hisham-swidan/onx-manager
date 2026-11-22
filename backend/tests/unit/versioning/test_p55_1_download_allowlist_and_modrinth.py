"""P5.5-1 download allow-list, hardened downloader, and Modrinth batch tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    UntrustedDownloadHostError,
)
from app.modules.plugin.infrastructure.providers import modrinth as modrinth_module
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthProjectMeta,
    ModrinthProvider,
    ModrinthVersionRecord,
)
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

CDN = "https://cdn.modrinth.com/data/abc/versions/1/file.jar"


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, _size: int = -1) -> bytes:
        body, self._body = self._body, b""
        return body


class _FakeResponse:
    def __init__(self, status: int, *, body: bytes = b"", headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(body)

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def get(self, url: str, *, allow_redirects: bool = True) -> _FakeResponse:
        self.calls.append((url, allow_redirects))
        return self._responses.pop(0)


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestDownloadAllowList:
    def test_normative_host_count(self) -> None:
        assert len(ALL_NORMATIVE_DOWNLOAD_HOSTS) == 19
        assert len(DEFAULT_ALLOWED_DOWNLOAD_HOSTS) == 15

    @pytest.mark.parametrize("host", sorted(DEFAULT_ALLOWED_DOWNLOAD_HOSTS))
    def test_all_unconditional_hosts_accepted(self, host: str) -> None:
        validated = validate_download_url(f"https://{host}/path/file.bin")
        assert validated.host == host
        assert validated.is_github_release_origin is False

    def test_github_release_download_accepted(self) -> None:
        url = "https://github.com/owner/repo/releases/download/v1.0/thing.jar"
        validated = validate_download_url(url)
        assert validated.host == "github.com"
        assert validated.is_github_release_origin is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo/raw/main/thing.jar",
            "https://github.com/owner/repo/archive/refs/heads/main.zip",
            "https://github.com/owner/repo/releases/download/../etc/passwd",
            "https://github.com/owner/repo/releases/download/%2e%2e/thing.jar",
        ],
    )
    def test_github_non_release_paths_rejected(self, url: str) -> None:
        with pytest.raises(UntrustedDownloadHostError):
            validate_download_url(url)

    @pytest.mark.parametrize("host", sorted(GITHUB_REDIRECT_ASSET_HOSTS))
    def test_github_asset_hosts_rejected_as_initial_urls(self, host: str) -> None:
        with pytest.raises(UntrustedDownloadHostError) as exc:
            validate_download_url(f"https://{host}/owner/repo/asset")
        assert exc.value.reason == "github_asset_host_requires_release_redirect"

    @pytest.mark.parametrize("host", sorted(GITHUB_REDIRECT_ASSET_HOSTS))
    def test_github_asset_hosts_accepted_only_after_release_redirect(self, host: str) -> None:
        validated = validate_download_url(
            f"https://{host}/owner/repo/asset", from_github_release=True
        )
        assert validated.host == host

    @pytest.mark.parametrize(
        "url",
        [
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
    def test_invalid_urls_rejected(self, url: str) -> None:
        with pytest.raises(UntrustedDownloadHostError):
            validate_download_url(url)

    def test_extra_allowed_hosts_are_validated(self) -> None:
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

    def test_host_normalization(self) -> None:
        assert normalize_allowed_host("CDN.Modrinth.COM.") == "cdn.modrinth.com"
        with pytest.raises(UntrustedDownloadHostError):
            normalize_allowed_host("*.modrinth.com")


class TestHardenedDownloader:
    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    @pytest.mark.asyncio
    async def test_download_verifies_and_stores(self, tmp_path: Path) -> None:
        body = b"verified-content"
        cas = ArtifactCas(tmp_path / "cas")
        session = _FakeSession([_FakeResponse(200, body=body)])

        result = await download_verified_to_cas(
            CDN,
            cas,
            expected_size=len(body),
            expected_sha512=_sha512(body),
            expected_sha1=_sha1(body),
            expected_sha256=_sha256(body),
            client=session,
        )
        assert result.size == len(body)
        assert result.sha256 == _sha256(body)
        assert cas.has(_sha256(body))
        assert session.calls == [(CDN, False)]

    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    @pytest.mark.asyncio
    async def test_download_follows_validated_github_redirect(self, tmp_path: Path) -> None:
        body = b"github-asset"
        cas = ArtifactCas(tmp_path / "cas")
        session = _FakeSession(
            [
                _FakeResponse(
                    302,
                    headers={
                        "Location": "https://release-assets.githubusercontent.com/asset"
                    },
                ),
                _FakeResponse(200, body=body),
            ]
        )
        result = await download_verified_to_cas(
            "https://github.com/owner/repo/releases/download/v1/thing.jar",
            cas,
            client=session,
        )
        assert result.redirect_count == 1
        assert result.final_url.endswith("release-assets.githubusercontent.com/asset")
        assert cas.has(result.sha256)

    @pytest.mark.asyncio
    async def test_download_rejects_unlisted_redirect(self, tmp_path: Path) -> None:
        cas = ArtifactCas(tmp_path / "cas")
        session = _FakeSession(
            [_FakeResponse(302, headers={"Location": "https://evil.example.com/file"})]
        )
        with pytest.raises(UntrustedDownloadHostError):
            await download_verified_to_cas(CDN, cas, client=session)

    @pytest.mark.asyncio
    async def test_download_rejects_too_many_redirects(self, tmp_path: Path) -> None:
        cas = ArtifactCas(tmp_path / "cas")
        responses = [
            _FakeResponse(302, headers={"Location": f"https://cdn.modrinth.com/hop{i}"})
            for i in range(6)
        ]
        with pytest.raises(DownloadError, match="Too many redirects"):
            await download_verified_to_cas(
                CDN, cas, client=_FakeSession(responses)
            )

    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    @pytest.mark.asyncio
    async def test_hash_mismatch_does_not_pollute_cas(self, tmp_path: Path) -> None:
        body = b"corrupted"
        cas = ArtifactCas(tmp_path / "cas")
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_sha512="0" * 128,
                client=_FakeSession([_FakeResponse(200, body=body)]),
            )
        assert not cas.has(_sha256(body))

    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    @pytest.mark.asyncio
    async def test_size_mismatch_does_not_pollute_cas(self, tmp_path: Path) -> None:
        body = b"short"
        cas = ArtifactCas(tmp_path / "cas")
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_size=len(body) + 10,
                client=_FakeSession([_FakeResponse(200, body=body)]),
            )
        assert not cas.has(_sha256(body))

    @pytest.mark.skipif(
        os.name != "posix",
        reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
    )
    @pytest.mark.asyncio
    async def test_oversized_stream_aborts(self, tmp_path: Path) -> None:
        body = b"x" * 32
        cas = ArtifactCas(tmp_path / "cas")
        with pytest.raises(CorruptedDownloadError):
            await download_verified_to_cas(
                CDN,
                cas,
                expected_size=8,
                client=_FakeSession([_FakeResponse(200, body=body)]),
            )
        assert not cas.has(_sha256(body))

    @pytest.mark.asyncio
    async def test_download_bytes_variant(self) -> None:
        body = b"bytes"
        data, result = await download_verified_bytes(
            CDN,
            expected_sha256=_sha256(body),
            client=_FakeSession([_FakeResponse(200, body=body)]),
        )
        assert data == body
        assert result.sha1 == _sha1(body)


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

    async def __aexit__(self, *args: object) -> bool:
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


class TestModrinthBatchClient:
    @staticmethod
    def _hash(index: int, length: int = 128) -> str:
        return f"{index:0{length}x}"

    @pytest.mark.asyncio
    async def test_version_files_chunks_200(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        calls: list[tuple[str, str, dict]] = []

        async def fake_request(
            method: str, path: str, *, json_body: dict | None = None, **_kwargs: object
        ) -> dict:
            calls.append((method, path, json_body or {}))
            return {}

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        hashes = [self._hash(i) for i in range(450)]
        result = await provider.lookup_version_files_by_hashes(hashes)
        assert result == {}
        assert [len(call[2]["hashes"]) for call in calls] == [200, 200, 50]
        assert {call[1] for call in calls} == {"/version_files"}
        assert all(call[2]["algorithm"] == "sha512" for call in calls)

    @pytest.mark.asyncio
    async def test_version_update_chunks_and_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        calls: list[dict] = []

        async def fake_request(
            method: str, path: str, *, json_body: dict | None = None, **_kwargs: object
        ) -> dict:
            calls.append({"method": method, "path": path, **(json_body or {})})
            return {}

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        hashes = [self._hash(i) for i in range(450)]
        await provider.lookup_version_updates_by_hashes(
            hashes, loaders=["fabric"], game_versions=["1.21.4"]
        )
        assert [len(call["hashes"]) for call in calls] == [200, 200, 50]
        assert all(call["path"] == "/version_files/update" for call in calls)
        assert calls[0]["loaders"] == ["fabric"]
        assert calls[0]["game_versions"] == ["1.21.4"]
        assert calls[0]["version_types"] == ["release"]

    @pytest.mark.asyncio
    async def test_versions_and_projects_get_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        calls: list[tuple[str, str, dict]] = []

        async def fake_request(
            method: str, path: str, *, params: dict | None = None, **_kwargs: object
        ) -> list:
            calls.append((method, path, params or {}))
            return []

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        ids = [f"v{i}" for i in range(450)]
        await provider.get_versions_by_ids(ids)
        await provider.get_projects_by_ids(ids)
        version_calls = [c for c in calls if c[1] == "/versions"]
        project_calls = [c for c in calls if c[1] == "/projects"]
        assert [len(json.loads(c[2]["ids"])) for c in version_calls] == [200, 200, 50]
        assert [len(json.loads(c[2]["ids"])) for c in project_calls] == [200, 200, 50]
        assert all(c[0] == "GET" for c in calls)

    @pytest.mark.asyncio
    async def test_version_environment_ignores_server_side(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        digest = self._hash(1)

        async def fake_request(
            method: str, path: str, *, json_body: dict | None = None, **_kwargs: object
        ) -> dict:
            del method, json_body
            assert path == "/version_files"
            return {
                digest: {
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

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        matched = await provider.lookup_version_files_by_hashes([digest])
        assert matched[digest].environment == "client_only"

    @pytest.mark.asyncio
    async def test_environment_absent_even_if_server_side_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        digest = self._hash(2)

        async def fake_request(
            method: str, path: str, *, json_body: dict | None = None, **_kwargs: object
        ) -> dict:
            del method, path, json_body
            return {
                digest: {
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
        matched = await provider.lookup_version_files_by_hashes([digest])
        assert matched[digest].environment is None

    @pytest.mark.asyncio
    async def test_projects_server_side_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        digest = self._hash(3)

        async def fake_lookup(
            _hashes: object, *, algorithm: str = "sha512"
        ) -> dict[str, ModrinthVersionRecord]:
            del algorithm
            return {
                digest: ModrinthVersionRecord(
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

        async def fake_projects(
            _project_ids: object,
        ) -> dict[str, ModrinthProjectMeta]:
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
        client_only, matched, projects = await provider.classify_client_only_jars_by_sha512(
            [digest]
        )
        assert client_only == {digest}
        assert digest in matched
        assert projects["proj-3"].server_side == "unsupported"

    @pytest.mark.asyncio
    async def test_batch_methods_never_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        paths: list[str] = []

        async def fake_request(
            method: str, path: str, **_kwargs: object
        ) -> dict:
            del method
            paths.append(path)
            return {}

        monkeypatch.setattr(provider, "_request_json_with_ratelimit", fake_request)
        digest = self._hash(4)
        await provider.lookup_version_files_by_hashes([digest])
        await provider.lookup_version_updates_by_hashes(
            [digest], loaders=["fabric"], game_versions=["1.20.1"]
        )
        await provider.get_versions_by_ids(["ver-1"])
        await provider.get_projects_by_ids(["proj-1"])
        assert "/search" not in paths


class TestModrinthRateLimit:
    @pytest.mark.asyncio
    async def test_429_retries_with_exponential_backoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        session = _JsonSession(
            [
                _JsonResponse(429, headers={"Retry-After": "0"}),
                _JsonResponse(429, headers={"Retry-After": "0"}),
                _JsonResponse(200, payload={"ok": True}),
            ]
        )
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: session)
        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)
        result = await provider._request_json_with_ratelimit(
            "GET", "/versions", params={"ids": "[]"}
        )
        assert result == {"ok": True}
        assert len(session.calls) == 3
        assert sleeps == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_429_exhaustion_raises_download_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        session = _JsonSession(
            [_JsonResponse(429, headers={"Retry-After": "0"}) for _ in range(4)]
        )

        async def fake_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: session)
        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)
        with pytest.raises(DownloadError) as exc:
            await provider._request_json_with_ratelimit(
                "GET", "/versions", max_retries=3
            )
        assert exc.value.status == 429

    @pytest.mark.asyncio
    async def test_400_fails_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        session = _JsonSession([_JsonResponse(400)])
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: session)
        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)
        with pytest.raises(DownloadError) as exc:
            await provider._request_json_with_ratelimit("GET", "/projects")
        assert exc.value.status == 400
        assert len(session.calls) == 1
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_zero_remaining_cooldown_before_next_chunk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = ModrinthProvider()
        session = _JsonSession(
            [
                _JsonResponse(
                    200,
                    payload={},
                    headers={
                        "X-Ratelimit-Remaining": "0",
                        "X-Ratelimit-Reset": "30",
                    },
                ),
                _JsonResponse(200, payload={}),
            ]
        )
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(modrinth_module, "get_http_client", lambda: session)
        monkeypatch.setattr(modrinth_module.asyncio, "sleep", fake_sleep)
        await provider._request_json_with_ratelimit("GET", "/versions")
        await provider._request_json_with_ratelimit("GET", "/versions")
        assert len(session.calls) == 2
        assert sleeps and sleeps[0] > 0
