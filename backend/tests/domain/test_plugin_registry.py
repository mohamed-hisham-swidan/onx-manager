from __future__ import annotations

import pytest

from app.modules.plugin.domain.aggregate import DependencyStatus, Plugin, PluginRegistry
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


@pytest.fixture
def registry() -> PluginRegistry:
    return PluginRegistry(server_id=ServerId("s1"))


class TestPluginRegistry:
    def test_empty_registry(self, registry: PluginRegistry) -> None:
        assert len(registry.plugins) == 0
        assert registry.server_id == ServerId("s1")

    def test_add_and_get_plugin(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="TestPlugin",
            version=PluginVersion.parse("1.0.0"),
        )
        registry.add_plugin(plugin)
        assert len(registry.plugins) == 1
        retrieved = registry.get_plugin(PluginId("p1"))
        assert retrieved is not None
        assert retrieved.name == "TestPlugin"

    def test_get_by_name(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="UniqueName",
            version=PluginVersion.parse("1.0.0"),
        )
        registry.add_plugin(plugin)
        found = registry.get_by_name("UniqueName")
        assert found is not None
        assert found.plugin_id == PluginId("p1")

    def test_get_by_name_not_found(self, registry: PluginRegistry) -> None:
        assert registry.get_by_name("Nope") is None

    def test_remove_plugin(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="RemoveMe",
            version=PluginVersion.parse("1.0.0"),
        )
        registry.add_plugin(plugin)
        registry.remove_plugin(PluginId("p1"))
        assert registry.get_plugin(PluginId("p1")) is None

    def test_check_dependencies_missing(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="DepPlugin",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["MissingDep"],
        )
        registry.add_plugin(plugin)
        deps = registry.check_dependencies(plugin)
        assert deps["MissingDep"] == DependencyStatus.MISSING

    def test_check_dependencies_satisfied(self, registry: PluginRegistry) -> None:
        dep = Plugin.install(
            plugin_id=PluginId("dep1"),
            server_id=ServerId("s1"),
            name="BaseLib",
            version=PluginVersion.parse("1.0.0"),
        )
        dep.enable()
        registry.add_plugin(dep)
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="MainPlugin",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["BaseLib"],
        )
        registry.add_plugin(plugin)
        deps = registry.check_dependencies(plugin)
        assert deps["BaseLib"] == DependencyStatus.SATISFIED

    def test_can_enable(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="Standalone",
            version=PluginVersion.parse("1.0.0"),
        )
        registry.add_plugin(plugin)
        assert registry.can_enable(plugin) is True

    def test_can_enable_missing_dep(self, registry: PluginRegistry) -> None:
        plugin = Plugin.install(
            plugin_id=PluginId("p1"),
            server_id=ServerId("s1"),
            name="NeedsDep",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["Missing"],
        )
        registry.add_plugin(plugin)
        assert registry.can_enable(plugin) is False

    def test_circular_dependency(self, registry: PluginRegistry) -> None:
        a = Plugin.install(
            plugin_id=PluginId("a"),
            server_id=ServerId("s1"),
            name="PluginA",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["PluginB"],
        )
        b = Plugin.install(
            plugin_id=PluginId("b"),
            server_id=ServerId("s1"),
            name="PluginB",
            version=PluginVersion.parse("1.0.0"),
            dependencies=["PluginA"],
        )
        a.collect_events()
        b.collect_events()
        a.enable()
        b.enable()
        registry.add_plugin(a)
        registry.add_plugin(b)
        deps = registry.check_dependencies(a)
        assert DependencyStatus.CIRCULAR in deps.values()
