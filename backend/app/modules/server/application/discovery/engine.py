from __future__ import annotations

import logging
from collections.abc import Sequence

from app.core.event_bus import EventBus
from app.modules.server.application.services.jar_service import server_dir_name
from app.modules.server.domain.events import ServerDiscoveredEvent, ServerVanishedEvent
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.scanner import FilesystemScanner

logger = logging.getLogger("mcs.discovery.engine")


async def run_discovery_scan(
    repo: ServerRepository,
    event_bus: EventBus,
    scanner: FilesystemScanner | None = None,
) -> dict[str, int]:
    if scanner is None:
        scanner = FilesystemScanner()

    discovered = await scanner.scan()

    known_dirs: set[str] = set()
    try:
        all_servers = await repo.list()
        for s in all_servers:
            sid = str(s.id)
            known_dirs.add(server_dir_name(s.name, sid))
            if s.deployment and s.deployment.root_path:
                known_dirs.add(s.deployment.server_directory())
    except Exception:
        logger.exception("Failed to list known servers for discovery scan")
        return {"discovered": 0, "vanished": 0, "already_known": 0}

    new_count = 0
    known_count = 0
    for entry in discovered:
        if entry.path in known_dirs or entry.dirname in known_dirs:
            known_count += 1
            continue
        parsed_id = entry.properties.get("server-id", "")
        await event_bus.publish(ServerDiscoveredEvent(
            path=entry.path,
            detected_type=entry.detected_type,
            metadata={
                "dirname": entry.dirname,
                "has_jar": entry.has_server_jar,
                "has_world": entry.has_world_dir,
                "size_mb": round(entry.size_mb, 1),
                "jar_name": entry.jar_name,
                "level_name": entry.properties.get("level-name", "world"),
                "server_port": entry.properties.get("server-port", "25565"),
                "server_id_hint": parsed_id,
            },
        ))
        new_count += 1

    logger.info(
        "Discovery scan complete: %d new, %d already known (from %d total entries)",
        new_count, known_count, len(discovered),
    )
    return {"discovered": new_count, "vanished": 0, "already_known": known_count}
