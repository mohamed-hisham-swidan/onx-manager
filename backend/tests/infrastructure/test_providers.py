from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ProviderFactory,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
    provider_factory,
)
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.server.infrastructure.providers.remote import SSHProvider


class TestProviderFactory:
    def test_register_and_get(self) -> None:
        factory = ProviderFactory()
        provider = DockerProvider()
        factory.register(provider)
        assert factory.get("docker") is provider
        assert "docker" in factory.list_types()

    def test_get_unregistered_raises(self) -> None:
        factory = ProviderFactory()
        with pytest.raises(ValueError, match="No provider registered"):
            factory.get("nonexistent")

    def test_default_registrations(self) -> None:
        assert "docker" in provider_factory.list_types()
        assert "local" not in provider_factory.list_types()
        assert "local_windows" not in provider_factory.list_types()


class TestServerHandle:
    def test_create_handle(self) -> None:
        handle = ServerHandle(
            provider="local",
            server_id="s1",
            external_id="onx-s1",
            metadata={"key": "val"},
        )
        assert str(handle) == "local/s1:onx-s1"
        assert handle.metadata["key"] == "val"


class TestDeploymentResult:
    def test_create_result(self) -> None:
        result = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=1234,
            metadata={"key": "val"},
        )
        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 1234
        assert result.metadata["key"] == "val"


class TestProviderTypes:
    @pytest.mark.asyncio
    async def test_docker_provider_type(self) -> None:
        assert DockerProvider().provider_type == "docker"

    @pytest.mark.asyncio
    async def test_ssh_provider_type(self) -> None:
        provider = SSHProvider(host="localhost")
        assert provider.provider_type == "ssh"


class TestProviderCapabilities:
    def test_base_provider_default_capabilities(self) -> None:
        class DummyProvider(ServerProvider):
            @property
            def provider_type(self) -> str:
                return "dummy"

            async def ping(self) -> bool:
                return True

            async def start(self, *args, **kwargs):
                pass

            async def stop(self, *args, **kwargs):
                pass

            async def status(self, *args, **kwargs):
                pass

            async def console(self, *args, **kwargs):
                pass

            async def execute_command(self, *args, **kwargs):
                pass

            async def destroy(self, *args, **kwargs):
                pass

        assert DummyProvider().capabilities() == []

    def test_docker_provider_capabilities(self) -> None:
        capabilities = DockerProvider().capabilities()
        assert capabilities == ["process", "console", "exec"]
        assert "docker" not in capabilities
        assert "logs" not in capabilities


def _make_docker_command_fake(pid_ip: str = "1234\n"):
    async def fake_docker_command(*args: object, **_kwargs: object):
        if not args:
            return (0, "")
        cmd = args[0]
        if cmd == "inspect":
            if "--format" in args and "{{json .}}" in args:
                return (1, "")
            return (0, pid_ip)
        if cmd in ("create", "start", "rm"):
            return (0, "")
        return (0, "")
    return fake_docker_command


class TestDockerProvider:
    @pytest.mark.asyncio
    async def test_start_creates_container_with_ownership_labels(self) -> None:
        provider = DockerProvider()
        config = {
            "image": "itzg/minecraft-server:latest",
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()) as mock_ensure,
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = _make_docker_command_fake(pid_ip="12345 172.17.0.5\n")
            result = await provider.start(server_id="test-server-42", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 12345
        assert result.port == 25565
        mock_ensure.assert_awaited_once_with("itzg/minecraft-server:latest")

        create_call = next(c for c in mock_docker.call_args_list if c[0] and c[0][0] == "create")
        create_call_args = list(create_call[0])
        assert create_call_args[0] == "create"
        assert "--name" in create_call_args
        name_idx = create_call_args.index("--name")
        assert create_call_args[name_idx + 1] == "onx-test-server-42"
        assert "--label" in create_call_args
        assert "com.onx-manager.managed=true" in create_call_args
        assert "com.onx-manager.server_id=test-server-42" in create_call_args
        assert "com.onx-manager.runtime=docker" in create_call_args

    @pytest.mark.asyncio
    async def test_docker_start_quotes_special_characters(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "my world's" / "dir"
        srv_dir.mkdir(parents=True)
        config = {
            "image": "itzg/minecraft-server:latest",
            "world_dir": str(srv_dir),
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.dict(
                os.environ,
                {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
            ),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = _make_docker_command_fake(pid_ip="12345 172.17.0.5\n")
            await provider.start(server_id="srv 'special' 42", config=config)

        create_call = next(c for c in mock_docker.call_args_list if c[0] and c[0][0] == "create")
        create_call_args = list(create_call[0])
        assert create_call_args[0] == "create"
        assert "--name" in create_call_args
        name_idx = create_call_args.index("--name")
        assert create_call_args[name_idx + 1] == "onx-srv 'special' 42"
        assert "-v" in create_call_args
        vol_idx = create_call_args.index("-v")
        assert create_call_args[vol_idx + 1].endswith(":/data")
        assert "my world's/dir" in create_call_args[vol_idx + 1]

    @pytest.mark.asyncio
    async def test_docker_start_accepts_four_kwargs_without_type_error(
        self, tmp_path: Path
    ) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "docker-srv"
        srv_dir.mkdir()
        config = {
            "image": "itzg/minecraft-server:latest",
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )

        with (
            patch.dict(
                os.environ,
                {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
            ),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = _make_docker_command_fake(pid_ip="7890 172.17.0.5\n")
            result = await provider.start(
                server_id="docker-4-kwarg",
                config=config,
                deployment=deployment,
                launch_config=lc,
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 7890


class TestSSHProvider:
    @pytest.mark.asyncio
    async def test_ssh_start_quotes_special_characters(self) -> None:
        import shlex
        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "9999\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        config = {
            "server_dir": "/opt/minecraft/my server's/dir",
            "jar_path": "my custom 'server'.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start("srv 'test' 1", config)

        assert res.pid == 9999
        calls = [call[0][0] for call in mock_conn.run.call_args_list]
        mkdir_cmd = calls[0]
        tmux_cmd = calls[1]
        assert "mkdir -p" in mkdir_cmd
        assert shlex.quote("/opt/minecraft/my server's/dir") in mkdir_cmd
        assert "tmux new-session" in tmux_cmd
        parsed = shlex.split(tmux_cmd)
        assert parsed[0] == "tmux"
        assert parsed[1] == "new-session"

    @pytest.mark.asyncio
    async def test_ssh_start_accepts_four_kwargs_without_type_error(self) -> None:
        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5555\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        config = {
            "server_dir": "/opt/minecraft/srv1",
            "jar_path": "server.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }
        deployment = ServerDeployment(
            location_type=LocationType.SSH,
            root_path="/opt/minecraft/srv1",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start(
                server_id="ssh-4-kwarg",
                config=config,
                deployment=deployment,
                launch_config=lc,
            )

        assert res.pid == 5555

    @pytest.mark.asyncio
    async def test_remote_provider_start_quotes_all_jvm_args(self) -> None:
        import shlex

        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "7777\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        lc = LaunchConfiguration(
            java_executable="/usr/lib/jvm/java 21/bin/java",
            jvm_flags=(
                '-XX:OnOutOfMemoryError="kill -9 %p"',
                '-Dproperty="hello world"',
                "-Dcustom.msg=welcome to minecraft",
            ),
            startup_jar="server.jar",
        )
        config = {
            "server_dir": "/opt/minecraft/srv with spaces",
            "jar_path": "server.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start(
                server_id="ssh-quotes",
                config=config,
                launch_config=lc,
            )

        assert res.pid == 7777
        calls = [call[0][0] for call in mock_conn.run.call_args_list]
        tmux_cmd = calls[1]

        expected_tokens = [
            "/usr/lib/jvm/java 21/bin/java",
            '-XX:OnOutOfMemoryError="kill -9 %p"',
            '-Dproperty="hello world"',
            "-Dcustom.msg=welcome to minecraft",
            "-Xms1024M",
            "-Xmx2048M",
            "-jar",
            "server.jar",
            "nogui",
        ]
        expected_inner_cmd = " ".join(shlex.quote(t) for t in expected_tokens)
        expected_pane_cmd = (
            f"cd {shlex.quote('/opt/minecraft/srv with spaces')} && exec {expected_inner_cmd}"
        )
        expected_tmux_cmd = (
            f"tmux new-session -d -s {shlex.quote('onx-ssh-quotes')} "
            f"{shlex.quote(expected_pane_cmd)}"
        )

        assert tmux_cmd == expected_tmux_cmd

    @pytest.mark.asyncio
    async def test_ssh_get_connection_builds_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        mock_conn = MagicMock()
        mock_connect = AsyncMock(return_value=mock_conn)
        fake_asyncssh = types.ModuleType("asyncssh")
        fake_asyncssh.connect = mock_connect
        monkeypatch.setitem(sys.modules, "asyncssh", fake_asyncssh)

        provider = SSHProvider(
            host="192.168.1.50",
            port=2222,
            username="admin",
            client_keys=["/id_rsa"],
            passphrase="secret",
            known_hosts="/known_hosts",
            keepalive_seconds=45,
        )

        conn = await provider._get_connection()
        assert conn is mock_conn
        mock_connect.assert_awaited_once_with(
            host="192.168.1.50",
            port=2222,
            username="admin",
            known_hosts="/known_hosts",
            keepalive_interval=45,
            client_keys=["/id_rsa"],
            passphrase="secret",
        )
