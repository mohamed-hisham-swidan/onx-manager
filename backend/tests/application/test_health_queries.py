from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.query_bus import QueryBus
from app.modules.health.application import (
    GetHealthStatusHandler,
    GetHealthStatusQuery,
    GetHealthTimelineHandler,
    GetHealthTimelineQuery,
)
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.value_objects import (
    HealthStatusEnum,
    HealthTimelineEntry,
    HealthTrend,
)
from app.core.persistence.db import database


pytestmark = pytest.mark.asyncio


def _mock_session():
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock()
    return s


class TestGetHealthStatusHandler:
    async def test_get_existing(self) -> None:
        handler = GetHealthStatusHandler()

        status = HealthStatus.create("srv_q_1")
        status.update(
            new_classification=HealthStatusEnum.HEALTHY,
            contributing_factors=["ok"],
            trend=HealthTrend.IMPROVING,
            confidence=0.95,
        )

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=status)

        old_factory = database._session_factory
        database._session_factory = _mock_session()
        try:
            with patch(
                "app.modules.health.application.queries.get_health_status.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(GetHealthStatusQuery(server_id="srv_q_1"))
        finally:
            database._session_factory = old_factory

        assert result is not None
        assert result.server_id == "srv_q_1"
        assert result.status == "healthy"
        assert result.trend == "improving"
        assert result.confidence == 0.95

    async def test_get_nonexistent(self) -> None:
        handler = GetHealthStatusHandler()

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        old_factory = database._session_factory
        database._session_factory = _mock_session()
        try:
            with patch(
                "app.modules.health.application.queries.get_health_status.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(GetHealthStatusQuery(server_id="nonexistent"))
        finally:
            database._session_factory = old_factory

        assert result is None

    async def test_register_and_query(self, query_bus: QueryBus) -> None:
        query_bus.register(GetHealthStatusQuery, GetHealthStatusHandler())

        status = HealthStatus.create("srv_q_reg")
        status.update(new_classification=HealthStatusEnum.WARNING, contributing_factors=["high cpu"])

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=status)

        old_factory = database._session_factory
        database._session_factory = _mock_session()
        try:
            with patch(
                "app.modules.health.application.queries.get_health_status.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await query_bus.ask(GetHealthStatusQuery(server_id="srv_q_reg"))
        finally:
            database._session_factory = old_factory

        assert result is not None
        assert result.status == "warning"


class TestGetHealthTimelineHandler:
    async def test_get_timeline(self) -> None:
        handler = GetHealthTimelineHandler()

        entries = [
            HealthTimelineEntry(
                server_id="srv_tl_q",
                previous_status=HealthStatusEnum.PENDING,
                new_status=HealthStatusEnum.HEALTHY,
                contributing_factors=["ok"],
                timestamp=datetime.now(timezone.utc),
            ),
            HealthTimelineEntry(
                server_id="srv_tl_q",
                previous_status=HealthStatusEnum.HEALTHY,
                new_status=HealthStatusEnum.WARNING,
                contributing_factors=["cpu"],
                timestamp=datetime.now(timezone.utc),
            ),
        ]

        mock_repo = AsyncMock()
        mock_repo.get_timeline = AsyncMock(return_value=entries)

        old_factory = database._session_factory
        database._session_factory = _mock_session()
        try:
            with patch(
                "app.modules.health.application.queries.get_health_timeline.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(GetHealthTimelineQuery(server_id="srv_tl_q", limit=5))
        finally:
            database._session_factory = old_factory

        assert len(result) == 2
        assert result[0].new_status == "healthy"
        assert result[1].new_status == "warning"
        assert result[1].previous_status == "healthy"

    async def test_empty_timeline(self) -> None:
        handler = GetHealthTimelineHandler()

        mock_repo = AsyncMock()
        mock_repo.get_timeline = AsyncMock(return_value=[])

        old_factory = database._session_factory
        database._session_factory = _mock_session()
        try:
            with patch(
                "app.modules.health.application.queries.get_health_timeline.SQLHealthRepository",
                return_value=mock_repo,
            ):
                result = await handler.handle(GetHealthTimelineQuery(server_id="srv_empty"))
        finally:
            database._session_factory = old_factory

        assert result == []
