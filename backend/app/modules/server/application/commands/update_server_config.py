import asyncio
import contextlib
import logging
from typing import Any

from pydantic import Field

from app.core.allowlist import CLASS_D_PANEL_KEYS
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError, ValidationError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.branch_settings import save_branch_scoped_settings
from app.modules.server.application.read_models import is_secret_property_key
from app.modules.server.application.services.jar_service import update_server_properties_key
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    MemoryAllocation,
    ServerMode,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.infrastructure.port_allocator import (
    _collect_reserved_ports,
    async_get_live_docker_published_ports,
    probe_os_port_free,
)

_PROP_KEY_MAP = {
    "port": "server-port",
    "max_players": "max-players",
    "spawn_protection": "spawn-protection",
    "enable_command_block": "enable-command-block",
    "online_mode": "online-mode",
    "whitelist": "white-list",
    "view_distance": "view-distance",
    "simulation_distance": "simulation-distance",
}
_REVERSE_PROP_KEY_MAP = {v: k for k, v in _PROP_KEY_MAP.items()}
_NON_PORT_CLASS_D_KEYS = CLASS_D_PANEL_KEYS - {"server-port"}

logger = logging.getLogger(__name__)


def _is_non_port_class_d_key(file_key: str) -> bool:
    return file_key in _NON_PORT_CLASS_D_KEYS or file_key.startswith("management-server-")


def _parse_valid_port(raw_port: Any) -> int:
    if isinstance(raw_port, bool):
        raise InvalidValueError(
            field="server-port",
            value=raw_port,
            reason="Port must be an integer between 1024 and 65535",
        )
    try:
        port = int(str(raw_port).strip())
    except (TypeError, ValueError) as exc:
        raise InvalidValueError(
            field="server-port",
            value=raw_port,
            reason="Port must be an integer between 1024 and 65535",
        ) from exc
    if port < 1024 or port > 65535:
        raise InvalidValueError(
            field="server-port",
            value=raw_port,
            reason="Port must be between 1024 and 65535",
        )
    return port


async def _validate_and_check_port_available(
    session: Any,
    *,
    server: Server,
    raw_port: Any,
) -> int:
    port = _parse_valid_port(raw_port)
    if port == server.properties.port.value:
        return port

    reserved = await _collect_reserved_ports(
        session,
        exclude_server_id=str(server.id),
        include_docker_ports=False,
    )
    if port in reserved:
        raise ConflictError(f"Port {port} is already in use by another server or branch")

    exclude_containers: set[str] = {f"onx-{server.id}"}
    if server.runtime and server.runtime.external_id:
        exclude_containers.add(server.runtime.external_id)
    live_docker_ports = await async_get_live_docker_published_ports(
        exclude_containers=exclude_containers
    )
    if port in live_docker_ports:
        raise ConflictError(f"Port {port} is already published by a running container")

    if not await asyncio.to_thread(probe_os_port_free, port):
        raise ConflictError(f"Port {port} is already bound on this host")

    return port


class UpdateServerConfigCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str | None = None
    name: str | None = None
    properties: dict[str, Any] = {}
    min_memory_mb: int | None = None
    max_memory_mb: int | None = None
    cpu_cores: int | None = None
    cpu_affinity: str | None = None
    java_args: list[str] | None = None
    startup_timeout_seconds: int | None = None
    update_startup_timeout: bool = False


class UpdateServerConfigHandler(CommandHandler[UpdateServerConfigCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateServerConfigCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        branch_result: dict[str, Any] = {}

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            # Server-wide fields apply across all branches immediately in DB.
            name_changed = False
            if command.name is not None and command.name.strip():
                server.rename(command.name)
                name_changed = True
            if command.update_startup_timeout or command.startup_timeout_seconds is not None:
                server.update_startup_timeout(command.startup_timeout_seconds)

            if server.mode == ServerMode.ADVANCED:
                effective_branch = (command.branch_name or "main").strip() or "main"

                raw_port = None
                if command.properties:
                    if "server-port" in command.properties:
                        raw_port = command.properties.get("server-port")
                    elif "port" in command.properties:
                        raw_port = command.properties.get("port")

                if raw_port is not None:
                    requested_port = _parse_valid_port(raw_port)
                    if requested_port != server.properties.port.value:
                        if effective_branch != "main":
                            raise ValidationError(
                                "Host game port is server-wide and cannot be changed on a "
                                "working branch. Working branches automatically allocate "
                                "isolated test ports.",
                                field="server-port",
                            )
                        validated_port = await _validate_and_check_port_available(
                            uow.session, server=server, raw_port=requested_port
                        )
                        server.update_properties(port=validated_port)
                        if server.runtime:
                            server.runtime.port = validated_port
                        if (
                            server.deployment
                            and server.deployment.root_path
                            and server.status not in (ServerStatus.RUNNING, ServerStatus.STARTING)
                        ):
                            with contextlib.suppress(Exception):
                                update_server_properties_key(
                                    server.deployment.properties_path(),
                                    "server-port",
                                    str(validated_port),
                                )

                branch_props: dict[str, Any] = {}
                for k, v in (command.properties or {}).items():
                    file_key = _PROP_KEY_MAP.get(k, k.replace("_", "-"))
                    if (
                        file_key in ("server-port", "server-name")
                        or is_secret_property_key(file_key)
                        or _is_non_port_class_d_key(file_key)
                    ):
                        continue
                    branch_props[k] = v

                has_branch_scoped_changes = bool(
                    branch_props
                    or command.min_memory_mb is not None
                    or command.max_memory_mb is not None
                    or command.cpu_cores is not None
                    or command.cpu_affinity is not None
                    or command.java_args is not None
                )
                if has_branch_scoped_changes:
                    branch_result = await save_branch_scoped_settings(
                        session=uow.session,
                        server=server,
                        branch_name=effective_branch,
                        properties=branch_props or None,
                        min_memory_mb=command.min_memory_mb,
                        max_memory_mb=command.max_memory_mb,
                        cpu_cores=command.cpu_cores,
                        cpu_affinity=command.cpu_affinity,
                        java_args=command.java_args,
                        event_bus=self._event_bus,
                    )
                    for ev in branch_result.get("events", []):
                        uow.add_event(ev)
            else:
                filtered_props: dict[str, Any] = {}
                if command.properties:
                    pname = (
                        command.properties.get("server-name")
                        or command.properties.get("server_name")
                        or command.properties.get("name")
                    )
                    if isinstance(pname, str) and pname.strip() and not name_changed:
                        server.rename(pname)
                        name_changed = True

                    for k, v in command.properties.items():
                        file_key = _PROP_KEY_MAP.get(k, k.replace("_", "-"))
                        if is_secret_property_key(file_key) or _is_non_port_class_d_key(file_key):
                            logger.warning(
                                "Dropped attempt to write protected property key '%s' "
                                "for server %s",
                                file_key,
                                command.server_id,
                            )
                            continue
                        filtered_props[k] = v

                raw_port = None
                if "server-port" in filtered_props:
                    raw_port = filtered_props.get("server-port")
                elif "port" in filtered_props:
                    raw_port = filtered_props.get("port")

                validated_simple_port: int | None = None
                if raw_port is not None:
                    validated_simple_port = await _validate_and_check_port_available(
                        uow.session, server=server, raw_port=raw_port
                    )
                    if "server-port" in filtered_props:
                        filtered_props["server-port"] = validated_simple_port
                    if "port" in filtered_props:
                        filtered_props["port"] = validated_simple_port

                if filtered_props:
                    domain_props: dict[str, Any] = {}
                    for k, v in filtered_props.items():
                        domain_key = _REVERSE_PROP_KEY_MAP.get(k, k.replace("-", "_"))
                        domain_props[domain_key] = v
                    server.update_properties(**domain_props)
                    if validated_simple_port is not None and server.runtime:
                        server.runtime.port = validated_simple_port
                if command.min_memory_mb is not None or command.max_memory_mb is not None:
                    min_mb = command.min_memory_mb or server.memory.min_mb
                    max_mb = command.max_memory_mb or server.memory.max_mb
                    server.update_memory(MemoryAllocation(min_mb=min_mb, max_mb=max_mb))
                if command.cpu_cores is not None or command.cpu_affinity is not None:
                    cores = (
                        command.cpu_cores
                        if command.cpu_cores is not None
                        else server.cpu.cores
                    )
                    affinity = (
                        command.cpu_affinity
                        if command.cpu_affinity is not None
                        else server.cpu.affinity
                    )
                    server.update_cpu(CpuAllocation(cores=cores, affinity=affinity))
                if command.java_args is not None:
                    server.update_java_args(JavaArguments(command.java_args))

                if server.deployment and server.deployment.root_path:
                    props_path = server.deployment.properties_path()
                    try:
                        if name_changed:
                            update_server_properties_key(props_path, "server-name", server.name)
                        if filtered_props:
                            for k, v in filtered_props.items():
                                file_key = _PROP_KEY_MAP.get(k, k.replace("_", "-"))
                                if file_key != "server-name":
                                    str_val = str(v).lower() if isinstance(v, bool) else str(v)
                                    update_server_properties_key(props_path, file_key, str_val)
                    except Exception:
                        pass

            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        data: dict[str, Any] = {"server_id": command.server_id}
        if branch_result:
            data["branch_name"] = branch_result.get("target_branch")
            data["commit_id"] = branch_result.get("commit_id")
            if branch_result.get("pending_settings_branch") is not None:
                data["pending_settings_branch"] = branch_result["pending_settings_branch"]
        return CommandResult(success=True, data=data)
