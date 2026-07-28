from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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
IDENTITY_VERSION = 1


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class ReconciliationResult:
    imported: list[dict] = field(default_factory=list)
    updated: list[dict] = field(default_factory=list)
    deleted: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    broken: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    invalid_identity: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


# ===================================================================
# Stage 1 — Filesystem Scanner
# ===================================================================


@dataclass
class FsEntry:
    path: str
    name: str


def scan_filesystem() -> list[FsEntry]:
    data_dir = AppSettings().servers_data_dir
    data_path = Path(data_dir)
    if not data_path.is_dir():
        logger.info("data/servers/ does not exist — skipping")
        return []
    entries: list[FsEntry] = []
    for entry in sorted(data_path.iterdir()):
        if entry.is_dir():
            entries.append(FsEntry(path=str(entry), name=entry.name))
    return entries


# ===================================================================
# Stage 2 — Identity Reader
# ===================================================================


class IdentityStatus(Enum):
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"


@dataclass
class IdentityResult:
    status: IdentityStatus
    identity: dict | None = None
    uid: str | None = None
    error: str | None = None


IDENTITY_SCHEMA_V1 = {"version", "uid", "manager", "schema"}


def _identity_path(dir_path: str) -> str:
    return str(Path(dir_path) / IDENTITY_DIR / IDENTITY_FILE)


def read_identity(fs_entry: FsEntry) -> IdentityResult:
    path = _identity_path(fs_entry.path)
    if not local_fs.exists(path):
        return IdentityResult(status=IdentityStatus.MISSING)

    try:
        raw = json.loads(local_fs.read_text(path))
    except (json.JSONDecodeError, OSError) as exc:
        return IdentityResult(
            status=IdentityStatus.INVALID,
            error=f"Unreadable identity file: {exc}",
        )

    if not isinstance(raw, dict):
        return IdentityResult(status=IdentityStatus.INVALID, error="Identity is not a JSON object")

    uid = raw.get("uid") or raw.get("server_id")
    if not isinstance(uid, str) or len(uid) != 32:
        return IdentityResult(
            status=IdentityStatus.INVALID,
            error=f"Invalid UID in identity: {uid!r}",
            identity=raw,
        )

    return IdentityResult(
        status=IdentityStatus.VALID,
        identity=raw,
        uid=uid,
    )


def _build_identity_doc(uid: str) -> dict:
    return {
        "version": IDENTITY_VERSION,
        "uid": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manager": "mcsmanager",
        "schema": 1,
    }


# ===================================================================
# Stage 3 — Minecraft Detector
# ===================================================================


@dataclass
class ScanOutcome:
    scanned: dict | None
    is_minecraft: bool
    is_broken: bool
    broken_reasons: list[str]


def detect_minecraft(fs_entry: FsEntry) -> ScanOutcome:
    try:
        scanned = scan_server_directory(fs_entry.path, fs=local_fs)
    except (NotADirectoryError, ValueError):
        return ScanOutcome(
            scanned=None,
            is_minecraft=False,
            is_broken=True,
            broken_reasons=["Directory is not a valid Minecraft server (empty or unreadable)"],
        )
    except Exception as exc:
        logger.warning("Unexpected scan error %s: %s", fs_entry.path, exc)
        return ScanOutcome(
            scanned=None,
            is_minecraft=False,
            is_broken=True,
            broken_reasons=[f"Scan error: {exc}"],
        )

    reasons: list[str] = []
    if not scanned.get("server_jar"):
        reasons.append("No server jar detected")
    if not scanned.get("properties"):
        reasons.append("No server.properties found or empty")
    is_broken = len(reasons) > 0
    return ScanOutcome(
        scanned=scanned,
        is_minecraft=True,
        is_broken=is_broken,
        broken_reasons=reasons,
    )


# ===================================================================
# Stage 4 — Reconciliation Planner
# ===================================================================


class ActionType(Enum):
    IMPORT = "import"
    UPDATE_BROKEN = "update_broken"
    UPDATE_REPAIRED = "update_repaired"
    UPDATE_DEPLOYMENT = "update_deployment"
    MARK_MISSING = "mark_missing"
    DELETE = "delete"
    UNCHANGED = "unchanged"
    IGNORE = "ignore"
    INVALID_IDENTITY = "invalid_identity"


@dataclass
class PlanAction:
    action: ActionType
    fs_entry: FsEntry | None = None
    identity_result: IdentityResult | None = None
    scan_outcome: ScanOutcome | None = None
    db_server: Server | None = None
    new_uid: str | None = None  # generated UID for adopted dirs


@dataclass
class ReconciliationPlan:
    actions: list[PlanAction] = field(default_factory=list)


def _servers_data_dir() -> str:
    return AppSettings().servers_data_dir


def build_plan(
    fs_entries: list[FsEntry],
    identities: list[IdentityResult],
    scans: list[ScanOutcome],
    db_servers: list[Server],
) -> ReconciliationPlan:
    plan = ReconciliationPlan()
    by_path: dict[str, int] = {e.path: i for i, e in enumerate(fs_entries)}

    db_by_id: dict[str, Server] = {str(s.id): s for s in db_servers}
    accounted: set[str] = set()
    data_dir = _servers_data_dir()

    for i, entry in enumerate(fs_entries):
        identity = identities[i]
        scan = scans[i]

        if identity.status == IdentityStatus.VALID:
            uid = identity.uid
            if uid in db_by_id:
                server = db_by_id[uid]
                accounted.add(uid)

                if scan.is_broken and server.status != ServerStatus.BROKEN:
                    plan.actions.append(PlanAction(
                        action=ActionType.UPDATE_BROKEN,
                        fs_entry=entry, identity_result=identity,
                        scan_outcome=scan, db_server=server,
                    ))
                elif not scan.is_broken and server.status == ServerStatus.BROKEN:
                    plan.actions.append(PlanAction(
                        action=ActionType.UPDATE_REPAIRED,
                        fs_entry=entry, identity_result=identity,
                        scan_outcome=scan, db_server=server,
                    ))
                else:
                    needs_deploy_update = _deployment_needs_update(server, entry, scan)
                    if needs_deploy_update:
                        plan.actions.append(PlanAction(
                            action=ActionType.UPDATE_DEPLOYMENT,
                            fs_entry=entry, identity_result=identity,
                            scan_outcome=scan, db_server=server,
                        ))
                    else:
                        plan.actions.append(PlanAction(
                            action=ActionType.UNCHANGED,
                            db_server=server,
                        ))
            else:
                plan.actions.append(PlanAction(
                    action=ActionType.IMPORT,
                    fs_entry=entry, identity_result=identity,
                    scan_outcome=scan, new_uid=uid,
                ))

        elif identity.status == IdentityStatus.MISSING:
            if scan.is_minecraft:
                plan.actions.append(PlanAction(
                    action=ActionType.IMPORT,
                    fs_entry=entry, identity_result=identity,
                    scan_outcome=scan, new_uid=uuid.uuid4().hex,
                ))
            else:
                plan.actions.append(PlanAction(
                    action=ActionType.IGNORE,
                    fs_entry=entry, identity_result=identity,
                    scan_outcome=scan,
                ))

        elif identity.status == IdentityStatus.INVALID:
            plan.actions.append(PlanAction(
                action=ActionType.INVALID_IDENTITY,
                fs_entry=entry, identity_result=identity,
                scan_outcome=scan,
            ))

    for sid, server in db_by_id.items():
        if sid in accounted:
            continue
        if _is_outside_data_dir(server, data_dir):
            continue
        if server.missing_since is not None:
            plan.actions.append(PlanAction(
                action=ActionType.DELETE,
                db_server=server,
            ))
        else:
            plan.actions.append(PlanAction(
                action=ActionType.MARK_MISSING,
                db_server=server,
            ))

    return plan


def _deployment_needs_update(server: Server, entry: FsEntry, scan: ScanOutcome) -> bool:
    if not server.deployment:
        return True
    current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
    return server.deployment.root_path != entry.path or server.deployment.startup_jar != current_jar


def _is_outside_data_dir(server: Server, data_dir: str) -> bool:
    dep = server.deployment
    if dep is None or not dep.root_path:
        return True
    try:
        root = Path(dep.root_path).resolve()
        dd = Path(data_dir).resolve()
        return not str(root).startswith(str(dd))
    except (ValueError, OSError):
        return True


# ===================================================================
# Stage 5 — Transaction Executor
# ===================================================================


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


def _build_deployment(entry: FsEntry, scan: ScanOutcome) -> ServerDeployment:
    jar = (scan.scanned or {}).get("server_jar") or "server.jar"
    return ServerDeployment(
        root_path=entry.path,
        working_directory=".",
        startup_jar=jar,
    )


def _find_name(entry: FsEntry, scan: ScanOutcome) -> str:
    return (scan.scanned or {}).get("name") or entry.name


async def execute_plan(
    plan: ReconciliationPlan,
    repo: ServerRepository,
    result: ReconciliationResult,
    pending_identities: list[tuple[str, str]],
) -> None:
    for pa in plan.actions:
        try:
            if pa.action == ActionType.IMPORT:
                await _handle_import(pa, repo, result, pending_identities)

            elif pa.action == ActionType.UPDATE_BROKEN:
                await _handle_update_broken(pa, repo, result)

            elif pa.action == ActionType.UPDATE_REPAIRED:
                await _handle_update_repaired(pa, repo, result)

            elif pa.action == ActionType.UPDATE_DEPLOYMENT:
                await _handle_update_deployment(pa, repo, result)

            elif pa.action == ActionType.MARK_MISSING:
                await _handle_mark_missing(pa, repo, result)

            elif pa.action == ActionType.DELETE:
                await _handle_delete(pa, repo, result)

            elif pa.action == ActionType.UNCHANGED:
                result.unchanged.append({
                    "server_id": str(pa.db_server.id),
                    "name": pa.db_server.name,
                })

            elif pa.action == ActionType.IGNORE:
                result.ignored.append({
                    "path": pa.fs_entry.path,
                    "reason": "No identity file and not a Minecraft server",
                })
                logger.debug("Ignored non-Minecraft directory %s", pa.fs_entry.path)

            elif pa.action == ActionType.INVALID_IDENTITY:
                result.invalid_identity.append({
                    "path": pa.fs_entry.path,
                    "error": pa.identity_result.error or "Invalid identity file",
                    "identity": pa.identity_result.identity,
                })
                logger.warning("Invalid identity in %s: %s", pa.fs_entry.path, pa.identity_result.error)

        except Exception as exc:
            logger.exception("Action failed: %s on %s", pa.action.value, _action_path(pa))
            result.errors.append({
                "path": _action_path(pa),
                "action": pa.action.value,
                "error": str(exc),
            })


def _action_path(pa: PlanAction) -> str:
    if pa.fs_entry:
        return pa.fs_entry.path
    if pa.db_server:
        return str(pa.db_server.id)
    return "unknown"


async def _handle_import(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult, pending: list[tuple[str, str]]) -> None:
    uid = pa.new_uid
    entry = pa.fs_entry
    scan = pa.scan_outcome
    server_id = ServerId(uid)

    name = _find_name(entry, scan)
    scanned_type = (scan.scanned or {}).get("server_type", "vanilla")
    try:
        server_type = ServerType(scanned_type)
    except ValueError:
        server_type = ServerType.VANILLA

    mc_version_str = (scan.scanned or {}).get("minecraft_version", "")
    if mc_version_str:
        try:
            mc_version = MinecraftVersion.parse(mc_version_str)
        except ValueError:
            mc_version = MinecraftVersion(0, 0)
    else:
        mc_version = MinecraftVersion(0, 0)

    props = _build_server_properties(scan.scanned)
    deployment = _build_deployment(entry, scan)

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

    if scan.is_broken:
        server.mark_broken()
        result.broken.append({
            "server_id": uid,
            "name": name,
            "path": entry.path,
            "reasons": scan.broken_reasons,
        })

    await repo.save(server)
    result.imported.append({
        "server_id": uid,
        "name": name,
        "path": entry.path,
        "broken": scan.is_broken,
    })
    logger.info("Imported server %s (%s) from %s", name, uid, entry.path)

    pending.append((entry.path, uid))


async def _handle_update_broken(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult) -> None:
    server = pa.db_server
    entry = pa.fs_entry
    scan = pa.scan_outcome

    if server.deployment:
        current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
        if server.deployment.root_path != entry.path or server.deployment.startup_jar != current_jar:
            server.update_deployment(_build_deployment(entry, scan))
    server.mark_broken()

    await repo.save(server)
    result.broken.append({
        "server_id": str(server.id),
        "name": server.name,
        "path": entry.path,
        "reasons": scan.broken_reasons,
    })
    result.updated.append({
        "server_id": str(server.id),
        "name": server.name,
        "path": entry.path,
    })
    logger.info("Marked server %s (%s) as BROKEN", server.name, server.id)


async def _handle_update_repaired(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult) -> None:
    server = pa.db_server
    entry = pa.fs_entry
    scan = pa.scan_outcome

    if server.deployment:
        current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
        if server.deployment.root_path != entry.path or server.deployment.startup_jar != current_jar:
            server.update_deployment(_build_deployment(entry, scan))
    server.mark_repaired()

    await repo.save(server)
    result.updated.append({
        "server_id": str(server.id),
        "name": server.name,
        "path": entry.path,
    })
    logger.info("Server %s (%s) repaired — restored to CREATED", server.name, server.id)


async def _handle_update_deployment(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult) -> None:
    server = pa.db_server
    entry = pa.fs_entry
    scan = pa.scan_outcome

    current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
    server.update_deployment(_build_deployment(entry, scan))
    await repo.save(server)
    result.updated.append({
        "server_id": str(server.id),
        "name": server.name,
        "path": entry.path,
    })
    logger.info("Updated deployment for %s (%s)", server.name, server.id)


async def _handle_mark_missing(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult) -> None:
    server = pa.db_server
    sid = str(server.id)
    server.mark_missing()
    await repo.save(server)
    result.missing.append({
        "server_id": sid,
        "name": server.name,
    })
    logger.warning("Marked server %s (%s) as missing — directory not found", server.name, sid)


async def _handle_delete(pa: PlanAction, repo: ServerRepository, result: ReconciliationResult) -> None:
    server = pa.db_server
    sid = str(server.id)
    server.mark_deleted()
    await repo.delete(server.id)
    result.deleted.append({
        "server_id": sid,
        "name": server.name,
    })
    logger.info("Deleted MISSING server %s (%s) — second pass", server.name, sid)


# ===================================================================
# Stage 6 — Identity Writer (post-commit)
# ===================================================================


def write_pending_identities(pending: list[tuple[str, str]]) -> None:
    for dir_path, uid in pending:
        try:
            identity_dir = str(Path(dir_path) / IDENTITY_DIR)
            local_fs.ensure_dir(identity_dir)
            doc = _build_identity_doc(uid)
            local_fs.write_text(
                _identity_path(dir_path),
                json.dumps(doc, indent=2),
            )
            logger.debug("Wrote identity for %s in %s", uid, dir_path)
        except Exception as exc:
            logger.error("Failed to write identity for %s in %s: %s", uid, dir_path, exc)


# ===================================================================
# Public API
# ===================================================================


async def reconcile(repo: ServerRepository) -> ReconciliationResult:
    # Stage 1 — scan filesystem
    fs_entries = scan_filesystem()
    if not fs_entries:
        return ReconciliationResult()

    # Stage 2 — read identities
    identities = [read_identity(e) for e in fs_entries]

    # Stage 3 — detect Minecraft
    scans = [detect_minecraft(e) for e in fs_entries]

    # Stage 4 — build plan
    db_servers = await repo.list()
    plan = build_plan(fs_entries, identities, scans, db_servers)

    # Stage 5 — execute plan
    result = ReconciliationResult()
    pending_identities: list[tuple[str, str]] = []
    await execute_plan(plan, repo, result, pending_identities)

    # Stage 6 — write identities post-execution (caller must have committed first)
    if pending_identities:
        write_pending_identities(pending_identities)

    _log_summary(result)
    return result


async def reconcile_now() -> ReconciliationResult:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        result = await reconcile(repo)
        await session.commit()
        return result


def _log_summary(result: ReconciliationResult) -> None:
    logger.info(
        "Reconciliation done: %d imported, %d updated, %d deleted, "
        "%d missing, %d broken, %d unchanged, %d ignored, "
        "%d invalid_identity, %d errors",
        len(result.imported), len(result.updated), len(result.deleted),
        len(result.missing), len(result.broken), len(result.unchanged),
        len(result.ignored), len(result.invalid_identity),
        len(result.errors),
    )
