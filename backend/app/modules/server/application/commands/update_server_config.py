from typing import Any

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.services.jar_service import update_server_properties_key
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    MemoryAllocation,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

_PROP_KEY_MAP = {
    "port": "server-port",
    "max_players": "max-players",
    "spawn_protection": "spawn-protection",
    "enable_command_block": "enable-command-block",
    "online_mode": "online-mode",
    "whitelist": "white-list",
    "view_distance": "view-distance",
    "simulation_distance": "simulation-distance",
}
_REVERSE_PROP_KEY_MAP = {v: k for k, v in _PROP_KEY_MAP.items()}


class UpdateServerConfigCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    name: str | None = None
    properties: dict[str, Any] = {}
    min_memory_mb: int | None = None
    max_memory_mb: int | None = None
    cpu_cores: int | None = None
    cpu_affinity: str | None = None
    java_args: list[str] | None = None


class UpdateServerConfigHandler(CommandHandler[UpdateServerConfigCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateServerConfigCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            name_changed = False
            if command.name is not None and command.name.strip():
                server.rename(command.name)
                name_changed = True
            elif command.properties:
                pname = (
                    command.properties.get("server-name")
                    or command.properties.get("server_name")
                    or command.properties.get("name")
                )
                if isinstance(pname, str) and pname.strip():
                    server.rename(pname)
                    name_changed = True

            if command.properties:
                domain_props: dict[str, Any] = {}
                for k, v in command.properties.items():
                    domain_key = _REVERSE_PROP_KEY_MAP.get(k, k.replace("-", "_"))
                    domain_props[domain_key] = v
                server.update_properties(**domain_props)
            if command.min_memory_mb is not None or command.max_memory_mb is not None:
                min_mb = command.min_memory_mb or server.memory.min_mb
                max_mb = command.max_memory_mb or server.memory.max_mb
                server.update_memory(MemoryAllocation(min_mb=min_mb, max_mb=max_mb))
            if command.cpu_cores is not None or command.cpu_affinity is not None:
                cores = (
                    command.cpu_cores
                    if command.cpu_cores is not None
                    else server.cpu.cores
                )
                affinity = (
                    command.cpu_affinity
                    if command.cpu_affinity is not None
                    else server.cpu.affinity
                )
                server.update_cpu(CpuAllocation(cores=cores, affinity=affinity))
            if command.java_args is not None:
                server.update_java_args(JavaArguments(command.java_args))

            if server.deployment and server.deployment.root_path:
                props_path = server.deployment.properties_path()
                try:
                    if name_changed:
                        update_server_properties_key(props_path, "server-name", server.name)
                    if command.properties:
                        for k, v in command.properties.items():
                            file_key = _PROP_KEY_MAP.get(k, k.replace("_", "-"))
                            if file_key != "server-name":
                                str_val = str(v).lower() if isinstance(v, bool) else str(v)
                                update_server_properties_key(props_path, file_key, str_val)
                except Exception:
                    pass

            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"server_id": command.server_id})
