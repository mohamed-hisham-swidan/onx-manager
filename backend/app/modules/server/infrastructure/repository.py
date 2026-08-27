from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerFilters, ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LaunchConfiguration,
    LocationType,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.modules.shared.value_objects import MinecraftVersion, ServerId


class SQLServerRepository(ServerRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: ServerId) -> Server:
        model = await self._session.get(ServerModel, str(id))
        if model is None:
            from app.core.exceptions import ServerNotFoundError

            raise ServerNotFoundError(str(id))
        return self._model_to_domain(model)

    async def list(self, filters: ServerFilters | None = None) -> list[Server]:
        stmt = select(ServerModel)
        if filters:
            if filters.status:
                stmt = stmt.where(ServerModel.status == filters.status)
            if filters.group_id:
                stmt = stmt.where(ServerModel.group_id == filters.group_id)
            if filters.name_search:
                stmt = stmt.where(ServerModel.name.ilike(f"%{filters.name_search}%"))
            if filters.minecraft_version:
                stmt = stmt.where(ServerModel.minecraft_version == filters.minecraft_version)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_domain(m) for m in models]

    async def save(self, server: Server) -> None:
        model = await self._session.get(ServerModel, str(server.id))
        if model is None:
            model = ServerModel(id=str(server.id))
            self._session.add(model)

        model.name = server.name
        model.server_type = server.server_type.value
        model.minecraft_version = str(server.minecraft_version)
        model.memory_min_mb = server.memory.min_mb
        model.memory_max_mb = server.memory.max_mb
        model.java_args = " ".join(server.java_args.args)
        model.group_id = server.group_id
        model.status = server.status.value
        model.port = server.properties.port.value
        model.motd = server.properties.motd
        model.max_players = server.properties.max_players
        model.gamemode = server.properties.gamemode
        model.difficulty = server.properties.difficulty
        model.spawn_protection = server.properties.spawn_protection
        model.pvp = server.properties.pvp
        model.enable_command_block = server.properties.enable_command_block
        model.online_mode = server.properties.online_mode
        model.whitelist_enabled = server.properties.whitelist
        model.view_distance = server.properties.view_distance
        model.simulation_distance = server.properties.simulation_distance

        model.provider = server.runtime.provider if server.runtime else "local"
        model.deployment_host = server.runtime.host if server.runtime else None
        model.deployment_port = server.runtime.port if server.runtime else None
        model.deployment_pid = server.runtime.pid if server.runtime else None
        model.deployment_start_time = server.runtime.start_time if server.runtime else None
        model.external_id = server.runtime.external_id if server.runtime else None

        if server.deployment:
            model.location_type = server.deployment.location_type.value
            model.location_uri = server.deployment.location_uri or None
            model.root_path = server.deployment.root_path or None
            model.working_directory = server.deployment.working_directory or "."
            model.startup_jar = server.deployment.startup_jar or "server.jar"
            model.startup_command = server.deployment.startup_command or ""
            model.primary_world = server.deployment.primary_world or "world"

        if server.runtime:
            model.uptime_seconds = server.runtime.uptime_seconds
            model.last_crash_time = server.runtime.last_crash_time
            model.restart_count = server.runtime.restart_count

        if server.launch_config is not None:
            model.launch_config_json = json.dumps(asdict(server.launch_config))
        else:
            model.launch_config_json = None

        model.missing_since = server.missing_since
        model.owner_id = server.owner_id
        model.provisioning_error = server.provisioning_error
        model.provisioning_retryable = server.provisioning_retryable

        await self._session.flush()

    async def delete(self, id: ServerId) -> None:
        model = await self._session.get(ServerModel, str(id))
        if model:
            await self._session.delete(model)
            await self._session.flush()

    def _model_to_domain(self, model: ServerModel) -> Server:
        memory = MemoryAllocation(
            min_mb=model.memory_min_mb,
            max_mb=model.memory_max_mb,
        )
        java_args_list = model.java_args.split() if model.java_args else []
        java_args = JavaArguments(java_args_list)

        deployment: ServerDeployment | None = None
        if model.root_path:
            deployment = ServerDeployment(
                location_type=LocationType(model.location_type or "local"),
                location_uri=model.location_uri or "",
                root_path=model.root_path,
                working_directory=model.working_directory or ".",
                startup_jar=model.startup_jar or "server.jar",
                startup_command=model.startup_command or "",
                primary_world=model.primary_world or "world",
            )

        runtime = RuntimeInfo(
            status=model.status or "created",
            provider=model.provider or "local",
            host=model.deployment_host or "",
            port=model.deployment_port or model.port or 25565,
            pid=model.deployment_pid,
            start_time=model.deployment_start_time,
            uptime_seconds=model.uptime_seconds or 0.0,
            last_crash_time=model.last_crash_time,
            restart_count=model.restart_count or 0,
            external_id=model.external_id or "",
        )

        launch_config: LaunchConfiguration | None = None
        if model.launch_config_json:
            try:
                raw = json.loads(model.launch_config_json)
                launch_config = LaunchConfiguration(
                    java_executable=raw.get("java_executable", "java"),
                    startup_command=raw.get("startup_command", ""),
                    startup_jar=raw.get("startup_jar", "server.jar"),
                    jvm_flags=tuple(raw.get("jvm_flags", [])),
                    environment=raw.get("environment", {}),
                    working_directory=raw.get("working_directory", ""),
                )
            except (json.JSONDecodeError, TypeError, KeyError):
                launch_config = None

        server = Server(
            server_id=ServerId(model.id),
            name=model.name,
            server_type=ServerType(model.server_type or "vanilla"),
            minecraft_version=MinecraftVersion.parse(model.minecraft_version),
            memory=memory,
            java_args=java_args,
            properties=ServerProperties(
                port=PortNumber(model.port),
                motd=model.motd,
                max_players=model.max_players,
                gamemode=model.gamemode,
                difficulty=model.difficulty,
                spawn_protection=model.spawn_protection,
                pvp=model.pvp,
                enable_command_block=model.enable_command_block,
                online_mode=model.online_mode,
                whitelist=model.whitelist_enabled,
                view_distance=model.view_distance,
                simulation_distance=model.simulation_distance,
            ),
            group_id=model.group_id,
            deployment=deployment,
            runtime=runtime,
            launch_config=launch_config,
            created_at=model.created_at,
            updated_at=model.updated_at,
            missing_since=model.missing_since,
            owner_id=model.owner_id,
            provisioning_error=model.provisioning_error,
            provisioning_retryable=bool(model.provisioning_retryable),
        )

        from app.modules.server.domain.aggregate import ServerStatus

        status_map: dict[str, Any] = {s.value: s for s in ServerStatus}
        server._status = status_map.get(model.status, ServerStatus.CREATED)

        return server


class SQLServerMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_membership(
        self, id: str, server_id: str, user_id: str, role: str
    ) -> ServerMembershipModel:
        model = ServerMembershipModel(
            id=id,
            server_id=server_id,
            user_id=user_id,
            role=role,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_membership(self, server_id: str, user_id: str) -> ServerMembershipModel | None:
        stmt = select(ServerMembershipModel).where(
            ServerMembershipModel.server_id == server_id,
            ServerMembershipModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_memberships_for_server(self, server_id: str) -> list[ServerMembershipModel]:
        stmt = select(ServerMembershipModel).where(ServerMembershipModel.server_id == server_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_memberships_for_user(self, user_id: str) -> list[ServerMembershipModel]:
        stmt = select(ServerMembershipModel).where(ServerMembershipModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def remove_membership(self, server_id: str, user_id: str) -> bool:
        membership = await self.get_membership(server_id, user_id)
        if membership is None:
            return False
        await self._session.delete(membership)
        await self._session.flush()
        return True

    async def update_membership_role(
        self, server_id: str, user_id: str, role: str
    ) -> ServerMembershipModel | None:
        membership = await self.get_membership(server_id, user_id)
        if membership is None:
            return None
        membership.role = role
        await self._session.flush()
        return membership
