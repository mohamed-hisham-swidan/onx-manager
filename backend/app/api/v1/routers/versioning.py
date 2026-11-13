from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_command_bus, get_query_bus, require_permission
from app.api.errors import check_command_result
from app.api.v1.dependencies.server_mode import require_advanced_mode
from app.api.v1.schemas.versioning import (
    AutoCommitLiveChangesRequest,
    AutoCommitLiveChangesResponse,
    BotSettingsRequest,
    BotSettingsResponse,
    BranchProtectionResponse,
    BranchResponse,
    CommitResponse,
    CreateBranchRequest,
    CreateCommitRequest,
    CreateMaterializationRequest,
    CreateTagRequest,
    DiffResponse,
    EvidenceBundleResponse,
    ImportReviewActionResponse,
    MaterializationCreateResponse,
    MaterializationFileResponse,
    MaterializationListItemResponse,
    MaterializationTreeResponse,
    MergeCommitsRequest,
    PreflightResponse,
    PromoteCommitRequest,
    RunIsolatedTestRequest,
    ScanLiveChangesRequest,
    ScanLiveChangesResponse,
    SetBranchProtectionRequest,
    SetEditModeRequest,
    SetEditModeResponse,
    TagResponse,
    TestDefinitionCreateRequest,
    TestDefinitionResponse,
    TestDefinitionUpdateRequest,
    TestRunResponse,
    WriteMaterializedFileRequest,
    WriteMaterializedFileResponse,
)
from app.core.command_bus import CommandBus
from app.core.exceptions import MaterializationFileTooLargeError, PermissionDenied
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    AutoCommitLiveChangesCommand,
    ConfirmImportReviewCommand,
    CreateBranchCommand,
    CreateCommitCommand,
    CreateMaterializationCommand,
    CreateTagCommand,
    CreateTestDefinitionCommand,
    DeleteBranchCommand,
    DeleteTestDefinitionCommand,
    DiffCommitsQuery,
    DiscardTestCommand,
    DismissImportReviewCommand,
    GetBranchHistoryQuery,
    GetBranchProtectionQuery,
    GetCommitHistoryQuery,
    GetMaterializationFileQuery,
    GetMaterializationsQuery,
    GetMaterializationTreeQuery,
    GetServerBranchesQuery,
    GetServerTagQuery,
    GetServerTagsQuery,
    GetServerTestRunsQuery,
    GetTestDefinitionQuery,
    GetTestRunEvidenceQuery,
    GetTestStatusQuery,
    ListTestDefinitionsQuery,
    MergeCommitsCommand,
    PromoteCommitCommand,
    RemoveBranchProtectionCommand,
    RemoveMaterializationCommand,
    RevertImportReviewCommand,
    RunIsolatedTestCommand,
    ScanLiveChangesQuery,
    SetBranchProtectionCommand,
    SetMaterializationEditModeCommand,
    UpdateTestDefinitionCommand,
    WriteMaterializedFileCommand,
)
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe

router = APIRouter(
    prefix="/api/v1/servers/{server_id}/versioning",
    tags=["versioning"],
    dependencies=[Depends(require_advanced_mode)],
)

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


@router.post("/branches/{name}/archive", response_model=dict[str, Any])
async def archive_branch(
    server_id: str,
    name: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    cmd = ArchiveBranchCommand(server_id=server_id, name=name)
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.delete("/branches/{name}", response_model=dict[str, Any])
async def delete_branch(
    server_id: str,
    name: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    cmd = DeleteBranchCommand(server_id=server_id, name=name)
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/branches/{name}/protection", response_model=BranchProtectionResponse)
async def get_branch_protection(
    server_id: str,
    name: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> BranchProtectionResponse:
    res = await query_bus.ask(
        GetBranchProtectionQuery(server_id=server_id, branch_name=name)
    )
    return BranchProtectionResponse(**res)


@router.put("/branches/{name}/protection", response_model=BranchProtectionResponse)
async def set_branch_protection(
    server_id: str,
    name: str,
    body: SetBranchProtectionRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:branch:protect"))],
) -> BranchProtectionResponse:
    policy_dict = body.policy.model_dump() if body.policy else None
    cmd = SetBranchProtectionCommand(
        server_id=server_id,
        branch_name=name,
        policy=policy_dict,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return BranchProtectionResponse(
        server_id=data["server_id"],
        branch_name=data["branch_name"],
        is_protected=data["is_protected"],
        policy=data["policy"],
    )


@router.delete("/branches/{name}/protection", response_model=BranchProtectionResponse)
async def remove_branch_protection(
    server_id: str,
    name: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:branch:protect"))],
) -> BranchProtectionResponse:
    cmd = RemoveBranchProtectionCommand(server_id=server_id, branch_name=name)
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return BranchProtectionResponse(
        server_id=data["server_id"],
        branch_name=data["branch_name"],
        is_protected=data["is_protected"],
        policy=data.get("policy"),
    )


@router.get("/branches/{name}/history", response_model=list[CommitResponse])
async def get_branch_history(
    server_id: str,
    name: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[CommitResponse]:
    commits = await query_bus.ask(
        GetBranchHistoryQuery(server_id=server_id, branch_name=name, limit=limit)
    )
    return [CommitResponse(**c) for c in commits]


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


@router.get("/commits/diff", response_model=DiffResponse)
async def diff_commits_endpoint(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    from_commit_id: str = Query(..., alias="from"),
    to_commit_id: str = Query(..., alias="to"),
) -> DiffResponse:
    diff = await query_bus.ask(
        DiffCommitsQuery(
            server_id=server_id,
            from_commit_id=from_commit_id,
            to_commit_id=to_commit_id,
        )
    )
    return DiffResponse(**diff)


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
        force=body.force,
        force_reason=body.force_reason,
        caller_permissions=_current_user.get("permissions", []),
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.post("/commits/merge", response_model=dict[str, Any], status_code=201)
async def merge_commits_endpoint(
    server_id: str,
    body: MergeCommitsRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    author_id = body.author_id or _current_user.get("sub")
    cmd = MergeCommitsCommand(
        server_id=server_id,
        target_branch_name=body.target_branch_name,
        parent_commit_ids=body.parent_commit_ids,
        message=body.message,
        author_id=author_id,
        manifest=body.manifest,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.post("/tags", response_model=dict[str, Any], status_code=201)
async def create_tag(
    server_id: str,
    body: CreateTagRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    cmd = CreateTagCommand(
        server_id=server_id,
        name=body.name,
        commit_id=body.commit_id,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[TagResponse]:
    tags = await query_bus.ask(GetServerTagsQuery(server_id=server_id))
    return [TagResponse(**t) for t in tags]


@router.get("/tags/{name}", response_model=TagResponse)
async def get_tag(
    server_id: str,
    name: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> TagResponse:
    tag = await query_bus.ask(GetServerTagQuery(server_id=server_id, name=name))
    if tag is None:
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found")
    return TagResponse(**tag)


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
        test_definition_id=body.test_definition_id,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/tests", response_model=list[TestRunResponse])
async def list_test_runs(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[TestRunResponse]:
    data = await query_bus.ask(GetServerTestRunsQuery(server_id=server_id, limit=limit))
    return [TestRunResponse(**item) for item in data]


@router.get("/tests/{test_id}", response_model=TestRunResponse)
async def get_test_status(
    server_id: str,
    test_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> TestRunResponse:
    data = await query_bus.ask(GetTestStatusQuery(server_id=server_id, test_id=test_id))
    return TestRunResponse(**data)


@router.get("/tests/{test_id}/evidence", response_model=EvidenceBundleResponse)
async def get_test_run_evidence(
    server_id: str,
    test_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> EvidenceBundleResponse:
    data = await query_bus.ask(GetTestRunEvidenceQuery(server_id=server_id, test_id=test_id))
    return EvidenceBundleResponse(**data)


@router.post("/tests/{test_id}/promote", response_model=dict[str, Any])
async def promote_commit(
    server_id: str,
    test_id: str,
    body: PromoteCommitRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    current_user: Annotated[dict, Depends(require_permission("server:version:promote"))],
) -> dict[str, Any]:
    if body.force:
        user_perms = current_user.get("permissions", [])
        if "admin:full" not in user_perms and "server:version:promote:force" not in user_perms:
            raise PermissionDenied("missing required permission: server:version:promote:force")
    cmd = PromoteCommitCommand(
        server_id=server_id,
        test_id=test_id,
        keep_world_changes=body.keep_world_changes,
        force=body.force,
        force_reason=body.force_reason,
        actor_id=current_user.get("sub") or current_user.get("username"),
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


@router.get("/test-definitions", response_model=list[TestDefinitionResponse])
async def list_test_definitions(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[TestDefinitionResponse]:
    data = await query_bus.ask(ListTestDefinitionsQuery(server_id=server_id))
    return [TestDefinitionResponse(**item) for item in data]


@router.post("/test-definitions", response_model=dict[str, Any], status_code=201)
async def create_test_definition(
    server_id: str,
    body: TestDefinitionCreateRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:test:configure"))],
) -> dict[str, Any]:
    cmd = CreateTestDefinitionCommand(
        server_id=server_id,
        name=body.name,
        description=body.description,
        server_type=body.server_type,
        bot_technology=body.bot_technology,
        bot_count=body.bot_count,
        duration_seconds=body.duration_seconds,
        join_stagger_seconds=body.join_stagger_seconds,
        connect_grace_seconds=body.connect_grace_seconds,
        placement_mode=body.placement_mode,
        assertion_rules=body.assertion_rules,
        timeout_seconds=body.timeout_seconds,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.get("/test-definitions/{id}", response_model=TestDefinitionResponse)
async def get_test_definition(
    server_id: str,
    id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> TestDefinitionResponse:
    data = await query_bus.ask(GetTestDefinitionQuery(server_id=server_id, definition_id=id))
    if data is None:
        raise HTTPException(status_code=404, detail=f"Test definition '{id}' not found")
    return TestDefinitionResponse(**data)


@router.put("/test-definitions/{id}", response_model=dict[str, Any])
async def update_test_definition(
    server_id: str,
    id: str,
    body: TestDefinitionUpdateRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:test:configure"))],
) -> dict[str, Any]:
    cmd = UpdateTestDefinitionCommand(
        server_id=server_id,
        definition_id=id,
        name=body.name,
        description=body.description,
        server_type=body.server_type,
        bot_technology=body.bot_technology,
        bot_count=body.bot_count,
        duration_seconds=body.duration_seconds,
        join_stagger_seconds=body.join_stagger_seconds,
        connect_grace_seconds=body.connect_grace_seconds,
        placement_mode=body.placement_mode,
        assertion_rules=body.assertion_rules,
        timeout_seconds=body.timeout_seconds,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.delete("/test-definitions/{id}", response_model=dict[str, Any])
async def delete_test_definition(
    server_id: str,
    id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:test:configure"))],
) -> dict[str, Any]:
    cmd = DeleteTestDefinitionCommand(server_id=server_id, definition_id=id)
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

    reflink_ok = StorageCapabilityProbe.probe_path(server_dir) if server_dir else False

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


# --- Stage C Materialization & Import Review Endpoints ---


@router.post("/materializations", response_model=MaterializationCreateResponse, status_code=201)
async def create_materialization(
    server_id: str,
    body: CreateMaterializationRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> MaterializationCreateResponse:
    cmd = CreateMaterializationCommand(
        server_id=server_id,
        revision_type=body.revision_type,
        ref=body.ref,
        mode=body.mode,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return MaterializationCreateResponse(**data)


@router.get("/materializations", response_model=list[MaterializationListItemResponse])
async def list_materializations(
    server_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[MaterializationListItemResponse]:
    query = GetMaterializationsQuery(server_id=server_id)
    items = await query_bus.ask(query)
    return [MaterializationListItemResponse(**m) for m in items]


@router.get("/materializations/{mat_id}/tree", response_model=MaterializationTreeResponse)
async def get_materialization_tree(
    server_id: str,
    mat_id: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    path: str = "",
) -> MaterializationTreeResponse:
    query = GetMaterializationTreeQuery(
        materialization_id=mat_id,
        server_id=server_id,
        path=path,
    )
    data = await query_bus.ask(query)
    return MaterializationTreeResponse(**data)


@router.get("/materializations/{mat_id}/files", response_model=MaterializationFileResponse)
async def get_materialization_file(
    server_id: str,
    mat_id: str,
    path: str,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> MaterializationFileResponse:
    query = GetMaterializationFileQuery(
        materialization_id=mat_id,
        server_id=server_id,
        path=path,
    )
    try:
        data = await query_bus.ask(query)
    except MaterializationFileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=exc.message) from exc
    return MaterializationFileResponse(**data)


@router.post("/materializations/{mat_id}/edit-mode", response_model=SetEditModeResponse)
async def set_materialization_edit_mode(
    server_id: str,
    mat_id: str,
    body: SetEditModeRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> SetEditModeResponse:
    cmd = SetMaterializationEditModeCommand(
        materialization_id=mat_id,
        server_id=server_id,
        enabled=body.enabled,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return SetEditModeResponse(**data)


@router.put("/materializations/{mat_id}/files", response_model=WriteMaterializedFileResponse)
async def write_materialized_file(
    server_id: str,
    mat_id: str,
    body: WriteMaterializedFileRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> WriteMaterializedFileResponse:
    cmd = WriteMaterializedFileCommand(
        materialization_id=mat_id,
        server_id=server_id,
        path=body.path,
        content=body.content,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return WriteMaterializedFileResponse(**data)


@router.delete("/materializations/{mat_id}", response_model=dict[str, Any])
async def remove_materialization(
    server_id: str,
    mat_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> dict[str, Any]:
    cmd = RemoveMaterializationCommand(
        materialization_id=mat_id,
        server_id=server_id,
    )
    res = await command_bus.send(cmd)
    return check_command_result(res)


@router.post("/import-review/scan", response_model=ScanLiveChangesResponse)
async def scan_live_changes(
    server_id: str,
    body: ScanLiveChangesRequest,
    query_bus: Annotated[QueryBus, Depends(get_query_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> ScanLiveChangesResponse:
    query = ScanLiveChangesQuery(
        server_id=server_id,
        source=body.source,
    )
    data = await query_bus.ask(query)
    return ScanLiveChangesResponse(**data)


@router.post(
    "/import-review/auto-commit",
    response_model=AutoCommitLiveChangesResponse,
    status_code=201,
)
async def auto_commit_live_changes(
    server_id: str,
    body: AutoCommitLiveChangesRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> AutoCommitLiveChangesResponse:
    cmd = AutoCommitLiveChangesCommand(
        server_id=server_id,
        branch=body.branch,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return AutoCommitLiveChangesResponse(**data)


@router.post(
    "/import-review/{review_id}/confirm",
    response_model=ImportReviewActionResponse,
)
async def confirm_import_review(
    server_id: str,
    review_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ImportReviewActionResponse:
    cmd = ConfirmImportReviewCommand(
        review_id=review_id,
        server_id=server_id,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return ImportReviewActionResponse(**data)


@router.post(
    "/import-review/{review_id}/dismiss",
    response_model=ImportReviewActionResponse,
)
async def dismiss_import_review(
    server_id: str,
    review_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ImportReviewActionResponse:
    cmd = DismissImportReviewCommand(
        review_id=review_id,
        server_id=server_id,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return ImportReviewActionResponse(**data)


@router.post(
    "/import-review/{review_id}/revert",
    response_model=ImportReviewActionResponse,
)
async def revert_import_review(
    server_id: str,
    review_id: str,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ImportReviewActionResponse:
    cmd = RevertImportReviewCommand(
        review_id=review_id,
        server_id=server_id,
    )
    res = await command_bus.send(cmd)
    data = check_command_result(res)
    return ImportReviewActionResponse(**data)

