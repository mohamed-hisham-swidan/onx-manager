from typing import Any

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.monitoring.domain.aggregate import AlertCondition, AlertSeverity
from app.modules.monitoring.infrastructure.repository import SQLAlertRuleRepository


class UpdateAlertRuleCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    alert_rule_id: str
    metric_name: str | None = None
    condition: str | None = None
    threshold: float | None = None
    severity: str | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = None


class UpdateAlertRuleHandler(CommandHandler[UpdateAlertRuleCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateAlertRuleCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLAlertRuleRepository(uow.session)
            rule = await repo.get(command.alert_rule_id)

            changes: dict[str, Any] = {}
            if command.metric_name is not None:
                rule._metric_name = command.metric_name
                changes["metric_name"] = command.metric_name
            if command.condition is not None:
                rule._condition = AlertCondition(command.condition)
                changes["condition"] = command.condition
            if command.threshold is not None:
                rule._threshold = command.threshold
                changes["threshold"] = command.threshold
            if command.severity is not None:
                rule._severity = AlertSeverity(command.severity)
                changes["severity"] = command.severity
            if command.enabled is not None:
                rule._enabled = command.enabled
                changes["enabled"] = command.enabled
            if command.cooldown_minutes is not None:
                rule._cooldown_minutes = command.cooldown_minutes
                changes["cooldown_minutes"] = command.cooldown_minutes

            await repo.save(rule)
            await uow.commit()

        return CommandResult(
            success=True, data={"alert_rule_id": command.alert_rule_id, "changes": changes}
        )
