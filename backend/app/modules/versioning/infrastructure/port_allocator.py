"""Atomic host port-set allocator for P4."""

from __future__ import annotations

import contextlib
import os
import socket
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

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

_ALLOCATED_PORTS: set[int] = set()


def is_host_port_free(port: int) -> bool:
    """Probe TCP/UDP availability without SO_REUSEADDR masking."""
    if os.name != "posix":
        raise ServerModeVersioningDisabledError()
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
) -> set[int]:
    reserved: set[int] = set()

    result = await session.execute(select(ServerModel))
    for server in result.scalars().all():
        if getattr(server, "port", None) is not None:
            reserved.add(int(server.port))
        if getattr(server, "deployment_port", None) is not None:
            reserved.add(int(server.deployment_port))
        # Implicit live RCON port.
        reserved.add(25575)

    result = await session.execute(select(ServerBranchModel))
    for branch in result.scalars().all():
        if exclude_branch_id is not None and branch.id == exclude_branch_id:
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
    reserved = await _collect_reserved_ports(session) | _ALLOCATED_PORTS
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
