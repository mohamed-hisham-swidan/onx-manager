from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId
from app.storage.unit_of_work import UnitOfWork


class InstallPluginCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    website: str = ""
    dependencies: list[str] = []


class InstallPluginHandler(CommandHandler[InstallPluginCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: InstallPluginCommand) -> CommandResult:
        plugin_id = PluginId()
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: PluginRepository = SQLPluginRepository(uow.session)
            plugin = Plugin.install(
                plugin_id=plugin_id,
                server_id=server_id,
                name=command.name,
                version=PluginVersion.parse(command.version),
                description=command.description,
                author=command.author,
                website=command.website,
                dependencies=command.dependencies or None,
            )
            await repo.save(plugin)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"plugin_id": str(plugin_id)})
