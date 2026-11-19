"""Pre-warm builders for the host Loader Environment Cache (P5.5).

Each builder runs the normative loader install/pre-warm flow in an isolated
staging directory, validates the payload boundary, and publishes an immutable
LEC entry through :class:`LecStore`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.allowlist import open_safe_path_fd, validate_canonical_relpath
from app.core.config import AppSettings
from app.core.exceptions import ValidationError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.server.application.services.jar_service import (
    QUILT_SERVER_JSON_URL,
    neoforge_installer_url,
    resolve_paper_build,
    validate_forge_supported_version,
)
from app.modules.server.domain.runtime_exceptions import InstallerExecutionError
from app.modules.versioning.domain.lockfile import LecKeyParts, parse_lec_key
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import (
    download_verified_bytes,
    download_verified_to_cas,
)
from app.modules.versioning.infrastructure.java_floor import (
    resolve_java_floor_from_mc_version,
)
from app.modules.versioning.infrastructure.lec_store import LecStore

logger = logging.getLogger(__name__)

VANILLA_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_SERVER_JAR_URL = (
    "https://meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/{installer}/server/jar"
)
FORGE_INSTALLER_URL = (
    "https://maven.minecraftforge.net/net/minecraftforge/forge/"
    "{mc}-{forge}/forge-{mc}-{forge}-installer.jar"
)
QUILT_DEFAULT_MAIN_CLASS = "org.quiltmc.loader.impl.launch.knot.KnotServer"
QUILT_DEFAULT_MAVEN = "https://maven.quiltmc.org/repository/release/"
MOJANG_LIBRARIES_MAVEN = "https://libraries.minecraft.net/"

DownloadBytes = Callable[..., Awaitable[Any]]
DownloadToCas = Callable[..., Awaitable[Any]]
CommandRunner = Callable[[list[str], str], Awaitable[int]]


@dataclass(frozen=True)
class QuiltLibraryEntry:
    name: str
    url: str = ""
    relpath: str = ""
    sha1: str | None = None
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class LecBuildResult:
    lec_key: str
    entry_dir: Path
    file_count: int
    total_bytes: int
    java_major: int
    unix_args_relpath: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


def _maven_relpath(coordinate: str) -> str:
    parts = coordinate.split(":")
    if len(parts) < 3:
        raise ValidationError("Invalid Maven coordinate", field="lec")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) >= 4 else ""
    if not group or not artifact or not version:
        raise ValidationError("Invalid Maven coordinate", field="lec")
    filename = f"{artifact}-{version}"
    if classifier:
        filename += f"-{classifier}"
    filename += ".jar"
    rel = "/".join([group.replace(".", "/"), artifact, version, filename])
    return validate_canonical_relpath(f"libraries/{rel}")


def _unix_args_relpath(parts: LecKeyParts) -> str | None:
    if parts.loader == "forge":
        return f"libraries/net/minecraftforge/forge/{parts.mc}-{parts.version}/unix_args.txt"
    if parts.loader == "neoforge":
        if parts.version.startswith("1.20.1-"):
            return f"libraries/net/minecraftforge/forge/{parts.version}/unix_args.txt"
        return f"libraries/net/neoforged/neoforge/{parts.version}/unix_args.txt"
    if parts.loader == "quilt":
        return f"libraries/org/quiltmc/quilt-loader/{parts.version}/unix_args.txt"
    return None


def _join_url(base: str, relpath: str) -> str:
    return base.rstrip("/") + "/" + relpath


async def _default_runner(argv: list[str], cwd: str) -> int:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await process.wait()


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _write_bytes(root: Path, relpath: str, data: bytes) -> None:
    rel = validate_canonical_relpath(relpath)
    fd = open_safe_path_fd(
        str(root),
        rel,
        flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode=0o644,
        allow_create_parents=True,
    )
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(entry: Path) -> None:
    for current, _dirs, files in os.walk(entry, topdown=False, followlinks=False):
        for name in files:
            path = Path(current) / name
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)


def _files_under(root: Path, tree: str) -> list[Path]:
    base = root / tree
    if not base.is_dir():
        return []
    return [path for path in base.rglob("*") if path.is_file()]


class LecBuilder:
    """Pre-warm builder for all five normative loaders."""

    def __init__(
        self,
        layout: HostStateLayout | None = None,
        *,
        store: LecStore | None = None,
        cas: ArtifactCas | None = None,
        settings: AppSettings | None = None,
        command_runner: CommandRunner | None = None,
        download_bytes: DownloadBytes | None = None,
        download_to_cas: DownloadToCas | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings or AppSettings()
        self._layout = layout or ensure_host_state_layout(self._settings)
        self._cas = cas or ArtifactCas(self._layout.cas)
        self._store = store or LecStore(self._layout)
        self._runner = command_runner or _default_runner
        self._download_bytes = download_bytes or download_verified_bytes
        self._download_to_cas = download_to_cas or download_verified_to_cas
        self._session_factory = session_factory

    @property
    def store(self) -> LecStore:
        return self._store

    async def _fetch_bytes(self, url: str, **kwargs: Any) -> bytes:
        try:
            result = await self._download_bytes(url, **kwargs)
        except TypeError:
            result = await self._download_bytes(url)
        data = result[0] if isinstance(result, tuple) else result
        if not isinstance(data, (bytes, bytearray)):
            raise ValidationError("Downloader returned non-bytes", field="lec")
        return bytes(data)

    async def _fetch_to_cas(self, url: str, **kwargs: Any) -> str:
        try:
            result = await self._download_to_cas(url, self._cas, **kwargs)
        except TypeError:
            result = await self._download_to_cas(url, self._cas)
        if isinstance(result, str):
            return result
        digest = getattr(result, "sha256", None)
        if not isinstance(digest, str):
            raise ValidationError("CAS downloader returned no digest", field="lec")
        return digest

    async def _publish(
        self,
        staging: Path,
        lec_key: str,
        *,
        java_major: int,
        unix_args_relpath: str | None = None,
    ) -> LecBuildResult:
        _fsync_tree(staging)
        session = None
        entry = None
        try:
            if self._session_factory is not None:
                session = self._session_factory()
                if hasattr(session, "__aenter__"):
                    async with session as active:
                        metadata = await self._store.publish_staged_entry(
                            staging, lec_key, java_major=java_major, session=active
                        )
                        with contextlib.suppress(Exception):
                            await active.commit()
                else:
                    metadata = await self._store.publish_staged_entry(
                        staging, lec_key, java_major=java_major, session=session
                    )
            else:
                metadata = await self._store.publish_staged_entry(
                    staging, lec_key, java_major=java_major
                )
        finally:
            if staging.exists():
                with contextlib.suppress(OSError):
                    import shutil

                    shutil.rmtree(staging)
        entry = self._store.entry_dir(lec_key)
        return LecBuildResult(
            lec_key=lec_key,
            entry_dir=entry,
            file_count=metadata.file_count,
            total_bytes=metadata.total_bytes,
            java_major=metadata.java_major,
            unix_args_relpath=unix_args_relpath,
        )

    def _check_unix_args(self, staging: Path, relpath: str) -> None:
        path = staging / relpath
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise ValidationError("LEC build has no non-empty unix_args.txt", field="lec")

    async def _run(self, argv: list[str], staging: Path) -> None:
        exit_code = await self._runner(argv, str(staging))
        if exit_code != 0:
            raise InstallerExecutionError(
                server_id=str(staging),
                detail=f"pre-warm command exited with code {exit_code}",
                exit_code=exit_code,
            )

    async def _write_forge_like(
        self,
        staging: Path,
        installer_url: str,
        installer_name: str,
        argv: list[str],
        unix_args_relpath: str,
    ) -> None:
        installer_bytes = await self._fetch_bytes(installer_url)
        _write_bytes(staging, installer_name, installer_bytes)
        await self._run(argv, staging)
        self._check_unix_args(staging, unix_args_relpath)

    # ------------------------------------------------------------------
    # Quilt
    # ------------------------------------------------------------------

    @staticmethod
    def _quilt_library_entries(document: Mapping[str, Any]) -> list[QuiltLibraryEntry]:
        entries: list[QuiltLibraryEntry] = []
        libraries = document.get("libraries", [])
        if not isinstance(libraries, list):
            return entries
        for raw in libraries:
            if not isinstance(raw, Mapping):
                continue
            name = raw.get("name")
            if not isinstance(name, str):
                continue
            url = raw.get("url")
            entries.append(
                QuiltLibraryEntry(
                    name=name,
                    url=url if isinstance(url, str) else "",
                    relpath=_maven_relpath(name),
                    sha1=raw.get("sha1") if isinstance(raw.get("sha1"), str) else None,
                    sha256=raw.get("sha256") if isinstance(raw.get("sha256"), str) else None,
                    size=raw.get("size") if type(raw.get("size")) is int else None,
                )
            )
        return entries

    async def _mojang_server_jar(self, minecraft_version: str) -> tuple[str, bytes]:
        manifest_raw = await self._fetch_bytes(VANILLA_MANIFEST_URL)
        manifest = json.loads(manifest_raw)
        version_url: str | None = None
        versions = manifest.get("versions", []) if isinstance(manifest, Mapping) else []
        for entry in versions:
            if isinstance(entry, Mapping) and entry.get("id") == minecraft_version:
                candidate = entry.get("url")
                if isinstance(candidate, str):
                    version_url = candidate
                break
        if version_url is None:
            raise ValidationError(
                f"Mojang version metadata is missing for {minecraft_version}", field="lec"
            )
        raw = await self._fetch_bytes(version_url)
        version_data = json.loads(raw)
        downloads = version_data.get("downloads", {}) if isinstance(version_data, Mapping) else {}
        server = downloads.get("server", {}) if isinstance(downloads, Mapping) else {}
        server_url = server.get("url") if isinstance(server, Mapping) else None
        if not isinstance(server_url, str):
            raise ValidationError("Mojang server download is missing", field="lec")
        sha1 = server.get("sha1") if isinstance(server, Mapping) else None
        size = server.get("size") if isinstance(server, Mapping) else None
        data = await self._fetch_bytes(
            server_url,
            expected_sha1=sha1 if isinstance(sha1, str) else None,
            expected_size=size if type(size) is int else None,
        )
        rel = f"libraries/net/minecraft/server/{minecraft_version}/server-{minecraft_version}.jar"
        return rel, data

    async def build_quilt_lec(self, minecraft_version: str, loader_version: str) -> LecBuildResult:
        lec_key = f"quilt/{minecraft_version}/{loader_version}"
        staging = self._store.create_staging_dir(lec_key)
        try:
            server_json_url = QUILT_SERVER_JSON_URL.format(
                mc_version=minecraft_version, loader_version=loader_version
            )
            raw = await self._fetch_bytes(server_json_url)
            document = json.loads(raw)
            if not isinstance(document, Mapping):
                raise ValidationError("Quilt server JSON is invalid", field="lec")
            main_class = document.get("mainClass") or QUILT_DEFAULT_MAIN_CLASS
            inherits = document.get("inheritsFrom")
            if inherits is not None and inherits != minecraft_version:
                raise ValidationError("Quilt server JSON inheritsFrom mismatch", field="lec")

            entries = self._quilt_library_entries(document)
            if not entries:
                raise ValidationError("Quilt server JSON has no libraries", field="lec")
            classpath: list[str] = []
            for entry in entries:
                base = entry.url or (
                    MOJANG_LIBRARIES_MAVEN
                    if entry.relpath.startswith("libraries/net/minecraft/")
                    else QUILT_DEFAULT_MAVEN
                )
                data = await self._fetch_bytes(
                    _join_url(base, entry.relpath),
                    expected_sha1=entry.sha1,
                    expected_sha256=entry.sha256,
                    expected_size=entry.size,
                )
                _write_bytes(staging, entry.relpath, data)
                classpath.append(entry.relpath)

            server_rel, server_bytes = await self._mojang_server_jar(minecraft_version)
            _write_bytes(staging, server_rel, server_bytes)
            unix_rel = f"libraries/org/quiltmc/quilt-loader/{loader_version}/unix_args.txt"
            unix_content = (
                f"-Dfabric.gameJarPath={server_rel} -cp "
                f"{':'.join(classpath)} {main_class}\n"
            )
            _write_bytes(staging, unix_rel, unix_content.encode("utf-8"))
            self._check_unix_args(staging, unix_rel)
            java_major = resolve_java_floor_from_mc_version(minecraft_version)
            return await self._publish(
                staging, lec_key, java_major=java_major, unix_args_relpath=unix_rel
            )
        except BaseException:
            self._cleanup(staging)
            raise

    # ------------------------------------------------------------------
    # Forge / NeoForge
    # ------------------------------------------------------------------

    async def build_forge_lec(
        self, minecraft_version: str, forge_version: str
    ) -> LecBuildResult:
        validate_forge_supported_version(minecraft_version)
        lec_key = f"forge/{minecraft_version}/{forge_version}"
        staging = self._store.create_staging_dir(lec_key)
        try:
            full_version = f"{minecraft_version}-{forge_version}"
            unix_rel = f"libraries/net/minecraftforge/forge/{full_version}/unix_args.txt"
            url = FORGE_INSTALLER_URL.format(mc=minecraft_version, forge=forge_version)
            await self._write_forge_like(
                staging,
                url,
                "installer.jar",
                ["java", "-jar", "installer.jar", "--installServer"],
                unix_rel,
            )
            java_major = resolve_java_floor_from_mc_version(minecraft_version)
            return await self._publish(
                staging, lec_key, java_major=java_major, unix_args_relpath=unix_rel
            )
        except BaseException:
            self._cleanup(staging)
            raise

    async def build_neoforge_lec(
        self, minecraft_version: str, neoforge_version: str
    ) -> LecBuildResult:
        lec_key = f"neoforge/{minecraft_version}/{neoforge_version}"
        staging = self._store.create_staging_dir(lec_key)
        try:
            unix_rel = (
                f"libraries/net/minecraftforge/forge/{neoforge_version}/unix_args.txt"
                if neoforge_version.startswith("1.20.1-")
                else f"libraries/net/neoforged/neoforge/{neoforge_version}/unix_args.txt"
            )
            await self._write_forge_like(
                staging,
                neoforge_installer_url(neoforge_version),
                "installer.jar",
                ["java", "-jar", "installer.jar", "--installServer"],
                unix_rel,
            )
            java_major = resolve_java_floor_from_mc_version(minecraft_version)
            return await self._publish(
                staging, lec_key, java_major=java_major, unix_args_relpath=unix_rel
            )
        except BaseException:
            self._cleanup(staging)
            raise

    # ------------------------------------------------------------------
    # Fabric
    # ------------------------------------------------------------------

    async def build_fabric_lec(
        self, minecraft_version: str, loader_version: str, installer_version: str
    ) -> LecBuildResult:
        lec_key = f"fabric/{minecraft_version}/{loader_version}/{installer_version}"
        staging = self._store.create_staging_dir(lec_key)
        try:
            url = FABRIC_SERVER_JAR_URL.format(
                mc=minecraft_version, loader=loader_version, installer=installer_version
            )
            digest = await self._fetch_to_cas(url)
            launcher_bytes = self._cas.blob_path(digest).read_bytes()
            launcher_name = (
                f"fabric-server-mc.{minecraft_version}-loader.{loader_version}"
                f"-launcher.{installer_version}.jar"
            )
            _write_bytes(staging, launcher_name, launcher_bytes)
            _write_bytes(staging, "eula.txt", b"eula=true\n")
            _write_bytes(
                staging,
                f".fabric/server/{launcher_name}",
                launcher_bytes,
            )
            await self._run(["java", "-jar", launcher_name, "nogui"], staging)
            _fsync_tree(staging)
            java_major = resolve_java_floor_from_mc_version(minecraft_version)
            return await self._publish(staging, lec_key, java_major=java_major)
        except BaseException:
            self._cleanup(staging)
            raise

    # ------------------------------------------------------------------
    # Paper
    # ------------------------------------------------------------------

    async def build_paper_lec(self, minecraft_version: str, build: str | int) -> LecBuildResult:
        resolution = await resolve_paper_build(minecraft_version)
        resolved_build = resolution.build_id if build in ("", None) else build
        lec_key = f"paper/{minecraft_version}/{resolved_build}"
        staging = self._store.create_staging_dir(lec_key)
        try:
            digest = await self._fetch_to_cas(
                resolution.download_url,
                expected_sha256=resolution.sha256,
                expected_size=resolution.size,
            )
            launcher_name = f"paper-{minecraft_version}-{resolution.build_id}.jar"
            _write_bytes(staging, launcher_name, self._cas.blob_path(digest).read_bytes())
            _write_bytes(staging, "eula.txt", b"eula=true\n")
            await self._run(
                ["java", "-Dpaperclip.patchonly=true", "-jar", launcher_name],
                staging,
            )
            payload_files = (
                _files_under(staging, "cache")
                + _files_under(staging, "versions")
                + _files_under(staging, "libraries")
            )
            if not payload_files:
                raise ValidationError(
                    "Paper pre-warm produced no cache/versions/libraries files", field="lec"
                )
            java_major = resolution.java_min_major or resolve_java_floor_from_mc_version(
                resolution.mc_version
            )
            return await self._publish(staging, lec_key, java_major=java_major)
        except BaseException:
            self._cleanup(staging)
            raise

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def ensure_lec(self, lec_key: str) -> LecBuildResult:
        norm = validate_canonical_relpath(lec_key)
        parts = parse_lec_key(norm)
        if parts.loader == "fabric":
            return await self.build_fabric_lec(
                parts.mc, parts.version, parts.installer or ""
            )
        if parts.loader == "forge":
            return await self.build_forge_lec(parts.mc, parts.version)
        if parts.loader == "neoforge":
            return await self.build_neoforge_lec(parts.mc, parts.version)
        if parts.loader == "quilt":
            return await self.build_quilt_lec(parts.mc, parts.version)
        if parts.loader == "paper":
            return await self.build_paper_lec(parts.mc, parts.version)
        raise ValidationError("Unsupported LEC loader", field="lec")

    @staticmethod
    def _cleanup(staging: Path) -> None:
        if staging.exists():
            with contextlib.suppress(OSError):
                import shutil

                shutil.rmtree(staging)


__all__ = [
    "LecBuildResult",
    "LecBuilder",
    "QuiltLibraryEntry",
]
