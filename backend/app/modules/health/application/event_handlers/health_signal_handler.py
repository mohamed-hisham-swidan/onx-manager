from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.events import (
    CrashClassifiedEvent,
    IntegrityCheckFailedEvent,
    RuntimeHealthSignalEvent,
)
from app.modules.health.domain.value_objects import (
    HealthSignal,
    HealthStatusEnum,
    HealthTrend,
    SignalSeverity,
)
from app.modules.health.infrastructure.health_calculator import SignalHealthCalculator
from app.modules.health.infrastructure.repository import SQLHealthRepository

logger = logging.getLogger("mcs.health.signal_handler")


class HealthSignalHandler(EventHandler):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._calculator = SignalHealthCalculator()

    async def handle(self, event: DomainEvent) -> None:
        if isinstance(event, RuntimeHealthSignalEvent):
            await self._handle_signal(event)
        elif isinstance(event, IntegrityCheckFailedEvent):
            await self._handle_integrity_failure(event)
        elif isinstance(event, CrashClassifiedEvent):
            await self._handle_crash_classified(event)

    async def _handle_signal(self, event: RuntimeHealthSignalEvent) -> None:
        signal = HealthSignal(
            server_id=event.server_id,
            signal_type=event.signal_type,
            severity=SignalSeverity(event.severity),
            value=event.value,
            details=event.details or {},
            timestamp=datetime.now(timezone.utc),
        )
        await self._recompute(event.server_id, [signal])

    async def _handle_integrity_failure(self, event: IntegrityCheckFailedEvent) -> None:
        signal = HealthSignal(
            server_id=event.server_id,
            signal_type=f"integrity:{event.check_name}",
            severity=SignalSeverity(event.severity),
            value=event.detail,
            details={"check_name": event.check_name, "scope": event.scope},
            timestamp=datetime.now(timezone.utc),
        )
        await self._recompute(event.server_id, [signal])

    async def _handle_crash_classified(self, event: CrashClassifiedEvent) -> None:
        signal = HealthSignal(
            server_id=event.server_id,
            signal_type="crash",
            severity=SignalSeverity.CRITICAL,
            value=event.failure_code,
            details={
                "failure_code": event.failure_code,
                "confidence": event.confidence,
                "summary": event.summary,
            },
            timestamp=datetime.now(timezone.utc),
        )
        await self._recompute(event.server_id, [signal])

    async def _recompute(self, server_id: str, new_signals: list[HealthSignal]) -> None:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLHealthRepository(uow.session)
            status = await repo.get(server_id)
            if status is None:
                status = HealthStatus.create(server_id)

            timeline = await repo.get_timeline(server_id, limit=50)
            historical_signals = self._extract_signals_from_timeline(timeline) if timeline else []

            all_signals = historical_signals + new_signals
            new_classification, factors, confidence, trend = await self._calculator.compute(
                current_status=status.classification,
                signals=all_signals,
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

    def _extract_signals_from_timeline(self, timeline: list) -> list[HealthSignal]:
        signals: list[HealthSignal] = []
        for entry in timeline:
            for factor in entry.contributing_factors:
                signals.append(HealthSignal(
                    server_id=entry.server_id,
                    signal_type="timeline",
                    severity=SignalSeverity.INFO,
                    value=factor,
                    timestamp=entry.timestamp,
                ))
        return signals
