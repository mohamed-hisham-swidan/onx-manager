from __future__ import annotations

import struct
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.modules.monitoring.infrastructure.rcon_client import (
    PACKET_AUTH_RESPONSE,
    PACKET_RESPONSE,
    AsyncRCONClient,
    AuthenticationError,
    RCONError,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    LocationType,
    RuntimeInfo,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
)
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.services.backup_orchestrator import BackupSaga


def _pack_packet(req_id: int, ptype: int, body: str) -> tuple[bytes, bytes]:
    """Helper returning header (12 bytes) and body bytes (length - 8 bytes)."""
    payload = body.encode("utf-8") + b"\x00\x00"
    length = 8 + len(payload)
    header = struct.pack("<iii", length, req_id, ptype)
    return header, payload


class TestAsyncRCONClient:
    @pytest.mark.asyncio
    async def test_async_rcon_success(self) -> None:
        client = AsyncRCONClient(host="127.0.0.1", port=25575, password="test_secret")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        auth_hdr, auth_body = _pack_packet(2, PACKET_AUTH_RESPONSE, "")
        cmd_hdr, cmd_body = _pack_packet(3, PACKET_RESPONSE, "There are 2 players online")

        mock_reader.readexactly.side_effect = [
            auth_hdr,
            auth_body,
            cmd_hdr,
            cmd_body,
        ]

        with patch("asyncio.open_connection", AsyncMock(return_value=(mock_reader, mock_writer))):
            await client.connect()
            resp = await client.send_command("list")
            await client.close()

        assert resp == "There are 2 players online"
        assert mock_writer.write.call_count == 2
        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_rcon_auth_failure(self) -> None:
        client = AsyncRCONClient(host="127.0.0.1", port=25575, password="wrong_password")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()

        # Auth failure returns resp_id = -1
        fail_hdr, fail_body = _pack_packet(-1, PACKET_AUTH_RESPONSE, "")
        mock_reader.readexactly.side_effect = [fail_hdr, fail_body]

        with (
            patch("asyncio.open_connection", AsyncMock(return_value=(mock_reader, mock_writer))),
            pytest.raises(AuthenticationError, match="RCON authentication failed"),
        ):
            await client.connect()

    @pytest.mark.asyncio
    async def test_async_rcon_timeout(self) -> None:
        client = AsyncRCONClient(host="127.0.0.1", port=25575, password="any", timeout=0.1)

        with (
            patch(
                "asyncio.open_connection",
                AsyncMock(side_effect=TimeoutError("Connection timed out")),
            ),
            pytest.raises(RCONError, match="Failed to connect to 127.0.0.1:25575"),
        ):
            await client.connect()

    @pytest.mark.asyncio
    async def test_async_rcon_response_mismatch(self) -> None:
        client = AsyncRCONClient(host="127.0.0.1", port=25575, password="secret")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()

        auth_hdr, auth_body = _pack_packet(2, PACKET_AUTH_RESPONSE, "")
        # Response with unexpected request-id 999
        cmd_hdr, cmd_body = _pack_packet(999, PACKET_RESPONSE, "Unexpected")

        mock_reader.readexactly.side_effect = [auth_hdr, auth_body, cmd_hdr, cmd_body]

        with (
            patch("asyncio.open_connection", AsyncMock(return_value=(mock_reader, mock_writer))),
            pytest.raises(RCONError, match="RCON response mismatch"),
        ):
            await client.connect()
            await client.send_command("list")


class TestDockerProviderRCONExecution:
    @pytest.mark.asyncio
    async def test_docker_execute_command_rcon_success(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-rcon",
            external_id="onx-srv-rcon",
        )

        mock_rcon = AsyncMock()
        mock_rcon.connect = AsyncMock()
        mock_rcon.send_command = AsyncMock(return_value="Command executed via RCON")
        mock_rcon.close = AsyncMock()

        with (
            patch.object(
                provider,
                "_resolve_rcon_credentials",
                AsyncMock(return_value=("127.0.0.1", 25575, "secret123")),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                return_value=mock_rcon,
            ),
        ):
            output = await provider.execute_command(handle, "/say hello world")

        assert output == "Command executed via RCON"
        # Verifies leading slash was stripped for pure command
        mock_rcon.send_command.assert_awaited_once_with("say hello world")
        mock_rcon.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_docker_execute_command_auth_failure_no_password_leak(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-auth-fail",
            external_id="onx-srv-auth-fail",
        )

        mock_rcon = AsyncMock()
        mock_rcon.connect = AsyncMock(
            side_effect=AuthenticationError("RCON authentication failed")
        )

        with (
            patch.object(
                provider,
                "_resolve_rcon_credentials",
                AsyncMock(return_value=("127.0.0.1", 25575, "super_sensitive_password_123")),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                return_value=mock_rcon,
            ),
            pytest.raises(ProviderError) as exc_info,
        ):
            await provider.execute_command(handle, "list")

        # Must raise ProviderError and not leak plaintext password
        err_msg = str(exc_info.value)
        assert "RCON authentication failed" in err_msg
        assert "super_sensitive_password_123" not in err_msg

    @pytest.mark.asyncio
    async def test_docker_execute_command_no_rcon_cli_when_rcon_unavailable(self) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-fallback",
            external_id="onx-srv-fallback",
        )

        with (
            patch.object(provider, "_resolve_rcon_credentials", AsyncMock(return_value=None)),
            patch.object(
                provider, "status", AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
            ),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
            pytest.raises(ProviderError) as exc_info,
        ):
            await provider.execute_command(handle, "help")

        mock_docker.assert_not_called()
        assert "RCON is not ready yet" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_docker_execute_command_rcon_connection_error_returns_friendly_message(
        self,
    ) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-conn-fail",
            external_id="onx-srv-conn-fail",
        )

        mock_rcon = AsyncMock()
        mock_rcon.connect = AsyncMock(side_effect=RCONError("Connection refused"))

        with (
            patch.object(
                provider,
                "_resolve_rcon_credentials",
                AsyncMock(return_value=("127.0.0.1", 25575, "secret")),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                return_value=mock_rcon,
            ),
            patch.object(
                provider, "status", AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
            ),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
            pytest.raises(ProviderError) as exc_info,
        ):
            await provider.execute_command(handle, "time set day")

        mock_docker.assert_not_called()
        err_msg = str(exc_info.value)
        assert "Server console is still starting up" in err_msg
        assert "rcon-cli" not in err_msg

    @pytest.mark.asyncio
    async def test_docker_execute_command_stopped_container_raises_provider_error(self) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-double-fail",
            external_id="onx-srv-double-fail",
        )

        mock_rcon = AsyncMock()
        mock_rcon.connect = AsyncMock(side_effect=RCONError("Connection refused"))

        with (
            patch.object(
                provider,
                "_resolve_rcon_credentials",
                AsyncMock(return_value=("127.0.0.1", 25575, "secret")),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                return_value=mock_rcon,
            ),
            patch.object(
                provider, "status", AsyncMock(return_value=ServerRuntimeStatus.STOPPED)
            ),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
            pytest.raises(ProviderError) as exc_info,
        ):
            await provider.execute_command(handle, "whitelist reload")

        mock_docker.assert_not_called()
        err_msg = str(exc_info.value)
        assert "not running" in err_msg
        assert "rcon-cli" not in err_msg


class TestDockerProviderGracefulStop:
    @pytest.mark.asyncio
    async def test_docker_stop_rcon_success_avoids_docker_stop(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-clean-stop",
            external_id="onx-srv-clean-stop",
        )

        with (
            patch.object(provider, "execute_command", AsyncMock(return_value="")) as mock_exec,
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=True)),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            await provider.stop(handle, force=False)

        mock_exec.assert_awaited_once_with(handle, "stop")
        # Container stopped cleanly via RCON; docker stop must NOT be called
        mock_docker.assert_not_called()

    @pytest.mark.asyncio
    async def test_docker_stop_rcon_failure_falls_back_to_docker_stop(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-fail-stop",
            external_id="onx-srv-fail-stop",
        )

        with (
            patch.object(
                provider,
                "execute_command",
                AsyncMock(side_effect=ProviderError("docker", "execute_command", "failed")),
            ),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=True)),
            patch.object(
                provider,
                "_docker_command",
                AsyncMock(return_value=(0, "")),
            ) as mock_docker,
        ):
            await provider.stop(handle, force=False)

        mock_docker.assert_any_await("stop", "-t", "30", "onx-srv-fail-stop")

    @pytest.mark.asyncio
    async def test_docker_stop_timeout_falls_back_to_docker_stop(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-timeout-stop",
            external_id="onx-srv-timeout-stop",
        )

        with (
            patch.object(provider, "execute_command", AsyncMock(return_value="")),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=False)),
            patch.object(
                provider,
                "_docker_command",
                AsyncMock(return_value=(0, "")),
            ) as mock_docker,
            pytest.raises(ProviderError, match="still running after docker stop"),
        ):
            await provider.stop(handle, force=False)

        mock_docker.assert_any_await("stop", "-t", "30", "onx-srv-timeout-stop")


class TestBackupSaveAllWithDockerProvider:
    @pytest.mark.asyncio
    async def test_backup_save_all_docker_rcon_success(self) -> None:
        saga_orchestrator = AsyncMock()
        saga = BackupSaga(saga_orchestrator)

        server_id = ServerId("srv-backup-docker")
        backup_id = BackupJobId("bkp-123")

        mock_server = MagicMock(spec=Server)
        mock_server.id = server_id
        mock_server.status = ServerStatus.RUNNING
        mock_server.runtime = RuntimeInfo(
            provider="docker",
            external_id="onx-srv-backup-docker",
        )
        mock_server.deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path="/tmp/test_backup",
        )

        mock_docker_provider = AsyncMock()
        mock_docker_provider.console.side_effect = [
            ["[12:00:00 INFO]: Preparing spawn area"],  # baseline snapshot
            [
                "[12:00:00 INFO]: Preparing spawn area",
                "[12:00:01 INFO]: Saved the game",
            ],  # poll matches _SAVE_CONFIRMED_RE
        ]
        mock_docker_provider.execute_command.return_value = "Saved the game"

        with (
            patch.object(saga, "_server_is_running", AsyncMock(return_value=True)),
            patch.object(saga, "_load_server", AsyncMock(return_value=mock_server)),
            patch(
                "app.modules.server.infrastructure.providers.provider_factory.get",
                return_value=mock_docker_provider,
            ),
        ):
            save_fn = saga._save_world(backup_id, server_id)
            await save_fn()

        mock_docker_provider.execute_command.assert_awaited_once_with(
            ANY, "save-all"
        )
        handle_arg = mock_docker_provider.execute_command.call_args[0][0]
        assert handle_arg.provider == "docker"
        assert handle_arg.server_id == str(server_id)
        assert handle_arg.external_id == "onx-srv-backup-docker"


class TestMultiServerDockerRCONIsolation:
    @pytest.mark.asyncio
    async def test_multi_server_rcon_ports_avoid_collision_and_route_commands(
        self, tmp_path
    ) -> None:
        import os

        srv1_dir = tmp_path / "srv-1"
        srv2_dir = tmp_path / "srv-2"
        srv1_dir.mkdir()
        srv2_dir.mkdir()
        (srv1_dir / "server.properties").write_text(
            "server-port=25565\nenable-rcon=true\nrcon.port=25575\nrcon.password=pw_srv1\n",
            encoding="utf-8",
        )
        (srv2_dir / "server.properties").write_text(
            "server-port=25566\nenable-rcon=true\nrcon.port=25575\nrcon.password=pw_srv2\n",
            encoding="utf-8",
        )

        provider = DockerProvider()
        captured_creates: list[list[str]] = []
        busy_ports: set[int] = set()
        started_containers: set[str] = set()

        async def fake_docker_cmd(*args: str, **_kwargs: object) -> tuple[int, str]:
            if args[0] == "inspect" and "--format" in args:
                fmt = args[args.index("--format") + 1]
                if "{{json .}}" in fmt:
                    target = args[-1]
                    if target == "onx-srv-2" and target in started_containers:
                        return (
                            0,
                            '{"NetworkSettings":{"Ports":'
                            '{"25575/tcp":[{"HostIp":"127.0.0.1","HostPort":"25576"}]}}}',
                        )
                    return (1, "")
                return (0, "12345 172.17.0.2")
            if args[0] == "create":
                captured_creates.append(list(args))
                return (0, "cid-new")
            if args[0] == "start":
                started_containers.add(args[1])
                # Simulate Server 1 binding 25575 once started
                if args[1] == "onx-srv-1":
                    busy_ports.add(25575)
                return (0, "")
            return (0, "")

        with (
            patch.dict(
                os.environ,
                {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
            ),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", side_effect=fake_docker_cmd),
            patch(
                "app.modules.server.infrastructure.providers.docker.prepare_data_ownership",
                AsyncMock(),
            ),
            patch(
                "app.modules.server.infrastructure.providers.docker.is_loopback_port_free",
                side_effect=lambda p: p not in busy_ports,
            ),
        ):
            res1 = await provider.start(
                server_id="srv-1",
                config={"port": 25565, "server_dir": str(srv1_dir)},
            )
            res2 = await provider.start(
                server_id="srv-2",
                config={"port": 25566, "server_dir": str(srv2_dir)},
            )

        assert res1.port == 25565
        assert res1.metadata["rcon_port"] == 25575
        assert res2.port == 25566
        assert res2.metadata["rcon_port"] == 25576

        srv2_create = captured_creates[1]
        srv2_ports = [srv2_create[i + 1] for i, v in enumerate(srv2_create) if v == "-p"]
        assert "25566:25566" in srv2_ports
        assert "127.0.0.1:25576:25575" in srv2_ports
        assert "127.0.0.1:25575:25575" not in srv2_ports

        # Cache must store host port 25576, NOT container port 25575 from server.properties
        assert provider._rcon_cache["srv-2"]["port"] == 25576

        # Route RCON commands and graceful stop to each server's own host RCON port
        mock_rcon = AsyncMock()
        mock_rcon.connect = AsyncMock()
        mock_rcon.send_command = AsyncMock(return_value="ok")
        mock_rcon.close = AsyncMock()

        created_clients: list[tuple[str, int, str]] = []

        def make_client(host: str, port: int, password: str, **_kw: object) -> AsyncMock:
            created_clients.append((host, port, password))
            return mock_rcon

        with (
            patch(
                "app.modules.server.infrastructure.providers.docker.AsyncRCONClient",
                side_effect=make_client,
            ),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=True)),
        ):
            await provider.execute_command(
                ServerHandle(provider="docker", server_id="srv-1", external_id="onx-srv-1"),
                "list",
            )
            await provider.execute_command(
                ServerHandle(provider="docker", server_id="srv-2", external_id="onx-srv-2"),
                "list",
            )
            await provider.stop(
                ServerHandle(provider="docker", server_id="srv-2", external_id="onx-srv-2"),
                force=False,
            )

        assert ("127.0.0.1", 25575, "pw_srv1") in created_clients
        assert ("127.0.0.1", 25576, "pw_srv2") in created_clients
        mock_rcon.send_command.assert_any_await("stop")

        # After simulated backend restart (empty _rcon_cache), inspect still resolves 25576
        provider._rcon_cache.clear()
        with (
            patch.object(provider, "_docker_command", side_effect=fake_docker_cmd),
        ):
            creds = await provider.resolve_rcon_endpoint(
                ServerHandle(
                    provider="docker",
                    server_id="srv-2",
                    external_id="onx-srv-2",
                    metadata={"server_dir": str(srv2_dir)},
                )
            )
        assert creds == ("127.0.0.1", 25576, "pw_srv2")
