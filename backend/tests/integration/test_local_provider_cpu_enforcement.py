from __future__ import annotations

import ctypes
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.modules.server.infrastructure.fs import FileSystem
from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus
from app.modules.server.infrastructure.providers.local import LocalLinuxProvider
from app.modules.server.infrastructure.providers.local_windows import (
    LocalWindowsProvider,
    parse_affinity_mask,
)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="LocalLinuxProvider is POSIX-only; Windows uses LocalWindowsProvider",
)
class TestLocalLinuxProviderCpuEnforcement:
    @pytest.mark.asyncio
    async def test_linux_start_injects_active_processor_count_jar(self) -> None:
        provider = LocalLinuxProvider()
        config = {
            "server_dir": "/tmp/test-srv",
            "jar_path": "server.jar",
            "cpu_cores": 4,
            "port": 25565,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_find_java_processes", AsyncMock(return_value=[])),
            patch.object(provider, "_find_jvms_by_cwd", AsyncMock(return_value=[])),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
        ):
            result = await provider.start(server_id="srv-linux-cpu", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        cmd = mock_run.call_args[0][0]
        assert "-XX:ActiveProcessorCount=4" in cmd

    @pytest.mark.asyncio
    async def test_linux_start_writes_active_processor_count_to_jvm_args_script(self) -> None:
        provider = LocalLinuxProvider()
        mock_fs = MagicMock(spec=FileSystem)
        mock_fs.exists.side_effect = lambda path: path.endswith("run.sh")
        provider._fs = mock_fs

        config = {
            "server_dir": "/tmp/test-srv",
            "jar_path": "run.sh",
            "cpu_cores": 6,
            "port": 25565,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_find_java_processes", AsyncMock(return_value=[])),
            patch.object(provider, "_find_jvms_by_cwd", AsyncMock(return_value=[])),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)),
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
        ):
            await provider.start(server_id="srv-linux-script", config=config)

        mock_fs.write_text.assert_called_once()
        args = mock_fs.write_text.call_args[0]
        assert args[0].endswith("user_jvm_args.txt")
        assert "-XX:ActiveProcessorCount=6" in args[1]

    @pytest.mark.asyncio
    async def test_linux_start_wraps_command_in_taskset_when_affinity_provided(self) -> None:
        provider = LocalLinuxProvider()
        config = {
            "server_dir": "/tmp/test-srv",
            "jar_path": "server.jar",
            "cpu_affinity": "0-3",
            "port": 25565,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_find_java_processes", AsyncMock(return_value=[])),
            patch.object(provider, "_find_jvms_by_cwd", AsyncMock(return_value=[])),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
            patch("shutil.which", return_value="/usr/bin/taskset"),
        ):
            result = await provider.start(server_id="srv-linux-affinity", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        cmd = mock_run.call_args[0][0]
        assert "taskset -c 0-3" in cmd

    @pytest.mark.asyncio
    async def test_linux_start_skips_taskset_when_binary_not_found(self) -> None:
        provider = LocalLinuxProvider()
        config = {
            "server_dir": "/tmp/test-srv",
            "jar_path": "server.jar",
            "cpu_affinity": "0,2",
            "port": 25565,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_find_java_processes", AsyncMock(return_value=[])),
            patch.object(provider, "_find_jvms_by_cwd", AsyncMock(return_value=[])),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
            patch("shutil.which", return_value=None),
        ):
            result = await provider.start(server_id="srv-linux-missing-bin", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        cmd = mock_run.call_args[0][0]
        assert "taskset" not in cmd

    @pytest.mark.asyncio
    async def test_linux_start_validation_gate_rejects_invalid_cpu_allocation(self) -> None:
        provider = LocalLinuxProvider()

        with pytest.raises(ProviderError) as exc_info:
            await provider.start(
                server_id="srv-err",
                config={"cpu_affinity": "invalid-aff"},
            )
        assert "Invalid CPU allocation configuration" in str(exc_info.value)

        with pytest.raises(ProviderError) as exc_info2:
            await provider.start(
                server_id="srv-err-cores",
                config={"cpu_cores": -1},
            )
        assert "Invalid CPU allocation configuration" in str(exc_info2.value)


class TestLocalWindowsProviderCpuEnforcement:
    @pytest.mark.asyncio
    async def test_windows_start_injects_active_processor_count_jar(self) -> None:
        mock_fs = MagicMock(spec=FileSystem)
        mock_fs.exists.return_value = False
        provider = LocalWindowsProvider(fs=mock_fs)

        mock_proc = MagicMock()
        mock_proc.pid = 9876
        mock_proc.stdin = MagicMock()

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            result = await provider.start(
                server_id="srv-win-cpu",
                config={
                    "server_dir": "/srv/win",
                    "jar_path": "server.jar",
                    "port": 25565,
                    "cpu_cores": 4,
                },
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert "-XX:ActiveProcessorCount=4" in cmd_args

    @pytest.mark.asyncio
    async def test_windows_start_writes_active_processor_count_to_jvm_args_script(self) -> None:
        mock_fs = MagicMock(spec=FileSystem)
        mock_fs.exists.side_effect = lambda p: p.endswith("run.bat")
        provider = LocalWindowsProvider(fs=mock_fs)

        mock_proc = MagicMock()
        mock_proc.pid = 8765
        mock_proc.stdin = MagicMock()

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
        ):
            await provider.start(
                server_id="srv-win-script",
                config={
                    "server_dir": "/srv/win",
                    "jar_path": "run.bat",
                    "port": 25565,
                    "cpu_cores": 8,
                },
            )

        mock_fs.write_text.assert_called_once()
        args = mock_fs.write_text.call_args[0]
        assert args[0].endswith("user_jvm_args.txt")
        assert "-XX:ActiveProcessorCount=8" in args[1]

    @pytest.mark.asyncio
    async def test_windows_affinity_mask_parsing_and_kernel32_call(self) -> None:
        assert parse_affinity_mask("0") == 1
        assert parse_affinity_mask("0-3") == 15
        assert parse_affinity_mask("0,2") == 5

        mock_fs = MagicMock(spec=FileSystem)
        mock_fs.exists.return_value = False
        provider = LocalWindowsProvider(fs=mock_fs)

        mock_proc = MagicMock()
        mock_proc.pid = 7654
        mock_proc._handle = 42
        mock_proc.stdin = MagicMock()

        mock_kernel32 = MagicMock()
        mock_windll = MagicMock(kernel32=mock_kernel32)

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
            patch.object(ctypes, "windll", mock_windll, create=True),
        ):
            result = await provider.start(
                server_id="srv-win-aff",
                config={
                    "server_dir": "/srv/win",
                    "jar_path": "server.jar",
                    "port": 25565,
                    "cpu_affinity": "0-3",
                },
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        mock_kernel32.SetProcessAffinityMask.assert_called_once()
        handle_arg, mask_arg = mock_kernel32.SetProcessAffinityMask.call_args[0]
        assert handle_arg == 42
        assert mask_arg.value == 15

    @pytest.mark.asyncio
    async def test_windows_affinity_failure_logs_warning_and_proceeds(self) -> None:
        mock_fs = MagicMock(spec=FileSystem)
        mock_fs.exists.return_value = False
        provider = LocalWindowsProvider(fs=mock_fs)

        mock_proc = MagicMock()
        mock_proc.pid = 6543
        mock_proc._handle = 42
        mock_proc.stdin = MagicMock()

        mock_kernel32 = MagicMock()
        mock_kernel32.SetProcessAffinityMask.side_effect = OSError("Permission denied")
        mock_windll = MagicMock(kernel32=mock_kernel32)

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "app.modules.server.infrastructure.providers.local_windows.platform_pid_alive",
                return_value=True,
            ),
            patch.object(ctypes, "windll", mock_windll, create=True),
        ):
            result = await provider.start(
                server_id="srv-win-aff-fail",
                config={
                    "server_dir": "/srv/win",
                    "jar_path": "server.jar",
                    "port": 25565,
                    "cpu_affinity": "0-3",
                },
            )

        # Server must still start successfully even if affinity setting failed
        assert result.status == ServerRuntimeStatus.RUNNING

    @pytest.mark.asyncio
    async def test_windows_start_validation_gate_rejects_invalid_cpu_allocation(self) -> None:
        mock_fs = MagicMock(spec=FileSystem)
        provider = LocalWindowsProvider(fs=mock_fs)

        with pytest.raises(ProviderError) as exc_info:
            await provider.start(
                server_id="srv-win-err",
                config={"cpu_affinity": "invalid-mask"},
            )
        assert "Invalid CPU allocation configuration" in str(exc_info.value)

        with pytest.raises(ProviderError) as exc_info2:
            await provider.start(
                server_id="srv-win-err-cores",
                config={"cpu_cores": -2},
            )
        assert "Invalid CPU allocation configuration" in str(exc_info2.value)
