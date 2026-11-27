import contextlib

from sqlalchemy import select

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.read_models import ServerReadModel
from app.modules.server.domain.repository import ServerFilters, ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository


class ListServersQuery(Query):
    status: str | None = None
    group_id: str | None = None
    name_search: str | None = None
    minecraft_version: str | None = None
    allowed_server_ids: list[str] | None = None


class ListServersHandler(QueryHandler[ListServersQuery]):
    async def handle(self, query: ListServersQuery) -> list[ServerReadModel]:
        filters = ServerFilters(
            status=query.status,
            group_id=query.group_id,
            name_search=query.name_search,
            minecraft_version=query.minecraft_version,
        )
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            servers = await repo.list(filters)
            if query.allowed_server_ids is not None:
                allowed = set(query.allowed_server_ids)
                servers = [s for s in servers if str(s.id) in allowed]
            models = [ServerReadModel.from_domain(s) for s in servers]
            if not models:
                return models

            server_ids = [m.server_id for m in models]

            # Batch lookup of active exposure public addresses (zero N+1)
            public_addresses: dict[str, str] = {}
            with contextlib.suppress(Exception):
                from app.modules.exposure.infrastructure.models import (
                    ServerExposureModel,
                    ServerExposureTargetModel,
                )

                exp_stmt = (
                    select(
                        ServerExposureModel.server_id,
                        ServerExposureTargetModel.service_type,
                        ServerExposureTargetModel.public_address,
                    )
                    .join(
                        ServerExposureTargetModel,
                        ServerExposureTargetModel.exposure_id == ServerExposureModel.id,
                    )
                    .where(
                        ServerExposureModel.server_id.in_(server_ids),
                        ServerExposureModel.branch_name == "main",
                        ServerExposureModel.desired_state == "ENABLED",
                        ServerExposureModel.aggregate_status == "ACTIVE",
                        ServerExposureTargetModel.public_address.is_not(None),
                    )
                )
                exp_rows = (await session.execute(exp_stmt)).all()
                for sid, svc_type, pub_addr in exp_rows:
                    if not pub_addr:
                        continue
                    if sid not in public_addresses or svc_type == "java":
                        public_addresses[sid] = pub_addr

            # Batch lookup of active non-main branch for Advanced servers
            advanced_ids = [m.server_id for m in models if m.mode == "advanced"]
            active_branches: dict[str, str] = {}
            if advanced_ids:
                with contextlib.suppress(Exception):
                    from app.modules.versioning.infrastructure.models import ServerBranchModel

                    br_stmt = select(
                        ServerBranchModel.server_id,
                        ServerBranchModel.name,
                        ServerBranchModel.runtime_status,
                    ).where(
                        ServerBranchModel.server_id.in_(advanced_ids),
                        ServerBranchModel.name != "main",
                        ServerBranchModel.runtime_status.in_(("running", "starting")),
                    )
                    br_rows = (await session.execute(br_stmt)).all()
                    for sid, branch_name, _rt_status in br_rows:
                        if branch_name and sid not in active_branches:
                            active_branches[sid] = branch_name

            for m in models:
                if m.server_id in public_addresses:
                    m.public_address = public_addresses[m.server_id]
                if m.mode == "advanced":
                    m.active_branch = active_branches.get(m.server_id, "main")

            return models
