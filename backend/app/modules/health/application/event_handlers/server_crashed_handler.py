from __future__ import annotations

import logging

from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.health.domain.events import CrashClassifiedEvent, EvidenceCollectedEvent
from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.health.infrastructure.evidence_collector import LogBasedEvidenceCollector
from app.modules.health.infrastructure.recovery_orchestrator import RecoveryOrchestrator
from app.modules.health.infrastructure.repository import SQLDiagnosticsRepository
from app.modules.server.domain.events import ServerCrashedEvent

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.crash_handler")


class HandleServerCrashHandler(EventHandler):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._collector = LogBasedEvidenceCollector()
        self._classifier = PatternCrashAnalyzer()
        self._recovery = RecoveryOrchestrator()

    async def handle(self, event: DomainEvent) -> None:
        if not isinstance(event, ServerCrashedEvent):
            return

        server_id = event.server_id
        logger.info("Handling ServerCrashedEvent for server %s", server_id)

        bundle = await self._collector.collect(server_id)
        classification = await self._classifier.classify(bundle)

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLDiagnosticsRepository(uow.session)

            await repo.save_evidence(bundle)
            await repo.save_classification(classification)

            uow.add_event(
                EvidenceCollectedEvent(
                    server_id=server_id,
                    evidence_id=bundle.evidence_id,
                    collection_errors=bundle.collection_errors,
                ),
            )
            uow.add_event(
                CrashClassifiedEvent(
                    server_id=server_id,
                    evidence_id=bundle.evidence_id,
                    failure_code=classification.failure_code,
                    confidence=classification.confidence,
                    summary=classification.summary,
                    suggested_action=classification.suggested_action,
                ),
            )

            recovery_action = await self._recovery.trigger(
                server_id,
                classification.failure_code,
            )
            for recovery_event in recovery_action.events:
                uow.add_event(recovery_event)

            await uow.commit()

        logger.info(
            "Crash handling complete server=%s failure=%s action=%s",
            server_id,
            classification.failure_code,
            recovery_action.action,
        )
