from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import AppSettings
from app.modules.server.application.services.import_service import scan_server_directory
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger("mcs.reconciliation.fs")

IDENTITY_DIR = ".mcsmanager"
IDENTITY_FILE = "server.json"
MCSMANAGER_META_DIR = IDENTITY_DIR


@dataclass
class ReconciliationResult:
    imported: list[dict] = field(default_factory=list)
    updated: list[dict] = field(default_factory=list)
    deleted: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    broken: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _data_dir() -> str:
    return AppSettings().servers_data_dir


# ---------------------------------------------------------------------------
# Identity I/O  —  .mcsmanager/server.json
# ---------------------------------------------------------------------------


def _identity_path(dir_path: str) -> str:
    return str(Path(dir_path) / IDENTITY_DIR / IDENTITY_FILE)


def _read_identity(dir_path: str) -> str | None:
    path = _identity_path(dir_path)
    if not local_fs.exists(path):
        return None
    try:
        data = json.loads(local_fs.read_text(path))
        sid = data.get("server_id", "")
        return sid if isinstance(sid, str) and len(sid) == 32 else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_identity(dir_path: str, server_id: str) -> None:
    meta_dir = str(Path(dir_path) / MCSMANAGER_META_DIR)
    local_fs.ensure_dir(meta_dir)
    local_fs.write_text(
        _identity_path(dir_path),
        json.dumps({"server_id": server_id}, indent=2),
    )


# ---------------------------------------------------------------------------
# Broken detection
# ---------------------------------------------------------------------------


def _detect_broken(scanned: dict | None) -> tuple[bool, list[str]]:
    if scanned is None:
        return True, ["Directory is not a valid Minecraft server"]
    reasons: list[str] = []
    if not scanned.get("server_jar"):
        reasons.append("No server jar detected")
    props = scanned.get("properties", {})
    if not props:
        reasons.append("No server.properties found or empty")
    return len(reasons) > 0, reasons


# ---------------------------------------------------------------------------
# FS scan
# ---------------------------------------------------------------------------


@dataclass
class _DirEntry:
    dir_path: str
    dir_name: str
    server_id: str | None
    is_minecraft: bool
    scanned: dict | None
    is_broken: bool
    broken_reasons: list[str]


def _scan_fs() -> list[_DirEntry]:
    data_dir = _data_dir()
    data_path = Path(data_dir)
    if not data_path.is_dir():
        logger.info("data/servers/ does not exist — skipping FS scan")
        return []

    entries: list[_DirEntry] = []
    for entry in sorted(data_path.iterdir()):
        if not entry.is_dir():
            continue
        dir_path = str(entry)
        dir_name = entry.name

        sid = _read_identity(dir_path)

        scanned: dict | None = None
        is_minecraft = False
        try:
            scanned = scan_server_directory(dir_path, fs=local_fs)
            is_minecraft = True
        except (NotADirectoryError, ValueError):
            scanned = None
            is_minecraft = False
        except Exception as exc:
            logger.warning("Unexpected error scanning %s: %s", dir_path, exc)
            scanned = None
            is_minecraft = False

        broken, reasons = _detect_broken(scanned)

        entries.append(_DirEntry(
            dir_path=dir_path,
            dir_name=dir_name,
            server_id=sid,
            is_minecraft=is_minecraft,
            scanned=scanned,
            is_broken=broken,
            broken_reasons=reasons,
        ))
    return entries


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


@dataclass
class _ReconciliationPlan:
    imports: list[_DirEntry] = field(default_factory=list)
    updates: list[tuple[_DirEntry, Server]] = field(default_factory=list)
    mark_missing: list[Server] = field(default_factory=list)
    deletes: list[Server] = field(default_factory=list)
    unchanged: list[Server] = field(default_factory=list)
    ignored: list[_DirEntry] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _build_plan(
    fs_entries: list[_DirEntry],
    db_servers: list[Server],
) -> _ReconciliationPlan:
    plan = _ReconciliationPlan()
    db_by_id: dict[str, Server] = {str(s.id): s for s in db_servers}
    accounted: set[str] = set()

    for entry in fs_entries:
        if entry.server_id and entry.server_id in db_by_id:
            server = db_by_id[entry.server_id]
            accounted.add(entry.server_id)

            needs_update = False
            if server.deployment:
                current_jar = (entry.scanned or {}).get("server_jar") or "server.jar"
                if server.deployment.root_path != entry.dir_path:
                    needs_update = True
                elif server.deployment.startup_jar != current_jar:
                    needs_update = True
            else:
                needs_update = True

            if entry.is_broken and server.status not in (ServerStatus.BROKEN, ServerStatus.MISSING):
                needs_update = True
            elif not entry.is_broken and server.status == ServerStatus.BROKEN:
                needs_update = True

            if needs_update:
                plan.updates.append((entry, server))
            else:
                plan.unchanged.append(server)

        elif entry.server_id and entry.server_id not in db_by_id:
            plan.imports.append(entry)

        elif not entry.server_id and entry.is_minecraft:
            plan.imports.append(entry)

        elif not entry.server_id and not entry.is_minecraft:
            plan.ignored.append(entry)

    for sid, server in db_by_id.items():
        if sid in accounted:
            continue
        if server.status == ServerStatus.MISSING:
            plan.deletes.append(server)
        else:
            plan.mark_missing.append(server)

    return plan


# ---------------------------------------------------------------------------
# Value-object builders
# ---------------------------------------------------------------------------


def _build_server_properties(scanned: dict | None) -> ServerProperties:
    props = (scanned or {}).get("properties", {})
    return ServerProperties(
        port=PortNumber(props.get("port", 25565)),
        motd=props.get("motd", "A Minecraft Server"),
        max_players=props.get("max_players", 20),
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


def _build_deployment(entry: _DirEntry) -> ServerDeployment:
    jar = (entry.scanned or {}).get("server_jar") or "server.jar"
    return ServerDeployment(
        root_path=entry.dir_path,
        working_directory=".",
        startup_jar=jar,
    )


def _build_name(entry: _DirEntry) -> str:
    return (entry.scanned or {}).get("name") or entry.dir_name


# ---------------------------------------------------------------------------
# Plan executor
# ---------------------------------------------------------------------------


async def _execute_plan(
    plan: _ReconciliationPlan,
    repo: ServerRepository,
) -> ReconciliationResult:
    result = ReconciliationResult()
    now = datetime.now(timezone.utc)

    for entry in plan.imports:
        try:
            sid = entry.server_id or uuid.uuid4().hex
            server_id = ServerId(sid)

            if not entry.server_id:
                _write_identity(entry.dir_path, sid)

            name = _build_name(entry)
            scanned_type = (entry.scanned or {}).get("server_type", "vanilla")
            try:
                server_type = ServerType(scanned_type)
            except ValueError:
                server_type = ServerType.VANILLA

            mc_version_str = (entry.scanned or {}).get("minecraft_version", "")
            if mc_version_str:
                try:
                    mc_version = MinecraftVersion.parse(mc_version_str)
                except ValueError:
                    mc_version = MinecraftVersion(0, 0)
            else:
                mc_version = MinecraftVersion(0, 0)

            props = _build_server_properties(entry.scanned)
            deployment = _build_deployment(entry)

            server = Server(
                server_id=server_id,
                name=name,
                server_type=server_type,
                minecraft_version=mc_version,
                memory=MemoryAllocation(min_mb=1024, max_mb=2048),
                java_args=JavaArguments(),
                properties=props,
                deployment=deployment,
            )

            if entry.is_broken:
                server._status = ServerStatus.BROKEN
                result.broken.append({
                    "server_id": sid,
                    "name": name,
                    "path": entry.dir_path,
                    "reasons": entry.broken_reasons,
                })

            await repo.save(server)
            result.imported.append({
                "server_id": sid,
                "name": name,
                "path": entry.dir_path,
                "broken": entry.is_broken,
            })
            logger.info("Imported server %s (%s) from %s", name, sid, entry.dir_path)

        except Exception as exc:
            logger.exception("Failed to import %s", entry.dir_path)
            result.errors.append({
                "path": entry.dir_path,
                "action": "import",
                "error": str(exc),
            })

    for entry, server in plan.updates:
        try:
            sid = str(server.id)
            modified = False

            if server.deployment:
                current_jar = (entry.scanned or {}).get("server_jar") or "server.jar"
                if server.deployment.root_path != entry.dir_path or server.deployment.startup_jar != current_jar:
                    server._deployment = ServerDeployment(
                        root_path=entry.dir_path,
                        working_directory=".",
                        startup_jar=current_jar,
                    )
                    modified = True

            if entry.is_broken and server.status not in (ServerStatus.BROKEN, ServerStatus.MISSING):
                server._status = ServerStatus.BROKEN
                result.broken.append({
                    "server_id": sid,
                    "name": server.name,
                    "path": entry.dir_path,
                    "reasons": entry.broken_reasons,
                })
                modified = True
            elif not entry.is_broken and server.status == ServerStatus.BROKEN:
                server._status = ServerStatus.CREATED
                modified = True

            if modified:
                server._updated_at = now
                await repo.save(server)
                result.updated.append({
                    "server_id": sid,
                    "name": server.name,
                    "path": entry.dir_path,
                })
                logger.info("Updated server %s (%s) from FS scan", server.name, sid)
            else:
                result.unchanged.append({
                    "server_id": sid,
                    "name": server.name,
                })
        except Exception as exc:
            logger.exception("Failed to update server %s", str(server.id))
            result.errors.append({
                "server_id": str(server.id),
                "name": server.name,
                "action": "update",
                "error": str(exc),
            })

    for server in plan.mark_missing:
        try:
            sid = str(server.id)
            prev_status = server.status.value
            server._status = ServerStatus.MISSING
            server._updated_at = now
            await repo.save(server)
            result.missing.append({
                "server_id": sid,
                "name": server.name,
                "previous_status": prev_status,
            })
            logger.warning(
                "Marked server %s (%s) as MISSING — directory not found",
                server.name, sid,
            )
        except Exception as exc:
            logger.exception("Failed to mark MISSING for %s", str(server.id))
            result.errors.append({
                "server_id": str(server.id),
                "action": "mark_missing",
                "error": str(exc),
            })

    for server in plan.deletes:
        try:
            sid = str(server.id)
            server.mark_deleted()
            await repo.delete(server.id)
            result.deleted.append({
                "server_id": sid,
                "name": server.name,
            })
            logger.info(
                "Deleted DB record for MISSING server %s (%s) — second pass",
                server.name, sid,
            )
        except Exception as exc:
            logger.exception("Failed to delete server %s", str(server.id))
            result.errors.append({
                "server_id": str(server.id),
                "action": "delete",
                "error": str(exc),
            })

    for entry in plan.ignored:
        result.ignored.append({
            "path": entry.dir_path,
            "reason": "Not a Minecraft server and no identity file",
        })
        logger.debug("Ignored non-Minecraft directory %s", entry.dir_path)

    logger.info(
        "Reconciliation done: %d imported, %d updated, %d deleted, "
        "%d missing, %d broken, %d unchanged, %d ignored, %d errors",
        len(result.imported), len(result.updated), len(result.deleted),
        len(result.missing), len(result.broken), len(result.unchanged),
        len(result.ignored), len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def reconcile(repo: ServerRepository) -> ReconciliationResult:
    fs_entries = _scan_fs()
    if not fs_entries:
        return ReconciliationResult()

    db_servers = await repo.list()
    plan = _build_plan(fs_entries, db_servers)
    return await _execute_plan(plan, repo)


async def reconcile_now() -> ReconciliationResult:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        result = await reconcile(repo)
        await session.commit()
        return result
