from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_command_bus, get_current_user, get_event_bus, get_query_bus
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
from app.core.command_bus import Command, CommandBus, CommandResult
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.core.persistence.db import database
from app.modules.server.application import (
    CreateServerCommand,
    DeleteServerCommand,
    GetServerConsoleQuery,
    GetServerQuery,
    GetServerRuntimeDiagnosticsQuery,
    ImportServerCommand,
    ListServersQuery,
    RestartServerCommand,
    StartServerCommand,
    StopServerCommand,
    UpdateServerConfigCommand,
)
from app.modules.server.application.services.import_service import scan_server_directory
from app.modules.server.infrastructure.models import ServerModel
from app.core.persistence.db import database

router = APIRouter(prefix="/api/v1/servers", tags=["servers"])

__all__ = ["router"]


@router.get("/available-port")
async def get_available_port(current_user: dict = Depends(get_current_user)) -> dict:
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
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = CreateServerCommand(
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
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.post("/scan", response_model=ScanResult)
async def scan_directory(
    body: ScanDirectoryRequest,
    current_user: dict = Depends(get_current_user),
) -> ScanResult:
    try:
        result = scan_server_directory(body.path)
        return ScanResult(**result)
    except (NotADirectoryError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied to read the specified directory")


@router.post("/import", response_model=dict, status_code=201)
async def import_server(
    body: ImportServerRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = ImportServerCommand(
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
    current_user: dict = Depends(get_current_user),
) -> ServerDetailResponse:
    result = await query_bus.ask(GetServerQuery(server_id=server_id))
    return ServerDetailResponse(**result.__dict__)


@router.patch("/{server_id}", response_model=dict)
async def update_server(
    server_id: str,
    body: ServerUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = UpdateServerConfigCommand(
        server_id=server_id,
        properties=body.properties,
        min_memory_mb=body.min_memory_mb,
        max_memory_mb=body.max_memory_mb,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> None:
    result = await command_bus.send(DeleteServerCommand(server_id=server_id))
    check_command_result(result)


@router.post("/{server_id}/start", response_model=dict)
async def start_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    result = await command_bus.send(StartServerCommand(server_id=server_id))
    return check_command_result(result)


@router.post("/{server_id}/stop", response_model=dict)
async def stop_server(
    server_id: str,
    body: ServerActionRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    result = await command_bus.send(StopServerCommand(server_id=server_id, reason=body.reason))
    return check_command_result(result)


@router.post("/{server_id}/restart", response_model=dict)
async def restart_server(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    result = await command_bus.send(RestartServerCommand(server_id=server_id))
    return check_command_result(result)


@router.get("/{server_id}/console", response_model=ConsoleResponse)
async def get_server_console(
    server_id: str,
    tail: int = Query(default=100, ge=1, le=10000),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> ConsoleResponse:
    result = await query_bus.ask(GetServerConsoleQuery(server_id=server_id, tail=tail))
    return ConsoleResponse(server_id=result.server_id, lines=result.lines)


@router.get("/{server_id}/runtime", response_model=RuntimeDiagnosticsResponse)
async def get_server_runtime_diagnostics(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
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
            if not server.runtime or not server.runtime.external_id or server.status not in (
                ServerStatus.RUNNING, ServerStatus.STARTING
            ):
                return CommandResult(
                    success=False,
                    error="Server not running",
                    error_code="SERVER_NOT_RUNNING",
                )
            handle = ServerHandle(
                provider=server.runtime.provider,
                server_id=server_id,
                external_id=server.runtime.external_id,
            )
            provider = provider_factory.get(server.runtime.provider)
            await provider.execute_command(handle, command)
            return CommandResult(success=True, data={"server_id": server_id, "command": command})


@router.post("/{server_id}/command", response_model=dict)
async def send_server_command(
    server_id: str,
    body: CommandRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    event_bus: EventBus = Depends(get_event_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    impl = _SendConsoleCommandImpl(event_bus)
    result = await impl.handle(server_id=server_id, command=body.command)
    return check_command_result(result)


@router.get("/runtime/ownership", response_model=RuntimeOwnershipResponse)
async def get_runtime_ownership(
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
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
    command_bus: CommandBus = Depends(get_command_bus),
    event_bus: EventBus = Depends(get_event_bus),
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
) -> ReconciliationResultResponse:
    from app.modules.server.application.services.filesystem_reconciliation import FilesystemReconciliationService
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
