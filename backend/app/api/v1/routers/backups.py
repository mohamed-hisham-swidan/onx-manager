from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_backup_permission,
    require_server_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.backup import (
    BackupResponse,
    CreateBackupRequest,
    VerifyBackupResponse,
)
from app.core.authorization import authorize_server_action, is_admin_or_owner_context
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.backup.application import (
    CreateBackupCommand,
    DeleteBackupCommand,
    GetBackupQuery,
    ListBackupsQuery,
    RestoreBackupCommand,
    VerifyBackupCommand,
)

router = APIRouter(prefix="/api/v1/backups", tags=["backups"])

__all__ = ["router"]


@router.get("", response_model=list[BackupResponse])
async def list_backups(
    server_id: str | None = Query(None),
    tier: str | None = Query(None),
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> list[BackupResponse]:
    if (
        server_id
        and not is_admin_or_owner_context(current_user)
        and not authorize_server_action(current_user, server_id, "backups.view")
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    q = ListBackupsQuery(server_id=server_id, tier=tier)
    backups = await query_bus.ask(q)
    if not is_admin_or_owner_context(current_user):
        backups = [
            b
            for b in backups
            if authorize_server_action(current_user, b.server_id, "backups.view")
        ]
    return [BackupResponse(**b.__dict__) for b in backups]


@router.post("", response_model=dict, status_code=201)
async def create_backup(
    body: CreateBackupRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_server_permission("server.{id}.backups")),
) -> dict:
    cmd = CreateBackupCommand(
        server_id=body.server_id,
        backup_type=body.backup_type,
        tier=body.tier,
        archive_format=body.archive_format,
        include_cas_jars=body.include_cas_jars,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.get("/{backup_id}", response_model=BackupResponse)
async def get_backup(
    backup_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    _current_user: dict = Depends(require_backup_permission("backup:read")),
) -> BackupResponse:
    result = await query_bus.ask(GetBackupQuery(backup_id=backup_id))
    return BackupResponse(**result.__dict__)


@router.delete("/{backup_id}", status_code=204)
async def delete_backup(
    backup_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_backup_permission("backup:delete")),
) -> None:
    cmd = DeleteBackupCommand(backup_id=backup_id)
    result = await command_bus.send(cmd)
    check_command_result(result)


@router.post("/{backup_id}/restore", response_model=dict)
async def restore_backup(
    backup_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_backup_permission("backup:restore")),
) -> JSONResponse:
    cmd = RestoreBackupCommand(backup_id=backup_id)
    result = await command_bus.send(cmd)
    if result.success and result.data and result.data.get("deferred"):
        return JSONResponse(status_code=202, content=result.data)
    return check_command_result(result)


@router.post("/{backup_id}/verify", response_model=VerifyBackupResponse)
async def verify_backup(
    backup_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    _current_user: dict = Depends(require_backup_permission("backup:read")),
) -> VerifyBackupResponse:
    cmd = VerifyBackupCommand(backup_id=backup_id)
    result = await command_bus.send(cmd)
    check_command_result(result)
    return VerifyBackupResponse(**result.data)
