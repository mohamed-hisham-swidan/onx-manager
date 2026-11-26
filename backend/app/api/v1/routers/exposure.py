from fastapi import APIRouter, Depends, Query

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
    RegisteredPortCreateRequest,
    RegisteredPortResponse,
    ServerExposureResponse,
    ServerExposureStateUpdateRequest,
    ServerExposureUpdateRequest,
    StopAllResponse,
    TargetCreateRequest,
    TargetResponse,
    TargetUpdateRequest,
)
from app.core.command_bus import CommandBus
from app.core.query_bus import QueryBus
from app.modules.exposure.application import (
    CreateExposureTargetCommand,
    DeleteServerPortCommand,
    DisableServerExposureCommand,
    EnableServerExposureCommand,
    GenerateClaimCommand,
    GetAgentStatusQuery,
    GetPanelExposureQuery,
    GetServerExposureQuery,
    ListExposureTargetsQuery,
    ListServerPortsQuery,
    ReconcileExposureCommand,
    RegisterServerPortCommand,
    RemoveCredentialsCommand,
    RemoveServerExposureCommand,
    ResetAgentCommand,
    SetPanelExposureCommand,
    SetServerExposureCommand,
    StopAllExposuresCommand,
    UpdateExposureTargetCommand,
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
    result = await command_bus.send(GenerateClaimCommand(actor_id=current_user.get("user_id", "")))
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


def _to_panel_exposure_response(data: dict) -> PanelExposureResponse:
    """Project internal panel payload onto API schema without ever returning secrets."""
    payload = dict(data)
    has_creds = bool(payload.pop("has_cloudflare_credentials", False))
    ephemeral = bool(payload.get("ephemeral", False))
    method = payload.get("method")
    if method == "cloudflare_tunnel":
        is_quick = ephemeral or payload.get("cloudflare_tunnel_id") == "quick"
        cf_mode = "quick" if is_quick else "token"
    else:
        cf_mode = None
    payload["token_configured"] = has_creds
    payload["cloudflare_mode"] = cf_mode
    payload["ephemeral"] = ephemeral
    return PanelExposureResponse(**payload)


@router.get("/exposure/panel", response_model=PanelExposureResponse)
async def get_panel_exposure(
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_owner()),  # noqa: B008
) -> PanelExposureResponse:
    return _to_panel_exposure_response(await query_bus.ask(GetPanelExposureQuery()))


@router.put("/exposure/panel", response_model=PanelExposureResponse)
async def set_panel_exposure(
    body: PanelExposureUpdateRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_owner()),  # noqa: B008
) -> PanelExposureResponse:
    result = await command_bus.send(
        SetPanelExposureCommand(
            method=body.method,
            desired_state=body.desired_state,
            cloudflare_mode=body.cloudflare_mode,
            cloudflare_token=body.cloudflare_token,
            hostname=body.hostname,
            external_port=body.external_port,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return _to_panel_exposure_response(check_command_result(result))


def _is_blocked_ssrf_probe_host(host: str) -> bool:
    """Reject loopback/private/link-local/metadata IPs on user-supplied external probes."""
    import ipaddress

    cleaned = (host or "").strip().strip("[]").lower()
    if not cleaned:
        return True
    if cleaned in ("localhost", "localhost.localdomain", "metadata.google.internal"):
        return True
    try:
        ip = ipaddress.ip_address(cleaned)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def _parse_probe_host_port(result: dict) -> tuple[str, int] | None:
    """Resolve the (host, port) target for a live Minecraft SLP reachability probe."""
    targets = result.get("targets") or []
    is_active = (
        result.get("desired_state") == "ENABLED"
        and result.get("aggregate_status") == "ACTIVE"
    )
    if is_active and targets:
        primary = next((t for t in targets if t.get("service_type") == "java"), targets[0])
        raw_addr = (primary.get("public_address") or "").strip()
        if raw_addr:
            clean = raw_addr
            if "://" in clean:
                clean = clean.split("://", 1)[1]
            clean = clean.split("/", 1)[0].strip()
            if clean:
                host_part = clean
                port_val = 25565
                if clean.startswith("[") and "]" in clean:
                    host_part, _, rest = clean[1:].partition("]")
                    if rest.startswith(":") and rest[1:].isdigit():
                        port_val = int(rest[1:])
                elif ":" in clean:
                    h, p = clean.rsplit(":", 1)
                    if h and p.isdigit():
                        host_part = h
                        port_val = int(p)
                if _is_blocked_ssrf_probe_host(host_part):
                    return None
                return host_part, port_val
    return None


@router.get(
    "/servers/{server_id}/exposure",
    response_model=ServerExposureResponse,
)
async def get_server_exposure(
    server_id: str,
    branch: str | None = Query(default=None),
    probe: bool = Query(default=False),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure.view")),  # noqa: B008
) -> ServerExposureResponse:
    result = await query_bus.ask(
        GetServerExposureQuery(server_id=server_id, branch_name=branch or "main")
    )
    if probe:
        from app.modules.versioning.infrastructure.mc_slp import probe_minecraft_slp

        parsed_target = _parse_probe_host_port(result)
        if parsed_target is None:
            result = {
                **result,
                "reachability": {
                    "reachable": False,
                    "target_address": "",
                    "latency_ms": None,
                    "version_name": None,
                    "protocol_version": None,
                    "players_online": None,
                    "players_max": None,
                    "motd": None,
                    "error": "No active public external address available to probe",
                },
            }
        else:
            host, port = parsed_target
            slp = await probe_minecraft_slp(host, port, timeout_seconds=4.0)
            result = {
                **result,
                "reachability": {
                    "reachable": slp.reachable,
                    "target_address": f"{host}:{port}",
                    "latency_ms": slp.latency_ms,
                    "version_name": slp.version_name,
                    "protocol_version": slp.protocol_version,
                    "players_online": slp.players_online,
                    "players_max": slp.players_max,
                    "motd": slp.motd,
                    "error": slp.error,
                },
            }
    return ServerExposureResponse(**result)


@router.put(
    "/servers/{server_id}/exposure",
    response_model=ServerExposureResponse,
)
async def set_server_exposure(
    server_id: str,
    body: ServerExposureUpdateRequest,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> ServerExposureResponse:
    result = await command_bus.send(
        SetServerExposureCommand(
            server_id=server_id,
            branch_name=branch or "main",
            method=body.method,
            desired_state=body.desired_state,
            cloudflare_mode=body.cloudflare_mode,
            cloudflare_token=body.cloudflare_token,
            hostname=body.hostname,
            subdomain_prefix=body.subdomain_prefix,
            base_domain=body.base_domain,
            srv_record_enabled=body.srv_record_enabled,
            external_port=body.external_port,
            acknowledged_warning=body.acknowledged_warning,
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
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> ServerExposureResponse:
    if body.desired_state == "ENABLED":
        cmd = EnableServerExposureCommand(
            server_id=server_id,
            branch_name=branch or "main",
            cloudflare_token=body.cloudflare_token,
            hostname=body.hostname,
            acknowledged_warning=body.acknowledged_warning,
        )
    else:
        cmd = DisableServerExposureCommand(server_id=server_id, branch_name=branch or "main")
    result = await command_bus.send(cmd)
    return ServerExposureResponse(**check_command_result(result))


@router.delete(
    "/servers/{server_id}/exposure",
    status_code=204,
)
async def remove_server_exposure(
    server_id: str,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> None:
    effective_branch = branch if isinstance(branch, str) and branch else "main"
    result = await command_bus.send(
        RemoveServerExposureCommand(
            server_id=server_id,
            branch_name=effective_branch,
            actor_id=current_user.get("user_id", ""),
        )
    )
    check_command_result(result)


@router.get(
    "/servers/{server_id}/exposure/targets",
    response_model=list[TargetResponse],
)
async def list_exposure_targets(
    server_id: str,
    branch: str | None = Query(default=None),
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure.view")),  # noqa: B008
) -> list[TargetResponse]:
    return [
        TargetResponse(**t)
        for t in await query_bus.ask(
            ListExposureTargetsQuery(server_id=server_id, branch_name=branch or "main")
        )
    ]


@router.post(
    "/servers/{server_id}/exposure/targets",
    response_model=TargetResponse,
    status_code=201,
)
async def create_exposure_target(
    server_id: str,
    body: TargetCreateRequest | None = None,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> TargetResponse:
    result = await command_bus.send(
        CreateExposureTargetCommand(
            server_id=server_id,
            branch_name=branch or "main",
            service_type=body.service_type if body else "java",
            protocol=body.protocol if body else None,
            local_port=body.local_port if body else None,
            public_address=body.public_address if body else None,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return TargetResponse(**check_command_result(result))


@router.put(
    "/servers/{server_id}/exposure/targets/{target_id}",
    response_model=TargetResponse,
)
async def update_exposure_target(
    server_id: str,
    target_id: str,
    body: TargetUpdateRequest,
    branch: str | None = Query(default=None),
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> TargetResponse:
    result = await command_bus.send(
        UpdateExposureTargetCommand(
            server_id=server_id,
            branch_name=branch or "main",
            target_id=target_id,
            public_address=body.public_address,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return TargetResponse(**check_command_result(result))


@router.get(
    "/servers/{server_id}/ports",
    response_model=list[RegisteredPortResponse],
)
async def list_server_ports(
    server_id: str,
    query_bus: QueryBus = Depends(get_query_bus),  # noqa: B008
    _current_user: dict = Depends(require_exposure_grant("server.{id}.exposure.view")),  # noqa: B008
) -> list[RegisteredPortResponse]:
    result = await query_bus.ask(ListServerPortsQuery(server_id=server_id))
    return [RegisteredPortResponse(**p) for p in result]


@router.post(
    "/servers/{server_id}/ports",
    response_model=RegisteredPortResponse,
    status_code=201,
)
async def register_server_port(
    server_id: str,
    body: RegisteredPortCreateRequest,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> RegisteredPortResponse:
    result = await command_bus.send(
        RegisterServerPortCommand(
            server_id=server_id,
            service_type=body.service_type,
            protocol=body.protocol,
            port=body.port,
            name=body.name,
            actor_id=current_user.get("user_id", ""),
        )
    )
    return RegisteredPortResponse(**check_command_result(result))


@router.delete(
    "/servers/{server_id}/ports/{port_id}",
    status_code=204,
)
async def delete_server_port(
    server_id: str,
    port_id: str,
    command_bus: CommandBus = Depends(get_command_bus),  # noqa: B008
    current_user: dict = Depends(require_exposure_grant("server.{id}.exposure")),  # noqa: B008
) -> None:
    result = await command_bus.send(
        DeleteServerPortCommand(
            server_id=server_id,
            port_id=port_id,
            actor_id=current_user.get("user_id", ""),
        )
    )
    check_command_result(result)
