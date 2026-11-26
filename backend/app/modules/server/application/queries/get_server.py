import contextlib

from sqlalchemy import select

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.branch_settings import read_branch_settings_overlay
from app.modules.server.application.read_models import ServerDetailReadModel
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import ServerHandle, provider_factory
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


class GetServerQuery(Query):
    server_id: str
    branch_name: str | None = None


class GetServerHandler(QueryHandler[GetServerQuery]):
    async def handle(self, query: GetServerQuery) -> ServerDetailReadModel | None:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))
            if not server:
                return None
            if server.status == ServerStatus.RUNNING and server.runtime:
                try:
                    provider = provider_factory.get(server.runtime.provider)
                    handle = ServerHandle(
                        provider=server.runtime.provider,
                        server_id=str(server.id),
                        external_id=server.runtime.external_id or f"onx-{server.id}",
                    )
                    live_addr = await provider.get_address(handle)
                    if live_addr and live_addr != server.runtime.host:
                        server.runtime.host = live_addr
                        await repo.save(server)
                        await session.commit()
                except Exception:
                    pass
            detail = ServerDetailReadModel.from_domain(server)
            overlay = await read_branch_settings_overlay(session, server, query.branch_name)
            for key, value in overlay.items():
                setattr(detail, key, value)

            # Enrich with active exposure public_address (parity with ListServersHandler)
            target_branch = query.branch_name or "main"
            with contextlib.suppress(Exception):
                from app.modules.exposure.infrastructure.models import (
                    ServerExposureModel,
                    ServerExposureTargetModel,
                )

                exp_stmt = (
                    select(
                        ServerExposureTargetModel.service_type,
                        ServerExposureTargetModel.public_address,
                    )
                    .join(
                        ServerExposureTargetModel,
                        ServerExposureTargetModel.exposure_id == ServerExposureModel.id,
                    )
                    .where(
                        ServerExposureModel.server_id == detail.server_id,
                        ServerExposureModel.branch_name == target_branch,
                        ServerExposureModel.desired_state == "ENABLED",
                        ServerExposureModel.aggregate_status == "ACTIVE",
                        ServerExposureTargetModel.public_address.is_not(None),
                    )
                )
                exp_rows = (await session.execute(exp_stmt)).all()
                public_address: str | None = None
                for svc_type, pub_addr in exp_rows:
                    if not pub_addr:
                        continue
                    if public_address is None or svc_type == "java":
                        public_address = pub_addr
                if public_address:
                    detail.public_address = public_address

            # Enrich with active_branch for Advanced servers (parity with ListServersHandler)
            if detail.mode == "advanced":
                active_branch = "main"
                with contextlib.suppress(Exception):
                    from app.modules.versioning.infrastructure.models import ServerBranchModel

                    br_stmt = select(ServerBranchModel.name).where(
                        ServerBranchModel.server_id == detail.server_id,
                        ServerBranchModel.name != "main",
                        ServerBranchModel.runtime_status.in_(("running", "starting")),
                    )
                    br_rows = (await session.execute(br_stmt)).all()
                    for (branch_name,) in br_rows:
                        if branch_name:
                            active_branch = branch_name
                            break
                detail.active_branch = active_branch

            return detail

