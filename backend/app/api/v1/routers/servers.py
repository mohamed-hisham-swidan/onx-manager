import secrets
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_event_bus,
    get_query_bus,
    require_permission,
    require_server_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.import_server import (
    ImportServerRequest,
    ScanDirectoryRequest,
    ScanResult,
)
from app.api.v1.schemas.server import (
    ClaimLocalhostResponse,
    CommandRequest,
    ConsoleResponse,
    ReconcileRequest,
    ReconciliationResultResponse,
    RuntimeDiagnosticsResponse,
    RuntimeOwnershipResponse,
    ServerActionRequest,
    ServerCreateRequest,
    ServerDetailResponse,
    ServerResponse,
    ServerUpdateRequest,
    ValidationChainResponse,
)
from app.core.command_bus import CommandBus, CommandResult
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.application import (
    CreateServerCommand,
    DeleteServerCommand,
    GetServerConsoleQuery,
    GetServerQuery,
    GetServerRuntimeDiagnosticsQuery,
    ImportServerCommand,
    ListServersQuery,
    RestartServerCommand,
    RetryProvisioningCommand,
    StartServerCommand,
    StopServerCommand,
    UpdateServerConfigCommand,
)
from app.modules.server.application.services.import_service import (
    _safe_extract_zip,
    get_effective_server_dir,
    scan_server_directory,
)
from app.modules.server.infrastructure.models import ServerModel

router = APIRouter(prefix="/api/v1/servers", tags=["servers"])

__all__ = ["router"]


@router.get("/available-port")
async def get_available_port(_current_user: dict = Depends(get_current_user)) -> dict:
    from sqlalchemy import select

    async with database.session_factory() as session:
        result = await session.execute(select(ServerModel.port))
        used_ports = {row[0] for row in result}
    port = 25565
    while port in used_ports and port < 65535:
        port += 1
    return {"port": port}


@router.get("", response_model=list[ServerResponse])
async def list_servers(
    status: str | None = Query(None),
    group_id: str | None = Query(None),
    name_search: str | None = Query(None),
    minecraft_version: str | None = Query(None),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(get_current_user),
) -> list[ServerResponse]:
    q = ListServersQuery(
        status=status,
        group_id=group_id,
        name_search=name_search,
        minecraft_version=minecraft_version,
    )
    servers = await query_bus.ask(q)
    return [ServerResponse(**s.__dict__) for s in servers]


@router.post("", response_model=dict, status_code=201)
async def create_server(
    body: ServerCreateRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(require_permission("server:create")),
) -> dict:
    cmd = CreateServerCommand(
        creator_id=current_user.get("user_id"),
        name=body.name,
        server_type=body.server_type,
        minecraft_version=body.minecraft_version,
        min_memory_mb=body.min_memory_mb,
        max_memory_mb=body.max_memory_mb,
        port=body.port,
        motd=body.motd,
        max_players=body.max_players,
        gamemode=body.gamemode,
        difficulty=body.difficulty,
        spawn_protection=body.spawn_protection,
        pvp=body.pvp,
        enable_command_block=body.enable_command_block,
        online_mode=body.online_mode,
        whitelist=body.whitelist,
        view_distance=body.view_distance,
        simulation_distance=body.simulation_distance,
        java_args=body.java_args,
        group_id=body.group_id,
        install_dir=body.install_dir,
        provider=body.provider,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


def _process_and_scan_zip(zip_path: Path, staging_dir: Path) -> ScanResult:
    try:
        free_bytes = shutil.disk_usage(str(staging_dir)).free
    except OSError:
        free_bytes = 0

    file_size = zip_path.stat().st_size
    required_free = int(file_size * 1.5)
    if free_bytes < required_free:
        raise HTTPException(
            status_code=507,
            detail="Insufficient disk space on host to extract server archive",
        )

    extracted_dir = staging_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    try:
        _safe_extract_zip(zip_path, extracted_dir)
    except zipfile.BadZipFile as e:
        raise HTTPException(
            status_code=400, detail=f"Corrupted or invalid zip file: {e}"
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    effective_dir = get_effective_server_dir(extracted_dir)

    try:
        result = scan_server_directory(str(effective_dir))
        return ScanResult(**result)
    except (NotADirectoryError, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to scan extracted server: {e}"
        ) from e


@router.post("/scan", response_model=ScanResult)
async def scan_directory(
    body: ScanDirectoryRequest,
    _current_user: dict = Depends(require_permission("server:write")),
) -> ScanResult:
    path_obj = Path(body.path).expanduser().resolve()
    if path_obj.is_file() and body.path.lower().endswith(".zip"):
        settings = AppSettings()
        import_id = secrets.token_hex(8)
        staging_dir = Path(settings.import_staging_dir).resolve() / import_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        try:
            return _process_and_scan_zip(path_obj, staging_dir)
        except HTTPException:
            shutil.rmtree(str(staging_dir), ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(str(staging_dir), ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process archive: {exc}",
            ) from exc

    try:
        result = scan_server_directory(body.path)
        return ScanResult(**result)
    except (NotADirectoryError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(
            status_code=403, detail="Permission denied to read the specified directory"
        ) from e


@router.post("/import/upload", response_model=ScanResult)
async def upload_and_scan_server_archive(
    file: UploadFile = File(...),
    _current_user: dict = Depends(require_permission("server:write")),
) -> ScanResult:
    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="Only .zip archives are supported for server import"
        )

    settings = AppSettings()
    max_mb = settings.import_max_zip_size_mb
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0

    import_id = secrets.token_hex(8)
    staging_dir = Path(settings.import_staging_dir).resolve() / import_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    zip_path = staging_dir / "upload.zip"

    try:
        total_bytes = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        with open(zip_path, "wb") as f_out:
            while chunk := await file.read(chunk_size):
                total_bytes += len(chunk)
                if max_bytes > 0 and total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded archive exceeds the maximum allowed size of {max_mb} MB",
                    )
                f_out.write(chunk)

        return _process_and_scan_zip(zip_path, staging_dir)

    except HTTPException:
        shutil.rmtree(str(staging_dir), ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(str(staging_dir), ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to process archive: {exc}") from exc


@router.post("/import", response_model=dict, status_code=201)
async def import_server(
    body: ImportServerRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(require_permission("server:write")),
) -> dict:
    cmd = ImportServerCommand(
        creator_id=current_user.get("user_id"),
        source_path=body.source_path,
        name=body.name,
        server_type=body.server_type,
        minecraft_version=body.minecraft_version,
        min_memory_mb=body.min_memory_mb,
        max_memory_mb=body.max_memory_mb,
        port=body.port,
        motd=body.motd,
        max_players=body.max_players,
        gamemode=body.gamemode,
        difficulty=body.difficulty,
        spawn_protection=body.spawn_protection,
        pvp=body.pvp,
        enable_command_block=body.enable_command_block,
        online_mode=body.online_mode,
        whitelist=body.whitelist,
        view_distance=body.view_distance,
        simulation_distance=body.simulation_distance,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.get("/{server_id}", response_model=ServerDetailResponse)
async def get_server(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(get_current_user),
) -> ServerDetailResponse:
    result = await query_bus.ask(GetServerQuery(server_id=server_id))
    return ServerDetailResponse(**result.__dict__)


@router.patch("/{server_id}", response_model=dict)
async def update_server(
    server_id: str,
    body: ServerUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_permission("server:write")),
) -> dict:
    cmd = UpdateServerConfigCommand(
        server_id=server_id,
        name=body.name,
        properties=body.properties,
        min_memory_mb=body.min_memory_mb,
        max_memory_mb=body.max_memory_mb,
        cpu_cores=body.cpu_cores,
        cpu_affinity=body.cpu_affinity,
        java_args=body.java_args,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_permission("server:delete")),
) -> None:
    result = await command_bus.send(DeleteServerCommand(server_id=server_id))
    check_command_result(result)


@router.post("/{server_id}/start", response_model=dict)
async def start_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.power")),
) -> dict:
    result = await command_bus.send(StartServerCommand(server_id=server_id))
    return check_command_result(result)


@router.post("/{server_id}/stop", response_model=dict)
async def stop_server(
    server_id: str,
    body: ServerActionRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.power")),
) -> dict:
    result = await command_bus.send(StopServerCommand(server_id=server_id, reason=body.reason))
    return check_command_result(result)


@router.post("/{server_id}/restart", response_model=dict)
async def restart_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.power")),
) -> dict:
    result = await command_bus.send(RestartServerCommand(server_id=server_id))
    return check_command_result(result)


@router.post("/{server_id}/retry-provisioning", response_model=dict)
async def retry_provisioning(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.write")),
) -> dict:
    result = await command_bus.send(RetryProvisioningCommand(server_id=server_id))
    return check_command_result(result)


@router.get("/{server_id}/console", response_model=ConsoleResponse)
async def get_server_console(
    server_id: str,
    tail: int = Query(default=100, ge=1, le=10000),
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> ConsoleResponse:
    result = await query_bus.ask(GetServerConsoleQuery(server_id=server_id, tail=tail))
    return ConsoleResponse(server_id=result.server_id, lines=result.lines)


@router.get("/{server_id}/runtime", response_model=RuntimeDiagnosticsResponse)
async def get_server_runtime_diagnostics(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> RuntimeDiagnosticsResponse:
    result = await query_bus.ask(GetServerRuntimeDiagnosticsQuery(server_id=server_id))
    return RuntimeDiagnosticsResponse(**result.data)


class _SendConsoleCommandImpl:
    """Executes a server console command via the provider layer."""

    def __init__(self, event_bus) -> None:
        self._event_bus = event_bus

    async def handle(self, server_id: str, command: str) -> CommandResult:
        from app.modules.server.domain.aggregate import ServerStatus
        from app.modules.server.infrastructure.providers import provider_factory
        from app.modules.server.infrastructure.providers.base import ServerHandle
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            if (
                not server.runtime
                or not server.runtime.external_id
                or server.status not in (ServerStatus.RUNNING, ServerStatus.STARTING)
            ):
                return CommandResult(
                    success=False,
                    error="Server not running",
                    error_code="SERVER_NOT_RUNNING",
                )
            from app.modules.server.domain.value_objects import default_provider_for_platform

            provider_name = server.runtime.provider or default_provider_for_platform()
            handle = ServerHandle(
                provider=provider_name,
                server_id=server_id,
                external_id=server.runtime.external_id,
            )
            provider = provider_factory.get(provider_name)
            await provider.execute_command(handle, command)
            return CommandResult(success=True, data={"server_id": server_id, "command": command})


@router.post("/{server_id}/command", response_model=dict)
async def send_server_command(
    server_id: str,
    body: CommandRequest,
    _command_bus: CommandBus = Depends(get_command_bus),
    event_bus: EventBus = Depends(get_event_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.console")),
) -> dict:
    impl = _SendConsoleCommandImpl(event_bus)
    result = await impl.handle(server_id=server_id, command=body.command)
    return check_command_result(result)


@router.get("/runtime/ownership", response_model=RuntimeOwnershipResponse)
async def get_runtime_ownership(
    _current_user: dict = Depends(require_permission("server:read")),
) -> RuntimeOwnershipResponse:
    from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        manager = RuntimeOwnershipManager(repo)
        snapshot = await manager.discover_all()

    return RuntimeOwnershipResponse(
        timestamp=snapshot.timestamp,
        active_servers=snapshot.active_servers,
        orphan_tmux=[
            {"resource_type": r.resource_type, "identifier": r.identifier, "pid": r.pid}
            for r in snapshot.orphan_tmux
        ],
        orphan_processes=[
            {"resource_type": r.resource_type, "identifier": r.identifier, "pid": r.pid}
            for r in snapshot.orphan_processes
        ],
        stale_db_records=snapshot.stale_db_records,
        conflicts=[
            {"reason": c.reason.value, "detail": c.detail, "auto_resolvable": c.auto_resolvable}
            for c in snapshot.conflicts
        ],
        localhost_owner=snapshot.localhost_owner,
        total_orphans=snapshot.total_orphans,
    )


@router.post("/runtime/ownership/claim", response_model=ClaimLocalhostResponse)
async def claim_runtime_ownership(
    server_id: str,
    _current_user: dict = Depends(require_permission("server:write")),
) -> ClaimLocalhostResponse:
    from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        manager = RuntimeOwnershipManager(repo)
        result = await manager.claim_localhost(server_id)

    return ClaimLocalhostResponse(
        success=result.success,
        actions=result.actions,
        conflicts_resolved=result.conflicts_resolved,
    )


@router.get("/{server_id}/runtime/validate", response_model=ValidationChainResponse)
async def validate_server_runtime(
    server_id: str,
    _current_user: dict = Depends(require_server_permission("server.{id}.view")),
) -> ValidationChainResponse:
    from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        manager = RuntimeOwnershipManager(repo)
        result = await manager.validate_runtime(server_id)

    return ValidationChainResponse(
        server_id=result.server_id,
        healthy=result.healthy,
        chain=result.chain,
    )


@router.post("/reconcile", response_model=dict)
async def reconcile_runtimes(
    body: ReconcileRequest = Body(default=ReconcileRequest()),
    _command_bus: CommandBus = Depends(get_command_bus),
    _event_bus: EventBus = Depends(get_event_bus),
    _current_user: dict = Depends(require_permission("server:write")),
) -> dict:
    from app.modules.server.application.runtime_reconciliation import (
        reconcile_all_runtimes,
        reconcile_orphans,
    )
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        outcomes = await reconcile_all_runtimes(repo)
        orphan_actions = await reconcile_orphans(repo, scope=body.scope)  # type: ignore[arg-type]

    return {
        "total_checked": len(outcomes),
        "repaired": sum(1 for o in outcomes if o.repaired),
        "details": [
            {
                "server_id": o.server_id,
                "server_name": o.server_name,
                "repaired": o.repaired,
                "actions": o.actions,
                "error": o.error,
            }
            for o in outcomes
        ],
        "orphans_cleaned": len(orphan_actions),
    }


@router.post("/refresh", response_model=ReconciliationResultResponse)
async def refresh_servers(
    dry_run: bool = Query(default=False, description="Preview changes without applying them"),
    _current_user: dict = Depends(require_permission("server:write")),
) -> ReconciliationResultResponse:
    from app.modules.server.application.services.filesystem_reconciliation import (
        FilesystemReconciliationService,
    )
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        service = FilesystemReconciliationService(repo)
        result = await service.reconcile(dry_run=dry_run)
        if not dry_run:
            await session.commit()

    return ReconciliationResultResponse(
        imported=result.imported,
        updated=result.updated,
        deleted=result.deleted,
        missing=result.missing,
        broken=result.broken,
        unchanged=result.unchanged,
        ignored=result.ignored,
        invalid_identity=result.invalid_identity,
        errors=result.errors,
        identity_written=result.identity_written,
        total_imported=result.total_imported,
        total_updated=result.total_updated,
        total_deleted=result.total_deleted,
        total_missing=result.total_missing,
        total_broken=result.total_broken,
        total_unchanged=result.total_unchanged,
        total_ignored=result.total_ignored,
        total_invalid_identity=result.total_invalid_identity,
        total_errors=result.total_errors,
        total_dirs_found=result.total_dirs_found,
        total_minecraft_dirs=result.total_minecraft_dirs,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_ms=result.duration_ms,
        dry_run=dry_run,
    )
