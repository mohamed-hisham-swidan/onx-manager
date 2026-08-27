from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.health.application import (
    EvaluateHealthCommand,
    EvaluateHealthHandler,
)
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.value_objects import HealthStatusEnum

pytestmark = pytest.mark.asyncio


def _mock_session():
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock()
    return s


def _prepare_db():
    old = database._session_factory
    database._session_factory = _mock_session()
    return old


def _restore_db(old):
    database._session_factory = old


class TestEvaluateHealthHandler:
    async def test_evaluate_new_server(self, event_bus: EventBus) -> None:
        handler = EvaluateHealthHandler(event_bus)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.save = AsyncMock()
        mock_repo.append_timeline = AsyncMock()

        old = _prepare_db()
        try:
            with patch(
                "app.modules.health.application.commands.evaluate_health.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(EvaluateHealthCommand(server_id="srv_new_1"))
        finally:
            _restore_db(old)

        assert result.success
        assert result.data["server_id"] == "srv_new_1"

    async def test_evaluate_existing_healthy(self, event_bus: EventBus) -> None:
        handler = EvaluateHealthHandler(event_bus)
        status = HealthStatus.create("srv_existing")
        status.update(
            new_classification=HealthStatusEnum.HEALTHY,
            contributing_factors=["All checks passed"],
            confidence=0.95,
        )

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=status)
        mock_repo.save = AsyncMock()
        mock_repo.append_timeline = AsyncMock()

        old = _prepare_db()
        try:
            with patch(
                "app.modules.health.application.commands.evaluate_health.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(EvaluateHealthCommand(server_id="srv_existing"))
        finally:
            _restore_db(old)

        assert result.success
        assert result.data["status"] == "healthy"

    async def test_register_and_dispatch(
        self, command_bus: CommandBus, event_bus: EventBus
    ) -> None:
        command_bus.register(EvaluateHealthCommand, EvaluateHealthHandler(event_bus))
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.save = AsyncMock()
        mock_repo.append_timeline = AsyncMock()

        old = _prepare_db()
        try:
            with patch(
                "app.modules.health.application.commands.evaluate_health.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await command_bus.send(EvaluateHealthCommand(server_id="srv_cmd_test"))
        finally:
            _restore_db(old)

        assert result.success
