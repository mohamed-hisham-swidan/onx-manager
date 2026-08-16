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


class GetServerExposureQuery(Query):
    server_id: str


class GetServerExposureHandler(QueryHandler[GetServerExposureQuery]):
    async def handle(self, query: GetServerExposureQuery) -> dict:
        async with UnitOfWork() as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(query.server_id)
            if exposure is None:
                raise NotFoundError(
                    f"Exposure not found for server {query.server_id}",
                )
            _fold_aggregate(exposure)
            await repo.save(exposure)
            await uow.commit()
            return _exposure_payload(exposure)


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
        async with UnitOfWork() as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            state_repo = SQLSystemStateRepository(uow.session)
            panel = await repo.get()
            system_state = await state_repo.get()
            return _panel_payload(panel, access_mode=system_state.access_mode)


class ListExposureTargetsQuery(Query):
    server_id: str


class ListExposureTargetsHandler(QueryHandler[ListExposureTargetsQuery]):
    async def handle(self, query: ListExposureTargetsQuery) -> list[dict]:
        async with UnitOfWork() as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(query.server_id)
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
