from __future__ import annotations

from app.modules.plugin.infrastructure.dependency_resolver import DependencyResolver


class TestDependencyResolver:
    def test_resolve_no_deps(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("core", "1.0.0", [])
        result = resolver.resolve("core")
        assert result.success
        assert len(result.resolved) == 1

    def test_resolve_with_deps(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("lib-a", "1.0.0", [])
        resolver.register_plugin("app", "2.0.0", [{"name": "lib-a", "min_version": "1.0.0"}])
        result = resolver.resolve("app")
        assert result.success
        assert len(result.resolved) == 1

    def test_missing_dep(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("app", "1.0.0", [{"name": "missing-lib", "min_version": "1.0.0"}])
        result = resolver.resolve("app")
        assert not result.success
        assert len(result.conflicts) == 1
        assert result.conflicts[0].name == "missing-lib"

    def test_circular_dependency(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("a", "1.0.0", [{"name": "b", "min_version": "1.0.0"}])
        resolver.register_plugin("b", "1.0.0", [{"name": "a", "min_version": "1.0.0"}])
        result = resolver.resolve("a")
        assert not result.success
        assert any("Circular" in c.message for c in result.conflicts)

    def test_version_mismatch(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("lib", "1.0.0", [])
        resolver.register_plugin("app", "1.0.0", [{"name": "lib", "min_version": "2.0.0"}])
        result = resolver.resolve("app")
        assert not result.success
        assert "No version >= 2.0.0" in result.conflicts[0].message

    def test_picks_highest_version(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("lib", "1.0.0", [])
        resolver.register_plugin("lib", "2.0.0", [])
        resolver.register_plugin("app", "1.0.0", [{"name": "lib", "min_version": "1.0.0"}])
        result = resolver.resolve("app")
        assert result.success
        lib = result.resolved[0].dependencies[0]
        assert lib.version.major == 2

    def test_complex_dependency_tree(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("base", "1.0.0", [])
        resolver.register_plugin("middle", "1.0.0", [{"name": "base", "min_version": "1.0.0"}])
        resolver.register_plugin("top", "1.0.0", [{"name": "middle", "min_version": "1.0.0"}])
        result = resolver.resolve("top")
        assert result.success
        assert len(result.resolved) == 1

    def test_batch_register(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugins(
            [
                {"name": "a", "version": "1.0.0", "dependencies": []},
                {
                    "name": "b",
                    "version": "1.0.0",
                    "dependencies": [{"name": "a", "min_version": "1.0.0"}],
                },
            ]
        )
        result = resolver.resolve("b")
        assert result.success

    def test_constraint_chain_message(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("app", "1.0.0", [{"name": "missing", "min_version": "1.0.0"}])
        result = resolver.resolve("app")
        chain = result.constraint_chain
        assert "missing" in chain
        assert "required by" in chain
