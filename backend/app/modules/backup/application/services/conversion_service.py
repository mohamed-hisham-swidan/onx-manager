# P7-2 Conversion API & contracts (OD-v8.6-3).

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from app.core.config import ConfigFactory
from app.core.exceptions import (
    CasUnsupportedPlatformError,
    ConflictError,
    GitRepositoryStateError,
    MCSError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout, validate_server_segment
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.domain.aggregate import BackupJob, BackupJobId, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import create_tier1_snapshot
from app.modules.server.domain.aggregate import ServerMode
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.application.baseline_adoption import (
    ensure_simple_baseline_lockfile,
    stage_and_ingest,
)
from app.modules.versioning.application.loader_ref import derive_loader_ref
from app.modules.versioning.application.lockfile_service import LockfileService, dump_lockfile
from app.modules.versioning.domain.lockfile import LockfileV21
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.server_tree_scanner import scan_server_tree

logger = logging.getLogger(__name__)

_CLONE_FIELDS = (
    "server_type",
    "minecraft_version",
    "memory_min_mb",
    "memory_max_mb",
    "java_args",
    "cpu_cores",
    "cpu_affinity",
    "group_id",
    "motd",
    "max_players",
    "gamemode",
    "difficulty",
    "spawn_protection",
    "pvp",
    "enable_command_block",
    "online_mode",
    "whitelist_enabled",
    "view_distance",
    "simulation_distance",
    "provider",
    "owner_id",
    "working_directory",
    "startup_jar",
    "startup_command",
    "primary_world",
    "launch_config_json",
    "bot_verification_settings",
    "startup_timeout_seconds",
    "health_gate_boot_timeout_seconds",
    "install_optional_server_files",
    "allow_experimental_paper_builds",
    "download_host_allowlist_json",
    "max_concurrent_branch_runs",
)


class ConversionError(MCSError):
    """Raised when a mode conversion cannot be performed."""

    def __init__(
        self,
        message: str = "",
        *,
        http_status: int = 409,
        code: str = "CONVERSION_FAILED",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or "Conversion failed",
            code=code,
            http_status=http_status,
            details=details or {},
        )


@dataclass
class ConversionResult:
    server_id: str
    from_mode: str
    to_mode: str
    backup_id: str | None = None
    class_c_snapshot_id: str | None = None
    lockfile_sha256: str | None = None
    new_server_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


SimpleToAdvancedResult = ConversionResult
AdvancedToSimpleResult = ConversionResult


def _backup_local_dir() -> Path:
    """Return the local Tier-1 snapshot root.

    ``AppSettings`` exposes the backup root as ``backup_storage_path`` (env
    ``ONX_BACKUP_STORAGE_PATH``). ``backup_local_dir`` is accepted as a
    forward-compatible alias because the P7-1 backup task uses that name.
    """
    settings = ConfigFactory.global_settings()
    raw = getattr(settings, "backup_local_dir", None) or settings.backup_storage_path
    return Path(raw) / "tier1"


def _model_mode(model: ServerModel) -> str:
    return str(cast(Any, model).mode or "").lower()


def _model_status(model: ServerModel) -> str:
    return str(cast(Any, model).status or "").upper()


def _server_root(model: ServerModel, domain_server: Any) -> Path:
    deployment = getattr(domain_server, "deployment", None)
    if deployment is not None:
        directory = getattr(deployment, "server_directory", None)
        if callable(directory):
            raw = str(directory() or "")
            if raw:
                return Path(os.path.abspath(raw))
    raw_root = str(cast(Any, model).root_path or "")
    if not raw_root:
        raise ValidationError("Server has no deployment root", field="root_path")
    return Path(os.path.abspath(raw_root))


def _main_sha(repo_git: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "--git-dir", str(repo_git), "rev-parse", "main"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:  # noqa: BLE001 - converted to a domain error below
        raise GitRepositoryStateError(
            f"Advanced server has no usable main branch: {exc}"
        ) from exc
    sha = result.stdout.strip()
    if not sha:
        raise GitRepositoryStateError("Advanced server has no main branch")
    return sha


def _new_server_root(source_root: Path, new_id: str) -> Path:
    settings = ConfigFactory.global_settings()
    raw_dir = str(getattr(settings, "servers_data_dir", "") or "")
    if raw_dir:
        candidate = Path(os.path.abspath(raw_dir))
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate / new_id
    return source_root.parent / new_id


def _strip_git_association(root: Path) -> None:
    shutil.rmtree(root / ".git", ignore_errors=True)
    shutil.rmtree(root / ".onx", ignore_errors=True)
    for relpath in (".git", ".onx"):
        candidate = root / relpath
        if candidate.exists() or candidate.is_symlink():
            raise ValidationError(
                f"New server root '{root}' still contains Git association '{relpath}'"
            )


class ConversionService:
    def __init__(
        self,
        layout: HostStateLayout | None = None,
        *,
        session_factory: Any = None,
        class_c_service: ClassCSnapshotService | None = None,
    ) -> None:
        self._layout = layout if layout is not None else ensure_host_state_layout()
        self._session_factory = session_factory
        self._class_c_service = class_c_service

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory
        from app.core.persistence.db import database

        return database.session_factory

    async def _get_event_bus(self, event_bus):
        if event_bus is not None:
            return event_bus
        try:
            from app.api.deps import get_event_bus

            return await get_event_bus()
        except Exception:  # noqa: BLE001 - event publication is best effort
            return None

    async def _load_model(self, session, server_id: str) -> ServerModel:
        model = await session.get(ServerModel, server_id)
        if model is None:
            raise ConversionError(
                f"Server '{server_id}' not found",
                http_status=404,
                code="NOT_FOUND",
            )
        return model

    async def _create_tier1_backup(self, sid: str, server_root: Path) -> str:
        backup_id = uuid.uuid4().hex
        snapshots_root = _backup_local_dir()
        snapshots_root.mkdir(parents=True, exist_ok=True)

        async with UnitOfWork() as uow:
            repo = SQLBackupRepository(uow.session)
            job = BackupJob.create_tier1(
                backup_id=BackupJobId(backup_id),
                server_id=ServerId(sid),
                backup_type=BackupType.FULL,
                pinned=True,
            )
            await repo.save_job(job)

        try:
            snapshot = await create_tier1_snapshot(
                server_id=sid,
                server_dir=server_root,
                snapshots_root=snapshots_root,
                backup_id=backup_id,
                is_running=False,
                locks_dir=self._layout.locks,
            )
        except Exception as exc:  # noqa: BLE001 - record the failed safety backup
            try:
                async with UnitOfWork() as uow:
                    repo = SQLBackupRepository(uow.session)
                    failed = await repo.get_job(BackupJobId(backup_id))
                    failed.mark_failed(str(exc)[:500])
                    await repo.save_job(failed)
            except Exception:  # noqa: BLE001 - never mask the snapshot failure
                logger.warning("Failed to mark Tier-1 backup %s failed", backup_id, exc_info=True)
            raise

        async with UnitOfWork() as uow:
            repo = SQLBackupRepository(uow.session)
            completed = await repo.get_job(BackupJobId(backup_id))
            completed.mark_completed(
                size_bytes=snapshot.size_bytes,
                checksum=snapshot.checksum,
                storage_path=snapshot.snapshot_dir,
            )
            await repo.save_job(completed)
        return backup_id

    async def _ensure_lockfile(
        self, sid: str, server_root: Path, domain_server: Any
    ) -> tuple[LockfileV21, int]:
        adoption = await ensure_simple_baseline_lockfile(sid)
        lockfile = LockfileService(self._layout).read(sid)
        if lockfile is not None:
            return lockfile, adoption.cas_ingested

        report = scan_server_tree(server_root)
        if report.truncated:
            raise ValidationError("Server tree scan was truncated; cannot convert")

        server_meta_dir = self._layout.server_meta_dir(sid)
        server_meta_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        cas = ArtifactCas(self._layout.cas)
        ingested = [
            stage_and_ingest(server_root, scanned.path, server_meta_dir, cas)
            for scanned in report.files
            if scanned.classification in ("A-JAR", "A-CAS")
        ]
        lockfile = LockfileV21(
            format=2,
            mc=str(domain_server.minecraft_version),
            loader=derive_loader_ref(domain_server),
            base_overrides={},
            files=tuple(sorted(ingested, key=lambda item: item.path)),
            lec=None,
            modpack=None,
        )
        LockfileService(self._layout).write(sid, lockfile)
        return lockfile, len(ingested)

    async def convert_simple_to_advanced(
        self,
        server_id,
        *,
        event_bus=None,
        actor_id=None,
        actor_type: str = "user",
        session=None,
    ) -> ConversionResult:
        if os.name != "posix":
            raise CasUnsupportedPlatformError(
                "Advanced mode is only supported on POSIX hosts in this release"
            )

        sid = str(server_id)
        validate_server_segment(sid)
        layout = self._layout
        bus = await self._get_event_bus(event_bus)

        owns_session = session is None
        if owns_session:
            session = self._factory()()
        try:
            model = await self._load_model(session, sid)
            if _model_mode(model) != "simple":
                raise ConversionError(
                    f"Server '{sid}' is not in Simple mode",
                    http_status=409,
                    code="CONFLICT",
                )
            if _model_status(model) not in {"STOPPED", "CREATED"}:
                raise ConflictError(
                    f"Server '{sid}' must be stopped or created before conversion"
                )
            domain_server = await SQLServerRepository(session).get(ServerId(sid))
            server_root = _server_root(model, domain_server)
            if not server_root.is_dir():
                raise ValidationError("Server deployment root does not exist", field="root_path")
        finally:
            if owns_session:
                await session.close()

        lockfile, cas_ingested = await self._ensure_lockfile(sid, server_root, domain_server)
        backup_id = await self._create_tier1_backup(sid, server_root)
        class_c_service = self._class_c_service or ClassCSnapshotService(layout)
        class_c_result = class_c_service.create_snapshot(sid, server_root, pinned=True)
        class_c_id = class_c_result.snapshot_id

        scratch_dir = server_root.parent / f".onx-scratch-{uuid.uuid4().hex}"
        repo_dir = layout.repo_dir(sid)
        repo_git = repo_dir / "repo.git"
        worktree_dir = server_root / ".onx" / "worktrees" / "main"
        repo_dir_preexisting = repo_dir.exists() or repo_dir.is_symlink()
        repo_git_preexisting = repo_git.exists() or repo_git.is_symlink()
        worktree_preexisting = worktree_dir.exists() or worktree_dir.is_symlink()

        try:
            repo_result = GitRepositoryService(layout).initialize(sid, server_root, lockfile)
            export_result = CleanExportService(layout).export(
                CleanExportRequest(
                    server_id=sid,
                    server_root=server_root,
                    commit_sha=repo_result.main_sha,
                    destination=scratch_dir,
                    lockfile=lockfile,
                )
            )
            if not export_result.marker_path.exists():
                raise ValidationError("Clean export verification failed")
            shutil.rmtree(scratch_dir, ignore_errors=True)

            async with self._factory()() as flip_session:
                flipped = await flip_session.get(ServerModel, sid)
                if flipped is None:
                    raise ConversionError(
                        f"Server '{sid}' disappeared during conversion",
                        http_status=409,
                        code="CONFLICT",
                    )
                cast(Any, flipped).mode = ServerMode.ADVANCED.value
                await flip_session.commit()

            if bus is not None:
                try:
                    from app.modules.server.domain.events import (
                        ServerConvertedToAdvancedEvent,
                    )

                    await bus.publish(
                        ServerConvertedToAdvancedEvent(
                            ServerId(sid),
                            main_commit_sha=repo_result.main_sha,
                            backup_id=backup_id,
                            class_c_snapshot_id=class_c_id,
                            actor_id=actor_id,
                            actor_type=actor_type,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - conversion already committed
                    logger.warning(
                        "Failed to publish ServerConvertedToAdvancedEvent: %s", exc
                    )

            return ConversionResult(
                server_id=sid,
                from_mode="simple",
                to_mode="advanced",
                backup_id=backup_id,
                class_c_snapshot_id=class_c_id,
                lockfile_sha256=None,
                new_server_id=None,
                details={
                    "lockfile_path": str(LockfileService(layout).path_for(sid)),
                    "files_count": len(lockfile.files),
                    "cas_ingested": cas_ingested,
                    "worktree_path": str(repo_result.worktree_path),
                    "main_commit_sha": repo_result.main_sha,
                },
            )
        except Exception:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            if not worktree_preexisting and (
                worktree_dir.exists() or worktree_dir.is_symlink()
            ):
                shutil.rmtree(worktree_dir, ignore_errors=True)
                for empty_parent in (worktree_dir.parent, worktree_dir.parent.parent):
                    if empty_parent.is_dir() and not any(empty_parent.iterdir()):
                        empty_parent.rmdir()
            if not repo_git_preexisting and (repo_git.exists() or repo_git.is_symlink()):
                shutil.rmtree(repo_git, ignore_errors=True)
            if not repo_dir_preexisting and (repo_dir.exists() or repo_dir.is_symlink()):
                shutil.rmtree(repo_dir, ignore_errors=True)
            try:
                async with self._factory()() as rollback_session:
                    rolled_back = await rollback_session.get(ServerModel, sid)
                    if rolled_back is not None:
                        cast(Any, rolled_back).mode = ServerMode.SIMPLE.value
                    await rollback_session.commit()
            except Exception:  # noqa: BLE001 - preserve the original failure
                logger.warning("Failed to reset server %s to Simple mode", sid, exc_info=True)
            raise

    async def convert_advanced_to_simple(
        self,
        server_id,
        *,
        new_server_id=None,
        new_name=None,
        new_port=None,
        event_bus=None,
        actor_id=None,
        actor_type: str = "user",
        session=None,
    ) -> ConversionResult:
        if os.name != "posix":
            raise CasUnsupportedPlatformError(
                "Advanced mode is only supported on POSIX hosts in this release"
            )

        sid = str(server_id)
        validate_server_segment(sid)
        layout = self._layout
        bus = await self._get_event_bus(event_bus)

        owns_session = session is None
        if owns_session:
            session = self._factory()()
        try:
            model = await self._load_model(session, sid)
            if _model_mode(model) != "advanced":
                raise ConversionError(
                    f"Server '{sid}' is not in Advanced mode",
                    http_status=409,
                    code="CONFLICT",
                )
            domain_server = await SQLServerRepository(session).get(ServerId(sid))
            source_root = _server_root(model, domain_server)
            if not source_root.is_dir():
                raise ValidationError("Server deployment root does not exist", field="root_path")
            source_name = str(cast(Any, model).name or "server")
            source_port = int(cast(Any, model).port or 25565)
        finally:
            if owns_session:
                await session.close()

        lockfile = LockfileService(layout).read(sid)
        if lockfile is None:
            raise GitRepositoryStateError(
                f"Advanced server '{sid}' has no authoritative host lockfile"
            )

        repo_git = layout.repo_dir(sid) / "repo.git"
        if not repo_git.is_dir():
            raise GitRepositoryStateError(
                f"Advanced server '{sid}' has no native Git repository"
            )
        sha = _main_sha(repo_git)

        new_id = str(new_server_id) if new_server_id is not None else str(ServerId())
        validate_server_segment(new_id)
        new_root = _new_server_root(source_root, new_id)
        if new_root.exists() or new_root.is_symlink():
            raise ConflictError(f"Target root '{new_root}' already exists")

        new_name_final = str(new_name) if new_name is not None else f"{source_name} (Simple)"
        if len(new_name_final) > 255:
            raise ValidationError("Server name is too long", field="name")
        new_port_final = int(new_port) if new_port is not None else source_port
        if not 1 <= new_port_final <= 65535:
            raise ValidationError("Port must be between 1 and 65535", field="port")

        committed = False
        try:
            CleanExportService(layout).export(
                CleanExportRequest(
                    server_id=sid,
                    server_root=source_root,
                    commit_sha=sha,
                    destination=new_root,
                    lockfile=lockfile,
                )
            )
            _strip_git_association(new_root)

            report = scan_server_tree(source_root)
            if report.truncated:
                raise ValidationError("Server tree scan was truncated; cannot convert")

            for scanned in report.files:
                if scanned.classification not in ("C", "E"):
                    continue
                if scanned.path.split("/", 1)[0] in {".git", ".onx", ".onx-manager"}:
                    continue
                source_file = source_root / scanned.path
                target_file = new_root / scanned.path
                if target_file.exists() or target_file.is_symlink():
                    continue
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)

            LockfileService(layout).write(new_id, lockfile)
            info_dir = new_root / ".onx-manager"
            info_dir.mkdir(parents=True, exist_ok=True)
            (info_dir / "onx-jars.lock.json").write_bytes(dump_lockfile(lockfile))

            source_attrs = cast(Any, model)
            cloned = {name: getattr(source_attrs, name) for name in _CLONE_FIELDS}
            new_model = ServerModel(
                id=new_id,
                name=new_name_final,
                mode=ServerMode.SIMPLE.value,
                status="stopped",
                port=new_port_final,
                root_path=str(new_root),
                location_type="local",
                location_uri=None,
                **cloned,
            )
            async with self._factory()() as insert_session:
                insert_session.add(new_model)
                await insert_session.commit()
            committed = True

            if bus is not None:
                try:
                    from app.modules.server.domain.events import (
                        ServerConvertedToSimpleEvent,
                    )

                    await bus.publish(
                        ServerConvertedToSimpleEvent(
                            ServerId(sid),
                            new_server_id=new_id,
                            name=new_name_final,
                            actor_id=actor_id,
                            actor_type=actor_type,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - conversion already committed
                    logger.warning(
                        "Failed to publish ServerConvertedToSimpleEvent: %s", exc
                    )

            return ConversionResult(
                server_id=sid,
                from_mode="advanced",
                to_mode="simple",
                backup_id=None,
                class_c_snapshot_id=None,
                lockfile_sha256=None,
                new_server_id=new_id,
                details={
                    "name": new_name_final,
                    "root_path": str(new_root),
                    "lockfile_path": str(LockfileService(layout).path_for(new_id)),
                    "files_count": len(lockfile.files),
                },
            )
        except Exception:
            if not committed:
                shutil.rmtree(new_root, ignore_errors=True)
                server_meta_dir = layout.server_meta_dir(new_id)
                if server_meta_dir.exists() or server_meta_dir.is_symlink():
                    shutil.rmtree(server_meta_dir, ignore_errors=True)
            raise

    async def simple_to_advanced(self, *a, **kw):
        return await self.convert_simple_to_advanced(*a, **kw)

    async def advanced_to_simple(self, *a, **kw):
        return await self.convert_advanced_to_simple(*a, **kw)
