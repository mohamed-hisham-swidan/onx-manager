from __future__ import annotations

import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.value_objects import HealthStatusEnum
from app.modules.health.infrastructure.repository import SQLHealthRepository
from app.core.persistence.unit_of_work import UnitOfWork

logger = logging.getLogger("mcs.health.evaluate")


class EvaluateHealthCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str


class EvaluateHealthHandler(CommandHandler[EvaluateHealthCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: EvaluateHealthCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLHealthRepository(uow.session)
            status = await repo.get(command.server_id)
            if status is None:
                status = HealthStatus.create(command.server_id)

            current = status.classification
            factors: list[str] = []
            new_classification = current
            confidence = 0.5

            if current == HealthStatusEnum.PENDING:
                new_classification = HealthStatusEnum.UNKNOWN
                factors.append("No health signals received yet")

            status.update(
                new_classification=new_classification,
                contributing_factors=factors,
                confidence=confidence,
            )

            await repo.save(status)
            if new_classification != current:
                await repo.append_timeline(status.to_timeline_entry())
            for event in status.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "server_id": command.server_id,
                "status": new_classification.value,
            },
        )
