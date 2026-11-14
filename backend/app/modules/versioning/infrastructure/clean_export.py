"""Clean Export service for Advanced servers (P2-3).

The export is the only container root used by branch/test runs. It is built from
a pinned Git commit with the normative five-step order:

1. hardened ``git archive`` extraction;
2. Class-A materialization from the host CAS;
3. Loader Environment Cache (LEC) attach;
4. optional Class-E Data Template / Class-C snapshot overlay;
5. Class-D injection last (panel properties, EULA, JVM args, secrets).

Steps 1-4 use a probe-verified reflink on the exact file descriptors or a plain
copy under a per-``st_dev`` storage lock after a free-space reservation. Hard
links are never created. The export contains no ``.git`` and is finalized with a
fsynced ``.onx-complete.json`` marker.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:  # pragma: no cover - Advanced mode is POSIX-only
    fcntl = None  # type: ignore[assignment]

from app.core.allowlist import (
    CLASS_D_PANEL_KEYS,
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    validate_canonical_relpath,
)
from app.core.exceptions import (
    ConflictError,
    InsufficientStorageError,
    StorageCowUnavailableError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.domain.lockfile import (
    LecKeyParts,
    LockfileFile,
    LockfileV21,
    parse_lec_key,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import validate_server_root
from app.modules.versioning.infrastructure.git_runner import GitRunner

EXPORT_MARKER_NAME = ".onx-complete.json"
MAX_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_COPY_HEADROOM = 1.10
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"\A[0-9a-f]{40,64}\Z")
_SECRET_PLACEHOLDER_RE = re.compile(r"\$\{ONX_SECRET_([A-Za-z0-9_]+)\}")
_FORBIDDEN_EXPORT_NAMES = frozenset({"run.sh", "run.bat", "serverstarterjar", "serverstarter.jar"})
_TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".conf",
        ".json",
        ".json5",
        ".lang",
        ".mcmeta",
        ".mcfunction",
        ".properties",
        ".snbt",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_LEC_TREES: dict[str, tuple[str, ...]] = {
    "fabric": ("libraries", ".fabric/server"),
    "quilt": ("libraries",),
    "forge": ("libraries",),
    "neoforge": ("libraries",),
    "paper": ("cache", "versions"),
    "purpur": ("cache", "versions"),
}

_DENIED_ARCHIVE_FILES = frozenset({".git", "run.sh", "run.bat", "user_jvm_args.txt"})
_DENIED_ARCHIVE_PREFIXES = (".git/", "libraries/", ".fabric/")


@dataclass(frozen=True)
class CleanExportRequest:
    """Inputs for one clean export of a pinned commit."""

    server_id: str
    server_root: str | os.PathLike[str]
    commit_sha: str
    destination: str | os.PathLike[str]
    lockfile: LockfileV21
    panel_properties: Mapping[str, str] = field(default_factory=dict)
    jvm_args: str = ""
    secrets: Mapping[str, str] = field(default_factory=dict)
    data_template_dir: str | os.PathLike[str] | None = None
    class_c_overlay_dir: str | os.PathLike[str] | None = None
    lec_root: str | os.PathLike[str] | None = None
    joinable_test_container: bool = False


@dataclass(frozen=True)
class CleanExportResult:
    """Result of a completed clean export."""

    root: Path
    marker_path: Path
    file_count: int
    total_bytes: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short write")
        view = view[written:]


def _hash_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, _CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(fd)


def _is_text_relpath(relpath: str) -> bool:
    suffix = Path(relpath).suffix.casefold()
    return suffix in _TEXT_SUFFIXES


def _validate_export_relpath(relpath: str) -> str:
    try:
        return validate_canonical_relpath(relpath)
    except ValueError as exc:
        raise ValidationError(
            "Export path is not a canonical relative path",
            field="path",
            details={"path": str(relpath)[:128], "reason": str(exc)[:128]},
        ) from exc


def _validate_secret_value(key: str, value: object) -> str:
    text = str(value)
    if any(ch in text for ch in ("\x00", "\n", "\r")):
        raise ValidationError(
            "Secret value contains a forbidden control character",
            field="secrets",
            details={"key": key[:128]},
        )
    return text


def _substitute_secrets(text: str, secrets: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in secrets:
            raise ValidationError(
                "Unresolved secret placeholder in export",
                field="secrets",
                details={"key": key[:128]},
            )
        return _validate_secret_value(key, secrets[key])

    return _SECRET_PLACEHOLDER_RE.sub(replace, text)


def _render_properties(props: Mapping[str, str]) -> bytes:
    lines = [f"{key}={props[key]}" for key in sorted(props)]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _parse_properties(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("server.properties is not valid UTF-8", field="path") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    props: dict[str, str] = {}
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line:
            raise ValidationError(
                "server.properties contains a line that is not key=value",
                field="path",
                details={"line": line[:128]},
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValidationError("server.properties contains an empty property key", field="path")
        props[key] = value
    return props


def _validate_property_entry(key: str, value: object) -> tuple[str, str]:
    clean_key = str(key).strip()
    clean_value = str(value).strip()
    if not clean_key or "=" in clean_key:
        raise ValidationError("Invalid panel property key", field="properties")
    if any(ch in clean_key + clean_value for ch in ("\x00", "\n", "\r")):
        raise ValidationError(
            "Panel property contains a forbidden control character",
            field="properties",
        )
    return clean_key, clean_value


class CleanExportService:
    """Build a container-ready export from a pinned native Git commit."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        branch_service: GitBranchService | None = None,
        cas: ArtifactCas | None = None,
    ) -> None:
        self._layout = layout
        self._branch_service = branch_service or GitBranchService(layout)
        self._cas = cas or ArtifactCas(layout.cas)

    def export(
        self,
        request: CleanExportRequest,
        *,
        fencing_verifier: Callable[[], None] | None = None,
    ) -> CleanExportResult:
        if os.name != "posix":
            raise StorageCowUnavailableError(str(request.destination))
        server_id = validate_server_segment(request.server_id)
        server_root = validate_server_root(request.server_root)
        destination = self._prepare_destination(request.destination)
        archive_dir: Path | None = None
        try:
            runner = self._branch_service.open_runner(server_id, server_root)
            commit_sha = self._resolve_commit(runner, request.commit_sha)

            archive_dir = Path(tempfile.mkdtemp(prefix=".onx-export-", dir=str(destination.parent)))
            archive_path = archive_dir / "export.tar"
            runner.run(
                "archive",
                "--format=tar",
                "--no-worktree-attributes",
                f"--output={archive_path}",
                commit_sha,
            )
            self._extract_archive(archive_path, destination)
            self._materialize_class_a(destination, request.lockfile)
            self._attach_lec(destination, request)
            if request.data_template_dir is not None:
                self._copy_tree(
                    Path(request.data_template_dir),
                    destination,
                    overwrite=True,
                    label="Data Template",
                    allowed_class="E",
                    require_marker=True,
                )
            if request.class_c_overlay_dir is not None:
                self._copy_tree(
                    Path(request.class_c_overlay_dir),
                    destination,
                    overwrite=True,
                    label="Class-C snapshot",
                    allowed_class="C",
                    require_marker=True,
                )
            self._inject_class_d(destination, request)
            file_count, total_bytes = self._measure_export(destination)
            if fencing_verifier is not None:
                fencing_verifier()
            marker_path = self._write_marker(destination, file_count, total_bytes)
            return CleanExportResult(
                root=destination,
                marker_path=marker_path,
                file_count=file_count,
                total_bytes=total_bytes,
            )
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            if archive_dir is not None:
                shutil.rmtree(archive_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Destination and commit resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_destination(raw: str | os.PathLike[str]) -> Path:
        try:
            text = os.fspath(raw)
        except TypeError as exc:
            raise ValidationError("Export destination must be a filesystem path") from exc
        if not isinstance(text, str) or not text:
            raise ValidationError("Export destination must be a non-empty path")
        if not os.path.isabs(text):
            raise ValidationError("Export destination must be an absolute path")
        destination = Path(os.path.abspath(text))
        parent = destination.parent
        if not parent.is_dir() or parent.is_symlink():
            raise ValidationError("Export destination parent is not a real directory")
        if os.path.realpath(parent) != str(parent):
            raise ValidationError("Export destination parent must not contain symlinks")
        if destination.exists() or destination.is_symlink():
            raise ValidationError(
                "Export destination already exists",
                field="destination",
                details={"path": str(destination)[:256]},
            )
        try:
            os.mkdir(destination, 0o700)
        except OSError as exc:
            raise ValidationError(
                f"Unable to create export destination: {exc}",
                field="destination",
            ) from exc
        return destination

    @staticmethod
    def _resolve_commit(runner: GitRunner, sha: str) -> str:
        if not isinstance(sha, str) or not _COMMIT_RE.match(sha):
            raise ValidationError("Export commit must be a 40-64 character hex object id")
        result = runner.run("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False)
        if result.returncode != 0:
            raise ValidationError(
                "Export commit does not exist",
                field="commit_sha",
                details={"sha": sha[:128]},
            )
        resolved = result.stdout.strip()
        if not _COMMIT_RE.match(resolved):
            raise ValidationError(
                "Git returned an invalid commit object id",
                field="commit_sha",
            )
        return resolved

    # ------------------------------------------------------------------
    # Step 1: git archive extraction
    # ------------------------------------------------------------------

    def _extract_archive(self, archive_path: Path, destination: Path) -> None:
        seen: set[str] = set()
        try:
            with tarfile.open(archive_path, mode="r:") as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValidationError(
                            "Archive contains a non-regular member",
                            field="archive",
                            details={"path": member.name[:128]},
                        )
                    relpath = _validate_export_relpath(member.name)
                    if relpath == EXPORT_MARKER_NAME:
                        raise ValidationError(
                            "Archive must not contain the completion marker",
                            field="archive",
                        )
                    if relpath in _DENIED_ARCHIVE_FILES or relpath.startswith(
                        _DENIED_ARCHIVE_PREFIXES
                    ):
                        raise ValidationError(
                            "Archive contains a path reserved for the export service",
                            field="archive",
                            details={"path": relpath[:128]},
                        )
                    if relpath in seen:
                        raise ConflictError(f"Archive contains duplicate path: {relpath[:128]}")
                    seen.add(relpath)
                    if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                        raise ValidationError(
                            "Archive member exceeds the export size limit",
                            field="archive",
                            details={"path": relpath[:128], "size": member.size},
                        )
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValidationError(
                            "Archive member has no readable payload",
                            field="archive",
                            details={"path": relpath[:128]},
                        )
                    try:
                        self._write_stream_to_new_file(destination, relpath, source)
                    finally:
                        source.close()
        except tarfile.TarError as exc:
            raise ValidationError("Unable to read the Git archive", field="archive") from exc
        except SymlinkEscapeError as exc:
            raise ValidationError(
                "Archive member escapes the export root",
                field="archive",
            ) from exc

    @staticmethod
    def _write_stream_to_new_file(root: Path, relpath: str, source: IO[bytes]) -> None:
        try:
            fd = open_safe_path_fd(
                str(root),
                relpath,
                flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode=0o644,
                allow_create_parents=True,
            )
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise ConflictError(f"Export path already exists: {relpath[:128]}") from exc
            raise
        try:
            while True:
                chunk = source.read(_CHUNK_SIZE)
                if not chunk:
                    break
                _write_all(fd, chunk)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Step 2: Class-A materialization
    # ------------------------------------------------------------------

    def _materialize_class_a(self, destination: Path, lockfile: LockfileV21) -> None:
        for relpath in lockfile.base_overrides:
            _validate_export_relpath(relpath)
        for entry in lockfile.files:
            self._materialize_one(destination, entry)

    def _materialize_one(self, destination: Path, entry: LockfileFile) -> None:
        relpath = _validate_export_relpath(entry.path)
        if not _SHA256_RE.match(entry.sha256):
            raise ValidationError("Invalid CAS digest in lockfile", field="sha256")
        existing_path = destination / relpath
        if existing_path.exists() or existing_path.is_symlink():
            existing_digest = self._hash_export_file(destination, relpath)
            if existing_digest == entry.sha256:
                return
            raise ConflictError(f"Export path collides with a Class-A CAS entry: {relpath[:128]}")
        if not self._cas.has(entry.sha256):
            if entry.optional:
                return
            raise ValidationError(
                "Class-A CAS blob is missing for export",
                field="cas",
                details={"path": relpath[:128]},
            )
        with self._cas.open_blob(entry.sha256) as source:
            stat_result = os.fstat(source.fileno())
            if stat_result.st_size != entry.size:
                raise ValidationError(
                    "Class-A CAS size does not match the lockfile",
                    field="cas",
                    details={"path": relpath[:128]},
                )
            try:
                fd = open_safe_path_fd(
                    str(destination),
                    relpath,
                    flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    mode=0o644,
                    allow_create_parents=True,
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise ConflictError(f"Export path already exists: {relpath[:128]}") from exc
                raise
            try:
                self._copy_fd(source.fileno(), fd, entry.size)
            finally:
                os.close(fd)

    @staticmethod
    def _hash_export_file(root: Path, relpath: str) -> str:
        try:
            fd = open_safe_path_fd(str(root), relpath, flags=os.O_RDONLY)
        except OSError as exc:
            raise ValidationError(
                "Unable to read export path",
                field="path",
                details={"path": relpath[:128]},
            ) from exc
        try:
            return _hash_fd(fd)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Step 3: LEC attach
    # ------------------------------------------------------------------

    def _attach_lec(self, destination: Path, request: CleanExportRequest) -> None:
        lec = request.lockfile.lec
        if lec is None:
            return
        parts = parse_lec_key(lec.key)
        if request.lec_root is not None:
            lec_root = Path(os.path.abspath(os.fspath(request.lec_root)))
        else:
            lec_root = self._layout.lec / lec.key
        if lec_root.is_symlink() or not lec_root.is_dir():
            raise ValidationError(
                "LEC tree is missing for export",
                field="lec",
                details={"key": lec.key[:128]},
            )
        if os.path.realpath(lec_root) != str(lec_root):
            raise ValidationError("LEC tree must not contain symlinks", field="lec")

        trees = _LEC_TREES.get(parts.loader, ())
        if not trees:
            raise ValidationError("Unsupported loader for clean export", field="lec")
        copied_any = False
        for tree in trees:
            source = lec_root / tree
            if source.is_symlink():
                raise ValidationError("LEC tree contains a symlink", field="lec")
            if source.is_dir():
                self._copy_tree(
                    source,
                    destination,
                    overwrite=False,
                    label=f"LEC {tree}",
                    dest_prefix=tree,
                )
                copied_any = True
        if not copied_any:
            raise ValidationError(
                "LEC tree does not contain the required loader files",
                field="lec",
                details={"key": lec.key[:128]},
            )
        if parts.loader in {"forge", "neoforge", "quilt"}:
            unix_args = destination / _unix_args_relpath(parts)
            if not unix_args.is_file() or unix_args.is_symlink() or unix_args.stat().st_size == 0:
                raise ValidationError(
                    "LEC export has no non-empty unix_args.txt",
                    field="lec",
                    details={"key": lec.key[:128]},
                )

    # ------------------------------------------------------------------
    # Step 4: overlays
    # ------------------------------------------------------------------

    def _copy_tree(
        self,
        source_root: Path,
        destination_root: Path,
        *,
        overwrite: bool,
        label: str,
        dest_prefix: str = "",
        allowed_class: str = "",
        require_marker: bool = False,
    ) -> None:
        source = Path(os.path.abspath(source_root))
        if source.is_symlink() or not source.is_dir():
            raise ValidationError(f"{label} source is not a directory", field="overlay")
        if os.path.realpath(source) != str(source):
            raise ValidationError(f"{label} source must not contain symlinks", field="overlay")
        if require_marker:
            marker = source / EXPORT_MARKER_NAME
            if marker.is_symlink() or not marker.is_file():
                raise ValidationError(
                    f"{label} lacks the {EXPORT_MARKER_NAME} marker",
                    field="overlay",
                    details={"path": str(source)[:256]},
                )
        self._copy_tree_dir(
            source, source, destination_root, overwrite, label, dest_prefix, allowed_class
        )

    def _copy_tree_dir(
        self,
        current: Path,
        source_root: Path,
        destination_root: Path,
        overwrite: bool,
        label: str,
        dest_prefix: str,
        allowed_class: str,
    ) -> None:
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError as exc:
            raise ValidationError(f"Unable to read {label} tree", field="overlay") from exc
        for entry in entries:
            path = Path(entry.path)
            source_relpath = path.relative_to(source_root).as_posix()
            dest_relpath = f"{dest_prefix}/{source_relpath}" if dest_prefix else source_relpath
            name = entry.name.casefold()
            if entry.is_symlink():
                raise ValidationError(
                    f"{label} contains a symlink",
                    field="overlay",
                    details={"path": source_relpath[:128]},
                )
            if entry.is_dir(follow_symlinks=False):
                if name == ".git":
                    continue
                self._copy_tree_dir(
                    path,
                    source_root,
                    destination_root,
                    overwrite,
                    label,
                    dest_prefix,
                    allowed_class,
                )
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValidationError(
                    f"{label} contains a non-regular file",
                    field="overlay",
                    details={"path": source_relpath[:128]},
                )
            if name in _FORBIDDEN_EXPORT_NAMES or entry.name == EXPORT_MARKER_NAME:
                continue
            _validate_export_relpath(dest_relpath)
            if allowed_class and classify(dest_relpath) != allowed_class:
                raise ValidationError(
                    f"{label} may only contain class-{allowed_class} paths",
                    field="overlay",
                    details={"path": dest_relpath[:128]},
                )
            self._copy_tree_file(
                source_root,
                destination_root,
                source_relpath,
                dest_relpath,
                overwrite=overwrite,
            )

    def _copy_tree_file(
        self,
        source_root: Path,
        destination_root: Path,
        source_relpath: str,
        dest_relpath: str,
        *,
        overwrite: bool,
    ) -> None:
        try:
            source_fd = open_safe_path_fd(str(source_root), source_relpath, flags=os.O_RDONLY)
        except (OSError, SymlinkEscapeError) as exc:
            raise ValidationError(
                "Unable to open export source file",
                field="overlay",
                details={"path": source_relpath[:128]},
            ) from exc
        try:
            stat_result = os.fstat(source_fd)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValidationError(
                    "Export source is not a regular file",
                    field="overlay",
                    details={"path": source_relpath[:128]},
                )
            flags = os.O_WRONLY | os.O_CREAT
            flags |= os.O_TRUNC if overwrite else os.O_EXCL
            try:
                destination_fd = open_safe_path_fd(
                    str(destination_root),
                    dest_relpath,
                    flags=flags,
                    mode=0o644,
                    allow_create_parents=True,
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise ConflictError(
                        f"Export path already exists: {dest_relpath[:128]}"
                    ) from exc
                raise
            try:
                self._copy_fd(source_fd, destination_fd, stat_result.st_size)
            finally:
                os.close(destination_fd)
        finally:
            os.close(source_fd)

    # ------------------------------------------------------------------
    # Step 5: Class-D injection
    # ------------------------------------------------------------------

    def _inject_class_d(self, destination: Path, request: CleanExportRequest) -> None:
        props = self._read_existing_properties(destination)
        for key in list(props):
            if key in CLASS_D_PANEL_KEYS or key.startswith("management-server-"):
                del props[key]
        for key, value in request.panel_properties.items():
            clean_key, clean_value = _validate_property_entry(key, value)
            props[clean_key] = clean_value
        if request.joinable_test_container:
            props["white-list"] = "true"
            props["enforce-whitelist"] = "true"
        props = {key: _substitute_secrets(value, request.secrets) for key, value in props.items()}
        self._write_export_file(destination, "server.properties", _render_properties(props))
        self._write_export_file(destination, "eula.txt", b"eula=true\n")
        jvm_args = request.jvm_args
        if jvm_args and not jvm_args.endswith("\n"):
            jvm_args += "\n"
        self._write_export_file(
            destination,
            "user_jvm_args.txt",
            _substitute_secrets(jvm_args, request.secrets).encode("utf-8"),
        )
        self._substitute_text_tree(destination, request.secrets)

    def _read_existing_properties(self, destination: Path) -> dict[str, str]:
        path = destination / "server.properties"
        if not path.exists() and not path.is_symlink():
            return {}
        try:
            fd = open_safe_path_fd(str(destination), "server.properties", flags=os.O_RDONLY)
        except (OSError, SymlinkEscapeError) as exc:
            raise ValidationError(
                "Unable to read exported server.properties", field="path"
            ) from exc
        try:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(fd, _CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValidationError("Exported server.properties is too large", field="path")
                chunks.append(chunk)
        finally:
            os.close(fd)
        return _parse_properties(b"".join(chunks))

    def _substitute_text_tree(self, destination: Path, secrets: Mapping[str, str]) -> None:
        for dirpath, dirnames, filenames in os.walk(destination, followlinks=False):
            for dirname in list(dirnames):
                candidate = Path(dirpath) / dirname
                if candidate.is_symlink():
                    raise ValidationError("Export tree contains a symlink", field="path")
                if dirname == ".git":
                    raise ValidationError("Export tree must not contain .git", field="path")
            for filename in filenames:
                path = Path(dirpath) / filename
                relpath = path.relative_to(destination).as_posix()
                if filename.casefold() == ".git":
                    raise ValidationError("Export tree must not contain .git", field="path")
                if not _is_text_relpath(relpath):
                    continue
                try:
                    fd = open_safe_path_fd(str(destination), relpath, flags=os.O_RDONLY)
                except (OSError, SymlinkEscapeError) as exc:
                    raise ValidationError(
                        "Unable to read export text file",
                        field="path",
                        details={"path": relpath[:128]},
                    ) from exc
                try:
                    data = os.read(fd, MAX_ARCHIVE_MEMBER_BYTES + 1)
                finally:
                    os.close(fd)
                if len(data) > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValidationError(
                        "Export text file is too large",
                        field="path",
                        details={"path": relpath[:128]},
                    )
                if b"${ONX_SECRET_" not in data:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                replaced = _substitute_secrets(text, secrets)
                if replaced != text:
                    self._write_export_file(destination, relpath, replaced.encode("utf-8"))

    @staticmethod
    def _write_export_file(root: Path, relpath: str, data: bytes) -> None:
        relpath = _validate_export_relpath(relpath)
        try:
            fd = open_safe_path_fd(
                str(root),
                relpath,
                flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                mode=0o644,
                allow_create_parents=True,
            )
        except (OSError, SymlinkEscapeError) as exc:
            raise ValidationError(
                "Unable to write export file",
                field="path",
                details={"path": relpath[:128]},
            ) from exc
        try:
            _write_all(fd, data)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Copy primitives: reflink on exact fds, else locked plain copy
    # ------------------------------------------------------------------

    def _copy_fd(self, source_fd: int, destination_fd: int, size: int) -> None:
        if self._try_reflink(source_fd, destination_fd, size):
            return
        self._assert_free_space(destination_fd, size)
        with self._copy_lock(os.fstat(destination_fd).st_dev):
            os.ftruncate(destination_fd, 0)
            os.lseek(destination_fd, 0, os.SEEK_SET)
            os.lseek(source_fd, 0, os.SEEK_SET)
            remaining = size
            while remaining > 0:
                chunk = os.read(source_fd, min(_CHUNK_SIZE, remaining))
                if not chunk:
                    raise OSError(errno.EIO, "unexpected end of source file")
                _write_all(destination_fd, chunk)
                remaining -= len(chunk)
        if os.fstat(destination_fd).st_size != size:
            raise OSError(errno.EIO, "copied file has the wrong size")

    @staticmethod
    def _try_reflink(source_fd: int, destination_fd: int, size: int) -> bool:
        if fcntl is None:  # pragma: no cover - POSIX-only path
            return False
        try:
            fcntl.ioctl(destination_fd, 0x40049409, source_fd)
        except OSError:
            return False
        if os.fstat(destination_fd).st_size != size:
            with contextlib.suppress(OSError):
                os.ftruncate(destination_fd, 0)
            return False
        return True

    @staticmethod
    def _assert_free_space(destination_fd: int, size: int) -> None:
        vfs = os.fstatvfs(destination_fd)
        free = vfs.f_bavail * vfs.f_frsize
        required = int(size * _COPY_HEADROOM) + 1
        if free < required:
            raise InsufficientStorageError(details={"required_bytes": required, "free_bytes": free})

    @contextlib.contextmanager
    def _copy_lock(self, st_dev: int):
        if fcntl is None:  # pragma: no cover - POSIX-only path
            yield
            return
        lock_path = self._layout.locks / f"copy-{st_dev}.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # ------------------------------------------------------------------
    # Completion marker and export invariants
    # ------------------------------------------------------------------

    def _measure_export(self, root: Path) -> tuple[int, int]:
        file_count = 0
        total_bytes = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for dirname in list(dirnames):
                candidate = Path(dirpath) / dirname
                if candidate.is_symlink():
                    raise ValidationError("Export tree contains a symlink directory", field="path")
                if dirname == ".git":
                    raise ValidationError("Export tree must not contain .git", field="path")
            for filename in filenames:
                path = Path(dirpath) / filename
                stat_result = path.lstat()
                if filename.casefold() == ".git":
                    raise ValidationError("Export tree must not contain .git", field="path")
                if stat.S_ISLNK(stat_result.st_mode):
                    raise ValidationError("Export tree contains a symlink file", field="path")
                if not stat.S_ISREG(stat_result.st_mode):
                    raise ValidationError("Export tree contains a non-regular file", field="path")
                if filename.casefold() in _FORBIDDEN_EXPORT_NAMES:
                    raise ValidationError(
                        "Export tree contains a forbidden executable", field="path"
                    )
                if stat_result.st_nlink != 1:
                    raise ValidationError("Export tree contains a hard link", field="path")
                file_count += 1
                total_bytes += stat_result.st_size
        return file_count, total_bytes

    @staticmethod
    def _write_marker(root: Path, file_count: int, total_bytes: int) -> Path:
        payload = {
            "completed_at": _utc_now(),
            "total_bytes": total_bytes,
            "file_count": file_count,
        }
        data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            fd = open_safe_path_fd(
                str(root),
                EXPORT_MARKER_NAME,
                flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode=0o644,
            )
        except OSError as exc:
            raise ConflictError("Export completion marker already exists") from exc
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(root)
        return root / EXPORT_MARKER_NAME


def _unix_args_relpath(parts: LecKeyParts) -> str:
    if parts.loader == "neoforge":
        return f"libraries/net/neoforged/neoforge/{parts.version}/unix_args.txt"
    if parts.loader == "forge":
        return f"libraries/net/minecraftforge/forge/{parts.mc}-{parts.version}/unix_args.txt"
    if parts.loader == "quilt":
        return f"libraries/org/quiltmc/quilt-loader/{parts.version}/unix_args.txt"
    raise ValidationError("Loader has no unix_args.txt contract", field="lec")


__all__ = [
    "CleanExportRequest",
    "CleanExportResult",
    "CleanExportService",
    "EXPORT_MARKER_NAME",
]
