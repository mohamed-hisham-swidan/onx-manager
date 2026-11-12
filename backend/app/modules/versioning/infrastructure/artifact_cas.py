"""Content-Addressable Storage (CAS) for artifacts indexed by SHA-256."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import re
import stat
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.core.allowlist import SymlinkEscapeError, open_safe_path_fd
from app.core.exceptions import (
    CasBlobNotFoundError,
    CasContainmentError,
    CasCorruptionError,
    CasError,
    CasInvalidDigestError,
    CasInvalidSourceError,
    CasUnsupportedPlatformError,
    CasWriteError,
    InsufficientStorageError,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}\Z")
_CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunk size


def _validate_digest(digest: str) -> str:
    """Validate that digest is exactly 64 lowercase hexadecimal characters."""
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        truncated = str(digest)[:128]
        raise CasInvalidDigestError(
            "Digest must be exactly 64 lowercase hex characters", digest=truncated
        )
    return digest


def _check_ancestors_no_symlinks(path: Path) -> None:
    """Validate that path and all existing ancestors contain no symlinks."""
    curr = path
    path_str = str(path)[:128]
    while True:
        curr_str = str(curr)
        if os.path.islink(curr_str):
            raise CasContainmentError(
                f"Path component {curr.name!r} is a symlink",
                path=curr_str[:128],
                root=path_str,
            )
        if curr.exists(follow_symlinks=False):
            real = os.path.realpath(curr_str)
            if real != curr_str:
                raise CasContainmentError(
                    f"Path contains symlinked ancestor: {curr.name!r}",
                    path=curr_str[:128],
                    root=path_str,
                )
        parent = curr.parent
        if parent == curr:
            break
        curr = parent


class ArtifactCas:
    """Host-level SHA-256 Content-Addressable Storage."""

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root)
        if not root_path.is_absolute():
            raise CasContainmentError("CAS root must be an absolute path", root=str(root)[:128])
        self._root = root_path

    @property
    def root(self) -> Path:
        return self._root

    def _check_platform(self) -> None:
        if os.name != "posix":
            raise CasUnsupportedPlatformError("Artifact CAS requires a POSIX environment")

    def _open_root_fd(self, *, create: bool = False) -> int:
        """Open or initialize root directory fd with 0700 permissions and containment validation."""
        _check_ancestors_no_symlinks(self._root)
        root_str = str(self._root)

        if not self._root.exists(follow_symlinks=False):
            if not create:
                raise CasBlobNotFoundError("CAS root does not exist", root=root_str[:128])
            parent = self._root.parent
            if not parent.is_dir() or parent.is_symlink():
                raise CasWriteError("Parent of CAS root is not an existing directory")

            parent_flags = (
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                parent_fd = os.open(str(parent), parent_flags)
            except OSError as exc:
                raise CasWriteError(f"Failed opening parent directory (errno={exc.errno})") from exc

            try:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(self._root.name, 0o700, dir_fd=parent_fd)
            except OSError as exc:
                raise CasWriteError(f"Failed creating root directory (errno={exc.errno})") from exc
            finally:
                os.close(parent_fd)

        if not self._root.is_dir():
            raise CasCorruptionError(
                "CAS root exists but is not a directory", details={"root": root_str[:128]}
            )

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(root_str, flags)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasContainmentError(
                    "Root is a symlink or not a directory", root=root_str[:128]
                ) from exc
            raise CasWriteError(f"Failed opening root directory (errno={exc.errno})") from exc

        try:
            expected = os.stat(root_str)
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != (expected.st_dev, expected.st_ino):
                raise CasContainmentError(
                    "CAS root directory identity changed during open", root=root_str[:128]
                )
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.fchmod(fd, 0o700)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _ensure_subdir_fd(self, parent_fd: int, seg: str) -> int:
        """Open or create a sub-directory relative to parent_fd with mode 0700."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(seg, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                os.mkdir(seg, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise CasContainmentError(
                        f"Symlink or non-directory component rejected: {seg!r}",
                        path=seg[:128],
                        root=str(self._root)[:128],
                    ) from exc
                raise CasWriteError(
                    f"Failed creating directory {seg!r} (errno={exc.errno})"
                ) from exc
            try:
                fd = os.open(seg, flags, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise CasContainmentError(
                        f"Symlink or non-directory component rejected: {seg!r}",
                        path=seg[:128],
                        root=str(self._root)[:128],
                    ) from exc
                raise CasWriteError(
                    f"Failed opening created directory {seg!r} (errno={exc.errno})"
                ) from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasContainmentError(
                    f"Symlink or non-directory component rejected: {seg!r}",
                    path=seg[:128],
                    root=str(self._root)[:128],
                ) from exc
            raise CasWriteError(f"Failed opening directory {seg!r} (errno={exc.errno})") from exc

        st = os.fstat(fd)
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.fchmod(fd, 0o700)
        return fd

    def _ensure_layout_fds(self, digest: str) -> tuple[int, int, int]:
        """Ensure CAS layout and return (root_fd, tmp_dir_fd, prefix_dir_fd).

        Caller is responsible for closing all returned fds.
        """
        root_fd = self._open_root_fd(create=True)
        try:
            tmp_dir_fd = self._ensure_subdir_fd(root_fd, ".tmp")
            try:
                sha_dir_fd = self._ensure_subdir_fd(root_fd, "sha256")
                try:
                    prefix = digest[:2]
                    prefix_dir_fd = self._ensure_subdir_fd(sha_dir_fd, prefix)
                    return root_fd, tmp_dir_fd, prefix_dir_fd
                finally:
                    os.close(sha_dir_fd)
            except BaseException:
                os.close(tmp_dir_fd)
                raise
        except BaseException:
            os.close(root_fd)
            raise

    def blob_path(self, digest: str) -> Path:
        """Return the calculated path for a digest, checking containment."""
        _validate_digest(digest)
        _check_ancestors_no_symlinks(self._root)

        target = self._root / "sha256" / digest[:2] / digest
        curr = self._root
        for comp in ("sha256", digest[:2], digest):
            curr = curr / comp
            curr_str = str(curr)
            if os.path.islink(curr_str):
                raise CasContainmentError(
                    f"Component {comp!r} is a symlink",
                    path=curr_str[:128],
                    root=str(self._root)[:128],
                )
            if not curr.exists(follow_symlinks=False):
                break
        return target

    def has(self, digest: str) -> bool:
        """Check whether a valid blob exists for the given digest (cheap existence check)."""
        _validate_digest(digest)
        self._check_platform()
        _check_ancestors_no_symlinks(self._root)

        root_str = str(self._root)
        if not self._root.exists(follow_symlinks=False):
            return False
        if not self._root.is_dir():
            raise CasCorruptionError(
                "CAS root is not a directory", details={"root": root_str[:128]}
            )

        rel = f"sha256/{digest[:2]}/{digest}"
        nonblock = getattr(os, "O_NONBLOCK", 0)
        try:
            fd = open_safe_path_fd(root_str, rel, flags=os.O_RDONLY | nonblock)
        except FileNotFoundError:
            return False
        except SymlinkEscapeError as exc:
            raise CasContainmentError(
                f"Symlink in blob path: {exc}", path=rel[:128], root=root_str[:128]
            ) from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasContainmentError(
                    f"Symlink in blob path: {exc}", path=rel[:128], root=root_str[:128]
                ) from exc
            raise CasError(f"Failed checking blob (errno={exc.errno})") from exc

        try:
            st = os.fstat(fd)
            return stat.S_ISREG(st.st_mode)
        finally:
            os.close(fd)

    def open_blob(self, digest: str) -> BinaryIO:
        """Open and verify the integrity of a stored blob, returning a readable handle."""
        _validate_digest(digest)
        self._check_platform()
        _check_ancestors_no_symlinks(self._root)

        root_str = str(self._root)
        if not self._root.exists(follow_symlinks=False):
            raise CasBlobNotFoundError("CAS root does not exist", digest=digest[:128])
        if not self._root.is_dir():
            raise CasCorruptionError(
                "CAS root is not a directory", details={"root": root_str[:128]}
            )

        rel = f"sha256/{digest[:2]}/{digest}"
        nonblock = getattr(os, "O_NONBLOCK", 0)
        try:
            fd = open_safe_path_fd(root_str, rel, flags=os.O_RDONLY | nonblock)
        except FileNotFoundError as exc:
            raise CasBlobNotFoundError("Blob not found", digest=digest[:128]) from exc
        except SymlinkEscapeError as exc:
            raise CasContainmentError(
                f"Symlink in blob path: {exc}", path=rel[:128], root=root_str[:128]
            ) from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasContainmentError(
                    f"Symlink in blob path: {exc}", path=rel[:128], root=root_str[:128]
                ) from exc
            raise CasError(f"Failed opening blob (errno={exc.errno})") from exc

        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise CasCorruptionError("Blob is not a regular file", digest=digest[:128])

            h = hashlib.sha256()
            while True:
                try:
                    chunk = os.read(fd, _CHUNK_SIZE)
                except OSError as exc:
                    raise CasError(f"Failed reading blob (errno={exc.errno})") from exc
                if not chunk:
                    break
                h.update(chunk)

            if h.hexdigest() != digest:
                raise CasCorruptionError("CAS blob hash mismatch", digest=digest[:128])

            try:
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError as exc:
                raise CasError(f"Failed seeking blob (errno={exc.errno})") from exc
            return os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise

    def _quarantine_corrupt_blob(self, root_fd: int, prefix_dir_fd: int, digest: str) -> None:
        """Move a corrupt blob into quarantine."""
        q_root_fd = self._ensure_subdir_fd(root_fd, "quarantine")
        try:
            q_sha_fd = self._ensure_subdir_fd(q_root_fd, "sha256")
            try:
                q_prefix_fd = self._ensure_subdir_fd(q_sha_fd, digest[:2])
                try:
                    now = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
                    q_name = f"{digest}.{now}-{uuid.uuid4().hex}"
                    try:
                        os.replace(
                            digest, q_name, src_dir_fd=prefix_dir_fd, dst_dir_fd=q_prefix_fd
                        )
                    except OSError as exc:
                        raise CasWriteError(
                            f"Failed quarantining corrupt blob (errno={exc.errno})"
                        ) from exc
                    # Tighten quarantine file mode to 0400
                    with contextlib.suppress(OSError):
                        q_file_fd = os.open(
                            q_name,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=q_prefix_fd,
                        )
                        try:
                            os.fchmod(q_file_fd, 0o400)
                        finally:
                            os.close(q_file_fd)
                    try:
                        os.fsync(q_prefix_fd)
                    except OSError as exc:
                        raise CasWriteError(
                            f"Failed fsyncing quarantine directory (errno={exc.errno})"
                        ) from exc
                finally:
                    os.close(q_prefix_fd)
            finally:
                os.close(q_sha_fd)
        finally:
            os.close(q_root_fd)

    def _check_and_dedupe_existing(
        self, root_fd: int, prefix_dir_fd: int, digest: str
    ) -> bool:
        """Check if blob exists. If valid, return True. If corrupt, quarantine and return False."""
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(digest, os.O_RDONLY | nofollow | nonblock, dir_fd=prefix_dir_fd)
        except FileNotFoundError:
            return False
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasContainmentError(
                    "Blob is a symlink", path=digest[:128], root=str(self._root)[:128]
                ) from exc
            raise CasError(f"Failed opening existing blob (errno={exc.errno})") from exc

        try:
            try:
                st = os.fstat(fd)
            except OSError as exc:
                raise CasError(f"Failed stating existing blob (errno={exc.errno})") from exc

            if not stat.S_ISREG(st.st_mode):
                raise CasCorruptionError(
                    "Blob exists but is not a regular file", digest=digest[:128]
                )

            h = hashlib.sha256()
            while True:
                try:
                    chunk = os.read(fd, _CHUNK_SIZE)
                except OSError as exc:
                    raise CasError(f"Failed reading existing blob (errno={exc.errno})") from exc
                if not chunk:
                    break
                h.update(chunk)

            if h.hexdigest() == digest:
                # Valid existing blob! Tighten mode if needed.
                if stat.S_IMODE(st.st_mode) != 0o400:
                    with contextlib.suppress(OSError):
                        os.fchmod(fd, 0o400)
                return True
        finally:
            os.close(fd)

        # Hash mismatch: quarantine
        self._quarantine_corrupt_blob(root_fd, prefix_dir_fd, digest)
        return False

    def put_bytes(self, data: bytes | bytearray) -> str:
        """Store bytes into the CAS atomically, returning the SHA-256 digest."""
        if not isinstance(data, (bytes, bytearray)):
            raise CasWriteError("data must be bytes")
        data = bytes(data)
        self._check_platform()

        digest = hashlib.sha256(data).hexdigest()
        root_fd, tmp_dir_fd, prefix_dir_fd = self._ensure_layout_fds(digest)
        try:
            if self._check_and_dedupe_existing(root_fd, prefix_dir_fd, digest):
                return digest

            temp_name = f"{uuid.uuid4().hex}.part"
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            try:
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=tmp_dir_fd,
                )
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise InsufficientStorageError(
                        "No space left on device while creating CAS temp file"
                    ) from exc
                raise CasWriteError(f"Failed creating temp file (errno={exc.errno})") from exc

            committed = False
            try:
                try:
                    os.fchmod(temp_fd, 0o600)
                    offset = 0
                    total = len(data)
                    while offset < total:
                        chunk = data[offset : offset + _CHUNK_SIZE]
                        chunk_offset = 0
                        while chunk_offset < len(chunk):
                            written = os.write(temp_fd, chunk[chunk_offset:])
                            if written <= 0:
                                raise CasWriteError("os.write returned 0 bytes")
                            chunk_offset += written
                        offset += len(chunk)

                    os.fsync(temp_fd)
                    os.fchmod(temp_fd, 0o400)
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise InsufficientStorageError(
                            "No space left on device while writing CAS blob"
                        ) from exc
                    raise CasWriteError(
                        f"Failed writing temp CAS file (errno={exc.errno})"
                    ) from exc
                finally:
                    os.close(temp_fd)

                try:
                    os.replace(
                        temp_name,
                        digest,
                        src_dir_fd=tmp_dir_fd,
                        dst_dir_fd=prefix_dir_fd,
                    )
                    os.fsync(prefix_dir_fd)
                    committed = True
                except OSError as exc:
                    raise CasWriteError(f"Failed committing CAS blob (errno={exc.errno})") from exc

                return digest
            finally:
                if not committed:
                    with contextlib.suppress(OSError):
                        os.unlink(temp_name, dir_fd=tmp_dir_fd)
        finally:
            os.close(prefix_dir_fd)
            os.close(tmp_dir_fd)
            os.close(root_fd)

    def put_file(self, path: str | Path) -> str:
        """Stream a regular file into the CAS atomically, returning the SHA-256 digest.

        Only the final source component is O_NOFOLLOW; intermediate source-directory
        symlinks are allowed because the source is caller-supplied and content is
        verified by double hashing.
        """
        self._check_platform()
        src_path = Path(path)
        src_str = str(src_path)

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        try:
            src_fd = os.open(src_str, os.O_RDONLY | nofollow | nonblock)
        except FileNotFoundError as exc:
            raise CasInvalidSourceError(
                f"Source file does not exist: {src_str[:128]}", path=src_str[:128]
            ) from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise CasInvalidSourceError(
                    f"Source file cannot be a symlink: {src_str[:128]}", path=src_str[:128]
                ) from exc
            raise CasInvalidSourceError(
                f"Failed opening source file (errno={exc.errno})", path=src_str[:128]
            ) from exc

        try:
            try:
                st = os.fstat(src_fd)
            except OSError as exc:
                raise CasInvalidSourceError(
                    f"Failed stating source file (errno={exc.errno})", path=src_str[:128]
                ) from exc

            if not stat.S_ISREG(st.st_mode):
                raise CasInvalidSourceError(
                    f"Source must be a regular file: {src_str[:128]}", path=src_str[:128]
                )

            # First pass: hash the source fd
            h1 = hashlib.sha256()
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK_SIZE)
                except OSError as exc:
                    raise CasWriteError(
                        f"Failed reading source file (errno={exc.errno})"
                    ) from exc
                if not chunk:
                    break
                h1.update(chunk)
            digest = h1.hexdigest()

            root_fd, tmp_dir_fd, prefix_dir_fd = self._ensure_layout_fds(digest)
            try:
                if self._check_and_dedupe_existing(root_fd, prefix_dir_fd, digest):
                    return digest

                try:
                    os.lseek(src_fd, 0, os.SEEK_SET)
                except OSError as exc:
                    raise CasWriteError(
                        f"Failed seeking source file (errno={exc.errno})"
                    ) from exc

                temp_name = f"{uuid.uuid4().hex}.part"
                try:
                    temp_fd = os.open(
                        temp_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                        0o600,
                        dir_fd=tmp_dir_fd,
                    )
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise InsufficientStorageError(
                            "No space left on device while creating CAS temp file"
                        ) from exc
                    raise CasWriteError(f"Failed creating temp file (errno={exc.errno})") from exc

                committed = False
                try:
                    try:
                        os.fchmod(temp_fd, 0o600)
                        h2 = hashlib.sha256()
                        while True:
                            try:
                                chunk = os.read(src_fd, _CHUNK_SIZE)
                            except OSError as exc:
                                raise CasWriteError(
                                    f"Failed reading source file (errno={exc.errno})"
                                ) from exc
                            if not chunk:
                                break
                            h2.update(chunk)
                            chunk_offset = 0
                            while chunk_offset < len(chunk):
                                written = os.write(temp_fd, chunk[chunk_offset:])
                                if written <= 0:
                                    raise CasWriteError("os.write returned 0 bytes")
                                chunk_offset += written

                        if h2.hexdigest() != digest:
                            raise CasWriteError("Source file mutated or truncated during copy")

                        os.fsync(temp_fd)
                        os.fchmod(temp_fd, 0o400)
                    except OSError as exc:
                        if exc.errno == errno.ENOSPC:
                            raise InsufficientStorageError(
                                "No space left on device while writing CAS blob"
                            ) from exc
                        raise CasWriteError(
                            f"Failed streaming file into CAS (errno={exc.errno})"
                        ) from exc
                    finally:
                        os.close(temp_fd)

                    try:
                        os.replace(
                            temp_name,
                            digest,
                            src_dir_fd=tmp_dir_fd,
                            dst_dir_fd=prefix_dir_fd,
                        )
                        os.fsync(prefix_dir_fd)
                        committed = True
                    except OSError as exc:
                        raise CasWriteError(
                            f"Failed committing CAS blob (errno={exc.errno})"
                        ) from exc

                    return digest
                finally:
                    if not committed:
                        with contextlib.suppress(OSError):
                            os.unlink(temp_name, dir_fd=tmp_dir_fd)
            finally:
                os.close(prefix_dir_fd)
                os.close(tmp_dir_fd)
                os.close(root_fd)
        finally:
            os.close(src_fd)

    def cleanup_stale_temp(self, max_age_seconds: float = 86400.0) -> int:
        """Remove .part files in <root>/.tmp older than max_age_seconds."""
        self._check_platform()
        if not self._root.exists(follow_symlinks=False):
            return 0

        _check_ancestors_no_symlinks(self._root)
        root_str = str(self._root)
        if not self._root.is_dir():
            raise CasCorruptionError(
                "CAS root is not a directory", details={"root": root_str[:128]}
            )

        root_fd = self._open_root_fd(create=False)
        try:
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            try:
                tmp_fd = os.open(
                    ".tmp",
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow,
                    dir_fd=root_fd,
                )
            except FileNotFoundError:
                return 0
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise CasContainmentError(
                        "Temp directory .tmp is a symlink or not a directory",
                        path=".tmp",
                        root=root_str[:128],
                    ) from exc
                raise CasError(f"Failed opening .tmp directory (errno={exc.errno})") from exc

            try:
                now = time.time()
                cleaned = 0
                with os.scandir(tmp_fd) as it:
                    for entry in it:
                        if not entry.name.endswith(".part"):
                            continue
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except (FileNotFoundError, OSError):
                            continue

                        if now - st.st_mtime >= max_age_seconds:
                            with contextlib.suppress(OSError):
                                os.unlink(entry.name, dir_fd=tmp_fd)
                                cleaned += 1
                return cleaned
            finally:
                os.close(tmp_fd)
        finally:
            os.close(root_fd)
