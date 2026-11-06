"""FakePlayer-Next plugin artifact download, digest verification, cache, and staging.

Enforces DECISION-2026-09-18-003 §4:
- Fetches latest release metadata from GitHub API (v0.4.4+).
- Verifies sha256 digest against release asset 'digest' field (no trust-on-first-use).
- Content-addressable cache under <data_root>/artifacts/<sha256>/fakeplayer.jar.
- Atomic .part replace for safe concurrent downloads.
- Staged into <test_dir>/plugins/ with path containment and deduplication before container launch.
"""

import contextlib
import hashlib
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp

from app.modules.server.application.services.jar_service import validate_jar

logger = logging.getLogger(__name__)

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/yigemingzii/minecraft-fakeplayer-next/releases/latest"
)
RELEASE_CACHE_TTL_SECONDS: float = 300.0
MAX_PLUGIN_ARTIFACT_SIZE_BYTES: int = 16 * 1024 * 1024  # 16 MiB
ALLOWED_DOWNLOAD_HOSTS: frozenset[str] = frozenset(
    {
        "github.com",
        "release-assets.githubusercontent.com",
    }
)
MAX_REDIRECT_HOPS: int = 3
REDIRECT_STATUS_CODES: frozenset[int] = frozenset({301, 302, 303, 307, 308})


def _validate_download_url(url: str) -> tuple[bool, str]:
    """Validate download URL according to security policy.

    Scheme must be https, port default (None or 443), no userinfo,
    and host must be an exact match in ALLOWED_DOWNLOAD_HOSTS.
    Returns (True, "") or (False, error_reason).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid download url"

    if parsed.scheme != "https":
        if parsed.scheme == "http":
            return False, "download redirect scheme not allowed: http"
        return False, "download scheme not https"

    if parsed.username is not None or parsed.password is not None:
        return False, "download redirect userinfo not allowed"

    if parsed.port is not None and parsed.port != 443:
        return False, "download redirect port not allowed"

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        return False, f"download redirect host not allowed: {host}"

    return True, ""


@dataclass(frozen=True)
class ReleaseAsset:
    """Represents a verified binary asset descriptor from the GitHub release."""

    name: str
    download_url: str
    sha256: str
    size: int
    version_label: str


@dataclass(frozen=True)
class ArtifactFailure:
    """Typed failure descriptor ensuring secrets/bodies are never exposed in reason."""

    reason: str
    details: str | None = None

    def __str__(self) -> str:
        return f"ArtifactFailure(reason={self.reason!r})"


# Module-level TTL cache for release metadata
_RELEASE_CACHE: dict[str, tuple[float, ReleaseAsset]] = {}


def clear_release_cache() -> None:
    """Clear metadata cache for test isolation."""
    _RELEASE_CACHE.clear()


async def fetch_release_metadata(
    session: aiohttp.ClientSession | None = None,
) -> ReleaseAsset | ArtifactFailure:
    """Fetch and parse release metadata from GitHub with 300s TTL caching.

    Returns ReleaseAsset on success or ArtifactFailure with typed error reason.
    """
    now = time.monotonic()
    cached = _RELEASE_CACHE.get(GITHUB_LATEST_RELEASE_URL)
    if cached is not None:
        cached_time, asset = cached
        if now - cached_time < RELEASE_CACHE_TTL_SECONDS:
            return asset

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "onx-manager/0.1.0",
    }
    timeout = aiohttp.ClientTimeout(total=15.0)

    owns_session = session is None
    client_session = session or aiohttp.ClientSession()
    try:
        try:
            async with client_session.get(
                GITHUB_LATEST_RELEASE_URL,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
            ) as resp:
                if 300 <= resp.status < 400:
                    return ArtifactFailure(reason="release metadata redirect not allowed")
                if resp.status in (403, 429):
                    return ArtifactFailure(reason="github rate limited")
                if resp.status == 404:
                    return ArtifactFailure(reason="release not found")
                if resp.status >= 400:
                    return ArtifactFailure(reason=f"http error: {resp.status}")

                try:
                    payload = await resp.json()
                except Exception:
                    return ArtifactFailure(reason="invalid json")

        except TimeoutError:
            return ArtifactFailure(reason="network error: TimeoutError")
        except aiohttp.ClientError as exc:
            return ArtifactFailure(reason=f"network error: {type(exc).__name__}")
        except Exception as exc:
            return ArtifactFailure(reason=f"network error: {type(exc).__name__}")
    finally:
        if owns_session:
            await client_session.close()

    assets = payload.get("assets", [])
    matching: list[dict] = []
    for a in assets:
        name = a.get("name", "")
        if re.match(r"^fakeplayer-.*\.jar$", name, re.IGNORECASE):
            matching.append(a)

    if len(matching) != 1:
        return ArtifactFailure(reason="no unique fakeplayer jar asset")

    selected = matching[0]
    raw_digest = selected.get("digest")
    if not isinstance(raw_digest, str) or not re.match(r"^sha256:[0-9a-fA-F]{64}$", raw_digest):
        return ArtifactFailure(reason="release asset has no digest")

    sha256 = raw_digest.split(":", 1)[1].lower()
    tag_name = payload.get("tag_name", "")
    version_label = tag_name.lstrip("v") if tag_name else "latest"
    name = selected.get("name", "fakeplayer.jar")
    download_url = selected.get("browser_download_url", "")
    size = int(selected.get("size", 0))

    asset = ReleaseAsset(
        name=name,
        download_url=download_url,
        sha256=sha256,
        size=size,
        version_label=version_label,
    )
    _RELEASE_CACHE[GITHUB_LATEST_RELEASE_URL] = (now, asset)
    return asset


async def ensure_plugin_artifact(
    data_root: Path,
    asset: ReleaseAsset | None = None,
    session: aiohttp.ClientSession | None = None,
) -> Path | ArtifactFailure:
    """Ensure FakePlayer-Next plugin jar is cached locally by sha256 digest.

    Follows redirects manually up to MAX_REDIRECT_HOPS, validating scheme, host,
    port, and credentials on every hop without leaking sensitive query parameters.
    Returns Path to cached jar on success, or ArtifactFailure on validation failure.
    """
    if asset is None:
        fetched = await fetch_release_metadata(session=session)
        if isinstance(fetched, ArtifactFailure):
            return fetched
        asset = fetched

    expected_sha256 = asset.sha256.lower()

    # 1. Download host validation on initial URL
    current_url = asset.download_url
    valid, err_reason = _validate_download_url(current_url)
    if not valid:
        return ArtifactFailure(reason=err_reason)

    # 2. Asset size cap check
    if asset.size > MAX_PLUGIN_ARTIFACT_SIZE_BYTES:
        return ArtifactFailure(reason="asset exceeds size limit")

    cache_dir = data_root / "artifacts" / expected_sha256
    cache_path = cache_dir / "fakeplayer.jar"

    # 3. Cache hit: re-hash and verify
    if cache_path.is_file():
        h = hashlib.sha256()
        with open(cache_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        if h.hexdigest().lower() == expected_sha256:
            return cache_path
        # Corrupt cache: remove and re-download
        with contextlib.suppress(OSError):
            cache_path.unlink()

    cache_dir.mkdir(parents=True, exist_ok=True)
    part_path = cache_dir / f"fakeplayer.{uuid.uuid4().hex[:8]}.part"

    # 4. Miss: download to unique .part, compute sha256 and validate
    owns_session = session is None
    client_session = session or aiohttp.ClientSession()
    try:
        timeout = aiohttp.ClientTimeout(total=60.0, sock_read=30.0)
        hops = 0

        while True:
            # We enforce allow_redirects=False to inspect every hop manually
            async with client_session.get(
                current_url, timeout=timeout, allow_redirects=False
            ) as resp:
                if resp.status in REDIRECT_STATUS_CODES:
                    hops += 1
                    if hops > MAX_REDIRECT_HOPS:
                        return ArtifactFailure(reason="too many redirects")

                    headers = getattr(resp, "headers", {})
                    location = headers.get("Location") if hasattr(headers, "get") else None
                    if not isinstance(location, str) or not location.strip():
                        return ArtifactFailure(reason="redirect without location")

                    # Resolve relative/protocol-relative Location
                    next_url = urljoin(current_url, location.strip())
                    valid, err_reason = _validate_download_url(next_url)
                    if not valid:
                        return ArtifactFailure(reason=err_reason)

                    current_url = next_url
                    continue

                if resp.status != 200:
                    return ArtifactFailure(reason=f"http error: {resp.status}")

                headers = getattr(resp, "headers", {})
                content_length_hdr = (
                    headers.get("Content-Length") if hasattr(headers, "get") else None
                )
                if (
                    isinstance(content_length_hdr, str)
                    and content_length_hdr.strip().isdigit()
                    and int(content_length_hdr.strip()) > MAX_PLUGIN_ARTIFACT_SIZE_BYTES
                ):
                    return ArtifactFailure(reason="asset exceeds size limit")

                hasher = hashlib.sha256()
                total_read = 0
                size_exceeded = False

                with open(part_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(65536)
                        if not chunk:
                            break
                        total_read += len(chunk)
                        if total_read > MAX_PLUGIN_ARTIFACT_SIZE_BYTES:
                            size_exceeded = True
                            break
                        hasher.update(chunk)
                        f.write(chunk)

                if size_exceeded:
                    with contextlib.suppress(OSError):
                        part_path.unlink()
                    return ArtifactFailure(reason="asset exceeds size limit")

                # Successfully finished reading response body
                break

        computed_sha256 = hasher.hexdigest().lower()
        if computed_sha256 != expected_sha256:
            with contextlib.suppress(OSError):
                part_path.unlink()
            return ArtifactFailure(reason="digest mismatch")

        # 5. Validate jar structure
        try:
            validate_jar(str(part_path))
        except Exception as exc:
            with contextlib.suppress(OSError):
                part_path.unlink()
            return ArtifactFailure(reason=f"invalid jar: {type(exc).__name__}")

        # 6. Atomic move to final cache location
        os.replace(part_path, cache_path)
        return cache_path

    except TimeoutError:
        with contextlib.suppress(OSError):
            if part_path.exists():
                part_path.unlink()
        return ArtifactFailure(reason="network error: TimeoutError")
    except aiohttp.ClientError as exc:
        with contextlib.suppress(OSError):
            if part_path.exists():
                part_path.unlink()
        return ArtifactFailure(reason=f"network error: {type(exc).__name__}")
    except Exception as exc:
        with contextlib.suppress(OSError):
            if part_path.exists():
                part_path.unlink()
        return ArtifactFailure(reason=f"download failed: {type(exc).__name__}")
    finally:
        with contextlib.suppress(OSError):
            if part_path.exists():
                part_path.unlink()
        if owns_session:
            await client_session.close()


def stage_plugin_artifact(
    cached: Path,
    test_dir: Path,
    version_label: str = "latest",
    asset_name: str | None = None,
) -> Path:
    """Stage cached plugin jar into <test_dir>/plugins/ with containment and deduplication.

    Derives a sanitized filename conforming to ^[A-Za-z0-9._-]+\\.jar$ with length <= 100,
    guaranteeing containment inside plugins_dir and falling back to 'fakeplayer.jar' for
    empty or dotfile-only inputs.
    Returns the Path to the staged plugin jar.
    """
    raw = f"fakeplayer-{version_label}.jar" if asset_name is None else asset_name

    # 1. Normalize directory separators (/ and \\) and extract basename
    normalized = raw.replace("\\", "/")
    basename = normalized.split("/")[-1]

    # 2. Replace any character outside [A-Za-z0-9._-] with '_'
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", basename)

    # 3. Check stem and suffix
    stem = sanitized[:-4] if sanitized.lower().endswith(".jar") else sanitized

    # Strip leading dots from stem to prevent dotfiles
    stem = stem.lstrip(".")

    # 4. Fallback if empty, dotfile-only, or whitespace/punctuation-only
    if not stem or stem.strip("._-") == "":
        final_name = "fakeplayer.jar"
    else:
        if not stem.lower().startswith("fakeplayer"):
            stem = f"fakeplayer-{stem}"
        # Max length 100 chars (96 for stem + 4 for '.jar')
        stem = stem[:96]
        final_name = f"{stem}.jar"

    # Final safety check: if anything violates regex, fallback to fakeplayer.jar
    if not re.match(r"^[A-Za-z0-9._-]+\.jar$", final_name) or final_name.startswith("."):
        final_name = "fakeplayer.jar"

    plugins_dir = test_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    target_path = plugins_dir / final_name

    # Containment check: resolved parent must be plugins_dir
    if target_path.resolve().parent != plugins_dir.resolve():
        target_path = plugins_dir / "fakeplayer.jar"

    # Plain copy per Step 0a
    shutil.copy2(cached, target_path)

    # Deduplicate: remove any other fakeplayer jars in plugins_dir
    for candidate in plugins_dir.glob("fakeplayer*.jar"):
        if candidate.resolve() != target_path.resolve():
            with contextlib.suppress(OSError):
                candidate.unlink()

    return target_path
