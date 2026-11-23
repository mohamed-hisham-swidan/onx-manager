from __future__ import annotations

from app.core.exceptions import NotFoundError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository
from app.modules.exposure.application.commands import (
    _agent_payload,
    _exposure_payload,
    _fold_aggregate,
    _panel_payload,
    _target_payload,
    resolve_server_branch_exposure_context,
)
from app.modules.exposure.domain.repository import (
    HostAgentRepository,
    PanelExposureRepository,
    ServerExposureRepository,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
    SQLServerRegisteredPortRepository,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


class GetServerExposureQuery(Query):
    server_id: str
    branch_name: str = "main"


class GetServerExposureHandler(QueryHandler[GetServerExposureQuery]):
    async def handle(self, query: GetServerExposureQuery) -> dict:
        async with UnitOfWork() as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(ServerId(query.server_id))
            if server is None:
                raise NotFoundError(
                    f"Server {query.server_id} not found",
                )

            ctx = await resolve_server_branch_exposure_context(
                uow.session, server, query.branch_name
            )
            exposure = await repo.get(query.server_id, branch_name=ctx["branch_name"])
            if exposure is None:
                return {
                    "server_id": query.server_id,
                    "branch_name": ctx["branch_name"],
                    "branch_runtime_status": ctx.get("branch_runtime_status"),
                    "allocated_game_port": ctx.get("game_port"),
                    "allocated_port_set": ctx.get("allocated_port_set"),
                    "method": "none",
                    "desired_state": "DISABLED",
                    "aggregate_status": "DISABLED",
                    "error_code": None,
                    "error_message": None,
                    "cloudflare_tunnel_id": None,
                    "has_cloudflare_credentials": False,
                    "cloudflare_mode": None,
                    "subdomain_prefix": None,
                    "base_domain": None,
                    "srv_record_enabled": False,
                    "srv_record_hint": None,
                    "ephemeral": False,
                    "upnp_status": "IDLE",
                    "detected_wan_ip": None,
                    "targets": [],
                }
            _fold_aggregate(exposure)
            await repo.save(exposure)
            await uow.commit()
            return _exposure_payload(exposure, branch_context=ctx)


class GetAgentStatusQuery(Query):
    pass


class GetAgentStatusHandler(QueryHandler[GetAgentStatusQuery]):
    async def handle(self, _query: GetAgentStatusQuery) -> dict:
        async with UnitOfWork() as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            return _agent_payload(agent)


class GetPanelExposureQuery(Query):
    pass


class GetPanelExposureHandler(QueryHandler[GetPanelExposureQuery]):
    async def handle(self, _query: GetPanelExposureQuery) -> dict:
        from app.core.config import get_active_panel_bind
        from app.core.event_bus import EventBus
        from app.modules.exposure.application.commands import (
            SetPanelExposureCommand,
            SetPanelExposureHandler,
            _is_loopback_bind_host,
        )
        from app.modules.exposure.domain.value_objects import DesiredState, PanelExposureMethod

        async with UnitOfWork() as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            state_repo = SQLSystemStateRepository(uow.session)
            panel = await repo.get()
            system_state = await state_repo.get()
            access_mode = system_state.access_mode

            should_recheck_bind = (
                panel.method == PanelExposureMethod.PORT_FORWARD
                and panel.desired_state == DesiredState.ENABLED
                and panel.error_code == "BIND_MISMATCH"
            )

        if should_recheck_bind:
            active_host, _ = get_active_panel_bind()
            if not _is_loopback_bind_host(active_host):
                result = await SetPanelExposureHandler(EventBus()).handle(
                    SetPanelExposureCommand(
                        method="port_forward",
                        desired_state="ENABLED",
                        external_port=panel.external_port,
                    )
                )
                if result.success and result.data:
                    return result.data

        return _panel_payload(panel, access_mode=access_mode)


class ListExposureTargetsQuery(Query):
    server_id: str
    branch_name: str = "main"


class ListExposureTargetsHandler(QueryHandler[ListExposureTargetsQuery]):
    async def handle(self, query: ListExposureTargetsQuery) -> list[dict]:
        async with UnitOfWork() as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(query.server_id, branch_name=query.branch_name)
            if exposure is None:
                raise NotFoundError(
                    f"Exposure not found for server {query.server_id}",
                )
            return [_target_payload(t) for t in exposure.targets]


class ListServerPortsQuery(Query):
    server_id: str


class ListServerPortsHandler(QueryHandler[ListServerPortsQuery]):
    async def handle(self, query: ListServerPortsQuery) -> list[dict]:
        async with UnitOfWork() as uow:
            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            ports = await ports_repo.list_for_server(query.server_id)
            return [
                {
                    "id": p.id,
                    "server_id": p.server_id,
                    "service_type": p.service_type,
                    "protocol": p.protocol,
                    "port": p.port,
                    "name": p.name,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in ports
            ]
