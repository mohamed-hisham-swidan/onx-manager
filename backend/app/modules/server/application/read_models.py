from __future__ import annotations

import base64
import contextlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import ServerDeployment

_SERVER_NAME_RE = re.compile(r"^\s*server-name\s*=\s*(.*?)\s*$")
_MAX_ICON_BYTES = 128 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_ICON_CACHE_ENTRIES = 256
_ICON_DATA_URL_CACHE: dict[tuple[str, int, int], str] = {}


def _read_server_icon_data_url(deployment: ServerDeployment | None) -> str | None:
    """Safely read and base64-encode ``server-icon.png`` with mtime caching."""
    if deployment is None or not deployment.root_path:
        return None
    raw_dir = deployment.server_directory()
    if not raw_dir:
        return None
    try:
        base_dir = Path(raw_dir).resolve()
        icon_candidate = base_dir / "server-icon.png"
        if not icon_candidate.exists():
            return None
        resolved_icon = icon_candidate.resolve(strict=True)
        if not resolved_icon.is_relative_to(base_dir) or not resolved_icon.is_file():
            return None
        st = resolved_icon.stat()
    except OSError:
        return None

    if st.st_size <= 0 or st.st_size > _MAX_ICON_BYTES:
        return None

    cache_key = (str(resolved_icon), st.st_mtime_ns, st.st_size)
    cached = _ICON_DATA_URL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        raw_bytes = resolved_icon.read_bytes()
    except OSError:
        return None

    if len(raw_bytes) > _MAX_ICON_BYTES or not raw_bytes.startswith(_PNG_SIGNATURE):
        return None

    encoded = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"
    if len(_ICON_DATA_URL_CACHE) >= _MAX_ICON_CACHE_ENTRIES:
        oldest_key = next(iter(_ICON_DATA_URL_CACHE))
        _ICON_DATA_URL_CACHE.pop(oldest_key, None)
    _ICON_DATA_URL_CACHE[cache_key] = data_url
    return data_url


def _resolve_uptime_seconds(server: Server) -> int | None:
    """Return live uptime in seconds when server is running, otherwise None."""
    if server.status != ServerStatus.RUNNING:
        return None

    with contextlib.suppress(Exception):
        from app.modules.server.application.supervisor import RuntimeSupervisor

        supervisor = RuntimeSupervisor.get_for(str(server.id))
        if supervisor is not None and supervisor.is_running:
            return max(0, int(supervisor.uptime))

    rt = server.runtime
    if rt is None:
        return None
    if rt.running_start_time is not None:
        return max(0, int(time.time() - rt.running_start_time))
    if rt.start_time is not None:
        return max(0, int(time.time() - rt.start_time))
    if rt.uptime_seconds and rt.uptime_seconds > 0:
        return max(0, int(rt.uptime_seconds))
    return 0


def resolve_display_name(server: Server) -> str:
    """Resolve the server display name, prioritizing the authoritative DB name.

    SQLite ``server.name`` is the source of truth so renames apply cleanly across
    Simple and Advanced modes. Falls back to ``server-name=`` in on-disk
    ``server.properties`` only when ``server.name`` is empty.
    """
    if server.name and server.name.strip():
        return server.name

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


_SECRET_KEY_STEMS: tuple[str, ...] = ("password", "secret", "token", "apikey")
_DELIM_RE = re.compile(r"[._\-]")


def _normalize_property_key(key: str) -> str:
    """Lowercase, strip all . _ - delimiters: 'rcon.password' -> 'rconpassword'."""
    return _DELIM_RE.sub("", key.strip().lower())


def is_secret_property_key(key: str) -> bool:
    """Canonical secret test. No second regex, no bare 'key' suffix."""
    norm = _normalize_property_key(key)
    return norm in _SECRET_KEY_STEMS or norm.endswith(_SECRET_KEY_STEMS)


def _read_raw_properties(deployment: ServerDeployment | None) -> dict[str, str]:
    if deployment is None or not deployment.root_path:
        return {}
    from app.modules.server.infrastructure.fs import local_fs

    props_path = deployment.properties_path()
    try:
        if not local_fs.exists(props_path):
            return {}
        result: dict[str, str] = {}
        for line in local_fs.read_text(props_path).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            clean_key = key.strip()
            if is_secret_property_key(clean_key):
                continue
            result[clean_key] = value.strip()
        return result
    except (OSError, PermissionError):
        return {}


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
        startup_timeout_seconds: int | None = None,
        mode: str = "simple",
        branch_name: str | None = None,
        pending_settings_branch: dict | None = None,
        max_memory_mb: int | None = None,
        cpu_cores: float | None = None,
        uptime_seconds: int | None = None,
        deployment_host: str | None = None,
        public_address: str | None = None,
        active_branch: str | None = None,
        icon_data_url: str | None = None,
        provisioning_progress: dict[str, Any] | None = None,
    ) -> None:
        self.server_id = server_id
        self.name = name
        self.mode = mode
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
        self.startup_timeout_seconds = startup_timeout_seconds
        self.branch_name = branch_name
        self.pending_settings_branch = pending_settings_branch
        self.max_memory_mb = max_memory_mb
        self.cpu_cores = cpu_cores
        self.uptime_seconds = uptime_seconds
        self.deployment_host = deployment_host
        self.public_address = public_address
        self.active_branch = active_branch
        self.icon_data_url = icon_data_url
        self.provisioning_progress = provisioning_progress

    @classmethod
    def from_domain(cls, server: Server) -> ServerReadModel:
        from app.modules.server.application.services.provisioning_telemetry import (
            ProvisioningTelemetryStore,
        )

        rt = server.runtime
        cpu_cores = (
            float(server.cpu.cores)
            if (server.cpu is not None and server.cpu.cores > 0)
            else None
        )
        deployment_host = (rt.host or None) if rt else None
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
            startup_timeout_seconds=server.startup_timeout_seconds,
            mode=server.mode.value,
            max_memory_mb=server.memory.max_mb if server.memory else None,
            cpu_cores=cpu_cores,
            uptime_seconds=_resolve_uptime_seconds(server),
            deployment_host=deployment_host,
            icon_data_url=_read_server_icon_data_url(server.deployment),
            provisioning_progress=ProvisioningTelemetryStore.get_snapshot(str(server.id)),
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
        cpu_cores: int = 0,
        cpu_affinity: str = "",
        raw_properties: dict[str, str] | None = None,
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
        startup_timeout_seconds: int | None = None,
        mode: str = "simple",
        branch_name: str | None = None,
        pending_settings_branch: dict | None = None,
        uptime_seconds: int | None = None,
        public_address: str | None = None,
        active_branch: str | None = None,
        icon_data_url: str | None = None,
        provisioning_progress: dict[str, Any] | None = None,
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
            startup_timeout_seconds=startup_timeout_seconds,
            mode=mode,
            branch_name=branch_name,
            pending_settings_branch=pending_settings_branch,
            max_memory_mb=max_memory_mb,
            cpu_cores=cpu_cores,
            uptime_seconds=uptime_seconds,
            deployment_host=deployment_host,
            public_address=public_address,
            active_branch=active_branch,
            icon_data_url=icon_data_url,
            provisioning_progress=provisioning_progress,
        )
        self.min_memory_mb = min_memory_mb
        self.max_memory_mb = max_memory_mb
        self.java_args = java_args
        self.cpu_cores = cpu_cores
        self.cpu_affinity = cpu_affinity
        self.raw_properties = raw_properties or {}
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
        self.branch_name = branch_name
        self.pending_settings_branch = pending_settings_branch

    @classmethod
    def from_domain(cls, server: Server) -> ServerDetailReadModel:
        from app.modules.server.application.services.provisioning_telemetry import (
            ProvisioningTelemetryStore,
        )

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
            cpu_cores=server.cpu.cores,
            cpu_affinity=server.cpu.affinity,
            raw_properties=_read_raw_properties(dep),
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
            startup_timeout_seconds=server.startup_timeout_seconds,
            mode=server.mode.value,
            uptime_seconds=_resolve_uptime_seconds(server),
            icon_data_url=_read_server_icon_data_url(server.deployment),
            provisioning_progress=ProvisioningTelemetryStore.get_snapshot(str(server.id)),
        )
