from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

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
    ClassCSnapshotDeleteResponse,
    ClassCSnapshotResponse,
    ClassCSnapshotRestoreResponse,
    CommitResponse,
    ConfirmUpgradeHttpRequest,
    ConfirmUpgradeResponse,
    CreateBranchRequest,
    CreateClassCSnapshotRequest,
    CreateCommitRequest,
    CreateMaterializationRequest,
    CreateTagRequest,
    DeleteSecretResponse,
    DiffResponse,
    DynamicClassCEntryResponse,
    DynamicClassCResetRequest,
    DynamicClassCResetResponse,
    EvidenceBundleResponse,
    ExtractSecretHttpRequest,
    ExtractSecretResponse,
    ImportReviewActionResponse,
    MaterializationCreateResponse,
    MaterializationFileResponse,
    MaterializationListItemResponse,
    MaterializationTreeResponse,
    MergeCommitsRequest,
    PreflightResponse,
    RefreshJournalSummaryResponse,
    RefreshServerHttpRequest,
    RefreshServerResponse,
    RefreshStateResponse,
    RollbackRefreshHttpRequest,
    RollbackRefreshResponse,
    RunIsolatedTestRequest,
    ScanLiveChangesRequest,
    ScanLiveChangesResponse,
    SecretMetadataResponse,
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
from app.core.exceptions import MaterializationFileTooLargeError
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
from app.modules.versioning.application.refresh_orchestrator import (
    ConfirmUpgradeCommand,
    RefreshServerCommand,
    ReleaseRefreshPinsCommand,
    RollbackRefreshCommand,
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
    res = await query_bus.ask(GetBranchProtectionQuery(server_id=server_id, branch_name=name))
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
    branch: str | None = Query(default=None),
    branch_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CommitResponse]:
    commits = await query_bus.ask(
        GetCommitHistoryQuery(
            server_id=server_id, branch_name=branch, branch_id=branch_id, limit=limit
        )
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
        force=body.force or body.force_bypass_protection,
        force_reason=body.force_reason,
        caller_permissions=_current_user.get("permissions", []),
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
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found")  # noqa: B904
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
        raise HTTPException(status_code=404, detail=f"Test definition '{id}' not found")  # noqa: B904
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
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        stored = server.bot_verification_settings or {}

        from app.modules.versioning.application.refresh_orchestrator import (
            parse_retention_policy as _parse_retention,
        )
        from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel

        resolved = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=stored,
        )

        lease = await session.get(ServerRepoLeaseModel, server_id)
        retention = (
            lease.previous_tree_retention
            if lease is not None
            else stored.get("previous_tree_retention", "until_health_gate")
        )
        try:
            retention = _parse_retention(retention)[0]
        except Exception:
            retention = "until_health_gate"

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
            previous_tree_retention=retention,
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
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904

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

        from app.modules.versioning.application.refresh_orchestrator import (
            parse_retention_policy as _parse_retention,
        )
        from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel

        retention_value = "until_health_gate"
        if body.previous_tree_retention is not None:
            try:
                normalized, _ = _parse_retention(body.previous_tree_retention)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc  # noqa: B904
            new_settings["previous_tree_retention"] = normalized
            retention_value = normalized

            lease = await session.get(ServerRepoLeaseModel, server_id)
            if lease is None:
                lease = ServerRepoLeaseModel(
                    server_id=server_id, previous_tree_retention=normalized
                )
                session.add(lease)
            else:
                lease.previous_tree_retention = normalized

        server.bot_verification_settings = new_settings
        await session.commit()

        resolved = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=new_settings,
        )

        lease = await session.get(ServerRepoLeaseModel, server_id)
        if lease is not None:
            retention_value = lease.previous_tree_retention

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
            previous_tree_retention=retention_value,
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
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
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
        raise HTTPException(status_code=413, detail=exc.message) from exc  # noqa: B904
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


# --- P3-4 Batch B: refresh / rollback / confirm / release-pins ---


@router.get("/refresh", response_model=RefreshStateResponse)
async def get_refresh_state(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> RefreshStateResponse:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel
    from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRepository

    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        try:
            await server_repo.get(ServerId(server_id))
        except Exception:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        from app.core.host_state import resolve_host_state_layout as _rhl

        journal_repo = RefreshJournalRepository(_rhl())
        active = await journal_repo.get_active_for_server(server_id)
        latest = await journal_repo.get_latest_for_server(server_id)
        lease = await session.get(ServerRepoLeaseModel, server_id)

    def _summary(rec):
        if rec is None:
            return None
        return RefreshJournalSummaryResponse(
            journal_id=rec.journal_id,
            server_id=rec.server_id,
            phase=rec.phase,
            terminal=rec.terminal,
            target_main_sha=rec.target_main_sha or "",
            previous_main_sha=rec.previous_main_sha or "",
            class_c_snapshot_id=rec.class_c_snapshot_id,
            class_c_Manifest_sha256=None,
            previous_dir=(
                rec.staging_path if getattr(rec, "used_exchange", False) else rec.previous_path
            ),
            retention_policy=rec.retention_policy,
            retain_until=rec.previous_tree_expires_at,
            rollback_reason=rec.error,
            error_detail=rec.error,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )

    active_s = _summary(active)
    latest_s = _summary(latest)
    def _prev_dir(rec):
        if rec is None:
            return None
        return rec.staging_path if getattr(rec, "used_exchange", False) else rec.previous_path

    can_confirm = bool(
        latest
        and latest.phase in ("COMPLETED", "ROLLED_BACK")
        and (
            bool(latest.class_c_snapshot_id)
            or bool(_prev_dir(latest) and Path(_prev_dir(latest)).exists())
        )
    )
    can_rollback = bool(
        active is not None
        or (
            latest
            and latest.phase == "COMPLETED"
            and _prev_dir(latest)
            and Path(_prev_dir(latest)).exists()
        )
    )
    retention = lease.previous_tree_retention if lease is not None else "until_health_gate"
    return RefreshStateResponse(
        server_id=server_id,
        active_journal=active_s,
        latest_journal=latest_s,
        can_confirm_upgrade=can_confirm,
        can_rollback=can_rollback,
        previous_tree_retention=retention,
    )


@router.post("/refresh", response_model=RefreshServerResponse)
async def post_refresh(
    server_id: str,
    body: RefreshServerHttpRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> RefreshServerResponse:
    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.application.refresh_orchestrator import (
        STAGING_SUFFIX,
        LiveRefreshRequest,
        parse_retention_policy,
    )

    layout = resolve_host_state_layout()
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        try:
            server = await server_repo.get(ServerId(server_id))
        except Exception:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904

    root_path = (
        getattr(getattr(server, "deployment", None), "root_path", None)
        or getattr(server, "root_path", None)
    )
    if not root_path:
        raise HTTPException(status_code=404, detail="Server root path not configured")  # noqa: B904
    live_dir = Path(root_path).resolve()
    staging_dir = Path(f"{live_dir}{STAGING_SUFFIX}")
    repo_dir = layout.repo_dir(server_id) / "repo.git"

    # target sha
    import subprocess as _sp

    target_main_sha = body.target_main_sha
    if target_main_sha:
        if repo_dir.is_dir():
            r = await asyncio.to_thread(
                _sp.run,
                [
                    "git",
                    "--git-dir",
                    str(repo_dir),
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    f"{target_main_sha}^{{commit}}",
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise HTTPException(status_code=404, detail="Target ref not found")  # noqa: B904
            target_main_sha = r.stdout.strip()
    else:
        if repo_dir.is_dir():
            r = await asyncio.to_thread(
                _sp.run,
                [
                    "git",
                    "--git-dir",
                    str(repo_dir),
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    "refs/heads/main^{commit}",
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise HTTPException(  # noqa: B904
                    status_code=409, detail="Repository has no main branch commit to refresh"
                )
            target_main_sha = r.stdout.strip()
        else:
            raise HTTPException(  # noqa: B904
                status_code=409, detail="Repository has no main branch commit to refresh"
            )

    # previous main sha
    previous_main_sha = target_main_sha
    _resolved_previous = False
    onx_complete = live_dir / ".onx-complete.json"
    if onx_complete.is_file():
        try:
            import json as _json

            data = _json.loads(onx_complete.read_text())
            if isinstance(data, dict) and data.get("target_main_sha"):
                previous_main_sha = data["target_main_sha"]
                _resolved_previous = True
        except Exception:
            pass
    if not _resolved_previous:
        try:
            from app.modules.versioning.infrastructure.refresh_journal import (
                RefreshJournalRepository,
            )

            _journal_repo = RefreshJournalRepository(layout)
            _latest = await _journal_repo.get_latest_for_server(server_id)
            if (
                _latest is not None
                and _latest.phase in ("COMPLETED", "UPGRADE_CONFIRMED")
                and getattr(_latest, "target_main_sha", None)
            ):
                previous_main_sha = _latest.target_main_sha
                _resolved_previous = True
        except Exception:
            pass
    if not _resolved_previous:
        previous_main_sha = target_main_sha

    # (Staging directory is created by the clean-export stage inside refresh.)

    # retention
    if body.retention_policy is not None:
        try:
            retention_policy = parse_retention_policy(body.retention_policy)[0]
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))  # noqa: B904
    else:
        from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel

        async with database.session_factory() as session:
            lease = await session.get(ServerRepoLeaseModel, server_id)
            retention_policy = (
                lease.previous_tree_retention if lease is not None else "until_health_gate"
            )

    export_bytes = 0
    if staging_dir.exists():
        for root, _, files in os.walk(staging_dir):
            for f in files:
                with contextlib.suppress(OSError):
                    export_bytes += (Path(root) / f).stat().st_size
    elif live_dir.exists():
        for root, _, files in os.walk(live_dir):
            for f in files:
                with contextlib.suppress(OSError):
                    export_bytes += (Path(root) / f).stat().st_size

    req = LiveRefreshRequest(
        server_id=server_id,
        live_dir=str(live_dir),
        staging_dir=str(staging_dir),
        export_bytes=export_bytes,
        retention_policy=retention_policy,
        previous_main_sha=previous_main_sha,
        target_main_sha=target_main_sha,
        export_id="",
    )

    cmd = RefreshServerCommand(
        server_id=server_id,
        request=req,
        actor_id=str(_current_user.get("user_id") or _current_user.get("id") or ""),
    )
    res = await command_bus.send(cmd)
    check_command_result(res)
    journal = getattr(res, "data", None)
    if hasattr(journal, "journal"):
        journal = journal.journal
    journal_id = getattr(journal, "journal_id", None) if journal is not None else None
    phase = getattr(journal, "phase", None) if journal is not None else None
    return RefreshServerResponse(
        server_id=server_id, journal_id=journal_id, phase=phase, status="ok"
    )


@router.post("/rollback", response_model=RollbackRefreshResponse)
async def post_rollback(
    server_id: str,
    body: RollbackRefreshHttpRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> RollbackRefreshResponse:
    cmd = RollbackRefreshCommand(
        server_id=server_id, journal_id=body.journal_id, reason=body.reason
    )
    res = await command_bus.send(cmd)
    check_command_result(res)
    journal = getattr(res, "data", None)
    if hasattr(journal, "journal"):
        journal = journal.journal
    journal_id = getattr(journal, "journal_id", None) if journal is not None else body.journal_id
    phase = getattr(journal, "phase", None) if journal is not None else None
    return RollbackRefreshResponse(
        server_id=server_id, journal_id=journal_id, phase=phase, status="ok"
    )


@router.post("/upgrade/confirm", response_model=ConfirmUpgradeResponse)
async def post_confirm_upgrade(
    server_id: str,
    body: ConfirmUpgradeHttpRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ConfirmUpgradeResponse:
    cmd = ConfirmUpgradeCommand(server_id=server_id, journal_id=body.journal_id)
    res = await command_bus.send(cmd)
    check_command_result(res)
    journal = getattr(res, "data", None)
    journal_id = getattr(journal, "journal_id", None) if journal is not None else body.journal_id
    phase = getattr(journal, "phase", None) if journal is not None else None
    return ConfirmUpgradeResponse(
        server_id=server_id, journal_id=journal_id, phase=phase, status="ok"
    )


@router.post("/refresh/release-pins", response_model=ConfirmUpgradeResponse)
async def post_release_pins(
    server_id: str,
    body: ConfirmUpgradeHttpRequest,
    command_bus: Annotated[CommandBus, Depends(get_command_bus)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ConfirmUpgradeResponse:
    cmd = ReleaseRefreshPinsCommand(server_id=server_id, journal_id=body.journal_id)
    res = await command_bus.send(cmd)
    check_command_result(res)
    journal = getattr(res, "data", None)
    journal_id = getattr(journal, "journal_id", None) if journal is not None else body.journal_id
    phase = getattr(journal, "phase", None) if journal is not None else None
    return ConfirmUpgradeResponse(
        server_id=server_id, journal_id=journal_id, phase=phase, status="ok"
    )


# --- P3-4 Batch B: class-c snapshots / dynamic / secrets ---


@router.get("/class-c/snapshots", response_model=list[ClassCSnapshotResponse])
async def list_class_c_snapshots(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[ClassCSnapshotResponse]:
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService

    layout = resolve_host_state_layout()
    svc = ClassCSnapshotService(layout)
    rows = svc.repository.list_active(server_id)
    return [
        ClassCSnapshotResponse(
            snapshot_id=r.snapshot_id,
            server_id=r.server_id,
            created_at=r.created_at.isoformat()
            if hasattr(r.created_at, "isoformat")
            else str(r.created_at),
            manifest_sha256=r.manifest_sha256,
            pinned=r.pinned,
            entry_count=r.file_count,
            archive_size_bytes=r.total_bytes,
        )
        for r in rows
    ]


@router.post("/class-c/snapshots", response_model=ClassCSnapshotResponse, status_code=201)
async def create_class_c_snapshot(
    server_id: str,
    body: CreateClassCSnapshotRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ClassCSnapshotResponse:
    from pathlib import Path

    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="class-c-snapshot-create"):  # noqa: E501
        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            server = await server_repo.get(ServerId(server_id))
            if server is None:
                raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
            root_path = (
                getattr(getattr(server, "deployment", None), "root_path", None)
                or getattr(server, "root_path", None)
            )
            if not root_path and getattr(server, "deployment", None):
                root_path = getattr(server.deployment, "root_path", None)
            if not root_path:
                raise HTTPException(status_code=404, detail="Server root path not configured")  # noqa: B904
            live_dir = Path(root_path).resolve()
        dyn = DynamicClassCService(layout)
        dynamic_paths = dyn.list_paths(server_id)
        svc = ClassCSnapshotService(layout)
        result = svc.create_snapshot(
            server_id, live_dir, dynamic_class_c=dynamic_paths, pinned=body.pinned
        )
        return ClassCSnapshotResponse(
            snapshot_id=result.snapshot_id,
            server_id=server_id,
            created_at=None,
            manifest_sha256=result.manifest_sha256,
            pinned=body.pinned,
            entry_count=result.file_count,
            archive_size_bytes=result.total_bytes,
        )


@router.post(
    "/class-c/snapshots/{snapshot_id}/restore", response_model=ClassCSnapshotRestoreResponse
)
async def restore_class_c_snapshot(
    server_id: str,
    snapshot_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ClassCSnapshotRestoreResponse:
    from pathlib import Path

    from app.core.host_state import resolve_host_state_layout
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="class-c-snapshot-restore"):  # noqa: E501
        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            server = await server_repo.get(ServerId(server_id))
            if server is None:
                raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
            status = str(getattr(server.status, "value", server.status)).upper()
            if status in {"RUNNING", "STARTING", "STOPPING"}:
                raise HTTPException(  # noqa: B904
                    status_code=409, detail="Server must be stopped before restoring a Class-C snapshot"  # noqa: E501
                )
            root_path = (
                getattr(getattr(server, "deployment", None), "root_path", None)
                or getattr(server, "root_path", None)
            )
            if not root_path and getattr(server, "deployment", None):
                root_path = getattr(server.deployment, "root_path", None)
            if not root_path:
                raise HTTPException(status_code=404, detail="Server root path not configured")  # noqa: B904
            live_dir = Path(root_path).resolve()
        svc = ClassCSnapshotService(layout)
        try:
            svc.restore_snapshot(server_id, snapshot_id, live_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Snapshot not found")  # noqa: B904
        return ClassCSnapshotRestoreResponse(server_id=server_id, snapshot_id=snapshot_id)


@router.delete("/class-c/snapshots/{snapshot_id}", response_model=ClassCSnapshotDeleteResponse)
async def delete_class_c_snapshot(
    server_id: str,
    snapshot_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ClassCSnapshotDeleteResponse:
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="class-c-snapshot-delete"):  # noqa: E501
        svc = ClassCSnapshotService(layout)
        try:
            svc.delete_snapshot(server_id, snapshot_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Snapshot not found")  # noqa: B904
        except Exception as exc:
            if "PINNED" in str(exc).upper():
                raise HTTPException(status_code=409, detail="BACKUP_PINNED")  # noqa: B904
            raise
        return ClassCSnapshotDeleteResponse(server_id=server_id, snapshot_id=snapshot_id)


@router.get("/class-c/dynamic", response_model=list[DynamicClassCEntryResponse])
async def list_dynamic_class_c(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[DynamicClassCEntryResponse]:
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService

    layout = resolve_host_state_layout()
    svc = DynamicClassCService(layout)
    entries = svc.list_entries(server_id)
    return [
        DynamicClassCEntryResponse(
            server_id=server_id,
            relpath=e.relpath,
            promoted_at=e.promoted_at.isoformat()
            if hasattr(e.promoted_at, "isoformat")
            else str(e.promoted_at),
            main_commit_sha=e.main_commit_sha,
            ast_Node_summary=e.ast_node_summary if hasattr(e, "ast_node_summary") else None,
        )
        for e in entries
    ]


@router.post("/class-c/dynamic/reset", response_model=DynamicClassCResetResponse)
async def reset_dynamic_class_c(
    server_id: str,
    body: DynamicClassCResetRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> DynamicClassCResetResponse:
    from app.core.allowlist import validate_canonical_relpath
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService

    try:
        relpath = validate_canonical_relpath(body.path)
    except ValueError as exc:
        from app.core.exceptions import ValidationError

        raise ValidationError(str(exc)) from exc
    layout = resolve_host_state_layout()
    svc = DynamicClassCService(layout)
    removed = svc.reset_to_class_b(server_id, relpath)
    return DynamicClassCResetResponse(server_id=server_id, path=relpath, reset=removed)


@router.get("/secrets", response_model=list[SecretMetadataResponse])
async def list_secrets(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[SecretMetadataResponse]:

    from app.core.persistence.db import database
    from app.modules.versioning.infrastructure.models import ServerSecretModel
    from app.modules.versioning.infrastructure.server_secret_vault import placeholder_for

    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ServerSecretModel).where(ServerSecretModel.server_id == server_id)
                )
            )
            .scalars()
            .all()
        )
    return [
        SecretMetadataResponse(
            server_id=r.server_id,
            key_name=r.key_name,
            placeholder=placeholder_for(r.key_name),
            kek_version=r.kek_version,
            created_at=r.created_at.isoformat()
            if hasattr(r.created_at, "isoformat")
            else str(r.created_at),
            updated_at=r.updated_at.isoformat()
            if hasattr(r.updated_at, "isoformat")
            else str(r.updated_at),
        )
        for r in rows
    ]


@router.post("/secrets/extract", response_model=ExtractSecretResponse)
async def extract_secret(
    server_id: str,
    body: ExtractSecretHttpRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> ExtractSecretResponse:
    from pathlib import Path

    from app.core.allowlist import (
        classify,
        open_safe_path_fd,
        resolve_safe_disk_path,
        validate_canonical_relpath,
    )
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.server_secret_vault import ServerSecretVault

    if body.branch == "main":
        raise HTTPException(status_code=403, detail="Direct writes to 'main' are forbidden")  # noqa: B904
    if "/" in body.branch or ".." in body.branch:
        raise HTTPException(status_code=422, detail="Invalid branch name")  # noqa: B904
    try:
        relpath = validate_canonical_relpath(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc  # noqa: B904
    if classify(relpath) != "B":
        raise HTTPException(  # noqa: B904
            status_code=403, detail="Secrets can only be extracted from Class B config files"
        )

    # ensure branch worktree
    # best-effort: use git context
    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="secrets-extract"):  # noqa: E501
        # find server
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            server = await server_repo.get(ServerId(server_id))
            if server is None:
                raise HTTPException(status_code=404, detail="Server not found")  # noqa: B904
        root_path = (
            getattr(getattr(server, "deployment", None), "root_path", None)
            or getattr(server, "root_path", None)
        )
        if not root_path:
            raise HTTPException(status_code=404, detail="Server root path not configured")  # noqa: B904
        worktree_root = (
            Path(root_path).resolve() / ".onx" / "worktrees" / body.branch
        )

        vault = ServerSecretVault(layout)
        # read file
        import os as _os

        try:
            fd = open_safe_path_fd(str(worktree_root), relpath, flags=_os.O_RDONLY)
        except Exception:
            raise HTTPException(status_code=404, detail="File not found")  # noqa: B904
        import os as _os2

        raw = _os2.read(fd, 10 * 1024 * 1024)
        _os2.close(fd)
        extraction = vault.extract_secret_from_bytes(
            server_id,
            relpath,
            raw,
            secret_value=body.secret_value,
            key_name=body.key_name,
        )
        # write back
        target = resolve_safe_disk_path(str(worktree_root), relpath, allow_create_parents=True)
        from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

        atomic_write_private(target, extraction.content)
        remaining = getattr(extraction, "remaining_findings", []) or []
        return ExtractSecretResponse(
            server_id=server_id,
            branch=body.branch,
            path=relpath,
            key_name=extraction.key_name,
            placeholder=extraction.placeholder,
            replaced_occurrences=extraction.replaced_count,
            remaining_findings=remaining,
        )


@router.delete("/secrets/{key_name}", response_model=DeleteSecretResponse)
async def delete_secret(
    server_id: str,
    key_name: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> DeleteSecretResponse:
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.application.repo_lease import RepoLeaseManager
    from app.modules.versioning.infrastructure.server_secret_vault import ServerSecretVault
    layout = resolve_host_state_layout()
    async with RepoLeaseManager(locks_dir=layout.locks).acquire(server_id, holder="secrets-delete"):  # noqa: E501
        vault = ServerSecretVault(layout)
        deleted = vault.delete_secret(server_id, key_name)
        if not deleted:
            raise HTTPException(status_code=404, detail="Secret not found")  # noqa: B904
        return DeleteSecretResponse(server_id=server_id, key_name=key_name)
