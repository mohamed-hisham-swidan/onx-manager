from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import AppSettings
from app.modules.server.application.services.import_service import scan_server_directory
from app.modules.server.application.services.jar_service import parse_server_dir_name, _slugify
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LaunchConfiguration,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger("mcs.reconciliation.fs")


def _data_dir() -> str:
    return AppSettings().servers_data_dir


def _extract_server_id_from_dir(dirname: str) -> str | None:
    prefix = parse_server_dir_name(dirname)
    if prefix and len(prefix) == 32:
        return prefix
    if prefix and len(prefix) == 8:
        return prefix
    return None


async def reconcile(
    repo: ServerRepository,
) -> dict[str, list[dict]]:
    data_dir = _data_dir()
    data_path = Path(data_dir)

    if not data_path.is_dir():
        logger.info("data/servers/ does not exist — skipping reconciliation")
        return {"imported": [], "deleted": [], "errors": []}

    dir_entries: set[str] = set()
    dir_to_id: dict[str, str] = {}

    for entry in data_path.iterdir():
        if not entry.is_dir():
            continue
        dirname = entry.name
        dir_entries.add(dirname)
        sid = _extract_server_id_from_dir(dirname)
        if sid:
            dir_to_id[dirname] = sid

    db_servers = await repo.list()
    db_ids: set[str] = {str(s.id) for s in db_servers}

    ids_from_dirs: set[str] = set(dir_to_id.values())
    imported: list[dict] = []
    deleted: list[dict] = []
    errors: list[dict] = []

    for dirname, sid in dir_to_id.items():
        if sid not in db_ids:
            full_path = str(data_path / dirname)
            result = await _auto_import(full_path, repo)
            if result["success"]:
                imported.append(result)
                logger.info("Auto-imported server from %s (id=%s)", dirname, result["server_id"])
            else:
                errors.append(result)
                logger.warning("Failed to auto-import %s: %s", dirname, result.get("error"))

    for server in db_servers:
        sid = str(server.id)
        known_dirs = {d for d, i in dir_to_id.items() if i == sid}
        if not known_dirs:
            slug = _slugify(server.name)
            expected_dir = f"{slug}-{sid[:8]}"
            if expected_dir not in dir_entries and sid not in dir_entries:
                try:
                    await repo.delete(server.id)
                    deleted.append({"server_id": sid, "name": server.name})
                    logger.info("Deleted DB record for missing server dir: %s (%s)", server.name, sid)
                except Exception as e:
                    errors.append({"server_id": sid, "name": server.name, "error": str(e)})

    logger.info(
        "Reconciliation complete: %d imported, %d deleted, %d errors",
        len(imported), len(deleted), len(errors),
    )
    return {"imported": imported, "deleted": deleted, "errors": errors}


async def _auto_import(dir_path: str, repo: ServerRepository) -> dict:
    try:
        scanned = scan_server_directory(dir_path, fs=local_fs)
    except (NotADirectoryError, ValueError, Exception) as e:
        return {"path": dir_path, "success": False, "error": str(e)}

    server_id = ServerId(str(uuid.uuid4().hex))
    name = scanned.get("name") or Path(dir_path).name
    server_type_str = scanned.get("server_type", "vanilla")
    try:
        server_type = ServerType(server_type_str)
    except ValueError:
        server_type = ServerType.VANILLA

    mc_version = MinecraftVersion(scanned.get("minecraft_version", ""))

    props = scanned.get("properties", {})
    server_properties = ServerProperties(
        server_port=PortNumber(props.get("port", 25565)),
        max_players=props.get("max_players", 20),
        motd=props.get("motd", "A Minecraft Server"),
        gamemode=props.get("gamemode", "survival"),
        difficulty=props.get("difficulty", "easy"),
        spawn_protection=props.get("spawn_protection", 16),
        pvp=props.get("pvp", True),
        enable_command_block=props.get("enable_command_block", False),
        online_mode=props.get("online_mode", True),
        whitelist=props.get("whitelist", False),
        view_distance=props.get("view_distance", 10),
        simulation_distance=props.get("simulation_distance", 10),
    )

    server = Server(
        server_id=server_id,
        name=name,
        server_type=server_type,
        minecraft_version=mc_version,
        memory=MemoryAllocation(min_mb=1024, max_mb=2048),
        java_args=JavaArguments(),
        properties=server_properties,
        deployment=ServerDeployment(root_path=dir_path),
    )
    await repo.save(server)
    return {
        "path": dir_path,
        "success": True,
        "server_id": str(server_id),
        "name": name,
    }
