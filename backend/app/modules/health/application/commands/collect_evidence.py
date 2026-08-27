from __future__ import annotations

import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.health.domain.aggregate import DiagnosticsReport
from app.modules.health.infrastructure.evidence_collector import LogBasedEvidenceCollector
from app.modules.health.infrastructure.repository import SQLDiagnosticsRepository

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.collect_evidence")


class CollectEvidenceCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    server_dir: str | None = None


class CollectEvidenceHandler(CommandHandler[CollectEvidenceCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._collector = LogBasedEvidenceCollector()

    async def handle(self, command: CollectEvidenceCommand) -> CommandResult:
        logger.info("Collecting evidence for server %s", command.server_id)

        bundle = await self._collector.collect(command.server_id, command.server_dir)
        report = DiagnosticsReport.create_from_evidence(command.server_id, bundle)

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLDiagnosticsRepository(uow.session)
            await repo.save_evidence(bundle)
            await repo.save_report(report)
            for event in report.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "server_id": command.server_id,
                "evidence_id": bundle.evidence_id,
                "error_count": len(bundle.collection_errors),
            },
        )
