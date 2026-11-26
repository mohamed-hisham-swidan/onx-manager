from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.core.exceptions import InvalidValueError
from app.modules.server.domain.events import (
    ServerConfigChangedEvent,
    ServerCrashedEvent,
    ServerCreatedEvent,
    ServerDeletedEvent,
    ServerStartedEvent,
    ServerStartingEvent,
    ServerStoppedEvent,
    ServerStoppingEvent,
    ServerStopUnknownEvent,
)
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    LaunchConfiguration,
    MemoryAllocation,
    RuntimeInfo,
    ServerDeployment,
    ServerMode,
    ServerProperties,
    ServerType,
    build_server_handle,
    default_provider_for_platform,
)
from app.modules.shared.aggregate import AggregateRoot
from app.modules.shared.value_objects import MinecraftVersion, ServerId


class ServerStatus(Enum):
    CREATED = "created"
    PROVISIONING = "provisioning"
    PROVISIONING_FAILED = "provisioning_failed"
    BROKEN = "broken"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"
    RESTORING = "restoring"


_SERVER_TRANSITIONS: dict[ServerStatus, set[ServerStatus]] = {
    ServerStatus.CREATED: {
        ServerStatus.STARTING,
        ServerStatus.BROKEN,
        ServerStatus.PROVISIONING,
        ServerStatus.RESTORING,
    },
    ServerStatus.PROVISIONING: {
        ServerStatus.CREATED,
        ServerStatus.STARTING,
        ServerStatus.BROKEN,
        ServerStatus.PROVISIONING_FAILED,
    },
    ServerStatus.PROVISIONING_FAILED: {
        ServerStatus.PROVISIONING,
        ServerStatus.CREATED,
        ServerStatus.BROKEN,
    },
    ServerStatus.BROKEN: {ServerStatus.STARTING, ServerStatus.CREATED, ServerStatus.PROVISIONING},
    ServerStatus.STARTING: {
        ServerStatus.RUNNING,
        ServerStatus.CRASHED,
        ServerStatus.STOPPING,
        ServerStatus.STOPPED,
    },
    ServerStatus.RUNNING: {
        ServerStatus.STOPPING,
        ServerStatus.CRASHED,
        ServerStatus.STOPPED,
    },
    ServerStatus.STOPPING: {
        ServerStatus.STOPPED,
        ServerStatus.CRASHED,
        ServerStatus.RUNNING,
    },
    ServerStatus.STOPPED: {
        ServerStatus.STARTING,
        ServerStatus.RUNNING,
        ServerStatus.RESTORING,
    },
    ServerStatus.CRASHED: {
        ServerStatus.STARTING,
        ServerStatus.RUNNING,
        ServerStatus.STOPPED,
        ServerStatus.RESTORING,
    },
    ServerStatus.RESTORING: {ServerStatus.STOPPED, ServerStatus.BROKEN},
}


class Server(AggregateRoot):
    def __init__(
        self,
        server_id: ServerId,
        name: str,
        server_type: ServerType,
        minecraft_version: MinecraftVersion,
        memory: MemoryAllocation,
        java_args: JavaArguments,
        properties: ServerProperties,
        group_id: str = "default",
        deployment: ServerDeployment | None = None,
        runtime: RuntimeInfo | None = None,
        launch_config: LaunchConfiguration | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        missing_since: datetime | None = None,
        owner_id: str | None = None,
        provisioning_error: str | None = None,
        provisioning_retryable: bool = False,
        cpu: CpuAllocation | None = None,
        startup_timeout_seconds: int | None = None,
        mode: ServerMode = ServerMode.SIMPLE,
    ) -> None:
        super().__init__()
        self._id = server_id
        self._name = name
        self._mode = mode
        self._server_type = server_type
        self._minecraft_version = minecraft_version
        self._memory = memory
        self._java_args = java_args
        self._properties = properties
        self._cpu = cpu or CpuAllocation()
        self._group_id = group_id
        self._status = ServerStatus.CREATED
        self._deployment = deployment
        self._runtime = runtime or RuntimeInfo(
            provider=default_provider_for_platform(),
            port=properties.port.value,
        )
        self._launch_config = launch_config
        self._missing_since = missing_since
        self._owner_id = owner_id
        self._provisioning_error = provisioning_error
        self._provisioning_retryable = provisioning_retryable
        self._startup_timeout_seconds = startup_timeout_seconds
        self._has_run = (
            self._runtime.restart_count > 0
            or self._runtime.running_start_time is not None
            or self._runtime.status in ("running", "crashed", "stopping", "stopped")
        )
        now = datetime.now(UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now

    @property
    def id(self) -> ServerId:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> ServerMode:
        return self._mode

    @property
    def server_type(self) -> ServerType:
        return self._server_type

    @property
    def minecraft_version(self) -> MinecraftVersion:
        return self._minecraft_version

    @property
    def memory(self) -> MemoryAllocation:
        return self._memory

    @property
    def cpu(self) -> CpuAllocation:
        return self._cpu

    @property
    def java_args(self) -> JavaArguments:
        return self._java_args

    @property
    def properties(self) -> ServerProperties:
        return self._properties

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def status(self) -> ServerStatus:
        return self._status

    @property
    def deployment(self) -> ServerDeployment | None:
        return self._deployment

    @property
    def runtime(self) -> RuntimeInfo:
        return self._runtime

    @property
    def launch_config(self) -> LaunchConfiguration | None:
        return self._launch_config

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def missing_since(self) -> datetime | None:
        return self._missing_since

    @property
    def owner_id(self) -> str | None:
        return self._owner_id

    @property
    def provisioning_error(self) -> str | None:
        return self._provisioning_error

    @property
    def provisioning_retryable(self) -> bool:
        return self._provisioning_retryable

    @property
    def startup_timeout_seconds(self) -> int | None:
        return self._startup_timeout_seconds

    def update_startup_timeout(self, timeout_seconds: int | None) -> None:
        if timeout_seconds is not None and not (30 <= timeout_seconds <= 1800):
            raise InvalidValueError(
                field="startup_timeout_seconds",
                value=str(timeout_seconds),
                reason="startup_timeout_seconds must be between 30 and 1800, or None",
            )
        if self._startup_timeout_seconds != timeout_seconds:
            self._startup_timeout_seconds = timeout_seconds
            self._updated_at = datetime.now(UTC)
            self._add_event(
                ServerConfigChangedEvent(
                    server_id=self._id, changed_keys=["startup_timeout_seconds"]
                ),
            )

    def mark_broken(self) -> None:
        self._status = ServerStatus.BROKEN
        self._updated_at = datetime.now(UTC)

    def mark_repaired(self) -> None:
        self._status = ServerStatus.CREATED
        self._updated_at = datetime.now(UTC)

    def mark_missing(self) -> None:
        self._missing_since = datetime.now(UTC)
        self._updated_at = datetime.now(UTC)

    def clear_missing(self) -> None:
        self._missing_since = None
        self._updated_at = datetime.now(UTC)

    @classmethod
    def create(
        cls,
        server_id: ServerId,
        name: str,
        server_type: ServerType,
        minecraft_version: MinecraftVersion,
        memory: MemoryAllocation,
        java_args: JavaArguments,
        properties: ServerProperties,
        group_id: str = "default",
        deployment: ServerDeployment | None = None,
        owner_id: str | None = None,
        cpu: CpuAllocation | None = None,
        runtime: RuntimeInfo | None = None,
        startup_timeout_seconds: int | None = None,
        mode: ServerMode = ServerMode.SIMPLE,
    ) -> Server:
        server = cls(
            server_id=server_id,
            name=name,
            server_type=server_type,
            minecraft_version=minecraft_version,
            memory=memory,
            java_args=java_args,
            properties=properties,
            group_id=group_id,
            deployment=deployment,
            owner_id=owner_id,
            cpu=cpu,
            runtime=runtime,
            startup_timeout_seconds=startup_timeout_seconds,
            mode=mode,
        )
        server._add_event(
            ServerCreatedEvent(
                server_id=server_id,
                name=name,
                minecraft_version=str(minecraft_version),
            ),
        )
        return server

    def _transition_to(self, new_status: ServerStatus) -> None:
        allowed = _SERVER_TRANSITIONS.get(self._status, set())
        if new_status not in allowed:
            raise InvalidValueError(
                field="status",
                value=new_status.value,
                reason=f"Cannot transition from {self._status.value} to {new_status.value}",
            )
        self._status = new_status
        self._updated_at = datetime.now(UTC)

    def begin_provisioning(self) -> None:
        self._provisioning_error = None
        self._provisioning_retryable = False
        self._transition_to(ServerStatus.PROVISIONING)

    def finish_provisioning(self) -> None:
        self._provisioning_error = None
        self._provisioning_retryable = False
        self._transition_to(ServerStatus.CREATED)

    def fail_provisioning(
        self, error: str = "", retryable: bool = False, fatal: bool = False
    ) -> None:
        self._provisioning_error = error or None
        self._provisioning_retryable = retryable
        if fatal:
            self._transition_to(ServerStatus.BROKEN)
        else:
            self._transition_to(ServerStatus.PROVISIONING_FAILED)

    def start(self) -> None:
        self._transition_to(ServerStatus.STARTING)
        self._runtime.port = self._properties.port.value
        self._runtime.status = "starting"
        self._runtime.last_log_lines = []
        self._runtime.last_crash_time = None
        self._add_event(ServerStartingEvent(server_id=self._id))

    def record_runtime_starting(
        self,
        pid: int,
        port: int,
        host: str = "127.0.0.1",
        external_id: str = "",
        start_time: int | None = None,
    ) -> None:
        if self._status != ServerStatus.STARTING:
            raise InvalidValueError(
                field="status",
                value=self._status.value,
                reason=f"Cannot record runtime starting when server is in {self._status} state",
            )
        self._runtime = RuntimeInfo(
            status="starting",
            provider=self._runtime.provider,
            host=host,
            port=port,
            pid=pid,
            start_time=start_time,
            restart_count=self._runtime.restart_count,
            external_id=external_id,
        )
        self._updated_at = datetime.now(UTC)

    def mark_running(
        self,
        pid: int,
        port: int,
        host: str = "127.0.0.1",
        external_id: str = "",
        start_time: int | None = None,
        running_start_time: float | None = None,
    ) -> None:
        self._transition_to(ServerStatus.RUNNING)
        self._runtime = RuntimeInfo(
            status="running",
            provider=self._runtime.provider,
            host=host,
            port=port,
            pid=pid,
            start_time=start_time,
            running_start_time=(
                running_start_time if running_start_time is not None else time.time()
            ),
            restart_count=self._runtime.restart_count + 1
            if self._has_run
            else self._runtime.restart_count,
            external_id=external_id,
        )
        self._has_run = True
        self._add_event(ServerStartedEvent(server_id=self._id, pid=pid, port=port))

    def stop(self, reason: str = "") -> None:
        self._transition_to(ServerStatus.STOPPING)
        self._add_event(ServerStoppingEvent(server_id=self._id, reason=reason))

    def mark_stopped(self) -> None:
        self._transition_to(ServerStatus.STOPPED)
        self._has_run = True
        self._runtime = RuntimeInfo(
            status="stopped",
            provider=self._runtime.provider,
            port=self._properties.port.value,
            restart_count=self._runtime.restart_count,
            external_id="",
        )
        self._add_event(ServerStoppedEvent(server_id=self._id))

    def revert_to_running(self) -> None:
        self._transition_to(ServerStatus.RUNNING)
        self._runtime = RuntimeInfo(
            status="running",
            provider=self._runtime.provider,
            host=self._runtime.host,
            port=self._runtime.port,
            pid=self._runtime.pid,
            start_time=self._runtime.start_time,
            running_start_time=self._runtime.running_start_time,
            restart_count=self._runtime.restart_count,
            external_id=self._runtime.external_id,
        )
        self._updated_at = datetime.now(UTC)

    def mark_stop_unknown(self, reason: str = "") -> None:
        if self._status != ServerStatus.STOPPING:
            raise InvalidValueError(
                field="status",
                value=self._status.value,
                reason=f"Cannot mark stop unknown when server is in {self._status} state",
            )
        self._updated_at = datetime.now(UTC)
        self._add_event(ServerStopUnknownEvent(server_id=str(self._id), reason=reason))

    def mark_restoring(self) -> None:
        self._transition_to(ServerStatus.RESTORING)
        self._runtime = RuntimeInfo(
            status="restoring",
            provider=self._runtime.provider,
            port=self._properties.port.value,
            restart_count=self._runtime.restart_count,
            external_id="",
        )

    def mark_restore_completed(self) -> None:
        self._transition_to(ServerStatus.STOPPED)
        self._runtime = RuntimeInfo(
            status="stopped",
            provider=self._runtime.provider,
            port=self._properties.port.value,
            restart_count=self._runtime.restart_count,
            external_id="",
        )

    def crash(
        self,
        exit_code: int = -1,
        last_log_lines: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        self._transition_to(ServerStatus.CRASHED)
        self._has_run = True
        log_lines = list(last_log_lines or [])
        if reason and not log_lines:
            log_lines = [reason]
        self._runtime = RuntimeInfo(
            status="crashed",
            provider=self._runtime.provider,
            port=self._properties.port.value,
            last_crash_time=datetime.now(UTC).timestamp(),
            restart_count=self._runtime.restart_count,
            external_id=self._runtime.external_id,
            last_log_lines=log_lines,
        )
        self._add_event(
            ServerCrashedEvent(
                server_id=self._id,
                exit_code=exit_code,
                last_log_lines=log_lines,
            ),
        )

    def build_handle(
        self, provider_name: str, server_dir: Any | None = None
    ) -> Any:
        return build_server_handle(self, provider_name, server_dir)

    def rename(self, name: str) -> None:
        if not name or not name.strip():
            raise InvalidValueError(field="name", value=name, reason="Server name cannot be empty")
        new_name = name.strip()
        if self._name != new_name:
            self._name = new_name
            self._updated_at = datetime.now(UTC)
            self._add_event(
                ServerConfigChangedEvent(server_id=self._id, changed_keys=["name"]),
            )

    def update_deployment(self, deployment: ServerDeployment) -> None:
        self._deployment = deployment
        self._updated_at = datetime.now(UTC)

    def update_launch_config(self, config: LaunchConfiguration) -> None:
        self._launch_config = config
        self._updated_at = datetime.now(UTC)

    def update_properties(self, **changes: Any) -> None:
        current = self._properties
        changed_keys: list[str] = []
        kwargs: dict[str, Any] = {
            "port": current.port,
            "motd": current.motd,
            "max_players": current.max_players,
            "gamemode": current.gamemode,
            "difficulty": current.difficulty,
            "spawn_protection": current.spawn_protection,
            "pvp": current.pvp,
            "enable_command_block": current.enable_command_block,
            "online_mode": current.online_mode,
            "whitelist": current.whitelist,
            "view_distance": current.view_distance,
            "simulation_distance": current.simulation_distance,
        }
        for key, value in changes.items():
            if key in kwargs and kwargs[key] != value:
                kwargs[key] = value
                changed_keys.append(key)
        if changed_keys:
            from app.modules.server.domain.value_objects import PortNumber

            if "port" in kwargs and isinstance(kwargs["port"], int):
                kwargs["port"] = PortNumber(kwargs["port"])
            self._properties = ServerProperties(**kwargs)
            if "port" in changed_keys and self._status not in (
                ServerStatus.RUNNING,
                ServerStatus.STARTING,
            ):
                self._runtime.port = self._properties.port.value
            self._updated_at = datetime.now(UTC)
            self._add_event(
                ServerConfigChangedEvent(server_id=self._id, changed_keys=changed_keys),
            )

    def update_memory(self, memory: MemoryAllocation) -> None:
        self._memory = memory
        self._updated_at = datetime.now(UTC)
        self._add_event(
            ServerConfigChangedEvent(server_id=self._id, changed_keys=["memory"]),
        )

    def update_cpu(self, cpu: CpuAllocation) -> None:
        self._cpu = cpu
        self._updated_at = datetime.now(UTC)
        self._add_event(
            ServerConfigChangedEvent(server_id=self._id, changed_keys=["cpu"]),
        )

    def update_java_args(self, java_args: JavaArguments) -> None:
        self._java_args = java_args
        self._updated_at = datetime.now(UTC)
        self._add_event(
            ServerConfigChangedEvent(server_id=self._id, changed_keys=["java_args"]),
        )

    def mark_deleted(self) -> None:
        self._add_event(ServerDeletedEvent(server_id=self._id))
