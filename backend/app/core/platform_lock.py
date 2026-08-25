from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcs.core.platform_lock")


def set_cloexec_on_all_fds() -> None:
    """Set FD_CLOEXEC on all file descriptors >= 3 on POSIX to prevent socket leakage into children."""
    if os.name != "posix":
        return
    try:
        import fcntl

        for fd_str in os.listdir("/proc/self/fd"):
            try:
                fd = int(fd_str)
                if fd > 2:
                    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
                    fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
            except (ValueError, OSError):
                pass
    except (OSError, ImportError):
        pass


def lock_file_nonblocking(fd: int) -> None:
    """Acquire an exclusive, non-blocking lock on an open file descriptor.

    On POSIX systems, uses ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.
    On Windows systems, uses ``msvcrt.locking(fd, LK_NBLCK, 1)``.

    Raises:
        OSError: If the lock cannot be acquired or the file is already locked by another process.
    """
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_file(fd: int) -> None:
    """Release a previously acquired exclusive lock on an open file descriptor.

    On POSIX systems, uses ``fcntl.flock(fd, LOCK_UN)``.
    On Windows systems, uses ``msvcrt.locking(fd, LK_UNLCK, 1)``.
    """
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)


class FileLock:
    """Cross-process mutual exclusion file lock supporting POSIX (fcntl.flock) and Windows (msvcrt.locking)."""

    def __init__(self, lock_path: Path | str) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    def acquire(self, timeout: float = 2.0) -> bool:
        """Attempt to acquire an exclusive non-blocking lock within the given timeout.

        Returns True if acquired successfully, False on timeout or error.
        """
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            start = time.monotonic()
            while True:
                try:
                    lock_file_nonblocking(self._fd)
                    return True
                except (BlockingIOError, OSError, PermissionError):
                    if time.monotonic() - start > timeout:
                        self._cleanup_fd()
                        return False
                    time.sleep(0.05)
        except Exception as exc:
            logger.warning("Failed to acquire file lock %s: %s", self.lock_path, exc)
            self._cleanup_fd()
            return False

    def release(self) -> None:
        """Release the acquired file lock and close the underlying file descriptor."""
        if self._fd is None:
            return
        try:
            unlock_file(self._fd)
        finally:
            self._cleanup_fd()

    def _cleanup_fd(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
