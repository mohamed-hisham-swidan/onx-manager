from fastapi import APIRouter, Depends

from app.api.deps import (
    get_command_bus,
    get_current_user,
    get_query_bus,
    require_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.plugin import InstallPluginRequest, PluginResponse
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.plugin.application import (
    DisablePluginCommand,
    EnablePluginCommand,
    GetPluginQuery,
    InstallPluginCommand,
    ListPluginsQuery,
    UninstallPluginCommand,
)

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
    current_user: dict = Depends(get_current_user),
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
