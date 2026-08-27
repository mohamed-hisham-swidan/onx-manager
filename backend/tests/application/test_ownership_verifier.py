from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.modules.server.application.ownership_verifier import (
    OwnershipStatus,
    _get_process_cwd,
    _get_process_env,
    _get_process_start_time,
    _is_pid_alive,
    verify_ownership,
)


class TestGetProcessEnv:
    @patch("builtins.open", new_callable=MagicMock)
    def test_reads_env(self, mock_open):
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = (
            b"HOME=/root\x00PATH=/usr/bin\x00MCS_MANAGED=1\x00"
        )
        mock_open.return_value = mock_file
        env = _get_process_env(12345)
        assert env["HOME"] == "/root"
        assert env["MCS_MANAGED"] == "1"

    @patch("builtins.open", side_effect=OSError)
    def test_error_returns_empty(self, mock_open):
        assert _get_process_env(99999) == {}


class TestGetProcessCwd:
    @patch("os.readlink", return_value="/data/servers/my-server")
    def test_reads_cwd(self, mock_readlink):
        assert _get_process_cwd(12345) == "/data/servers/my-server"

    @patch("os.readlink", side_effect=OSError)
    def test_error_returns_none(self, mock_readlink):
        assert _get_process_cwd(99999) is None


class TestGetProcessStartTime:
    FAKE_STAT = (
        "12345 (java) S 1 100 200 34816 "
        "0 0 0 0 0 5000 6000 7000 8000 9000 10000 11000 12000 13000 14000 15000 16000"
    )

    @patch("builtins.open", new_callable=MagicMock)
    def test_reads_start_time(self, mock_open):
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = self.FAKE_STAT
        mock_open.return_value = mock_file
        result = _get_process_start_time(12345)
        assert result == 14000

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_not_found(self, mock_open):
        assert _get_process_start_time(99999) is None


class TestIsPidAlive:
    @patch("app.modules.server.application.ownership_verifier.os.kill")
    def test_alive(self, mock_kill):
        assert _is_pid_alive(100) is True

    @patch("app.modules.server.application.ownership_verifier.os.kill", side_effect=OSError)
    def test_dead(self, mock_kill):
        assert _is_pid_alive(100) is False


class TestVerifyOwnership:
    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    @patch("app.modules.server.application.ownership_verifier._get_process_start_time")
    def test_verified_by_marker(
        self,
        mock_start_time,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {"MCS_MANAGED": "1"}
        mock_cwd.return_value = "/some/other/dir"
        mock_start_time.return_value = 12345

        result = verify_ownership(100)
        assert result.status == OwnershipStatus.VERIFIED
        assert result.has_marker is True
        assert result.cwd_matches is False

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    @patch("app.modules.server.application.ownership_verifier._get_process_start_time")
    def test_verified_by_cwd(
        self,
        mock_start_time,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {}
        mock_cwd.return_value = "/data/servers/my-server"
        mock_start_time.return_value = 12345

        result = verify_ownership(100, servers_data_dir="/data/servers")
        assert result.status == OwnershipStatus.VERIFIED
        assert result.has_marker is False
        assert result.cwd_matches is True

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    def test_unknown_no_marker_no_cwd_match(
        self,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {}
        mock_cwd.return_value = "/opt/custom/server"

        result = verify_ownership(100, servers_data_dir="/data/servers")
        assert result.status == OwnershipStatus.UNKNOWN
        assert result.has_marker is False
        assert result.cwd_matches is False

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    def test_unknown_no_cwd(
        self,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {}
        mock_cwd.return_value = None

        result = verify_ownership(100)
        assert result.status == OwnershipStatus.UNKNOWN
        assert result.cwd is None

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=False)
    def test_not_found(self, mock_alive):
        result = verify_ownership(99999)
        assert result.status == OwnershipStatus.NOT_FOUND

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    @patch("app.modules.server.application.ownership_verifier._get_process_start_time")
    def test_rejects_recycled_pid_via_start_time(
        self,
        mock_start_time,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {"MCS_MANAGED": "1"}
        mock_cwd.return_value = "/data/servers/my-server"
        mock_start_time.return_value = 99999

        result = verify_ownership(
            100,
            servers_data_dir="/data/servers",
            stored_start_time=50000,
        )
        assert result.status == OwnershipStatus.NOT_OWNED
        assert "start_time mismatch" in result.detail
        assert result.start_time == 99999

    @patch("app.modules.server.application.ownership_verifier._is_pid_alive", return_value=True)
    @patch("app.modules.server.application.ownership_verifier._get_process_env")
    @patch("app.modules.server.application.ownership_verifier._get_process_cwd")
    @patch("app.modules.server.application.ownership_verifier._get_process_start_time")
    def test_accepts_matching_start_time(
        self,
        mock_start_time,
        mock_cwd,
        mock_env,
        mock_alive,
    ):
        mock_env.return_value = {"MCS_MANAGED": "1"}
        mock_cwd.return_value = "/data/servers/my-server"
        mock_start_time.return_value = 50000

        result = verify_ownership(
            100,
            servers_data_dir="/data/servers",
            stored_start_time=50000,
        )
        assert result.status == OwnershipStatus.VERIFIED
