from __future__ import annotations

import pytest

from app.modules.plugin.infrastructure.lifecycle import (
    MAX_RESTART_ATTEMPTS,
    PluginLifecycleManager,
    RuntimeStatus,
)


class _MockRunner:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.healthy = True

    async def start(self, plugin_id: str, plugin_dir: str, manifest: dict) -> None:
        self.started.append(plugin_id)

    async def stop(self, plugin_id: str) -> None:
        self.stopped.append(plugin_id)

    async def restart(self, plugin_id: str) -> None:
        pass

    async def health(self, plugin_id: str) -> bool:
        return self.healthy

    async def execute_hook(self, plugin_id: str, hook: str, payload: dict) -> None:
        pass


class TestPluginLifecycleManager:
    @pytest.mark.asyncio
    async def test_install_sets_installed(self) -> None:
        mgr = PluginLifecycleManager(_MockRunner())
        await mgr.install("p1")
        status = await mgr.get_status("p1")
        assert status == RuntimeStatus.INSTALLED

    @pytest.mark.asyncio
    async def test_enable_transitions(self) -> None:
        runner = _MockRunner()
        mgr = PluginLifecycleManager(runner)
        await mgr.install("p1")
        await mgr.enable("p1", "/tmp/p1", {})
        status = await mgr.get_status("p1")
        assert status == RuntimeStatus.ENABLED
        assert "p1" in runner.started

    @pytest.mark.asyncio
    async def test_disable_transitions(self) -> None:
        runner = _MockRunner()
        mgr = PluginLifecycleManager(runner)
        await mgr.install("p1")
        await mgr.enable("p1", "/tmp/p1", {})
        await mgr.disable("p1")
        status = await mgr.get_status("p1")
        assert status == RuntimeStatus.DISABLED
        assert "p1" in runner.stopped

    @pytest.mark.asyncio
    async def test_uninstall_cleans_up(self) -> None:
        runner = _MockRunner()
        mgr = PluginLifecycleManager(runner)
        await mgr.install("p1")
        await mgr.uninstall("p1")
        status = await mgr.get_status("p1")
        assert status is None

    @pytest.mark.asyncio
    async def test_enable_failure_sets_failed(self) -> None:
        class _FailingRunner(_MockRunner):
            async def start(self, plugin_id: str, plugin_dir: str, manifest: dict) -> None:
                raise RuntimeError("Start failed")

        mgr = PluginLifecycleManager(_FailingRunner())
        await mgr.install("p1")
        with pytest.raises(RuntimeError):
            await mgr.enable("p1", "/tmp/p1", {})
        status = await mgr.get_status("p1")
        assert status == RuntimeStatus.FAILED

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        runner = _MockRunner()
        mgr = PluginLifecycleManager(runner)
        await mgr.install("p1")
        await mgr.enable("p1", "/tmp/p1", {})
        healthy = await mgr.check_health("p1")
        assert healthy

    @pytest.mark.asyncio
    async def test_mark_failed(self) -> None:
        mgr = PluginLifecycleManager(_MockRunner())
        await mgr.install("p1")
        await mgr.mark_failed("p1")
        status = await mgr.get_status("p1")
        assert status == RuntimeStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self) -> None:
        mgr = PluginLifecycleManager(_MockRunner())
        await mgr.install("p1")

        with pytest.raises(ValueError, match="Cannot transition"):
            await mgr._transition("p1", RuntimeStatus.UNINSTALLED)

    def test_max_restart_attempts(self) -> None:
        assert MAX_RESTART_ATTEMPTS == 3
