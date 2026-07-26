from __future__ import annotations

import json
import tempfile

import pytest

from app.modules.plugin.infrastructure.manifest import (
    ManifestLoader,
    PluginManifest,
)


class TestPluginManifest:
    def test_valid_manifest(self) -> None:
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            min_app_version="4.0.0",
        )
        assert manifest.name == "test-plugin"
        assert manifest.parsed_version().major == 1
        assert manifest.parsed_min_app_version().major == 4
        assert manifest.isolation == "subprocess"

    def test_manifest_with_permissions(self) -> None:
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            permissions={
                "filesystem": {"paths": ["/data", "/tmp"]},
                "network": {"hosts": ["api.example.com"], "ports": [443]},
                "events": {"subscribe": ["server.started"], "publish": []},
            },
        )
        assert manifest.permissions.filesystem.paths == ["/data", "/tmp"]
        assert manifest.permissions.network.hosts == ["api.example.com"]
        assert manifest.permissions.events.subscribe == ["server.started"]

    def test_manifest_with_hooks(self) -> None:
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            hooks={
                "backup.completed": {"handler": "handlers.on_backup", "timeout": 30},
            },
        )
        assert "backup.completed" in manifest.hooks
        assert manifest.hooks["backup.completed"].handler == "handlers.on_backup"

    def test_manifest_with_dependencies(self) -> None:
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            dependencies={
                "plugins": [
                    {"name": "dep-plugin", "min_version": "1.0.0"},
                ],
            },
        )
        assert len(manifest.dependencies.plugins) == 1
        assert manifest.dependencies.plugins[0].name == "dep-plugin"

    def test_invalid_version(self) -> None:
        with pytest.raises(Exception):
            PluginManifest(name="test", version="not-a-version")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(Exception):
            PluginManifest(name="", version="1.0.0")

    def test_isolated_container_accepted(self) -> None:
        manifest = PluginManifest(name="test", version="1.0.0", isolation="container")
        assert manifest.isolation == "container"

    def test_invalid_isolation_rejected(self) -> None:
        with pytest.raises(Exception):
            PluginManifest(name="test", version="1.0.0", isolation="invalid")


class TestManifestLoader:
    def test_from_dict(self) -> None:
        data = {
            "name": "test-plugin",
            "version": "1.0.0",
            "min_app_version": "4.0.0",
        }
        manifest = ManifestLoader.from_dict(data)
        assert manifest.name == "test-plugin"

    def test_from_dict_with_permissions(self) -> None:
        data = {
            "name": "test-plugin",
            "version": "1.0.0",
            "permissions": {
                "filesystem": {"paths": ["/data"]},
                "network": {"hosts": ["example.com"]},
            },
        }
        manifest = ManifestLoader.from_dict(data)
        assert manifest.permissions.filesystem.paths == ["/data"]

    def test_invalid_name_in_dict(self) -> None:
        with pytest.raises(Exception):
            ManifestLoader.from_dict({"name": "", "version": "1.0.0"})
