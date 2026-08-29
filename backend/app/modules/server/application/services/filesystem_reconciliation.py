from __future__ import annotations

import json
import logging
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from app.core.config import AppSettings
from app.core.identity import IDENTITY
from app.modules.server.application.services.import_service import scan_server_directory
from app.modules.server.domain.aggregate import Server, ServerStatus
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
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.reconciliation.fs")

# ---------------------------------------------------------------------------
# Reconciliation Result
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
    identity_written: list[dict] = field(default_factory=list)
    total_dirs_found: int = 0
    total_minecraft_dirs: int = 0
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0

    @property
    def total_imported(self) -> int:
        return len(self.imported)

    @property
    def total_updated(self) -> int:
        return len(self.updated)

    @property
    def total_deleted(self) -> int:
        return len(self.deleted)

    @property
    def total_missing(self) -> int:
        return len(self.missing)

    @property
    def total_broken(self) -> int:
        return len(self.broken)

    @property
    def total_unchanged(self) -> int:
        return len(self.unchanged)

    @property
    def total_ignored(self) -> int:
        return len(self.ignored)

    @property
    def total_invalid_identity(self) -> int:
        return len(self.invalid_identity)

    @property
    def total_errors(self) -> int:
        return len(self.errors)


# ===================================================================
# Stage 1 — Filesystem Scanner
# ===================================================================


@dataclass
class FsEntry:
    path: str
    name: str


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
    uid: str = ""
    identity: dict | None = None
    error: str | None = None


# ===================================================================
# Stage 3 — Minecraft Detector
# ===================================================================


class ScanCategory(Enum):
    MINECRAFT_VALID = "valid"
    MINECRAFT_BROKEN = "broken"
    NOT_MINECRAFT = "not_minecraft"
    SCAN_FAILED = "scan_failed"


@dataclass
class ScanOutcome:
    scanned: dict | None
    category: ScanCategory
    is_minecraft: bool
    is_broken: bool
    broken_reasons: list[str]
    scan_error: str | None = None


# ===================================================================
# Stage 4 — Plan
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
    REPAIR_IDENTITY = "repair_identity"


@dataclass
class PlanAction:
    action: ActionType
    fs_entry: FsEntry | None = None
    identity: IdentityResult | None = None
    scan: ScanOutcome | None = None
    db_server: Server | None = None


@dataclass
class ReconciliationPlan:
    actions: list[PlanAction] = field(default_factory=list)


# ===================================================================
# Filesystem Reconciliation Service
# ===================================================================


class FilesystemReconciliationService:
    def __init__(self, repo: ServerRepository, fs: FileSystem | None = None) -> None:
        self._repo = repo
        self._fs = fs or local_fs
        self._last_plan: ReconciliationPlan | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(
        self,
        dry_run: bool = False,
    ) -> ReconciliationResult:
        started_at = datetime.now(UTC)
        start_ms = time.monotonic()
        entries = self._scan_filesystem()
        if not entries:
            logger.info("data/servers/ does not exist or is empty — nothing to reconcile")
            return ReconciliationResult()

        identities = self._read_identities(entries)
        scans = self._detect_minecraft(entries)
        db_servers = await self._repo.list()
        self._last_plan = self._build_plan(entries, identities, scans, db_servers)

        total_mc = sum(1 for s in scans if s.is_minecraft)
        total_dirs = len(entries)

        if dry_run:
            result = self._plan_to_result(self._last_plan)
            result.total_dirs_found = total_dirs
            result.total_minecraft_dirs = total_mc
            result.started_at = started_at.isoformat()
            result.finished_at = datetime.now(UTC).isoformat()
            result.duration_ms = (time.monotonic() - start_ms) * 1000
            return result

        result = await self._execute_plan(self._last_plan)
        result.total_dirs_found = total_dirs
        result.total_minecraft_dirs = total_mc
        finished_at = datetime.now(UTC)
        result.started_at = started_at.isoformat()
        result.finished_at = finished_at.isoformat()
        result.duration_ms = (time.monotonic() - start_ms) * 1000
        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Stage 1 — Scan filesystem directories
    # ------------------------------------------------------------------

    def _scan_filesystem(self) -> list[FsEntry]:
        data_dir = AppSettings().servers_data_dir
        data_path = Path(data_dir)
        if not data_path.is_dir():
            return []
        entries: list[FsEntry] = []
        for entry in sorted(data_path.iterdir()):
            if entry.is_dir():
                entries.append(FsEntry(path=str(entry), name=entry.name))
        return entries

    # ------------------------------------------------------------------
    # Stage 2 — Read (or generate) identity for every directory
    # ------------------------------------------------------------------

    def _read_identities(self, entries: list[FsEntry]) -> list[IdentityResult]:
        return [self._read_single_identity(e) for e in entries]

    def _identity_paths(self, dir_path: str) -> list[str]:
        """Return candidate identity file paths in priority order: NEW first, then LEGACY."""
        base = Path(dir_path)
        return [
            str(base / IDENTITY.identity_dir_new / IDENTITY.identity_file),  # NEW primary
            str(base / IDENTITY.identity_dir_legacy / IDENTITY.identity_file),  # LEGACY fallback
        ]

    def _read_single_identity(self, entry: FsEntry) -> IdentityResult:
        """Try NEW location first, then LEGACY. Accept both manager values.
        If LEGACY is read successfully, trigger migration write to NEW location.
        """
        for path in self._identity_paths(entry.path):
            if not self._fs.exists(path):
                continue
            try:
                raw = json.loads(self._fs.read_text(path))
            except (json.JSONDecodeError, OSError) as exc:
                # Corrupted file — try next location instead of failing fast
                logger.warning(
                    "Failed to read identity at %s: %s; trying fallback",
                    path,
                    exc,
                )
                continue

            if not isinstance(raw, dict):
                continue  # try next location

            version = raw.get("version", 0)
            if version != IDENTITY.identity_version:
                continue  # try next location

            uid = raw.get("uid") or raw.get("server_id")
            if not isinstance(uid, str) or len(uid) != 32:
                continue  # try next location

            # ACCEPT both manager values (field was never validated before)
            manager = raw.get("manager", "")
            if manager not in (
                IDENTITY.manager_field_legacy,
                IDENTITY.manager_field_new,
            ):
                logger.debug(
                    "Identity manager field %r not in expected set; accepting anyway",
                    manager,
                )

            # MIGRATION-ON-READ: if we read from legacy path, write new identity atomically
            legacy_path = str(
                Path(entry.path) / IDENTITY.identity_dir_legacy / IDENTITY.identity_file
            )
            if path == legacy_path:
                try:
                    self._write_single_identity_atomic(entry.path, uid, location="new")
                    logger.info(
                        "Migrated identity for %s from legacy to new location",
                        uid,
                    )
                except Exception as exc:
                    logger.warning("Failed to migrate identity for %s: %s", uid, exc)

            return IdentityResult(status=IdentityStatus.VALID, uid=uid, identity=raw)

        return IdentityResult(status=IdentityStatus.MISSING)

    # ------------------------------------------------------------------
    # Stage 3 — Detect whether each directory is a Minecraft server
    # ------------------------------------------------------------------

    def _detect_minecraft(self, entries: list[FsEntry]) -> list[ScanOutcome]:
        return [self._detect_single(e) for e in entries]

    def _detect_single(self, entry: FsEntry) -> ScanOutcome:
        try:
            scanned = scan_server_directory(entry.path, fs=self._fs)
        except (NotADirectoryError, ValueError) as exc:
            return ScanOutcome(
                scanned=None,
                category=ScanCategory.SCAN_FAILED,
                is_minecraft=False,
                is_broken=True,
                broken_reasons=[str(exc)],
                scan_error=str(exc),
            )
        except Exception as exc:
            logger.warning("Unexpected scan error %s: %s", entry.path, exc)
            return ScanOutcome(
                scanned=None,
                category=ScanCategory.SCAN_FAILED,
                is_minecraft=False,
                is_broken=True,
                broken_reasons=[f"Scan error: {exc}"],
                scan_error=str(exc),
            )

        reasons: list[str] = []
        has_executable = bool(
            scanned.get("server_jar")
            or scanned.get("run_script")
            or self._fs.exists(str(Path(entry.path) / "run.sh"))
            or self._fs.exists(str(Path(entry.path) / "run.bat"))
        )
        if not has_executable:
            reasons.append("No server jar or run script detected")
        if not scanned.get("properties"):
            reasons.append("No server.properties found or empty")

        if reasons:
            return ScanOutcome(
                scanned=scanned,
                category=ScanCategory.MINECRAFT_BROKEN,
                is_minecraft=True,
                is_broken=True,
                broken_reasons=reasons,
            )

        return ScanOutcome(
            scanned=scanned,
            category=ScanCategory.MINECRAFT_VALID,
            is_minecraft=True,
            is_broken=False,
            broken_reasons=[],
        )

    # ------------------------------------------------------------------
    # Stage 4 — Build reconciliation plan (no writes)
    # ------------------------------------------------------------------

    def _build_plan(
        self,
        entries: list[FsEntry],
        identities: list[IdentityResult],
        scans: list[ScanOutcome],
        db_servers: list[Server],
    ) -> ReconciliationPlan:
        plan = ReconciliationPlan()
        db_by_id: dict[str, Server] = {str(s.id): s for s in db_servers}
        accounted: set[str] = set()
        data_dir = self._servers_data_dir()

        for i, entry in enumerate(entries):
            identity = identities[i]
            scan = scans[i]

            if scan.category == ScanCategory.SCAN_FAILED:
                plan.actions.append(
                    PlanAction(
                        action=ActionType.IGNORE,
                        fs_entry=entry,
                        identity=identity,
                        scan=scan,
                    )
                )
                continue

            if identity.status == IdentityStatus.VALID:
                uid = identity.uid
                if uid in db_by_id:
                    server = db_by_id[uid]
                    accounted.add(uid)
                    self._classify_existing(server, entry, scan, plan)
                else:
                    plan.actions.append(
                        PlanAction(
                            action=ActionType.IMPORT,
                            fs_entry=entry,
                            identity=identity,
                            scan=scan,
                        )
                    )

            elif identity.status == IdentityStatus.MISSING:
                if scan.is_minecraft:
                    uid = uuid.uuid4().hex
                    plan.actions.append(
                        PlanAction(
                            action=ActionType.IMPORT,
                            fs_entry=entry,
                            identity=IdentityResult(status=IdentityStatus.MISSING, uid=uid),
                            scan=scan,
                        )
                    )
                else:
                    plan.actions.append(
                        PlanAction(
                            action=ActionType.IGNORE,
                            fs_entry=entry,
                            identity=IdentityResult(
                                status=IdentityStatus.MISSING, uid=uuid.uuid4().hex
                            ),
                            scan=scan,
                        )
                    )

            elif identity.status == IdentityStatus.INVALID:
                plan.actions.append(
                    PlanAction(
                        action=ActionType.REPAIR_IDENTITY,
                        fs_entry=entry,
                        identity=identity,
                        scan=scan,
                    )
                )

        for sid, server in db_by_id.items():
            if sid in accounted:
                continue
            if self._is_outside_data_dir(server, data_dir):
                continue
            if server.missing_since is not None:
                plan.actions.append(
                    PlanAction(
                        action=ActionType.DELETE,
                        db_server=server,
                    )
                )
            else:
                plan.actions.append(
                    PlanAction(
                        action=ActionType.MARK_MISSING,
                        db_server=server,
                    )
                )

        return plan

    def _classify_existing(
        self,
        server: Server,
        entry: FsEntry,
        scan: ScanOutcome,
        plan: ReconciliationPlan,
    ) -> None:
        if server.status == ServerStatus.PROVISIONING:
            plan.actions.append(
                PlanAction(
                    action=ActionType.UNCHANGED,
                    db_server=server,
                )
            )
            return

        if scan.is_broken and server.status != ServerStatus.BROKEN:
            plan.actions.append(
                PlanAction(
                    action=ActionType.UPDATE_BROKEN,
                    fs_entry=entry,
                    scan=scan,
                    db_server=server,
                )
            )
        elif not scan.is_broken and server.status == ServerStatus.BROKEN:
            plan.actions.append(
                PlanAction(
                    action=ActionType.UPDATE_REPAIRED,
                    fs_entry=entry,
                    scan=scan,
                    db_server=server,
                )
            )
        elif self._deployment_needs_update(server, entry, scan):
            plan.actions.append(
                PlanAction(
                    action=ActionType.UPDATE_DEPLOYMENT,
                    fs_entry=entry,
                    scan=scan,
                    db_server=server,
                )
            )
        else:
            plan.actions.append(
                PlanAction(
                    action=ActionType.UNCHANGED,
                    db_server=server,
                )
            )

    def _deployment_needs_update(self, server: Server, entry: FsEntry, scan: ScanOutcome) -> bool:
        if not server.deployment:
            return True
        scanned = scan.scanned or {}
        current_jar = scanned.get("server_jar") or "server.jar"
        if scanned.get("server_name_declared"):
            disk_name = (scanned.get("name") or "").strip()
            if disk_name and disk_name != server.name:
                return True
        return (
            server.deployment.root_path != entry.path
            or server.deployment.startup_jar != current_jar
        )

    def _is_outside_data_dir(self, server: Server, data_dir: str) -> bool:
        dep = server.deployment
        if dep is None or not dep.root_path:
            return True
        try:
            root = Path(dep.root_path).resolve()
            dd = Path(data_dir).resolve()
            return not str(root).startswith(str(dd))
        except (ValueError, OSError):
            return True

    def _servers_data_dir(self) -> str:
        return AppSettings().servers_data_dir

    # ------------------------------------------------------------------
    # Stage 5 — Execute plan (writes to DB)
    # ------------------------------------------------------------------

    async def _execute_plan(self, plan: ReconciliationPlan) -> ReconciliationResult:
        result = ReconciliationResult()
        for pa in plan.actions:
            try:
                handler = self._handler_for(pa.action)
                await handler(pa, result)
            except Exception as exc:
                logger.exception("Action failed: %s on %s", pa.action.value, self._action_path(pa))
                result.errors.append(
                    {
                        "path": self._action_path(pa),
                        "action": pa.action.value,
                        "error": str(exc),
                    }
                )
        return result

    def _handler_for(self, action: ActionType):
        handlers = {
            ActionType.IMPORT: self._handle_import,
            ActionType.UPDATE_BROKEN: self._handle_update_broken,
            ActionType.UPDATE_REPAIRED: self._handle_update_repaired,
            ActionType.UPDATE_DEPLOYMENT: self._handle_update_deployment,
            ActionType.MARK_MISSING: self._handle_mark_missing,
            ActionType.DELETE: self._handle_delete,
            ActionType.UNCHANGED: self._handle_unchanged,
            ActionType.IGNORE: self._handle_ignore,
            ActionType.INVALID_IDENTITY: self._handle_invalid_identity,
            ActionType.REPAIR_IDENTITY: self._handle_repair_identity,
        }
        return handlers[action]

    def _action_path(self, pa: PlanAction) -> str:
        if pa.fs_entry:
            return pa.fs_entry.path
        if pa.db_server:
            return str(pa.db_server.id)
        return "unknown"

    async def _handle_import(self, pa: PlanAction, result: ReconciliationResult) -> None:
        uid = pa.identity.uid
        entry = pa.fs_entry
        scan = pa.scan

        self._write_single_identity(entry.path, uid, result)

        server = self._build_server_from_scan(ServerId(uid), entry, scan)

        if scan.is_broken:
            server.mark_broken()
            result.broken.append(
                {
                    "server_id": uid,
                    "name": server.name,
                    "path": entry.path,
                    "reasons": scan.broken_reasons,
                }
            )

        await self._repo.save(server)
        result.imported.append(
            {
                "server_id": uid,
                "name": server.name,
                "path": entry.path,
                "broken": scan.is_broken,
            }
        )
        logger.info("Imported server %s (%s) from %s", server.name, uid, entry.path)

    async def _handle_update_broken(self, pa: PlanAction, result: ReconciliationResult) -> None:
        server = pa.db_server
        entry = pa.fs_entry
        scan = pa.scan

        if server.deployment:
            current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
            if (
                server.deployment.root_path != entry.path
                or server.deployment.startup_jar != current_jar
            ):
                server.update_deployment(self._build_deployment(entry, scan))
        server.mark_broken()

        await self._repo.save(server)
        result.broken.append(
            {
                "server_id": str(server.id),
                "name": server.name,
                "path": entry.path,
                "reasons": scan.broken_reasons,
            }
        )
        result.updated.append(
            {
                "server_id": str(server.id),
                "name": server.name,
                "path": entry.path,
            }
        )
        logger.info("Marked server %s (%s) as BROKEN", server.name, server.id)

    async def _handle_update_repaired(self, pa: PlanAction, result: ReconciliationResult) -> None:
        server = pa.db_server
        entry = pa.fs_entry
        scan = pa.scan

        if server.deployment:
            current_jar = (scan.scanned or {}).get("server_jar") or "server.jar"
            if (
                server.deployment.root_path != entry.path
                or server.deployment.startup_jar != current_jar
            ):
                server.update_deployment(self._build_deployment(entry, scan))
        server.mark_repaired()

        await self._repo.save(server)
        result.updated.append(
            {
                "server_id": str(server.id),
                "name": server.name,
                "path": entry.path,
            }
        )
        logger.info("Server %s (%s) repaired — restored to CREATED", server.name, server.id)

    async def _handle_update_deployment(self, pa: PlanAction, result: ReconciliationResult) -> None:
        server = pa.db_server
        entry = pa.fs_entry
        scan = pa.scan

        scanned = scan.scanned or {}
        if scanned.get("server_name_declared"):
            disk_name = (scanned.get("name") or "").strip()
            if disk_name and disk_name != server.name:
                server.rename(disk_name)

        server.update_deployment(self._build_deployment(entry, scan))
        await self._repo.save(server)
        result.updated.append(
            {
                "server_id": str(server.id),
                "name": server.name,
                "path": entry.path,
            }
        )
        logger.info("Updated deployment for %s (%s)", server.name, server.id)

    async def _handle_mark_missing(self, pa: PlanAction, result: ReconciliationResult) -> None:
        server = pa.db_server
        sid = str(server.id)
        server.mark_missing()
        await self._repo.save(server)
        result.missing.append(
            {
                "server_id": sid,
                "name": server.name,
            }
        )
        logger.warning("Marked server %s (%s) as missing — directory not found", server.name, sid)

    async def _handle_delete(self, pa: PlanAction, result: ReconciliationResult) -> None:
        server = pa.db_server
        sid = str(server.id)
        server.mark_deleted()
        await self._repo.delete(server.id)
        result.deleted.append(
            {
                "server_id": sid,
                "name": server.name,
            }
        )
        logger.info("Deleted MISSING server %s (%s) — second pass", server.name, sid)

    async def _handle_unchanged(self, pa: PlanAction, result: ReconciliationResult) -> None:
        result.unchanged.append(
            {
                "server_id": str(pa.db_server.id),
                "name": pa.db_server.name,
            }
        )

    async def _handle_ignore(self, pa: PlanAction, result: ReconciliationResult) -> None:
        self._write_single_identity(pa.fs_entry.path, pa.identity.uid, result)
        result.ignored.append(
            {
                "path": pa.fs_entry.path,
                "reason": "Not a Minecraft server",
            }
        )
        logger.debug("Ignored non-Minecraft directory %s", pa.fs_entry.path)

    async def _handle_invalid_identity(self, pa: PlanAction, result: ReconciliationResult) -> None:
        result.invalid_identity.append(
            {
                "path": pa.fs_entry.path,
                "error": pa.identity.error or "Invalid identity file",
                "identity": pa.identity.identity,
            }
        )
        logger.warning("Invalid identity in %s: %s", pa.fs_entry.path, pa.identity.error)

    async def _handle_repair_identity(self, pa: PlanAction, result: ReconciliationResult) -> None:
        new_uid = uuid.uuid4().hex
        self._write_single_identity(pa.fs_entry.path, new_uid, result)
        logger.info("Repaired identity in %s → new UID: %s", pa.fs_entry.path, new_uid)

        new_scan = self._detect_single(pa.fs_entry)
        if new_scan.category == ScanCategory.SCAN_FAILED:
            result.ignored.append(
                {
                    "path": pa.fs_entry.path,
                    "reason": f"Identity repaired but scan failed: {new_scan.scan_error}",
                }
            )
            return

        if not new_scan.is_minecraft:
            result.ignored.append(
                {
                    "path": pa.fs_entry.path,
                    "reason": "Identity repaired but directory is not a Minecraft server",
                }
            )
            return

        server = self._build_server_from_scan(ServerId(new_uid), pa.fs_entry, new_scan)

        if new_scan.is_broken:
            server.mark_broken()
            result.broken.append(
                {
                    "server_id": new_uid,
                    "name": server.name,
                    "path": pa.fs_entry.path,
                    "reasons": new_scan.broken_reasons,
                }
            )

        await self._repo.save(server)
        result.imported.append(
            {
                "server_id": new_uid,
                "name": server.name,
                "path": pa.fs_entry.path,
                "broken": new_scan.is_broken,
                "repaired_identity": True,
            }
        )
        logger.info("Imported server after identity repair: %s (%s)", server.name, new_uid)

    # ------------------------------------------------------------------
    # Build helpers (reuse scan_server_directory output)
    # ------------------------------------------------------------------

    def _build_server_properties(self, scanned: dict | None) -> ServerProperties:
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

    def _build_deployment(self, entry: FsEntry, scan: ScanOutcome) -> ServerDeployment:
        jar = (scan.scanned or {}).get("server_jar") or "server.jar"
        run_script = (scan.scanned or {}).get("run_script")
        has_run = bool(
            run_script
            or self._fs.exists(str(Path(entry.path) / "run.sh"))
            or self._fs.exists(str(Path(entry.path) / "run.bat"))
        )
        startup_cmd = (
            f"bash {run_script or 'run.sh'} nogui"
            if (has_run or jar.endswith((".sh", ".bat")))
            else ""
        )
        return ServerDeployment(
            root_path=entry.path,
            working_directory=".",
            startup_jar=jar,
            startup_command=startup_cmd,
        )

    def _find_name(self, entry: FsEntry, scan: ScanOutcome) -> str:
        return (scan.scanned or {}).get("name") or entry.name

    # ------------------------------------------------------------------
    # Shared Builder — constructs a Server domain object from scan data.
    # Centralizes property/deployment construction so ImportService
    # scan output is used directly without duplicating the mapping.
    # ------------------------------------------------------------------

    def _build_server_from_scan(
        self, server_id: ServerId, entry: FsEntry, scan: ScanOutcome
    ) -> Server:
        name = self._find_name(entry, scan)
        scanned_type = (scan.scanned or {}).get("server_type", "vanilla")
        try:
            server_type = ServerType(scanned_type)
        except ValueError:
            server_type = ServerType.VANILLA

        mc_version_str = (scan.scanned or {}).get("minecraft_version", "")
        mc_version = (
            MinecraftVersion.parse(mc_version_str) if mc_version_str else MinecraftVersion(0, 0)
        )

        props = self._build_server_properties(scan.scanned)
        deployment = self._build_deployment(entry, scan)

        launch_config = None
        run_script = (scan.scanned or {}).get("run_script")
        server_jar = (scan.scanned or {}).get("server_jar") or ""
        has_run = bool(
            run_script
            or self._fs.exists(str(Path(entry.path) / "run.sh"))
            or self._fs.exists(str(Path(entry.path) / "run.bat"))
        )
        if (
            has_run
            or server_jar.endswith((".sh", ".bat"))
            or server_type in (ServerType.FORGE, ServerType.NEOFORGE)
        ):
            script_cmd = ["bash", run_script or "run.sh", "nogui"]
            launch_config = LaunchConfiguration(startup_command=script_cmd)

        return Server(
            server_id=server_id,
            name=name,
            server_type=server_type,
            minecraft_version=mc_version,
            memory=MemoryAllocation(min_mb=1024, max_mb=2048),
            java_args=JavaArguments(),
            properties=props,
            deployment=deployment,
            launch_config=launch_config,
        )

    # ------------------------------------------------------------------
    # Identity Writer — write identity file for a single directory
    # Called DURING _execute_plan() (before DB commit) for write-ahead safety.
    # ------------------------------------------------------------------

    def _write_single_identity(
        self, dir_path: str, uid: str, result: ReconciliationResult | None = None
    ) -> None:
        """Write identity to BOTH locations atomically (write-to-temp-then-rename).
        Called by _handle_import, _handle_ignore, _handle_repair_identity.
        """
        # Write NEW (primary) atomically
        self._write_single_identity_atomic(dir_path, uid, location="new", result=result)
        # Write LEGACY (for backward compat during transition) atomically
        self._write_single_identity_atomic(dir_path, uid, location="legacy", result=result)

    def _write_single_identity_atomic(
        self,
        dir_path: str,
        uid: str,
        location: str,  # "new" or "legacy"
        result: ReconciliationResult | None = None,
    ) -> None:
        """Atomic write: write to temp file, then rename over target."""
        try:
            if location == "new":
                identity_dir = str(Path(dir_path) / IDENTITY.identity_dir_new)
                target_path = str(
                    Path(dir_path) / IDENTITY.identity_dir_new / IDENTITY.identity_file
                )
                doc = self._build_identity_doc_new(uid)
            else:
                identity_dir = str(Path(dir_path) / IDENTITY.identity_dir_legacy)
                target_path = str(
                    Path(dir_path) / IDENTITY.identity_dir_legacy / IDENTITY.identity_file
                )
                doc = self._build_identity_doc_legacy(uid)

            self._fs.ensure_dir(identity_dir)

            # Atomic write: write to temp, then rename
            # Use same directory for temp to ensure rename is atomic on POSIX
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=identity_dir,
                prefix=f".{IDENTITY.identity_file}.tmp.",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(doc, tmp, indent=2)
                tmp_path = tmp.name

            # Atomic rename (POSIX guarantee: no partial file visible)
            self._fs.rename(tmp_path, target_path)

            if result is not None:
                result.identity_written.append({"path": dir_path, "uid": uid, "location": location})
            logger.debug("Wrote %s identity for %s in %s", location, uid, dir_path)

        except Exception as exc:
            logger.error(
                "Failed to write %s identity for %s in %s: %s",
                location,
                uid,
                dir_path,
                exc,
            )
            # Clean up temp file if it exists
            try:
                if "tmp_path" in locals() and self._fs.exists(tmp_path):
                    self._fs.remove(tmp_path)
            except Exception:
                pass
            raise

    def _build_identity_doc_new(self, uid: str) -> dict:
        return {
            "version": IDENTITY.identity_version,
            "uid": uid,
            "created_at": datetime.now(UTC).isoformat(),
            "manager": IDENTITY.manager_field_new,
            "schema_version": IDENTITY.schema_version,
        }

    def _build_identity_doc_legacy(self, uid: str) -> dict:
        return {
            "version": IDENTITY.identity_version,
            "uid": uid,
            "created_at": datetime.now(UTC).isoformat(),
            "manager": IDENTITY.manager_field_legacy,
            "schema_version": IDENTITY.schema_version,
        }

    def _plan_to_result(self, plan: ReconciliationPlan) -> ReconciliationResult:
        result = ReconciliationResult()
        for pa in plan.actions:
            if pa.action == ActionType.IMPORT:
                result.imported.append(
                    {
                        "path": pa.fs_entry.path,
                        "uid": pa.identity.uid,
                        "broken": pa.scan.is_broken,
                    }
                )
            elif pa.action == ActionType.UPDATE_BROKEN:
                result.broken.append(
                    {
                        "server_id": str(pa.db_server.id),
                        "name": pa.db_server.name,
                        "reasons": pa.scan.broken_reasons,
                    }
                )
            elif (
                pa.action == ActionType.UPDATE_REPAIRED or pa.action == ActionType.UPDATE_DEPLOYMENT
            ):
                result.updated.append(
                    {
                        "server_id": str(pa.db_server.id),
                        "name": pa.db_server.name,
                    }
                )
            elif pa.action == ActionType.MARK_MISSING:
                result.missing.append(
                    {
                        "server_id": str(pa.db_server.id),
                        "name": pa.db_server.name,
                    }
                )
            elif pa.action == ActionType.DELETE:
                result.deleted.append(
                    {
                        "server_id": str(pa.db_server.id),
                        "name": pa.db_server.name,
                    }
                )
            elif pa.action == ActionType.UNCHANGED:
                result.unchanged.append(
                    {
                        "server_id": str(pa.db_server.id),
                        "name": pa.db_server.name,
                    }
                )
            elif pa.action == ActionType.IGNORE:
                result.ignored.append(
                    {
                        "path": pa.fs_entry.path,
                    }
                )
            elif pa.action == ActionType.INVALID_IDENTITY:
                result.invalid_identity.append(
                    {
                        "path": pa.fs_entry.path,
                        "error": pa.identity.error,
                    }
                )
            elif pa.action == ActionType.REPAIR_IDENTITY:
                result.ignored.append(
                    {
                        "path": pa.fs_entry.path,
                        "reason": "Identity will be repaired and rescanned",
                    }
                )
        return result

    def _log_summary(self, result: ReconciliationResult) -> None:
        logger.info(
            "Reconciliation done: %d imported, %d updated, %d deleted, "
            "%d missing, %d broken, %d unchanged, %d ignored, "
            "%d invalid_identity, %d errors",
            result.total_imported,
            result.total_updated,
            result.total_deleted,
            result.total_missing,
            result.total_broken,
            result.total_unchanged,
            result.total_ignored,
            result.total_invalid_identity,
            result.total_errors,
        )


# ===================================================================
# Convenience function (backward-compatible)
# ===================================================================


async def reconcile(repo: ServerRepository, dry_run: bool = False) -> ReconciliationResult:
    service = FilesystemReconciliationService(repo)
    return await service.reconcile(dry_run=dry_run)


async def reconcile_now(dry_run: bool = False) -> ReconciliationResult:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        service = FilesystemReconciliationService(repo)
        result = await service.reconcile(dry_run=dry_run)
        if not dry_run:
            await session.commit()
        return result
