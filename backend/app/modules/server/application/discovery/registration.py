from __future__ import annotations

import logging
from pathlib import Path

from app.core.event_bus import EventBus
from app.core.identity import IDENTITY
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.events import ServerDiscoveredEvent
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.discovery.registration")


async def handle_server_discovered(
    event: ServerDiscoveredEvent,
    repo: ServerRepository,
    event_bus: EventBus,
) -> str | None:
    try:
        path = Path(event.path)
        dirname = path.name
        metadata = event.metadata or {}

        name = metadata.get("dirname", dirname)
        try:
            port = int(metadata.get("server_port", "25565"))
        except (ValueError, TypeError):
            port = 25565

        server_type_str = event.detected_type
        try:
            server_type = ServerType(server_type_str)
        except ValueError:
            server_type = ServerType.VANILLA

        server = Server.create(
            server_id=ServerId(),
            name=name,
            server_type=server_type,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(min_mb=1024, max_mb=2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(port)),
            deployment=ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(path),
                working_directory=".",
            ),
        )

        server_id = str(server.id)
        await repo.save(server)
        logger.info(
            "Registered discovered server name=%s id=%s path=%s type=%s",
            name,
            server_id,
            event.path,
            server_type_str,
        )
        return server_id

    except Exception as exc:
        logger.exception(
            "Failed to register discovered server path=%s: %s",
            event.path,
            exc,
        )
        return None
