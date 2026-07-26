from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.modules.plugin.infrastructure.manifest import ManifestLoader, PluginManifest
from app.modules.plugin.infrastructure.sandbox import FilesystemSandbox, NetworkSandbox


class TestSDKManifestIntegration:
    def test_plugin_manifest_from_yaml(self) -> None:
        yaml_content = """
name: "backup-to-s3"
version: "1.0.0"
min_app_version: "4.0.0"
isolation: "subprocess"
permissions:
  filesystem:
    paths: ["/backups"]
  network:
    hosts: ["s3.amazonaws.com"]
    ports: [443]
  events:
    subscribe: ["backup.completed"]
    publish: []
hooks:
  "backup.completed":
    handler: "handlers.on_backup"
    timeout: 60
dependencies:
  plugins:
    - name: "core-utils"
      min_version: "1.0.0"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            manifest = ManifestLoader.from_yaml(yaml_path)
            assert manifest.name == "backup-to-s3"
            assert manifest.version == "1.0.0"
            assert manifest.isolation == "subprocess"
            assert manifest.permissions.network.hosts == ["s3.amazonaws.com"]
            assert "backup.completed" in manifest.hooks
            assert len(manifest.dependencies.plugins) == 1
        finally:
            os.unlink(yaml_path)

    def test_sdk_reads_own_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("data.txt", b"hello from plugin")
            data = sandbox.read_file("data.txt")
            assert data == b"hello from plugin"

    def test_sdk_writes_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            config = json.dumps({"api_key": "test-123"}).encode()
            sandbox.write_file("config.json", config)
            read_back = sandbox.read_file("config.json")
            assert json.loads(read_back)["api_key"] == "test-123"

    def test_sdk_network_check(self) -> None:
        sandbox = NetworkSandbox(allowed_hosts=["api.example.com"], allowed_ports=[443])
        assert sandbox.check_url("https://api.example.com/v1/data")
        assert not sandbox.check_url("https://evil.com/malware")

    def test_sdk_list_own_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            sandbox.write_file("a.txt", b"")
            sandbox.write_file("sub/b.txt", b"")
            files = sandbox.list_files()
            assert "a.txt" in files
            assert "sub" in files


class TestSubprocessPlugin:
    @pytest.mark.asyncio
    async def test_json_rpc_ping_pong(self) -> None:
        from app.modules.plugin.infrastructure.runner.subprocess import JsonRpcClient

        client = JsonRpcClient()
        request = client.build_request("ping")
        data = json.loads(request)
        assert data["method"] == "ping"

        response = json.dumps({"jsonrpc": "2.0", "id": data["id"], "result": "pong"})
        result = client.parse_response(response)
        assert result == "pong"

    @pytest.mark.asyncio
    async def test_json_rpc_hook_call(self) -> None:
        from app.modules.plugin.infrastructure.runner.subprocess import JsonRpcClient

        client = JsonRpcClient()
        request = client.build_request(
            "hook",
            {"hook": "backup.completed", "payload": {"status": "success"}},
        )
        data = json.loads(request)
        assert data["params"]["hook"] == "backup.completed"
        assert data["params"]["payload"]["status"] == "success"

    def test_plugin_has_required_fields(self) -> None:
        manifest = PluginManifest(name="test", version="1.0.0")
        assert manifest.name
        assert manifest.version
        assert manifest.isolation in ("subprocess", "container")
