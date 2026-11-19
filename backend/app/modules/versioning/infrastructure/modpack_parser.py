"""``.mrpack`` reader, strict archive quarantine, and ``InstallPlan`` engine (P5.5).

The parser never writes into a server root. It opens the archive read-only,
quarantines every member (entry count, total size, compression ratio, symlinks,
canonical paths, casefold collisions), validates the index/manifest, and
returns an immutable ``InstallPlan`` plus the surviving override blobs. Staging
to disk is done exclusively through ``open_safe_path_fd``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import posixpath
import stat
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from app.core.allowlist import (
    CLASS_A_JAR_REGEX,
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    validate_canonical_relpath,
)
from app.core.exceptions import (
    CaseCollisionError,
    HostileExecutableError,
    ModpackFormatError,
    OversizedGitTrackedFileError,
    UnsupportedForgeVersionError,
)
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider
from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.domain.lockfile import EnvServer, Origin
from app.modules.versioning.infrastructure.download_allowlist import validate_download_url

logger = logging.getLogger(__name__)

MAX_ARCHIVE_ENTRIES = 100_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
COMPRESSION_RATIO_SIZE_THRESHOLD_BYTES = 16 * 1024 * 1024
MAX_COMPRESSION_RATIO = 64.0
MAX_CLASS_B_FILE_BYTES = 1 * 1024 * 1024
MAX_CLASS_B_ROUTED_BYTES = 16 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024

FORBIDDEN_PREFIXES = (".git", ".fabric", "libraries", "versions", "logs")
DISCARDED_ROOT_FILES = frozenset({"run.sh", "run.bat", "user_jvm_args.txt", "eula.txt"})
HOSTILE_EXECUTABLE_EXTENSIONS = frozenset(
    {".jar", ".war", ".class", ".so", ".dll", ".dylib", ".exe", ".sh", ".bat", ".cmd", ".ps1"}
)
MRPACK_LOADER_KEY_MAP = {
    "fabric-loader": "fabric",
    "quilt-loader": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}
FORGE_MIN_MC = MinecraftVersion(1, 17, 1)
FORGE_MAX_MC = MinecraftVersion(1, 20, 1)
FORGE_MAX_EXCLUSIVE_MC = MinecraftVersion(1, 20, 2)

OVERRIDE_LAYERS = ("overrides", "server-overrides")
IGNORED_OVERRIDE_LAYERS = ("client-overrides",)
_ENCODED_TRICKS = ("%2e", "%2f", "%5c", "%00")
_CHUNK_SIZE = 64 * 1024


def _sha1_hex(value: object) -> str:
    if not isinstance(value, str) or not _is_hex(value, 40):
        raise ModpackFormatError(
            "Index file entry has an invalid sha1 hash",
            field="files.hashes.sha1",
        )
    return value.lower()


def _sha512_hex(value: object) -> str:
    if not isinstance(value, str) or not _is_hex(value, 128):
        raise ModpackFormatError(
            "Index file entry has an invalid sha512 hash",
            field="files.hashes.sha512",
        )
    return value.lower()


def _is_hex(value: str, length: int) -> bool:
    if len(value) != length:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def _is_regular_or_directory(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    if mode == 0:
        return
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise ModpackFormatError(
            f"Archive member is a symlink: {info.filename[:128]!r}",
            field="archive.member",
        )
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ModpackFormatError(
            f"Archive member is not a regular file or directory: {info.filename[:128]!r}",
            field="archive.member",
        )


def _member_is_dir(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return True
    mode = info.external_attr >> 16
    return mode != 0 and stat.S_IFMT(mode) == stat.S_IFDIR


def _member_relpath(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.is_dir() and name.endswith("/"):
        name = name[:-1]
    return name


def validate_forge_mc_version(mc_version: str) -> None:
    """Reject Forge outside the supported 1.17.1..1.20.1 range."""
    try:
        parsed = MinecraftVersion.parse(mc_version)
    except ValueError as exc:
        raise ModpackFormatError(
            f"Invalid Minecraft version {mc_version[:32]!r}",
            field="minecraft.version",
        ) from exc
    if parsed < FORGE_MIN_MC or parsed >= FORGE_MAX_EXCLUSIVE_MC:
        raise UnsupportedForgeVersionError(minecraft_version=mc_version)


def validate_archive_quarantine(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Enforce the strict archive quarantine and return the member list."""
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ModpackFormatError(
            f"Archive has too many entries ({len(infos)} > {MAX_ARCHIVE_ENTRIES})",
            field="archive.entries",
        )

    total_bytes = sum(info.file_size for info in infos)
    if total_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise ModpackFormatError(
            "Archive exceeds the 4 GiB uncompressed size limit",
            field="archive.uncompressed_size",
        )

    seen: dict[str, tuple[str, bool]] = {}
    for info in infos:
        _is_regular_or_directory(info)
        relpath = _member_relpath(info)
        if not relpath:
            raise ModpackFormatError("Archive member has an empty path", field="archive.member")
        lower = relpath.lower()
        if any(trick in lower for trick in _ENCODED_TRICKS):
            raise ModpackFormatError(
                f"Archive member contains an encoded path trick: {relpath[:128]!r}",
                field="archive.member",
            )
        try:
            validate_canonical_relpath(relpath)
        except ValueError as exc:
            raise ModpackFormatError(
                f"Archive member has an invalid path: {relpath[:128]!r}",
                field="archive.member",
            ) from exc

        is_dir = _member_is_dir(info)
        casefold_path = relpath.casefold()
        previous = seen.get(casefold_path)
        if previous is not None:
            previous_path, previous_is_dir = previous
            if previous_path == relpath:
                if previous_is_dir != is_dir:
                    raise ModpackFormatError(
                        f"Archive member is both a file and a directory: {relpath[:128]!r}",
                        field="archive.member",
                    )
                raise ModpackFormatError(
                    f"Duplicate archive member: {relpath[:128]!r}",
                    field="archive.member",
                )
            raise CaseCollisionError(
                "Casefold collision between archive members",
                path_a=previous_path,
                path_b=relpath,
            )
        seen[casefold_path] = (relpath, is_dir)

        if not is_dir and info.file_size > COMPRESSION_RATIO_SIZE_THRESHOLD_BYTES:
            if info.compress_size == 0:
                raise ModpackFormatError(
                    f"Archive member has a forged compression size: {relpath[:128]!r}",
                    field="archive.compression_ratio",
                )
            if info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise ModpackFormatError(
                    f"Archive member exceeds the compression ratio limit: {relpath[:128]!r}",
                    field="archive.compression_ratio",
                )
    return infos


def read_zip_member_bounded(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Read one member, rejecting spoofed sizes and bounded decompression."""
    chunks: list[bytes] = []
    total = 0
    try:
        with zf.open(info, "r") as handle:
            while True:
                chunk = handle.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > info.file_size:
                    raise ModpackFormatError(
                        f"Archive member exceeds its declared size: {info.filename[:128]!r}",
                        field="archive.member",
                    )
                if max_bytes is not None and total > max_bytes:
                    raise ModpackFormatError(
                        f"Archive member exceeds the permitted size: {info.filename[:128]!r}",
                        field="archive.member",
                    )
                chunks.append(chunk)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ModpackFormatError(
            f"Archive member could not be read: {info.filename[:128]!r}",
            field="archive.member",
        ) from exc
    if total != info.file_size:
        raise ModpackFormatError(
            f"Archive member is shorter than declared: {info.filename[:128]!r}",
            field="archive.member",
        )
    return b"".join(chunks)


def _has_forbidden_prefix(relpath: str) -> bool:
    return any(
        relpath == prefix or relpath.startswith(f"{prefix}/")
        for prefix in FORBIDDEN_PREFIXES
    )


def classify_and_validate_target_path(
    relpath: str,
    size: int,
) -> Literal["DISCARD", "A-JAR", "A-CAS", "B", "B-ROUTED-CAS", "SKIP"]:
    """Classify one archive target path and apply the Class-B size caps."""
    try:
        validate_canonical_relpath(relpath)
    except ValueError as exc:
        raise ModpackFormatError(
            f"Invalid target path: {relpath[:128]!r}",
            field="path",
        ) from exc

    if _has_forbidden_prefix(relpath):
        raise ModpackFormatError(
            f"Target path uses a forbidden prefix: {relpath[:128]!r}",
            field="path",
        )
    if relpath == "onx-jars.lock.json":
        raise ModpackFormatError(
            "Modpacks may not ship onx-jars.lock.json",
            field="path",
        )
    if relpath.lower() in DISCARDED_ROOT_FILES:
        return "DISCARD"

    extension = posixpath.splitext(relpath)[1].lower()
    if extension in HOSTILE_EXECUTABLE_EXTENSIONS:
        if extension == ".jar" and CLASS_A_JAR_REGEX.match(relpath):
            return "A-JAR"
        raise HostileExecutableError(path=relpath)

    classification = classify(relpath)
    if classification == "QUARANTINE":
        raise HostileExecutableError(path=relpath)
    if classification == "REJECT-PATH":
        raise ModpackFormatError(
            f"Target path is rejected by the allow-list: {relpath[:128]!r}",
            field="path",
        )
    if classification == "A-JAR":
        return "A-JAR"
    if classification == "A-CAS":
        return "A-CAS"
    if classification == "B":
        if relpath == "server-icon.png" and size > MAX_CLASS_B_FILE_BYTES:
            raise OversizedGitTrackedFileError(
                relpath, size, MAX_CLASS_B_FILE_BYTES
            )
        if size > MAX_CLASS_B_ROUTED_BYTES:
            raise OversizedGitTrackedFileError(relpath, size, MAX_CLASS_B_ROUTED_BYTES)
        if size > MAX_CLASS_B_FILE_BYTES:
            return "B-ROUTED-CAS"
        return "B"
    if classification in ("C", "E"):
        return "SKIP"
    raise ModpackFormatError(
        f"Target path could not be classified: {relpath[:128]!r}",
        field="path",
    )


@dataclass(frozen=True)
class InstallPlanFile:
    """One required download entry from a modpack index/manifest."""

    path: str
    sha1: str
    size: int
    downloads: tuple[str, ...]
    sha512: str | None = None
    sha256: str | None = None
    env_server: str = EnvServer.REQUIRED.value
    optional: bool = False
    origin: Origin = Origin.MODRINTH
    project_id: str | None = None
    version_id: str | None = None
    source_layer: str = "index"
    curseforge_project_id: int | None = None
    curseforge_file_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha1": self.sha1,
            "sha512": self.sha512,
            "sha256": self.sha256,
            "size": self.size,
            "downloads": list(self.downloads),
            "env_server": str(self.env_server),
            "optional": self.optional,
            "origin": str(self.origin),
            "project_id": self.project_id,
            "version_id": self.version_id,
            "source_layer": self.source_layer,
            "curseforge_project_id": self.curseforge_project_id,
            "curseforge_file_id": self.curseforge_file_id,
        }


@dataclass(frozen=True)
class InstallPlanOverride:
    """One surviving override file, already classified and hashed."""

    path: str
    archive_path: str
    source_layer: str
    classification: str
    sha256: str
    sha512: str
    sha1: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "archive_path": self.archive_path,
            "source_layer": self.source_layer,
            "classification": self.classification,
            "sha256": self.sha256,
            "sha512": self.sha512,
            "sha1": self.sha1,
            "size": self.size,
        }


@dataclass(frozen=True)
class ManualDownloadBlocker:
    """A CurseForge entry that requires an operator drag-and-drop upload."""

    path: str
    filename: str
    project_id: int | None = None
    file_id: int | None = None
    webpage_url: str = ""
    expected_size: int | None = None
    expected_sha1: str | None = None
    expected_sha512: str | None = None
    required: bool = True
    reason: str = "download_url_null"
    blocker_type: str = "manual_download_required"
    resolved: bool = False
    resolved_sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "filename": self.filename,
            "project_id": self.project_id,
            "file_id": self.file_id,
            "webpage_url": self.webpage_url,
            "expected_size": self.expected_size,
            "expected_sha1": self.expected_sha1,
            "expected_sha512": self.expected_sha512,
            "required": self.required,
            "reason": self.reason,
            "blocker_type": self.blocker_type,
            "resolved": self.resolved,
            "resolved_sha256": self.resolved_sha256,
        }


@dataclass(frozen=True)
class InstallPlan:
    """Immutable, JSON-serializable plan produced by either pack adapter."""

    source: str
    project_id: str
    version_id: str
    version_label: str
    index_sha256: str
    mc_version: str
    loader_id: str
    loader_version: str
    files: tuple[InstallPlanFile, ...]
    overrides: tuple[InstallPlanOverride, ...]
    manual_blockers: tuple[ManualDownloadBlocker, ...] = ()
    skipped_client_files: tuple[str, ...] = ()
    skipped_optional_files: tuple[str, ...] = ()
    skipped_client_override_jars: tuple[str, ...] = ()
    discarded_paths: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def has_unresolved_blockers(self) -> bool:
        return any(not blocker.resolved for blocker in self.manual_blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "project_id": self.project_id,
            "version_id": self.version_id,
            "version_label": self.version_label,
            "index_sha256": self.index_sha256,
            "mc_version": self.mc_version,
            "loader_id": self.loader_id,
            "loader_version": self.loader_version,
            "files": [f.to_dict() for f in sorted(self.files, key=lambda f: f.path)],
            "overrides": [
                o.to_dict() for o in sorted(self.overrides, key=lambda o: o.path)
            ],
            "manual_blockers": [
                b.to_dict()
                for b in sorted(
                    self.manual_blockers,
                    key=lambda b: (b.path, b.file_id if b.file_id is not None else -1),
                )
            ],
            "skipped_client_files": list(self.skipped_client_files),
            "skipped_optional_files": list(self.skipped_optional_files),
            "skipped_client_override_jars": list(self.skipped_client_override_jars),
            "discarded_paths": list(self.discarded_paths),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _RawIndexFile:
    path: str
    sha1: str
    sha512: str
    size: int
    downloads: tuple[str, ...]
    env_server: str
    optional: bool


def _parse_env(entry: dict[str, object], path: str) -> tuple[str, bool]:
    env = entry.get("env")
    if env is None:
        return EnvServer.REQUIRED.value, False
    if not isinstance(env, dict):
        raise ModpackFormatError(
            f"Index file entry has an invalid env object: {path[:128]!r}",
            field="files.env",
        )
    server = env.get("server", EnvServer.REQUIRED.value)
    if server not in (
        EnvServer.REQUIRED.value,
        EnvServer.OPTIONAL.value,
        EnvServer.UNSUPPORTED.value,
    ):
        raise ModpackFormatError(
            f"Index file entry has an invalid env.server: {server!r}",
            field="files.env.server",
        )
    return str(server), server == EnvServer.OPTIONAL.value


def _parse_index_files(
    payload: dict[str, object],
    *,
    install_optional_server_files: bool,
    extra_allowed_hosts: Iterable[str],
) -> tuple[list[_RawIndexFile], list[str], list[str], list[str], list[str]]:
    raw_files = payload.get("files", [])
    if not isinstance(raw_files, list):
        raise ModpackFormatError("Index 'files' must be a list", field="files")

    index_files: list[_RawIndexFile] = []
    skipped_client: list[str] = []
    skipped_optional: list[str] = []
    discarded_paths: list[str] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}

    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ModpackFormatError("Index file entry must be an object", field="files")
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise ModpackFormatError("Index file entry is missing a path", field="files.path")
        try:
            validate_canonical_relpath(path)
        except ValueError as exc:
            raise ModpackFormatError(
                f"Index file entry has an invalid path: {path[:128]!r}",
                field="files.path",
            ) from exc

        hashes = entry.get("hashes")
        if not isinstance(hashes, dict):
            raise ModpackFormatError(
                f"Index file entry is missing hashes: {path[:128]!r}",
                field="files.hashes",
            )
        sha1 = _sha1_hex(hashes.get("sha1"))
        sha512 = _sha512_hex(hashes.get("sha512"))

        size = entry.get("fileSize")
        if type(size) is not int or size < 0:
            raise ModpackFormatError(
                f"Index file entry has an invalid fileSize: {path[:128]!r}",
                field="files.fileSize",
            )

        downloads = entry.get("downloads")
        if (
            not isinstance(downloads, list)
            or not downloads
            or any(not isinstance(url, str) or not url for url in downloads)
        ):
            raise ModpackFormatError(
                f"Index file entry has invalid downloads: {path[:128]!r}",
                field="files.downloads",
            )
        normalized_downloads = tuple(str(url) for url in downloads)
        for url in normalized_downloads:
            validate_download_url(url, extra_allowed_hosts=extra_allowed_hosts)

        env_server, is_optional = _parse_env(entry, path)
        if env_server == EnvServer.UNSUPPORTED.value:
            skipped_client.append(path)
            continue
        optional = False
        if is_optional:
            if not install_optional_server_files:
                skipped_optional.append(path)
                continue
            optional = True

        classification = classify_and_validate_target_path(path, size)
        if classification in ("DISCARD", "SKIP"):
            discarded_paths.append(path)
            if classification == "SKIP":
                warnings.append(f"skipped_path:{path}")
            continue

        casefold_path = path.casefold()
        previous = seen.get(casefold_path)
        if previous is not None:
            if previous == path:
                raise ModpackFormatError(
                    f"Duplicate index file path: {path[:128]!r}",
                    field="files.path",
                )
            raise CaseCollisionError(
                "Casefold collision between index files",
                path_a=previous,
                path_b=path,
            )
        seen[casefold_path] = path

        index_files.append(
            _RawIndexFile(
                path=path,
                sha1=sha1,
                sha512=sha512,
                size=size,
                downloads=normalized_downloads,
                env_server=env_server,
                optional=optional,
            )
        )

    if not index_files:
        warnings.append("index_contains_no_installable_files")
    return index_files, skipped_client, skipped_optional, discarded_paths, warnings


def _effective_override_members(
    infos: Sequence[zipfile.ZipInfo],
) -> tuple[dict[str, tuple[zipfile.ZipInfo, str]], list[str]]:
    """Resolve override precedence without reading member bodies."""
    effective: dict[str, tuple[zipfile.ZipInfo, str]] = {}
    by_casefold: dict[str, str] = {}
    warnings: list[str] = []

    for layer in OVERRIDE_LAYERS:
        prefix = f"{layer}/"
        for info in infos:
            if _member_is_dir(info):
                continue
            name = info.filename
            if not name.startswith(prefix):
                continue
            relpath = name[len(prefix) :]
            if not relpath:
                continue
            casefold_path = relpath.casefold()
            previous = by_casefold.get(casefold_path)
            if previous is not None and previous != relpath:
                raise CaseCollisionError(
                    "Casefold collision between override members",
                    path_a=previous,
                    path_b=relpath,
                )
            if layer == OVERRIDE_LAYERS[1]:
                effective[relpath] = (info, layer)
            else:
                if previous == relpath:
                    raise ModpackFormatError(
                        f"Duplicate override member: {relpath[:128]!r}",
                        field="overrides",
                    )
                effective[relpath] = (info, layer)
            by_casefold[casefold_path] = relpath

    for ignored in IGNORED_OVERRIDE_LAYERS:
        prefix = f"{ignored}/"
        for info in infos:
            if not _member_is_dir(info) and info.filename.startswith(prefix):
                warnings.append(f"ignored_override_layer:{ignored}")
                break
    return effective, warnings


def _is_override_filter_jar(relpath: str) -> bool:
    lower = relpath.lower()
    if not lower.endswith(".jar"):
        return False
    return lower.startswith("mods/") or lower.startswith("plugins/")


async def parse_mrpack(
    archive_path: str | Path,
    *,
    install_optional_server_files: bool = True,
    extra_allowed_hosts: Iterable[str] = (),
    modrinth_client: ModrinthProvider | None = None,
    project_id: str = "local",
    version_id: str = "local",
) -> tuple[InstallPlan, dict[str, bytes]]:
    """Parse a ``.mrpack`` into an ``InstallPlan`` and surviving override blobs."""
    path = Path(archive_path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ModpackFormatError(
            f"Not a valid modpack ZIP archive: {path.name[:128]!r}",
            field="archive",
        ) from exc

    with zf:
        infos = validate_archive_quarantine(zf)
        index_info = next(
            (info for info in infos if info.filename == "modrinth.index.json"),
            None,
        )
        if index_info is None:
            raise ModpackFormatError(
                "Modpack archive is missing modrinth.index.json",
                field="modrinth.index.json",
            )
        index_bytes = read_zip_member_bounded(zf, index_info, max_bytes=MAX_INDEX_BYTES)
        index_sha256 = hashlib.sha256(index_bytes).hexdigest()
        try:
            payload = json.loads(index_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModpackFormatError(
                "modrinth.index.json is not valid UTF-8 JSON",
                field="modrinth.index.json",
            ) from exc
        if not isinstance(payload, dict):
            raise ModpackFormatError(
                "modrinth.index.json must be a JSON object",
                field="modrinth.index.json",
            )

        format_version = payload.get("formatVersion")
        if type(format_version) is not int or format_version != 1:
            raise ModpackFormatError(
                "Unsupported modrinth.index.json formatVersion",
                field="formatVersion",
            )
        if payload.get("game") != "minecraft":
            raise ModpackFormatError(
                "modrinth.index.json game must be 'minecraft'",
                field="game",
            )

        dependencies = payload.get("dependencies")
        if not isinstance(dependencies, dict):
            raise ModpackFormatError(
                "modrinth.index.json is missing dependencies",
                field="dependencies",
            )
        mc_version = dependencies.get("minecraft")
        try:
            MinecraftVersion.parse(mc_version if isinstance(mc_version, str) else "")
        except ValueError as exc:
            raise ModpackFormatError(
                "modrinth.index.json has an invalid minecraft dependency",
                field="dependencies.minecraft",
            ) from exc

        loader_keys = [key for key in MRPACK_LOADER_KEY_MAP if key in dependencies]
        if len(loader_keys) != 1:
            raise ModpackFormatError(
                "Modrinth pack must declare exactly one loader dependency",
                field="dependencies",
            )
        loader_key = loader_keys[0]
        loader_id = MRPACK_LOADER_KEY_MAP[loader_key]
        loader_version = dependencies.get(loader_key)
        if not isinstance(loader_version, str) or not loader_version:
            raise ModpackFormatError(
                f"Modrinth pack has an invalid {loader_key} version",
                field="dependencies",
            )
        if loader_id == "forge":
            validate_forge_mc_version(str(mc_version))

        (
            index_files,
            skipped_client,
            skipped_optional,
            index_discarded_paths,
            warnings,
        ) = _parse_index_files(
            payload,
            install_optional_server_files=install_optional_server_files,
            extra_allowed_hosts=extra_allowed_hosts,
        )

        effective, override_warnings = _effective_override_members(infos)
        warnings.extend(override_warnings)

        removed_index_paths: set[str] = set()
        index_by_casefold = {f.path.casefold(): f.path for f in index_files}
        for relpath in effective:
            index_path = index_by_casefold.get(relpath.casefold())
            if index_path is None:
                continue
            if index_path != relpath:
                raise CaseCollisionError(
                    "Casefold collision between index files and overrides",
                    path_a=index_path,
                    path_b=relpath,
                )
            removed_index_paths.add(index_path)

        surviving_index_files = [
            f for f in index_files if f.path not in removed_index_paths
        ]
        for removed in sorted(removed_index_paths):
            warnings.append(f"override_supersedes_index_file:{removed}")

        plan_files = [
            InstallPlanFile(
                path=f.path,
                sha1=f.sha1,
                sha512=f.sha512,
                size=f.size,
                downloads=f.downloads,
                env_server=f.env_server,
                optional=f.optional,
                origin=Origin.MODRINTH,
                source_layer="index",
            )
            for f in surviving_index_files
        ]

        override_members: list[tuple[str, zipfile.ZipInfo, str, str, bytes]] = []
        discarded_paths: list[str] = list(index_discarded_paths)
        override_jar_digests: dict[str, str] = {}
        for relpath in sorted(effective):
            info, layer = effective[relpath]
            classification = classify_and_validate_target_path(relpath, info.file_size)
            if classification in ("DISCARD", "SKIP"):
                discarded_paths.append(relpath)
                if classification == "SKIP":
                    warnings.append(f"skipped_path:{relpath}")
                continue
            max_bytes = (
                MAX_CLASS_B_ROUTED_BYTES
                if classification in ("B", "B-ROUTED-CAS")
                else None
            )
            data = read_zip_member_bounded(
                zf,
                info,
                max_bytes=max_bytes,
            )
            digest = hashlib.sha512(data).hexdigest()
            override_members.append((relpath, info, layer, classification, data))
            if _is_override_filter_jar(relpath):
                override_jar_digests[digest] = relpath

        client_only_hashes: set[str] = set()
        if override_jar_digests:
            client = modrinth_client or ModrinthProvider()
            (
                client_only_hashes,
                _matched_versions,
                _matched_projects,
            ) = await client.classify_client_only_jars_by_sha512(
                sorted(override_jar_digests)
            )

        overrides: list[InstallPlanOverride] = []
        override_blobs: dict[str, bytes] = {}
        skipped_client_override_jars: list[str] = []
        for relpath, info, layer, classification, data in override_members:
            digest = hashlib.sha512(data).hexdigest()
            if digest in client_only_hashes:
                skipped_client_override_jars.append(relpath)
                logger.info("skipped_client_override_jar path=%s", relpath)
                continue
            overrides.append(
                InstallPlanOverride(
                    path=relpath,
                    archive_path=info.filename,
                    source_layer=layer,
                    classification=classification,
                    sha256=hashlib.sha256(data).hexdigest(),
                    sha512=digest,
                    sha1=hashlib.sha1(data).hexdigest(),
                    size=len(data),
                )
            )
            override_blobs[relpath] = data

        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"{project_id}:{version_id}"
        else:
            name = name.strip()[:256]

        plan = InstallPlan(
            source="modrinth",
            project_id=project_id,
            version_id=version_id,
            version_label=name,
            index_sha256=index_sha256,
            mc_version=str(mc_version),
            loader_id=loader_id,
            loader_version=loader_version,
            files=tuple(sorted(plan_files, key=lambda f: f.path)),
            overrides=tuple(sorted(overrides, key=lambda o: o.path)),
            manual_blockers=(),
            skipped_client_files=tuple(sorted(skipped_client)),
            skipped_optional_files=tuple(sorted(skipped_optional)),
            skipped_client_override_jars=tuple(sorted(skipped_client_override_jars)),
            discarded_paths=tuple(sorted(set(discarded_paths))),
            warnings=tuple(warnings),
        )
        return plan, override_blobs


def extract_overrides_safely(
    zf: zipfile.ZipFile,
    overrides: Sequence[InstallPlanOverride],
    dest_root: str | Path,
) -> list[Path]:
    """Stage override blobs beneath ``dest_root`` without ever following symlinks."""
    root = Path(dest_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    written: list[Path] = []
    for override in sorted(overrides, key=lambda o: o.path):
        info = zf.getinfo(override.archive_path)
        max_bytes = (
            MAX_CLASS_B_ROUTED_BYTES
            if override.classification in ("B", "B-ROUTED-CAS")
            else None
        )
        data = read_zip_member_bounded(zf, info, max_bytes=max_bytes)
        if hashlib.sha256(data).hexdigest() != override.sha256:
            raise ModpackFormatError(
                f"Override changed after planning: {override.path[:128]!r}",
                field="overrides",
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        try:
            fd = open_safe_path_fd(
                str(root),
                override.path,
                flags=flags,
                mode=0o644,
                allow_create_parents=True,
            )
        except SymlinkEscapeError:
            raise
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        written.append(root / override.path)
    return written


def replace_plan(
    plan: InstallPlan,
    *,
    files: Sequence[InstallPlanFile] | None = None,
    overrides: Sequence[InstallPlanOverride] | None = None,
    manual_blockers: Sequence[ManualDownloadBlocker] | None = None,
    skipped_client_files: Sequence[str] | None = None,
    skipped_client_override_jars: Sequence[str] | None = None,
    warnings: Sequence[str] | None = None,
) -> InstallPlan:
    """Return a copy of ``plan`` with deterministic ordering after mutations."""
    return replace(
        plan,
        files=tuple(sorted(files if files is not None else plan.files, key=lambda f: f.path)),
        overrides=tuple(
            sorted(overrides if overrides is not None else plan.overrides, key=lambda o: o.path)
        ),
        manual_blockers=tuple(
            manual_blockers if manual_blockers is not None else plan.manual_blockers
        ),
        skipped_client_files=tuple(
            sorted(
                dict.fromkeys(
                    skipped_client_files
                    if skipped_client_files is not None
                    else plan.skipped_client_files
                )
            )
        ),
        skipped_client_override_jars=tuple(
            sorted(
                dict.fromkeys(
                    skipped_client_override_jars
                    if skipped_client_override_jars is not None
                    else plan.skipped_client_override_jars
                )
            )
        ),
        warnings=tuple(warnings if warnings is not None else plan.warnings),
    )


__all__ = [
    "COMPRESSION_RATIO_SIZE_THRESHOLD_BYTES",
    "DISCARDED_ROOT_FILES",
    "FORBIDDEN_PREFIXES",
    "FORGE_MAX_MC",
    "FORGE_MIN_MC",
    "HOSTILE_EXECUTABLE_EXTENSIONS",
    "InstallPlan",
    "InstallPlanFile",
    "InstallPlanOverride",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
    "MAX_CLASS_B_FILE_BYTES",
    "MAX_CLASS_B_ROUTED_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MRPACK_LOADER_KEY_MAP",
    "ManualDownloadBlocker",
    "classify_and_validate_target_path",
    "extract_overrides_safely",
    "parse_mrpack",
    "read_zip_member_bounded",
    "replace_plan",
    "validate_archive_quarantine",
    "validate_forge_mc_version",
]
