import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.monitoring.domain.aggregate import AlertCondition, AlertRule, AlertSeverity
from app.modules.monitoring.infrastructure.repository import SQLAlertRuleRepository
from app.modules.shared.value_objects import ServerId
from app.storage.unit_of_work import UnitOfWork


class CreateAlertRuleCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    metric_name: str
    condition: str = "gt"
    threshold: float
    severity: str = "warning"
    cooldown_minutes: int = 15


class CreateAlertRuleHandler(CommandHandler[CreateAlertRuleCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateAlertRuleCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLAlertRuleRepository(uow.session)
            rule = AlertRule(
                server_id=ServerId(command.server_id),
                metric_name=command.metric_name,
                condition=AlertCondition(command.condition),
                threshold=command.threshold,
                severity=AlertSeverity(command.severity),
                cooldown_minutes=command.cooldown_minutes,
            )
            await repo.save(rule)
            for event in rule.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"alert_rule_id": rule._alert_rule_id})
