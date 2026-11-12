from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.api.errors import check_command_result
from app.core.command_bus import CommandResult
from app.core.exceptions import (
    GuardConfigurationError,
    MCSError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ServerNotFoundError,
)
from app.core.persistence.db import database
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import ServerMode
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.application.mode_guard import ensure_versioning_allowed


def _make_server(server_id: str, mode: ServerMode) -> Server:
    server = object.__new__(Server)
    server._id = ServerId(server_id)
    server._mode = mode
    return server


@pytest.mark.asyncio
async def test_no_source_or_multiple_sources_raises_guard_configuration_error() -> None:
    # 1. No source provided
    with pytest.raises(GuardConfigurationError):
        await ensure_versioning_allowed("srv-1")

    # 2. Multiple sources: server aggregate + session
    server = _make_server("srv-1", ServerMode.ADVANCED)
    mock_session = AsyncMock()
    with pytest.raises(GuardConfigurationError):
        await ensure_versioning_allowed(server, session=mock_session)

    # 3. Multiple sources: server_repo + session
    mock_repo = AsyncMock()
    with pytest.raises(GuardConfigurationError):
        await ensure_versioning_allowed("srv-1", server_repo=mock_repo, session=mock_session)


@pytest.mark.asyncio
async def test_repo_returns_none_raises_not_found_error() -> None:
    mock_repo = AsyncMock()
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Server 'srv-missing' not found"):
        await ensure_versioning_allowed("srv-missing", server_repo=mock_repo)


@pytest.mark.asyncio
async def test_repo_raises_server_not_found_raises_not_found_error() -> None:
    mock_repo = AsyncMock()
    mock_repo.get.side_effect = ServerNotFoundError("Server not found")

    with pytest.raises(NotFoundError, match="Server 'srv-missing' not found"):
        await ensure_versioning_allowed("srv-missing", server_repo=mock_repo)


@pytest.mark.asyncio
async def test_repo_raises_runtime_error_propagates_same_error() -> None:
    mock_repo = AsyncMock()
    mock_repo.get.side_effect = RuntimeError("database connection failed")

    with pytest.raises(RuntimeError, match="database connection failed"):
        await ensure_versioning_allowed("srv-error", server_repo=mock_repo)


@pytest.mark.asyncio
async def test_guard_with_repo_does_not_call_global_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raising_factory(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Global database.session_factory was invoked unexpectedly")

    monkeypatch.setattr(database, "_session_factory", raising_factory)

    mock_repo = AsyncMock()
    mock_repo.get.return_value = _make_server("srv-adv", ServerMode.ADVANCED)

    # Guard must succeed with injected repository without touching the global session factory
    await ensure_versioning_allowed("srv-adv", server_repo=mock_repo)


@pytest.mark.asyncio
async def test_server_aggregate_simple_blocks_and_advanced_passes() -> None:
    server_simple = _make_server("srv-simple", ServerMode.SIMPLE)
    with pytest.raises(ServerModeVersioningDisabledError):
        await ensure_versioning_allowed(server_simple)

    server_advanced = _make_server("srv-adv", ServerMode.ADVANCED)
    # Advanced server aggregate must pass without error
    await ensure_versioning_allowed(server_advanced)


def test_check_command_result_guard_configuration_error_maps_to_500() -> None:
    cmd_result = CommandResult(
        success=False,
        error="Mode guard misconfigured",
        error_code="GUARD_CONFIGURATION_ERROR",
    )
    with pytest.raises(MCSError) as exc_info:
        check_command_result(cmd_result)

    assert exc_info.value.http_status == 500
    assert exc_info.value.code == "GUARD_CONFIGURATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc_cls", "message"),
    [
        (Exception, "record not found in storage"),
        (RuntimeError, "table servers not found"),
    ],
)
async def test_repo_raising_unrelated_exception_propagates_without_mapping_to_not_found(
    exc_cls: type[Exception], message: str
) -> None:
    mock_repo = AsyncMock()
    mock_repo.get.side_effect = exc_cls(message)

    with pytest.raises(exc_cls) as exc_info:
        await ensure_versioning_allowed("srv-err", server_repo=mock_repo)

    assert not isinstance(exc_info.value, NotFoundError)
    assert str(exc_info.value) == message
