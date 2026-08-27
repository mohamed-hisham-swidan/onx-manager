from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.value_objects import (
    HealthSignal,
    HealthTrend,
    SignalSeverity,
)
from app.modules.health.infrastructure.health_calculator import SignalHealthCalculator
from app.modules.health.infrastructure.repository import SQLHealthRepository

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.evaluate")


class EvaluateHealthCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    signals: list[dict] | None = None


class EvaluateHealthHandler(CommandHandler[EvaluateHealthCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._calculator = SignalHealthCalculator()

    async def handle(self, command: EvaluateHealthCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLHealthRepository(uow.session)
            status = await repo.get(command.server_id)
            if status is None:
                status = HealthStatus.create(command.server_id)

            signals = self._build_signals(command)
            new_classification, factors, confidence, trend = await self._calculator.compute(
                current_status=status.classification,
                signals=signals,
            )

            status.update(
                new_classification=new_classification,
                contributing_factors=factors,
                trend=HealthTrend(trend),
                confidence=confidence,
            )

            await repo.save(status)
            if new_classification != status.previous_classification:
                await repo.append_timeline(status.to_timeline_entry())
            for event in status.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "server_id": command.server_id,
                "status": new_classification.value,
                "confidence": confidence,
                "factors": factors,
            },
        )

    def _build_signals(self, command: EvaluateHealthCommand) -> list[HealthSignal]:
        if not command.signals:
            return []
        signals: list[HealthSignal] = []
        for s in command.signals:
            try:
                severity = SignalSeverity(s.get("severity", "info"))
            except ValueError:
                severity = SignalSeverity.INFO
            signals.append(
                HealthSignal(
                    server_id=command.server_id,
                    signal_type=s.get("signal_type", "unknown"),
                    severity=severity,
                    value=s.get("value", ""),
                    details=s.get("details", {}),
                    timestamp=datetime.fromisoformat(s["timestamp"])
                    if "timestamp" in s
                    else datetime.now(UTC),
                )
            )
        return signals
