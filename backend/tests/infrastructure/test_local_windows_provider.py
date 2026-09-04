from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.modules.server.domain.value_objects import LaunchConfiguration
from app.modules.server.infrastructure.fs import FileSystem
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.providers.local_windows import (
    LocalWindowsProvider,
    is_windows,
)
from app.modules.server.infrastructure.providers.patterns import FailureCode


@pytest.fixture
def mock_fs():
    fs = MagicMock(spec=FileSystem)
    fs.exists.return_value = False
    return fs


@pytest.fixture
def provider(mock_fs):
    return LocalWindowsProvider(fs=mock_fs)


class TestLocalWindowsProviderStart:
    @pytest.mark.asyncio
    async def test_start_spawns_process_and_returns_correct_metadata(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 4321
        mock_proc.stdin = MagicMock()

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-1",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "paper.jar",
                    "port": 25565,
                    "memory_min_mb": 2048,
                    "memory_max_mb": 4096,
                },
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.address == "127.0.0.1"
        assert result.port == 25565
        assert result.pid == 4321
        assert "handle" in result.metadata
        assert "session_name" in result.metadata
        assert "start_time" in result.metadata
        assert isinstance(result.metadata["start_time"], int)
        assert result.metadata["port"] == 25565
        assert result.metadata["pid"] == 4321
        assert result.metadata["server_dir"] == "/test/server"

        mock_popen.assert_called_once()
        cmd_args, popen_kwargs = mock_popen.call_args[0][0], mock_popen.call_args[1]
        assert isinstance(cmd_args, list)
        assert cmd_args == ["java", "-Xms2048M", "-Xmx4096M", "-jar", "paper.jar", "nogui"]
        assert popen_kwargs["cwd"] == "/test/server"
        assert "shell" not in popen_kwargs or popen_kwargs.get("shell") is not True
        assert popen_kwargs["stdin"] == subprocess.PIPE
        assert popen_kwargs["stdout"] == subprocess.DEVNULL
        assert popen_kwargs["stderr"] == subprocess.DEVNULL
        assert "ONX_INSTANCE_ID" in popen_kwargs["env"]

    @pytest.mark.asyncio
    async def test_start_plain_java_command_list_no_shell(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 1111
        mock_proc.stdin = MagicMock()

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            await provider.start(
                server_id="srv-plain",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "server.jar",
                    "java_args": ["-XX:+UseG1GC", "-Dfile.encoding=UTF-8"],
                    "memory_min_mb": 1024,
                    "memory_max_mb": 2048,
                    "port": 25565,
                },
            )

        mock_popen.assert_called_once()
        cmd_args, popen_kwargs = mock_popen.call_args[0][0], mock_popen.call_args[1]
        assert isinstance(cmd_args, list)
        assert cmd_args == [
            "java",
            "-XX:+UseG1GC",
            "-Dfile.encoding=UTF-8",
            "-Xms1024M",
            "-Xmx2048M",
            "-jar",
            "server.jar",
            "nogui",
        ]
        assert "shell" not in popen_kwargs or popen_kwargs.get("shell") is not True

    @pytest.mark.asyncio
    async def test_start_bat_script_command_list(self, provider, mock_fs):
        mock_proc = MagicMock()
        mock_proc.pid = 2222
        mock_proc.stdin = MagicMock()

        mock_fs.exists.side_effect = lambda path: path.endswith("run.bat")

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            await provider.start(
                server_id="srv-bat",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "server.jar",
                    "port": 25565,
                },
            )

        mock_popen.assert_called_once()
        cmd_args, popen_kwargs = mock_popen.call_args[0][0], mock_popen.call_args[1]
        assert isinstance(cmd_args, list)
        assert cmd_args == ["cmd.exe", "/c", "run.bat", "nogui"]
        assert "shell" not in popen_kwargs or popen_kwargs.get("shell") is not True

    @pytest.mark.asyncio
    async def test_start_ps1_script_command_list(self, provider, mock_fs):
        mock_proc = MagicMock()
        mock_proc.pid = 3333
        mock_proc.stdin = MagicMock()

        mock_fs.exists.side_effect = lambda path: path.endswith("run.ps1")

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            await provider.start(
                server_id="srv-ps1",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "server.jar",
                    "port": 25565,
                },
            )

        mock_popen.assert_called_once()
        cmd_args, popen_kwargs = mock_popen.call_args[0][0], mock_popen.call_args[1]
        assert isinstance(cmd_args, list)
        assert cmd_args == [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "run.ps1",
            "nogui",
        ]
        assert "shell" not in popen_kwargs or popen_kwargs.get("shell") is not True

    @pytest.mark.asyncio
    async def test_start_ps1_only_regression_test(self, provider, mock_fs):
        # Scenario: run.ps1 exists, run.bat and run.cmd both absent, jar_path does not exist
        mock_proc = MagicMock()
        mock_proc.pid = 3334
        mock_proc.stdin = MagicMock()

        def fake_exists(path: str) -> bool:
            if path.endswith("run.bat") or path.endswith("run.cmd") or path.endswith("server.jar"):
                return False
            return path.endswith("run.ps1")

        mock_fs.exists.side_effect = fake_exists

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-ps1-only",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "server.jar",
                    "port": 25565,
                },
            )

        assert result.pid == 3334
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert isinstance(cmd_args, list)
        # Must resolve to powershell.exe with run.ps1, NOT a bare "server.jar nogui"
        assert cmd_args == [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "run.ps1",
            "nogui",
        ]

    @pytest.mark.asyncio
    async def test_start_creationflags_includes_create_no_window(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 4444
        mock_proc.stdin = MagicMock()

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            await provider.start(
                server_id="srv-win-flags",
                config={
                    "server_dir": "/test/server",
                    "jar_path": "server.jar",
                    "port": 25565,
                },
            )

        mock_popen.assert_called_once()
        popen_kwargs = mock_popen.call_args[1]
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW
        expected_flags = 0x00000200 | 0x00000008 | 0x08000000
        assert popen_kwargs["creationflags"] == expected_flags

    @pytest.mark.asyncio
    async def test_start_launch_config_effective_command(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 5678
        mock_proc.stdin = MagicMock()

        launch_config = LaunchConfiguration(
            java_executable="custom_java.exe",
            jvm_flags=("-XX:+UseG1GC",),
            startup_jar="server.jar",
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-lc",
                config={"server_dir": "/test/server", "port": 25570},
                launch_config=launch_config,
            )

        assert result.pid == 5678
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert isinstance(cmd_args, list)
        assert "custom_java.exe" in cmd_args
        assert "-XX:+UseG1GC" in cmd_args

    @pytest.mark.asyncio
    async def test_start_launch_config_windows_path_with_spaces_and_backslashes(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 7777
        mock_proc.stdin = MagicMock()

        custom_java = r"C:\Program Files\Java\bin\java.exe"
        launch_config = LaunchConfiguration(
            startup_command=[custom_java, "-jar", "server.jar", "nogui"],
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-path",
                config={"server_dir": r"C:\minecraft\servers\srv-win-path", "port": 25575},
                launch_config=launch_config,
            )

        assert result.pid == 7777
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert isinstance(cmd_args, list)
        # Verify exact character-for-character preservation with spaces and backslashes intact
        assert cmd_args[0] == custom_java
        assert cmd_args == [custom_java, "-jar", "server.jar", "nogui", "-Xms1024M", "-Xmx2048M"]

    @pytest.mark.asyncio
    async def test_start_launch_config_ps1_script_list(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 8888
        mock_proc.stdin = MagicMock()

        launch_config = LaunchConfiguration(
            startup_command=["custom_start.ps1"],
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-ps1-lc",
                config={"server_dir": "/test/server", "port": 25580},
                launch_config=launch_config,
            )

        assert result.pid == 8888
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert isinstance(cmd_args, list)
        assert cmd_args == [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "custom_start.ps1",
            "nogui",
        ]

    @pytest.mark.asyncio
    async def test_start_launch_config_bat_script_list(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 8889
        mock_proc.stdin = MagicMock()

        launch_config = LaunchConfiguration(
            startup_command=["custom_start.bat"],
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-bat-lc",
                config={"server_dir": "/test/server", "port": 25585},
                launch_config=launch_config,
            )

        assert result.pid == 8889
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert isinstance(cmd_args, list)
        assert cmd_args == ["cmd.exe", "/c", "custom_start.bat", "nogui"]

    @pytest.mark.asyncio
    async def test_start_raises_when_port_in_use(self, provider):
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.bind.side_effect = OSError("Address already in use")
            mock_socket_cls.return_value = mock_sock

            with pytest.raises(ProviderError) as exc_info:
                await provider.start(
                    server_id="srv-fail",
                    config={"port": 25565},
                )
            assert "already in use" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_start_raises_when_process_dies_immediately(self, provider):
        mock_proc = MagicMock()
        mock_proc.pid = 9999

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._verify_port_free",
                new_callable=AsyncMock,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=False,
            ),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.start(
                    server_id="srv-die",
                    config={"server_dir": "/test/server", "port": 25565},
                )
            assert "died immediately" in str(exc_info.value)


class TestLocalWindowsProviderVerifyAndStatus:
    @pytest.mark.asyncio
    async def test_verify_process_scenario_3(self, provider):
        handle_live = ServerHandle(
            provider="local_windows",
            server_id="srv-1",
            external_id="1234",
            metadata={"pid": 1234},
        )
        handle_dead = ServerHandle(
            provider="local_windows",
            server_id="srv-2",
            external_id="5678",
            metadata={"pid": 5678},
        )
        handle_no_pid = ServerHandle(
            provider="local_windows",
            server_id="srv-3",
            external_id="not-a-number",
            metadata={},
        )

        with patch(
            "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
            side_effect=lambda pid: pid == 1234,
        ):
            assert await provider.verify_process(handle_live) is True
            assert await provider.verify_process(handle_dead) is False
            assert await provider.verify_process(handle_no_pid) is False

    @pytest.mark.asyncio
    async def test_status_returns_running_and_stopped(self, provider):
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-1",
            external_id="1234",
            metadata={"pid": 1234},
        )

        with patch(
            "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
            return_value=True,
        ):
            assert await provider.status(handle) == ServerRuntimeStatus.RUNNING

        with patch(
            "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
            return_value=False,
        ):
            assert await provider.status(handle) == ServerRuntimeStatus.STOPPED


class TestLocalWindowsProviderStop:
    @pytest.mark.asyncio
    async def test_stop_graceful_scenario_4(self, provider):
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-graceful",
            external_id="2001",
            metadata={"pid": 2001},
        )

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        provider._processes["srv-graceful"] = mock_proc

        liveness = [True, True, False]

        def fake_pid_alive(_pid):
            if liveness:
                return liveness.pop(0)
            return False

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                side_effect=fake_pid_alive,
            ),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._force_kill_process_tree",
                new_callable=AsyncMock,
            ) as mock_force,
        ):
            await provider.stop(handle, force=False)
            mock_force.assert_not_called()

        assert "srv-graceful" not in provider._processes

    @pytest.mark.asyncio
    async def test_stop_force_kill_fallback_scenario_5(self, provider):
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-force",
            external_id="3001",
            metadata={"pid": 3001},
        )

        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.LocalWindowsProvider._force_kill_process_tree",
                new_callable=AsyncMock,
            ) as mock_force,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await provider.stop(handle, force=True)
            mock_force.assert_called_once_with(3001)

    @pytest.mark.asyncio
    async def test_force_kill_process_tree_calls_taskkill_on_win32(self, provider):
        with (
            patch.object(sys, "platform", "win32"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_proc = AsyncMock()
            mock_exec.return_value = mock_proc
            await provider._force_kill_process_tree(4001)
            mock_exec.assert_called_once_with(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                "4001",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

    @pytest.mark.asyncio
    async def test_force_kill_process_tree_calls_platform_kill_on_posix(self, provider):
        with (
            patch.object(sys, "platform", "linux"),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_kill_process_tree_async",
                new_callable=AsyncMock,
            ) as mock_kill,
        ):
            await provider._force_kill_process_tree(4001)
            mock_kill.assert_called_once_with(4001, sig=signal.SIGKILL)


class TestLocalWindowsProviderConsoleAndExec:
    @pytest.mark.asyncio
    async def test_console_reads_log_tail(self, provider, tmp_path):
        server_dir = tmp_path / "server1"
        logs_dir = server_dir / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "latest.log"

        lines = [f"[Server thread/INFO]: Line {i}" for i in range(150)]
        log_file.write_text("\n".join(lines), encoding="utf-8")

        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-1",
            external_id="1234",
            metadata={"server_dir": str(server_dir), "pid": 1234},
        )

        captured = await provider.console(handle, tail=50)
        assert len(captured) == 50
        assert captured[-1] == "[Server thread/INFO]: Line 149"

    @pytest.mark.asyncio
    async def test_execute_command_writes_to_stdin(self, provider):
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        provider._processes["srv-cmd"] = mock_proc

        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-cmd",
            external_id="1234",
            metadata={"pid": 1234},
        )

        res = await provider.execute_command(handle, "say hello")
        assert "Command sent" in res
        mock_proc.stdin.write.assert_called_once_with(b"say hello\n")
        mock_proc.stdin.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_command_raises_without_stdin(self, provider):
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-no-proc",
            external_id="1234",
            metadata={"pid": 1234},
        )
        with (
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=False,
            ),
            pytest.raises(ProviderError) as exc_info,
        ):
            await provider.execute_command(handle, "say hello")
        assert "no interactive stdin" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_command_raises_actionable_error_on_lost_handle_after_restart(
        self, provider
    ):
        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-lost-proc",
            external_id="5678",
            metadata={"pid": 5678},
        )
        with patch(
            "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
            return_value=True,
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.execute_command(handle, "save-all")
            assert "Console access lost" in str(exc_info.value)
            assert "after daemon restart" in str(exc_info.value)
            assert "PID 5678" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_collect_diagnostics_and_failure_detection(self, provider, tmp_path):
        server_dir = tmp_path / "server_crash"
        logs_dir = server_dir / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "latest.log"

        log_file.write_text("java.net.BindException: Address already in use\n", encoding="utf-8")

        handle = ServerHandle(
            provider="local_windows",
            server_id="srv-crash",
            external_id="5001",
            metadata={"server_dir": str(server_dir), "pid": 5001},
        )

        with patch(
            "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
            return_value=False,
        ):
            diag = await provider.collect_diagnostics(handle)

        assert diag.provider == "local_windows"
        assert diag.exit_code == -1
        assert len(diag.last_log_lines) == 1
        assert "BindException" in diag.last_log_lines[0]
        assert diag.failure_code == FailureCode.PORT_ALREADY_BOUND

    def test_is_windows_helper(self):
        with patch.object(sys, "platform", "win32"):
            assert is_windows() is True
        with patch.object(sys, "platform", "linux"):
            assert is_windows() is False
