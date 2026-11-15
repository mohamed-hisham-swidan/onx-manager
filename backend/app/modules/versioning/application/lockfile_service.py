"""Host lockfile service for reading and writing authoritative host lockfiles.

P2-1 Core Substrate — B4b
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from app.core.allowlist import SymlinkEscapeError
from app.core.host_state import HostStateLayout
from app.modules.versioning.domain.lockfile import LockfileV21, dump_lockfile, parse_lockfile
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

MAX_LOCKFILE_BYTES = 16 * 1024 * 1024  # 16 MiB


class LockfileServiceError(Exception):
    """Raised for lockfile service I/O, size, symlink, or permissions failures."""


class LockfileService:
    """Authoritative reader and writer for server host lockfiles."""

    def __init__(self, layout: HostStateLayout) -> None:
        self._layout = layout

    def path_for(self, server_id: str) -> Path:
        """Return the authoritative lockfile path for the given server ID.

        Validates the server segment using app.core.host_state.validate_server_segment
        via layout.server_meta_dir.
        """
        server_dir = self._layout.server_meta_dir(server_id)
        return server_dir / "onx-jars.lock.json"

    def exists(self, server_id: str) -> bool:
        """Return True if an authoritative lockfile exists and is a regular file."""
        path = self.path_for(server_id)
        return path.is_file() and not path.is_symlink()

    def read(self, server_id: str) -> LockfileV21 | None:
        """Read and parse the authoritative host lockfile.

        Returns None if the lockfile does not exist.
        Raises LockfileServiceError on I/O, symlink, or size violations.
        Raises B2 lockfile domain exceptions unchanged on malformed content.
        """
        path = self.path_for(server_id)

        if os.name == "posix":
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags)
            except FileNotFoundError:
                return None
            except OSError as e:
                raise LockfileServiceError(f"Failed to open lockfile {path}: {e}") from e

            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise LockfileServiceError(f"Lockfile {path} is not a regular file")
                if st.st_size > MAX_LOCKFILE_BYTES:
                    raise LockfileServiceError(
                        f"Lockfile {path} exceeds maximum size of {MAX_LOCKFILE_BYTES} bytes "
                        f"(size: {st.st_size})"
                    )
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = os.read(fd, min(65536, MAX_LOCKFILE_BYTES + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_LOCKFILE_BYTES:
                        raise LockfileServiceError(
                            f"Lockfile {path} exceeds maximum size of {MAX_LOCKFILE_BYTES} bytes"
                        )
                raw = b"".join(chunks)
            except OSError as e:
                raise LockfileServiceError(f"Failed to read lockfile {path}: {e}") from e
            finally:
                os.close(fd)
        else:
            if not path.is_file():
                if not path.exists():
                    return None
                raise LockfileServiceError(f"Lockfile {path} is not a regular file")
            try:
                st = path.stat()
                if st.st_size > MAX_LOCKFILE_BYTES:
                    raise LockfileServiceError(
                        f"Lockfile {path} exceeds maximum size of {MAX_LOCKFILE_BYTES} bytes "
                        f"(size: {st.st_size})"
                    )
                raw = path.read_bytes()
                if len(raw) > MAX_LOCKFILE_BYTES:
                    raise LockfileServiceError(
                        f"Lockfile {path} exceeds maximum size of {MAX_LOCKFILE_BYTES} bytes"
                    )
            except FileNotFoundError:
                return None
            except OSError as e:
                raise LockfileServiceError(f"Failed to read lockfile {path}: {e}") from e

        return parse_lockfile(raw)

    def write(self, server_id: str, lockfile: LockfileV21) -> Path:
        """Serialize and atomically write the authoritative host lockfile.

        Ensures parent directory exists with 0700 on POSIX without following symlinks.
        Writes with atomic_write_private (0600, parent fsync).
        """
        path = self.path_for(server_id)
        parent = path.parent

        if os.name == "posix":
            if self._layout.root.is_symlink():
                raise LockfileServiceError(f"Layout root is a symlink: {self._layout.root}")
            if self._layout.server_meta.is_symlink():
                raise LockfileServiceError(
                    f"Layout server_meta is a symlink: {self._layout.server_meta}"
                )
            if parent.is_symlink():
                raise LockfileServiceError(f"Parent directory is a symlink: {parent}")

            try:
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError as e:
                raise LockfileServiceError(f"Failed to create directory {parent}: {e}") from e

            if parent.is_symlink():
                raise LockfileServiceError(f"Parent directory is a symlink: {parent}")
            if not parent.is_dir():
                raise LockfileServiceError(f"Parent path {parent} is not a directory")

            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
            try:
                fd = os.open(parent, flags)
            except OSError as e:
                raise LockfileServiceError(f"Failed to open directory {parent}: {e}") from e
            try:
                st = os.fstat(fd)
                if not stat.S_ISDIR(st.st_mode):
                    raise LockfileServiceError(f"Parent path {parent} is not a directory")
                mode = stat.S_IMODE(st.st_mode)
                if mode != 0o700:
                    if st.st_uid == os.geteuid():
                        os.fchmod(fd, 0o700)
                    else:
                        raise LockfileServiceError(
                            f"Parent directory {parent} permissions ({oct(mode)}) are not 0700 "
                            f"and not owned by current process"
                        )
            finally:
                os.close(fd)
        else:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise LockfileServiceError(f"Failed to create directory {parent}: {e}") from e

        data = dump_lockfile(lockfile)
        try:
            atomic_write_private(path, data, mode=0o600, fsync_parent=True)
        except (SymlinkEscapeError, OSError) as e:
            raise LockfileServiceError(f"Failed to write lockfile {path}: {e}") from e
        return path
