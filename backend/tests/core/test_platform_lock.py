from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.platform_lock import (
    FileLock,
    lock_file_nonblocking,
    set_cloexec_on_all_fds,
    unlock_file,
)


class TestSetCloexecOnAllFds:
    def test_non_posix_does_nothing(self) -> None:
        with patch("os.name", "nt"), patch("os.listdir") as mock_listdir:
            set_cloexec_on_all_fds()
            mock_listdir.assert_not_called()

    def test_posix_sets_cloexec(self) -> None:
        mock_fcntl = MagicMock()
        mock_fcntl.fcntl.return_value = 0
        with patch("os.name", "posix"):
            with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
                with patch("os.listdir", return_value=["0", "1", "2", "3", "invalid"]):
                    set_cloexec_on_all_fds()
                    # Only fd=3 (>2) should have fcntl called
                    assert mock_fcntl.fcntl.call_count >= 2


class TestPlatformLockDispatch:
    def test_lock_posix(self) -> None:
        mock_fcntl = MagicMock()
        mock_fcntl.LOCK_EX = 1
        mock_fcntl.LOCK_NB = 2
        with patch("sys.platform", "linux"):
            with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
                lock_file_nonblocking(10)
                mock_fcntl.flock.assert_called_once_with(10, 1 | 2)

    def test_lock_windows(self) -> None:
        mock_msvcrt = MagicMock()
        mock_msvcrt.LK_NBLCK = 1
        with patch("sys.platform", "win32"):
            with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
                with patch("os.lseek") as mock_lseek:
                    lock_file_nonblocking(10)
                    mock_lseek.assert_called_once_with(10, 0, os.SEEK_SET)
                    mock_msvcrt.locking.assert_called_once_with(10, 1, 1)

    def test_unlock_posix(self) -> None:
        mock_fcntl = MagicMock()
        mock_fcntl.LOCK_UN = 8
        with patch("sys.platform", "linux"):
            with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
                unlock_file(10)
                mock_fcntl.flock.assert_called_once_with(10, 8)

    def test_unlock_windows(self) -> None:
        mock_msvcrt = MagicMock()
        mock_msvcrt.LK_UNLCK = 2
        with patch("sys.platform", "win32"):
            with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
                with patch("os.lseek") as mock_lseek:
                    unlock_file(10)
                    mock_lseek.assert_called_once_with(10, 0, os.SEEK_SET)
                    mock_msvcrt.locking.assert_called_once_with(10, 2, 1)

    def test_unlock_suppresses_os_error(self) -> None:
        mock_fcntl = MagicMock()
        mock_fcntl.flock.side_effect = OSError("Bad file descriptor")
        with patch("sys.platform", "linux"):
            with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
                # Should not raise
                unlock_file(999)


class TestFileLock:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test.lock"
        lock = FileLock(lock_file)

        assert lock.acquire(timeout=0.5) is True
        assert lock._fd is not None

        lock.release()
        assert lock._fd is None

    def test_mutual_exclusion(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "shared.lock"
        lock1 = FileLock(lock_file)
        lock2 = FileLock(lock_file)

        assert lock1.acquire(timeout=0.5) is True
        # Second acquire should fail due to contention
        assert lock2.acquire(timeout=0.1) is False

        lock1.release()
        # After releasing, second lock can acquire
        assert lock2.acquire(timeout=0.5) is True
        lock2.release()

    def test_context_manager(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "ctx.lock"
        lock = FileLock(lock_file)

        with lock as acquired:
            assert acquired is True
            assert lock._fd is not None

        assert lock._fd is None

    def test_acquire_windows_simulation(self, tmp_path: Path) -> None:
        mock_msvcrt = MagicMock()
        mock_msvcrt.LK_NBLCK = 1
        mock_msvcrt.LK_UNLCK = 2

        lock_file = tmp_path / "win.lock"
        lock = FileLock(lock_file)

        with patch("sys.platform", "win32"):
            with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
                assert lock.acquire(timeout=0.2) is True
                assert lock._fd is not None
                mock_msvcrt.locking.assert_called_with(lock._fd, 1, 1)

                lock.release()
                assert lock._fd is None
                mock_msvcrt.locking.assert_called_with(
                    pytest.approx(mock_msvcrt.locking.call_args[0][0]), 2, 1
                )

    def test_acquire_timeout_cleanup(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "timeout.lock"
        lock = FileLock(lock_file)

        with patch(
            "app.core.platform_lock.lock_file_nonblocking", side_effect=OSError("Resource locked")
        ):
            assert lock.acquire(timeout=0.05) is False
            assert lock._fd is None
