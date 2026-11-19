"""Normative download host allow-list and hardened streaming downloader (P5.5).

The initial URL and every manually followed redirect hop are validated against
the 19-host normative allow-list. ``*.githubusercontent.com`` asset hosts are
accepted only when reached by redirect from a validated GitHub release download
URL. HTTPS, no userinfo, port 443, IDNA normalization, and literal IPv4/IPv6
rejection are enforced for every hop.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import os
import re
import socket
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    UntrustedDownloadHostError,
)
from app.core.http_client import get_http_client
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas

MAX_REDIRECT_HOPS = 5
DEFAULT_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

DEFAULT_ALLOWED_DOWNLOAD_HOSTS: frozenset[str] = frozenset(
    {
        "cdn.modrinth.com",
        "edge.forgecdn.net",
        "mediafilez.forgecdn.net",
        "media.forgecdn.net",
        "maven.fabricmc.net",
        "meta.fabricmc.net",
        "maven.quiltmc.org",
        "meta.quiltmc.org",
        "maven.neoforged.net",
        "maven.minecraftforge.net",
        "fill.papermc.io",
        "fill-data.papermc.io",
        "piston-meta.mojang.com",
        "piston-data.mojang.com",
        "libraries.minecraft.net",
    }
)

GITHUB_RELEASE_HOST = "github.com"
GITHUB_RELEASE_DOWNLOAD_PATH_RE = re.compile(
    r"\A/[^/]+/[^/]+/releases/download/[^/]+/[^/]+\Z"
)
GITHUB_REDIRECT_ASSET_HOSTS: frozenset[str] = frozenset(
    {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
ALL_NORMATIVE_DOWNLOAD_HOSTS = (
    DEFAULT_ALLOWED_DOWNLOAD_HOSTS | {GITHUB_RELEASE_HOST} | GITHUB_REDIRECT_ASSET_HOSTS
)

_FORBIDDEN_HOST_CHARS = frozenset("*:/@?#")
_CONTROL_CHARS = frozenset(chr(code) for code in range(0x20)) | {"\x7f"}
_ENCODED_TRICKS = ("%2e", "%2f", "%5c", "%00")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class ValidatedDownloadUrl:
    url: str
    host: str
    is_github_release_origin: bool = False


@dataclass(frozen=True)
class VerifiedDownloadResult:
    sha256: str
    sha512: str
    sha1: str
    size: int
    final_url: str
    redirect_count: int


def normalize_allowed_host(raw_host: str) -> str:
    """Normalize and validate a DNS hostname; reject IP literals and tricks."""
    if not isinstance(raw_host, str) or not raw_host:
        raise UntrustedDownloadHostError(str(raw_host)[:128], "invalid_host")
    if any(ch in _CONTROL_CHARS or ch.isspace() for ch in raw_host):
        raise UntrustedDownloadHostError(raw_host, "host_contains_whitespace_or_control")
    if any(ch in _FORBIDDEN_HOST_CHARS for ch in raw_host):
        raise UntrustedDownloadHostError(raw_host, "host_contains_forbidden_character")
    if raw_host.startswith("[") or raw_host.endswith("]") or raw_host in (".", ".."):
        raise UntrustedDownloadHostError(raw_host, "invalid_host")

    host = raw_host[:-1] if raw_host.endswith(".") else raw_host
    if not host or host.endswith("."):
        raise UntrustedDownloadHostError(raw_host, "invalid_host")
    if any(not label for label in host.split(".")):
        raise UntrustedDownloadHostError(raw_host, "invalid_host")

    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UntrustedDownloadHostError(raw_host, "host_idna_invalid") from exc

    if ":" in host:
        raise UntrustedDownloadHostError(host, "ip_literal_rejected")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UntrustedDownloadHostError(host, "ip_literal_rejected")

    try:
        socket.inet_aton(host)
    except OSError:
        pass
    else:
        raise UntrustedDownloadHostError(host, "ip_literal_rejected")

    if host.split(".")[-1].isdigit():
        raise UntrustedDownloadHostError(host, "numeric_host_rejected")

    return host


def _normalize_extra_hosts(extra_allowed_hosts: Iterable[str]) -> frozenset[str]:
    return frozenset(normalize_allowed_host(host) for host in extra_allowed_hosts)


def _has_dot_segment(path: str) -> bool:
    return any(segment in (".", "..") for segment in path.split("/"))


def validate_download_url(
    url: str,
    *,
    extra_allowed_hosts: Iterable[str] = (),
    from_github_release: bool = False,
) -> ValidatedDownloadUrl:
    """Validate a URL against the normative download allow-list."""
    if not isinstance(url, str) or not url:
        raise UntrustedDownloadHostError("", "invalid_url")
    if any(ch in _CONTROL_CHARS for ch in url):
        raise UntrustedDownloadHostError("", "url_contains_control_character")

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise UntrustedDownloadHostError("", "malformed_url") from exc

    if parsed.scheme.lower() != "https":
        raise UntrustedDownloadHostError(parsed.hostname or "", "https_required")
    if parsed.username is not None or parsed.password is not None:
        raise UntrustedDownloadHostError(parsed.hostname or "", "userinfo_rejected")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UntrustedDownloadHostError(parsed.hostname or "", "invalid_port") from exc
    if port not in (None, 443):
        raise UntrustedDownloadHostError(parsed.hostname or "", "port_not_allowed")
    if not parsed.hostname:
        raise UntrustedDownloadHostError("", "missing_host")

    host = normalize_allowed_host(parsed.hostname)
    extra_hosts = _normalize_extra_hosts(extra_allowed_hosts)
    lower_path = parsed.path.lower()

    if host in DEFAULT_ALLOWED_DOWNLOAD_HOSTS or host in extra_hosts:
        return ValidatedDownloadUrl(url=url, host=host, is_github_release_origin=False)

    if host == GITHUB_RELEASE_HOST:
        if any(trick in lower_path for trick in _ENCODED_TRICKS) or _has_dot_segment(
            parsed.path
        ):
            raise UntrustedDownloadHostError(host, "github_path_not_release_download")
        if not GITHUB_RELEASE_DOWNLOAD_PATH_RE.match(parsed.path):
            raise UntrustedDownloadHostError(host, "github_path_not_release_download")
        return ValidatedDownloadUrl(url=url, host=host, is_github_release_origin=True)

    if host in GITHUB_REDIRECT_ASSET_HOSTS:
        if not from_github_release:
            raise UntrustedDownloadHostError(
                host, "github_asset_host_requires_release_redirect"
            )
        return ValidatedDownloadUrl(url=url, host=host, is_github_release_origin=True)

    raise UntrustedDownloadHostError(host, "host_not_in_allowlist")


async def _stream_download(
    url: str,
    *,
    write_chunk: Callable[[bytes], Any],
    extra_allowed_hosts: Iterable[str],
    max_bytes: int,
    max_redirects: int,
    expected_size: int | None,
    expected_sha512: str | None,
    expected_sha1: str | None,
    expected_sha256: str | None,
    client: aiohttp.ClientSession | None,
) -> VerifiedDownloadResult:
    effective_max = min(max_bytes, expected_size) if expected_size is not None else max_bytes
    session = client or get_http_client()
    current_url = url
    from_github_release = False
    redirect_count = 0

    while True:
        validated = validate_download_url(
            current_url,
            extra_allowed_hosts=extra_allowed_hosts,
            from_github_release=from_github_release,
        )
        try:
            async with session.get(current_url, allow_redirects=False) as resp:
                status = int(resp.status)
                if status in _REDIRECT_STATUSES:
                    if redirect_count >= max_redirects:
                        raise DownloadError(current_url, status, "Too many redirects")
                    location = resp.headers.get("Location") or resp.headers.get("location")
                    if not location:
                        raise DownloadError(current_url, status, "Redirect missing Location")
                    current_url = urljoin(current_url, str(location))
                    from_github_release = validated.is_github_release_origin
                    redirect_count += 1
                    continue
                if status != 200:
                    raise DownloadError(current_url, status)

                sha256 = hashlib.sha256()
                sha512 = hashlib.sha512()
                sha1 = hashlib.sha1()
                size = 0
                while True:
                    chunk = await resp.content.read(65536)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise DownloadError(current_url, 0, "Invalid response body chunk")
                    size += len(chunk)
                    if size > effective_max:
                        raise CorruptedDownloadError(
                            current_url, "download exceeds the maximum allowed size"
                        )
                    sha256.update(chunk)
                    sha512.update(chunk)
                    sha1.update(chunk)
                    write_chunk(bytes(chunk))
        except (DownloadError, CorruptedDownloadError):
            raise
        except TimeoutError as exc:
            raise DownloadError(current_url, 0, "Download timed out") from exc
        except (aiohttp.ClientError, OSError) as exc:
            raise DownloadError(current_url, 0, str(exc)[:200]) from exc

        digest256 = sha256.hexdigest()
        digest512 = sha512.hexdigest()
        digest1 = sha1.hexdigest()
        if expected_size is not None and size != expected_size:
            raise CorruptedDownloadError(
                current_url, f"size mismatch: expected {expected_size}, got {size}"
            )
        if expected_sha512 is not None and digest512 != expected_sha512.lower():
            raise CorruptedDownloadError(current_url, "sha512 mismatch")
        if expected_sha1 is not None and digest1 != expected_sha1.lower():
            raise CorruptedDownloadError(current_url, "sha1 mismatch")
        if expected_sha256 is not None and digest256 != expected_sha256.lower():
            raise CorruptedDownloadError(current_url, "sha256 mismatch")
        return VerifiedDownloadResult(
            sha256=digest256,
            sha512=digest512,
            sha1=digest1,
            size=size,
            final_url=current_url,
            redirect_count=redirect_count,
        )


async def download_verified_to_cas(
    url: str,
    cas: ArtifactCas,
    *,
    expected_size: int | None = None,
    expected_sha512: str | None = None,
    expected_sha1: str | None = None,
    expected_sha256: str | None = None,
    extra_allowed_hosts: Iterable[str] = (),
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    max_redirects: int = MAX_REDIRECT_HOPS,
    client: aiohttp.ClientSession | None = None,
) -> VerifiedDownloadResult:
    """Stream a validated download into the CAS, verifying hashes and size."""
    tmp_dir = Path(cas.root) / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix="download-", suffix=".part", dir=tmp_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            result = await _stream_download(
                url,
                write_chunk=handle.write,
                extra_allowed_hosts=extra_allowed_hosts,
                max_bytes=max_bytes,
                max_redirects=max_redirects,
                expected_size=expected_size,
                expected_sha512=expected_sha512,
                expected_sha1=expected_sha1,
                expected_sha256=expected_sha256,
                client=client,
            )
            handle.flush()
            os.fsync(handle.fileno())
        digest = cas.put_file(tmp_path)
        if digest != result.sha256:
            raise CorruptedDownloadError(url, "CAS digest mismatch")
        return result
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


async def download_verified_bytes(
    url: str,
    *,
    expected_size: int | None = None,
    expected_sha512: str | None = None,
    expected_sha1: str | None = None,
    expected_sha256: str | None = None,
    extra_allowed_hosts: Iterable[str] = (),
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    max_redirects: int = MAX_REDIRECT_HOPS,
    client: aiohttp.ClientSession | None = None,
) -> tuple[bytes, VerifiedDownloadResult]:
    """In-memory variant used for small metadata artifacts and tests."""
    buffer = bytearray()
    result = await _stream_download(
        url,
        write_chunk=buffer.extend,
        extra_allowed_hosts=extra_allowed_hosts,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        expected_size=expected_size,
        expected_sha512=expected_sha512,
        expected_sha1=expected_sha1,
        expected_sha256=expected_sha256,
        client=client,
    )
    return bytes(buffer), result


__all__ = [
    "ALL_NORMATIVE_DOWNLOAD_HOSTS",
    "DEFAULT_ALLOWED_DOWNLOAD_HOSTS",
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "GITHUB_REDIRECT_ASSET_HOSTS",
    "GITHUB_RELEASE_DOWNLOAD_PATH_RE",
    "GITHUB_RELEASE_HOST",
    "MAX_REDIRECT_HOPS",
    "ValidatedDownloadUrl",
    "VerifiedDownloadResult",
    "download_verified_bytes",
    "download_verified_to_cas",
    "normalize_allowed_host",
    "validate_download_url",
]
