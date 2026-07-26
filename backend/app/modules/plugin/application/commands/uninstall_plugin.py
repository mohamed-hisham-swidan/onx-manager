from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import PluginId
from app.storage.unit_of_work import UnitOfWork


class UninstallPluginCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    plugin_id: str


class UninstallPluginHandler(CommandHandler[UninstallPluginCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UninstallPluginCommand) -> CommandResult:
        plugin_id = PluginId(command.plugin_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: PluginRepository = SQLPluginRepository(uow.session)
            plugin = await repo.get(plugin_id)
            plugin.mark_uninstalled()
            await repo.delete(plugin_id)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"plugin_id": command.plugin_id})
