from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.api.v1.routers.files import upload_file
from app.api.v1.schemas.server import CommandRequest
from app.core.exceptions import InvalidValueError, ProviderError
from app.modules.server.domain.value_objects import JavaArguments
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.infrastructure.config_writer import (
    write_test_server_properties,
)


# -----------------------------------------------------------------------------
# Item 1: Secret redaction in docker.py
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_docker_command_redacts_secrets_in_logs_and_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = DockerProvider()
    secret_pw = "SuperSecretP@ssword123!"

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(
        return_value=(
            b"",
            f"Error response from daemon: -e RCON_PASSWORD={secret_pw} invalid parameter".encode(),
        )
    )

    with (
        patch.object(provider, "_ensure_image", AsyncMock()),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        with pytest.raises(ProviderError) as exc_info:
            await provider.start(
                server_id="srv-redact-test",
                config={"env_vars": {"RCON_PASSWORD": secret_pw}},
            )

        # Secret must NOT appear in exception message or log output
        err_text = str(exc_info.value)
        assert secret_pw not in err_text
        assert "******" in err_text
        assert secret_pw not in caplog.text


# -----------------------------------------------------------------------------
# Item 2: Console command safety
# -----------------------------------------------------------------------------
def test_command_request_rejects_cr_lf_nul() -> None:
    # Valid commands
    assert CommandRequest(command="help").command == "help"
    assert CommandRequest(command="say hello world").command == "say hello world"
    assert CommandRequest(command="-X").command == "-X"
    assert CommandRequest(command="C-c").command == "C-c"

    # Rejection of CR, LF, NUL
    for bad_cmd in ("say hello\nstop", "help\r", "say test\0payload", "line1\r\nline2"):
        with pytest.raises(ValidationError):
            CommandRequest(command=bad_cmd)


@pytest.mark.asyncio
async def test_docker_rcon_cli_passes_double_dash_before_command() -> None:
    provider = DockerProvider()
    handle = ServerHandle(
        provider="docker",
        server_id="srv-docker-cmd",
        external_id="onx-srv-docker-cmd",
        metadata={"container_name": "onx-srv-docker-cmd"},
    )

    recorded_docker_args: list[tuple] = []
    sent_commands: list[str] = []

    async def mock_docker_cmd(*args: str, **_kwargs: Any) -> tuple[int, str]:
        recorded_docker_args.append(args)
        return 0, "Server output"

    mock_rcon = AsyncMock()
    mock_rcon.connect = AsyncMock()
    mock_rcon.close = AsyncMock()

    async def _send(cmd: str) -> str:
        sent_commands.append(cmd)
        return "Server output"

    mock_rcon.send_command = AsyncMock(side_effect=_send)

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
        patch.object(provider, "_docker_command", side_effect=mock_docker_cmd),
    ):
        await provider.execute_command(handle, "-h")

    exec_calls = [c for c in recorded_docker_args if c[0] == "exec"]
    assert exec_calls == []
    assert sent_commands == ["-h"]


# -----------------------------------------------------------------------------
# Item 3: JavaArguments JVM hook flags rejection
# -----------------------------------------------------------------------------
def test_java_arguments_rejects_hook_flags() -> None:
    forbidden = [
        "-XX:OnError=cmd",
        "-XX:OnOutOfMemoryError=kill",
        "-XX:Flags=extra.flags",
        "-XX:VMOptionsFile=/etc/passwd",
        "-javaagent:/tmp/agent.jar",
        "-agentpath:/tmp/lib.so",
        "-agentlib:jdwp",
        "-Xrunjdwp",
    ]
    for flag in forbidden:
        with pytest.raises(InvalidValueError) as exc:
            JavaArguments([flag])
        assert "Disallowed JVM flag" in str(exc.value)

    # Legitimate flags must pass
    legit = ["-Xms1024M", "-Xmx2048M", "-XX:+UseG1GC", "-Dserver.name=TestServer"]
    ja = JavaArguments(legit)
    assert ja.as_list() == legit


# -----------------------------------------------------------------------------
# Item 4: Atomic writes (config_writer.py & fs.py file mode preservation)
# -----------------------------------------------------------------------------
def test_config_writer_uses_atomic_write(tmp_path: Path) -> None:
    test_dir = str(tmp_path / ".onx" / "tests" / "test-12345")
    os.makedirs(test_dir, exist_ok=True)
    deployment = TestServerDeployment(test_id="test-12345", test_dir=test_dir)

    with patch("app.modules.server.infrastructure.fs.local_fs.write_text_atomic") as mock_atomic:
        write_test_server_properties(deployment, server_port=25565)
        # Must write server.properties and eula.txt through write_text_atomic
        assert mock_atomic.call_count == 2
        paths_written = [call.args[0] for call in mock_atomic.call_args_list]
        assert any(p.endswith("server.properties") for p in paths_written)
        assert any(p.endswith("eula.txt") for p in paths_written)


def test_fs_atomic_write_preserves_original_file_mode(tmp_path: Path) -> None:
    test_file = tmp_path / "preserve_mode.txt"
    test_file.write_text("initial content", encoding="utf-8")
    # Set custom mode (0o644)
    target_mode = 0o644
    os.chmod(test_file, target_mode)
    initial_stat = test_file.stat().st_mode

    local_fs.write_text_atomic(str(test_file), "updated atomic content")

    new_stat = test_file.stat().st_mode
    assert stat.S_IMODE(new_stat) == stat.S_IMODE(initial_stat)


# -----------------------------------------------------------------------------
# Item 5: api/deps.py get_current_user masks unexpected exceptions
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_current_user_masks_unexpected_exception() -> None:
    with patch(
        "app.api.deps.resolve_bearer_token",
        AsyncMock(side_effect=RuntimeError("Internal database connection failed with credentials")),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(db=MagicMock(), authorization="Bearer valid_token_string")

        assert exc.value.status_code == 401
        assert exc.value.detail == "Authentication failed"
        assert "Internal database connection" not in exc.value.detail


# -----------------------------------------------------------------------------
# Item 6: Files API upload streaming and size limit
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_files_upload_oversized_returns_413_and_cleans_up(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv-oversized"
    server_dir.mkdir()

    mock_query_bus = AsyncMock()
    mock_server = MagicMock()
    mock_server.deployment.root_path = str(server_dir)
    mock_query_bus.ask = AsyncMock(return_value=mock_server)

    upload = UploadFile(filename="huge.bin", file=io.BytesIO(b"0123456789" * 100))

    with (
        patch("app.api.v1.routers.files.AppSettings") as settings_cls,
        patch(
            "app.api.v1.routers.files._resolve_server_file_path",
            return_value=(server_dir, server_dir / "huge.bin", "huge.bin", False, False),
        ),
    ):
        settings_cls.return_value.files_max_upload_size_mb = 0.00001
        with pytest.raises(HTTPException) as exc:
            await upload_file(
                server_id="s1",
                path="",
                file=upload,
                query_bus=mock_query_bus,
                _current_user={"permissions": ["admin:full"]},
            )

        assert exc.value.status_code == 413
        assert not (server_dir / "huge.bin").exists()
        assert list(server_dir.glob("*.tmp")) == []
