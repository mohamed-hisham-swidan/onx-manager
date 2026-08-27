from __future__ import annotations

import re
from datetime import datetime

from app.modules.server.domain.aggregate import Server

_SERVER_NAME_RE = re.compile(r"^\s*server-name\s*=\s*(.*?)\s*$")


def resolve_display_name(server: Server) -> str:
    """Resolve the server display name from the on-disk server.properties.

    server.properties is the source of truth for the server name. When the
    deployment root is known and the file declares a non-empty ``server-name``,
    that value wins; otherwise the manager DB name is used as the fallback.
    """
    deployment = server.deployment
    if deployment is None or not deployment.root_path:
        return server.name

    from app.modules.server.infrastructure.fs import local_fs

    props_path = deployment.properties_path()
    try:
        if not local_fs.exists(props_path):
            return server.name
        for line in local_fs.read_text(props_path).splitlines():
            m = _SERVER_NAME_RE.match(line)
            if m:
                value = m.group(1).strip()
                if value:
                    return value
    except (OSError, PermissionError):
        pass
    return server.name


class ServerReadModel:
    def __init__(
        self,
        server_id: str,
        name: str,
        server_type: str,
        minecraft_version: str,
        status: str,
        group_id: str,
        port: int,
        motd: str,
        max_players: int,
        gamemode: str,
        difficulty: str,
        created_at: datetime,
        updated_at: datetime,
        provisioning_error: str | None = None,
        provisioning_retryable: bool = False,
    ) -> None:
        self.server_id = server_id
        self.name = name
        self.server_type = server_type
        self.minecraft_version = minecraft_version
        self.status = status
        self.group_id = group_id
        self.port = port
        self.motd = motd
        self.max_players = max_players
        self.gamemode = gamemode
        self.difficulty = difficulty
        self.created_at = created_at
        self.updated_at = updated_at
        self.provisioning_error = provisioning_error
        self.provisioning_retryable = provisioning_retryable

    @classmethod
    def from_domain(cls, server: Server) -> ServerReadModel:
        return cls(
            server_id=str(server.id),
            name=resolve_display_name(server),
            server_type=server.server_type.value,
            minecraft_version=str(server.minecraft_version),
            status=server.status.value,
            group_id=server.group_id,
            port=server.properties.port.value,
            motd=server.properties.motd,
            max_players=server.properties.max_players,
            gamemode=server.properties.gamemode,
            difficulty=server.properties.difficulty,
            created_at=server.created_at,
            updated_at=server.updated_at,
            provisioning_error=server.provisioning_error,
            provisioning_retryable=server.provisioning_retryable,
        )


class ServerDetailReadModel(ServerReadModel):
    def __init__(
        self,
        server_id: str,
        name: str,
        server_type: str,
        minecraft_version: str,
        status: str,
        group_id: str,
        port: int,
        motd: str,
        max_players: int,
        gamemode: str,
        difficulty: str,
        created_at: datetime,
        updated_at: datetime,
        min_memory_mb: int,
        max_memory_mb: int,
        java_args: str,
        spawn_protection: int,
        pvp: bool,
        enable_command_block: bool,
        online_mode: bool,
        whitelist: bool,
        view_distance: int,
        simulation_distance: int,
        provider: str | None = None,
        deployment_host: str | None = None,
        deployment_port: int | None = None,
        deployment_pid: int | None = None,
        location_type: str | None = None,
        location_uri: str | None = None,
        root_path: str | None = None,
        working_directory: str | None = None,
        startup_jar: str | None = None,
        startup_command: str | None = None,
        primary_world: str | None = None,
        provisioning_error: str | None = None,
        provisioning_retryable: bool = False,
    ) -> None:
        super().__init__(
            server_id=server_id,
            name=name,
            server_type=server_type,
            minecraft_version=minecraft_version,
            status=status,
            group_id=group_id,
            port=port,
            motd=motd,
            max_players=max_players,
            gamemode=gamemode,
            difficulty=difficulty,
            created_at=created_at,
            updated_at=updated_at,
            provisioning_error=provisioning_error,
            provisioning_retryable=provisioning_retryable,
        )
        self.min_memory_mb = min_memory_mb
        self.max_memory_mb = max_memory_mb
        self.java_args = java_args
        self.spawn_protection = spawn_protection
        self.pvp = pvp
        self.enable_command_block = enable_command_block
        self.online_mode = online_mode
        self.whitelist = whitelist
        self.view_distance = view_distance
        self.simulation_distance = simulation_distance
        self.provider = provider
        self.deployment_host = deployment_host
        self.deployment_port = deployment_port
        self.deployment_pid = deployment_pid
        self.location_type = location_type
        self.location_uri = location_uri
        self.root_path = root_path
        self.working_directory = working_directory
        self.startup_jar = startup_jar
        self.startup_command = startup_command
        self.primary_world = primary_world

    @classmethod
    def from_domain(cls, server: Server) -> ServerDetailReadModel:
        dep = server.deployment
        rt = server.runtime
        return cls(
            server_id=str(server.id),
            name=resolve_display_name(server),
            server_type=server.server_type.value,
            minecraft_version=str(server.minecraft_version),
            status=server.status.value,
            group_id=server.group_id,
            port=server.properties.port.value,
            motd=server.properties.motd,
            max_players=server.properties.max_players,
            gamemode=server.properties.gamemode,
            difficulty=server.properties.difficulty,
            created_at=server.created_at,
            updated_at=server.updated_at,
            min_memory_mb=server.memory.min_mb,
            max_memory_mb=server.memory.max_mb,
            java_args=str(server.java_args),
            spawn_protection=server.properties.spawn_protection,
            pvp=server.properties.pvp,
            enable_command_block=server.properties.enable_command_block,
            online_mode=server.properties.online_mode,
            whitelist=server.properties.whitelist,
            view_distance=server.properties.view_distance,
            simulation_distance=server.properties.simulation_distance,
            provider=rt.provider if rt else None,
            deployment_host=rt.host if rt else None,
            deployment_port=rt.port if rt else None,
            deployment_pid=rt.pid if rt else None,
            location_type=dep.location_type.value if dep else None,
            location_uri=dep.location_uri if dep else None,
            root_path=dep.root_path if dep else None,
            working_directory=dep.working_directory if dep else None,
            startup_jar=dep.startup_jar if dep else None,
            startup_command=dep.startup_command if dep else None,
            primary_world=dep.primary_world if dep else None,
            provisioning_error=server.provisioning_error,
            provisioning_retryable=server.provisioning_retryable,
        )
