"""FastAPI routers for P5.5 Modpacks, 1-Click Safe Upgrades, Settings & Host LEC."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select

from app.api.deps import get_event_bus, require_permission, require_server_permission
from app.api.v1.routers.versioning import get_branch_runtime_service
from app.api.v1.schemas.modpacks_upgrades import (
    ApplyUpgradeRequest,
    LecEntryResponse,
    LecGcRequest,
    LecGcResponse,
    LecPrewarmRequest,
    LecPrewarmResponse,
    ModpackInspectResponse,
    ModpackInstallRequest,
    ModpackInstallResponse,
    PlanUpgradeRequest,
    PrepareUpgradeTestRequest,
    PrepareUpgradeTestResponse,
    RollbackUpgradeRequest,
    ServerP55SettingsResponse,
    ServerP55SettingsUpdateRequest,
    ServerUpgradeListResponse,
    ServerUpgradeResponse,
)
from app.api.v1.schemas.versioning import PortSetSchema, StartBranchRunResponse
from app.core.allowlist import open_safe_path_fd, validate_canonical_relpath
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import (
    CasUnsupportedPlatformError,
    CurseForgeApiKeyMissingError,
    DownloadError,
    InfrastructureError,
    ManualDownloadRequiredError,
    ModpackFormatError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import (
    HostStateLayout,
    ensure_host_state_layout,
    validate_server_segment,
)
from app.core.persistence.db import database
from app.modules.operations.application.services.operation_service import (
    get_operation_service,
)
from app.modules.operations.domain.enums import OperationType
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.application.modpack_lockfile_builder import (
    build_lockfile_from_install_plan,
)
from app.modules.versioning.application.modpack_upgrade_service import (
    ModpackUpgradeService,
    _install_plan_from_dict,
    _write_safe_file,
)
from app.modules.versioning.application.refresh_orchestrator import (
    LiveRefreshService,
    Tier1BackupServiceAdapter,
)
from app.modules.versioning.application.repo_lease import RepoLeaseManager
from app.modules.versioning.application.upgrade_health_gate import (
    DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS,
    UpgradeHealthGateEvaluator,
    validate_health_gate_timeout,
)
from app.modules.versioning.domain.events import (
    ModpackInstalledEvent,
    ServerP55SettingsUpdatedEvent,
    UpgradeAppliedEvent,
    UpgradeBranchPreparedEvent,
    UpgradeConfirmedEvent,
    UpgradeManualBlockerResolvedEvent,
    UpgradePlannedEvent,
    UpgradeRolledBackEvent,
    UpgradeTestStartedEvent,
)
from app.modules.versioning.domain.lockfile import (
    LoaderRef,
    LockfileV21,
    dump_lockfile,
    parse_lec_key,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import CleanExportService
from app.modules.versioning.infrastructure.curseforge_adapter import (
    download_curseforge_plan_files,
    parse_curseforge_zip,
    resolve_manual_download_upload,
)
from app.modules.versioning.infrastructure.download_allowlist import (
    ALL_NORMATIVE_DOWNLOAD_HOSTS,
    VerifiedDownloadResult,
)
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_merge import GitMergeService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.git_save_commit import GitSaveCommitService
from app.modules.versioning.infrastructure.lec_builder import LecBuilder
from app.modules.versioning.infrastructure.lec_store import LecStore
from app.modules.versioning.infrastructure.models import LoaderEnvCacheEntryModel
from app.modules.versioning.infrastructure.modpack_parser import (
    InstallPlan,
    parse_mrpack,
)
from app.modules.versioning.infrastructure.panel_secret_store import resolve_curseforge_api_key
from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRepository

logger = logging.getLogger(__name__)

server_p55_router = APIRouter(
    prefix="/api/v1/servers/{server_id}",
    tags=["modpacks", "upgrades"],
)
lec_router = APIRouter(
    prefix="/api/v1/lec",
    tags=["lec"],
)

__all__ = [
    "build_p55_live_refresh_service",
    "get_lec_builder",
    "get_lec_store",
    "get_modpack_upgrade_service",
    "get_upgrade_health_gate_factory",
    "get_upgrade_refresh_service_factory",
    "lec_router",
    "server_p55_router",
]

_SAFE_STAGED_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_MAX_MANUAL_UPLOAD_BYTES = 512 * 1024 * 1024
_REMINDER_OVERDUE_DELTA = timedelta(hours=72)
_TERMINAL_UPGRADE_STATUSES = frozenset({"confirmed", "rolled_back", "failed", "cancelled"})
MODPACK_SUPPORTED_LOADERS = frozenset({"fabric", "forge", "neoforge", "quilt"})


def _assert_modpack_supported_loader(server: ServerModel) -> None:
    """Ensure modpack endpoints are only invoked on modded server loaders."""
    server_type = str(getattr(server, "server_type", "") or "").strip().lower()
    if server_type not in MODPACK_SUPPORTED_LOADERS:
        supported = ", ".join(sorted(MODPACK_SUPPORTED_LOADERS))
        raise ValidationError(
            f"Modpack installation is only supported for modded server loaders ({supported}); "
            f"server '{server.id}' uses '{server_type or 'unknown'}'.",
            field="server_type",
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_id_from_user(current_user: dict[str, Any]) -> str | None:
    raw = current_user.get("user_id") or current_user.get("sub") or current_user.get("id")
    return str(raw) if raw else None


def _require_posix(message: str = "Operation requires a POSIX host in this release") -> None:
    if os.name != "posix":
        raise CasUnsupportedPlatformError(message)


def get_lec_store() -> LecStore:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    return LecStore(layout, settings=settings)


def get_lec_builder() -> LecBuilder:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    store = LecStore(layout, settings=settings)
    cas = ArtifactCas(layout.cas)
    return LecBuilder(
        layout=layout,
        store=store,
        cas=cas,
        settings=settings,
        session_factory=database.session_factory,
    )


def get_modpack_upgrade_service(
    lec_store: Annotated[LecStore, Depends(get_lec_store)],
    lec_builder: Annotated[LecBuilder, Depends(get_lec_builder)],
    branch_runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
) -> ModpackUpgradeService:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    return ModpackUpgradeService(
        layout,
        database.session_factory,
        lec_store=lec_store,
        lec_builder=lec_builder,
        branch_runtime_service=branch_runtime_service,
    )


async def build_p55_live_refresh_service(
    server_id: str,
    *,
    event_bus: EventBus,
) -> LiveRefreshService:
    """Mode-neutral LiveRefreshService builder supporting both Simple and Advanced."""
    from app.core.persistence.unit_of_work import UnitOfWork
    from app.core.settings_store import get_live_settings
    from app.modules.server.application.commands.start_server import StartServerHandler
    from app.modules.server.application.commands.stop_server import StopServerHandler
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.infrastructure.runtime_adapters import (
        CleanExportStageAdapter,
        DockerServerRuntimeAdapter,
        require_docker_provider,
    )

    if os.name != "posix":
        raise ServerModeVersioningDisabledError(
            "Live refresh is only supported on POSIX hosts in this release"
        )

    loop = asyncio.get_running_loop()
    layout = ensure_host_state_layout()
    async with UnitOfWork() as uow:
        server = await SQLServerRepository(uow.session).get(ServerId(server_id))
    if server.deployment is None:
        raise ValidationError(
            "Live refresh requires a deployed server directory", field="server_id"
        )
    server_root = server.deployment.server_directory()
    provider = require_docker_provider(
        server.runtime.provider if server.runtime else None
    )
    startup_timeout = float(
        server.startup_timeout_seconds
        or get_live_settings().server_startup_timeout_seconds
    )
    lockfile = await asyncio.to_thread(LockfileService(layout).read, server_id)
    runtime_record = server.runtime
    container_name = (
        str(runtime_record.external_id).strip()
        if runtime_record is not None and runtime_record.external_id
        else None
    )
    runtime = DockerServerRuntimeAdapter(
        server_id=server_id,
        loop=loop,
        start_handler=StartServerHandler(event_bus).handle,
        stop_handler=StopServerHandler(event_bus).handle,
        server_dir=server_root,
        startup_timeout_seconds=startup_timeout,
        provider_name=provider,
        container_name=container_name,
    )
    stage_export = CleanExportStageAdapter(
        layout,
        server_id=server_id,
        server_root=server_root,
        lockfile=lockfile,
        loop=loop,
    )
    journal_repo = RefreshJournalRepository(
        layout, session_factory=database.session_factory
    )
    class_c_service = ClassCSnapshotService(
        layout, session_factory=database.session_factory
    )
    return LiveRefreshService(
        layout,
        repository=journal_repo,
        class_c_service=class_c_service,
        repo_lease=RepoLeaseManager(locks_dir=layout.locks),
        backup_service=Tier1BackupServiceAdapter(),
        runtime=runtime,
        stage_export=stage_export,
    )


def get_upgrade_refresh_service_factory(
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> Callable[[str], Awaitable[LiveRefreshService]]:
    async def _factory(server_id: str) -> LiveRefreshService:
        return await build_p55_live_refresh_service(server_id, event_bus=event_bus)

    return _factory


def get_upgrade_health_gate_factory() -> (
    Callable[[Any, ServerModel], UpgradeHealthGateEvaluator | None]
):
    return lambda _upgrade, _server: None


async def _load_server(session: Any, server_id: str) -> ServerModel:
    server = await session.get(ServerModel, server_id)
    if server is None:
        raise NotFoundError(f"Server '{server_id}' not found")
    return server


def _server_allowlist(server: ServerModel) -> list[str]:
    raw = getattr(server, "download_host_allowlist_json", None)
    if isinstance(raw, list):
        return [str(h) for h in raw if isinstance(h, str) and h.strip()]
    return []


def _p55_settings_response(server: ServerModel) -> ServerP55SettingsResponse:
    return ServerP55SettingsResponse(
        server_id=str(server.id),
        health_gate_boot_timeout_seconds=int(
            getattr(server, "health_gate_boot_timeout_seconds", None)
            or DEFAULT_HEALTH_GATE_BOOT_TIMEOUT_SECONDS
        ),
        install_optional_server_files=bool(
            getattr(server, "install_optional_server_files", True)
        ),
        allow_experimental_paper_builds=bool(
            getattr(server, "allow_experimental_paper_builds", False)
        ),
        download_host_allowlist=_server_allowlist(server),
        default_allowed_hosts=sorted(ALL_NORMATIVE_DOWNLOAD_HOSTS),
    )


def _staged_pack_dir(layout: HostStateLayout, server_id: str, staged_pack_id: str) -> Path:
    segment = validate_server_segment(server_id)
    if not _SAFE_STAGED_ID_RE.fullmatch(staged_pack_id):
        raise ValidationError("Invalid staged_pack_id", field="staged_pack_id")
    return layout.root / "staging" / "modpacks" / segment / staged_pack_id


def _staged_upgrade_overrides_dir(
    layout: HostStateLayout, server_id: str, upgrade_id: str
) -> Path:
    segment = validate_server_segment(server_id)
    if not _SAFE_STAGED_ID_RE.fullmatch(upgrade_id):
        raise ValidationError("Invalid upgrade_id", field="upgrade_id")
    return layout.root / "staging" / "upgrades" / segment / upgrade_id / "overrides"


def _read_override_blobs_from_dir(
    overrides_dir: Path, plan: InstallPlan
) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    if not overrides_dir.is_dir():
        return blobs
    for override in plan.overrides:
        fd = open_safe_path_fd(str(overrides_dir), override.path, flags=os.O_RDONLY)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(fd)
        if hashlib.sha256(data).hexdigest() != override.sha256:
            raise ModpackFormatError(
                f"Staged override checksum mismatch: {override.path[:128]!r}",
                field="overrides",
            )
        blobs[override.path] = data
    return blobs


def _upgrade_to_response(row: Any) -> ServerUpgradeResponse:
    now = _utcnow()
    updated_at = row.updated_at
    if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    created_at = row.created_at
    if isinstance(created_at, datetime) and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    pinned = bool(row.pinned_until_confirm)
    overdue = bool(
        pinned
        and row.status == "active_pinned"
        and isinstance(updated_at, datetime)
        and (now - updated_at) >= _REMINDER_OVERDUE_DELTA
    )
    return ServerUpgradeResponse(
        id=str(row.id),
        server_id=str(row.server_id),
        kind=str(row.kind),
        mode=str(row.mode),
        status=str(row.status),
        source_mc=row.source_mc,
        target_mc=str(row.target_mc),
        source_loader_id=row.source_loader_id,
        source_loader_version=row.source_loader_version,
        target_loader_id=str(row.target_loader_id),
        target_loader_version=str(row.target_loader_version),
        target_lec_key=row.target_lec_key,
        upgrade_branch=row.upgrade_branch,
        operation_id=row.operation_id,
        journal_id=row.journal_id,
        previous_main_sha=row.previous_main_sha,
        target_main_sha=row.target_main_sha,
        pre_upgrade_backup_id=row.pre_upgrade_backup_id,
        class_c_snapshot_id=row.class_c_snapshot_id,
        data_template_id=row.data_template_id,
        plan=row.plan_json,
        matrix=row.matrix_json,
        manual_blockers=row.manual_blockers_json,
        pinned_until_confirm=pinned,
        health_gate_passed=bool(row.health_gate_passed),
        reminder_72h_overdue=overdue,
        error_code=row.error_code,
        error_message=row.error_message,
        confirmed_at=row.confirmed_at,
        rolled_back_at=row.rolled_back_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _raise_for_unresolved_blocker(plan: InstallPlan) -> None:
    blocker = next(b for b in plan.manual_blockers if not b.resolved)
    raise ManualDownloadRequiredError(
        filename=blocker.filename,
        webpage_url=blocker.webpage_url,
        expected_size=blocker.expected_size,
        expected_sha1=blocker.expected_sha1,
        expected_sha512=blocker.expected_sha512,
        project_id=blocker.project_id,
        file_id=blocker.file_id,
    )


def _default_lec_key(
    plan: InstallPlan,
    *,
    explicit_lec_key: str | None,
    fabric_installer_version: str,
) -> str:
    if explicit_lec_key:
        return explicit_lec_key
    if plan.loader_id == "fabric":
        return f"fabric/{plan.mc_version}/{plan.loader_version}/{fabric_installer_version}"
    return f"{plan.loader_id}/{plan.mc_version}/{plan.loader_version}"


async def _download_modrinth_plan_files(
    plan: InstallPlan,
    cas: ArtifactCas,
    *,
    extra_allowed_hosts: Iterable[str],
    downloader: Callable[..., Awaitable[VerifiedDownloadResult]],
    on_progress: Callable[[int, int, str, bool], Awaitable[None]] | None = None,
) -> dict[str, VerifiedDownloadResult]:
    downloaded: dict[str, VerifiedDownloadResult] = {}
    total = len(plan.files)
    for idx, f in enumerate(plan.files, start=1):
        if f.sha256 and cas.has(f.sha256):
            if on_progress is not None:
                await on_progress(idx, total, f.path, True)
            continue
        if not f.downloads:
            raise ValidationError(
                f"Modpack file '{f.path}' has no download URLs", field="files"
            )
        if on_progress is not None:
            await on_progress(idx, total, f.path, False)
        last_exc: Exception | None = None
        for url in f.downloads:
            try:
                result = await downloader(
                    url,
                    cas,
                    expected_size=f.size,
                    expected_sha512=f.sha512,
                    expected_sha1=f.sha1,
                    extra_allowed_hosts=extra_allowed_hosts,
                )
                downloaded[f.path] = result
                last_exc = None
                break
            except DownloadError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
    return downloaded


def _commit_advanced_modpack_install(
    layout: HostStateLayout,
    *,
    server_id: str,
    server_root: Path,
    staged_pack_id: str,
    lockfile: LockfileV21,
    class_b_blobs: dict[str, bytes],
    version_label: str,
) -> str:
    repo_git = layout.repo_dir(server_id) / "repo.git"
    if not (repo_git.exists() or repo_git.is_symlink()):
        init_res = GitRepositoryService(layout).initialize(
            server_id, server_root, lockfile
        )
        return init_res.main_sha

    branch_service = GitBranchService(layout)
    save_service = GitSaveCommitService(layout)
    merge_service = GitMergeService(layout)

    main_branch = branch_service.get_branch(server_id, server_root, "main")
    if main_branch is None or not main_branch.sha:
        raise NotFoundError(f"Branch 'main' not found for server '{server_id}'")

    install_branch = f"modpack-install-{staged_pack_id[:8]}"
    existing = branch_service.get_branch(server_id, server_root, install_branch)
    if existing is None:
        branch_info = branch_service.create_branch(
            server_id, server_root, install_branch, start_point="main"
        )
    else:
        branch_info = existing
    if branch_info.worktree_path is None:
        raise InfrastructureError(
            f"Modpack install branch '{install_branch}' has no active worktree"
        )

    worktree = branch_info.worktree_path
    for relpath, data in sorted(class_b_blobs.items()):
        _write_safe_file(worktree, relpath, data)
    _write_safe_file(worktree, "onx-jars.lock.json", dump_lockfile(lockfile))

    save_service.save(
        server_id,
        server_root,
        install_branch,
        f"Install modpack {version_label[:120]}",
    )
    merge_res = merge_service.merge(
        server_id,
        server_root,
        "main",
        [main_branch.sha, install_branch],
        f"Install modpack {version_label[:120]}",
    )
    with contextlib.suppress(Exception):
        branch_service.delete_branch(server_id, server_root, install_branch)
    return merge_res.commit_id


# ── Host LEC endpoints ──────────────────────────────────────────────────────


@lec_router.get("/entries", response_model=list[LecEntryResponse])
async def list_lec_entries(
    lec_store: Annotated[LecStore, Depends(get_lec_store)],
    _current_user: Annotated[dict, Depends(require_permission("settings:read"))],
) -> list[LecEntryResponse]:
    async with database.session_factory() as session:
        result = await session.execute(
            select(LoaderEnvCacheEntryModel).order_by(LoaderEnvCacheEntryModel.lec_key)
        )
        rows = list(result.scalars().all())

    entries: dict[str, LecEntryResponse] = {}
    for row in rows:
        r = cast(Any, row)
        key = str(r.lec_key)
        entries[key] = LecEntryResponse(
            lec_key=key,
            loader_id=str(r.loader_id),
            mc_version=str(r.mc_version),
            loader_version=str(r.loader_version),
            installer_version=r.installer_version,
            java_major=r.java_major,
            status=str(r.status),
            size_bytes=int(r.size_bytes or 0),
            file_count=int(r.file_count or 0),
            complete_manifest_sha256=r.complete_manifest_sha256,
            ready_on_disk=lec_store.is_ready(key),
            last_used_at=r.last_used_at,
            updated_at=r.updated_at,
        )

    for norm, _entry_path in lec_store._iter_lec_entry_dirs():
        if norm in entries:
            continue
        try:
            meta = lec_store.verify_entry(norm)
            parts = parse_lec_key(norm)
        except Exception:
            continue
        entries[norm] = LecEntryResponse(
            lec_key=norm,
            loader_id=parts.loader,
            mc_version=parts.mc,
            loader_version=parts.version,
            installer_version=parts.installer,
            java_major=meta.java_major,
            status="ready",
            size_bytes=meta.total_bytes,
            file_count=meta.file_count,
            complete_manifest_sha256=meta.complete_manifest_sha256,
            ready_on_disk=True,
            last_used_at=None,
            updated_at=None,
        )

    return [entries[k] for k in sorted(entries)]


@lec_router.post("/prewarm", response_model=LecPrewarmResponse, status_code=201)
async def prewarm_lec_entry(
    body: LecPrewarmRequest,
    response: Response,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    lec_builder: Annotated[LecBuilder, Depends(get_lec_builder)],
    current_user: Annotated[dict, Depends(require_permission("settings:write"))],
) -> LecPrewarmResponse:
    _require_posix("LEC pre-warm is only supported on POSIX hosts in this release")
    lec_key = body.lec_key
    assert lec_key is not None
    actor_id = _actor_id_from_user(current_user)
    op_service = get_operation_service(event_bus)
    op = await op_service.create_operation(
        type=OperationType.GENERIC.value,
        target_type="system",
        target_id=lec_key,
        actor_id=actor_id,
        metadata={"lec_key": lec_key, "action": "lec_prewarm"},
        initial_steps=[
            {
                "step_id": "PREWARM_LEC",
                "sequence": 1,
                "message_key": "operations.steps.prewarm_lec",
            }
        ],
    )

    async def _run() -> Any:
        await op_service.start_step(op.id, "PREWARM_LEC")
        try:
            res = await lec_builder.ensure_lec(lec_key)
            parts = parse_lec_key(lec_key)
            now = _utcnow()
            async with database.session_factory() as session:
                existing = await session.get(LoaderEnvCacheEntryModel, lec_key)
                if existing is None:
                    session.add(
                        LoaderEnvCacheEntryModel(
                            lec_key=lec_key,
                            loader_id=parts.loader,
                            mc_version=parts.mc,
                            loader_version=parts.version,
                            installer_version=parts.installer,
                            java_major=getattr(res, "java_major", None),
                            status="ready",
                            size_bytes=int(getattr(res, "total_bytes", 0) or 0),
                            file_count=int(getattr(res, "file_count", 0) or 0),
                            created_at=now,
                            last_used_at=now,
                            updated_at=now,
                        )
                    )
                    await session.commit()
            await op_service.complete_step(op.id, "PREWARM_LEC")
            await op_service.complete_operation(op.id)
            return res
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            with contextlib.suppress(Exception):
                await op_service.fail_step(op.id, "PREWARM_LEC", error=str(exc)[:500])
                await op_service.fail_operation(
                    op.id,
                    getattr(exc, "code", "INTERNAL_ERROR"),
                    str(exc)[:500],
                    failed_step_id="PREWARM_LEC",
                )
            raise

    if body.async_mode:

        async def _background() -> None:
            with contextlib.suppress(BaseException):
                await _run()

        task = asyncio.create_task(_background(), name=f"lec-prewarm:{op.id}")
        with contextlib.suppress(Exception):
            op_service.executor.register_task(op.id, task)
        response.status_code = 202
        return LecPrewarmResponse(
            lec_key=lec_key,
            status="queued",
            operation_id=op.id,
        )

    res = await _run()
    response.status_code = 201
    return LecPrewarmResponse(
        lec_key=res.lec_key,
        status="ready",
        file_count=int(res.file_count),
        total_bytes=int(res.total_bytes),
        java_major=res.java_major,
        unix_args_relpath=res.unix_args_relpath,
        operation_id=op.id,
    )


@lec_router.post("/gc", response_model=LecGcResponse)
async def gc_lec_cache(
    lec_store: Annotated[LecStore, Depends(get_lec_store)],
    _current_user: Annotated[dict, Depends(require_permission("settings:write"))],
    body: LecGcRequest | None = None,
) -> LecGcResponse:
    req = body or LecGcRequest()
    async with database.session_factory() as session:
        report = await lec_store.gc_unused_caches(
            min_age_days=req.min_age_days,
            session=session,
            settings=AppSettings(),
        )
        await session.commit()
    return LecGcResponse(
        pruned_lec_keys=list(report.pruned_lec_keys),
        pruned_cas_digests=list(report.pruned_cas_digests),
        freed_bytes=int(report.freed_bytes),
    )


# ── Server P5.5 Settings ────────────────────────────────────────────────────


@server_p55_router.get("/p55-settings", response_model=ServerP55SettingsResponse)
async def get_server_p55_settings(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.view"))],
) -> ServerP55SettingsResponse:
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
    return _p55_settings_response(server)


@server_p55_router.put("/p55-settings", response_model=ServerP55SettingsResponse)
async def update_server_p55_settings(
    server_id: str,
    body: ServerP55SettingsUpdateRequest,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.settings"))],
) -> ServerP55SettingsResponse:
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        writable = cast(Any, server)
        if body.health_gate_boot_timeout_seconds is not None:
            validate_health_gate_timeout(body.health_gate_boot_timeout_seconds)
            writable.health_gate_boot_timeout_seconds = body.health_gate_boot_timeout_seconds
        if body.install_optional_server_files is not None:
            writable.install_optional_server_files = body.install_optional_server_files
        if body.allow_experimental_paper_builds is not None:
            writable.allow_experimental_paper_builds = body.allow_experimental_paper_builds
        if body.download_host_allowlist is not None:
            writable.download_host_allowlist_json = list(body.download_host_allowlist)
        await session.commit()
        await session.refresh(server)

    resp = _p55_settings_response(server)
    await event_bus.publish(
        ServerP55SettingsUpdatedEvent(
            server_id=server_id,
            health_gate_boot_timeout_seconds=resp.health_gate_boot_timeout_seconds,
            install_optional_server_files=resp.install_optional_server_files,
            allow_experimental_paper_builds=resp.allow_experimental_paper_builds,
            download_host_allowlist=list(resp.download_host_allowlist),
            actor_type="user",
            actor_id=_actor_id_from_user(current_user),
        )
    )
    return resp


# ── Modpack Inspect & Install ───────────────────────────────────────────────


@server_p55_router.post("/modpacks/inspect", response_model=ModpackInspectResponse)
async def inspect_modpack(
    server_id: str,
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
    file: Annotated[UploadFile, File(...)],
    format: Annotated[Literal["auto", "mrpack", "curseforge"], Form()] = "auto",
    project_id: Annotated[str, Form()] = "local",
    version_id: Annotated[str, Form()] = "local",
    install_optional_server_files: Annotated[bool | None, Form()] = None,
) -> ModpackInspectResponse:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)

    async with database.session_factory() as session:
        srv = cast(Any, await _load_server(session, server_id))
        _assert_modpack_supported_loader(srv)
        extra_hosts = _server_allowlist(srv)
        optional_flag = (
            install_optional_server_files
            if install_optional_server_files is not None
            else bool(getattr(srv, "install_optional_server_files", True))
        )
        server_mode = str(getattr(srv, "mode", "simple") or "simple").lower()
        source_mc: str | None = str(srv.minecraft_version) if srv.minecraft_version else None
        source_loader: str | None = str(srv.server_type) if srv.server_type else None

        staged_pack_id = str(uuid.uuid4())
        staged_dir = _staged_pack_dir(layout, server_id, staged_pack_id)
        staged_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive_path = staged_dir / "archive.zip"

        max_mb = int(getattr(settings, "import_max_zip_size_mb", 0) or 0)
        max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0

        try:
            total_bytes = 0
            with open(archive_path, "wb") as fh:
                while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
                    total_bytes += len(chunk)
                    if max_bytes > 0 and total_bytes > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"Uploaded archive exceeds maximum size of {max_mb} MB"
                            ),
                        )
                    fh.write(chunk)

            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    names = set(zf.namelist())
            except (zipfile.BadZipFile, OSError) as exc:
                raise ModpackFormatError(
                    "Not a valid modpack ZIP archive",
                    field="archive",
                ) from exc

            detected: str
            if format == "mrpack":
                detected = "mrpack"
            elif format == "curseforge":
                detected = "curseforge"
            elif "modrinth.index.json" in names:
                detected = "mrpack"
            elif "manifest.json" in names:
                detected = "curseforge"
            else:
                raise ModpackFormatError(
                    "Modpack archive must contain modrinth.index.json or manifest.json",
                    field="format",
                )

            if detected == "mrpack":
                plan, override_blobs = await parse_mrpack(
                    archive_path,
                    install_optional_server_files=optional_flag,
                    extra_allowed_hosts=extra_hosts,
                    project_id=project_id,
                    version_id=version_id,
                )
            else:
                api_key = await resolve_curseforge_api_key(
                    session, layout=layout, settings=settings
                )
                if not api_key:
                    raise CurseForgeApiKeyMissingError()
                plan, override_blobs = await parse_curseforge_zip(
                    archive_path,
                    api_key=api_key,
                    install_optional_server_files=optional_flag,
                    extra_allowed_hosts=extra_hosts,
                    project_id=project_id,
                    version_id=version_id,
                )

            plan_dict = cast(dict[str, Any], plan.to_dict())
            atomic_write_private(
                staged_dir / "plan.json",
                json.dumps(plan_dict, sort_keys=True).encode("utf-8"),
                mode=0o600,
                fsync_parent=True,
            )
            overrides_dir = staged_dir / "overrides"
            overrides_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for relpath, blob in sorted(override_blobs.items()):
                norm = validate_canonical_relpath(relpath)
                fd = open_safe_path_fd(
                    str(overrides_dir),
                    norm,
                    flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    mode=0o644,
                    allow_create_parents=True,
                )
                try:
                    offset = 0
                    view = memoryview(blob)
                    while offset < len(blob):
                        written = os.write(fd, view[offset:])
                        if written <= 0:
                            raise OSError("short write")
                        offset += written
                finally:
                    os.close(fd)
        except BaseException:
            shutil.rmtree(staged_dir, ignore_errors=True)
            raise

    await upgrade_service._upgrade_repo.create(
        upgrade_id=staged_pack_id,
        server_id=server_id,
        kind="modpack_install",
        mode=server_mode,
        status="awaiting_manual_uploads" if plan.has_unresolved_blockers else "planned",
        source_mc=source_mc,
        target_mc=plan.mc_version,
        source_loader_id=source_loader,
        target_loader_id=plan.loader_id,
        target_loader_version=plan.loader_version,
        plan_json=plan_dict,
        manual_blockers_json=[
            cast(dict[str, Any], b.to_dict()) for b in plan.manual_blockers
        ],
    )
    return ModpackInspectResponse(
        server_id=server_id,
        staged_pack_id=staged_pack_id,
        source=plan.source,
        mc_version=plan.mc_version,
        loader_id=plan.loader_id,
        loader_version=plan.loader_version,
        has_unresolved_blockers=plan.has_unresolved_blockers,
        plan=plan_dict,
    )


@server_p55_router.post("/modpacks/install", response_model=ModpackInstallResponse)
async def install_modpack(
    server_id: str,
    body: ModpackInstallRequest,
    response: Response,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    lec_store: Annotated[LecStore, Depends(get_lec_store)],
    lec_builder: Annotated[LecBuilder, Depends(get_lec_builder)],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
) -> ModpackInstallResponse:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        _assert_modpack_supported_loader(server)
        extra_hosts = _server_allowlist(server)
        server_mode = str(getattr(server, "mode", "simple") or "simple").lower()
        raw_root = getattr(server, "root_path", None)

    _require_posix("Modpack install is only supported on POSIX hosts in this release")
    if not raw_root:
        raise ValidationError("Server root path is not configured", field="root_path")
    server_root = Path(os.path.abspath(str(raw_root)))

    row_raw = await upgrade_service._upgrade_repo.get(body.staged_pack_id)
    row = cast(Any, row_raw)
    if row is None or str(row.server_id) != server_id or not row.plan_json:
        raise NotFoundError(
            f"Staged modpack '{body.staged_pack_id}' not found for server '{server_id}'"
        )

    plan = _install_plan_from_dict(cast(dict[str, Any], row.plan_json))
    if plan.has_unresolved_blockers:
        _raise_for_unresolved_blocker(plan)

    staged_dir = _staged_pack_dir(layout, server_id, body.staged_pack_id)
    actor_id = _actor_id_from_user(current_user)
    op_service = get_operation_service(event_bus)
    op = await op_service.create_operation(
        type=OperationType.MODPACK_INSTALL.value,
        target_type="server",
        target_id=server_id,
        actor_id=actor_id,
        metadata={"staged_pack_id": body.staged_pack_id},
        initial_steps=[
            {
                "step_id": "INSTALL_MODPACK",
                "sequence": 1,
                "message_key": "operations.steps.install_modpack",
            }
        ],
    )
    await upgrade_service._upgrade_repo.update_status(
        body.staged_pack_id,
        str(row.status),
        operation_id=op.id,
    )

    async def _emit_progress(
        pct: float,
        message: str,
        *,
        level: str = "info",
        context: dict[str, Any] | None = None,
    ) -> None:
        with contextlib.suppress(Exception):
            await op_service.record_step_progress(
                op.id,
                "INSTALL_MODPACK",
                pct,
                context=context,
            )
        with contextlib.suppress(Exception):
            await op_service.emit_log(
                op.id,
                message,
                level=level,
                step_id="INSTALL_MODPACK",
            )

    async def _run_install() -> ModpackInstallResponse:
        await op_service.start_step(op.id, "INSTALL_MODPACK")
        cas = upgrade_service._cas
        try:
            await _emit_progress(
                5.0,
                f"Starting modpack installation ({len(plan.files)} server files, "
                f"{len(plan.overrides)} overrides)...",
                context={"stage": "preparing", "total": len(plan.files), "current": 0},
            )
            override_blobs = _read_override_blobs_from_dir(
                staged_dir / "overrides", plan
            )
            current_plan = plan
            downloaded: dict[str, VerifiedDownloadResult] = {}
            if current_plan.source == "curseforge":
                await _emit_progress(
                    15.0,
                    f"Downloading CurseForge server files ({len(current_plan.files)} total)...",
                    context={"stage": "downloading", "total": len(current_plan.files), "current": 0},
                )
                updated_plan, downloaded = await download_curseforge_plan_files(
                    current_plan,
                    cas,
                    extra_allowed_hosts=extra_hosts,
                    modrinth_client=upgrade_service._modrinth_client,
                )
                if updated_plan.has_unresolved_blockers:
                    await upgrade_service._upgrade_repo.update_status(
                        body.staged_pack_id,
                        "awaiting_manual_uploads",
                        plan_json=cast(dict[str, Any], updated_plan.to_dict()),
                        manual_blockers_json=[
                            cast(dict[str, Any], b.to_dict())
                            for b in updated_plan.manual_blockers
                        ],
                    )
                    _raise_for_unresolved_blocker(updated_plan)
                current_plan = updated_plan
            else:
                async def _on_file(idx: int, total: int, fpath: str, cached: bool) -> None:
                    ratio = idx / max(1, total)
                    pct = round(10.0 + ratio * 65.0, 1)
                    action = "Cached" if cached else "Downloading"
                    await _emit_progress(
                        pct,
                        f"{action} ({idx}/{total}): {fpath}",
                        context={
                            "stage": "downloading",
                            "current": idx,
                            "total": total,
                            "current_file": fpath,
                        },
                    )

                downloaded = await _download_modrinth_plan_files(
                    current_plan,
                    cas,
                    extra_allowed_hosts=extra_hosts,
                    downloader=upgrade_service._download_to_cas,
                    on_progress=_on_file,
                )

            candidate_lec_key = _default_lec_key(
                current_plan,
                explicit_lec_key=body.lec_key,
                fabric_installer_version=body.fabric_installer_version,
            )
            if body.build_lec and not lec_store.is_ready(candidate_lec_key):
                await _emit_progress(
                    80.0,
                    f"Preparing Loader Environment Cache ({candidate_lec_key})...",
                    context={"stage": "lec", "lec_key": candidate_lec_key},
                )
                await lec_builder.ensure_lec(candidate_lec_key)
            effective_lec_key = (
                candidate_lec_key if lec_store.is_ready(candidate_lec_key) else None
            )

            await _emit_progress(
                85.0,
                "Writing verified mods and overrides to server directory...",
                context={"stage": "writing"},
            )

            lockfile = build_lockfile_from_install_plan(
                current_plan,
                cas=cas,
                downloaded_files=downloaded,
                override_blobs=override_blobs,
                lec_key=effective_lec_key,
            )

            server_root.mkdir(parents=True, exist_ok=True)
            LockfileService(layout).write(server_id, lockfile)

            class_b_blobs: dict[str, bytes] = {}
            for override in current_plan.overrides:
                if override.classification != "B":
                    continue
                blob = override_blobs.get(override.path)
                if blob is not None:
                    class_b_blobs[override.path] = blob
                    _write_safe_file(server_root, override.path, blob)

            CleanExportService(layout, cas=cas)._materialize_class_a(
                server_root, lockfile
            )
            if lockfile.lec is not None:
                lec_store.attach_to_target(lockfile.lec.key, server_root)
            _write_safe_file(
                server_root,
                ".onx-manager/onx-jars.lock.json",
                dump_lockfile(lockfile),
            )

            commit_sha: str | None = None
            if server_mode == "advanced":
                commit_sha = await asyncio.to_thread(
                    _commit_advanced_modpack_install,
                    layout,
                    server_id=server_id,
                    server_root=server_root,
                    staged_pack_id=body.staged_pack_id,
                    lockfile=lockfile,
                    class_b_blobs=class_b_blobs,
                    version_label=current_plan.version_label,
                )

            async with database.session_factory() as session:
                srv = await _load_server(session, server_id)
                writable_srv = cast(Any, srv)
                writable_srv.minecraft_version = current_plan.mc_version
                writable_srv.server_type = current_plan.loader_id
                await session.commit()

            await upgrade_service._upgrade_repo.update_status(
                body.staged_pack_id,
                "confirmed",
                target_lec_key=effective_lec_key,
                target_main_sha=commit_sha,
                confirmed_at=_utcnow(),
            )
            shutil.rmtree(staged_dir, ignore_errors=True)

            await _emit_progress(
                100.0,
                f"Modpack installation complete ({len(lockfile.files)} files, "
                f"{len(lockfile.base_overrides)} overrides).",
                context={"stage": "complete"},
            )
            await op_service.complete_step(op.id, "INSTALL_MODPACK")
            await op_service.complete_operation(op.id)

            await event_bus.publish(
                ModpackInstalledEvent(
                    server_id=server_id,
                    upgrade_id=body.staged_pack_id,
                    source=current_plan.source,
                    project_id=current_plan.project_id,
                    version_id=current_plan.version_id,
                    version_label=current_plan.version_label,
                    mc_version=current_plan.mc_version,
                    loader_id=current_plan.loader_id,
                    loader_version=current_plan.loader_version,
                    file_count=len(lockfile.files),
                    operation_id=op.id,
                    actor_type="user",
                    actor_id=actor_id,
                )
            )
            return ModpackInstallResponse(
                server_id=server_id,
                upgrade_id=body.staged_pack_id,
                status="confirmed",
                mc_version=current_plan.mc_version,
                loader_id=current_plan.loader_id,
                loader_version=current_plan.loader_version,
                lec_key=effective_lec_key,
                files_installed=len(lockfile.files),
                base_overrides_count=len(lockfile.base_overrides),
                commit_sha=commit_sha,
                operation_id=op.id,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            with contextlib.suppress(Exception):
                await op_service.fail_step(op.id, "INSTALL_MODPACK", error=str(exc)[:500])
                await op_service.fail_operation(
                    op.id,
                    getattr(exc, "code", "INTERNAL_ERROR"),
                    str(exc)[:500],
                    failed_step_id="INSTALL_MODPACK",
                )
            raise

    if body.async_mode:

        async def _background() -> None:
            with contextlib.suppress(BaseException):
                await _run_install()

        task = asyncio.create_task(_background(), name=f"modpack-install:{op.id}")
        with contextlib.suppress(Exception):
            op_service.executor.register_task(op.id, task)
        response.status_code = 202
        return ModpackInstallResponse(
            server_id=server_id,
            upgrade_id=body.staged_pack_id,
            status="installing",
            mc_version=plan.mc_version,
            loader_id=plan.loader_id,
            loader_version=plan.loader_version,
            operation_id=op.id,
        )

    return await _run_install()


# ── 1-Click Safe Upgrade endpoints ──────────────────────────────────────────


@server_p55_router.get("/upgrades", response_model=ServerUpgradeListResponse)
async def list_server_upgrades(
    server_id: str,
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.view"))],
) -> ServerUpgradeListResponse:
    async with database.session_factory() as session:
        await _load_server(session, server_id)

    rows = await upgrade_service._upgrade_repo.list_for_server(server_id)
    items = [_upgrade_to_response(r) for r in rows]
    pinned_item = next(
        (i for i in items if i.status == "active_pinned" and i.pinned_until_confirm),
        None,
    )
    active_item = pinned_item or next(
        (i for i in items if i.status not in _TERMINAL_UPGRADE_STATUSES),
        None,
    )
    return ServerUpgradeListResponse(
        server_id=server_id,
        items=items,
        active_upgrade=active_item,
        banner_active=pinned_item is not None,
        reminder_72h_overdue=bool(pinned_item and pinned_item.reminder_72h_overdue),
    )


@server_p55_router.get("/upgrades/{upgrade_id}", response_model=ServerUpgradeResponse)
async def get_server_upgrade(
    server_id: str,
    upgrade_id: str,
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    _current_user: Annotated[dict, Depends(require_server_permission("server.{id}.view"))],
) -> ServerUpgradeResponse:
    async with database.session_factory() as session:
        await _load_server(session, server_id)
    row = await upgrade_service._upgrade_repo.get(upgrade_id)
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")
    return _upgrade_to_response(row)


@server_p55_router.post("/upgrades/plan", response_model=ServerUpgradeResponse, status_code=201)
async def plan_server_upgrade(
    server_id: str,
    body: PlanUpgradeRequest,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
) -> ServerUpgradeResponse:
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    async with database.session_factory() as session:
        srv = cast(Any, await _load_server(session, server_id))
        extra_hosts = _server_allowlist(srv)
        server_mode = str(getattr(srv, "mode", "simple") or "simple").lower()
        server_root: str | None = str(srv.root_path) if srv.root_path else None

    _require_posix("Upgrade planning is only supported on POSIX hosts in this release")

    target_install_plan: InstallPlan | None = None
    if body.staged_pack_id is not None:
        staged_row = cast(Any, await upgrade_service._upgrade_repo.get(body.staged_pack_id))
        if (
            staged_row is None
            or str(staged_row.server_id) != server_id
            or not staged_row.plan_json
        ):
            raise NotFoundError(
                f"Staged modpack '{body.staged_pack_id}' not found for server '{server_id}'"
            )
        target_install_plan = _install_plan_from_dict(
            cast(dict[str, Any], staged_row.plan_json)
        )

    row, matrix = await upgrade_service.plan_upgrade(
        server_id,
        target_mc=body.target_mc,
        target_loader=LoaderRef(
            id=body.target_loader_id, version=body.target_loader_version
        ),
        mode=server_mode,
        server_root=server_root,
        target_install_plan=target_install_plan,
        target_lec_key=body.target_lec_key,
        excluded_paths=body.excluded_paths,
        extra_allowed_hosts=extra_hosts,
        version_types=body.version_types,
    )
    row_any = cast(Any, row)

    if body.staged_pack_id is not None:
        src_overrides = _staged_pack_dir(layout, server_id, body.staged_pack_id) / "overrides"
        if src_overrides.is_dir():
            dst_overrides = _staged_upgrade_overrides_dir(layout, server_id, str(row_any.id))
            dst_overrides.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copytree(src_overrides, dst_overrides, dirs_exist_ok=True)

    await event_bus.publish(
        UpgradePlannedEvent(
            server_id=server_id,
            upgrade_id=str(row_any.id),
            source_mc=str(row_any.source_mc) if row_any.source_mc else None,
            target_mc=str(row_any.target_mc),
            target_loader_id=str(row_any.target_loader_id),
            target_loader_version=str(row_any.target_loader_version),
            status=str(row_any.status),
            blockers_count=len(matrix.blockers),
            warnings_count=len(matrix.warnings),
            actor_type="user",
            actor_id=_actor_id_from_user(current_user),
        )
    )
    return _upgrade_to_response(row_any)


@server_p55_router.post(
    "/upgrades/{upgrade_id}/manual-upload",
    response_model=ServerUpgradeResponse,
)
async def resolve_upgrade_manual_upload(
    server_id: str,
    upgrade_id: str,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
    file: Annotated[UploadFile, File(...)],
    file_id: Annotated[int | None, Form()] = None,
    path: Annotated[str | None, Form()] = None,
) -> ServerUpgradeResponse:
    async with database.session_factory() as session:
        srv = cast(Any, await _load_server(session, server_id))
        extra_hosts = _server_allowlist(srv)
        server_root: str | None = str(srv.root_path) if srv.root_path else None

    _require_posix("Manual upload resolution requires a POSIX host in this release")

    row = cast(Any, await upgrade_service._upgrade_repo.get(upgrade_id))
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > _MAX_MANUAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail="Manual upload exceeds 512 MB limit"
            )
        chunks.append(chunk)
    payload = b"".join(chunks)

    if str(row.kind) == "modpack_install":
        if not row.plan_json:
            raise ValidationError("Staged modpack has no install plan", field="plan_json")
        plan = _install_plan_from_dict(cast(dict[str, Any], row.plan_json))
        updated_plan, _verified = await resolve_manual_download_upload(
            plan,
            file_id=file_id,
            path=path,
            data=payload,
            cas=upgrade_service._cas,
            modrinth_client=upgrade_service._modrinth_client,
        )
        new_status = (
            "awaiting_manual_uploads" if updated_plan.has_unresolved_blockers else "planned"
        )
        updated_row = await upgrade_service._upgrade_repo.update_status(
            upgrade_id,
            new_status,
            plan_json=cast(dict[str, Any], updated_plan.to_dict()),
            manual_blockers_json=[
                cast(dict[str, Any], b.to_dict()) for b in updated_plan.manual_blockers
            ],
        )
        remaining = sum(1 for b in updated_plan.manual_blockers if not b.resolved)
    else:
        updated_row = await upgrade_service.resolve_manual_upload(
            upgrade_id,
            file_id=file_id,
            path=path,
            data=payload,
            server_root=server_root,
            extra_allowed_hosts=extra_hosts,
        )
        blockers = updated_row.manual_blockers_json or []
        remaining = sum(1 for b in blockers if not b.get("resolved", False))

    await event_bus.publish(
        UpgradeManualBlockerResolvedEvent(
            server_id=server_id,
            upgrade_id=upgrade_id,
            path=path,
            file_id=file_id,
            status=str(updated_row.status),
            remaining_blockers=remaining,
            actor_type="user",
            actor_id=_actor_id_from_user(current_user),
        )
    )
    return _upgrade_to_response(updated_row)


@server_p55_router.post(
    "/upgrades/{upgrade_id}/prepare-test",
    response_model=PrepareUpgradeTestResponse,
)
async def prepare_upgrade_test(
    server_id: str,
    upgrade_id: str,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
    body: PrepareUpgradeTestRequest | None = None,
) -> PrepareUpgradeTestResponse:
    req = body or PrepareUpgradeTestRequest()
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    async with database.session_factory() as session:
        srv = cast(Any, await _load_server(session, server_id))
        extra_hosts = _server_allowlist(srv)
        server_mode = str(getattr(srv, "mode", "simple") or "simple").lower()
        raw_root: str | None = str(srv.root_path) if srv.root_path else None
        server_provider = srv.provider
        memory_max_mb = srv.memory_max_mb
        cpu_cores = srv.cpu_cores
        max_branch_runs = srv.max_concurrent_branch_runs
        java_args = str(srv.java_args or "")
        startup_jar = str(srv.startup_jar or "server.jar")

    if server_mode != "advanced":
        raise ServerModeVersioningDisabledError(
            f"Upgrade branch testing requires Advanced mode "
            f"(server '{server_id}' is '{server_mode}')"
        )
    _require_posix("Upgrade branch testing requires a POSIX host in this release")
    if not raw_root:
        raise ValidationError("Server root path is not configured", field="root_path")
    server_root = Path(os.path.abspath(raw_root))

    row = cast(Any, await upgrade_service._upgrade_repo.get(upgrade_id))
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    target_overrides: dict[str, bytes] = {}
    if row.plan_json:
        plan = _install_plan_from_dict(cast(dict[str, Any], row.plan_json))
        overrides_dir = _staged_upgrade_overrides_dir(layout, server_id, upgrade_id)
        target_overrides = _read_override_blobs_from_dir(overrides_dir, plan)

    prepared = cast(
        Any,
        await upgrade_service.prepare_advanced_upgrade_branch(
            upgrade_id,
            server_root=server_root,
            target_overrides=target_overrides,
            resolved_conflicts={
                k: v.encode("utf-8") for k, v in req.resolved_conflicts.items()
            },
            extra_allowed_hosts=extra_hosts,
            target_slug=req.target_slug,
        ),
    )
    actor_id = _actor_id_from_user(current_user)
    await event_bus.publish(
        UpgradeBranchPreparedEvent(
            server_id=server_id,
            upgrade_id=upgrade_id,
            branch_name=str(prepared.upgrade_branch or ""),
            target_mc=str(prepared.target_mc),
            status=str(prepared.status),
            commit_sha=str(prepared.target_main_sha) if prepared.target_main_sha else None,
            actor_type="user",
            actor_id=actor_id,
        )
    )

    runtime_resp: StartBranchRunResponse | None = None
    if req.start_test and str(prepared.status) != "needs_resolution":
        start_kwargs: dict[str, Any] = {
            "server_provider": server_provider,
            "allow_public_test_join": req.allow_public_test_join,
            "requested_memory_mb": req.requested_memory_mb or memory_max_mb,
            "requested_cpu_cores": req.requested_cpu_cores or (cpu_cores or None),
            "max_concurrent_branch_runs": max_branch_runs,
            "jvm_args": java_args,
            "startup_jar": startup_jar,
            "check_os_ports": req.check_os_ports,
        }
        start_res = await upgrade_service.start_advanced_upgrade_test(
            upgrade_id,
            server_root=server_root,
            start_request_kwargs=start_kwargs,
        )
        refreshed = await upgrade_service._upgrade_repo.get(upgrade_id)
        if refreshed is not None:
            prepared = refreshed
        await event_bus.publish(
            UpgradeTestStartedEvent(
                server_id=server_id,
                upgrade_id=upgrade_id,
                branch_name=str(prepared.upgrade_branch or ""),
                runtime_id=start_res.runtime_id,
                data_template_id=start_res.data_template_id,
                actor_type="user",
                actor_id=actor_id,
            )
        )
        if start_res.port_set is None:
            raise InfrastructureError("Port set unavailable for branch runtime")
        port_data = (
            start_res.port_set.to_dict()
            if hasattr(start_res.port_set, "to_dict")
            else dict(cast(Any, start_res.port_set))
        )
        runtime_resp = StartBranchRunResponse(
            runtime_id=start_res.runtime_id,
            server_id=server_id,
            branch_name=str(prepared.upgrade_branch or ""),
            commit_sha=start_res.commit_sha,
            container_name=start_res.container_name,
            container_id=start_res.container_id,
            port_set=PortSetSchema(**port_data),
            data_template_id=start_res.data_template_id,
            allow_public_test_join=start_res.allow_public_test_join,
            uncommitted_changes_warning=start_res.uncommitted_changes_warning,
            memory_max_mb=start_res.memory_max_mb,
            cpu_cores=start_res.cpu_cores,
        )

    return PrepareUpgradeTestResponse(
        upgrade=_upgrade_to_response(prepared),
        runtime=runtime_resp,
    )


@server_p55_router.post(
    "/upgrades/{upgrade_id}/apply",
    response_model=ServerUpgradeResponse,
)
async def apply_server_upgrade(
    server_id: str,
    upgrade_id: str,
    response: Response,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    refresh_factory: Annotated[
        Callable[[str], Awaitable[LiveRefreshService]],
        Depends(get_upgrade_refresh_service_factory),
    ],
    health_gate_factory: Annotated[
        Callable[[Any, ServerModel], UpgradeHealthGateEvaluator | None],
        Depends(get_upgrade_health_gate_factory),
    ],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
    body: ApplyUpgradeRequest | None = None,
) -> ServerUpgradeResponse:
    req = body or ApplyUpgradeRequest()
    settings = AppSettings()
    layout = ensure_host_state_layout(settings)
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        srv = cast(Any, server)
        extra_hosts = _server_allowlist(server)
        server_mode = str(getattr(srv, "mode", "simple") or "simple").lower()
        raw_root: str | None = str(srv.root_path) if srv.root_path else None
        jvm_args = str(srv.java_args or "")

    _require_posix("Applying server upgrades requires a POSIX host in this release")
    if not raw_root:
        raise ValidationError("Server root path is not configured", field="root_path")
    server_root = Path(os.path.abspath(raw_root))

    row = cast(Any, await upgrade_service._upgrade_repo.get(upgrade_id))
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    actor_id = _actor_id_from_user(current_user)
    op_service = get_operation_service(event_bus)
    op = await op_service.create_operation(
        type=OperationType.SERVER_UPGRADE.value,
        target_type="server",
        target_id=server_id,
        actor_id=actor_id,
        metadata={"upgrade_id": upgrade_id, "mode": server_mode},
        initial_steps=[
            {
                "step_id": "APPLY_UPGRADE",
                "sequence": 1,
                "message_key": "operations.steps.apply_upgrade",
            }
        ],
    )
    row = cast(
        Any,
        await upgrade_service._upgrade_repo.update_status(
            upgrade_id,
            str(row.status),
            operation_id=op.id,
        ),
    )

    async def _run_apply() -> ServerUpgradeResponse:
        await op_service.start_step(op.id, "APPLY_UPGRADE")
        try:
            target_overrides: dict[str, bytes] = {}
            if row.plan_json:
                plan = _install_plan_from_dict(cast(dict[str, Any], row.plan_json))
                overrides_dir = _staged_upgrade_overrides_dir(
                    layout, server_id, upgrade_id
                )
                target_overrides = _read_override_blobs_from_dir(overrides_dir, plan)

            refresh_service = await refresh_factory(server_id)
            health_gate = health_gate_factory(row, server)
            resolved_bytes = {
                k: v.encode("utf-8") for k, v in req.resolved_conflicts.items()
            }

            if server_mode == "advanced":
                if (
                    not row.upgrade_branch
                    or str(row.status) == "needs_resolution"
                    or resolved_bytes
                ):
                    await upgrade_service.prepare_advanced_upgrade_branch(
                        upgrade_id,
                        server_root=server_root,
                        target_overrides=target_overrides,
                        resolved_conflicts=resolved_bytes,
                        extra_allowed_hosts=extra_hosts,
                    )
                res = await upgrade_service.apply_advanced_upgrade_to_live(
                    upgrade_id,
                    server_root=server_root,
                    refresh_service=refresh_service,
                    health_gate=health_gate,
                )
            else:
                res = await upgrade_service.execute_simple_upgrade(
                    upgrade_id,
                    server_root=server_root,
                    refresh_service=refresh_service,
                    health_gate=health_gate,
                    target_overrides=target_overrides,
                    resolved_conflicts=resolved_bytes,
                    extra_allowed_hosts=extra_hosts,
                    jvm_args=jvm_args,
                )

            updated = await upgrade_service._upgrade_repo.get(upgrade_id)
            if updated is None:
                raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

            if res.rolled_back:
                await event_bus.publish(
                    UpgradeRolledBackEvent(
                        server_id=server_id,
                        upgrade_id=upgrade_id,
                        target_mc=str(updated.target_mc),
                        journal_id=res.journal.journal_id,
                        reason=res.health.reason or "Health gate failed",
                        automatic=True,
                        actor_type="system",
                        actor_id=actor_id,
                    )
                )
            else:
                async with database.session_factory() as session:
                    srv = await _load_server(session, server_id)
                    writable_srv = cast(Any, srv)
                    writable_srv.minecraft_version = str(updated.target_mc)
                    writable_srv.server_type = str(updated.target_loader_id)
                    await session.commit()

                await event_bus.publish(
                    UpgradeAppliedEvent(
                        server_id=server_id,
                        upgrade_id=upgrade_id,
                        mode=str(updated.mode),
                        target_mc=str(updated.target_mc),
                        target_loader_id=str(updated.target_loader_id),
                        target_loader_version=str(updated.target_loader_version),
                        journal_id=res.journal.journal_id,
                        pre_upgrade_backup_id=res.pre_upgrade_backup_id,
                        class_c_snapshot_id=res.class_c_snapshot_id,
                        actor_type="user",
                        actor_id=actor_id,
                    )
                )

            await op_service.complete_step(op.id, "APPLY_UPGRADE")
            await op_service.complete_operation(op.id)
            return _upgrade_to_response(updated)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            with contextlib.suppress(Exception):
                await op_service.fail_step(op.id, "APPLY_UPGRADE", error=str(exc)[:500])
                await op_service.fail_operation(
                    op.id,
                    getattr(exc, "code", "INTERNAL_ERROR"),
                    str(exc)[:500],
                    failed_step_id="APPLY_UPGRADE",
                )
            raise

    if req.async_mode:

        async def _background() -> None:
            with contextlib.suppress(BaseException):
                await _run_apply()

        task = asyncio.create_task(_background(), name=f"server-upgrade:{op.id}")
        with contextlib.suppress(Exception):
            op_service.executor.register_task(op.id, task)
        response.status_code = 202
        return _upgrade_to_response(row)

    return await _run_apply()


@server_p55_router.post(
    "/upgrades/{upgrade_id}/confirm",
    response_model=ServerUpgradeResponse,
)
async def confirm_server_upgrade(
    server_id: str,
    upgrade_id: str,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    refresh_factory: Annotated[
        Callable[[str], Awaitable[LiveRefreshService]],
        Depends(get_upgrade_refresh_service_factory),
    ],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
) -> ServerUpgradeResponse:
    async with database.session_factory() as session:
        await _load_server(session, server_id)

    _require_posix("Confirming upgrades requires a POSIX host in this release")
    row = await upgrade_service._upgrade_repo.get(upgrade_id)
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    refresh_service = await refresh_factory(server_id)
    updated = cast(
        Any,
        await upgrade_service.confirm_upgrade_and_unpin(
            upgrade_id, refresh_service=refresh_service
        ),
    )
    await event_bus.publish(
        UpgradeConfirmedEvent(
            server_id=server_id,
            upgrade_id=upgrade_id,
            target_mc=str(updated.target_mc),
            journal_id=str(updated.journal_id) if updated.journal_id else None,
            actor_type="user",
            actor_id=_actor_id_from_user(current_user),
        )
    )
    return _upgrade_to_response(updated)


@server_p55_router.post(
    "/upgrades/{upgrade_id}/rollback",
    response_model=ServerUpgradeResponse,
)
async def rollback_server_upgrade(
    server_id: str,
    upgrade_id: str,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    upgrade_service: Annotated[ModpackUpgradeService, Depends(get_modpack_upgrade_service)],
    refresh_factory: Annotated[
        Callable[[str], Awaitable[LiveRefreshService]],
        Depends(get_upgrade_refresh_service_factory),
    ],
    current_user: Annotated[dict, Depends(require_server_permission("server.{id}.write"))],
    body: RollbackUpgradeRequest | None = None,
) -> ServerUpgradeResponse:
    req = body or RollbackUpgradeRequest()
    async with database.session_factory() as session:
        await _load_server(session, server_id)

    _require_posix("Rolling back upgrades requires a POSIX host in this release")
    row = await upgrade_service._upgrade_repo.get(upgrade_id)
    if row is None or str(row.server_id) != server_id:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    refresh_service = await refresh_factory(server_id)
    await upgrade_service.emergency_rollback_upgrade(
        upgrade_id,
        refresh_service=refresh_service,
        reason=req.reason,
    )
    updated = cast(Any, await upgrade_service._upgrade_repo.get(upgrade_id))
    if updated is None:
        raise NotFoundError(f"Server upgrade '{upgrade_id}' not found")

    if bool(updated.source_mc) and bool(updated.source_loader_id):
        async with database.session_factory() as session:
            srv = await _load_server(session, server_id)
            writable_srv = cast(Any, srv)
            writable_srv.minecraft_version = str(updated.source_mc)
            writable_srv.server_type = str(updated.source_loader_id)
            await session.commit()

    await event_bus.publish(
        UpgradeRolledBackEvent(
            server_id=server_id,
            upgrade_id=upgrade_id,
            target_mc=str(updated.target_mc),
            journal_id=str(updated.journal_id) if updated.journal_id else None,
            reason=req.reason,
            automatic=False,
            actor_type="user",
            actor_id=_actor_id_from_user(current_user),
        )
    )
    return _upgrade_to_response(updated)
