from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import InvalidValueError
from app.modules.exposure.domain.aggregate import DENY_LIST_PORTS, ServerExposure
from app.modules.exposure.domain.value_objects import ExposureMethod
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerRuntimeStatus,
    get_dynamic_local_ip,
)
from app.modules.server.infrastructure.providers.docker import (
    DockerProvider,
    normalize_host_path,
)


class TestDockerNetworkModel:
    """Decision 6: Bridge network model and host port publishing."""

    @pytest.mark.asyncio
    async def test_default_bridge_network_and_game_port_published(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25565,
            "container_port": 25565,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (0, ""),  # create
                (0, ""),  # start
                (0, "1234\n"),  # inspect pid
            ]
            result = await provider.start(server_id="net-test-1", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.address in ("127.0.0.1", get_dynamic_local_ip())
        assert result.port == 25565
        assert result.metadata["network"] == "bridge"

        create_args = list(mock_docker.call_args_list[0][0])
        assert "--network" in create_args
        assert create_args[create_args.index("--network") + 1] == "bridge"
        assert "-p" in create_args
        assert create_args[create_args.index("-p") + 1] == "25565:25565"

    @pytest.mark.asyncio
    async def test_container_ip_dynamically_collected_on_start_and_get_address(
        self,
    ) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25565,
            "container_port": 25565,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (0, ""),  # create
                (0, ""),  # start
                (0, "1234 172.17.0.5\n"),  # inspect pid and network ip
            ]
            result = await provider.start(server_id="ip-test-1", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.address == "172.17.0.5"
        assert result.port == 25565

        handle = ServerHandle(
            provider="docker",
            server_id="ip-test-1",
            external_id="onx-ip-test-1",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "172.17.0.5\n")
            live_ip = await provider.get_address(handle)
            assert live_ip == "172.17.0.5"

    @pytest.mark.asyncio
    async def test_custom_network_configuration(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25565,
            "network": "onx-custom-bridge",
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            result = await provider.start(server_id="net-test-2", config=config)

        assert result.metadata["network"] == "onx-custom-bridge"
        create_args = list(mock_docker.call_args_list[0][0])
        assert "--network" in create_args
        assert create_args[create_args.index("--network") + 1] == "onx-custom-bridge"

    @pytest.mark.asyncio
    async def test_custom_host_ip_binding(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "host_ip": "127.0.0.1",
            "port": 25565,
            "container_port": 25565,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(server_id="net-test-3", config=config)

        create_args = list(mock_docker.call_args_list[0][0])
        assert "-p" in create_args
        assert create_args[create_args.index("-p") + 1] == "127.0.0.1:25565:25565"

    @pytest.mark.asyncio
    async def test_protocol_variants(self) -> None:
        provider = DockerProvider()

        # UDP protocol (e.g. Bedrock)
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(
                server_id="udp-srv",
                config={"port": 19132, "container_port": 19132, "protocol": "udp"},
            )
            create_args = list(mock_docker.call_args_list[0][0])
            assert "-p" in create_args
            assert create_args[create_args.index("-p") + 1] == "19132:19132/udp"

        # Both TCP and UDP
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(
                server_id="both-srv",
                config={"port": 25565, "container_port": 25565, "protocol": "both"},
            )
            create_args = list(mock_docker.call_args_list[0][0])
            p_indices = [i for i, val in enumerate(create_args) if val == "-p"]
            published = [create_args[i + 1] for i in p_indices]
            assert "25565:25565/tcp" in published
            assert "25565:25565/udp" in published

    @pytest.mark.asyncio
    async def test_container_port_auto_detection_from_server_properties(
        self, tmp_path: Path
    ) -> None:
        srv_dir = tmp_path / "srv-props"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("server-port=25570\n", encoding="utf-8")

        provider = DockerProvider()
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            result = await provider.start(
                server_id="props-srv",
                config={"port": 25570, "server_dir": str(srv_dir)},
            )

        assert result.metadata["container_port"] == 25570
        create_args = list(mock_docker.call_args_list[0][0])
        assert "-p" in create_args
        assert create_args[create_args.index("-p") + 1] == "25570:25570"

    @pytest.mark.asyncio
    async def test_itzg_image_injects_server_port_env_var(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "itzg/minecraft-server:latest",
            "port": 25566,
            "container_port": 25566,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(server_id="itzg-srv", config=config)

        create_args = list(mock_docker.call_args_list[0][0])
        assert "-e" in create_args
        e_indices = [i for i, val in enumerate(create_args) if val == "-e"]
        env_pairs = [create_args[i + 1] for i in e_indices]
        assert "SERVER_PORT=25566" in env_pairs


class TestDockerRconLoopbackSecurity:
    """Confirm RCON loopback binding is strictly preserved and cannot be exposed."""

    @pytest.mark.asyncio
    async def test_rcon_port_strictly_loopback_only(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25565,
            "rcon_port": 25575,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(server_id="sec-srv-1", config=config)

        create_args = list(mock_docker.call_args_list[0][0])
        p_indices = [i for i, val in enumerate(create_args) if val == "-p"]
        published = [create_args[i + 1] for i in p_indices]

        # Exactly two ports published: game port and RCON port
        assert "25565:25565" in published
        assert "127.0.0.1:25575:25575" in published

        # Assert no RCON port is published without the loopback prefix
        for pub in published:
            if "25575" in pub:
                assert pub.startswith("127.0.0.1:"), f"RCON port published insecurely: {pub}"

    @pytest.mark.asyncio
    async def test_rcon_loopback_preserved_even_with_custom_host_ip(self) -> None:
        provider = DockerProvider()
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "host_ip": "192.168.1.100",
            "port": 25565,
            "rcon_port": 25575,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(server_id="sec-srv-2", config=config)

        create_args = list(mock_docker.call_args_list[0][0])
        p_indices = [i for i, val in enumerate(create_args) if val == "-p"]
        published = [create_args[i + 1] for i in p_indices]

        # Game port binds to host_ip, but RCON port MUST stay strictly 127.0.0.1
        assert "192.168.1.100:25565:25565" in published
        assert "127.0.0.1:25575:25575" in published
        assert "192.168.1.100:25575:25575" not in published

    @pytest.mark.asyncio
    async def test_rcon_disabled_no_rcon_port_published(self, tmp_path: Path) -> None:
        srv_dir = tmp_path / "srv-no-rcon"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("enable-rcon=false\n", encoding="utf-8")

        provider = DockerProvider()
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(
                server_id="no-rcon-srv",
                config={"port": 25565, "server_dir": str(srv_dir)},
            )

        create_args = list(mock_docker.call_args_list[0][0])
        p_indices = [i for i, val in enumerate(create_args) if val == "-p"]
        published = [create_args[i + 1] for i in p_indices]
        assert len(published) == 1
        assert published[0] == "25565:25565"


class TestDockerWindowsPolicyAndPathNormalization:
    """Decision 7: Windows WSL2 backend policy, OSType gating, and path normalization."""

    def test_normalize_host_path_posix(self) -> None:
        posix_path = "/var/minecraft/servers/srv1"
        normalized = normalize_host_path(posix_path)
        assert normalized == "/var/minecraft/servers/srv1"

    def test_normalize_host_path_windows_drive_backslash(self) -> None:
        win_path = r"C:\minecraft\servers\paper-server"
        normalized = normalize_host_path(win_path)
        assert normalized == "C:/minecraft/servers/paper-server"

    def test_normalize_host_path_windows_drive_forward_slash(self) -> None:
        win_path = "C:/minecraft/servers/paper-server"
        normalized = normalize_host_path(win_path)
        assert normalized == "C:/minecraft/servers/paper-server"

    def test_normalize_host_path_windows_mixed_slashes(self) -> None:
        mixed_path = r"D:\minecraft/servers\data/world"
        normalized = normalize_host_path(mixed_path)
        assert normalized == "D:/minecraft/servers/data/world"

    def test_normalize_host_path_empty(self) -> None:
        assert normalize_host_path("") == ""

    def test_normalize_host_path_simulated_win32(self) -> None:
        with (
            patch.object(sys, "platform", "win32"),
            patch("pathlib.Path.resolve") as mock_resolve,
        ):
            mock_resolve.return_value.as_posix.return_value = "C:/mock/resolved/path"
            res = normalize_host_path(r"C:\mock\resolved\path")
            assert res == "C:/mock/resolved/path"

    @pytest.mark.asyncio
    async def test_docker_start_windows_path_volume_mount(self) -> None:
        provider = DockerProvider()
        win_srv_dir = r"C:\minecraft\servers\win-srv"
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=win_srv_dir,
            startup_jar="paper.jar",
        )

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            result = await provider.start(
                server_id="win-srv",
                deployment=deployment,
                config={"port": 25565},
            )

        assert result.metadata["server_dir"] == "C:/minecraft/servers/win-srv"
        create_args = list(mock_docker.call_args_list[0][0])
        assert "-v" in create_args
        assert create_args[create_args.index("-v") + 1] == "C:/minecraft/servers/win-srv:/data"

    @pytest.mark.asyncio
    async def test_docker_start_windows_startup_jar_name_extraction(self) -> None:
        provider = DockerProvider()
        launch_config = LaunchConfiguration(
            startup_jar=r"C:\minecraft\servers\win-srv\custom-paper.jar"
        )

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            await provider.start(
                server_id="win-jar-srv",
                launch_config=launch_config,
                config={"port": 25565},
            )

        create_args = list(mock_docker.call_args_list[0][0])
        assert "-jar" in create_args
        assert create_args[create_args.index("-jar") + 1] == "/data/custom-paper.jar"


class TestDockerPingDiagnostics:
    """Actionable diagnostic error messages on ping() failures (Decision 7)."""

    @pytest.mark.asyncio
    async def test_ping_linux_containers_mode_success(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "linux\n")
            ok, msg = await provider.ping_detailed()
            assert ok is True
            assert msg == "ok"
            assert await provider.ping() is True
            assert provider.last_ping_error == ""

    @pytest.mark.asyncio
    async def test_ping_windows_containers_mode_actionable_guidance(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "windows\n")
            ok, msg = await provider.ping_detailed()
            assert ok is False
            assert "Docker daemon is running in 'windows' containers mode" in msg
            assert "Switch to Linux containers" in msg
            assert await provider.ping() is False
            assert provider.last_ping_error == msg

    @pytest.mark.asyncio
    async def test_ping_daemon_unreachable_diagnostics(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (1, "error during connect")
            ok, msg = await provider.ping_detailed()
            assert ok is False
            assert "Docker daemon is unreachable" in msg
            assert "Ensure Docker Desktop or dockerd is running" in msg
            assert await provider.ping() is False
            assert provider.last_ping_error == msg

    @pytest.mark.asyncio
    async def test_ping_command_exception_diagnostics(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.side_effect = FileNotFoundError("docker binary not found")
            ok, msg = await provider.ping_detailed()
            assert ok is False
            assert "Docker daemon is unreachable" in msg
            assert "docker binary not found" in msg
            assert await provider.ping() is False
            assert provider.last_ping_error == msg


class TestExposureSupervisorCompatibility:
    """Decision 6: Exposure supervisor integration with zero exposure code changes."""

    @pytest.mark.asyncio
    async def test_docker_deployment_result_matches_exposure_binding_assumptions(self) -> None:
        provider = DockerProvider()
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [(0, ""), (0, ""), (0, "1234\n")]
            result = await provider.start(
                server_id="exp-srv",
                config={"port": 25565, "container_port": 25565},
            )

        # Exposure daemons (playit.gg, cloudflared, UPnP) connect to host loopback
        # or primary host interface
        assert result.address in ("127.0.0.1", get_dynamic_local_ip())
        assert result.port == 25565

    def test_exposure_target_matches_server_port_and_blocks_rcon(self) -> None:
        exposure = ServerExposure(server_id="exp-srv", method=ExposureMethod.PLAYIT)
        target = exposure.enable(server_port=25565, target_id="target-1")

        # Playit/Cloudflare target local_port matches server port
        assert target.local_port == 25565

        # Attempting to expose RCON port on a game server (25565) fails port validation
        with pytest.raises(InvalidValueError, match="must equal the server's game port"):
            exposure.create_target(
                local_port=25575,
                server_port=25565,
                target_id="rcon-leak-attempt",
            )

        # Even if a server configured port 25575, RCON port is blocked by DENY_LIST_PORTS
        assert 25575 in DENY_LIST_PORTS
        with pytest.raises(InvalidValueError, match="deny-list"):
            exposure.create_target(
                local_port=25575,
                server_port=25575,
                target_id="rcon-deny-attempt",
            )
