import pytest

from app.core.event_bus import EventBus
from app.modules.monitoring.application.commands.create_alert_rule import (
    CreateAlertRuleCommand,
    CreateAlertRuleHandler,
)
from app.modules.monitoring.application.commands.update_alert_rule import (
    UpdateAlertRuleCommand,
    UpdateAlertRuleHandler,
)
from app.modules.monitoring.application.queries.get_metrics import (
    GetMetricsHandler,
    GetMetricsQuery,
)
from app.modules.monitoring.domain.aggregate import MetricPoint
from app.modules.monitoring.infrastructure.repository import (
    SQLAlertRuleRepository,
    SQLMetricRepository,
)
from app.modules.shared.value_objects import ServerId
from app.storage.db import database


@pytest.mark.usefixtures("init_test_db")
class TestCreateAlertRuleHandler:
    @pytest.mark.asyncio
    async def test_create_alert_rule(self, event_bus: EventBus) -> None:
        handler = CreateAlertRuleHandler(event_bus)
        cmd = CreateAlertRuleCommand(
            server_id="srv-1",
            metric_name="tps",
            condition="lt",
            threshold=10.0,
            severity="warning",
        )

        result = await handler.handle(cmd)

        assert result.success is True
        assert "alert_rule_id" in result.data

    @pytest.mark.asyncio
    async def test_create_alert_rule_defaults(self, event_bus: EventBus) -> None:
        handler = CreateAlertRuleHandler(event_bus)
        cmd = CreateAlertRuleCommand(
            server_id="srv-1",
            metric_name="players",
            condition="gt",
            threshold=50.0,
        )

        result = await handler.handle(cmd)

        assert result.success is True


@pytest.mark.usefixtures("init_test_db")
class TestUpdateAlertRuleHandler:
    @pytest.mark.asyncio
    async def test_update_alert_rule(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLAlertRuleRepository(session)
            from app.modules.monitoring.domain.aggregate import AlertCondition, AlertRule, AlertSeverity
            rule = AlertRule(
                server_id=ServerId("srv-1"),
                metric_name="tps",
                condition=AlertCondition.LESS_THAN,
                threshold=10.0,
            )
            await repo.save(rule)
            await session.commit()
            rule_id = rule._alert_rule_id

        handler = UpdateAlertRuleHandler(event_bus)
        result = await handler.handle(UpdateAlertRuleCommand(
            alert_rule_id=rule_id,
            threshold=5.0,
            enabled=False,
        ))

        assert result.success is True
        assert result.data["changes"]["threshold"] == 5.0
        assert result.data["changes"]["enabled"] is False


@pytest.mark.usefixtures("init_test_db")
class TestGetMetricsHandler:
    @pytest.mark.asyncio
    async def test_get_metrics_empty(self) -> None:
        handler = GetMetricsHandler()
        result = await handler.handle(GetMetricsQuery(server_id="srv-1"))

        assert result == []

    @pytest.mark.asyncio
    async def test_get_metrics_with_data(self) -> None:
        async with database.session_factory() as session:
            repo = SQLMetricRepository(session)
            point = MetricPoint(tps=19.5, players=10, ram_used_mb=2048.0, cpu_percent=55.0)
            await repo.record(ServerId("srv-1"), point)
            await session.commit()

        handler = GetMetricsHandler()
        result = await handler.handle(GetMetricsQuery(server_id="srv-1", limit=10))

        assert len(result) == 1
        assert result[0].tps == 19.5
        assert result[0].players == 10
