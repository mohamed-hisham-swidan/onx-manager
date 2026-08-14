from fastapi import APIRouter, Depends

from app.api.deps import (
    get_command_bus,
    get_query_bus,
    require_exposure_grant,
    require_owner,
    require_permission,
)
from app.api.errors import check_command_result
from app.api.v1.schemas.exposure import (
    AgentStatusResponse,
    ClaimResponse,
    PanelExposureResponse,
    PanelExposureUpdateRequest,
    ReconcileRequest,
    ServerExposureResponse,
    ServerExposureStateUpdateRequest,
    ServerExposureUpdateRequest,
    StopAllResponse,
    TargetCreateRequest,
    TargetResponse,
)
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.exposure.application import (
    CreateExposureTargetCommand,
    DisableServerExposureCommand,
    EnableServerExposureCommand,
    GenerateClaimCommand,
    GetAgentStatusQuery,
    GetPanelExposureQuery,
    GetServerExposureQuery,
    ListExposureTargetsQuery,
    ReconcileExposureCommand,
    RemoveCredentialsCommand,
    RemoveServerExposureCommand,
    ResetAgentCommand,
    SetPanelExposureCommand,
    SetServerExposureCommand,
    StopAllExposuresCommand,
)

router = APIRouter(prefix="/api/v1", tags=["exposure"])

__all__ = ["router"]


@router.get("/exposure/agent", response_model=AgentStatusResponse)
async def get_agent_status(
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_permission("exposure.credentials.manage")),  # noqa: B008
) -> AgentStatusResponse:
    return AgentStatusResponse(**await query_bus.ask(GetAgentStatusQuery()))


@router.post("/exposure/agent/claim", response_model=ClaimResponse, status_code=201)
async def generate_claim(
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_owner()),  # noqa: B008
) -> ClaimResponse:
    result = await command_bus.send(
        GenerateClaimCommand(actor_id=current_user.get("user_id", ""))
    )
    return ClaimResponse(**check_command_result(result))


@router.post("/exposure/agent/reset", response_model=AgentStatusResponse)
async def reset_agent(
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_owner()),  # noqa: B008
) -> AgentStatusResponse:
    result = await command_bus.send(ResetAgentCommand(actor_id=current_user.get("user_id", "")))
    return AgentStatusResponse(**check_command_result(result))


@router.post("/exposure/agent/reconcile")
async def reconcile_exposure(
    body: ReconcileRequest | None = None,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_permission("exposure.credentials.manage")),  # noqa: B008
) -> dict:
    scope = body.scope if body else "server"
    result = await command_bus.send(
        ReconcileExposureCommand(scope=scope, actor_id=current_user.get("user_id", ""))
    )
    return check_command_result(result)


@router.post("/exposure/stop-all", response_model=StopAllResponse)
async def stop_all_exposures(
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_owner()),  # noqa: B008
) -> StopAllResponse:
    result = await command_bus.send(
        StopAllExposuresCommand(actor_id=current_user.get("user_id", ""))
    )
    return StopAllResponse(**check_command_result(result))


@router.post("/exposure/credentials/remove")
async def remove_credentials(
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_owner()),  # noqa: B008
) -> dict:
    result = await command_bus.send(
        RemoveCredentialsCommand(actor_id=current_user.get("user_id", ""))
    )
    return check_command_result(result)


@router.get("/exposure/panel", response_model=PanelExposureResponse)
async def get_panel_exposure(
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_permission("exposure.panel.manage")),  # noqa: B008
) -> PanelExposureResponse:
    return PanelExposureResponse(**await query_bus.ask(GetPanelExposureQuery()))


@router.put("/exposure/panel", response_model=PanelExposureResponse)
async def set_panel_exposure(
    body: PanelExposureUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_permission("exposure.panel.manage")),  # noqa: B008
) -> PanelExposureResponse:
    result = await command_bus.send(
        SetPanelExposureCommand(
            method=body.method,
            desired_state=body.desired_state,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return PanelExposureResponse(**check_command_result(result))


@router.get(
    "/servers/{server_id}/exposure",
    response_model=ServerExposureResponse,
)
async def get_server_exposure(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure.view")),  # noqa: B008
) -> ServerExposureResponse:
    result = await query_bus.ask(GetServerExposureQuery(server_id=server_id))
    return ServerExposureResponse(**result)


@router.put(
    "/servers/{server_id}/exposure",
    response_model=ServerExposureResponse,
)
async def set_server_exposure(
    server_id: str,
    body: ServerExposureUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> ServerExposureResponse:
    result = await command_bus.send(
        SetServerExposureCommand(
            server_id=server_id,
            method=body.method,
            desired_state=body.desired_state,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return ServerExposureResponse(**check_command_result(result))


@router.patch(
    "/servers/{server_id}/exposure",
    response_model=ServerExposureResponse,
)
async def set_server_exposure_state(
    server_id: str,
    body: ServerExposureStateUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> ServerExposureResponse:
    if body.desired_state == "ENABLED":
        cmd = EnableServerExposureCommand(server_id=server_id)
    else:
        cmd = DisableServerExposureCommand(server_id=server_id)
    result = await command_bus.send(cmd)
    return ServerExposureResponse(**check_command_result(result))


@router.delete(
    "/servers/{server_id}/exposure",
    status_code=204,
)
async def remove_server_exposure(
    server_id: str,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> None:
    await command_bus.send(
        RemoveServerExposureCommand(server_id=server_id, actor_id=current_user.get("user_id", ""))
    )


@router.get(
    "/servers/{server_id}/exposure/targets",
    response_model=list[TargetResponse],
)
async def list_exposure_targets(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure.view")),  # noqa: B008
) -> list[TargetResponse]:
    return [
        TargetResponse(**t)
        for t in await query_bus.ask(ListExposureTargetsQuery(server_id=server_id))
    ]


@router.post(
    "/servers/{server_id}/exposure/targets",
    response_model=TargetResponse,
    status_code=201,
)
async def create_exposure_target(
    server_id: str,
    _body: TargetCreateRequest | None = None,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> TargetResponse:
    result = await command_bus.send(
        CreateExposureTargetCommand(server_id=server_id, actor_id=current_user.get("user_id", ""))
    )
    return TargetResponse(**check_command_result(result))
