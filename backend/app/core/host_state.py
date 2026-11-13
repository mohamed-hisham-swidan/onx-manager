"""Authoritative host-state layout, resolution, and validation.

P2-1 Core Substrate — B4a
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import AppSettings, ConfigFactory
from app.core.exceptions import InvalidValueError, MCSError, PathContainmentError, ValidationError

_SERVER_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
_WIN_DRIVE_RE = re.compile(r"^[a-zA-Z]:[/\\].*")
_UNC_RE = re.compile(r"^//[^/]+/[^/]+|^\\\\.+")


class HostStateError(ValidationError):
    """Base error for host-state initialization and access failures."""


class HostStateContainmentError(HostStateError, PathContainmentError):
    """Raised when a host-state path violates containment boundaries."""

    def __init__(self, message: str = "", *, path: str = "", root: str = "") -> None:
        msg = message or f"Path '{path}' must be strictly inside '{root}'"
        MCSError.__init__(
            self,
            msg,
            code="HOST_STATE_CONTAINMENT_VIOLATION",
            http_status=403,
            details={"path": path, "root": root},
        )
        self.path = path
        self.root = root


class HostStateSymlinkError(HostStateError):
    """Raised when a host-state path or component is an unsafe symlink/reparse point."""


def validate_server_segment(server_id: str) -> str:
    """Validate server identifier for safe use in filesystem paths.

    Accepts ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$; rejects '.', '..', separators,
    NUL, and Windows reserved device names.
    """
    if (
        not isinstance(server_id, str)
        or not _SERVER_SEGMENT_RE.match(server_id)
        or server_id.lower() in _RESERVED_NAMES
    ):
        raise InvalidValueError("server_id", server_id, "invalid server segment")
    return server_id


def is_lexically_absolute(path_str: str) -> bool:
    """Check if a path string is lexically absolute on POSIX or Windows."""
    if not path_str:
        return False
    if posixpath.isabs(path_str):
        return True
    return bool(_WIN_DRIVE_RE.match(path_str) or _UNC_RE.match(path_str))


def normalize_host_root_path(path_str: str) -> str:
    """Normalize a Docker-host-visible path lexically without resolving via panel filesystem."""
    forward = path_str.replace("\\", "/")
    return posixpath.normpath(forward)


def check_not_symlink_or_reparse(path: Path | str) -> None:
    """Reject symlinks on all platforms and NTFS reparse points/junctions on Windows."""
    p = Path(path)
    if p.is_symlink():
        raise HostStateSymlinkError(f"Path is a symlink: {p}")
    if not p.exists():
        return
    try:
        st = p.lstat()
    except OSError:
        return
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(st, "st_file_attributes", 0) & reparse:
        raise HostStateSymlinkError(f"Reparse point/junction rejected: {p}")


@dataclass(frozen=True)
class HostStateLayout:
    root: Path
    server_meta: Path  # <root>/server-meta
    class_c_vault: Path  # <root>/class-c-vault
    quarantine: Path  # <root>/quarantine
    lec: Path  # <root>/lec
    cas: Path  # <root>/cas (ArtifactCas root; appends sha256/)
    repos: Path  # <root>/repos
    locks: Path  # <root>/locks
    journal: Path  # <root>/journal
    host_root: str | None = None
    marker_id: str = ""
    marker_status: str = "unverified"

    def server_meta_dir(self, server_id: str) -> Path:
        seg = validate_server_segment(server_id)
        return self.server_meta / seg

    def quarantine_dir(self, server_id: str) -> Path:
        seg = validate_server_segment(server_id)
        return self.quarantine / seg

    def class_c_vault_dir(self, server_id: str) -> Path:
        seg = validate_server_segment(server_id)
        return self.class_c_vault / seg

    def repo_dir(self, server_id: str) -> Path:
        """Return the per-server repository storage directory outside the server tree."""
        seg = validate_server_segment(server_id)
        return self.repos / seg


def _ensure_directory(path: Path) -> None:
    """Ensure directory exists with 0700 on POSIX or default ACL on Windows.

    On POSIX, missing ancestors are created with 0700 component-by-component.
    Descriptors with O_NOFOLLOW | O_DIRECTORY are used for fchmod/fstat to prevent
    symlink-swap attacks. Existing ancestors are never chmodded.
    """
    check_not_symlink_or_reparse(path)
    if os.name != "posix":
        if path.exists():
            if not path.is_dir():
                raise HostStateError(f"Path exists and is not a directory: {path}")
        else:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise HostStateError(f"Failed to create directory {path}: {e}") from e
        return

    # POSIX path: descriptor-based mode enforcement and component-by-component creation
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)

    if not path.exists() and not path.is_symlink():
        missing: list[Path] = []
        curr = path
        while not curr.exists() and not curr.is_symlink():
            missing.append(curr)
            parent = curr.parent
            if parent == curr:
                break
            curr = parent

        check_not_symlink_or_reparse(curr)
        missing.reverse()
        for p in missing:
            check_not_symlink_or_reparse(p)
            try:
                os.mkdir(p, 0o700)
            except OSError as e:
                raise HostStateError(f"Failed to create directory {p}: {e}") from e
            try:
                fd = os.open(p, flags)
            except OSError as e:
                raise HostStateError(f"Failed to open directory {p}: {e}") from e
            try:
                os.fchmod(fd, 0o700)
            finally:
                os.close(fd)
        return

    # Existing directory on POSIX
    if not path.is_dir():
        raise HostStateError(f"Path exists and is not a directory: {path}")

    try:
        fd = os.open(path, flags)
    except OSError as e:
        raise HostStateError(f"Failed to open directory {path}: {e}") from e

    try:
        st = os.fstat(fd)
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o077:
            if st.st_uid == os.geteuid():
                os.fchmod(fd, 0o700)
            else:
                raise HostStateError(
                    f"Directory {path} permissions ({oct(mode)}) are broader than 0700 "
                    f"and owner UID {st.st_uid} does not match process UID {os.geteuid()}"
                )
    finally:
        os.close(fd)


def _read_marker_file(marker_file: Path) -> str:
    """Read and validate marker file with strict descriptor-based mode enforcement on POSIX."""
    check_not_symlink_or_reparse(marker_file)
    if os.name != "posix":
        if not marker_file.is_file():
            raise HostStateError(f"Marker path {marker_file} is not a regular file")
        try:
            content = marker_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as e:
            raise HostStateError(f"Failed to read marker {marker_file}: {e}") from e
    else:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(marker_file, flags)
        except OSError as e:
            raise HostStateError(f"Failed to open marker {marker_file}: {e}") from e

        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise HostStateError(f"Marker path {marker_file} is not a regular file")
            raw = os.read(fd, 4096)
            content = raw.decode("utf-8").strip()
            mode = stat.S_IMODE(st.st_mode)
            if mode & 0o077:
                if st.st_uid == os.geteuid():
                    os.fchmod(fd, 0o600)
                else:
                    raise HostStateError(
                        f"Marker file {marker_file} permissions ({oct(mode)}) are "
                        f"broader than 0600 and owner UID {st.st_uid} does not match "
                        f"process UID {os.geteuid()}"
                    )
        except (OSError, UnicodeDecodeError) as e:
            raise HostStateError(f"Failed to read or tighten marker {marker_file}: {e}") from e
        finally:
            os.close(fd)

    if len(content) != 32 or not all(c in "0123456789abcdefABCDEF" for c in content):
        raise HostStateError(
            f"Corrupt or invalid host-state marker in {marker_file}: {content!r}"
        )
    return content.lower()


def _write_marker_file(marker_file: Path, marker_id: str) -> None:
    """Create and write marker file with descriptor-based mode enforcement on POSIX."""
    check_not_symlink_or_reparse(marker_file)
    if os.name != "posix":
        try:
            marker_file.write_text(f"{marker_id}\n", encoding="utf-8")
        except OSError as e:
            raise HostStateError(f"Failed to write marker file {marker_file}: {e}") from e
    else:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | getattr(os, "O_EXCL", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            fd = os.open(marker_file, flags, 0o600)
        except OSError as e:
            raise HostStateError(f"Failed to create marker file {marker_file}: {e}") from e

        try:
            os.write(fd, f"{marker_id}\n".encode())
            os.fchmod(fd, 0o600)
        except OSError as e:
            raise HostStateError(f"Failed to write marker file {marker_file}: {e}") from e
        finally:
            os.close(fd)


def _ensure_marker(panel_root: Path, host_root: str | None) -> tuple[str, str]:
    """Ensure .onx-host-state-id marker exists with 0600 on POSIX and compare with host_root."""
    marker_file = panel_root / ".onx-host-state-id"

    if marker_file.exists() or marker_file.is_symlink():
        marker_id = _read_marker_file(marker_file)
    else:
        marker_id = uuid.uuid4().hex
        _write_marker_file(marker_file, marker_id)

    marker_status = "unverified"
    if host_root:
        # Visibility guard: host_root must be absolute in the panel platform's own sense
        platform_abs = ntpath.isabs(host_root) if os.name == "nt" else posixpath.isabs(host_root)
        if not platform_abs:
            return marker_id, "unverified"

        is_visible = False
        host_path = Path(host_root)
        try:
            if host_path.exists() and host_path.is_dir():
                is_visible = True
        except OSError:
            is_visible = False

        if is_visible:
            host_marker_file = host_path / ".onx-host-state-id"
            if host_marker_file.exists() or host_marker_file.is_symlink():
                host_marker_id = _read_marker_file(host_marker_file)
                if host_marker_id != marker_id:
                    raise HostStateError(
                        f"Host state marker mismatch between panel root ({marker_id}) "
                        f"and host root ({host_marker_id})"
                    )
                marker_status = "verified"
            else:
                _write_marker_file(host_marker_file, marker_id)
                marker_status = "verified"
        else:
            marker_status = "unverified"

    return marker_id, marker_status


def resolve_host_state_layout(settings: AppSettings | None = None) -> HostStateLayout:
    """Resolve and validate the HostStateLayout without creating directories."""
    if settings is None:
        settings = ConfigFactory.global_settings()

    servers_dir = Path(os.path.realpath(Path(settings.servers_data_dir).expanduser()))

    # Panel root resolution
    if settings.host_state_dir and settings.host_state_dir.strip():
        raw = settings.host_state_dir.strip()
        panel_root = Path(os.path.abspath(os.path.expanduser(raw)))
        if panel_root.is_symlink():
            raise HostStateSymlinkError(f"Host-state root is a symlink: {panel_root}")
        canonical_root = Path(os.path.realpath(panel_root))
    else:
        fallback = servers_dir.parent / "host-state"
        if fallback.is_symlink():
            raise HostStateSymlinkError(f"Host-state root is a symlink: {fallback}")
        canonical_root = Path(os.path.realpath(fallback))

    # Safety: check servers_data_dir containment against canonical paths
    try:
        canonical_root.relative_to(servers_dir)
        raise HostStateContainmentError(
            f"Host-state root '{canonical_root}' cannot be equal to or inside "
            f"servers directory '{servers_dir}'",
            path=str(canonical_root),
            root=str(servers_dir),
        )
    except ValueError:
        pass

    try:
        servers_dir.relative_to(canonical_root)
        raise HostStateContainmentError(
            f"Servers directory '{servers_dir}' cannot be inside "
            f"host-state root '{canonical_root}'",
            path=str(servers_dir),
            root=str(canonical_root),
        )
    except ValueError:
        pass

    # Docker-host-visible root resolution (lexical only, never canonicalized)
    host_root: str | None = None
    if settings.host_state_host_dir and settings.host_state_host_dir.strip():
        val = settings.host_state_host_dir.strip()
        if not is_lexically_absolute(val):
            raise ValidationError(
                f"host_state_host_dir must be an absolute path: '{val}'",
                field="host_state_host_dir",
            )
        host_root = normalize_host_root_path(val)
    elif settings.host_data_dir and settings.host_data_dir.strip():
        val = settings.host_data_dir.strip()
        if is_lexically_absolute(val):
            norm = normalize_host_root_path(val)
            parent = posixpath.dirname(norm)
            host_root = posixpath.join(parent, "host-state")
        else:
            host_root = None

    return HostStateLayout(
        root=canonical_root,
        server_meta=canonical_root / "server-meta",
        class_c_vault=canonical_root / "class-c-vault",
        quarantine=canonical_root / "quarantine",
        lec=canonical_root / "lec",
        cas=canonical_root / "cas",
        repos=canonical_root / "repos",
        locks=canonical_root / "locks",
        journal=canonical_root / "journal",
        host_root=host_root,
    )


def ensure_host_state_layout(settings: AppSettings | None = None) -> HostStateLayout:
    """Resolve, create, and validate layout directories and marker."""
    layout = resolve_host_state_layout(settings)

    _ensure_directory(layout.root)

    for subdir in (
        layout.server_meta,
        layout.class_c_vault,
        layout.quarantine,
        layout.lec,
        layout.cas,
        layout.repos,
        layout.locks,
        layout.journal,
    ):
        _ensure_directory(subdir)

    marker_id, marker_status = _ensure_marker(layout.root, layout.host_root)

    return HostStateLayout(
        root=layout.root,
        server_meta=layout.server_meta,
        class_c_vault=layout.class_c_vault,
        quarantine=layout.quarantine,
        lec=layout.lec,
        cas=layout.cas,
        repos=layout.repos,
        locks=layout.locks,
        journal=layout.journal,
        host_root=layout.host_root,
        marker_id=marker_id,
        marker_status=marker_status,
    )
