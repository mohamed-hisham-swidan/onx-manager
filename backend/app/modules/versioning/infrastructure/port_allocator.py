"""Atomic host port-set allocator for P4."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import socket
import subprocess
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select

from app.core.exceptions import (
    DuplicatePortSetError,
    PortAllocationExhaustedError,
    ServerModeVersioningDisabledError,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerRuntimeModel,
    ServerTestRunModel,
)

logger = logging.getLogger(__name__)

_ALLOCATED_PORTS: set[int] = set()
_DOCKER_PUBLISHED_PORT_RE = re.compile(
    r"(?:(?:\[[0-9a-fA-F:]+\]|[\d.]+):)?(\d+)(?:-(\d+))?->"
)


def parse_docker_published_ports(ports_spec: str) -> set[int]:
    """Parse published host ports from a Docker ``{{.Ports}}`` string."""
    ports: set[int] = set()
    if not ports_spec:
        return ports
    for match in _DOCKER_PUBLISHED_PORT_RE.finditer(ports_spec):
        with contextlib.suppress(TypeError, ValueError):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if 1 <= start <= 65535 and 1 <= end <= 65535 and end >= start:
                # Guard against absurdly wide ranges
                if end - start <= 1024:
                    ports.update(range(start, end + 1))
                else:
                    ports.add(start)
    return ports


def get_live_docker_published_ports(
    exclude_containers: set[str] | None = None,
) -> set[int]:
    """Query running Docker containers for all currently published host ports.

    Fails open (returns ``set()``) if Docker is unavailable or times out.
    """
    excluded = {c.strip() for c in (exclude_containers or ()) if c}
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0 or not proc.stdout:
        return set()

    ports: set[int] = set()
    for line in proc.stdout.splitlines():
        if "\t" in line:
            name, port_spec = line.split("\t", 1)
            if name.strip() in excluded:
                continue
        else:
            port_spec = line
        ports.update(parse_docker_published_ports(port_spec))
    return ports


async def async_get_live_docker_published_ports(
    exclude_containers: set[str] | None = None,
) -> set[int]:
    """Async wrapper around ``get_live_docker_published_ports``."""
    return await asyncio.to_thread(get_live_docker_published_ports, exclude_containers)


def is_host_port_free(port: int) -> bool:
    """Probe TCP/UDP availability without SO_REUSEADDR masking."""
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
    return probe_os_port_free(port)


def probe_os_port_free(port: int) -> bool:
    """Best-effort TCP/UDP bind probe on 127.0.0.1 and 0.0.0.0 without SO_REUSEADDR."""
    for host in ("127.0.0.1", "0.0.0.0"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError:
            return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("0.0.0.0", port))
    except OSError:
        return False
    return True


def _ports_from_mapping(data: Any) -> set[int]:
    ports: set[int] = set()
    if not isinstance(data, dict):
        return ports
    for key in ("game_port", "rcon_port", "query_port"):
        value = data.get(key)
        if value is not None:
            with contextlib.suppress(TypeError, ValueError):
                ports.add(int(value))
    plugin_ports = data.get("plugin_ports")
    if isinstance(plugin_ports, dict):
        for value in plugin_ports.values():
            with contextlib.suppress(TypeError, ValueError):
                ports.add(int(value))
    return ports


async def _collect_reserved_ports(
    session: Any,
    *,
    exclude_branch_id: str | None = None,
    exclude_runtime_id: str | None = None,
    exclude_server_id: str | None = None,
    include_docker_ports: bool = False,
) -> set[int]:
    from app.modules.server.infrastructure.providers.docker import _read_persisted_rcon_port

    reserved: set[int] = set()

    result = await session.execute(select(ServerModel))
    servers = result.scalars().all()
    for server in servers:
        if exclude_server_id is not None and server.id == exclude_server_id:
            continue
        if getattr(server, "port", None) is not None:
            reserved.add(int(server.port))
        if getattr(server, "deployment_port", None) is not None:
            reserved.add(int(server.deployment_port))
        # Reserve active server RCON port (persisted or deterministic offset)
        if getattr(server, "status", None) in ("starting", "running"):
            root_path = getattr(server, "root_path", None)
            persisted_rcon = _read_persisted_rcon_port(root_path) if root_path else None
            if persisted_rcon is not None:
                reserved.add(persisted_rcon)
            elif getattr(server, "port", None) is not None:
                reserved.add(25575 + (int(server.port) - 25565))
            else:
                reserved.add(25575)

    result = await session.execute(select(ServerBranchModel))
    for branch in result.scalars().all():
        if exclude_branch_id is not None and branch.id == exclude_branch_id:
            continue
        if getattr(branch, "status", None) in ("archived", "deleted"):
            continue
        if getattr(branch, "runtime_status", None) in ("crashed", "terminated"):
            continue
        reserved.update(_ports_from_mapping(getattr(branch, "port_set_json", None)))

    result = await session.execute(select(ServerRuntimeModel))
    for runtime in result.scalars().all():
        if exclude_runtime_id is not None and runtime.id == exclude_runtime_id:
            continue
        status = getattr(runtime, "status", None)
        if status not in ("starting", "running"):
            continue
        if getattr(runtime, "port", None) is not None:
            reserved.add(int(runtime.port))
        reserved.update(_ports_from_mapping(getattr(runtime, "port_set_json", None)))

    result = await session.execute(select(ServerTestRunModel))
    for run in result.scalars().all():
        status = getattr(run, "status", None)
        if status not in ("PENDING", "BOOTING", "RUNNING"):
            continue
        if getattr(run, "ephemeral_port", None) is not None:
            reserved.add(int(run.ephemeral_port))
        reserved.update(_ports_from_mapping(getattr(run, "port_set_json", None)))

    if include_docker_ports:
        reserved.update(await async_get_live_docker_published_ports())

    return reserved


async def validate_port_set_atomic(
    session: Any,
    candidate: HostPortSet,
    *,
    exclude_branch_id: str | None = None,
    exclude_runtime_id: str | None = None,
    check_os_ports: bool = True,
) -> None:
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
    reserved = await _collect_reserved_ports(
        session,
        exclude_branch_id=exclude_branch_id,
        exclude_runtime_id=exclude_runtime_id,
        include_docker_ports=check_os_ports,
    )
    conflicting: list[int] = []
    for port in candidate.all_host_ports():
        if port in reserved:
            conflicting.append(port)
            continue
        if check_os_ports and not is_host_port_free(port):
            conflicting.append(port)
    if conflicting:
        raise DuplicatePortSetError(
            "Duplicate port set",
            conflicting_ports=sorted(set(conflicting)),
        )


async def allocate_port_set(
    session: Any,
    *,
    include_query: bool = False,
    plugin_port_names: Sequence[str] = (),
    start_port: int = 25600,
    end_port: int = 35599,
    check_os_ports: bool = True,
) -> HostPortSet:
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
    reserved = (
        await _collect_reserved_ports(session, include_docker_ports=check_os_ports)
        | _ALLOCATED_PORTS
    )
    needed = 2 + (1 if include_query else 0) + len(plugin_port_names)

    free_ports: list[int] = []
    for port in range(start_port, end_port + 1):
        if len(free_ports) >= needed:
            break
        if port in reserved:
            continue
        if check_os_ports and not is_host_port_free(port):
            continue
        free_ports.append(port)

    if len(free_ports) < needed:
        raise PortAllocationExhaustedError("Port allocation exhausted")

    game_port = free_ports[0]
    rcon_port = free_ports[1]
    idx = 2
    query_port = None
    if include_query:
        query_port = free_ports[idx]
        idx += 1
    plugin_ports: dict[str, int] = {}
    for name in plugin_port_names:
        plugin_ports[name] = free_ports[idx]
        idx += 1

    _ALLOCATED_PORTS.update(free_ports)

    return HostPortSet(
        game_port=game_port,
        rcon_port=rcon_port,
        query_port=query_port,
        plugin_ports=plugin_ports,
    )


def release_port_set(port_set: HostPortSet | dict[str, Any] | None) -> None:
    """Remove a stopped/dead runtime's ports from the in-process allocated set."""
    if port_set is None:
        return
    try:
        if isinstance(port_set, dict):
            ports = _ports_from_mapping(port_set)
        else:
            ports = set(port_set.all_host_ports())
    except Exception:
        ports = set()
    _ALLOCATED_PORTS.difference_update(ports)


async def reclaim_dead_port_reservations(session: Any) -> dict[str, int]:
    """Reclaim dead/orphaned port reservations across servers, branches, runtimes, and test runs.

    Safe to run during startup reconciliation and maintenance. Tolerates missing
    tables via nested savepoints.
    """
    from sqlalchemy.exc import OperationalError

    from app.modules.exposure.infrastructure.models import ServerRegisteredPortModel
    from app.modules.server.infrastructure.providers.docker import _remove_persisted_rcon_port

    summary: dict[str, int] = {
        "orphaned_branches": 0,
        "orphaned_runtimes": 0,
        "orphaned_test_runs": 0,
        "orphaned_registered_ports": 0,
        "cleared_dead_port_sets": 0,
        "healed_deployment_ports": 0,
        "cleared_rcon_files": 0,
    }

    servers = (await session.execute(select(ServerModel))).scalars().all()
    valid_server_ids = {s.id for s in servers}

    # 1. Heal stale deployment_port and remove stale RCON files for non-active servers
    for srv in servers:
        if srv.status not in ("running", "starting", "stopping"):
            if srv.port is not None and srv.deployment_port != srv.port:
                srv.deployment_port = srv.port
                summary["healed_deployment_ports"] += 1
            if srv.root_path:
                from pathlib import Path

                rcon_file = Path(srv.root_path) / ".onx-manager" / "rcon-runtime.json"
                if rcon_file.is_file():
                    _remove_persisted_rcon_port(srv.root_path)
                    summary["cleared_rcon_files"] += 1

    async def _run_nested(fn: Any) -> None:
        try:
            async with session.begin_nested():
                await fn()
        except OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise

    # 2. Delete orphaned registered ports for deleted servers
    async def _clean_registered_ports() -> None:
        stmt = (
            delete(ServerRegisteredPortModel).where(
                ServerRegisteredPortModel.server_id.not_in(valid_server_ids)
            )
            if valid_server_ids
            else delete(ServerRegisteredPortModel)
        )
        res = await session.execute(stmt)
        summary["orphaned_registered_ports"] = res.rowcount or 0

    await _run_nested(_clean_registered_ports)

    # 3. Reclaim orphaned & dead ServerRuntimeModel rows
    async def _clean_runtimes() -> None:
        runtimes = (await session.execute(select(ServerRuntimeModel))).scalars().all()
        orphan_ids: list[str] = []
        for rt in runtimes:
            if rt.server_id not in valid_server_ids:
                release_port_set(getattr(rt, "port_set_json", None))
                orphan_ids.append(rt.id)
            elif getattr(rt, "status", None) in ("crashed", "terminated"):
                if getattr(rt, "port_set_json", None) is not None:
                    release_port_set(rt.port_set_json)
                    rt.port_set_json = None
                    summary["cleared_dead_port_sets"] += 1
        if orphan_ids:
            res = await session.execute(
                delete(ServerRuntimeModel).where(ServerRuntimeModel.id.in_(orphan_ids))
            )
            summary["orphaned_runtimes"] = res.rowcount or 0

    await _run_nested(_clean_runtimes)

    # 4. Reclaim orphaned & dead ServerBranchModel rows
    async def _clean_branches() -> None:
        branches = (await session.execute(select(ServerBranchModel))).scalars().all()
        orphan_ids: list[str] = []
        for br in branches:
            if br.server_id not in valid_server_ids:
                release_port_set(getattr(br, "port_set_json", None))
                orphan_ids.append(br.id)
            elif (
                getattr(br, "status", None) in ("archived", "deleted")
                or getattr(br, "runtime_status", None) in ("crashed", "terminated")
            ):
                if getattr(br, "port_set_json", None) is not None:
                    release_port_set(br.port_set_json)
                    br.port_set_json = None
                    summary["cleared_dead_port_sets"] += 1
        if orphan_ids:
            res = await session.execute(
                delete(ServerBranchModel).where(ServerBranchModel.id.in_(orphan_ids))
            )
            summary["orphaned_branches"] = res.rowcount or 0

    await _run_nested(_clean_branches)

    # 5. Reclaim orphaned & terminal ServerTestRunModel port reservations
    async def _clean_test_runs() -> None:
        runs = (await session.execute(select(ServerTestRunModel))).scalars().all()
        orphan_ids: list[str] = []
        for run in runs:
            if run.server_id not in valid_server_ids:
                release_port_set(getattr(run, "port_set_json", None))
                orphan_ids.append(run.id)
            elif getattr(run, "status", None) not in ("PENDING", "BOOTING", "RUNNING"):
                if getattr(run, "port_set_json", None) is not None:
                    release_port_set(run.port_set_json)
                    run.port_set_json = None
                    summary["cleared_dead_port_sets"] += 1
        if orphan_ids:
            res = await session.execute(
                delete(ServerTestRunModel).where(ServerTestRunModel.id.in_(orphan_ids))
            )
            summary["orphaned_test_runs"] = res.rowcount or 0

    await _run_nested(_clean_test_runs)

    await session.flush()
    return summary
