from __future__ import annotations

import pytest

from app.core.exceptions import InvalidValueError
from app.modules.plugin.domain.aggregate import Plugin, PluginStatus
from app.modules.plugin.domain.events import (
    PluginDisabledEvent,
    PluginEnabledEvent,
    PluginInstalledEvent,
    PluginUninstalledEvent,
)
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


@pytest.fixture
def sample_plugin() -> Plugin:
    return Plugin.install(
        plugin_id=PluginId("essentialsx"),
        server_id=ServerId("s1"),
        name="EssentialsX",
        version=PluginVersion.parse("2.20.0"),
        description="Essential commands",
        author="Essentials Team",
    )


class TestPlugin:
    def test_install_emits_event(self, sample_plugin: Plugin) -> None:
        events = sample_plugin.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], PluginInstalledEvent)
        assert events[0].version == "2.20.0"

    def test_initial_status(self, sample_plugin: Plugin) -> None:
        assert sample_plugin.status == PluginStatus.INSTALLED

    def test_enable(self, sample_plugin: Plugin) -> None:
        sample_plugin.collect_events()
        sample_plugin.enable()
        assert sample_plugin.status == PluginStatus.ENABLED
        events = sample_plugin.collect_events()
        assert any(isinstance(e, PluginEnabledEvent) for e in events)

    def test_disable(self, sample_plugin: Plugin) -> None:
        sample_plugin.enable()
        sample_plugin.collect_events()
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED
        events = sample_plugin.collect_events()
        assert any(isinstance(e, PluginDisabledEvent) for e in events)

    def test_disable_from_installed(self, sample_plugin: Plugin) -> None:
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED

    def test_enable_already_enabled_is_noop(self, sample_plugin: Plugin) -> None:
        sample_plugin.enable()
        assert sample_plugin.status == PluginStatus.ENABLED
        sample_plugin.collect_events()
        # Redundant call must not raise and must not emit duplicate events
        sample_plugin.enable()
        assert sample_plugin.status == PluginStatus.ENABLED
        assert len(sample_plugin.collect_events()) == 0

    def test_disable_already_disabled_is_noop(self, sample_plugin: Plugin) -> None:
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED
        sample_plugin.collect_events()
        # Redundant call must not raise and must not emit duplicate events
        sample_plugin.disable()
        assert sample_plugin.status == PluginStatus.DISABLED
        assert len(sample_plugin.collect_events()) == 0

    def test_invalid_transition(self, sample_plugin: Plugin) -> None:
        with pytest.raises(InvalidValueError):
            sample_plugin.mark_error()

    def test_mark_error_from_enabled(self, sample_plugin: Plugin) -> None:
        sample_plugin.enable()
        sample_plugin.mark_error()
        assert sample_plugin.status == PluginStatus.ERROR

    def test_update_version(self, sample_plugin: Plugin) -> None:
        sample_plugin.collect_events()
        new_version = PluginVersion.parse("2.21.0")
        sample_plugin.update_version(new_version)
        assert sample_plugin.version == new_version
        from app.modules.plugin.domain.events import PluginUpdatedEvent

        events = sample_plugin.collect_events()
        assert any(isinstance(e, PluginUpdatedEvent) for e in events)

    def test_mark_uninstalled(self, sample_plugin: Plugin) -> None:
        sample_plugin.collect_events()
        sample_plugin.mark_uninstalled()
        events = sample_plugin.collect_events()
        assert any(isinstance(e, PluginUninstalledEvent) for e in events)

    def test_properties(self, sample_plugin: Plugin) -> None:
        assert sample_plugin.name == "EssentialsX"
        assert sample_plugin.author == "Essentials Team"
        assert sample_plugin.description == "Essential commands"
        assert len(sample_plugin.dependencies) == 0

    def test_dependencies_list(self) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("vault"),
            server_id=ServerId("s1"),
            name="Vault",
            version=PluginVersion.parse("1.7.3"),
            dependencies=["EssentialsX"],
        )
        assert plugin.dependencies == ["EssentialsX"]
