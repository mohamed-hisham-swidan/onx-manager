from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exposure.domain.aggregate import (
    HostPlayitAgent,
    PanelExposure,
    ServerExposure,
    ServerExposureTarget,
)
from app.modules.exposure.domain.repository import (
    ExposureGrantRepository,
    HostAgentRepository,
    PanelExposureRepository,
    ServerExposureRepository,
)
from app.modules.exposure.domain.value_objects import (
    AgentProcessStatus,
    DesiredState,
    ExposureMethod,
    ExposureStatus,
    PanelExposureMethod,
    ServiceType,
    TargetProtocol,
)
from app.modules.exposure.infrastructure.models import (
    HostPlayitAgentModel,
    PanelExposureModel,
    ServerExposureGrantModel,
    ServerExposureModel,
    ServerExposureTargetModel,
    ServerRegisteredPortModel,
)


def _new_id() -> str:
    return uuid.uuid4().hex


class SQLHostAgentRepository(HostAgentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: str = "default") -> HostPlayitAgent:
        model = await self._session.get(HostPlayitAgentModel, id)
        if model is None:
            return HostPlayitAgent(id=id)
        return self._model_to_domain(model)

    async def save(self, agent: HostPlayitAgent) -> None:
        model = await self._session.get(HostPlayitAgentModel, agent.id)
        if model is None:
            model = HostPlayitAgentModel(id=agent.id)
            self._session.add(model)
        model.secret_ciphertext = agent.secret_ciphertext
        model.claim_code = agent.claim_code
        model.claim_expires_at = agent.claim_expires_at
        model.process_status = agent.process_status.value
        model.last_health_at = agent.last_health_at
        model.desired_agent_running = agent.desired_agent_running
        await self._session.flush()

    def _model_to_domain(self, model: HostPlayitAgentModel) -> HostPlayitAgent:
        return HostPlayitAgent(
            id=model.id,
            secret_ciphertext=model.secret_ciphertext,
            claim_code=model.claim_code,
            claim_expires_at=model.claim_expires_at,
            process_status=model.process_status or AgentProcessStatus.STOPPED.value,
            last_health_at=model.last_health_at,
            desired_agent_running=model.desired_agent_running,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SQLServerExposureRepository(ServerExposureRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, server_id: str) -> ServerExposure | None:
        stmt = select(ServerExposureModel).where(ServerExposureModel.server_id == server_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return await self._model_to_domain(model)

    async def get_by_id(self, exposure_id: str) -> ServerExposure | None:
        model = await self._session.get(ServerExposureModel, exposure_id)
        if model is None:
            return None
        return await self._model_to_domain(model)

    async def list(self) -> list[ServerExposure]:
        result = await self._session.execute(select(ServerExposureModel))
        return [await self._model_to_domain(m) for m in result.scalars().all()]

    async def list_playit_enabled(self) -> list[ServerExposure]:
        stmt = select(ServerExposureModel).where(
            ServerExposureModel.method == ExposureMethod.PLAYIT.value,
            ServerExposureModel.desired_state == DesiredState.ENABLED.value,
        )
        result = await self._session.execute(stmt)
        return [await self._model_to_domain(m) for m in result.scalars().all()]

    async def save(self, exposure: ServerExposure) -> None:
        model = None
        if exposure.id:
            model = await self._session.get(ServerExposureModel, exposure.id)
        if model is None:
            model = ServerExposureModel(
                id=exposure.id or _new_id(),
                server_id=exposure.server_id,
            )
            if exposure.id is None:
                exposure._id = model.id  # type: ignore[attr-defined]
            self._session.add(model)

        model.server_id = exposure.server_id
        model.method = exposure.method.value
        model.desired_state = exposure.desired_state.value
        model.aggregate_status = exposure.aggregate_status.value
        model.cloudflare_tunnel_id = exposure.cloudflare_tunnel_id
        model.cloudflare_token_ciphertext = exposure.cloudflare_token_ciphertext
        await self._session.flush()

        current_target_ids = {target.id for target in exposure.targets if target.id}
        stmt = select(ServerExposureTargetModel).where(
            ServerExposureTargetModel.exposure_id == model.id
        )
        existing_targets_res = await self._session.execute(stmt)
        for existing_tm in existing_targets_res.scalars().all():
            if existing_tm.id not in current_target_ids:
                await self._session.delete(existing_tm)

        for target in exposure.targets:
            target_model = None
            if target.id:
                target_model = await self._session.get(ServerExposureTargetModel, target.id)
            if target_model is None:
                target_model = ServerExposureTargetModel(
                    id=target.id or _new_id(),
                    exposure_id=model.id,
                )
                if target.id is None:
                    target._id = target_model.id  # type: ignore[attr-defined]
                self._session.add(target_model)
            target_model.service_type = target.service_type.value
            target_model.protocol = target.protocol.value
            target_model.local_port = target.local_port
            target_model.public_address = target.public_address
            target_model.status = target.status.value
            target_model.error_code = target.error_code
            target_model.error_message = target.error_message

        await self._session.flush()

    async def delete(self, exposure: ServerExposure) -> None:
        if exposure.id:
            model = await self._session.get(ServerExposureModel, exposure.id)
            if model:
                await self._session.delete(model)
                await self._session.flush()

    async def set_all_disabled(self) -> int:
        result = await self._session.execute(
            update(ServerExposureModel)
            .where(ServerExposureModel.desired_state == DesiredState.ENABLED.value)
            .values(desired_state=DesiredState.DISABLED.value)
        )
        return result.rowcount or 0

    async def _model_to_domain(self, model: ServerExposureModel) -> ServerExposure:
        target_stmt = select(ServerExposureTargetModel).where(
            ServerExposureTargetModel.exposure_id == model.id
        )
        target_result = await self._session.execute(target_stmt)
        targets = [
            ServerExposureTarget(
                id=t.id,
                exposure_id=t.exposure_id,
                protocol=t.protocol or TargetProtocol.TCP.value,
                service_type=t.service_type or ServiceType.JAVA.value,
                local_port=t.local_port,
                public_address=t.public_address,
                status=t.status or ExposureStatus.DISABLED.value,
                error_code=t.error_code,
                error_message=t.error_message,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in target_result.scalars().all()
        ]
        return ServerExposure(
            id=model.id,
            server_id=model.server_id,
            method=model.method or ExposureMethod.PLAYIT.value,
            desired_state=model.desired_state or DesiredState.DISABLED.value,
            aggregate_status=model.aggregate_status or ExposureStatus.DISABLED.value,
            targets=targets,
            cloudflare_tunnel_id=model.cloudflare_tunnel_id,
            cloudflare_token_ciphertext=model.cloudflare_token_ciphertext,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SQLPanelExposureRepository(PanelExposureRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: str = "default") -> PanelExposure:
        model = await self._session.get(PanelExposureModel, id)
        if model is None:
            return PanelExposure(id=id)
        return PanelExposure(
            id=model.id,
            method=model.method or PanelExposureMethod.NONE.value,
            desired_state=model.desired_state or DesiredState.DISABLED.value,
            status=model.status or ExposureStatus.DISABLED.value,
            public_address=model.public_address,
            error_code=model.error_code,
            error_message=model.error_message,
            cloudflare_tunnel_id=model.cloudflare_tunnel_id,
            cloudflare_token_ciphertext=model.cloudflare_token_ciphertext,
            external_port=model.external_port,
            playit_tunnel_id=model.playit_tunnel_id,
            upnp_last_result=model.upnp_last_result,
            upnp_last_mapped_at=model.upnp_last_mapped_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def save(self, panel: PanelExposure) -> None:
        model = await self._session.get(PanelExposureModel, panel.id)
        if model is None:
            model = PanelExposureModel(id=panel.id)
            self._session.add(model)
        model.method = panel.method.value
        model.desired_state = panel.desired_state.value
        model.status = panel.status.value
        model.public_address = panel.public_address
        model.error_code = panel.error_code
        model.error_message = panel.error_message
        model.cloudflare_tunnel_id = panel.cloudflare_tunnel_id
        model.cloudflare_token_ciphertext = panel.cloudflare_token_ciphertext
        model.external_port = panel.external_port
        model.playit_tunnel_id = panel.playit_tunnel_id
        model.upnp_last_result = panel.upnp_last_result
        model.upnp_last_mapped_at = panel.upnp_last_mapped_at
        await self._session.flush()


class SQLExposureGrantRepository(ExposureGrantRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_grant(self, server_id: str, user_id: str) -> ServerExposureGrantModel | None:
        stmt = select(ServerExposureGrantModel).where(
            ServerExposureGrantModel.server_id == server_id,
            ServerExposureGrantModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_grant(
        self,
        server_id: str,
        user_id: str,
        can_manage: bool,
        can_view: bool,
    ) -> ServerExposureGrantModel:
        stmt = select(ServerExposureGrantModel).where(
            ServerExposureGrantModel.server_id == server_id,
            ServerExposureGrantModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            model = ServerExposureGrantModel(
                id=_new_id(),
                server_id=server_id,
                user_id=user_id,
            )
            self._session.add(model)
        model.can_manage = can_manage
        model.can_view = can_view
        await self._session.flush()
        return model

    async def list_grants(self, server_id: str) -> list[ServerExposureGrantModel]:
        stmt = select(ServerExposureGrantModel).where(
            ServerExposureGrantModel.server_id == server_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class SQLServerRegisteredPortRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: str) -> ServerRegisteredPortModel | None:
        return await self._session.get(ServerRegisteredPortModel, id)

    async def list_for_server(self, server_id: str) -> list[ServerRegisteredPortModel]:
        stmt = (
            select(ServerRegisteredPortModel)
            .where(ServerRegisteredPortModel.server_id == server_id)
            .order_by(ServerRegisteredPortModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_service_type(
        self, server_id: str, service_type: str
    ) -> ServerRegisteredPortModel | None:
        stmt = select(ServerRegisteredPortModel).where(
            ServerRegisteredPortModel.server_id == server_id,
            ServerRegisteredPortModel.service_type == service_type,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_port_protocol(
        self, server_id: str, port: int, protocol: str
    ) -> ServerRegisteredPortModel | None:
        stmt = select(ServerRegisteredPortModel).where(
            ServerRegisteredPortModel.server_id == server_id,
            ServerRegisteredPortModel.port == port,
            ServerRegisteredPortModel.protocol == protocol,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, model: ServerRegisteredPortModel) -> None:
        existing = await self._session.get(ServerRegisteredPortModel, model.id)
        if existing is None:
            self._session.add(model)
        await self._session.flush()

    async def delete(self, id: str) -> bool:
        model = await self._session.get(ServerRegisteredPortModel, id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False
