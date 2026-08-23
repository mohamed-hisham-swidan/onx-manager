from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.event_bus import DomainEvent, EventBus
from app.core.persistence.db import database
from app.modules.monitoring.domain.aggregate import MetricPoint
from app.modules.monitoring.infrastructure.rcon_client import (
    PersistentRCONClient,
    parse_player_count,
    parse_tps,
)
from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(__name__)

_HAS_PSUTIL = False
try:
    import psutil as _psutil

    _HAS_PSUTIL = True
    _PSUTIL_PROC_ERRORS: tuple[type[BaseException], ...] = (
        _psutil.NoSuchProcess,
        _psutil.AccessDenied,
        OSError,
    )
except ImportError:
    _PSUTIL_PROC_ERRORS = (OSError,)


@dataclass
class ServerMetrics:
    server_id: str
    tps: float | None = None
    players: int = 0
    ram_used_mb: float = 0.0
    cpu_percent: float = 0.0
    uptime_seconds: float = 0.0
    world_size_bytes: int = 0


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _resolve_properties_path(properties_path: str) -> Path:
    p = Path(properties_path)
    if p.is_absolute():
        return p
    if p.exists():
        return p.resolve()
    backend_relative = _BACKEND_DIR / p
    if backend_relative.exists():
        return backend_relative
    return p.resolve()


def _read_server_properties(properties_path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        path = _resolve_properties_path(properties_path)
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return result


def _collect_process_metrics(
    pid: int, proc_cache: dict[int, tuple[float, Any]]
) -> tuple[float, float]:
    ram_mb = 0.0
    cpu = 0.0
    if not _HAS_PSUTIL:
        return ram_mb, cpu
    entry = proc_cache.get(pid)
    proc: Any = None
    fresh = False
    if entry is not None:
        cached_create_time, cached_proc = entry
        try:
            if cached_proc.is_running() and cached_proc.create_time() == cached_create_time:
                proc = cached_proc
            else:
                proc_cache.pop(pid, None)
        except _PSUTIL_PROC_ERRORS:
            proc_cache.pop(pid, None)
    if proc is None:
        try:
            proc = _psutil.Process(pid)
            proc_cache[pid] = (proc.create_time(), proc)
            fresh = True
        except _PSUTIL_PROC_ERRORS:
            return ram_mb, cpu
    try:
        mem = proc.memory_info()
        ram_mb = mem.rss / (1024 * 1024)
        raw_cpu = proc.cpu_percent(interval=0.1) if fresh else proc.cpu_percent(interval=0)
        core_count = _psutil.cpu_count() or 1
        cpu = raw_cpu / core_count
    except _PSUTIL_PROC_ERRORS:
        pass
    return ram_mb, cpu


async def _collect_rcon_metrics(
    client: PersistentRCONClient,
) -> tuple[float | None, int]:
    tps: float | None = None
    players = 0
    try:
        # Try NeoForge / Forge built-in TPS command first
        for cmd in ("neoforge tps", "forge tps"):
            resp = await client.send_command(cmd)
            parsed = _parse_forge_tps(resp)
            if parsed is not None:
                tps = parsed
                break

        # Fall back to Minecraft 1.20.3+ built-in 'tick query' (Vanilla, Fabric, NeoForge)
        if tps is None:
            tick_resp = await client.send_command("tick query")
            parsed = _parse_tick_query(tick_resp)
            if parsed is not None:
                tps = parsed

        # Fall back to Paper / Spigot 'tps' command
        if tps is None:
            tps_response = await client.send_command("tps")
            parsed = parse_tps(tps_response)
            if parsed is not None:
                tps = parsed

        list_response = await client.send_command("list")
        players = parse_player_count(list_response)
    except Exception as exc:
        logger.debug("RCON metrics failed: %s", exc)
    return tps, players


def _parse_tick_query(response: str) -> float | None:
    """Parse output from vanilla/Fabric/NeoForge '/tick query' command (1.20.3+).

    Examples:
    - "Target tick rate: 20.0 per second."
    - "The target tick rate is 20.0 per second. The average tick time is 0.1ms (target 50.0ms), with 20.0 ticks per second (100% of target)."
    - "The average tick time is 12.3ms, with 19.8 ticks per second"
    """
    import re
    match = re.search(r"Target tick rate:?\s*(?:is\s*)?([\d.]+)\s*per second", response, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = re.search(r"with\s+([\d.]+)\s+ticks per second", response, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = re.search(r"tick rate:?\s*(?:is\s*)?([\d.]+)\s*per second", response, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return None


def _parse_forge_tps(response: str) -> float | None:
    """Parse output from 'forge tps' or 'neoforge tps' command.

    Forge Format:
    Dim minecraft:overworld (minecraft:overworld): Mean tick time: 0.109 ms. Mean TPS: 20.000

    NeoForge Format:
    Overworld: 20.000 TPS (0.140 ms/tick)
    Overall: 20.000 TPS (0.246 ms/tick)
    """
    import re
    # Forge: Mean TPS: 20.000
    matches = re.findall(r"Mean TPS:\s*([\d.]+)", response)
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            pass

    # NeoForge: Overall: 20.000 TPS or Overworld: 20.000 TPS or <value> TPS
    matches = re.findall(r"([\d.]+)\s*TPS", response, re.IGNORECASE)
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            pass

    return None


class MetricsCollector:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        known_servers: list[str] | None = None,
        per_server_timeout: float = 15.0,
    ) -> None:
        self._event_bus = event_bus
        self._known_servers = known_servers or []
        self._per_server_timeout = per_server_timeout
        self._proc_cache: dict[int, tuple[float, Any]] = {}
        self._rcon_clients: dict[str, PersistentRCONClient] = {}

    async def close(self) -> None:
        for client in self._rcon_clients.values():
            with contextlib.suppress(Exception):
                await client.close()
        self._rcon_clients.clear()

    def set_known_servers(self, server_ids: list[str]) -> None:
        self._known_servers = list(server_ids)

    async def collect(self, server_id: str) -> ServerMetrics:
        metric = ServerMetrics(server_id=server_id)
        try:
            tps: float | None = None
            players = 0
            ram_used_mb = 0.0
            cpu_percent = 0.0

            async with database.session_factory() as session:
                server_repo = SQLServerRepository(session)
                try:
                    server = await server_repo.get(ServerId(server_id))
                    pid = server.runtime.pid

                    if pid is not None:
                        ram_used_mb, cpu_percent = _collect_process_metrics(pid, self._proc_cache)

                    rcon_host = server.runtime.host or "127.0.0.1"
                    rcon_port = 25575
                    rcon_password = ""

                    if server.deployment and server.deployment.root_path:
                        props_path = server.deployment.properties_path()
                        props = _read_server_properties(props_path)
                        if props.get("enable-rcon", "").lower() in ("true", "yes", "1"):
                            try:
                                rcon_port = int(props.get("rcon.port", "25575"))
                            except (ValueError, TypeError):
                                rcon_port = 25575
                            rcon_password = props.get("rcon.password", "")

                    if rcon_password:
                        client = self._rcon_clients.get(server_id)
                        if (
                            client is None
                            or client.host != rcon_host
                            or client.port != rcon_port
                            or client.password != rcon_password
                        ):
                            if client is not None:
                                with contextlib.suppress(Exception):
                                    await client.close()
                            client = PersistentRCONClient(rcon_host, rcon_port, rcon_password)
                            self._rcon_clients[server_id] = client
                        rcon_tps, rcon_players = await _collect_rcon_metrics(client)
                        tps = rcon_tps
                        players = rcon_players
                    else:
                        stale = self._rcon_clients.pop(server_id, None)
                        if stale is not None:
                            with contextlib.suppress(Exception):
                                await stale.close()

                except Exception:
                    logger.debug("Server lookup failed for %s, using defaults", server_id)

            point = MetricPoint(
                tps=tps,
                players=players,
                ram_used_mb=ram_used_mb,
                cpu_percent=cpu_percent,
                timestamp=datetime.now(timezone.utc),
            )

            metric = ServerMetrics(
                server_id=server_id,
                tps=point.tps,
                players=players,
                ram_used_mb=ram_used_mb,
                cpu_percent=cpu_percent,
            )

            async with database.session_factory() as session:
                repo = SQLMetricRepository(session)
                sid = ServerId(server_id)
                await repo.record(sid, point)
                await session.commit()

            if self._event_bus:
                await self._event_bus.publish(
                    MetricCollectedEvent(
                        server_id=server_id,
                        tps=metric.tps,
                        players=metric.players,
                        ram_mb=metric.ram_used_mb,
                        cpu=metric.cpu_percent,
                    ),
                )

        except Exception as e:
            logger.warning("Metrics collection failed for %s: %s", server_id, e)

        return metric

    async def collect_all(self) -> dict[str, ServerMetrics]:
        async def collect_one(server_id: str) -> ServerMetrics:
            try:
                return await asyncio.wait_for(
                    self.collect(server_id),
                    timeout=self._per_server_timeout,
                )
            except TimeoutError:
                logger.warning("Metrics collection timed out for %s", server_id)
                return ServerMetrics(server_id=server_id)

        if not self._known_servers:
            return {}
        collected = await asyncio.gather(
            *(collect_one(server_id) for server_id in self._known_servers)
        )
        return {m.server_id: m for m in collected}


class MetricCollectedEvent(DomainEvent):
    server_id: str
    tps: float | None = None
    players: int = 0
    ram_mb: float = 0.0
    cpu: float = 0.0
