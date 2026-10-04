from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.core.process_utils import (
    PROCESS_QUERY_LIMITED_INFORMATION,
    STILL_ACTIVE,
    _windows_pid_alive,
    platform_pid_alive,
)


class TestPlatformPidAlivePosix:
    @pytest.mark.allow_real_signals
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX live os.kill(pid, 0) triggers CTRL_C_EVENT on Windows",
    )
    def test_live_process_current_pid(self) -> None:
        """Test runner's own PID is alive on POSIX."""
        current_pid = os.getpid()
        with patch("sys.platform", "linux"):
            assert platform_pid_alive(current_pid) is True

    @pytest.mark.allow_real_signals
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX live os.kill(pid, 0) triggers CTRL_C_EVENT on Windows",
    )
    def test_dead_process_nonexistent_pid(self) -> None:
        """Non-existent PID returns False on POSIX."""
        dead_pid = 4194304  # Max pid on Linux is usually <= 4194304
        with patch("sys.platform", "linux"):
            assert platform_pid_alive(dead_pid) is False

    def test_non_positive_pids_return_false(self) -> None:
        """PIDs <= 0 return False immediately without signaling."""
        assert platform_pid_alive(0) is False
        assert platform_pid_alive(-1) is False
        assert platform_pid_alive(-999) is False

    @patch("app.core.process_utils.os.kill")
    def test_posix_os_error_handling(self, mock_kill: MagicMock) -> None:
        """OSError from os.kill returns False."""
        mock_kill.side_effect = OSError("Operation not permitted")
        with patch("sys.platform", "linux"):
            assert platform_pid_alive(12345) is False

    @patch("app.core.process_utils.os.kill")
    def test_posix_process_lookup_error(self, mock_kill: MagicMock) -> None:
        """ProcessLookupError returns False."""
        mock_kill.side_effect = ProcessLookupError("No such process")
        with patch("sys.platform", "linux"):
            assert platform_pid_alive(12345) is False

    @patch("app.core.process_utils.os.kill")
    def test_posix_success(self, mock_kill: MagicMock) -> None:
        """Successful os.kill(pid, 0) returns True."""
        mock_kill.return_value = None
        with patch("sys.platform", "linux"):
            assert platform_pid_alive(12345) is True
        mock_kill.assert_called_once_with(12345, 0)


class TestPlatformPidAliveWindows:
    def test_windows_constants(self) -> None:
        """Verify Windows constants match Win32 API values."""
        assert PROCESS_QUERY_LIMITED_INFORMATION == 0x1000
        assert STILL_ACTIVE == 259

    def test_windows_alive_process(self) -> None:
        """Windows process with exit code STILL_ACTIVE (259) returns True."""
        mock_kernel32 = MagicMock()
        mock_handle = 0x1234
        mock_kernel32.OpenProcess.return_value = mock_handle
        mock_kernel32.GetExitCodeProcess.return_value = True

        mock_wintypes = MagicMock()
        mock_dword = MagicMock()
        mock_dword.value = STILL_ACTIVE
        mock_wintypes.DWORD.return_value = mock_dword

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32
        mock_ctypes.wintypes = mock_wintypes

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes, "ctypes.wintypes": mock_wintypes}),
            patch("sys.platform", "win32"),
        ):
            result = platform_pid_alive(12345)

        assert result is True
        mock_kernel32.OpenProcess.assert_called_once_with(
            PROCESS_QUERY_LIMITED_INFORMATION, False, 12345
        )
        mock_kernel32.CloseHandle.assert_called_once_with(mock_handle)

    def test_windows_dead_process_exit_code(self) -> None:
        """Windows process with exit code other than STILL_ACTIVE returns False."""
        mock_kernel32 = MagicMock()
        mock_handle = 0x1234
        mock_kernel32.OpenProcess.return_value = mock_handle
        mock_kernel32.GetExitCodeProcess.return_value = True

        mock_wintypes = MagicMock()
        mock_dword = MagicMock()
        mock_dword.value = 0  # Process terminated with exit code 0
        mock_wintypes.DWORD.return_value = mock_dword

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32
        mock_ctypes.wintypes = mock_wintypes

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes, "ctypes.wintypes": mock_wintypes}),
            patch("sys.platform", "win32"),
        ):
            result = platform_pid_alive(12345)

        assert result is False
        mock_kernel32.CloseHandle.assert_called_once_with(mock_handle)

    def test_windows_open_process_failed(self) -> None:
        """Windows OpenProcess returning 0/NULL returns False."""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = 0  # NULL handle

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}),
            patch("sys.platform", "win32"),
        ):
            result = platform_pid_alive(12345)

        assert result is False
        mock_kernel32.OpenProcess.assert_called_once_with(
            PROCESS_QUERY_LIMITED_INFORMATION, False, 12345
        )
        mock_kernel32.GetExitCodeProcess.assert_not_called()
        mock_kernel32.CloseHandle.assert_not_called()

    def test_windows_get_exit_code_failed(self) -> None:
        """Windows GetExitCodeProcess returning False returns False and closes handle."""
        mock_kernel32 = MagicMock()
        mock_handle = 0x1234
        mock_kernel32.OpenProcess.return_value = mock_handle
        mock_kernel32.GetExitCodeProcess.return_value = False

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}),
            patch("sys.platform", "win32"),
        ):
            result = platform_pid_alive(12345)

        assert result is False
        mock_kernel32.CloseHandle.assert_called_once_with(mock_handle)

    def test_windows_exception_fallback(self) -> None:
        """Any exception (ctypes missing, permission error) returns False, does not raise."""
        with patch.dict("sys.modules", {"ctypes": None}), patch("sys.platform", "win32"):
            result = platform_pid_alive(12345)
        assert result is False

    def test_windows_direct_function_exception(self) -> None:
        """Direct call to _windows_pid_alive with error returns False."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.OpenProcess.side_effect = RuntimeError("Kernel failure")

        with patch.dict("sys.modules", {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}):
            assert _windows_pid_alive(12345) is False

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows live process liveness test requires Windows",
    )
    def test_windows_live_process_current_pid(self) -> None:
        """Test runner's own PID is alive on real Windows."""
        current_pid = os.getpid()
        assert platform_pid_alive(current_pid) is True

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows live process liveness test requires Windows",
    )
    def test_windows_dead_process_nonexistent_pid(self) -> None:
        """Non-existent PID returns False on real Windows."""
        dead_pid = 4194304
        assert platform_pid_alive(dead_pid) is False


class TestPlatformKillProcessTreeSafety:
    def test_kill_process_tree_skips_when_create_time_mismatches(self) -> None:
        """ISS-005: When target PID create_time mismatches expected, kill must be skipped."""
        from app.core.process_utils import platform_kill_process_tree_sync

        mock_target_proc = MagicMock()
        mock_target_proc.create_time.return_value = 200.0  # Reused PID with new create_time

        with (
            patch("os.getpid", return_value=1),
            patch("psutil.Process", return_value=mock_target_proc),
            patch("os.killpg", create=True) as mock_killpg,
            patch("subprocess.run") as mock_run,
        ):
            platform_kill_process_tree_sync(pid=5555, expected_create_time=100.0)

        mock_killpg.assert_not_called()
        mock_run.assert_not_called()

    def test_kill_process_tree_refuses_to_kill_self(self) -> None:
        """ISS-005: Target PID matching os.getpid() must never be killed."""
        from app.core.process_utils import platform_kill_process_tree_sync

        current_pid = os.getpid()
        with (
            patch("os.killpg", create=True) as mock_killpg,
            patch("subprocess.run") as mock_run,
        ):
            platform_kill_process_tree_sync(pid=current_pid)

        mock_killpg.assert_not_called()
        mock_run.assert_not_called()

    def test_kill_process_tree_refuses_to_kill_ancestor(self) -> None:
        """ISS-005: Target PID matching an ancestor process must never be killed."""
        from app.core.process_utils import platform_kill_process_tree_sync

        mock_parent = MagicMock()
        mock_parent.pid = 999

        mock_current_proc = MagicMock()
        mock_current_proc.parents.return_value = [mock_parent]

        def proc_factory(pid: int):
            if pid == os.getpid():
                return mock_current_proc
            m = MagicMock()
            m.pid = pid
            return m

        with (
            patch("psutil.Process", side_effect=proc_factory),
            patch("os.killpg", create=True) as mock_killpg,
            patch("subprocess.run") as mock_run,
        ):
            platform_kill_process_tree_sync(pid=999)

        mock_killpg.assert_not_called()
        mock_run.assert_not_called()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX process groups (getpgid/getpgrp) and SIGKILL are not supported on Windows",
    )
    def test_kill_process_tree_same_pgrp_avoids_killpg(self) -> None:
        """ISS-005: When target shares backend pgrp, os.killpg is bypassed to protect backend."""
        from app.core.process_utils import platform_kill_process_tree_sync

        mock_target = MagicMock()
        mock_target.create_time.return_value = 100.0
        mock_target.children.return_value = []

        with (
            patch("sys.platform", "linux"),
            patch("os.getpid", return_value=100),
            patch("os.getpgrp", return_value=500),
            patch("os.getpgid", return_value=500),  # Target shares pgrp with backend
            patch("os.kill") as mock_os_kill,
            patch("os.killpg", create=True) as mock_killpg,
            patch("psutil.Process", return_value=mock_target),
        ):
            platform_kill_process_tree_sync(pid=501)

        mock_killpg.assert_not_called()
        mock_os_kill.assert_called_once_with(501, pytest.importorskip("signal").SIGKILL)

