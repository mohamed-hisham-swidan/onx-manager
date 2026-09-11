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
    async def test_docker_execute_command_fallback_when_rcon_unavailable(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-fallback",
            external_id="onx-srv-fallback",
        )

        with (
            patch.object(provider, "_resolve_rcon_credentials", AsyncMock(return_value=None)),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.return_value = (0, "Output from rcon-cli\n")
            out = await provider.execute_command(handle, "help")

        mock_docker.assert_awaited_once_with(
            "exec", "onx-srv-fallback", "rcon-cli", "help"
        )
        assert "Output from rcon-cli" in out

    @pytest.mark.asyncio
    async def test_docker_execute_command_fallback_on_rcon_connection_error(self) -> None:
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
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.return_value = (0, "Fallback cli response\n")
            out = await provider.execute_command(handle, "time set day")

        mock_docker.assert_awaited_once_with(
            "exec", "onx-srv-conn-fail", "rcon-cli", "time set day"
        )
        assert "Fallback cli response" in out

    @pytest.mark.asyncio
    async def test_docker_execute_command_double_failure_raises_provider_error(self) -> None:
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
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
            pytest.raises(ProviderError) as exc_info,
        ):
            mock_docker.return_value = (
                127,
                "OCI runtime exec failed: exec: rcon-cli: executable file not found in $PATH",
            )
            await provider.execute_command(handle, "whitelist reload")

        err_msg = str(exc_info.value)
        assert "Failed to execute command on container onx-srv-double-fail" in err_msg
        assert "executable file not found" in err_msg


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
            patch.object(
                provider,
                "_docker_command",
                AsyncMock(return_value=(0, "")),
            ) as mock_docker,
        ):
            await provider.stop(handle, force=False)

        mock_docker.assert_awaited_once_with("stop", "-t", "30", "onx-srv-fail-stop")

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
        ):
            await provider.stop(handle, force=False)

        mock_docker.assert_awaited_once_with("stop", "-t", "30", "onx-srv-timeout-stop")


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
