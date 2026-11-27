from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile

from app.api.deps import (
    get_command_bus,
    get_event_bus,
    get_query_bus,
    require_server_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.plugin import (
    InstallModrinthPluginRequest,
    InstallModrinthPluginResponse,
    PluginFileResponse,
    PluginResponse,
    PluginSearchResultResponse,
    PluginSearchResultsResponse,
    PluginVersionResponse,
    PluginVersionsResponse,
    ToggleModStateRequest,
)
from app.core.command_bus import CommandBus
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import (
    DownloadError,
    MCSError,
    NotFoundError,
    RateLimitExceeded,
    ValidationError,
)
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.plugin.application import (
    DisablePluginCommand,
    EnablePluginCommand,
    GetPluginQuery,
    InstallModrinthPluginCommand,
    ListPluginsQuery,
    ReconcilePluginsCommand,
    ToggleModStateCommand,
    UninstallPluginCommand,
    UploadModCommand,
)
from app.modules.plugin.application.branch_plugins import (
    install_branch_modrinth_plugin,
    list_branch_plugins,
    remove_branch_plugin,
    toggle_branch_plugin,
    upload_branch_addon,
)
from app.modules.plugin.application.services.version_selector import select_best_version
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider
from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo
from app.modules.server.application.queries.get_server import GetServerQuery
from app.modules.server.domain.value_objects import ServerMode
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

router = APIRouter(prefix="/api/v1/servers/{server_id}/plugins", tags=["plugins"])

__all__ = ["router"]


def _to_version_response(v: PluginVersionInfo) -> PluginVersionResponse:
    return PluginVersionResponse(
        version_id=v.version_id,
        project_id=v.project_id,
        name=v.name,
        version_number=v.version_number,
        game_versions=v.game_versions,
        loaders=v.loaders,
        files=[PluginFileResponse(**f.__dict__) for f in v.files],
        dependencies=v.dependencies,
        required_dependencies=list(getattr(v, "required_dependencies", []) or []),
        changelog=getattr(v, "changelog", None),
        date_published=v.date_published,
        version_type=getattr(v, "version_type", "release") or "release",
    )


def _translate_provider_download_error(exc: DownloadError, *, not_found_msg: str) -> None:
    if exc.status == 404:
        raise NotFoundError(not_found_msg) from exc
    if exc.status == 400:
        raise ValidationError(str(exc)) from exc
    if exc.status == 429:
        retry_after = exc.details.get("retry_after") or exc.details.get("ratelimit_reset") or 60
        raise RateLimitExceeded(
            message="Upstream marketplace rate limit exceeded",
            details={"retry_after": retry_after},
        ) from exc
    raise exc


async def _load_server_aggregate(server_id: str):
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(ServerId(server_id))


@router.get(
    "",
    response_model=list[PluginResponse],
    dependencies=[Depends(require_server_permission("server.{id}.plugins.view"))],
)
async def list_plugins(
    server_id: str,
    response: Response,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),
    query_bus: QueryBus = Depends(get_query_bus),
) -> list[PluginResponse]:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        items, has_uncommitted = list_branch_plugins(server, effective_branch)
        if has_uncommitted:
            response.headers["X-ONX-Has-Uncommitted"] = "true"
        return [PluginResponse(**item) for item in items]

    await command_bus.send(ReconcilePluginsCommand(server_id=server_id))
    q = ListPluginsQuery(server_id=server_id)
    plugins = await query_bus.ask(q)
    return [PluginResponse(**p.__dict__) for p in plugins]


_MOD_FAMILY_LOADERS = frozenset({"fabric", "forge", "neoforge", "quilt"})
_PLUGIN_FAMILY_LOADERS = frozenset(
    {
        "paper",
        "purpur",
        "spigot",
        "bukkit",
        "folia",
        "velocity",
        "bungeecord",
        "waterfall",
        "minestom",
    }
)


@router.get(
    "/marketplace/search",
    response_model=PluginSearchResultsResponse,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def search_marketplace(
    server_id: str,
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    project_type: str | None = Query(default=None),
    loader: str = Query(default="", max_length=50),
    sort: Literal["relevance", "downloads", "follows", "newest", "updated"] = Query(
        default="relevance"
    ),
    game_version: str | None = Query(default=None, max_length=32),
    compatible_only: bool = Query(default=False),
) -> PluginSearchResultsResponse:
    provider = build_plugin_catalog_provider()
    effective_project_type = (
        project_type.strip().lower() if project_type and project_type.strip() else None
    )
    effective_loader = loader.strip() or None
    effective_game_version = (
        game_version.strip() if game_version and game_version.strip() else None
    )

    if compatible_only:
        server = await _load_server_aggregate(server_id)
        if server is not None:
            st = (
                server.server_type.value.lower()
                if hasattr(server.server_type, "value")
                else str(getattr(server, "server_type", "") or "").lower()
            )
            server_family = "mod" if st in _MOD_FAMILY_LOADERS else "plugin"
            effective_project_type = server_family
            if effective_loader is None and st in (_MOD_FAMILY_LOADERS | _PLUGIN_FAMILY_LOADERS):
                effective_loader = st
            if effective_game_version is None and server.minecraft_version:
                effective_game_version = str(server.minecraft_version)

    try:
        page = await provider.search(
            query,
            limit=limit,
            offset=offset,
            project_type=effective_project_type or "plugin",
            loader=effective_loader,
            sort=sort,
            game_version=effective_game_version,
        )
    except DownloadError as e:
        _translate_provider_download_error(e, not_found_msg="Marketplace search failed")
    return PluginSearchResultsResponse(
        items=[PluginSearchResultResponse(**r.__dict__) for r in page.items],
        total_hits=page.total_hits,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/marketplace/projects/{project_id}/versions",
    response_model=PluginVersionsResponse,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def get_project_versions(
    server_id: str,
    project_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    query_bus: QueryBus = Depends(get_query_bus),
) -> PluginVersionsResponse:
    server = await query_bus.ask(GetServerQuery(server_id=server_id))
    provider = build_plugin_catalog_provider()
    try:
        page = await provider.get_project_versions(project_id)
    except DownloadError as e:
        _translate_provider_download_error(
            e, not_found_msg=f"Marketplace project '{project_id}' not found"
        )
    versions = page.items

    selected = None
    notice = ""
    notice_kind = ""
    ordered_versions = versions
    if server is not None:
        selection = select_best_version(
            server_type=server.server_type,
            minecraft_version=server.minecraft_version,
            versions=versions,
        )
        if selection.selected is not None:
            selected = _to_version_response(selection.selected)
        if selection.available:
            ordered_versions = list(selection.available)
        notice = selection.notice
        notice_kind = selection.notice_kind

    versions_response = [_to_version_response(v) for v in ordered_versions]

    return PluginVersionsResponse(
        project_id=project_id,
        versions=versions_response[offset : offset + limit],
        selected=selected,
        notice=notice,
        notice_kind=notice_kind,
        total=page.total,
    )


@router.post(
    "/marketplace/install",
    response_model=InstallModrinthPluginResponse,
    status_code=201,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def install_from_marketplace(
    server_id: str,
    body: InstallModrinthPluginRequest,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),
    event_bus: EventBus = Depends(get_event_bus),
) -> InstallModrinthPluginResponse:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or body.branch or "main").strip() or "main"
        data = await install_branch_modrinth_plugin(
            server=server,
            branch_name=effective_branch,
            project_id=body.project_id,
            version_id=body.version_id,
            minecraft_version=body.minecraft_version,
            event_bus=event_bus,
        )
        return InstallModrinthPluginResponse(**data)

    cmd = InstallModrinthPluginCommand(
        server_id=server_id,
        project_id=body.project_id,
        version_id=body.version_id,
        minecraft_version=body.minecraft_version,
    )
    result = await command_bus.send(cmd)
    data = check_command_result(result)
    return InstallModrinthPluginResponse(**data)


@router.get(
    "/{plugin_id}",
    response_model=PluginResponse,
    dependencies=[Depends(require_server_permission("server.{id}.plugins.view"))],
)
async def get_plugin(
    server_id: str,
    plugin_id: str,
    branch: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),
) -> PluginResponse:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        items, _ = list_branch_plugins(server, effective_branch)
        for item in items:
            if item["plugin_id"] == plugin_id:
                return PluginResponse(**item)
        raise HTTPException(status_code=404, detail="Plugin not found on this branch")

    result = await query_bus.ask(GetPluginQuery(plugin_id=plugin_id))
    if result.server_id != server_id:
        raise HTTPException(status_code=404, detail="Plugin not found on this server")
    return PluginResponse(**result.__dict__)


@router.delete(
    "/{plugin_id}",
    status_code=204,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def uninstall_plugin(
    server_id: str,
    plugin_id: str,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),
    query_bus: QueryBus = Depends(get_query_bus),
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        await remove_branch_plugin(
            server=server,
            branch_name=effective_branch,
            plugin_identifier=plugin_id,
            event_bus=event_bus,
        )
        return

    plugin = await query_bus.ask(GetPluginQuery(plugin_id=plugin_id))
    if plugin.server_id != server_id:
        raise HTTPException(status_code=404, detail="Plugin not found on this server")
    cmd = UninstallPluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    check_command_result(result)


@router.post(
    "/{plugin_id}/enable",
    response_model=dict,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def enable_plugin(
    server_id: str,
    plugin_id: str,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),
    query_bus: QueryBus = Depends(get_query_bus),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        return await toggle_branch_plugin(
            server=server,
            branch_name=effective_branch,
            plugin_identifier=plugin_id,
            enabled=True,
            event_bus=event_bus,
        )

    plugin = await query_bus.ask(GetPluginQuery(plugin_id=plugin_id))
    if plugin.server_id != server_id:
        raise HTTPException(status_code=404, detail="Plugin not found on this server")
    cmd = EnablePluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.post(
    "/{plugin_id}/disable",
    response_model=dict,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def disable_plugin(
    server_id: str,
    plugin_id: str,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),
    query_bus: QueryBus = Depends(get_query_bus),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        return await toggle_branch_plugin(
            server=server,
            branch_name=effective_branch,
            plugin_identifier=plugin_id,
            enabled=False,
            event_bus=event_bus,
        )

    plugin = await query_bus.ask(GetPluginQuery(plugin_id=plugin_id))
    if plugin.server_id != server_id:
        raise HTTPException(status_code=404, detail="Plugin not found on this server")
    cmd = DisablePluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.post(
    "/upload",
    response_model=dict,
    status_code=201,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def upload_mod(
    server_id: str,
    file: UploadFile,
    branch: str | None = Query(default=None),
    command_bus: Annotated[CommandBus, Depends(get_command_bus)] = ...,  # type: ignore[assignment]
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    max_mb = AppSettings().files_max_upload_size_mb
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0
    chunk_size = 64 * 1024
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if max_bytes > 0 and total_bytes > max_bytes:
            raise MCSError(
                message=f"Uploaded plugin exceeds maximum allowed size of {max_mb} MB",
                code="FILE_TOO_LARGE",
                http_status=413,
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    filename = file.filename or "addon.jar"
    server = await _load_server_aggregate(server_id)
    if server is None:
        raise NotFoundError(f"Server '{server_id}' not found")
    if server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        return await upload_branch_addon(
            server=server,
            branch_name=effective_branch,
            filename=filename,
            file_content=content,
            event_bus=event_bus,
        )

    cmd = UploadModCommand(
        server_id=server_id,
        filename=filename,
        file_content=content,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.post(
    "/toggle",
    response_model=dict,
    dependencies=[
        Depends(require_server_permission("server.{id}.plugins")),
    ],
)
async def toggle_mod(
    server_id: str,
    body: ToggleModStateRequest,
    branch: str | None = Query(default=None),
    command_bus: Annotated[CommandBus, Depends(get_command_bus)] = ...,  # type: ignore[assignment]
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    server = await _load_server_aggregate(server_id)
    if server is not None and server.mode == ServerMode.ADVANCED:
        effective_branch = (branch or "main").strip() or "main"
        ident = body.plugin_id or body.mod_id or ""
        return await toggle_branch_plugin(
            server=server,
            branch_name=effective_branch,
            plugin_identifier=ident,
            enabled=body.enabled,
            event_bus=event_bus,
        )

    cmd = ToggleModStateCommand(
        server_id=server_id,
        mod_id=body.mod_id,
        plugin_id=body.plugin_id,
        enabled=body.enabled,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)

