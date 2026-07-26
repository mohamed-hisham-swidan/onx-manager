from __future__ import annotations

import time

from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.storage.db import database


class GetServerRuntimeDiagnosticsQuery(Query):
    server_id: str


class RuntimeDiagnosticsReadModel:
    def __init__(self, server_id: str, alive: bool, data: dict) -> None:
        self.server_id = server_id
        self.alive = alive
        self.data = data


class GetServerRuntimeDiagnosticsHandler(QueryHandler[GetServerRuntimeDiagnosticsQuery]):
    async def handle(self, query: GetServerRuntimeDiagnosticsQuery) -> RuntimeDiagnosticsReadModel:
        sid = ServerId(query.server_id)

        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(sid)

        server_name = server.name
        supervisor = RuntimeSupervisor.get_for(query.server_id)
        provider_type = server.runtime.provider if server.runtime else "local"
        provider = provider_factory.get(provider_type)

        runtime_handle: str | None = None
        external_id: str | None = None
        port = None
        if server.runtime:
            external_id = server.runtime.external_id
            runtime_handle = external_id or None
        if server.properties:
            port = server.properties.port.value if hasattr(server.properties, "port") else 25565

        handle: ServerHandle | None = None
        if external_id:
            handle = ServerHandle(
                provider=provider_type,
                server_id=query.server_id,
                external_id=external_id,
            )

        alive = False
        pid = server.runtime.pid if server.runtime else None
        provider_status = None

        if handle:
            try:
                provider_status = (await provider.status(handle)).value
                alive = provider_status == "running"
                if alive:
                    pid_obj = await provider.get_runtime_pid(handle)
                    pid = pid_obj or pid
            except Exception:
                provider_status = "error"

        jvm_command = None
        if pid and alive:
            try:
                from app.modules.server.application.runtime_ownership import _get_java_cmdline
                jvm_command = _get_java_cmdline(pid)
            except Exception:
                pass

        port_owner = None
        if port:
            try:
                from app.modules.server.application.runtime_ownership import _pid_for_port, _port_is_listening
                if _port_is_listening(port):
                    port_pid = _pid_for_port(port)
                    if port_pid:
                        port_owner = f"pid={port_pid}"
                    else:
                        port_owner = "unknown"
            except Exception:
                pass

        owner_conflicts = []
        validation_chain = []
        try:
            from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
            mgr = RuntimeOwnershipManager(repo)
            snapshot = await mgr.discover_all()
            for conflict in snapshot.conflicts:
                owner_conflicts.append({
                    "reason": conflict.reason.value,
                    "detail": conflict.detail,
                    "auto_resolvable": conflict.auto_resolvable,
                })
            validation = await mgr.validate_runtime(query.server_id)
            validation_chain = validation.chain
        except Exception:
            pass

        diag_data = {
            "server_id": query.server_id,
            "server_name": server_name,
            "status": server.status.value if server.status else "unknown",
            "alive": alive,
            "pid": pid,
            "provider": provider_type,
            "uptime_seconds": supervisor.uptime if (supervisor and supervisor.is_running) else (server.runtime.uptime_seconds if server.runtime else 0),
            "heartbeat_age_seconds": (time.time() - supervisor.last_heartbeat) if (supervisor and supervisor.is_running) else None,
            "startup_duration_seconds": supervisor.start_duration if (supervisor and supervisor.is_running) else None,
            "restart_count": server.runtime.restart_count if server.runtime else 0,
            "failure_code": None,
            "failure_reason": None,
            "last_logs": None,
            "last_exception": None,
            "last_verification_timestamp": time.time(),
            "supervised": RuntimeSupervisor.is_supervised(query.server_id),
            "runtime_handle": runtime_handle,
            "provider_status": provider_status,
            "last_crash_time": server.runtime.last_crash_time if server.runtime else None,
            "port": port,
            "port_owner": port_owner,
            "tmux_session": runtime_handle,
            "jvm_command": jvm_command,
            "owner_conflicts": owner_conflicts,
            "validation_chain": validation_chain,
        }

        return RuntimeDiagnosticsReadModel(
            server_id=query.server_id,
            alive=alive,
            data=diag_data,
        )
