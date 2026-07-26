from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.monitoring.domain.aggregate import AlertCondition, AlertRule, AlertSeverity, MetricPoint, MetricSeries
from app.modules.monitoring.infrastructure.models import AlertRuleModel, MetricPointModel
from app.modules.shared.value_objects import ServerId


class SQLMetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, server_id: ServerId, point: MetricPoint) -> None:
        model = MetricPointModel(
            server_id=str(server_id),
            tps=point.tps,
            players=point.players,
            ram_used_mb=point.ram_used_mb,
            cpu_percent=point.cpu_percent,
            recorded_at=point.timestamp,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_series(
        self,
        server_id: ServerId,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[MetricPoint]:
        stmt = (
            select(MetricPointModel)
            .where(MetricPointModel.server_id == str(server_id))
            .order_by(MetricPointModel.recorded_at.desc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(MetricPointModel.recorded_at >= since)

        result = await self._session.execute(stmt)
        points = []
        for model in result.scalars().all():
            points.append(
                MetricPoint(
                    tps=model.tps,
                    players=model.players,
                    ram_used_mb=model.ram_used_mb,
                    cpu_percent=model.cpu_percent,
                    timestamp=model.recorded_at,
                ),
            )
        return points


class SQLAlertRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, rule_id: str) -> AlertRule:
        model = await self._session.get(AlertRuleModel, rule_id)
        if model is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"Alert rule '{rule_id}' not found")
        return self._model_to_domain(model)

    async def list_by_server(self, server_id: ServerId) -> list[AlertRule]:
        stmt = (
            select(AlertRuleModel)
            .where(AlertRuleModel.server_id == str(server_id))
            .order_by(AlertRuleModel.created_at)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def save(self, rule: AlertRule) -> None:
        model = await self._session.get(AlertRuleModel, rule._alert_rule_id)
        if model is None:
            model = AlertRuleModel(id=rule._alert_rule_id)
            self._session.add(model)

        model.server_id = str(rule.server_id)
        model.metric_name = rule.metric_name
        model.condition = rule.condition.value
        model.threshold = rule.threshold
        model.severity = rule.severity.value
        model.enabled = rule.enabled
        model.cooldown_minutes = rule.cooldown_minutes
        await self._session.flush()

    async def delete(self, rule_id: str) -> None:
        model = await self._session.get(AlertRuleModel, rule_id)
        if model:
            await self._session.delete(model)
            await self._session.flush()

    def _model_to_domain(self, model: AlertRuleModel) -> AlertRule:
        rule = AlertRule(
            server_id=ServerId(model.server_id),
            metric_name=model.metric_name,
            condition=AlertCondition(model.condition),
            threshold=model.threshold,
            severity=AlertSeverity(model.severity),
            enabled=model.enabled,
            cooldown_minutes=model.cooldown_minutes,
        )
        rule._alert_rule_id = model.id
        rule._last_triggered_at = model.last_triggered_at
        return rule
