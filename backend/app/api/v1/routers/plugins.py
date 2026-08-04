from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.plugin import (
    InstallModrinthPluginRequest,
    InstallModrinthPluginResponse,
    InstallPluginRequest,
    PluginResponse,
    PluginSearchResultResponse,
    PluginVersionsResponse,
    PluginVersionResponse,
)
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.plugin.application import (
    DisablePluginCommand,
    EnablePluginCommand,
    GetPluginQuery,
    InstallModrinthPluginCommand,
    InstallPluginCommand,
    ListPluginsQuery,
    UninstallPluginCommand,
)
from app.modules.plugin.application.services.version_selector import select_best_version
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider
from app.modules.server.application.queries.get_server import GetServerQuery

router = APIRouter(prefix="/api/v1/servers/{server_id}/plugins", tags=["plugins"])

__all__ = ["router"]


@router.get("", response_model=list[PluginResponse])
async def list_plugins(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> list[PluginResponse]:
    q = ListPluginsQuery(server_id=server_id)
    plugins = await query_bus.ask(q)
    return [PluginResponse(**p.__dict__) for p in plugins]


@router.post("", response_model=dict, status_code=201)
async def install_plugin(
    server_id: str,
    body: InstallPluginRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> dict:
    cmd = InstallPluginCommand(
        server_id=server_id,
        name=body.name,
        version=body.version,
        description=body.description,
        author=body.author,
        website=body.website,
        dependencies=body.dependencies,
    )
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.get("/marketplace/search", response_model=list[PluginSearchResultResponse])
async def search_marketplace(
    server_id: str,
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> list[PluginSearchResultResponse]:
    provider = build_plugin_catalog_provider()
    results = await provider.search(query, limit=limit, offset=offset)
    return [PluginSearchResultResponse(**r.__dict__) for r in results]


@router.get("/marketplace/projects/{project_id}/versions", response_model=PluginVersionsResponse)
async def get_project_versions(
    server_id: str,
    project_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> PluginVersionsResponse:
    server = await query_bus.ask(GetServerQuery(server_id=server_id))
    provider = build_plugin_catalog_provider()
    versions = await provider.get_project_versions(project_id)
    versions_response = [PluginVersionResponse(**v.__dict__) for v in versions]

    selected = None
    notice = ""
    notice_kind = ""
    if server is not None:
        selection = select_best_version(
            server_type=server.server_type,
            minecraft_version=server.minecraft_version,
            versions=versions,
        )
        if selection.selected is not None:
            selected = PluginVersionResponse(**selection.selected.__dict__)
        notice = selection.notice
        notice_kind = selection.notice_kind

    return PluginVersionsResponse(
        project_id=project_id,
        versions=versions_response,
        selected=selected,
        notice=notice,
        notice_kind=notice_kind,
    )


@router.post("/marketplace/install", response_model=InstallModrinthPluginResponse, status_code=201)
async def install_from_marketplace(
    server_id: str,
    body: InstallModrinthPluginRequest,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> InstallModrinthPluginResponse:
    cmd = InstallModrinthPluginCommand(
        server_id=server_id,
        project_id=body.project_id,
        version_id=body.version_id,
        minecraft_version=body.minecraft_version,
    )
    result = await command_bus.send(cmd)
    data = check_command_result(result)
    return InstallModrinthPluginResponse(**data)


@router.get("/{plugin_id}", response_model=PluginResponse)
async def get_plugin(
    server_id: str,
    plugin_id: str,
    query_bus: QueryBus = Depends(get_query_bus),
    current_user: dict = Depends(get_current_user),
) -> PluginResponse:
    result = await query_bus.ask(GetPluginQuery(plugin_id=plugin_id))
    return PluginResponse(**result.__dict__)


@router.delete("/{plugin_id}", status_code=204)
async def uninstall_plugin(
    server_id: str,
    plugin_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(require_permission("plugin:manage")),
) -> None:
    cmd = UninstallPluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    check_command_result(result)


@router.post("/{plugin_id}/enable", response_model=dict)
async def enable_plugin(
    server_id: str,
    plugin_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = EnablePluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    return check_command_result(result)


@router.post("/{plugin_id}/disable", response_model=dict)
async def disable_plugin(
    server_id: str,
    plugin_id: str,
    command_bus: CommandBus = Depends(get_command_bus),
    current_user: dict = Depends(get_current_user),
) -> dict:
    cmd = DisablePluginCommand(plugin_id=plugin_id)
    result = await command_bus.send(cmd)
    return check_command_result(result)
