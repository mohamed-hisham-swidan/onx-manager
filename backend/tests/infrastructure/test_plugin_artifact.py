"""Tests for FakePlayer-Next plugin artifact fetching, digest verification, caching, and staging."""

import asyncio
import hashlib
import json
import traceback
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.core.config import AppSettings
from app.modules.server.application.services.jar_service import validate_jar
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
)
from app.modules.versioning.infrastructure.compatibility import (
    PLACEHOLDER_ARTIFACT,
    VerificationMode,
    is_fakeplayer_artifact_usable,
    resolve_verification_strategy,
)
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

TEST_JAR_DIGEST = "8de459b662d5598687fa177e6962ea98782a210ee4be17cf49f3e49830509618"


def _make_dummy_jar(path: Path, content: bytes = b"dummy content") -> bytes:
    """Create a minimal valid zip/jar file exceeding _MIN_JAR_SIZE (1 MiB)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        # Pad with dummy bytes so uncompressed file exceeds 1048576 bytes
        padding = content * 100 + b"0" * (1024 * 1024 + 1024)
        zf.writestr("payload.dat", padding)
    data = path.read_bytes()
    assert len(data) >= 1048576
    validate_jar(str(path))
    return data


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Metadata Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_release_metadata_happy_path() -> None:
    clear_release_cache()
    mock_payload = {
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

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    asset = await fetch_release_metadata(session=mock_session)
    assert isinstance(asset, ReleaseAsset)
    assert asset.name == "fakeplayer-0.4.4.jar"
    assert asset.sha256 == TEST_JAR_DIGEST
    assert asset.size == 1848353
    assert asset.version_label == "0.4.4"


@pytest.mark.asyncio
async def test_fetch_release_metadata_asset_missing_digest() -> None:
    clear_release_cache()
    mock_payload = {
        "tag_name": "v0.4.4",
        "assets": [
            {
                "name": "fakeplayer-0.4.4.jar",
                "browser_download_url": "https://github.com/fakeplayer.jar",
                "size": 1848353,
            }
        ],
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "no digest" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_malformed_digest() -> None:
    clear_release_cache()
    mock_payload = {
        "tag_name": "v0.4.4",
        "assets": [
            {
                "name": "fakeplayer-0.4.4.jar",
                "browser_download_url": "https://github.com/fakeplayer.jar",
                "size": 1848353,
                "digest": "sha256:not-a-valid-hex",
            }
        ],
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "no digest" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_multiple_matching_assets() -> None:
    clear_release_cache()
    mock_payload = {
        "tag_name": "v0.4.4",
        "assets": [
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
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "no unique fakeplayer jar asset" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_zero_matching_assets() -> None:
    clear_release_cache()
    mock_payload = {
        "tag_name": "v0.4.4",
        "assets": [
            {
                "name": "source.zip",
                "browser_download_url": "https://github.com/source.zip",
                "size": 1000,
            }
        ],
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "no unique fakeplayer jar asset" in res.reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_phrase"),
    [
        (403, "github rate limited"),
        (429, "github rate limited"),
        (404, "release not found"),
        (500, "http error: 500"),
    ],
)
async def test_fetch_release_metadata_http_error_codes(
    status_code: int, expected_phrase: str
) -> None:
    clear_release_cache()
    mock_resp = AsyncMock()
    mock_resp.status = status_code
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert expected_phrase in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_redirect_rejected() -> None:
    clear_release_cache()
    mock_resp = AsyncMock()
    mock_resp.status = 302
    mock_resp.headers = {"Location": "https://api.github.com/somewhere"}
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "release metadata redirect not allowed"
    # Ensure allow_redirects=False was passed
    call_kwargs = mock_session.get.call_args.kwargs
    assert call_kwargs.get("allow_redirects") is False


@pytest.mark.asyncio
async def test_fetch_release_metadata_network_error() -> None:
    clear_release_cache()
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = aiohttp.ClientError("network failure")

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "network error: ClientError" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_timeout() -> None:
    clear_release_cache()
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = TimeoutError()

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "network error: TimeoutError" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_invalid_json() -> None:
    clear_release_cache()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.side_effect = ValueError("invalid json")
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await fetch_release_metadata(session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "invalid json" in res.reason


@pytest.mark.asyncio
async def test_fetch_release_metadata_ttl_cache_hit() -> None:
    clear_release_cache()
    mock_payload = {
        "tag_name": "v0.4.4",
        "assets": [
            {
                "name": "fakeplayer-0.4.4.jar",
                "browser_download_url": "https://github.com/fake.jar",
                "size": 1848353,
                "digest": f"sha256:{TEST_JAR_DIGEST}",
            }
        ],
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_payload)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res1 = await fetch_release_metadata(session=mock_session)
    assert isinstance(res1, ReleaseAsset)
    assert mock_session.get.call_count == 1

    # Second call uses cache, no network call
    res2 = await fetch_release_metadata(session=mock_session)
    assert isinstance(res2, ReleaseAsset)
    assert mock_session.get.call_count == 1


# ---------------------------------------------------------------------------
# Download & Cache Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_miss_then_hit(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-miss")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/yigemingzii/releases/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    class MockContent:
        def __init__(self, data: bytes):
            self.data = data
            self.read_called = False

        async def read(self, _n: int = -1):
            if self.read_called:
                return b""
            self.read_called = True
            return self.data

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {}
    mock_resp.content = MockContent(jar_bytes)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    # Miss: downloads and caches
    cached_path = await ensure_plugin_artifact(
        data_root=tmp_path, asset=asset, session=mock_session
    )
    assert isinstance(cached_path, Path)
    assert cached_path.exists()
    assert cached_path == tmp_path / "artifacts" / digest / "fakeplayer.jar"
    assert mock_session.get.call_count == 1

    # Hit: file exists and hash matches -> no network call
    mock_session.get.reset_mock()
    hit_path = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert hit_path == cached_path
    assert mock_session.get.call_count == 0


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_corrupted_cache_redownloads(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-fresh")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    # Poison cache
    cache_file = tmp_path / "artifacts" / digest / "fakeplayer.jar"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"corrupted-data")

    class MockContent:
        def __init__(self, data: bytes):
            self.data = data
            self.read_called = False

        async def read(self, _n: int = -1):
            if self.read_called:
                return b""
            self.read_called = True
            return self.data

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {}
    mock_resp.content = MockContent(jar_bytes)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, Path)
    assert res.read_bytes() == jar_bytes
    assert mock_session.get.call_count == 1


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_digest_mismatch_cleans_part(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-mismatch")

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256="0000000000000000000000000000000000000000000000000000000000000000",
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    class MockContent:
        def __init__(self, data: bytes):
            self.data = data
            self.read_called = False

        async def read(self, _n: int = -1):
            if self.read_called:
                return b""
            self.read_called = True
            return self.data

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {}
    mock_resp.content = MockContent(jar_bytes)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "digest mismatch" in res.reason
    parts = list(tmp_path.glob("**/*.part"))
    assert len(parts) == 0


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_validate_jar_failure(tmp_path: Path) -> None:
    # 30-byte payload with matching digest, but fails validate_jar
    bad_bytes = b"PK\x03\x04fakeplayer-placeholder-too"
    digest = _compute_sha256(bad_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(bad_bytes),
        version_label="0.4.4",
    )

    class MockContent:
        def __init__(self, data: bytes):
            self.data = data
            self.read_called = False

        async def read(self, _n: int = -1):
            if self.read_called:
                return b""
            self.read_called = True
            return self.data

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {}
    mock_resp.content = MockContent(bad_bytes)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "invalid jar" in res.reason


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_size_cap_rejected(tmp_path: Path) -> None:
    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=TEST_JAR_DIGEST,
        size=20 * 1024 * 1024,  # 20 MiB > 16 MiB cap
        version_label="0.4.4",
    )
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "size limit" in res.reason
    assert mock_session.get.call_count == 0


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_disallowed_host_rejected(tmp_path: Path) -> None:
    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://evil.attacker.com/fakeplayer.jar",
        sha256=TEST_JAR_DIGEST,
        size=1000,
        version_label="0.4.4",
    )
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "download redirect host not allowed: evil.attacker.com"
    assert mock_session.get.call_count == 0


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_concurrent_calls(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-concurrent")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    class MockContent:
        def __init__(self, data: bytes):
            self.data = data

        async def read(self, _n: int = -1):
            await asyncio.sleep(0.01)
            d = self.data
            self.data = b""
            return d

    def make_cm():
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.content = MockContent(jar_bytes)
        cm = AsyncMock()
        cm.__aenter__.return_value = mock_resp
        return cm

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = lambda *_args, **_kwargs: make_cm()

    res1, res2 = await asyncio.gather(
        ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session),
        ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session),
    )
    assert isinstance(res1, Path)
    assert isinstance(res2, Path)
    assert res1.exists() and res2.exists()
    assert res1.read_bytes() == jar_bytes
    # No partial files left behind
    parts = list(tmp_path.glob("**/*.part"))
    assert len(parts) == 0


# ---------------------------------------------------------------------------
# Staging Tests
# ---------------------------------------------------------------------------


def test_stage_plugin_artifact_copies_one_jar_sanitized_name(tmp_path: Path) -> None:
    cache_jar = tmp_path / "artifacts" / "fakeplayer.jar"
    _make_dummy_jar(cache_jar, b"real-jar-bits")

    test_dir = tmp_path / "test_dir"
    plugins_dir = test_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    # Pre-existing stale fakeplayer jar and foreign jar
    (plugins_dir / "fakeplayer-old-stale.jar").write_bytes(b"old")
    (plugins_dir / "EssentialsX-2.20.1.jar").write_bytes(b"keep-me")

    staged = stage_plugin_artifact(
        cached=cache_jar,
        test_dir=test_dir,
        version_label="0.4.4",
        asset_name="../../fake player 0.4.4.jar",
    )
    assert staged.exists()
    # Path separators & spaces sanitized
    assert "/" not in staged.name
    assert ".." not in staged.name
    assert " " not in staged.name

    # Only ONE fakeplayer jar remains
    fp_jars = list(plugins_dir.glob("fakeplayer*.jar"))
    assert len(fp_jars) == 1
    assert fp_jars[0] == staged

    # Foreign jar intact
    assert (plugins_dir / "EssentialsX-2.20.1.jar").exists()
    # CommandAPI jar was never staged
    assert len(list(plugins_dir.glob("CommandAPI*.jar"))) == 0


@pytest.mark.parametrize(
    "raw_name",
    [
        "../x.jar",
        r"..\x.jar",
        "/etc/passwd.jar",
        "a b.jar",
        "fakeplayer-0.4.4.jar",
        "плагин-é.jar",
        "a" * 300 + ".jar",
        "myplugin",
        "bad\x00\x07name.jar",
        "",
        ".jar",
        "   ",
        "...jar",
    ],
)
def test_stage_plugin_artifact_untrusted_filename_sanitization(
    tmp_path: Path, raw_name: str
) -> None:
    cache_jar = tmp_path / "artifacts" / "fakeplayer.jar"
    _make_dummy_jar(cache_jar, b"real-jar-bits")

    test_dir = tmp_path / "test_dir"
    plugins_dir = test_dir / "plugins"

    staged = stage_plugin_artifact(
        cached=cache_jar,
        test_dir=test_dir,
        version_label="0.4.4",
        asset_name=raw_name,
    )
    assert staged.exists()
    # 1. Lands directly inside plugins_dir (resolved parent == plugins_dir)
    assert staged.resolve().parent == plugins_dir.resolve()
    # 2. Matches ^[A-Za-z0-9._-]+\.jar$
    import re

    assert re.match(r"^[A-Za-z0-9._-]+\.jar$", staged.name) is not None
    # 3. Length <= 100
    assert len(staged.name) <= 100
    # 4. Never a dotfile-only or empty name (fallback fakeplayer.jar)
    assert not staged.name.startswith(".")
    assert staged.name != ".jar"
    if raw_name in ("", ".jar", "   ", "...jar"):
        assert staged.name == "fakeplayer.jar"


def test_stage_plugin_artifact_b5_pinned_behaviors(tmp_path: Path) -> None:
    """Pin intentional B5 behaviors: prefixing, non-ascii collapse, length cap."""
    cache_jar = tmp_path / "artifacts" / "fakeplayer.jar"
    _make_dummy_jar(cache_jar, b"pinned-jar-bits")
    test_dir = tmp_path / "test_dir"

    # (a) a name not starting with "fakeplayer" gets prefix "fakeplayer-"
    staged_a = stage_plugin_artifact(cached=cache_jar, test_dir=test_dir, asset_name="x.jar")
    assert staged_a.name == "fakeplayer-x.jar"

    # (b) a non-ASCII-only name collapses to "fakeplayer.jar"
    staged_b = stage_plugin_artifact(cached=cache_jar, test_dir=test_dir, asset_name="плагин.jar")
    assert staged_b.name == "fakeplayer.jar"

    # (c) a 300-char name -> len <= 100 and endswith ".jar"
    staged_c = stage_plugin_artifact(
        cached=cache_jar, test_dir=test_dir, asset_name="a" * 300 + ".jar"
    )
    assert len(staged_c.name) <= 100
    assert len(staged_c.name) == 100
    assert staged_c.name.endswith(".jar")


# ---------------------------------------------------------------------------
# B2 Redirect Host Validation Tests (Failing-First)
# ---------------------------------------------------------------------------


class _MockResponseContext:
    def __init__(
        self,
        status: int,
        headers: dict[str, str] | None = None,
        data: bytes = b"",
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

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_allowed_redirect_success(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-redirect-allowed")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/yigemingzii/releases/download/v0.4.4/fakeplayer-0.4.4.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    redirect_url = (
        "https://release-assets.githubusercontent.com/github-production-release-asset/123/uuid"
        "?sig=S3CR3T&jwt=S3CR3T"
    )

    def mock_get(url: str, **_kwargs):
        if url == asset.download_url:
            return _MockResponseContext(302, {"Location": redirect_url})
        if url == redirect_url:
            return _MockResponseContext(200, data=jar_bytes)
        raise ValueError(f"Unexpected url: {url}")

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, Path)
    assert res.exists()
    assert res.read_bytes() == jar_bytes
    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_to_unlisted_host(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-evil")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    evil_url = "https://evil.example/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {"Location": evil_url})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    with caplog.at_level("DEBUG"):
        res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "download redirect host not allowed: evil.example"
    assert "sig=" not in res.reason
    assert "jwt=" not in res.reason
    assert "?" not in res.reason
    assert "fakeplayer.jar" not in res.reason
    assert "S3CR3T" not in caplog.text


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_to_http_downgrade(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-http")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    http_url = "http://release-assets.githubusercontent.com/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {"Location": http_url})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    with caplog.at_level("DEBUG"):
        res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "sig=" not in res.reason
    assert "jwt=" not in res.reason
    assert "?" not in res.reason
    assert "S3CR3T" not in caplog.text


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_suffix_trick(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-suffix")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    suffix_url = "https://github.com.evil.example/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {"Location": suffix_url})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    with caplog.at_level("DEBUG"):
        res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "download redirect host not allowed: github.com.evil.example"
    assert "sig=" not in res.reason
    assert "jwt=" not in res.reason
    assert "?" not in res.reason
    assert "S3CR3T" not in caplog.text


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_userinfo(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-userinfo")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    userinfo_url = (
        "https://user@release-assets.githubusercontent.com/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"
    )

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {"Location": userinfo_url})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    with caplog.at_level("DEBUG"):
        res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "sig=" not in res.reason
    assert "jwt=" not in res.reason
    assert "?" not in res.reason
    assert "S3CR3T" not in caplog.text


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_non_default_port(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-port")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    port_url = (
        "https://release-assets.githubusercontent.com:8443/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"
    )

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {"Location": port_url})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    with caplog.at_level("DEBUG"):
        res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert "sig=" not in res.reason
    assert "jwt=" not in res.reason
    assert "?" not in res.reason
    assert "S3CR3T" not in caplog.text


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_explicit_port_443(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-port-443")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    port_443_url = (
        "https://release-assets.githubusercontent.com:443/fakeplayer.jar?sig=S3CR3T&jwt=S3CR3T"
    )

    def mock_get(url: str, **_kwargs):
        if url == asset.download_url:
            return _MockResponseContext(302, {"Location": port_443_url})
        if url == port_443_url:
            return _MockResponseContext(200, data=jar_bytes)
        raise ValueError(f"Unexpected url: {url}")

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, Path)
    assert res.exists()
    assert res.read_bytes() == jar_bytes
    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_too_many_redirects(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-loops")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/hop0",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    def mock_get(url: str, **_kwargs):
        # 4 consecutive redirects between allowed hosts
        if url == "https://github.com/hop0":
            return _MockResponseContext(302, {"Location": "https://github.com/hop1"})
        if url == "https://github.com/hop1":
            return _MockResponseContext(302, {"Location": "https://github.com/hop2"})
        if url == "https://github.com/hop2":
            return _MockResponseContext(302, {"Location": "https://github.com/hop3"})
        if url == "https://github.com/hop3":
            return _MockResponseContext(302, {"Location": "https://github.com/hop4"})
        return _MockResponseContext(200, data=jar_bytes)

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "too many redirects"


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_redirect_without_location(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-nolocation")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(302, {})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == "redirect without location"


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_relative_location_resolved_and_validated(
    tmp_path: Path,
) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-relative")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/release/download",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    def mock_get(url: str, **_kwargs):
        if url == "https://github.com/release/download":
            return _MockResponseContext(
                302,
                {"Location": "/downloads/fakeplayer-0.4.4.jar?sig=S3CR3T&jwt=S3CR3T"},
            )
        if url == "https://github.com/downloads/fakeplayer-0.4.4.jar?sig=S3CR3T&jwt=S3CR3T":
            return _MockResponseContext(200, data=jar_bytes)
        raise ValueError(f"Unexpected url: {url}")

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, Path)
    assert res.exists()
    assert res.read_bytes() == jar_bytes
    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [300, 304])
async def test_ensure_plugin_artifact_unsupported_3xx(tmp_path: Path, status_code: int) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-3xx")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(status_code, {"Location": "https://github.com/other"})

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, ArtifactFailure)
    assert res.reason == f"http error: {status_code}"


@pytest.mark.asyncio
async def test_ensure_plugin_artifact_direct_200_allowed_host(tmp_path: Path) -> None:
    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"content-direct-200")
    digest = _compute_sha256(jar_bytes)

    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/direct/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    def mock_get(_url: str, **_kwargs):
        return _MockResponseContext(200, data=jar_bytes)

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.side_effect = mock_get

    res = await ensure_plugin_artifact(data_root=tmp_path, asset=asset, session=mock_session)
    assert isinstance(res, Path)
    assert res.exists()
    assert res.read_bytes() == jar_bytes
    assert mock_session.get.call_count == 1


# ---------------------------------------------------------------------------
# Integration Tests through run_test
# ---------------------------------------------------------------------------


def _setup_test_spec(
    tmp_path: Path,
    test_id: str = "t-fp-fix2b",
    bot_count: int = 5,
) -> tuple[TestSpec, Path]:
    server_dir = tmp_path / "server"
    server_dir.mkdir(parents=True, exist_ok=True)
    manifest = CommitManifest(
        server_type="paper",
        minecraft_version="1.21.1",
        configs={"server.properties": "server-port=25565\n"},
    )
    commit = ServerCommit(
        id=f"c-{test_id}",
        server_id="srv-fix2b",
        message="test commit",
        manifest=manifest,
    )
    spec = TestSpec(
        test_id=test_id,
        server_id="srv-fix2b",
        server_dir=str(server_dir),
        commit=commit,
        bot_config=BotVerificationConfig(bot_count=bot_count, bot_tech=BotTech.FAKEPLAYER_NEXT),
    )
    test_dir = server_dir / ".onx" / "tests" / test_id
    return spec, test_dir


@pytest.mark.asyncio
async def test_run_test_artifact_failure_downgrades_to_smoke(tmp_path: Path) -> None:
    runner = DockerTestExecutionRunner()
    spec, test_dir = _setup_test_spec(tmp_path)

    docker_run_env: dict[str, str] | None = None
    docker_run_cmd: list[str] | None = None

    def mock_subprocess(cmd, **kwargs):
        nonlocal docker_run_env, docker_run_cmd
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "docker" in cmd and "run" in cmd:
            docker_run_cmd = cmd
            docker_run_env = {}
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    val = cmd[i + 1]
                    if "=" in val:
                        k, v = val.split("=", 1)
                        docker_run_env[k] = v
                    else:
                        docker_run_env[val] = ""
            proc_env = kwargs.get("env") or {}
            for k, v in proc_env.items():
                if k.startswith("RCON_"):
                    docker_run_env[f"PROC_{k}"] = v
            logs_dir = test_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "latest.log").write_text(
                "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n",
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
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    mock_ensure = AsyncMock(return_value=ArtifactFailure("release asset has no digest"))

    saved_strats: list = []
    orig_downgrade = runner._downgrade_to_smoke

    def capture_downgrade(*args, **kwargs):
        s = orig_downgrade(*args, **kwargs)
        saved_strats.append(s)
        return s

    with (
        patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
        patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
        patch("subprocess.run", side_effect=mock_subprocess),
        patch.object(runner, "_downgrade_to_smoke", side_effect=capture_downgrade),
        patch(
            "app.modules.versioning.infrastructure.plugin_artifact.ensure_plugin_artifact",
            mock_ensure,
        ),
        patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock) as mock_persist,
    ):
        handle = await runner.run_test(spec)
        assert handle.status in ("BOOTING", "RUNNING")
        res = await handle.wait_for_completion()

    # 1. ensure_plugin_artifact was awaited exactly once
    mock_ensure.assert_awaited_once()

    # 2. Strategy used for the run is SMOKE_TEST with downgraded_from == "fakeplayer_next"
    assert res is not None
    expected_reason = "pre-launch step failed: artifact staging/check: release asset has no digest"
    assert res.failure_reason == expected_reason

    assert len(saved_strats) == 1
    strat_res = saved_strats[0]
    assert strat_res.mode == VerificationMode.SMOKE_TEST
    assert strat_res.driver != "fakeplayer_next"
    assert strat_res.driver == "none"
    assert strat_res.downgraded_from == "fakeplayer_next"

    mock_persist.assert_awaited_once()
    persist_kwargs = mock_persist.await_args.kwargs
    assert persist_kwargs.get("failure_reason") == expected_reason
    evidence = persist_kwargs.get("evidence_bundle") or {}
    assertions = evidence.get("assertions", {})
    assert assertions.get("strategy_downgraded_from") == "fakeplayer_next"
    assert assertions.get("downgrade_reason") == expected_reason

    # 3. NO MODRINTH_PROJECTS / RCON_* in docker run env
    assert docker_run_env is not None
    assert "MODRINTH_PROJECTS" not in docker_run_env
    assert not any(k.startswith("RCON_") or k.startswith("PROC_RCON_") for k in docker_run_env)

    # 4. resolve_docker_image result is used
    expected_image, _ = resolve_test_docker_image(
        minecraft_version="1.21.1",
        strategy=None,
    )
    assert docker_run_cmd is not None
    assert any(expected_image in arg for arg in docker_run_cmd)


@pytest.mark.asyncio
async def test_run_test_artifact_success_keeps_fakeplayer_next_and_stages_before_docker_run(
    tmp_path: Path,
) -> None:
    runner = DockerTestExecutionRunner()
    spec, test_dir = _setup_test_spec(tmp_path)

    cached_jar = tmp_path / "cached_fakeplayer.jar"
    _make_dummy_jar(cached_jar, b"verified-real-plugin")

    jar_present_before_docker_run = False
    docker_run_env: dict[str, str] | None = None
    docker_run_cmd: list[str] | None = None

    def mock_subprocess(cmd, **_kwargs):
        nonlocal jar_present_before_docker_run, docker_run_env, docker_run_cmd
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "docker" in cmd and "run" in cmd:
            docker_run_cmd = cmd
            docker_run_env = {}
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    val = cmd[i + 1]
                    if "=" in val:
                        k, v = val.split("=", 1)
                        docker_run_env[k] = v
                    else:
                        docker_run_env[val] = ""
            plugins = list((test_dir / "plugins").glob("fakeplayer*.jar"))
            if plugins and plugins[0].exists():
                jar_present_before_docker_run = True
            logs_dir = test_dir / "logs"
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
        if "rcon-cli" in cmd_str:
            return MagicMock(returncode=0, stdout="OK\n", stderr="")
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    mock_ensure = AsyncMock(return_value=cached_jar)

    saved_resolved_strats: list = []

    def spy_resolve(*args, **kwargs):
        s = resolve_verification_strategy(*args, **kwargs)
        saved_resolved_strats.append(s)
        return s

    with (
        patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
        patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
        patch("subprocess.run", side_effect=mock_subprocess),
        patch(
            "app.modules.versioning.infrastructure.test_runner.resolve_verification_strategy",
            side_effect=spy_resolve,
        ),
        patch(
            "app.modules.versioning.infrastructure.plugin_artifact.ensure_plugin_artifact",
            mock_ensure,
        ),
        patch.object(runner, "_persist_test_outcome", new_callable=AsyncMock) as mock_persist,
    ):
        handle = await runner.run_test(spec)
        assert handle.status in ("BOOTING", "RUNNING")
        res = await handle.wait_for_completion()

    # 1. ensure_plugin_artifact was awaited exactly once
    mock_ensure.assert_awaited_once()

    # 2. Strategy driver is "fakeplayer_next" (not downgraded)
    assert res is not None
    assert res.passed is True
    assert len(saved_resolved_strats) >= 1
    strat_succ = saved_resolved_strats[-1]
    assert strat_succ.mode == VerificationMode.FULL_BOT
    assert strat_succ.driver == "fakeplayer_next"
    assert strat_succ.driver != "none"
    assert strat_succ.downgraded_from is None
    mock_persist.assert_awaited_once()
    persist_kwargs = mock_persist.await_args.kwargs
    evidence = persist_kwargs.get("evidence_bundle") or {}
    assertions = evidence.get("assertions", {})
    assert assertions.get("strategy_downgraded_from") is None

    # 3. Exactly one fakeplayer*.jar in <test_dir>/plugins/
    fp_jars = list((test_dir / "plugins").glob("fakeplayer*.jar"))
    assert len(fp_jars) == 1
    assert fp_jars[0].exists()

    # 4. Jar present before docker run
    assert jar_present_before_docker_run is True

    # 5. Docker run env contains MODRINTH_PROJECTS=commandapi
    assert docker_run_env is not None
    assert docker_run_env.get("MODRINTH_PROJECTS") == "commandapi"

    # 6. Image is the pinned itzg image
    expected_image = AppSettings().docker_test_image
    assert docker_run_cmd is not None
    assert any(expected_image in arg for arg in docker_run_cmd)


# ---------------------------------------------------------------------------
# Hygiene & Secret Propagation Tests (Item 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_propagation_through_real_run_path_redirect(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Real run path where download redirects to an unlisted host with signed query."""
    runner = DockerTestExecutionRunner()
    spec, test_dir = _setup_test_spec(tmp_path, test_id="t-sec-redir")

    secret_query = "sig=S3CR3T&jwt=S3CR3T"
    fake_asset_url = "https://github.com/releases/download/v0.4.4/fakeplayer-0.4.4.jar"
    evil_redirect_url = f"https://evil.example/fakeplayer.jar?{secret_query}"

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

    def mock_get(url: str, **_kwargs):
        if url == GITHUB_LATEST_RELEASE_URL:
            resp = AsyncMock()
            resp.status = 200
            resp.headers = {}
            resp.json = AsyncMock(return_value=meta_payload)
            cm = AsyncMock()
            cm.__aenter__.return_value = resp
            return cm
        if url == fake_asset_url:
            return _MockResponseContext(302, {"Location": evil_redirect_url})
        raise ValueError(f"Unexpected URL: {url}")

    def mock_subprocess(cmd, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "docker" in cmd and "run" in cmd:
            logs_dir = test_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "latest.log").write_text(
                "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n",
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
        return MagicMock(returncode=0, stdout="container-123\n", stderr="")

    captured_failures: list[ArtifactFailure] = []
    orig_ensure = ensure_plugin_artifact

    async def spied_ensure(*args, **kwargs):
        res_art = await orig_ensure(*args, **kwargs)
        if isinstance(res_art, ArtifactFailure):
            captured_failures.append(res_art)
        return res_art

    captured_exceptions: list[BaseException] = []
    orig_downgrade = runner._downgrade_to_smoke

    def capture_downgrade(step_name, exc, *args, **kwargs):
        captured_exceptions.append(exc)
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
        handle = await runner.run_test(spec)
        res = await handle.wait_for_completion()

    assert res is not None
    assert res.failure_reason is not None
    mock_persist.assert_awaited_once()
    evidence_bundle = mock_persist.await_args.kwargs.get("evidence_bundle") or {}
    evidence_str = json.dumps(evidence_bundle)

    secret_tokens = ("S3CR3T", "sig=", "jwt=", "?")

    # 1. failure_reason
    for token in secret_tokens:
        assert token not in res.failure_reason

    # 2. json.dumps(evidence_bundle)
    for token in secret_tokens:
        assert token not in evidence_str

    # 3. caplog.text (ALL loggers)
    for token in secret_tokens:
        assert token not in caplog.text

    # 4. str(failure), repr(failure)
    assert len(captured_failures) == 1
    failure = captured_failures[0]
    for token in secret_tokens:
        assert token not in str(failure)
        assert token not in repr(failure)

    # 5. str/repr of every exception the code path captured or raised
    for record in caplog.records:
        if record.exc_info and record.exc_info[1] is not None:
            captured_exceptions.append(record.exc_info[1])

    assert len(captured_exceptions) >= 1
    for exc in captured_exceptions:
        exc_str = str(exc)
        exc_repr = repr(exc)
        formatted_tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        for token in secret_tokens:
            assert token not in exc_str
            assert token not in exc_repr
            assert token not in formatted_tb


@pytest.mark.asyncio
async def test_secret_propagation_through_real_run_path_network_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Real run path where download raises network error containing signed query."""
    runner = DockerTestExecutionRunner()
    spec, test_dir = _setup_test_spec(tmp_path, test_id="t-sec-neterr")

    secret_query = "sig=S3CR3T&jwt=S3CR3T"
    fake_asset_url = "https://github.com/releases/download/v0.4.4/fakeplayer-0.4.4.jar"
    sensitive_url = f"https://release-assets.githubusercontent.com/asset.jar?{secret_query}"

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

    def mock_get(url: str, **_kwargs):
        if url == GITHUB_LATEST_RELEASE_URL:
            resp = AsyncMock()
            resp.status = 200
            resp.headers = {}
            resp.json = AsyncMock(return_value=meta_payload)
            cm = AsyncMock()
            cm.__aenter__.return_value = resp
            return cm
        if url == fake_asset_url:
            raise aiohttp.ClientConnectionError(f"Cannot connect to host {sensitive_url}")
        raise ValueError(f"Unexpected URL: {url}")

    def mock_subprocess(cmd, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "docker" in cmd and "run" in cmd:
            logs_dir = test_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "latest.log").write_text(
                "[Server thread/INFO]: Done (1.0s)! For help, type 'help'\n",
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
        return MagicMock(returncode=0, stdout="container-123\n", stderr="")

    captured_failures: list[ArtifactFailure] = []
    orig_ensure = ensure_plugin_artifact

    async def spied_ensure(*args, **kwargs):
        res_art = await orig_ensure(*args, **kwargs)
        if isinstance(res_art, ArtifactFailure):
            captured_failures.append(res_art)
        return res_art

    captured_exceptions: list[BaseException] = []
    orig_downgrade = runner._downgrade_to_smoke

    def capture_downgrade(step_name, exc, *args, **kwargs):
        captured_exceptions.append(exc)
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
        handle = await runner.run_test(spec)
        res = await handle.wait_for_completion()

    assert res is not None
    assert res.failure_reason is not None
    mock_persist.assert_awaited_once()
    evidence_bundle = mock_persist.await_args.kwargs.get("evidence_bundle") or {}
    evidence_str = json.dumps(evidence_bundle)

    secret_tokens = ("S3CR3T", "sig=", "jwt=", "?")

    # 1. failure_reason
    for token in secret_tokens:
        assert token not in res.failure_reason

    # 2. json.dumps(evidence_bundle)
    for token in secret_tokens:
        assert token not in evidence_str

    # 3. caplog.text (ALL loggers)
    for token in secret_tokens:
        assert token not in caplog.text

    # 4. str(failure), repr(failure)
    assert len(captured_failures) == 1
    failure = captured_failures[0]
    for token in secret_tokens:
        assert token not in str(failure)
        assert token not in repr(failure)

    # 5. str/repr of every exception the code path captured or raised
    for record in caplog.records:
        if record.exc_info and record.exc_info[1] is not None:
            captured_exceptions.append(record.exc_info[1])

    assert len(captured_exceptions) >= 1
    for exc in captured_exceptions:
        exc_str = str(exc)
        exc_repr = repr(exc)
        formatted_tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        for token in secret_tokens:
            assert token not in exc_str
            assert token not in exc_repr
            assert token not in formatted_tb


@pytest.mark.asyncio
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
async def test_artifact_failure_details_never_populated_with_url(tmp_path: Path, case: str) -> None:
    """Drive real production paths of ensure_plugin_artifact / fetch_release_metadata

    across the failure matrix to assert details contains no URLs and repr(failure)
    exposes no sensitive parameters or URLs.
    """
    clear_release_cache()
    mock_session = MagicMock(spec=aiohttp.ClientSession)

    jar_file = tmp_path / "source.jar"
    jar_bytes = _make_dummy_jar(jar_file, b"matrix-dummy")
    digest = _compute_sha256(jar_bytes)
    asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://github.com/fakeplayer.jar",
        sha256=digest,
        size=len(jar_bytes),
        version_label="0.4.4",
    )

    if case == "no digest":
        payload = {
            "tag_name": "v0.4.4",
            "assets": [
                {
                    "name": "fakeplayer-0.4.4.jar",
                    "browser_download_url": "https://github.com/f.jar",
                    "size": 100,
                }
            ],
        }
        r = AsyncMock(status=200, json=AsyncMock(return_value=payload))
        cm = AsyncMock(__aenter__=AsyncMock(return_value=r))
        mock_session.get.return_value = cm
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "malformed digest":
        payload = {
            "tag_name": "v0.4.4",
            "assets": [
                {
                    "name": "fakeplayer-0.4.4.jar",
                    "browser_download_url": "https://github.com/f.jar",
                    "size": 100,
                    "digest": "invalid",
                }
            ],
        }
        r = AsyncMock(status=200, json=AsyncMock(return_value=payload))
        cm = AsyncMock(__aenter__=AsyncMock(return_value=r))
        mock_session.get.return_value = cm
        failure = await fetch_release_metadata(session=mock_session)
    elif case in ("404", "403", "429", "500"):
        r = AsyncMock(status=int(case))
        cm = AsyncMock(__aenter__=AsyncMock(return_value=r))
        mock_session.get.return_value = cm
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "network error":
        mock_session.get.side_effect = aiohttp.ClientConnectionError("Connection failed")
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "timeout":
        mock_session.get.side_effect = TimeoutError()
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "invalid JSON":
        r = AsyncMock(status=200, json=AsyncMock(side_effect=ValueError("bad json")))
        cm = AsyncMock(__aenter__=AsyncMock(return_value=r))
        mock_session.get.return_value = cm
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "metadata redirect":
        r = AsyncMock(status=302, headers={"Location": "https://api.github.com/other"})
        cm = AsyncMock(__aenter__=AsyncMock(return_value=r))
        mock_session.get.return_value = cm
        failure = await fetch_release_metadata(session=mock_session)
    elif case == "digest mismatch":
        mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(
            200, data=b"wrong content"
        )
        failure = await ensure_plugin_artifact(
            data_root=tmp_path, asset=asset, session=mock_session
        )
    elif case == "size cap":
        large_asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://github.com/fakeplayer.jar",
            sha256=digest,
            size=MAX_PLUGIN_ARTIFACT_SIZE_BYTES + 1,
            version_label="0.4.4",
        )
        failure = await ensure_plugin_artifact(
            data_root=tmp_path, asset=large_asset, session=mock_session
        )
    elif case == "host not allowed":
        bad_asset = ReleaseAsset(
            name="fakeplayer-0.4.4.jar",
            download_url="https://evil.example.com/fakeplayer.jar",
            sha256=digest,
            size=100,
            version_label="0.4.4",
        )
        failure = await ensure_plugin_artifact(
            data_root=tmp_path, asset=bad_asset, session=mock_session
        )
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
    elif case == "unsupported 3xx":
        mock_session.get.side_effect = lambda _u, **_kw: _MockResponseContext(
            300, {"Location": "https://github.com/other"}
        )
        failure = await ensure_plugin_artifact(
            data_root=tmp_path, asset=asset, session=mock_session
        )
    else:
        raise ValueError(f"Unknown matrix case: {case}")

    assert isinstance(failure, ArtifactFailure)
    assert failure.details is None or "http" not in failure.details.lower()
    for tok in ("http://", "https://", "sig=", "jwt=", "?"):
        assert tok not in repr(failure)
        assert tok not in str(failure)
    if not failure.reason.startswith("http error:"):
        assert "http" not in repr(failure)
        assert "http" not in str(failure)


@pytest.mark.asyncio
async def test_failure_reasons_contain_no_sensitive_data(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Production-driven test verifying that real failure paths never leak sensitive tokens."""
    clear_release_cache()

    # 1. Production metadata path where payload download URL contains secrets
    secret_url = "https://api.github.com/fakeplayer.jar?token=SECRET&sig=S3CR3T&jwt=JWT_TOKEN"
    payload = {
        "tag_name": "v0.4.4",
        "assets": [
            {
                "name": "fakeplayer-0.4.4.jar",
                "browser_download_url": secret_url,
                "size": 1848353,
                # Missing digest triggers ArtifactFailure
            }
        ],
    }
    mock_resp = AsyncMock(status=200, json=AsyncMock(return_value=payload))
    mock_cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_cm

    with caplog.at_level("DEBUG"):
        failure_meta = await fetch_release_metadata(session=mock_session)

    assert isinstance(failure_meta, ArtifactFailure)
    assert failure_meta.details is None
    for token in ("SECRET", "S3CR3T", "token", "sig=", "jwt=", "?", "http"):
        assert token not in str(failure_meta)
        assert token not in repr(failure_meta)
        assert token not in failure_meta.reason
        assert token not in caplog.text

    # 2. Production artifact download path with sensitive query parameters
    sensitive_asset = ReleaseAsset(
        name="fakeplayer-0.4.4.jar",
        download_url="https://evil.example.com/asset.jar?token=SECRET&sig=S3CR3T&jwt=JWT_TOKEN",
        sha256="8de459b662d5598687fa177e6962ea98782a210ee4be17cf49f3e49830509618",
        size=1024,
        version_label="0.4.4",
    )
    with caplog.at_level("DEBUG"):
        failure_art = await ensure_plugin_artifact(
            data_root=tmp_path, asset=sensitive_asset, session=mock_session
        )

    assert isinstance(failure_art, ArtifactFailure)
    assert failure_art.details is None
    for token in ("SECRET", "S3CR3T", "token", "sig=", "jwt=", "?"):
        assert token not in str(failure_art)
        assert token not in repr(failure_art)
        assert token not in failure_art.reason
        assert token not in caplog.text


# ---------------------------------------------------------------------------
# Regression: Fix 1 placeholder test still passes
# ---------------------------------------------------------------------------


def test_fix1_placeholder_still_rejected(tmp_path: Path) -> None:
    ph = tmp_path / "fakeplayer-placeholder.jar"
    ph.write_bytes(PLACEHOLDER_ARTIFACT)
    usable, reason = is_fakeplayer_artifact_usable(ph)
    assert usable is False
    assert reason is not None
    assert "placeholder" in reason.lower()
