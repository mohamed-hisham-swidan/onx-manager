from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger("mcs.runtime_reconciliation")


class MismatchType(Enum):
    DB_RUNNING_NO_SUPERVISOR = "db_running_no_supervisor"
    DB_RUNNING_NO_TMUX = "db_running_no_tmux"
    DB_RUNNING_DEAD_PID = "db_running_dead_pid"
    DB_STARTING_ALIVE = "db_starting_alive"
    SUPERVISOR_NO_TMUX = "supervisor_no_tmux"
    TMUX_PID_DEAD = "tmux_pid_dead"
    PID_PORT_MISMATCH = "pid_port_mismatch"
    PORT_NOT_LISTENING = "port_not_listening"
    ORPHAN_TMUX = "orphan_tmux"
    ORPHAN_PROCESS = "orphan_process"


@dataclass
class ServerRuntimeState:
    server_id: str
    server_name: str
    db_status: ServerStatus
    has_supervisor: bool
    supervisor_running: bool
    has_tmux: bool
    tmux_pid: int | None = None
    pid_alive: bool = False
    port_listening: bool = False
    port: int = 25565
    runtime_pid: int | None = None
    external_id: str = ""


@dataclass
class MismatchReport:
    server_id: str
    mismatch_type: MismatchType
    detail: str = ""
    auto_repairable: bool = False


@dataclass
class ReconciliationOutcome:
    server_id: str
    server_name: str
    mismatches: list[MismatchReport] = field(default_factory=list)
    repaired: bool = False
    actions: list[str] = field(default_factory=list)
    error: str | None = None


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _find_all_tmux_sessions() -> list[str]:
    try:
        proc = os.popen("tmux list-sessions -F '#{session_name}' 2>/dev/null")
        output = proc.read()
        proc.close()
        if not output:
            return []
        return [s.strip() for s in output.strip().splitlines() if s.strip().startswith("mcs-")]
    except Exception:
        return []


def _find_all_java_pids() -> list[int]:
    try:
        proc = os.popen("ps aux | grep java | grep -v grep | awk '{print $2}'")
        output = proc.read()
        proc.close()
        if not output:
            return []
        pids: list[int] = []
        for line in output.strip().splitlines():
            pid_str = line.strip()
            if pid_str.isdigit():
                pids.append(int(pid_str))
        return pids
    except Exception:
        return []


def _is_minecraft_java_pid(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read().decode("utf-8", errors="replace").replace("\0", " ")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    lower = raw.lower()
    return ("-jar" in raw and "server" in lower) or "minecraft" in lower


def _pid_for_port(port: int) -> int | None:
    try:
        proc = os.popen(f"ss -tlnp 'sport = :{port}' 2>/dev/null | grep -oP 'pid=\\K\\d+'")
        output = proc.read()
        proc.close()
        if output.strip():
            return int(output.strip().splitlines()[0])
        return None
    except Exception:
        return None


async def _get_server_state(
    server: Server,
    provider: ServerProvider | None,
) -> ServerRuntimeState:
    sid = str(server.id)
    supervisor = RuntimeSupervisor.get_for(sid)

    has_tmux = False
    tmux_pid: int | None = None
    pid_alive = False

    external_id = server.runtime.external_id if server.runtime else ""
    session_name = external_id or f"mcs-{sid}"

    if provider is not None:
        handle = ServerHandle(
            provider=server.runtime.provider or "local" if server.runtime else "local",
            server_id=sid,
            external_id=session_name,
        )
        try:
            has_tmux = await provider.verify_process(handle)
            if has_tmux:
                tmux_pid = await provider.get_runtime_pid(handle)
        except Exception as exc:
            logger.debug("State check failed for %s: %s", sid, exc)
        if tmux_pid:
            try:
                os.kill(tmux_pid, 0)
                pid_alive = True
            except OSError:
                pid_alive = False

    port = server.properties.port.value if hasattr(server.properties, "port") else 25565
    if isinstance(port, int):
        port_listening = _port_is_listening(port)
    else:
        port_listening = False

    return ServerRuntimeState(
        server_id=sid,
        server_name=server.name,
        db_status=server.status,
        has_supervisor=supervisor is not None,
        supervisor_running=supervisor.is_running if supervisor else False,
        has_tmux=has_tmux,
        tmux_pid=tmux_pid,
        pid_alive=pid_alive,
        port_listening=port_listening,
        port=port if isinstance(port, int) else 25565,
        runtime_pid=server.runtime.pid if server.runtime else None,
        external_id=external_id,
    )


def _detect_mismatches(state: ServerRuntimeState) -> list[MismatchReport]:
    mismatches: list[MismatchReport] = []

    if state.db_status in (ServerStatus.RUNNING,):
        if not state.has_supervisor:
            mismatches.append(MismatchReport(
                server_id=state.server_id,
                mismatch_type=MismatchType.DB_RUNNING_NO_SUPERVISOR,
                detail="DB marks RUNNING but no supervisor is tracking this server",
                auto_repairable=True,
            ))
        if not state.has_tmux and not state.supervisor_running:
            mismatches.append(MismatchReport(
                server_id=state.server_id,
                mismatch_type=MismatchType.DB_RUNNING_NO_TMUX,
                detail="DB marks RUNNING but no tmux session and no active supervisor",
                auto_repairable=True,
            ))
        if state.tmux_pid and not state.pid_alive:
            mismatches.append(MismatchReport(
                server_id=state.server_id,
                mismatch_type=MismatchType.TMUX_PID_DEAD,
                detail=f"tmux pane PID {state.tmux_pid} is not alive",
                auto_repairable=True,
            ))
        if state.has_supervisor and not state.has_tmux:
            mismatches.append(MismatchReport(
                server_id=state.server_id,
                mismatch_type=MismatchType.SUPERVISOR_NO_TMUX,
                detail="Supervisor is running but tmux session is gone",
                auto_repairable=True,
            ))

    if state.db_status == ServerStatus.STARTING:
        if state.has_tmux and state.pid_alive and state.port_listening:
            mismatches.append(MismatchReport(
                server_id=state.server_id,
                mismatch_type=MismatchType.DB_STARTING_ALIVE,
                detail="DB marks STARTING but process is fully up and port is listening",
                auto_repairable=True,
            ))

    return mismatches


async def _auto_repair(
    server: Server,
    state: ServerRuntimeState,
    mismatches: list[MismatchReport],
    repo: ServerRepository,
) -> tuple[bool, list[str]]:
    actions: list[str] = []
    repaired = False

    for m in mismatches:
        if not m.auto_repairable:
            continue

        if m.mismatch_type == MismatchType.DB_STARTING_ALIVE:
            server.mark_running(
                pid=state.tmux_pid or state.runtime_pid or 0,
                port=state.port,
                external_id=state.external_id or f"mcs-{state.server_id}",
            )
            await repo.save(server)
            actions.append(f"Transitioned STARTING → RUNNING (process is alive on port {state.port})")
            repaired = True

        elif m.mismatch_type in (
            MismatchType.DB_RUNNING_NO_TMUX,
            MismatchType.DB_RUNNING_DEAD_PID,
            MismatchType.TMUX_PID_DEAD,
        ):
            server.crash(
                exit_code=-1,
                last_log_lines=[
                    f"Runtime reconciliation: {m.detail}",
                ],
            )
            await repo.save(server)
            actions.append(f"Marked CRASHED: {m.detail}")
            repaired = True

        elif m.mismatch_type == MismatchType.DB_RUNNING_NO_SUPERVISOR:
            actions.append("No automatic repair — supervisor not running but DB says RUNNING")

    if state.supervisor_running and not state.has_tmux:
        await RuntimeSupervisor.stop_for(state.server_id)
        actions.append("Stopped supervisor — tmux session no longer exists")
        repaired = True

    return repaired, actions


async def reconcile_server_runtime(
    server: Server,
    repo: ServerRepository,
) -> ReconciliationOutcome:
    sid = str(server.id)
    outcome = ReconciliationOutcome(server_id=sid, server_name=server.name)

    try:
        provider_type = server.runtime.provider if server.runtime else "local"
        provider = provider_factory.get(provider_type)
    except Exception as exc:
        outcome.error = f"Failed to get provider: {exc}"
        return outcome

    state = await _get_server_state(server, provider)
    mismatches = _detect_mismatches(state)
    outcome.mismatches = mismatches

    if mismatches:
        repaired, actions = await _auto_repair(server, state, mismatches, repo)
        outcome.repaired = repaired
        outcome.actions = actions

        if repaired:
            for a in actions:
                logger.info("Reconciled %s — %s", sid, a)

    return outcome


async def reconcile_all_runtimes(
    repo: ServerRepository,
    server_ids: list[str] | None = None,
) -> list[ReconciliationOutcome]:
    if server_ids:
        servers: list[Server] = []
        for sid in server_ids:
            try:
                servers.append(await repo.get(ServerId(sid)))
            except Exception as exc:
                logger.warning("Server %s not found during reconciliation: %s", sid, exc)
    else:
        try:
            servers = await repo.list()
        except Exception as exc:
            logger.exception("Failed to list servers for runtime reconciliation")
            return []

    outcomes: list[ReconciliationOutcome] = []
    for server in servers:
        outcome = await reconcile_server_runtime(server, repo)
        outcomes.append(outcome)

    repaired_count = sum(1 for o in outcomes if o.repaired)
    total = len(outcomes)
    logger.info(
        "Runtime reconciliation complete: %d/%d servers checked, %d repaired",
        total, total, repaired_count,
    )
    return outcomes


async def reconcile_orphans() -> list[dict]:
    actions: list[dict] = []

    tmux_sessions = _find_all_tmux_sessions()
    for session in tmux_sessions:
        pid = _get_tmux_pid(session)
        reason = f"orphan tmux session {session} — no matching server in database"
        if pid:
            logger.warning(
                "Killing orphan tmux — session=%s pid=%d reason=%s",
                session, pid, reason,
            )
            try:
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.popen(f"tmux kill-session -t {session} 2>/dev/null")
        logger.info("Killed orphan tmux — session=%s pid=%s reason=%s", session, pid, reason)
        actions.append({"type": "orphan_tmux", "session": session, "pid": pid, "action": "killed"})

    all_java_pids = _find_all_java_pids()
    minecraft_pids = [p for p in all_java_pids if _is_minecraft_java_pid(p)]
    if minecraft_pids:
        for pid in minecraft_pids:
            reason = f"orphan Java process (Minecraft) pid={pid} — not attached to any managed tmux session"
            logger.warning("Killing orphan Minecraft process — pid=%d reason=%s", pid, reason)
            try:
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        logger.info(
            "Killed %d orphan Minecraft processes (filtered from %d total Java PIDs)",
            len(minecraft_pids), len(all_java_pids),
        )
        actions.append({"type": "orphan_java", "pids": minecraft_pids, "action": "killed"})

    return actions


def _get_tmux_pid(session_name: str) -> int | None:
    try:
        proc = os.popen(
            f"tmux list-panes -t {session_name} -F '#{{pane_pid}}' 2>/dev/null",
        )
        output = proc.read()
        proc.close()
        if output and output.strip().splitlines():
            line = output.strip().splitlines()[0]
            if line.isdigit():
                return int(line)
        return None
    except Exception:
        return None
