from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.exposure.infrastructure.playit_agent import PlayitAgentSupervisor
from app.modules.plugin.domain.aggregate import _PLUGIN_TRANSITIONS, Plugin, PluginStatus
from app.modules.plugin.infrastructure.lifecycle import PluginLifecycleManager, RuntimeStatus
from app.modules.plugin.infrastructure.runner.subprocess import SubprocessPluginRunner
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


def test_f038_plugin_mark_uninstalled_transition():
    """F038: Plugin aggregate transitions to UNINSTALLED and transitions map permits it."""
    plugin = Plugin(
        plugin_id=PluginId("p-test"),
        server_id=ServerId("s-1"),
        name="Test Plugin",
        version=PluginVersion(1, 0, 0),
        status=PluginStatus.INSTALLED,
    )
    assert PluginStatus.UNINSTALLED in _PLUGIN_TRANSITIONS[PluginStatus.INSTALLED]
    assert PluginStatus.UNINSTALLED in _PLUGIN_TRANSITIONS[PluginStatus.ENABLED]
    assert PluginStatus.UNINSTALLED in _PLUGIN_TRANSITIONS[PluginStatus.DISABLED]
    assert PluginStatus.UNINSTALLED in _PLUGIN_TRANSITIONS[PluginStatus.ERROR]

    plugin.mark_uninstalled()
    assert plugin.status == PluginStatus.UNINSTALLED
    events = plugin.collect_events()
    assert any(e.__class__.__name__ == "PluginUninstalledEvent" for e in events)


@pytest.mark.asyncio
async def test_f041_lifecycle_on_heartbeat_missed_restarts():
    """F041: PluginLifecycleManager restarts runner when heartbeat missed <= max attempts."""
    mock_runner = MagicMock()
    mock_runner.start = AsyncMock()
    mock_runner.stop = AsyncMock()

    mgr = PluginLifecycleManager(mock_runner)
    await mgr.enable("p1", "/fake/dir", {"entry_point": "main.py"})
    assert await mgr.get_status("p1") == RuntimeStatus.ENABLED

    # Missed heartbeat 1/3 triggers restart
    await mgr.on_heartbeat_missed("p1")
    assert await mgr.get_status("p1") == RuntimeStatus.ENABLED
    assert mock_runner.start.call_count == 2  # once on enable, once on restart

    # Exceeding MAX_RESTART_ATTEMPTS transitions to FAILED
    mgr._restart_counts["p1"] = 3
    await mgr.on_heartbeat_missed("p1")
    assert await mgr.get_status("p1") == RuntimeStatus.FAILED


@pytest.mark.asyncio
async def test_f042_subprocess_runner_restart():
    """F042: SubprocessPluginRunner.restart retrieves saved config and calls start."""
    runner = SubprocessPluginRunner()
    runner.start = AsyncMock()
    runner.stop = AsyncMock()

    runner._plugin_configs["p1"] = ("/fake/plugins/p1", {"entry_point": "plugin.py"})
    await runner.restart("p1")

    runner.stop.assert_awaited_once_with("p1")
    runner.start.assert_awaited_once_with("p1", "/fake/plugins/p1", {"entry_point": "plugin.py"})


@pytest.mark.asyncio
async def test_f047_playit_agent_terminate_pid_direct_windows():
    """F047: _terminate_pid_direct on Windows invokes taskkill and never touches signal.SIGKILL."""
    agent = PlayitAgentSupervisor()

    with (
        patch("app.modules.exposure.infrastructure.playit_agent.is_windows", return_value=True),
        patch("subprocess.run") as mock_run,
    ):
        await agent._terminate_pid_direct(12345)
        mock_run.assert_called_once_with(
            ["taskkill", "/F", "/PID", "12345"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


@pytest.mark.asyncio
async def test_f049_supervisor_cleanup_os_resources_uses_subprocess():
    """F049: _cleanup_os_resources uses subprocess.run with list arguments for tmux cleanup."""
    server = MagicMock()
    server.id = "s1"
    server.name = "TestServer"
    handle = MagicMock()
    handle.external_id = "tmux-session-123"

    supervisor = RuntimeSupervisor(
        server=server,
        provider=MagicMock(),
        handle=handle,
        repo_get=AsyncMock(),
        repo_save=AsyncMock(),
    )

    with patch("subprocess.run") as mock_run:
        # Mock tmux has-session returncode == 0
        mock_run.return_value = MagicMock(returncode=0)
        await supervisor._cleanup_os_resources()

        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["tmux", "has-session", "-t", "tmux-session-123"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
        mock_run.assert_any_call(
            ["tmux", "kill-session", "-t", "tmux-session-123"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )


@pytest.mark.asyncio
async def test_supervisor_cleanup_os_resources_timeout_handled():
    """_cleanup_os_resources catches TimeoutExpired gracefully."""
    server = MagicMock()
    server.id = "s1"
    server.name = "TestServer"
    handle = MagicMock()
    handle.external_id = "tmux-session-123"

    supervisor = RuntimeSupervisor(
        server=server,
        provider=MagicMock(),
        handle=handle,
        repo_get=AsyncMock(),
        repo_save=AsyncMock(),
    )

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tmux", timeout=5)):
        # Should catch TimeoutExpired and return without raising
        await supervisor._cleanup_os_resources()
