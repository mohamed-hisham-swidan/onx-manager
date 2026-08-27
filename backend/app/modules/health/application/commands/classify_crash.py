from __future__ import annotations

import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.health.infrastructure.repository import SQLDiagnosticsRepository

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.classify_crash")


class ClassifyCrashCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    evidence_id: str


class ClassifyCrashHandler(CommandHandler[ClassifyCrashCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._classifier = PatternCrashAnalyzer()
        self._repo: SQLDiagnosticsRepository | None = None

    async def handle(self, command: ClassifyCrashCommand) -> CommandResult:
        logger.info(
            "Classifying crash for server %s evidence=%s",
            command.server_id,
            command.evidence_id,
        )

        async with UnitOfWork(self._event_bus) as uow:
            self._repo = SQLDiagnosticsRepository(uow.session)

            report = await self._repo.get_report(command.evidence_id)
            if report is None:
                return CommandResult(
                    success=False,
                    error=f"No diagnostics report found for evidence_id={command.evidence_id}",
                    error_code="REPORT_NOT_FOUND",
                )

            evidence = report.evidence
            if evidence is None:
                return CommandResult(
                    success=False,
                    error=f"Report {command.evidence_id} has no evidence bundle",
                    error_code="EVIDENCE_MISSING",
                )

            classification = await self._classifier.classify(evidence)
            report.classify(classification)

            await self._repo.save_classification(classification)
            await self._repo.save_report(report)
            for event in report.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "server_id": command.server_id,
                "evidence_id": command.evidence_id,
                "failure_code": classification.failure_code,
                "confidence": classification.confidence,
                "summary": classification.summary,
            },
        )
