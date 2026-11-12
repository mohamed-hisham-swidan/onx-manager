from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.modules.versioning.application.mode_guard as mode_guard_module
from app.core.command_bus import CommandResult
from app.core.persistence.db import database
from tests.application.test_server_mode_command_guard import CASE_IDS, CASES, COMMANDS


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "handler_name", "command_factory"), CASES, ids=CASE_IDS)
async def test_one_session_factory_call_per_handle(
    module_name: str,
    handler_name: str,
    command_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I15: Exactly one database session per handle() on production path without injected repo.

    The guard receives the exact same session opened by the handler.
    """
    module = importlib.import_module(f"{COMMANDS}.{module_name}")
    handler_class = getattr(module, handler_name)
    handler = handler_class()

    base_factory = database._session_factory
    assert base_factory is not None, "database._session_factory must be initialized by fixture"

    created_sessions: list[Any] = []

    def counting_factory(*args: Any, **kwargs: Any) -> Any:
        session = base_factory(*args, **kwargs)
        created_sessions.append(session)
        return session

    monkeypatch.setattr(database, "_session_factory", counting_factory)

    guard_sessions: list[Any] = []

    async def spy_guard(_server_or_id: Any, **kwargs: Any) -> None:
        guard_sessions.append(kwargs.get("session"))

    monkeypatch.setattr(mode_guard_module, "ensure_versioning_allowed", spy_guard)
    monkeypatch.setattr(handler, "_execute", AsyncMock(return_value=CommandResult(success=True)))

    cmd = command_factory()
    result = await handler.handle(cmd)

    assert result.success is True
    # I15 assertion: exactly one session factory call on the direct path
    assert len(created_sessions) == 1, (
        f"{handler_name} opened {len(created_sessions)} sessions, expected exactly 1"
    )
    # The guard received the identical session object created by the handler
    assert len(guard_sessions) == 1
    assert guard_sessions[0] is created_sessions[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "handler_name", "command_factory"), CASES, ids=CASE_IDS)
async def test_guard_before_first_side_effect(
    module_name: str,
    handler_name: str,
    command_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I16: Guard is evaluated before the first side effect in all 21 handlers."""
    module = importlib.import_module(f"{COMMANDS}.{module_name}")
    handler_class = getattr(module, handler_name)
    handler = handler_class()

    execution_order: list[str] = []

    async def spy_guard(_server_or_id: Any, **_kwargs: Any) -> None:
        execution_order.append("guard")

    async def spy_execute(*_args: Any, **_kwargs: Any) -> CommandResult:
        execution_order.append("_execute")
        return CommandResult(success=True)

    monkeypatch.setattr(mode_guard_module, "ensure_versioning_allowed", spy_guard)
    monkeypatch.setattr(handler, "_execute", spy_execute)

    cmd = command_factory()
    result = await handler.handle(cmd)

    assert result.success is True
    # I16 assertion: guard must precede _execute
    assert execution_order == ["guard", "_execute"], (
        f"{handler_name} execution order was {execution_order}, expected ['guard', '_execute']"
    )
