from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from app.core.identity import IDENTITY
from app.core.process_utils import platform_pid_alive, verify_process_identity
from app.modules.server.application.ownership_verifier import (
    OwnershipStatus,
    log_ownership_decision,
    verify_ownership,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import default_provider_for_platform
from app.modules.server.infrastructure.providers import provider_factory as default_provider_factory
from app.modules.server.infrastructure.providers.base import (
    ProviderFactory,
    ServerHandle,
)
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.runtime_ownership")

MINECRAFT_CMDLINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"-jar\s+\S*server\.jar"),
    re.compile(r"-jar\s+\S*paper"),
    re.compile(r"-jar\s+\S*purpur"),
    re.compile(r"-jar\s+\S*fabric"),
    re.compile(r"-jar\s+\S*forge"),
    re.compile(r"-jar\s+\S*spigot"),
    re.compile(r"-jar\s+\S*bukkit"),
    re.compile(r"paper.*\.jar"),
    re.compile(r"purpur.*\.jar"),
    re.compile(r"fabric.*\.jar"),
    re.compile(r"forge.*\.jar"),
    re.compile(r"spigot.*\.jar"),
    re.compile(r"bukkit.*\.jar"),
    re.compile(r"minecraft.*server"),
]


class ConflictReason(Enum):
    DUPLICATE_PORT = "duplicate_port"
    DUPLICATE_PID = "duplicate_pid"
    ORPHAN_TMUX = "orphan_tmux"
    ORPHAN_PROCESS = "orphan_process"
    ORPHAN_PORT = "orphan_port"
    STALE_DB_RECORD = "stale_db_record"
    STALE_SUPERVISOR = "stale_supervisor"
    MULTIPLE_SERVERS_ACTIVE = "multiple_servers_active"
    PORT_NOT_RELEASED = "port_not_released"
    PROCESS_NOT_TERMINATED = "process_not_terminated"


@dataclass
class RuntimeResource:
    resource_type: str
    identifier: str
    pid: int | None = None
    port: int | None = None
    server_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictInfo:
    reason: ConflictReason
    detail: str
    auto_resolvable: bool = False
    resource: RuntimeResource | None = None


@dataclass
class ClaimResult:
    success: bool
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts_resolved: int = 0
    error: str | None = None


@dataclass
class OwnershipSnapshot:
    timestamp: float
    active_servers: list[dict[str, Any]]
    orphan_tmux: list[RuntimeResource]
    orphan_processes: list[RuntimeResource]
    stale_db_records: list[dict[str, Any]]
    stale_supervisors: list[dict[str, Any]]
    conflicts: list[ConflictInfo]
    localhost_owner: str | None = None
    total_orphans: int = 0


@dataclass
class ValidationChain:
    server_id: str
    server_name: str = ""
    db_ok: bool = False
    supervisor_ok: bool = False
    tmux_ok: bool = False
    pid_ok: bool = False
    port_ok: bool = False
    minecraft_ok: bool = False
    port_owner: str | None = None
    chain: list[str] = field(default_factory=list)
    healthy: bool = False


def _is_minecraft_cmdline(cmdline: str) -> bool:
    if not cmdline:
        return False
    for pat in MINECRAFT_CMDLINE_PATTERNS:
        if pat.search(cmdline):
            return True
    lower = cmdline.lower()
    return "minecraft" in lower and "server" in lower


def _find_all_tmux_sessions() -> list[tuple[str, int | None]]:
    sessions: list[tuple[str, int | None]] = []
    try:
        proc = os.popen("tmux list-sessions -F '#{session_name}' 2>/dev/null")
        output = proc.read()
        proc.close()
        if not output:
            return sessions
        for name in output.strip().splitlines():
            name = name.strip()
            if not name:
                continue
            pid = _get_tmux_pane_pid(name)
            sessions.append((name, pid))
        return sessions
    except Exception:
        logger.exception("Failed to list tmux sessions")
        return sessions


def _get_tmux_pane_pid(session_name: str) -> int | None:
    try:
        res = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = res.stdout or ""
        if output.strip().splitlines():
            line = output.strip().splitlines()[0]
            if line.isdigit():
                return int(line)
        return None
    except Exception:
        return None


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


def _get_java_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
        return raw.decode("utf-8", errors="replace").replace("\0", " ")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return ""


def _is_pid_alive(pid: int) -> bool:
    return platform_pid_alive(pid)


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


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


def _find_child_java_pids(parent_pid: int) -> list[int]:
    children: list[int] = []
    try:
        proc = os.popen(f"ps --ppid {parent_pid} -o pid= 2>/dev/null")
        output = proc.read()
        proc.close()
        if not output:
            return children
        for line in output.strip().splitlines():
            pid_str = line.strip()
            if pid_str.isdigit():
                children.append(int(pid_str))
        grandchildren: list[int] = []
        for child in children:
            grandchildren.extend(_find_child_java_pids(child))
        children.extend(grandchildren)
        return children
    except Exception:
        return children


def _find_minecraft_child_pids(tmux_pane_pid: int) -> list[int]:
    all_children = _find_child_java_pids(tmux_pane_pid)
    return [pid for pid in all_children if _is_pid_alive(pid)]


def _wait_for_port_free(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_is_listening(port):
            return True
        time.sleep(0.3)
    return not _port_is_listening(port)


def _wait_for_pid_dead(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.2)
    return not _is_pid_alive(pid)


def _try_kill_process(pid: int) -> tuple[bool, str]:
    if not _is_pid_alive(pid):
        return True, "already dead"
    try:
        os.kill(pid, signal.SIGTERM)
        if _wait_for_pid_dead(pid, timeout=2.0):
            return True, "SIGTERM succeeded"
    except ProcessLookupError:
        return True, "already dead"
    except Exception as exc:
        try:
            os.kill(pid, signal.SIGKILL)
            if _wait_for_pid_dead(pid, timeout=1.0):
                return True, "SIGKILL succeeded"
            else:
                return False, "SIGKILL sent but process still alive"
        except ProcessLookupError:
            return True, "already dead"
        except Exception as exc2:
            return False, f"SIGTERM failed ({exc}), SIGKILL failed ({exc2})"
    return False, "unknown"


def _try_kill_tmux_session(session_name: str) -> tuple[bool, str]:
    pid = _get_tmux_pane_pid(session_name)
    if pid:
        killed, reason = _try_kill_process(pid)
        if not killed:
            return False, f"pane PID {pid}: {reason}"
    with contextlib.suppress(FileNotFoundError, OSError):
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    still_exists = _get_tmux_pane_pid(session_name) is not None
    if still_exists:
        return False, f"tmux kill-session sent but session {session_name} still exists"
    return True, "tmux session removed"


class RuntimeOwnershipManager:
    def __init__(
        self,
        repo: ServerRepository,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._repo = repo
        self._provider_factory = provider_factory or default_provider_factory

    @property
    def _servers_data_dir(self) -> str:
        try:
            from app.modules.server.application.ownership_verifier import _get_servers_data_dir

            return _get_servers_data_dir()
        except Exception:
            return os.path.abspath("data/servers")

    async def discover_all(self) -> OwnershipSnapshot:
        servers = await self._repo.list()
        server_map: dict[str, Server] = {str(s.id): s for s in servers}

        all_tmux = _find_all_tmux_sessions()
        owned_server_ids: set[str] = set()

        active_servers_list: list[dict[str, Any]] = []
        orphan_tmux_list: list[RuntimeResource] = []
        orphan_process_list: list[RuntimeResource] = []
        stale_records: list[dict[str, Any]] = []
        stale_supervisors: list[dict[str, Any]] = []
        conflicts: list[ConflictInfo] = []

        all_java_pids = _find_all_java_pids()
        java_pid_set = set(all_java_pids)

        checked_tmux_names: set[str] = set()
        seen_pids: set[int] = set()
        port_to_server: dict[int, str] = {}

        for sid, server in server_map.items():
            ext_id = server.runtime.external_id if server.runtime else ""
            session_name = ext_id or f"{IDENTITY.temp_prefix_new}{sid}"
            raw_port = getattr(server.properties, "port", None) if server.properties else None
            port = (
                int(raw_port.value)
                if hasattr(raw_port, "value")
                else int(raw_port)
                if isinstance(raw_port, int)
                else 25565
            )

            is_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)
            matching_tmux = [t for t in all_tmux if t[0] == session_name]

            if matching_tmux:
                checked_tmux_names.add(session_name)
                tmux_name, pane_pid = matching_tmux[0]
                mc_pids = _find_minecraft_child_pids(pane_pid) if pane_pid else []
                mc_pid = mc_pids[0] if mc_pids else None
                port_listening = _port_is_listening(port) if is_running else False
                actual_pid = mc_pid if mc_pid else pane_pid

                if actual_pid and actual_pid in seen_pids:
                    conflicts.append(
                        ConflictInfo(
                            reason=ConflictReason.DUPLICATE_PID,
                            detail=(
                                f"PID {actual_pid} claimed by multiple servers "
                                f"(conflict with {sid})"
                            ),
                            auto_resolvable=True,
                        )
                    )
                if actual_pid:
                    seen_pids.add(actual_pid)

                owned_server_ids.add(sid)
                if port not in port_to_server:
                    port_to_server[port] = sid
                elif port_to_server[port] != sid:
                    conflicts.append(
                        ConflictInfo(
                            reason=ConflictReason.DUPLICATE_PORT,
                            detail=(
                                f"Port {port} claimed by {sid} but already owned by "
                                f"{port_to_server[port]}"
                            ),
                            auto_resolvable=True,
                            resource=RuntimeResource(
                                resource_type="port", identifier=str(port), port=port
                            ),
                        )
                    )

                active_servers_list.append(
                    {
                        "server_id": sid,
                        "server_name": server.name,
                        "status": server.status.value,
                        "tmux_session": tmux_name,
                        "pane_pid": pane_pid,
                        "minecraft_pid": mc_pid,
                        "actual_pid": actual_pid,
                        "port": port,
                        "port_listening": port_listening,
                        "port_owner": port_to_server.get(port),
                        "supervised": RuntimeSupervisor.is_supervised(sid),
                    }
                )

                for mcp in mc_pids:
                    java_pid_set.discard(mcp)
                if pane_pid:
                    java_pid_set.discard(pane_pid)

                has_supervisor = RuntimeSupervisor.is_supervised(sid)
                if is_running and not has_supervisor:
                    stale_supervisors.append(
                        {
                            "server_id": sid,
                            "server_name": server.name,
                            "detail": (
                                f"Server is {server.status.value} with active tmux "
                                "but no supervisor tracking it"
                            ),
                        }
                    )
            elif is_running:
                stale_records.append(
                    {
                        "server_id": sid,
                        "server_name": server.name,
                        "status": server.status.value,
                        "detail": (
                            f"DB marks {server.status.value} but no tmux session found "
                            f"({session_name})"
                        ),
                    }
                )

        checked_session_names: set[str] = (
            {f"{IDENTITY.temp_prefix_new}{s}" for s in server_map}
            | {f"{IDENTITY.temp_prefix_legacy}{s}" for s in server_map}
            | checked_tmux_names
        )

        for tmux_name, pane_pid in all_tmux:
            if tmux_name not in checked_session_names:
                mc_pids = _find_minecraft_child_pids(pane_pid) if pane_pid else []
                orphan_tmux_list.append(
                    RuntimeResource(
                        resource_type="tmux",
                        identifier=tmux_name,
                        pid=pane_pid,
                        details={"minecraft_child_pids": mc_pids},
                    )
                )
                for mcp in mc_pids:
                    java_pid_set.discard(mcp)
                if pane_pid:
                    java_pid_set.discard(pane_pid)

        for jpid in list(java_pid_set):
            cmdline = _get_java_cmdline(jpid)
            if _is_minecraft_cmdline(cmdline):
                orphan_process_list.append(
                    RuntimeResource(
                        resource_type="process",
                        identifier=str(jpid),
                        pid=jpid,
                        details={"cmdline": cmdline[:200]},
                    )
                )

        active_count = len(active_servers_list)
        if active_count > 1:
            active_names = ", ".join(a["server_name"] for a in active_servers_list)
            conflicts.append(
                ConflictInfo(
                    reason=ConflictReason.MULTIPLE_SERVERS_ACTIVE,
                    detail=f"{active_count} servers are actively running: {active_names}",
                    auto_resolvable=True,
                )
            )

        if orphan_tmux_list:
            orphan_ids = ", ".join(r.identifier for r in orphan_tmux_list)
            conflicts.append(
                ConflictInfo(
                    reason=ConflictReason.ORPHAN_TMUX,
                    detail=f"{len(orphan_tmux_list)} orphan tmux sessions: {orphan_ids}",
                    auto_resolvable=True,
                )
            )

        if orphan_process_list:
            orphan_pids = ", ".join(str(r.pid) for r in orphan_process_list if r.pid)
            conflicts.append(
                ConflictInfo(
                    reason=ConflictReason.ORPHAN_PROCESS,
                    detail=(
                        f"{len(orphan_process_list)} orphan Minecraft processes: "
                        f"PIDs {orphan_pids}"
                    ),
                    auto_resolvable=True,
                )
            )

        localhost_owner = None
        for a in active_servers_list:
            if a["port_listening"]:
                localhost_owner = a["server_id"]
                break

        return OwnershipSnapshot(
            timestamp=time.time(),
            active_servers=active_servers_list,
            orphan_tmux=orphan_tmux_list,
            orphan_processes=orphan_process_list,
            stale_db_records=stale_records,
            stale_supervisors=stale_supervisors,
            conflicts=conflicts,
            localhost_owner=localhost_owner,
            total_orphans=len(orphan_tmux_list) + len(orphan_process_list),
        )

    async def claim_localhost(self, requesting_server_id: str) -> ClaimResult:
        actions: list[str] = []
        warnings: list[str] = []
        resolved = 0
        snapshot = await self.discover_all()

        server = await self._repo.get(ServerId(requesting_server_id))
        requesting_port = (
            (server.properties.port.value if hasattr(server.properties, "port") else 25565)
            if server.properties
            else 25565
        )
        requesting_name = server.name

        logger.info(
            'Claiming localhost — server="%s" sid=%s port=%d reason="ownership transfer requested"',
            requesting_name,
            requesting_server_id,
            requesting_port,
        )

        other_servers = [
            a for a in snapshot.active_servers if a["server_id"] != requesting_server_id
        ]
        if other_servers:
            logger.warning(
                'Displacing %d competing server(s) for "%s" — reason="single owner required"',
                len(other_servers),
                requesting_name,
            )

        for other in other_servers:
            sid = other["server_id"]
            sname = other["server_name"]
            sport = other.get("port")
            try:
                spid = other.get("actual_pid")
                log_reason = (
                    f"server='{sname}' ({sid}) was running on port {sport} "
                    f"but '{requesting_name}' ({requesting_server_id}) needs localhost ownership"
                )
                logger.warning("Displacing competing server — %s", log_reason)

                await RuntimeSupervisor.stop_for(sid)
                actions.append(
                    f"Stopped supervisor for displaced server '{sname}' ({sid}) — {log_reason}"
                )
                resolved += 1

                displaced_server = await self._repo.get(ServerId(sid))
                provider_type = (
                    displaced_server.runtime.provider
                    if (displaced_server.runtime and displaced_server.runtime.provider)
                    else default_provider_for_platform()
                )
                provider = self._provider_factory.get(provider_type)
                ext_id = displaced_server.runtime.external_id if displaced_server.runtime else ""
                if ext_id:
                    handle = ServerHandle(
                        provider=provider_type,
                        server_id=sid,
                        external_id=ext_id,
                        metadata={
                            "server_name": sname,
                            "pid": (
                                displaced_server.runtime.pid
                                if displaced_server.runtime
                                else None
                            ),
                            "start_time": (
                                displaced_server.runtime.start_time
                                if displaced_server.runtime
                                else None
                            ),
                            "port": sport,
                        },
                    )
                    await provider.stop(handle, force=True)
                    actions.append(
                        f"Force-stopped displaced server '{sname}' ({sid}) "
                        f"via provider — {log_reason}"
                    )
                    resolved += 1

                if sport and _port_is_listening(sport):
                    released = _wait_for_port_free(sport, timeout=3.0)
                    if released:
                        actions.append(
                            f"Port {sport} released by displaced server '{sname}' ({sid})"
                        )
                    else:
                        warnings.append(
                            f"Port {sport} still listening after stopping '{sname}' ({sid})"
                        )

                if spid and _is_pid_alive(spid):
                    s_start_time = (
                        displaced_server.runtime.start_time
                        if displaced_server.runtime
                        else None
                    )
                    check = verify_process_identity(
                        spid,
                        expected_create_time=s_start_time,
                        servers_data_dir=self._servers_data_dir,
                        allow_wrapper_shell=True,
                    )
                    if not check.verified:
                        warnings.append(
                            f"Refusing to kill PID {spid} for displaced server "
                            f"'{sname}' ({sid}): identity check failed ({check.reason})"
                        )
                    else:
                        killed, reason = _try_kill_process(spid)
                        if killed:
                            actions.append(
                                f"Process PID {spid} terminated for displaced "
                                f"server '{sname}' ({sid}) — {reason}"
                            )
                        else:
                            warnings.append(
                                f"Could not terminate PID {spid} for '{sname}' ({sid}) — {reason}"
                            )
                            resolved += 1

                displaced_server.crash(
                    exit_code=-1,
                    last_log_lines=[
                        f"Displaced by runtime ownership claim from "
                        f"'{requesting_name}' ({requesting_server_id})"
                    ],
                )
                await self._repo.save(displaced_server)
                actions.append(
                    f"DB record for displaced server '{sname}' ({sid}) "
                    f"marked CRASHED — {log_reason}"
                )
                resolved += 1

            except Exception as exc:
                warn = f"Failed to fully displace server '{sname}' ({sid}): {exc}"
                warnings.append(warn)
                logger.exception("claim_localhost displacement failed — %s", warn)

        if snapshot.orphan_tmux:
            logger.warning(
                'Cleaning %d orphan tmux sessions before starting "%s"',
                len(snapshot.orphan_tmux),
                requesting_name,
            )
        for orphan in snapshot.orphan_tmux:
            try:
                reason = f"orphan tmux session {orphan.identifier} — no matching server in database"
                if orphan.pid:
                    orphan_start = getattr(orphan, "start_time", None) or (
                        orphan.details.get("start_time")
                        if hasattr(orphan, "details") and orphan.details
                        else None
                    )
                    if orphan_start is not None:
                        ownership = verify_ownership(
                            orphan.pid, stored_start_time=orphan_start
                        )
                    else:
                        ownership = verify_ownership(orphan.pid)
                    log_ownership_decision(
                        logger,
                        "KILL" if ownership.status == OwnershipStatus.VERIFIED else "SKIP",
                        f"session={orphan.identifier}",
                        orphan.pid,
                        ownership,
                        reason,
                    )
                    if ownership.status != OwnershipStatus.VERIFIED:
                        warnings.append(
                            f"Skipped orphan tmux {orphan.identifier} — "
                            f"not verified as project-owned ({ownership.detail})"
                        )
                        resolved += 1
                        continue
                killed, info = _try_kill_tmux_session(orphan.identifier)
                if killed:
                    actions.append(f"Killed orphan tmux session {orphan.identifier} — {reason}")
                else:
                    warnings.append(f"Failed to kill orphan tmux {orphan.identifier} — {info}")
                resolved += 1
            except Exception as exc:
                warnings.append(f"Failed to kill orphan tmux {orphan.identifier}: {exc}")

        if snapshot.orphan_processes:
            logger.warning(
                'Cleaning %d orphan Minecraft processes before starting "%s"',
                len(snapshot.orphan_processes),
                requesting_name,
            )
        for orphan in snapshot.orphan_processes:
            try:
                reason = (
                    f"orphan Minecraft process PID {orphan.pid} — "
                    "not attached to any managed server"
                )
                if orphan.pid:
                    orphan_start = getattr(orphan, "start_time", None) or (
                        orphan.details.get("start_time")
                        if hasattr(orphan, "details") and orphan.details
                        else None
                    )
                    if orphan_start is not None:
                        ownership = verify_ownership(
                            orphan.pid, stored_start_time=orphan_start
                        )
                    else:
                        ownership = verify_ownership(orphan.pid)
                    log_ownership_decision(
                        logger,
                        "KILL" if ownership.status == OwnershipStatus.VERIFIED else "SKIP",
                        f"pid={orphan.pid}",
                        orphan.pid,
                        ownership,
                        reason,
                    )
                    if ownership.status != OwnershipStatus.VERIFIED:
                        warnings.append(
                            f"Skipped orphan process PID {orphan.pid} — "
                            f"not verified as project-owned ({ownership.detail})"
                        )
                        resolved += 1
                        continue
                    killed, info = _try_kill_process(orphan.pid)
                    if killed:
                        actions.append(
                            f"Killed orphan Minecraft process PID {orphan.pid} — {reason}"
                        )
                    else:
                        warnings.append(f"Could not kill orphan process PID {orphan.pid} — {info}")
                resolved += 1
            except Exception as exc:
                warnings.append(f"Failed to kill orphan PID {orphan.pid}: {exc}")

        if _port_is_listening(requesting_port):
            port_pid = _pid_for_port(requesting_port)
            logger.warning(
                'Port %d occupied by PID %s before starting "%s" — reason="port must be free"',
                requesting_port,
                port_pid,
                requesting_name,
            )
            if port_pid:
                port_check = verify_process_identity(
                    port_pid, servers_data_dir=self._servers_data_dir
                )
                if not port_check.verified:
                    logger.warning(
                        "Refusing to kill process PID %s on port %d: "
                        "identity verification failed (%s)",
                        port_pid,
                        requesting_port,
                        port_check.reason,
                    )
                    warnings.append(
                        f"Port {requesting_port} is occupied by PID {port_pid} which is "
                        f"not an ONX-managed Minecraft process ({port_check.reason}); "
                        "refusing to kill"
                    )
                else:
                    killed, info = _try_kill_process(port_pid)
                    if killed:
                        actions.append(
                            f"Killed process PID {port_pid} occupying port "
                            f"{requesting_port} — {info}"
                        )
                        released = _wait_for_port_free(requesting_port, timeout=3.0)
                        if released:
                            actions.append(
                                f"Port {requesting_port} verified free after killing "
                                f"occupant PID {port_pid}"
                            )
                        else:
                            warnings.append(
                                f"Port {requesting_port} still occupied after killing "
                                f"PID {port_pid}"
                            )
                            resolved += 1
                    else:
                        warnings.append(
                            f"Could not kill PID {port_pid} occupying port "
                            f"{requesting_port} — {info}"
                        )
            else:
                warnings.append(
                    f"Port {requesting_port} is listening but owner PID could not be determined"
                )

        logger.info(
            'Localhost claim for "%s" completed — actions=%d warnings=%d resolved=%d',
            requesting_name,
            len(actions),
            len(warnings),
            resolved,
        )

        return ClaimResult(
            success=len(warnings) == 0,
            actions=actions,
            warnings=warnings,
            conflicts_resolved=resolved,
            error="; ".join(warnings) if warnings else None,
        )

    async def cleanup_orphans(
        self,
        scope: Literal["project_owned", "system_wide"] = "project_owned",
    ) -> list[dict[str, Any]]:
        snapshot = await self.discover_all()
        cleanup_actions: list[dict[str, Any]] = []
        servers_data_dir: str | None = None
        try:
            from app.modules.server.application.ownership_verifier import _get_servers_data_dir

            servers_data_dir = _get_servers_data_dir()
        except Exception:
            servers_data_dir = self._servers_data_dir

        for orphan in snapshot.orphan_tmux:
            try:
                reason = f"orphan tmux session {orphan.identifier} — no matching DB server"
                orphan_start = getattr(orphan, "start_time", None) or (
                    orphan.details.get("start_time")
                    if hasattr(orphan, "details") and orphan.details
                    else None
                )
                if scope == "project_owned" and orphan.pid:
                    if orphan_start is not None:
                        ownership = verify_ownership(
                            orphan.pid,
                            servers_data_dir,
                            stored_start_time=orphan_start,
                        )
                    else:
                        ownership = verify_ownership(orphan.pid, servers_data_dir)
                    log_ownership_decision(
                        logger,
                        "KILL" if ownership.status == OwnershipStatus.VERIFIED else "SKIP",
                        f"session={orphan.identifier}",
                        orphan.pid,
                        ownership,
                        reason,
                    )
                    if ownership.status != OwnershipStatus.VERIFIED:
                        cleanup_actions.append(
                            {
                                "type": "orphan_tmux",
                                "identifier": orphan.identifier,
                                "pid": orphan.pid,
                                "action": "skipped",
                                "reason": f"not verified as project-owned ({ownership.detail})",
                            }
                        )
                        continue
                elif scope == "system_wide" and orphan.pid:
                    check = verify_process_identity(
                        orphan.pid,
                        expected_create_time=orphan_start,
                        servers_data_dir=servers_data_dir or self._servers_data_dir,
                        allow_wrapper_shell=True,
                    )
                    if not check.verified:
                        cleanup_actions.append(
                            {
                                "type": "orphan_tmux",
                                "identifier": orphan.identifier,
                                "pid": orphan.pid,
                                "action": "skipped",
                                "reason": f"system_wide identity check failed ({check.reason})",
                            }
                        )
                        continue
                logger.warning("Cleaning orphan tmux — %s", reason)
                killed, info = _try_kill_tmux_session(orphan.identifier)
                cleanup_actions.append(
                    {
                        "type": "orphan_tmux",
                        "identifier": orphan.identifier,
                        "pid": orphan.pid,
                        "action": "killed" if killed else "failed",
                        "reason": reason,
                        "result": info,
                    }
                )
                if killed:
                    logger.info(
                        "Cleaned orphan tmux — session=%s pid=%s reason=%s",
                        orphan.identifier,
                        orphan.pid,
                        reason,
                    )
                else:
                    logger.error(
                        "Failed to clean orphan tmux — session=%s reason=%s result=%s",
                        orphan.identifier,
                        reason,
                        info,
                    )
            except Exception as exc:
                logger.exception("Exception cleaning orphan tmux %s", orphan.identifier)
                cleanup_actions.append(
                    {
                        "type": "orphan_tmux",
                        "identifier": orphan.identifier,
                        "pid": orphan.pid,
                        "action": "error",
                        "reason": str(exc),
                    }
                )

        for orphan in snapshot.orphan_processes:
            try:
                reason = (
                    f"orphan Minecraft process PID {orphan.pid} — "
                    "not attached to any managed server"
                )
                orphan_start = getattr(orphan, "start_time", None) or (
                    orphan.details.get("start_time")
                    if hasattr(orphan, "details") and orphan.details
                    else None
                )
                if scope == "project_owned" and orphan.pid:
                    if orphan_start is not None:
                        ownership = verify_ownership(
                            orphan.pid,
                            servers_data_dir,
                            stored_start_time=orphan_start,
                        )
                    else:
                        ownership = verify_ownership(orphan.pid, servers_data_dir)
                    log_ownership_decision(
                        logger,
                        "KILL" if ownership.status == OwnershipStatus.VERIFIED else "SKIP",
                        f"pid={orphan.pid}",
                        orphan.pid,
                        ownership,
                        reason,
                    )
                    if ownership.status != OwnershipStatus.VERIFIED:
                        cleanup_actions.append(
                            {
                                "type": "orphan_process",
                                "pid": orphan.pid,
                                "action": "skipped",
                                "reason": f"not verified as project-owned ({ownership.detail})",
                            }
                        )
                        continue
                elif scope == "system_wide" and orphan.pid:
                    check = verify_process_identity(
                        orphan.pid,
                        expected_create_time=orphan_start,
                        servers_data_dir=servers_data_dir or self._servers_data_dir,
                        allow_wrapper_shell=True,
                    )
                    if not check.verified:
                        cleanup_actions.append(
                            {
                                "type": "orphan_process",
                                "pid": orphan.pid,
                                "action": "skipped",
                                "reason": f"system_wide identity check failed ({check.reason})",
                            }
                        )
                        continue
                logger.warning("Cleaning orphan process — %s", reason)
                if orphan.pid:
                    killed, info = _try_kill_process(orphan.pid)
                    cleanup_actions.append(
                        {
                            "type": "orphan_process",
                            "pid": orphan.pid,
                            "action": "killed" if killed else "failed",
                            "reason": reason,
                            "result": info,
                        }
                    )
                    if killed:
                        logger.info("Cleaned orphan process — pid=%s reason=%s", orphan.pid, reason)
                    else:
                        logger.error(
                            "Failed to clean orphan process — pid=%s reason=%s result=%s",
                            orphan.pid,
                            reason,
                            info,
                        )
            except Exception:
                logger.exception("Exception cleaning orphan process PID %s", orphan.pid)

        for stale in snapshot.stale_db_records:
            sid = stale["server_id"]
            reason = f"DB marks {stale.get('status', 'RUNNING')} but no OS resources found"
            try:
                logger.warning("Cleaning stale DB record — server=%s reason=%s", sid, reason)
                server = await self._repo.get(ServerId(sid))
                server.crash(
                    exit_code=-1,
                    last_log_lines=[f"Stale DB record cleaned by orphan cleanup — {reason}"],
                )
                await self._repo.save(server)
                cleanup_actions.append(
                    {
                        "type": "stale_db_record",
                        "server_id": sid,
                        "server_name": stale.get("server_name", ""),
                        "action": "crashed",
                        "reason": reason,
                    }
                )
                logger.info("Cleaned stale DB record — server=%s reason=%s", sid, reason)
            except Exception as exc:
                logger.exception("Failed to clean stale DB record %s", sid)
                cleanup_actions.append(
                    {
                        "type": "stale_db_record",
                        "server_id": sid,
                        "action": "error",
                        "reason": str(exc),
                    }
                )

        for stale_sup in snapshot.stale_supervisors:
            sid = stale_sup["server_id"]
            reason = "server has active tmux but no supervisor — restarting supervisor"
            try:
                logger.warning("Repairing missing supervisor — server=%s reason=%s", sid, reason)
                cleanup_actions.append(
                    {
                        "type": "stale_supervisor",
                        "server_id": sid,
                        "action": "detected",
                        "reason": reason,
                    }
                )
            except Exception:
                logger.exception("Failed handling stale supervisor %s", sid)

        return cleanup_actions

    async def validate_runtime(self, server_id: str) -> ValidationChain:
        chain: list[str] = []
        result = ValidationChain(server_id=server_id)

        try:
            server = await self._repo.get(ServerId(server_id))
            sid = str(server.id)
            result.server_name = server.name
            ext_id = server.runtime.external_id if server.runtime else ""
            session_name = ext_id or f"{IDENTITY.temp_prefix_new}{sid}"
            port = (
                (server.properties.port.value if hasattr(server.properties, "port") else 25565)
                if server.properties
                else 25565
            )

            result.db_ok = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)
            chain.append(f"db={'ok' if result.db_ok else 'stale'}")

            supervisor = RuntimeSupervisor.get_for(sid)
            result.supervisor_ok = supervisor is not None and supervisor.is_running
            if supervisor is None:
                chain.append("supervisor=not_found")
            elif not supervisor.is_running:
                chain.append("supervisor=not_running")
            else:
                chain.append("supervisor=ok")

            all_tmux = _find_all_tmux_sessions()
            matching_tmux = [t for t in all_tmux if t[0] == session_name]
            result.tmux_ok = len(matching_tmux) > 0
            chain.append(f"tmux={'ok' if result.tmux_ok else 'missing'}")

            if matching_tmux and matching_tmux[0][1] and result.db_ok:
                pane_pid = matching_tmux[0][1]
                mc_pids = _find_minecraft_child_pids(pane_pid)
                result.pid_ok = len(mc_pids) > 0 or _is_pid_alive(pane_pid)
                chain.append(f"pid={'ok' if result.pid_ok else 'dead'}")
            else:
                result.pid_ok = False
                chain.append("pid=missing")

            if result.db_ok:
                result.port_ok = _port_is_listening(port)
                if result.port_ok:
                    port_pid = _pid_for_port(port)
                    result.port_owner = sid if port_pid else "unknown"
                    chain.append(f"port=ok(pid={port_pid})")
                else:
                    chain.append("port=not_listening")
            else:
                result.port_ok = False
                chain.append("port=skipped")

            if result.port_ok and result.pid_ok:
                result.minecraft_ok = True
                chain.append("minecraft=ok")
            else:
                result.minecraft_ok = False
                chain.append("minecraft=degraded")

            result.chain = chain
            result.healthy = all(
                [
                    result.db_ok,
                    result.supervisor_ok,
                    result.tmux_ok,
                    result.pid_ok,
                    result.port_ok,
                    result.minecraft_ok,
                ]
            )

        except Exception as exc:
            result.chain.append(f"error={exc}")

        return result


async def resolve_docker_host_rcon_port(
    server: Server,
    provider: Any,
    server_dir: str | None = None,
) -> int | None:
    """Resolve a non-colliding loopback host RCON port for a Docker server start."""
    from pathlib import Path

    from sqlalchemy import select

    from app.core.persistence.db import database
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.server.infrastructure.providers.docker import (
        _read_persisted_rcon_port,
        allocate_host_rcon_port,
    )

    resolved_dir = server_dir or (
        server.deployment.server_directory() if server.deployment else None
    )
    if not resolved_dir:
        return None
    props_file = Path(resolved_dir) / "server.properties"
    if not props_file.is_file():
        return None

    props: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for raw_line in props_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()

    if props.get("enable-rcon", "").lower() not in ("true", "yes", "1"):
        return None

    container_rcon_port = 25575
    with contextlib.suppress(TypeError, ValueError):
        container_rcon_port = int(props.get("rcon.port", "25575"))

    sid = str(server.id)
    reserved_ports: set[int] = set()

    for cache_attr in ("_rcon_cache", "_rcon_info"):
        cache = getattr(provider, cache_attr, None)
        if isinstance(cache, dict):
            for other_sid, entry in cache.items():
                if other_sid == sid or not isinstance(entry, dict):
                    continue
                with contextlib.suppress(TypeError, ValueError):
                    if entry.get("port") is not None:
                        reserved_ports.add(int(entry["port"]))

    with contextlib.suppress(Exception):
        from app.modules.versioning.infrastructure.port_allocator import (
            _ports_from_mapping,
            async_get_live_docker_published_ports,
        )

        # Cross-check live published ports on all running Docker containers
        live_docker_ports = await async_get_live_docker_published_ports(
            exclude_containers={
                f"{IDENTITY.temp_prefix_new}{sid}",
                f"{IDENTITY.temp_prefix_legacy}{sid}",
            }
        )
        reserved_ports.update(live_docker_ports)

        async with database.session_factory() as session:
            srv_rows = (await session.execute(select(ServerModel))).scalars().all()
            valid_server_ids = {r.id for r in srv_rows}
            for row in srv_rows:
                if row.id == sid:
                    continue
                if row.port is not None:
                    reserved_ports.add(int(row.port))
                if row.deployment_port is not None:
                    reserved_ports.add(int(row.deployment_port))
                if row.status in ("starting", "running"):
                    persisted_rcon = (
                        _read_persisted_rcon_port(row.root_path) if row.root_path else None
                    )
                    if persisted_rcon is not None:
                        reserved_ports.add(persisted_rcon)
                    elif row.port is not None:
                        reserved_ports.add(25575 + (int(row.port) - 25565))

            from app.modules.versioning.infrastructure.models import (
                ServerBranchModel,
                ServerRuntimeModel,
                ServerTestRunModel,
            )

            for branch in (await session.execute(select(ServerBranchModel))).scalars().all():
                if valid_server_ids and branch.server_id not in valid_server_ids:
                    continue
                if getattr(branch, "status", None) in ("archived", "deleted"):
                    continue
                if getattr(branch, "runtime_status", None) in ("crashed", "terminated"):
                    continue
                reserved_ports.update(_ports_from_mapping(getattr(branch, "port_set_json", None)))
            for rt in (await session.execute(select(ServerRuntimeModel))).scalars().all():
                if valid_server_ids and rt.server_id not in valid_server_ids:
                    continue
                if getattr(rt, "status", None) in ("starting", "running"):
                    if getattr(rt, "port", None) is not None:
                        reserved_ports.add(int(rt.port))
                    reserved_ports.update(_ports_from_mapping(getattr(rt, "port_set_json", None)))
            for run in (await session.execute(select(ServerTestRunModel))).scalars().all():
                if valid_server_ids and run.server_id not in valid_server_ids:
                    continue
                if getattr(run, "status", None) in ("PENDING", "BOOTING", "RUNNING"):
                    if getattr(run, "ephemeral_port", None) is not None:
                        reserved_ports.add(int(run.ephemeral_port))
                    reserved_ports.update(_ports_from_mapping(getattr(run, "port_set_json", None)))

    return allocate_host_rcon_port(
        game_port=server.properties.port.value,
        preferred_rcon_port=container_rcon_port,
        reserved_ports=reserved_ports,
        check_os=True,
    )
