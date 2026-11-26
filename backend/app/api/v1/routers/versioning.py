from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select

from app.api.deps import get_command_bus, get_event_bus, get_query_bus, require_permission
from app.api.errors import check_command_result
from app.api.v1.dependencies.server_mode import require_advanced_mode
from app.api.v1.schemas.versioning import (
    AllocatePortSetRequest,
    AutoCommitLiveChangesRequest,
    AutoCommitLiveChangesResponse,
    BotSettingsRequest,
    BotSettingsResponse,
    BranchConsoleCommandRequest,
    BranchConsoleCommandResponse,
    BranchConsoleLogsResponse,
    BranchPortSetResponse,
    BranchProtectionResponse,
    BranchResponse,
    BranchRuntimeStatusResponse,
    ClassCSnapshotDeleteResponse,
    ClassCSnapshotResponse,
    ClassCSnapshotRestoreResponse,
    CommitResponse,
    ConfirmUpgradeHttpRequest,
    ConfirmUpgradeResponse,
    ConnectGitHubRequest,
    CreateBranchRequest,
    CreateClassCSnapshotRequest,
    CreateCommitRequest,
    CreateDataTemplateRequest,
    CreateMaterializationRequest,
    CreateTagRequest,
    DataTemplateResponse,
    DeleteDataTemplateResponse,
    DeleteSecretResponse,
    DestroyBranchRunRequest,
    DestroyBranchRunResponse,
    DiffResponse,
    DynamicClassCEntryResponse,
    DynamicClassCResetRequest,
    DynamicClassCResetResponse,
    EvidenceBundleResponse,
    ExtractSecretHttpRequest,
    ExtractSecretResponse,
    GenerateGitHubDeployKeyRequest,
    GenerateGitHubDeployKeyResponse,
    GitHubBranchSyncStateResponse,
    GitHubConnectionStatusResponse,
    GitHubDisconnectResponse,
    GitHubPushResponse,
    GitHubSyncResponse,
    GitHubWebhookDeliveryResponse,
    GitHubWebhookIngestResponse,
    ImportReviewActionResponse,
    MaterializationCreateResponse,
    MaterializationFileResponse,
    MaterializationListItemResponse,
    MaterializationTreeResponse,
    MergeCommitsRequest,
    PortSetSchema,
    PreflightResponse,
    PushGitHubBranchRequest,
    RefreshJournalSummaryResponse,
    RefreshServerHttpRequest,
    RefreshServerResponse,
    RefreshStateResponse,
    RollbackRefreshHttpRequest,
    RollbackRefreshResponse,
    RotateGitHubCredentialsRequest,
    RunIsolatedTestRequest,
    SaveBranchDataTemplateRequest,
    ScanLiveChangesRequest,
    ScanLiveChangesResponse,
    SecretMetadataResponse,
    SetBranchProtectionRequest,
    SetEditModeRequest,
    SetEditModeResponse,
    SetPortSetRequest,
    StartBranchRunRequest,
    StartBranchRunResponse,
    StopBranchRunRequest,
    StopBranchRunResponse,
    TagResponse,
    TestDefinitionCreateRequest,
    TestDefinitionResponse,
    TestDefinitionUpdateRequest,
    TestRunResponse,
    WriteMaterializedFileRequest,
    WriteMaterializedFileResponse,
)
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import (
    BranchRuntimeActiveError,
    ConflictError,
    InfrastructureError,
    MaterializationFileTooLargeError,
    NotFoundError,
    ValidationError,
)
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
from app.modules.versioning.application.github_sync_service import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
)
from app.modules.versioning.application.refresh_orchestrator import (
    ConfirmUpgradeCommand,
    RefreshServerCommand,
    ReleaseRefreshPinsCommand,
    RollbackRefreshCommand,
)
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver
from app.modules.versioning.infrastructure.models import ServerDataTemplateModel
from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/servers/{server_id}/versioning",
    tags=["versioning"],
    dependencies=[Depends(require_advanced_mode)],
)

github_webhook_router = APIRouter(
    prefix="/api/v1/webhooks/github",
    tags=["webhooks"],
)

__all__ = [
    "create_github_sync_service",
    "get_branch_runtime_service",
    "get_github_sync_service",
    "github_webhook_router",
    "router",
]

_WEBHOOK_HARD_READ_LIMIT = MAX_WEBHOOK_PAYLOAD_BYTES + 65536

_branch_runtime_service: Any = None
_branch_runtime_service_key: tuple[str, int] | None = None


def get_branch_runtime_service() -> Any:
    """Return a process-level :class:`BranchRuntimeService`.

    The service is cached so in-memory RCON credentials survive across HTTP
    requests.  Tests may override this dependency via
    ``app.dependency_overrides`` or monkeypatch it directly.
    """

    global _branch_runtime_service, _branch_runtime_service_key

    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.branch_runtime_service import (
        BranchRuntimeService,
    )

    layout = resolve_host_state_layout()
    session_factory = database.session_factory
    key = (str(layout.root), id(session_factory))
    if _branch_runtime_service is None or _branch_runtime_service_key != key:
        _branch_runtime_service = BranchRuntimeService(
            layout,
            session_factory=session_factory,
        )
        _branch_runtime_service_key = key
    return _branch_runtime_service


# --- P5-3 GitHub sync DI & helpers ------------------------------------------


def create_github_sync_service(
    event_bus: EventBus,
    *,
    git_runner_factory: Any = None,
    kek: Any = None,
) -> Any:
    """Build a GitHubSyncService wired to the shared OperationExecutor.

    The webhook_sync_dispatcher schedules ``run_queued_sync_operation`` via
    ``asyncio.create_task`` and registers the task on
    ``op_service.executor.register_task(operation_id, task)`` so:
      1. Webhook ingestion and redelivery return 202 immediately without
         blocking on Git network I/O (D-J).
      2. A strong reference is held until task completion, preventing GC.
      3. Lifespan shutdown in ``main.py`` cleanly cancels/drains in-flight
         tasks via ``get_operation_service().executor.shutdown(...)``.
    """
    from app.core.host_state import resolve_host_state_layout
    from app.modules.operations.application.services.operation_service import (
        get_operation_service,
    )
    from app.modules.versioning.application.github_sync_service import (
        GitHubSyncService,
    )

    layout = resolve_host_state_layout()
    op_service = get_operation_service(event_bus)
    service_ref: list[Any] = []

    def _dispatch_webhook_sync(
        server_id: str, operation_id: str, delivery_id: str
    ) -> None:
        svc = service_ref[0]

        async def _run() -> None:
            try:
                await svc.run_queued_sync_operation(
                    server_id,
                    operation_id,
                    delivery_id=delivery_id,
                    trigger="webhook",
                )
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await op_service.confirm_cancellation(operation_id)
                raise
            except Exception:
                # run_queued_sync_operation already recorded redacted failure
                # details on both OperationModel and GitHubWebhookDeliveryModel.
                logger.warning(
                    "Queued GitHub webhook sync failed: server=%s operation=%s delivery=%s",
                    server_id,
                    operation_id,
                    delivery_id,
                )

        task = asyncio.create_task(
            _run(),
            name=f"github-webhook-sync:{server_id}:{operation_id}",
        )
        with contextlib.suppress(Exception):
            op_service.executor.register_task(operation_id, task)
            op_service.executor.schedule_timeout_watch(operation_id, 600)

    service = GitHubSyncService(
        layout,
        session_factory=database.session_factory,
        operation_service=op_service,
        event_bus=event_bus,
        git_runner_factory=git_runner_factory,
        webhook_sync_dispatcher=_dispatch_webhook_sync,
        kek=kek,
    )
    service_ref.append(service)
    return service


def get_github_sync_service(
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> Any:
    """FastAPI dependency returning a configured GitHubSyncService.

    Tests may override this dependency via ``app.dependency_overrides``.
    """
    return create_github_sync_service(event_bus)


def _actor_id_from_user(current_user: dict[str, Any]) -> str | None:
    raw = current_user.get("user_id") or current_user.get("sub") or current_user.get("id")
    return str(raw) if raw else None


def _github_branch_states(branches: Any) -> list[GitHubBranchSyncStateResponse]:
    states: list[GitHubBranchSyncStateResponse] = []
    for branch in branches or ():
        if hasattr(branch, "to_dict"):
            data = branch.to_dict()
        elif isinstance(branch, dict):
            data = branch
        else:
            data = {
                "branch": branch.branch,
                "status": branch.status,
                "local_sha": branch.local_sha,
                "remote_sha": branch.remote_sha,
                "ahead_count": branch.ahead_count,
                "behind_count": branch.behind_count,
            }
        states.append(GitHubBranchSyncStateResponse(**data))
    return states


def _github_status_response(status: Any) -> GitHubConnectionStatusResponse:
    return GitHubConnectionStatusResponse(
        server_id=status.server_id,
        connected=status.connected,
        remote_url=status.remote_url,
        auth_method=status.auth_method,
        credential_hint=status.credential_hint,
        deploy_public_key=status.deploy_public_key,
        webhook_enabled=status.webhook_enabled,
        webhook_path=(
            f"/api/v1/webhooks/github/{status.server_id}" if status.connected else None
        ),
        sync_status=status.sync_status,
        needs_reauth=status.needs_reauth,
        last_error_code=status.last_error_code,
        last_error_message=status.last_error_message,
        last_fetch_at=status.last_fetch_at,
        last_push_at=status.last_push_at,
        remote_default_branch=status.remote_default_branch,
        remote_head_sha=status.remote_head_sha,
        branches=_github_branch_states(status.branches),
        created_at=status.created_at,
        updated_at=status.updated_at,
        generated_webhook_secret=status.generated_webhook_secret,
    )


def _github_ingest_response(result: Any) -> GitHubWebhookIngestResponse:
    return GitHubWebhookIngestResponse(
        server_id=result.server_id,
        delivery_id=result.delivery_id,
        event_type=result.event_type,
        status=result.status,
        deduplicated=result.deduplicated,
        redelivered=result.redelivered,
        redelivery_count=result.redelivery_count,
        operation_id=result.operation_id,
        received_at=result.received_at,
    )


def _github_delivery_response(record: Any) -> GitHubWebhookDeliveryResponse:
    return GitHubWebhookDeliveryResponse(
        id=record.id,
        server_id=record.server_id,
        delivery_id=record.delivery_id,
        event_type=record.event_type,
        ref=record.ref,
        before_sha=record.before_sha,
        after_sha=record.after_sha,
        payload_sha256=record.payload_sha256,
        signature_valid=record.signature_valid,
        status=record.status,
        operation_id=record.operation_id,
        error_message=record.error_message,
        redelivery_count=record.redelivery_count,
        received_at=record.received_at,
        processed_at=record.processed_at,
    )


async def _read_bounded_webhook_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > _WEBHOOK_HARD_READ_LIMIT:
            raise ValidationError(
                "GitHub webhook payload exceeds the 2 MiB limit",
                field="raw_body",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# --- P4-3 helpers -----------------------------------------------------------


def _as_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _data_template_response(row: Any) -> DataTemplateResponse:
    return DataTemplateResponse(
        id=row.id,
        server_id=row.server_id,
        name=row.name,
        description=row.description or "",
        source_branch_name=row.source_branch_name,
        source_commit_sha=row.source_commit_sha,
        file_count=row.file_count or 0,
        total_bytes=row.total_bytes or 0,
        status=row.status or "ready",
        operation_id=row.operation_id,
        created_at=_as_iso(row.created_at),
        updated_at=_as_iso(row.updated_at),
    )


def _port_set_schema(port_set: Any) -> PortSetSchema:
    if port_set is None:
        raise InfrastructureError("Port set unavailable for branch runtime")
    data = port_set.to_dict() if hasattr(port_set, "to_dict") else dict(port_set)
    return PortSetSchema(**data)


async def _load_server(session: Any, server_id: str) -> ServerModel:
    server = await session.get(ServerModel, server_id)
    if server is None:
        raise NotFoundError(f"Server '{server_id}' not found")
    return server


def _server_container_name(server: ServerModel, server_id: str) -> str:
    from app.core.identity import IDENTITY

    return str(
        getattr(server, "external_id", None) or f"{IDENTITY.temp_prefix_new}{server_id}"
    )


def _read_server_properties(server_root: Path) -> dict[str, str]:
    path = server_root / "server.properties"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    props: dict[str, str] = {}
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


class _LiveContainerStateAdapter:
    def __init__(
        self,
        docker_runner: Any,
        container_name: str,
        fallback_running: bool,
    ) -> None:
        self._runner = docker_runner
        self._container_name = container_name
        self._fallback_running = fallback_running

    def is_running(self) -> Any:
        async def _check() -> bool:
            if self._runner is None:
                return self._fallback_running
            try:
                rc, out = await self._runner(
                    ["inspect", "-f", "{{.State.Running}}", self._container_name]
                )
                if rc == 0 and str(out).strip():
                    return str(out).strip().lower() == "true"
            except Exception:
                pass
            return self._fallback_running

        return _check()


class _LiveRconQuiesceAdapter:
    def __init__(self, host: str, port: int, password: str, client_factory: Any) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._factory = client_factory

    async def _client(self) -> Any:
        factory = self._factory
        if factory is None:
            from app.modules.monitoring.infrastructure.rcon_client import AsyncRCONClient

            factory = AsyncRCONClient
        client = factory(self._host, self._port, self._password)
        await client.connect()
        return client

    async def save_off(self) -> Any:
        client = await self._client()
        try:
            return await client.send_command("save-off")
        finally:
            await client.close()

    async def save_all_flush(self, timeout: float = 30.0) -> str:  # noqa: ARG002
        client = await self._client()
        try:
            return await client.send_command("save-all flush")
        finally:
            await client.close()

    async def save_on(self) -> Any:
        client = await self._client()
        try:
            return await client.send_command("save-on")
        finally:
            await client.close()


class _LiveSaveOffStore:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def set_save_off_active(self, server_id: str, active: bool) -> None:
        from sqlalchemy import update

        async with self._session_factory() as session:
            await session.execute(
                update(ServerModel)
                .where(ServerModel.id == server_id)
                .values(rcon_save_off_active=bool(active))
            )
            await session.commit()


async def _execute_live_data_template_clone(
    *,
    server_id: str,
    server_root: Path,
    server: ServerModel,
    template_id: str,
    name: str,
    description: str,
    operation_id: str,
    runtime_service: Any,
) -> tuple[str, int, int, str | None]:
    from app.core.host_state import resolve_host_state_layout
    from app.modules.server.infrastructure.providers.docker import _read_persisted_rcon_port
    from app.modules.versioning.infrastructure.data_templates import DataTemplateService

    props = _read_server_properties(server_root)
    rcon_port = _read_persisted_rcon_port(server_root) or int(props.get("rcon.port", "25575") or 25575)
    rcon_password = props.get("rcon.password", "")
    container_name = _server_container_name(server, server_id)
    status_text = str(getattr(server.status, "value", server.status)).upper()
    fallback_running = status_text in ("RUNNING", "STARTING")
    state_adapter = _LiveContainerStateAdapter(
        getattr(runtime_service, "docker_runner", None),
        container_name,
        fallback_running,
    )
    rcon_adapter = _LiveRconQuiesceAdapter(
        "127.0.0.1",
        rcon_port,
        rcon_password,
        getattr(runtime_service, "rcon_client_factory", None),
    )
    service = DataTemplateService(resolve_host_state_layout())
    async with database.session_factory() as session:
        storage_path = await service.clone(
            server_id,
            server_root,
            template_id,
            source_branch_name=None,
            rcon=rcon_adapter,
            container_state=state_adapter,
            save_off_store=_LiveSaveOffStore(database.session_factory),
            db_session=session,
        )
        row = await session.get(ServerDataTemplateModel, template_id)
        if row is not None:
            row.name = name
            row.description = description
            row.status = "ready"
            row.operation_id = operation_id
            row.storage_path = str(storage_path)
            row.source_branch_name = None
            row.updated_at = datetime.now(UTC)
        await session.commit()
    file_count = 0
    total_bytes = 0
    marker = Path(storage_path) / ".onx-complete.json"
    if marker.is_file():
        with contextlib.suppress(Exception):
            payload = json.loads(marker.read_text(encoding="utf-8"))
            file_count = int(payload.get("file_count") or 0)
            total_bytes = int(payload.get("total_bytes") or 0)
    return str(storage_path), file_count, total_bytes, None


async def _execute_data_template_clone(
    *,
    server_id: str,
    server: ServerModel,
    template_id: str,
    name: str,
    description: str,
    source: str,
    branch_name: str | None,
    operation_id: str,
    event_bus: EventBus,
    runtime_service: Any,
) -> None:
    from app.modules.operations.application.services.operation_service import (
        get_operation_service,
    )
    from app.modules.versioning.domain.events import DataTemplateSavedEvent

    op_service = get_operation_service(event_bus)
    try:
        await op_service.start_step(operation_id, "CLONE")
        if source == "branch":
            if not branch_name:
                raise ValidationError(
                    "branch_name is required when source is 'branch'",
                    field="branch_name",
                )
            saved = await runtime_service.save_data_template(
                server_id,
                branch_name,
                name=name,
                description=description,
                template_id=template_id,
            )
            storage_path = str(saved.storage_path)
            file_count = int(saved.file_count or 0)
            total_bytes = int(saved.total_bytes or 0)
            source_commit_sha = saved.source_commit_sha
            async with database.session_factory() as session:
                row = await session.get(ServerDataTemplateModel, template_id)
                if row is not None:
                    row.name = name
                    row.description = description
                    row.status = "ready"
                    row.operation_id = operation_id
                    row.storage_path = storage_path
                    row.source_branch_name = branch_name
                    row.source_commit_sha = source_commit_sha
                    row.updated_at = datetime.now(UTC)
                await session.commit()
        else:
            import os as _os_path

            root = Path(_os_path.path.abspath(server.root_path))
            storage_path, file_count, total_bytes, source_commit_sha = (
                await _execute_live_data_template_clone(
                    server_id=server_id,
                    server_root=root,
                    server=server,
                    template_id=template_id,
                    name=name,
                    description=description,
                    operation_id=operation_id,
                    runtime_service=runtime_service,
                )
            )

        await op_service.complete_operation(operation_id)
        await event_bus.publish(
            DataTemplateSavedEvent(
                server_id=server_id,
                branch_name=branch_name,
                template_id=template_id,
                template_name=name,
                commit_sha=source_commit_sha,
                actor_type="user",
            )
        )
    except BaseException as exc:
        with contextlib.suppress(Exception):
            async with database.session_factory() as session:
                row = await session.get(ServerDataTemplateModel, template_id)
                if row is not None:
                    row.status = "failed"
                    row.updated_at = datetime.now(UTC)
                await session.commit()
        with contextlib.suppress(Exception):
            await op_service.fail_operation(
                operation_id,
                getattr(exc, "code", "HOT_CLONE_REFUSED"),
                str(exc),
            )
        raise


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
    if not headroom.passed:
        error_msg = headroom.message

    return PreflightResponse(
        reflink_supported=reflink_ok,
        available_ram_mb=headroom.available_ram_mb,
        available_cores=headroom.available_cores,
        min_required_ram_mb=headroom.required_ram_mb,
        min_required_cores=headroom.required_cores,
        passed=headroom.passed,
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


# --- P4-3 Batch B: data templates, port sets, branch runtime, console ---


@router.get("/data-templates", response_model=list[DataTemplateResponse])
async def list_data_templates(
    server_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> list[DataTemplateResponse]:
    from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ServerDataTemplateModel)
                    .where(ServerDataTemplateModel.server_id == server_id)
                    .order_by(ServerDataTemplateModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return [_data_template_response(row) for row in rows]


@router.post("/data-templates", response_model=DataTemplateResponse, status_code=201)
async def create_data_template(
    server_id: str,
    body: CreateDataTemplateRequest,
    response: Response,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> DataTemplateResponse:
    from app.modules.operations.application.services.operation_service import (
        get_operation_service,
    )
    from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

    if body.source == "branch" and not body.branch_name:
        raise ValidationError(
            "branch_name is required when source is 'branch'",
            field="branch_name",
        )

    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        if not server.root_path:
            raise NotFoundError("Server root path not configured")
        existing = (
            (
                await session.execute(
                    select(ServerDataTemplateModel).where(
                        ServerDataTemplateModel.server_id == server_id,
                        ServerDataTemplateModel.name == body.name,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise ConflictError(f"Data template '{body.name}' already exists")
        from app.core.host_state import resolve_host_state_layout

        layout = resolve_host_state_layout()
        template_id = uuid.uuid4().hex
        actor_id = _current_user.get("user_id") or _current_user.get("id")
        op = await get_operation_service(event_bus).create_operation(
            type="CREATE_DATA_TEMPLATE",
            target_type="server",
            target_id=server_id,
            actor_id=str(actor_id) if actor_id else None,
            metadata={
                "template_id": template_id,
                "name": body.name,
                "source": body.source,
                "branch_name": body.branch_name,
            },
            initial_steps=[
                {
                    "step_id": "CLONE",
                    "sequence": 1,
                    "message_key": "operations.steps.clone",
                }
            ],
        )
        row = ServerDataTemplateModel(
            id=template_id,
            server_id=server_id,
            name=body.name,
            description=body.description,
            source_branch_name=body.branch_name,
            storage_path=str(layout.data_templates_dir(server_id) / template_id),
            status="cloning",
            operation_id=op.id,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        response_payload = _data_template_response(row)

    if body.async_mode:

        async def _background() -> None:
            with contextlib.suppress(BaseException):
                await _execute_data_template_clone(
                    server_id=server_id,
                    server=server,
                    template_id=template_id,
                    name=body.name,
                    description=body.description,
                    source=body.source,
                    branch_name=body.branch_name,
                    operation_id=op.id,
                    event_bus=event_bus,
                    runtime_service=runtime_service,
                )

        task = asyncio.create_task(_background())
        with contextlib.suppress(Exception):
            get_operation_service(event_bus).executor.register_task(op.id, task)
        response.status_code = 202
        return response_payload

    await _execute_data_template_clone(
        server_id=server_id,
        server=server,
        template_id=template_id,
        name=body.name,
        description=body.description,
        source=body.source,
        branch_name=body.branch_name,
        operation_id=op.id,
        event_bus=event_bus,
        runtime_service=runtime_service,
    )
    async with database.session_factory() as session:
        row = await session.get(ServerDataTemplateModel, template_id)
        if row is None:
            raise InfrastructureError("Data template row disappeared during clone")
        response.status_code = 201
        return _data_template_response(row)


@router.delete("/data-templates/{template_id}", response_model=DeleteDataTemplateResponse)
async def delete_data_template(
    server_id: str,
    template_id: str,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> DeleteDataTemplateResponse:
    from app.core.host_state import check_not_symlink_or_reparse, resolve_host_state_layout
    from app.modules.versioning.infrastructure.models import (
        ServerDataTemplateModel,
        ServerRuntimeModel,
    )

    layout = resolve_host_state_layout()
    async with database.session_factory() as session:
        row = await session.get(ServerDataTemplateModel, template_id)
        if row is None or row.server_id != server_id:
            raise NotFoundError(f"Data template '{template_id}' not found")
        active = (
            (
                await session.execute(
                    select(ServerRuntimeModel).where(
                        ServerRuntimeModel.server_id == server_id,
                        ServerRuntimeModel.data_template_id == template_id,
                        ServerRuntimeModel.status.in_(("starting", "running")),
                    )
                )
            )
            .scalars()
            .first()
        )
        if active is not None:
            raise ConflictError("Data template is currently in use by an active runtime")

        candidate = Path(row.storage_path)
        allowed_root = layout.data_templates_dir(server_id)
        check_not_symlink_or_reparse(candidate)
        try:
            allowed_real = os.path.realpath(allowed_root)
            candidate_real = os.path.realpath(candidate)
            if (
                os.path.commonpath([allowed_real, candidate_real]) != allowed_real
                or candidate_real == allowed_real
            ):
                raise ValidationError(
                    "Data template storage path outside server template directory",
                    field="storage_path",
                )
        except ValueError as exc:
            raise ValidationError(
                "Data template storage path outside server template directory",
                field="storage_path",
            ) from exc
        if candidate.exists():
            if candidate.is_dir() and not candidate.is_symlink():
                shutil.rmtree(candidate)
            else:
                candidate.unlink(missing_ok=True)
        await session.delete(row)
        await session.commit()
    return DeleteDataTemplateResponse(server_id=server_id, template_id=template_id)


async def _resolve_branch_row(
    session: Any,
    server_id: str,
    name: str,
    *,
    server_root: str | None,
) -> Any:
    from app.modules.versioning.infrastructure.models import ServerBranchModel

    branch_row = (
        (
            await session.execute(
                select(ServerBranchModel).where(
                    ServerBranchModel.server_id == server_id,
                    ServerBranchModel.name == name,
                )
            )
        )
        .scalars()
        .first()
    )
    if branch_row is not None:
        return branch_row
    if not server_root:
        return None
    from app.core.host_state import resolve_host_state_layout
    from app.modules.versioning.infrastructure.git_branches import GitBranchService

    try:
        info = GitBranchService(resolve_host_state_layout()).get_branch(
            server_id, server_root, name
        )
    except Exception:
        info = None
    if info is None:
        return None
    branch_row = ServerBranchModel(
        id=uuid.uuid4().hex,
        server_id=server_id,
        name=name,
        head_commit_id=getattr(info, "sha", None),
    )
    session.add(branch_row)
    await session.commit()
    await session.refresh(branch_row)
    return branch_row


async def _assert_branch_not_running(
    session: Any, server_id: str, name: str, branch_row: Any
) -> None:
    from app.modules.versioning.infrastructure.models import ServerRuntimeModel

    if getattr(branch_row, "runtime_status", None) in ("starting", "running"):
        raise BranchRuntimeActiveError(
            "Cannot reallocate port set while branch runtime is active"
        )
    active = (
        (
            await session.execute(
                select(ServerRuntimeModel).where(
                    ServerRuntimeModel.server_id == server_id,
                    ServerRuntimeModel.branch_name == name,
                    ServerRuntimeModel.status.in_(("starting", "running")),
                )
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        raise BranchRuntimeActiveError(
            "Cannot reallocate port set while branch runtime is active"
        )


@router.post(
    "/branches/{name}/port-set/allocate",
    response_model=BranchPortSetResponse,
)
async def allocate_branch_port_set(
    server_id: str,
    name: str,
    body: AllocatePortSetRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> BranchPortSetResponse:
    from app.modules.versioning.domain.port_sets import HostPortSet
    from app.modules.versioning.infrastructure.port_allocator import (
        allocate_port_set,
        release_port_set,
    )

    if name == "main":
        raise ValidationError(
            "Cannot assign branch port set to 'main'", field="branch_name"
        )
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        branch_row = await _resolve_branch_row(
            session, server_id, name, server_root=server.root_path
        )
        if branch_row is None:
            raise NotFoundError(f"Branch '{name}' not found")
        await _assert_branch_not_running(session, server_id, name, branch_row)

        previous = getattr(branch_row, "port_set_json", None)
        port_set = await allocate_port_set(
            session,
            include_query=body.include_query,
            plugin_port_names=tuple(body.plugin_port_names),
            check_os_ports=body.check_os_ports,
        )
        branch_row.port_set_json = port_set.to_dict()
        await session.commit()
        if previous:
            with contextlib.suppress(Exception):
                release_port_set(HostPortSet.from_dict(previous))
    return BranchPortSetResponse(
        server_id=server_id,
        branch_name=name,
        port_set=PortSetSchema(**port_set.to_dict()),
    )


@router.put("/branches/{name}/port-set", response_model=BranchPortSetResponse)
async def set_branch_port_set(
    server_id: str,
    name: str,
    body: SetPortSetRequest,
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> BranchPortSetResponse:
    from app.modules.versioning.domain.port_sets import HostPortSet
    from app.modules.versioning.infrastructure.port_allocator import (
        validate_port_set_atomic,
    )

    if name == "main":
        raise ValidationError(
            "Cannot assign branch port set to 'main'", field="branch_name"
        )
    candidate = HostPortSet(
        game_port=body.game_port,
        rcon_port=body.rcon_port,
        query_port=body.query_port,
        plugin_ports=dict(body.plugin_ports),
    )
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        branch_row = await _resolve_branch_row(
            session, server_id, name, server_root=server.root_path
        )
        if branch_row is None:
            raise NotFoundError(f"Branch '{name}' not found")
        await _assert_branch_not_running(session, server_id, name, branch_row)
        await validate_port_set_atomic(
            session,
            candidate,
            exclude_branch_id=branch_row.id,
            check_os_ports=body.check_os_ports,
        )
        branch_row.port_set_json = candidate.to_dict()
        await session.commit()
    return BranchPortSetResponse(
        server_id=server_id,
        branch_name=name,
        port_set=PortSetSchema(**candidate.to_dict()),
    )


@router.get("/branches/{name}/runtime", response_model=BranchRuntimeStatusResponse)
async def get_branch_runtime(
    server_id: str,
    name: str,
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> BranchRuntimeStatusResponse:
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        server_root = server.root_path
    status = await runtime_service.get_branch_runtime_status(
        server_id, name, server_root=server_root
    )
    port_set = status.get("port_set")
    return BranchRuntimeStatusResponse(
        server_id=server_id,
        branch_name=name,
        runtime_status=status.get("runtime_status") or "stopped",
        container_provisioned=bool(status.get("container_provisioned", False)),
        container_name=status.get("container_name"),
        runtime_id=status.get("runtime_id"),
        active_commit_sha=status.get("active_commit_sha"),
        data_template_id=status.get("data_template_id"),
        allow_public_test_join=bool(status.get("allow_public_test_join", False)),
        container_liveness=status.get("container_liveness"),
        port_set=PortSetSchema(**port_set) if port_set else None,
        worktree_locked=bool(status.get("worktree_locked")),
        worktree_lock_reason=status.get("worktree_lock_reason"),
    )


@router.post(
    "/branches/{name}/run",
    response_model=StartBranchRunResponse,
    status_code=201,
)
async def start_branch_run(
    server_id: str,
    name: str,
    body: StartBranchRunRequest | None,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> StartBranchRunResponse:
    from app.modules.versioning.domain.events import BranchRuntimeStartedEvent
    from app.modules.versioning.domain.port_sets import HostPortSet
    from app.modules.versioning.infrastructure.branch_runtime_service import (
        BranchStartRequest,
    )
    from app.modules.versioning.infrastructure.models import ServerBranchModel

    req_body = body or StartBranchRunRequest()
    if name == "main":
        raise ValidationError(
            "Branch runtime engine only launches non-main branches",
            field="branch_name",
        )
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        if not server.root_path:
            raise NotFoundError("Server root path not configured")
        branch_row = (
            (
                await session.execute(
                    select(ServerBranchModel).where(
                        ServerBranchModel.server_id == server_id,
                        ServerBranchModel.name == name,
                    )
                )
            )
            .scalars()
            .first()
        )
        saved_port_set = getattr(branch_row, "port_set_json", None)

    if req_body.port_set is not None:
        port_set = HostPortSet.from_dict(req_body.port_set.model_dump())
    elif saved_port_set:
        port_set = HostPortSet.from_dict(saved_port_set)
    else:
        port_set = None

    from app.core.host_state import resolve_host_state_layout
    from app.modules.server.application.branch_settings import load_branch_runtime_overrides
    from app.modules.versioning.infrastructure.git_branches import GitBranchService

    rt_overrides: dict[str, Any] = {}
    if server.root_path:
        with contextlib.suppress(Exception):
            git_br = GitBranchService(resolve_host_state_layout()).get_branch(
                server_id, Path(server.root_path), name
            )
            if git_br is not None and git_br.worktree_path and git_br.worktree_path.is_dir():
                rt_overrides = load_branch_runtime_overrides(git_br.worktree_path)

    eff_max_mem = (
        req_body.requested_memory_mb
        if req_body.requested_memory_mb is not None
        else rt_overrides.get("max_memory_mb", server.memory_max_mb)
    )
    eff_min_mem = rt_overrides.get("min_memory_mb", server.memory_min_mb)
    eff_cpu_cores = (
        req_body.requested_cpu_cores
        if req_body.requested_cpu_cores is not None
        else rt_overrides.get("cpu_cores", server.cpu_cores or None)
    )
    eff_cpu_affinity = (
        str(rt_overrides["cpu_affinity"])
        if "cpu_affinity" in rt_overrides
        else (server.cpu_affinity or "")
    )
    eff_jvm_args = (
        str(rt_overrides["java_args"])
        if "java_args" in rt_overrides
        else (server.java_args or "")
    )

    request = BranchStartRequest(
        server_id=server_id,
        server_root=server.root_path,
        branch_name=name,
        server_type=server.server_type,
        minecraft_version=server.minecraft_version,
        server_provider=server.provider,
        server_mode=server.mode,
        commit_sha=req_body.commit_sha,
        data_template_id=req_body.data_template_id,
        allow_public_test_join=req_body.allow_public_test_join,
        port_set=port_set,
        include_query=req_body.include_query,
        plugin_port_names=tuple(req_body.plugin_port_names),
        requested_memory_mb=eff_max_mem,
        requested_memory_min_mb=eff_min_mem,
        requested_cpu_cores=eff_cpu_cores,
        cpu_affinity=eff_cpu_affinity,
        max_concurrent_branch_runs=server.max_concurrent_branch_runs,
        jvm_args=eff_jvm_args,
        startup_jar=server.startup_jar or "server.jar",
        check_os_ports=req_body.check_os_ports,
    )
    result = await runtime_service.start_branch_runtime(request)
    actor_id = _current_user.get("user_id") or _current_user.get("id")
    await event_bus.publish(
        BranchRuntimeStartedEvent(
            server_id=server_id,
            branch_name=name,
            runtime_id=result.runtime_id,
            commit_sha=result.commit_sha,
            data_template_id=result.data_template_id,
            allow_public_test_join=result.allow_public_test_join,
            actor_type="user",
            actor_id=str(actor_id) if actor_id else None,
        )
    )
    return StartBranchRunResponse(
        runtime_id=result.runtime_id,
        server_id=server_id,
        branch_name=name,
        commit_sha=result.commit_sha,
        container_name=result.container_name,
        container_id=result.container_id,
        port_set=_port_set_schema(result.port_set),
        data_template_id=result.data_template_id,
        allow_public_test_join=result.allow_public_test_join,
        uncommitted_changes_warning=result.uncommitted_changes_warning,
        memory_max_mb=result.memory_max_mb,
        cpu_cores=result.cpu_cores,
    )


@router.post("/branches/{name}/stop", response_model=StopBranchRunResponse)
async def stop_branch_run(
    server_id: str,
    name: str,
    body: StopBranchRunRequest | None,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> StopBranchRunResponse:
    from app.modules.versioning.domain.events import (
        BranchRuntimeStoppedEvent,
        DataTemplateSavedEvent,
    )

    req_body = body or StopBranchRunRequest()
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        if not server.root_path:
            raise NotFoundError("Server root path not configured")
    result = await runtime_service.stop_branch_runtime(
        server_id,
        server.root_path,
        name,
        runtime_id=req_body.runtime_id,
        timeout_seconds=req_body.timeout_seconds,
        keep_port_assignment=req_body.keep_port_assignment,
        save_template_name=req_body.save_template_name,
        save_template_description=req_body.save_template_description,
    )
    actor_id = _current_user.get("user_id") or _current_user.get("id")
    saved_template_id = getattr(result.saved_template, "template_id", None)
    await event_bus.publish(
        BranchRuntimeStoppedEvent(
            server_id=server_id,
            branch_name=name,
            runtime_id=result.runtime_id,
            exit_code=result.exit_code,
            oom_killed=result.oom_killed,
            saved_template_id=saved_template_id,
            actor_type="user",
            actor_id=str(actor_id) if actor_id else None,
        )
    )
    if result.saved_template is not None:
        await event_bus.publish(
            DataTemplateSavedEvent(
                server_id=server_id,
                branch_name=name,
                template_id=result.saved_template.template_id,
                template_name=result.saved_template.name,
                commit_sha=result.saved_template.source_commit_sha,
                actor_type="user",
                actor_id=str(actor_id) if actor_id else None,
            )
        )
    return StopBranchRunResponse(
        runtime_id=result.runtime_id,
        server_id=server_id,
        branch_name=name,
        status="stopped",
        exit_code=result.exit_code,
        oom_killed=result.oom_killed,
        saved_template_id=saved_template_id,
        saved_template_name=(
            result.saved_template.name if result.saved_template is not None else None
        ),
    )


@router.post("/branches/{name}/destroy", response_model=DestroyBranchRunResponse)
async def destroy_branch_run(
    server_id: str,
    name: str,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
    body: DestroyBranchRunRequest | None = None,
) -> DestroyBranchRunResponse:
    from app.modules.versioning.domain.events import BranchRuntimeDestroyedEvent

    req_body = body or DestroyBranchRunRequest()
    if name == "main":
        raise ValidationError(
            "Branch runtime engine only manages non-main branches",
            field="branch_name",
        )
    async with database.session_factory() as session:
        server = await _load_server(session, server_id)
        if not server.root_path:
            raise NotFoundError("Server root path not configured")
    result = await runtime_service.destroy_branch_runtime(
        server_id,
        server.root_path,
        name,
        runtime_id=req_body.runtime_id,
        timeout_seconds=req_body.timeout_seconds,
        keep_port_assignment=req_body.keep_port_assignment,
    )
    actor_id = _current_user.get("user_id") or _current_user.get("id")
    await event_bus.publish(
        BranchRuntimeDestroyedEvent(
            server_id=server_id,
            branch_name=name,
            runtime_id=result.runtime_id,
            actor_type="user",
            actor_id=str(actor_id) if actor_id else None,
        )
    )
    return DestroyBranchRunResponse(
        runtime_id=result.runtime_id,
        server_id=server_id,
        branch_name=name,
        container_name=result.container_name,
        status="destroyed",
        container_provisioned=False,
        released_ports=result.released_ports,
    )


@router.post(
    "/branches/{name}/save-data-template",
    response_model=DataTemplateResponse,
    status_code=201,
)
async def save_branch_data_template(
    server_id: str,
    name: str,
    body: SaveBranchDataTemplateRequest,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> DataTemplateResponse:
    from app.modules.versioning.domain.events import DataTemplateSavedEvent
    from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

    async with database.session_factory() as session:
        existing = (
            (
                await session.execute(
                    select(ServerDataTemplateModel).where(
                        ServerDataTemplateModel.server_id == server_id,
                        ServerDataTemplateModel.name == body.name,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise ConflictError(f"Data template '{body.name}' already exists")

    saved = await runtime_service.save_data_template(
        server_id,
        name,
        name=body.name,
        description=body.description,
        runtime_id=body.runtime_id,
    )
    async with database.session_factory() as session:
        row = await session.get(ServerDataTemplateModel, saved.template_id)
        if row is None:
            raise InfrastructureError("Data template row missing after save")
        payload = _data_template_response(row)
    actor_id = _current_user.get("user_id") or _current_user.get("id")
    await event_bus.publish(
        DataTemplateSavedEvent(
            server_id=server_id,
            branch_name=name,
            template_id=saved.template_id,
            template_name=saved.name,
            commit_sha=saved.source_commit_sha,
            actor_type="user",
            actor_id=str(actor_id) if actor_id else None,
        )
    )
    return payload


@router.get("/branches/{name}/console", response_model=BranchConsoleLogsResponse)
async def get_branch_console(
    server_id: str,
    name: str,
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    tail: int = Query(default=200, ge=1, le=5000),
) -> BranchConsoleLogsResponse:
    payload = await runtime_service.get_branch_console_logs(
        server_id, name, tail=tail
    )
    return BranchConsoleLogsResponse(**payload)


@router.post(
    "/branches/{name}/console/command",
    response_model=BranchConsoleCommandResponse,
)
async def send_branch_console_command(
    server_id: str,
    name: str,
    body: BranchConsoleCommandRequest,
    runtime_service: Annotated[Any, Depends(get_branch_runtime_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> BranchConsoleCommandResponse:
    payload = await runtime_service.send_branch_console_command(
        server_id, name, body.command
    )
    return BranchConsoleCommandResponse(**payload)


# --- P5-3 GitHub sync authenticated routes -----------------------------------


@router.get("/github", response_model=GitHubConnectionStatusResponse)
async def get_github_connection_status(
    server_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
) -> GitHubConnectionStatusResponse:
    return _github_status_response(await service.get_status(server_id))


@router.post(
    "/github/deploy-key/generate",
    response_model=GenerateGitHubDeployKeyResponse,
    status_code=201,
)
async def generate_github_deploy_key(
    server_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
    body: GenerateGitHubDeployKeyRequest | None = None,
) -> GenerateGitHubDeployKeyResponse:
    result = await service.generate_deploy_key(
        server_id, comment=(body.comment if body else None)
    )
    return GenerateGitHubDeployKeyResponse(
        server_id=result.server_id,
        public_key_openssh=result.public_key_openssh,
        private_key_pem=result.private_key_pem,
        fingerprint_sha256=result.fingerprint_sha256,
    )


@router.post(
    "/github/connect",
    response_model=GitHubConnectionStatusResponse,
    status_code=201,
)
async def connect_github(
    server_id: str,
    body: ConnectGitHubRequest,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> GitHubConnectionStatusResponse:
    status = await service.connect(
        server_id,
        remote_url=body.remote_url,
        auth_method=body.auth_method,
        credential_secret=body.credential_secret,
        deploy_public_key=body.deploy_public_key,
        webhook_secret=body.webhook_secret,
        enable_webhook=body.enable_webhook,
        actor_id=_actor_id_from_user(_current_user),
    )
    return _github_status_response(status)


@router.post(
    "/github/credentials/rotate",
    response_model=GitHubConnectionStatusResponse,
)
async def rotate_github_credentials(
    server_id: str,
    body: RotateGitHubCredentialsRequest,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> GitHubConnectionStatusResponse:
    status = await service.rotate_credentials(
        server_id,
        credential_secret=body.credential_secret,
        auth_method=body.auth_method,
        deploy_public_key=body.deploy_public_key,
        webhook_secret=body.webhook_secret,
        enable_webhook=body.enable_webhook,
        regenerate_webhook_secret=body.regenerate_webhook_secret,
        disable_webhook=body.disable_webhook,
        actor_id=_actor_id_from_user(_current_user),
    )
    return _github_status_response(status)


@router.delete("/github", response_model=GitHubDisconnectResponse)
async def disconnect_github(
    server_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
    purge_deliveries: bool = Query(default=False),
) -> GitHubDisconnectResponse:
    result = await service.disconnect(
        server_id,
        purge_deliveries=purge_deliveries,
        actor_id=_actor_id_from_user(_current_user),
    )
    return GitHubDisconnectResponse(
        server_id=result.server_id,
        disconnected=result.disconnected,
        remote_url=result.remote_url,
        local_history_preserved=result.local_history_preserved,
        purged_deliveries=result.purged_deliveries,
    )


@router.post("/github/fetch", response_model=GitHubSyncResponse)
async def fetch_github_first_sync(
    server_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> GitHubSyncResponse:
    result = await service.fetch_first_sync(
        server_id,
        trigger="manual",
        actor_id=_actor_id_from_user(_current_user),
    )
    return GitHubSyncResponse(
        server_id=result.server_id,
        sync_status=result.sync_status,
        trigger=result.trigger,
        main_fast_forwarded=result.main_fast_forwarded,
        previous_main_sha=result.previous_main_sha,
        main_sha=result.main_sha,
        remote_default_branch=result.remote_default_branch,
        remote_head_sha=result.remote_head_sha,
        branches=_github_branch_states(result.branches),
        fetched_at=result.fetched_at,
    )


@router.post("/github/push", response_model=GitHubPushResponse)
async def push_github_branch(
    server_id: str,
    body: PushGitHubBranchRequest,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> GitHubPushResponse:
    result = await service.push_branch(
        server_id,
        body.branch_name,
        force=False,
        actor_id=_actor_id_from_user(_current_user),
    )
    return GitHubPushResponse(
        server_id=result.server_id,
        branch_name=result.branch_name,
        commit_sha=result.commit_sha,
        remote_url=result.remote_url,
        sync_status=result.sync_status,
        branches=_github_branch_states(result.branches),
        pushed_at=result.pushed_at,
    )


@router.get(
    "/github/webhooks/deliveries",
    response_model=list[GitHubWebhookDeliveryResponse],
)
async def list_github_webhook_deliveries(
    server_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:read"))],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[GitHubWebhookDeliveryResponse]:
    records = await service.list_deliveries(server_id, limit=limit)
    return [_github_delivery_response(record) for record in records]


@router.post(
    "/github/webhooks/deliveries/{delivery_id}/redeliver",
    response_model=GitHubWebhookIngestResponse,
    status_code=202,
)
async def redeliver_github_webhook(
    server_id: str,
    delivery_id: str,
    service: Annotated[Any, Depends(get_github_sync_service)],
    _current_user: Annotated[dict, Depends(require_permission("server:version:commit"))],
) -> GitHubWebhookIngestResponse:
    result = await service.redeliver_webhook(
        server_id,
        delivery_id,
        actor_id=_actor_id_from_user(_current_user),
    )
    return _github_ingest_response(result)


# --- P5-3 public GitHub webhook receiver -------------------------------------


@github_webhook_router.post(
    "/{server_id}",
    response_model=GitHubWebhookIngestResponse,
    status_code=202,
)
async def receive_github_webhook(
    server_id: str,
    request: Request,
    response: Response,
    service: Annotated[Any, Depends(get_github_sync_service)],
) -> GitHubWebhookIngestResponse:
    raw_body = await _read_bounded_webhook_body(request)
    result = await service.ingest_webhook(
        server_id,
        raw_body=raw_body,
        signature_header=request.headers.get("X-Hub-Signature-256"),
        delivery_id=request.headers.get("X-GitHub-Delivery"),
        event_type=request.headers.get("X-GitHub-Event"),
    )
    response.status_code = 202 if result.status == "queued" else 200
    return _github_ingest_response(result)
