from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.core.process_utils import (
    ProcessIdentityCheck,
    verify_process_identity,
)
from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.local import LocalLinuxProvider
from app.modules.server.infrastructure.providers.local_windows import LocalWindowsProvider
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _create_test_server(server_id: str, port: int = 25565) -> Server:
    return Server.create(
        server_id=ServerId(server_id),
        name=f"Server-{server_id}",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(port)),
    )


class TestWindowsProviderPidResolution:
    @pytest.mark.asyncio
    async def test_get_runtime_pid_from_metadata_when_external_id_non_numeric(self):
        provider = LocalWindowsProvider()
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-win-1",
            external_id="onx-srv-win-1",
            metadata={"pid": 12345, "start_time": 1700000000},
        )
        pid = await provider.get_runtime_pid(handle)
        assert pid == 12345

    @pytest.mark.asyncio
    async def test_get_runtime_pid_falls_back_to_external_id_when_numeric(self):
        provider = LocalWindowsProvider()
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-win-2",
            external_id="54321",
            metadata={},
        )
        pid = await provider.get_runtime_pid(handle)
        assert pid == 54321

    @pytest.mark.asyncio
    async def test_stop_raises_provider_error_when_pid_is_none(self):
        provider = LocalWindowsProvider()
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-win-no-pid",
            external_id="onx-srv-win-no-pid",
            metadata={"pid": None},
        )
        with pytest.raises(ProviderError) as exc_info:
            await provider.stop(handle)
        assert "missing runtime PID in handle" in str(exc_info.value)


class TestVerifyProcessIdentity:
    def test_verify_process_identity_rejects_non_positive_pid(self):
        check = verify_process_identity(0)
        assert check.verified is False
        assert check.reason == "no_such_process"

        check_neg = verify_process_identity(-10)
        assert check_neg.verified is False
        assert check_neg.reason == "no_such_process"

    def test_verify_process_identity_fails_on_create_time_mismatch(self):
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 1700000500.0  # 500s later (PID reuse)

        with patch("psutil.Process", return_value=mock_proc):
            check = verify_process_identity(
                pid=1234,
                expected_create_time=1700000000.0,
                create_time_tolerance_seconds=5.0,
            )
            assert check.verified is False
            assert check.reason == "create_time_mismatch"
            assert check.create_time == 1700000500.0

    def test_verify_process_identity_fails_on_cmdline_mismatch(self):
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 1700000000.0
        mock_proc.cmdline.return_value = ["python", "-m", "http.server", "8000"]
        mock_proc.cwd.return_value = "/data/servers/srv-1"
        mock_proc.environ.return_value = {}

        with patch("psutil.Process", return_value=mock_proc):
            check = verify_process_identity(
                pid=1234,
                expected_create_time=1700000000.0,
                expected_server_dir="/data/servers/srv-1",
            )
            assert check.verified is False
            assert check.reason == "cmdline_mismatch"
            assert check.cmdline == ("python", "-m", "http.server", "8000")

    def test_verify_process_identity_fails_on_server_dir_mismatch(self):
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 1700000000.0
        mock_proc.cmdline.return_value = ["java", "-Xmx2G", "-jar", "paper.jar", "nogui"]
        mock_proc.cwd.return_value = "/data/servers/other-server"
        mock_proc.environ.return_value = {}

        with patch("psutil.Process", return_value=mock_proc):
            check = verify_process_identity(
                pid=1234,
                expected_create_time=1700000000.0,
                expected_server_dir="/data/servers/target-server",
            )
            assert check.verified is False
            assert check.reason == "server_dir_mismatch"

    def test_verify_process_identity_succeeds_when_all_match(self, tmp_path):
        server_dir = tmp_path / "target-server"
        server_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 1700000001.0
        mock_proc.cmdline.return_value = ["java", "-Xmx2G", "-jar", "server.jar", "nogui"]
        mock_proc.cwd.return_value = str(server_dir)
        mock_proc.environ.return_value = {"ONX_MANAGED": "1"}

        with patch("psutil.Process", return_value=mock_proc):
            check = verify_process_identity(
                pid=1234,
                expected_create_time=1700000000.0,
                expected_server_dir=server_dir,
                create_time_tolerance_seconds=5.0,
            )
            assert check.verified is True
            assert check.reason == "verified"
            assert check.cmdline == ("java", "-Xmx2G", "-jar", "server.jar", "nogui")
            assert check.cwd == str(server_dir)

    def test_verify_process_identity_accepts_wrapper_shell_when_allowed(self, tmp_path):
        server_dir = tmp_path / "wrapper-server"
        server_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.create_time.return_value = 1700000000.0
        mock_proc.cmdline.return_value = ["cmd.exe", "/c", "run.bat", "nogui"]
        mock_proc.cwd.return_value = str(server_dir)
        mock_proc.environ.return_value = {"ONX_MANAGED": "1"}

        with patch("psutil.Process", return_value=mock_proc):
            check = verify_process_identity(
                pid=1234,
                expected_create_time=1700000000.0,
                expected_server_dir=server_dir,
                allow_wrapper_shell=True,
            )
            assert check.verified is True
            assert check.reason == "verified"


class TestKillRefusalOnIdentityMismatch:
    @pytest.mark.asyncio
    async def test_windows_force_kill_refuses_when_identity_check_fails(self):
        provider = LocalWindowsProvider()

        with (
            patch.object(sys, "platform", "win32"),
            patch("psutil.pid_exists", return_value=True),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.verify_process_identity",
                return_value=ProcessIdentityCheck(
                    verified=False,
                    reason="create_time_mismatch",
                    create_time=999999.0,
                ),
            ),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            await provider._force_kill_process_tree(
                12345,
                expected_create_time=1000.0,
                expected_server_dir="/data/servers/srv-1",
            )
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_linux_stop_refuses_kill_when_identity_check_fails(self):
        provider = LocalLinuxProvider()
        handle = ServerHandle(
            provider="local",
            server_id="srv-linux-1",
            external_id="onx-srv-linux-1",
            metadata={"start_time": 1000, "server_dir": "/data/servers/srv-linux-1"},
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local.LocalLinuxProvider._get_tmux_pid",
                new_callable=AsyncMock,
                return_value=54321,
            ),
            patch("psutil.pid_exists", return_value=True),
            patch(
                "app.modules.server.infrastructure.providers.local.verify_process_identity",
                return_value=ProcessIdentityCheck(
                    verified=False,
                    reason="cmdline_mismatch",
                    create_time=1000.0,
                    cmdline=("postgres", "-D", "/var/lib/postgresql/data"),
                ),
            ),
            patch("os.kill") as mock_os_kill,
            patch(
                "app.modules.server.infrastructure.providers.local.LocalLinuxProvider.execute_command",
                new_callable=AsyncMock,
            ),
        ):
            await provider.stop(handle, force=False)
            mock_os_kill.assert_not_called()


class TestPortOccupantIdentityRefusal:
    @pytest.mark.asyncio
    async def test_claim_localhost_refuses_to_kill_unverified_port_occupant(self):
        server = _create_test_server("s1", port=25565)
        repo = MagicMock(spec_set=["get", "list", "save", "delete"])
        repo.list = AsyncMock(return_value=[])
        repo.get = AsyncMock(return_value=server)

        manager = RuntimeOwnershipManager(repo)

        with (
            patch(
                "app.modules.server.application.runtime_ownership._find_all_tmux_sessions",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._find_all_java_pids",
                return_value=[],
            ),
            patch(
                "app.modules.server.application.runtime_ownership._port_is_listening",
                return_value=True,
            ),
            patch(
                "app.modules.server.application.runtime_ownership._pid_for_port",
                return_value=8888,
            ),
            patch(
                "app.modules.server.application.runtime_ownership.verify_process_identity",
                return_value=ProcessIdentityCheck(
                    verified=False,
                    reason="cmdline_mismatch",
                    create_time=123.0,
                    cmdline=("nginx", "-g", "daemon off;"),
                ),
            ),
            patch(
                "app.modules.server.application.runtime_ownership._try_kill_process",
                return_value=(True, "killed"),
            ) as mock_kill,
        ):
            result = await manager.claim_localhost("s1")

            # Must NOT call _try_kill_process on unverified port occupant!
            mock_kill.assert_not_called()
            assert result.success is False
            assert any(
                "Port 25565 is occupied by PID 8888 which is not an ONX-managed Minecraft process"
                in w
                for w in result.warnings
            )
