from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_command_bus, get_query_bus, require_permission
from app.api.errors import check_command_result
from app.api.v1.schemas.versioning import (
    BotSettingsRequest,
    BotSettingsResponse,
    BranchResponse,
    CommitResponse,
    CreateBranchRequest,
    CreateCommitRequest,
    PreflightResponse,
    PromoteCommitRequest,
    RunIsolatedTestRequest,
    TestRunResponse,
)
from app.core.command_bus import CommandBus
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    CreateBranchCommand,
    CreateCommitCommand,
    DiscardTestCommand,
    GetCommitHistoryQuery,
    GetServerBranchesQuery,
    GetTestStatusQuery,
    PromoteCommitCommand,
    RunIsolatedTestCommand,
)
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe

router = APIRouter(prefix="/api/v1/servers/{server_id}/versioning", tags=["versioning"])

__all__ = ["router"]


@router.get("/branches", response_model=list[BranchResponse])
async def list_branches(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[BranchResponse]:
    branches = await query_bus.ask(GetServerBranchesQuery(server_id=server_id))
    return [BranchResponse(**b) for b in branches]


@router.post("/branches", response_model=dict[str, Any], status_code=201)
async def create_branch(
    server_id: str,
    body: CreateBranchRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    cmd = CreateBranchCommand(
        server_id=server_id,
        name=body.name,
        head_commit_id=body.head_commit_id,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/commits", response_model=list[CommitResponse])
async def list_commits(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    branch_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CommitResponse]:
    commits = await query_bus.ask(
        GetCommitHistoryQuery(server_id=server_id, branch_id=branch_id, limit=limit)
    )
    return [CommitResponse(**c) for c in commits]


@router.post("/commits", response_model=dict[str, Any], status_code=201)
async def create_commit(
    server_id: str,
    body: CreateCommitRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    author_id = body.author_id or _current_user.get("sub")
    cmd = CreateCommitCommand(
        server_id=server_id,
        message=body.message,
        branch_name=body.branch_name,
        author_id=author_id,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.post("/tests", response_model=dict[str, Any], status_code=202)
async def run_isolated_test(
    server_id: str,
    body: RunIsolatedTestRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:test:execute"))],
) -> dict[str, Any]:
    cmd = RunIsolatedTestCommand(
        server_id=server_id,
        commit_id=body.commit_id,
        bot_count=body.bot_count,
        duration_minutes=body.duration_minutes,
        placement_mode=body.placement_mode,
        bot_tech=body.bot_tech,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/tests/{test_id}", response_model=TestRunResponse)
async def get_test_status(
    server_id: str,
    test_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> TestRunResponse:
    data = await query_bus.ask(GetTestStatusQuery(server_id=server_id, test_id=test_id))
    return TestRunResponse(**data)


@router.post("/tests/{test_id}/promote", response_model=dict[str, Any])
async def promote_commit(
    server_id: str,
    test_id: str,
    body: PromoteCommitRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:promote"))],
) -> dict[str, Any]:
    cmd = PromoteCommitCommand(
        server_id=server_id,
        test_id=test_id,
        keep_world_changes=body.keep_world_changes,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.post("/tests/{test_id}/discard", response_model=dict[str, Any])
async def discard_test(
    server_id: str,
    test_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:test:execute"))],
) -> dict[str, Any]:
    cmd = DiscardTestCommand(server_id=server_id, test_id=test_id)
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/settings", response_model=BotSettingsResponse)
async def get_bot_settings(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> BotSettingsResponse:
    async with database.session_factory() as session:
        server = await session.get(ServerModel, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        stored = server.bot_verification_settings or {}

        resolved = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=stored,
        )

        return BotSettingsResponse(
            server_id=server_id,
            bot_count=stored.get("bot_count"),
            duration_minutes=stored.get("duration_minutes"),
            bot_tech=stored.get("bot_tech"),
            placement_mode=stored.get("placement_mode"),
            effective_bot_count=resolved.bot_count,
            effective_duration_minutes=resolved.duration_minutes,
            effective_bot_tech=resolved.bot_tech.value,
            effective_placement_mode=resolved.placement_mode.value,
        )


@router.put("/settings", response_model=BotSettingsResponse)
async def update_bot_settings(
    server_id: str,
    body: BotSettingsRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:test:configure"))],
) -> BotSettingsResponse:
    async with database.session_factory() as session:
        server = await session.get(ServerModel, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        stored = server.bot_verification_settings or {}
        new_settings = dict(stored)
        if body.bot_count is not None:
            new_settings["bot_count"] = body.bot_count
        if body.duration_minutes is not None:
            new_settings["duration_minutes"] = body.duration_minutes
        if body.bot_tech is not None:
            new_settings["bot_tech"] = body.bot_tech
        if body.placement_mode is not None:
            new_settings["placement_mode"] = body.placement_mode

        server.bot_verification_settings = new_settings
        await session.commit()

        resolved = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=new_settings,
        )

        return BotSettingsResponse(
            server_id=server_id,
            bot_count=new_settings.get("bot_count"),
            duration_minutes=new_settings.get("duration_minutes"),
            bot_tech=new_settings.get("bot_tech"),
            placement_mode=new_settings.get("placement_mode"),
            effective_bot_count=resolved.bot_count,
            effective_duration_minutes=resolved.duration_minutes,
            effective_bot_tech=resolved.bot_tech.value,
            effective_placement_mode=resolved.placement_mode.value,
        )


@router.get("/preflight", response_model=PreflightResponse)
async def get_preflight_status(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    bot_count: int = Query(default=10, ge=0),
) -> PreflightResponse:
    async with database.session_factory() as session:
        server = await session.get(ServerModel, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        server_dir = server.root_path
        server_type = server.server_type

    reflink_ok = StorageCapabilityProbe.probe_path(server_dir)

    headroom = ResourcePreflightProbe.check_headroom(
        bot_count=bot_count,
        server_type=server_type,
    )

    error_msg = None
    if not reflink_ok:
        error_msg = "Filesystem does not support copy-on-write (reflink). Btrfs or ZFS required."
    elif not headroom.passed:
        error_msg = headroom.message

    return PreflightResponse(
        reflink_supported=reflink_ok,
        available_ram_mb=headroom.available_ram_mb,
        available_cores=headroom.available_cores,
        min_required_ram_mb=headroom.required_ram_mb,
        min_required_cores=headroom.required_cores,
        passed=reflink_ok and headroom.passed,
        error=error_msg,
    )
