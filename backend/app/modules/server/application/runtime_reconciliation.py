from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from app.core.config import AppSettings
from app.core.identity import IDENTITY
from app.core.process_utils import platform_pid_alive
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerFilters, ServerRepository
from app.modules.server.domain.value_objects import default_provider_for_platform
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
)
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.runtime_reconciliation")


def _get_post_running_grace_seconds() -> float:
    """Get post-RUNNING grace window from live settings, with 30s hardcoded fallback."""
    try:
        from app.core.settings_store import get_live_settings

        return get_live_settings().post_running_grace_seconds
    except Exception:
        return 30.0


class MismatchType(Enum):
    DB_RUNNING_NO_SUPERVISOR = "db_running_no_supervisor"
    DB_RUNNING_NO_TMUX = "db_running_no_tmux"
    DB_RUNNING_DEAD_PID = "db_running_dead_pid"
    DB_STARTING_ALIVE = "db_starting_alive"
    DB_STARTING_DEAD = "db_starting_dead"
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
    start_age_seconds: float | None = None
    running_age_seconds: float | None = None


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


MCS_MARKER = IDENTITY.process_marker_legacy
ONX_MARKER = IDENTITY.process_marker_new


def _get_process_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _get_process_env(pid: int) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
        for item in raw.decode("utf-8", errors="replace").split("\0"):
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v
    except OSError:
        pass
    return env


def _get_process_start_time(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        paren_end = data.rfind(")")
        if paren_end == -1:
            return None
        fields = data[paren_end + 2 :].split()
        if len(fields) >= 20:
            return int(fields[19])
        return None
    except (OSError, ValueError, IndexError):
        return None


def _get_servers_data_dir() -> str:
    try:
        settings = AppSettings()
        return os.path.abspath(settings.servers_data_dir)
    except Exception:
        return os.path.abspath("data/servers")


def _is_project_owned_process(pid: int, servers_data_dir: str | None = None) -> bool:
    env = _get_process_env(pid)
    if env.get(ONX_MARKER) == "1" or env.get(MCS_MARKER) == "1":
        return True
    if servers_data_dir is not None:
        cwd = _get_process_cwd(pid)
        if cwd is not None:
            try:
                common = os.path.commonpath([cwd, servers_data_dir])
                if common == servers_data_dir:
                    return True
            except ValueError:
                pass
    return False


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
        return [
            s.strip()
            for s in output.strip().splitlines()
            if s.strip().startswith(IDENTITY.temp_prefix_new)
            or s.strip().startswith(IDENTITY.temp_prefix_legacy)
        ]
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
    session_name = external_id or f"{IDENTITY.temp_prefix_new}{sid}"

    if provider is not None:
        handle = ServerHandle(
            provider=server.runtime.provider or default_provider_for_platform()
            if server.runtime
            else default_provider_for_platform(),
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
            pid_alive = platform_pid_alive(tmux_pid)

    port = server.properties.port.value if hasattr(server.properties, "port") else 25565
    port_listening = _port_is_listening(port) if isinstance(port, int) else False

    start_age_seconds: float | None = None
    if server.status == ServerStatus.STARTING:
        ref_time = None
        if server.runtime and server.runtime.start_time:
            with contextlib.suppress(Exception):
                ref_time = datetime.fromtimestamp(server.runtime.start_time, tz=UTC)
        if ref_time is None and server.updated_at:
            ref_time = server.updated_at
        if ref_time is not None:
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=UTC)
            start_age_seconds = (datetime.now(UTC) - ref_time).total_seconds()

    running_age_seconds: float | None = None
    if server.status == ServerStatus.RUNNING:
        if server.runtime and server.runtime.running_start_time:
            running_age_seconds = max(0.0, time.time() - server.runtime.running_start_time)

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
        start_age_seconds=start_age_seconds,
        running_age_seconds=running_age_seconds,
    )


def _detect_mismatches(state: ServerRuntimeState) -> list[MismatchReport]:
    mismatches: list[MismatchReport] = []

    if state.db_status in (ServerStatus.RUNNING,):
        if not state.has_supervisor:
            mismatches.append(
                MismatchReport(
                    server_id=state.server_id,
                    mismatch_type=MismatchType.DB_RUNNING_NO_SUPERVISOR,
                    detail="DB marks RUNNING but no supervisor is tracking this server",
                    auto_repairable=True,
                )
            )
        if not state.has_tmux and not state.supervisor_running and not state.pid_alive:
            mismatches.append(
                MismatchReport(
                    server_id=state.server_id,
                    mismatch_type=MismatchType.DB_RUNNING_NO_TMUX,
                    detail="DB marks RUNNING but no tmux session and no active supervisor",
                    auto_repairable=True,
                )
            )
        if state.tmux_pid and not state.pid_alive:
            mismatches.append(
                MismatchReport(
                    server_id=state.server_id,
                    mismatch_type=MismatchType.TMUX_PID_DEAD,
                    detail=f"tmux pane PID {state.tmux_pid} is not alive",
                    auto_repairable=True,
                )
            )
        if state.has_supervisor and not state.has_tmux:
            mismatches.append(
                MismatchReport(
                    server_id=state.server_id,
                    mismatch_type=MismatchType.SUPERVISOR_NO_TMUX,
                    detail="Supervisor is running but tmux session is gone",
                    auto_repairable=True,
                )
            )
            if not state.pid_alive:
                grace = _get_post_running_grace_seconds()
                in_grace = (
                    state.running_age_seconds is not None
                    and state.running_age_seconds < grace
                )
                if not in_grace:
                    mismatches.append(
                        MismatchReport(
                            server_id=state.server_id,
                            mismatch_type=MismatchType.DB_RUNNING_NO_TMUX,
                            detail="Supervisor running but tmux gone and PID dead",
                            auto_repairable=True,
                        )
                    )

    if state.db_status == ServerStatus.STARTING and not state.supervisor_running:
        if state.has_tmux and state.pid_alive:
            mismatches.append(
                MismatchReport(
                    server_id=state.server_id,
                    mismatch_type=MismatchType.DB_STARTING_ALIVE,
                    detail="DB marks STARTING with no active supervisor but process is alive",
                    auto_repairable=True,
                )
            )
        else:
            # Do not falsely crash servers that just started (within 60s grace window)
            is_fresh = state.start_age_seconds is not None and state.start_age_seconds < 60.0
            if not is_fresh:
                mismatches.append(
                    MismatchReport(
                        server_id=state.server_id,
                        mismatch_type=MismatchType.DB_STARTING_DEAD,
                        detail="DB marks STARTING with no active supervisor and process is dead",
                        auto_repairable=True,
                    )
                )

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
                external_id=state.external_id or f"{IDENTITY.temp_prefix_new}{state.server_id}",
            )
            await repo.save(server)
            actions.append(
                f"Transitioned STARTING → RUNNING (process is alive on port {state.port})"
            )
            repaired = True

        elif m.mismatch_type in (
            MismatchType.DB_RUNNING_NO_TMUX,
            MismatchType.DB_RUNNING_DEAD_PID,
            MismatchType.TMUX_PID_DEAD,
            MismatchType.DB_STARTING_DEAD,
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
        provider_type = (
            server.runtime.provider
            if (server.runtime and server.runtime.provider)
            else default_provider_for_platform()
        )
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
        except Exception:
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
        total,
        total,
        repaired_count,
    )
    return outcomes


async def reconcile_orphans(
    repo: ServerRepository | None = None,
    scope: Literal["project_owned", "system_wide"] = "project_owned",
) -> list[dict]:
    actions: list[dict] = []
    servers_data_dir = _get_servers_data_dir() if scope == "project_owned" else None

    expected_sessions: set[str] = set()
    known_pids: set[int] = set()

    if repo is not None:
        try:
            active_servers = await repo.list(ServerFilters(status="running"))
            active_servers += await repo.list(ServerFilters(status="starting"))
        except Exception:
            logger.exception("Failed to list active servers for orphan reconciliation")
            active_servers = []

        for s in active_servers:
            sid = str(s.id)
            expected_sessions.add(f"{IDENTITY.temp_prefix_new}{sid}")
            expected_sessions.add(f"{IDENTITY.temp_prefix_legacy}{sid}")
            if s.runtime and s.runtime.external_id:
                expected_sessions.add(s.runtime.external_id)
            if s.runtime and s.runtime.pid:
                known_pids.add(s.runtime.pid)

    tmux_sessions = _find_all_tmux_sessions()
    for session in tmux_sessions:
        if session in expected_sessions:
            logger.debug("Skipping tmux session %s — matches an active server", session)
            continue

        pid = _get_tmux_pid(session)

        if scope == "project_owned":
            try:
                is_owned = pid is not None and _is_project_owned_process(pid, servers_data_dir)
            except Exception:
                logger.warning(
                    "KILL_DECISION session=%s pid=%s scope=%s decision=SKIP reason='ownership-check-failed'",
                    session,
                    pid,
                    scope,
                )
                actions.append(
                    {
                        "type": "orphan_tmux_skipped",
                        "session": session,
                        "pid": pid,
                        "reason": "ownership-check-error",
                    }
                )
                continue
            if not is_owned:
                env_marker = (
                    _get_process_env(pid).get(ONX_MARKER) or _get_process_env(pid).get(MCS_MARKER)
                    if pid
                    else None
                )
                proc_cwd = _get_process_cwd(pid) if pid else None
                logger.info(
                    "KILL_DECISION session=%s pid=%s scope=%s marker=%s cwd=%s decision=SKIP reason='not-project-owned'",
                    session,
                    pid,
                    scope,
                    env_marker,
                    proc_cwd,
                )
                actions.append(
                    {
                        "type": "orphan_tmux_skipped",
                        "session": session,
                        "pid": pid,
                        "reason": "not-project-owned",
                    }
                )
                continue

        reason = f"orphan tmux session {session} — no matching running/starting server in database"
        env_marker = (
            _get_process_env(pid).get(ONX_MARKER) or _get_process_env(pid).get(MCS_MARKER)
            if pid
            else None
        )
        proc_cwd = _get_process_cwd(pid) if pid else None
        proc_start = _get_process_start_time(pid) if pid else None
        logger.info(
            "KILL_DECISION session=%s pid=%s scope=%s marker=%s cwd=%s start_time=%s decision=KILL reason=%s",
            session,
            pid,
            scope,
            env_marker,
            proc_cwd,
            proc_start,
            reason,
        )
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.popen(f"tmux kill-session -t {session} 2>/dev/null")
        actions.append({"type": "orphan_tmux", "session": session, "pid": pid, "action": "killed"})

    all_java_pids = _find_all_java_pids()
    for pid in all_java_pids:
        if not _is_minecraft_java_pid(pid):
            continue
        if pid in known_pids:
            continue

        if scope == "project_owned":
            try:
                is_owned = _is_project_owned_process(pid, servers_data_dir)
            except Exception:
                logger.warning(
                    "KILL_DECISION pid=%s scope=%s decision=SKIP reason='ownership-check-failed'",
                    pid,
                    scope,
                )
                continue
            if not is_owned:
                env_marker = _get_process_env(pid).get(ONX_MARKER) or _get_process_env(pid).get(
                    MCS_MARKER
                )
                proc_cwd = _get_process_cwd(pid)
                logger.info(
                    "KILL_DECISION pid=%s scope=%s marker=%s cwd=%s decision=SKIP reason='not-project-owned'",
                    pid,
                    scope,
                    env_marker,
                    proc_cwd,
                )
                continue

        reason = f"orphan Java process (Minecraft) pid={pid} — not attached to any managed server"
        env_marker = _get_process_env(pid).get(ONX_MARKER) or _get_process_env(pid).get(MCS_MARKER)
        proc_cwd = _get_process_cwd(pid)
        proc_start = _get_process_start_time(pid)
        logger.info(
            "KILL_DECISION pid=%s scope=%s marker=%s cwd=%s start_time=%s decision=KILL reason=%s",
            pid,
            scope,
            env_marker,
            proc_cwd,
            proc_start,
            reason,
        )
        try:
            os.kill(pid, signal.SIGTERM)
            await asyncio.sleep(0.5)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        actions.append({"type": "orphan_java", "pid": pid, "action": "killed"})

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
