from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.event_bus import DomainEvent, EventBus
from app.core.persistence.db import database
from app.modules.monitoring.domain.aggregate import MetricPoint
from app.modules.monitoring.infrastructure.rcon_client import (
    PersistentRCONClient,
    _clamp_tps,
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
    net_rx_mb: float = 0.0
    net_tx_mb: float = 0.0
    block_read_mb: float = 0.0
    block_write_mb: float = 0.0


@dataclass
class ContainerStats:
    name: str
    cpu_percent: float = 0.0
    ram_used_mb: float = 0.0
    net_rx_mb: float = 0.0
    net_tx_mb: float = 0.0
    block_read_mb: float = 0.0
    block_write_mb: float = 0.0


def _parse_size_str_to_mb(val: str) -> float:
    import re

    val = val.strip().lower()
    if not val:
        return 0.0
    m = re.match(r"^([\d.]+)\s*([a-z]+)?$", val)
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    if unit in ("gib", "gb"):
        return num * 1024.0
    if unit in ("mib", "mb"):
        return num
    if unit in ("kib", "kb"):
        return num / 1024.0
    if unit == "b":
        return num / (1024.0 * 1024.0)
    return num


def parse_docker_stats_output(output: str) -> dict[str, ContainerStats]:
    import json

    result: dict[str, ContainerStats] = {}
    core_count = (_psutil.cpu_count() or 1) if _HAS_PSUTIL else 1

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue

        name = data.get("Name") or data.get("Container") or ""
        if not name:
            continue

        raw_cpu = 0.0
        cpu_str = str(data.get("CPUPerc", "0")).replace("%", "").strip()
        try:
            raw_cpu = float(cpu_str)
        except ValueError:
            raw_cpu = 0.0
        cpu_percent = min(100.0, max(0.0, raw_cpu / core_count))

        mem_str = str(data.get("MemUsage", "0B"))
        used_mem_part = mem_str.split("/")[0].strip() if "/" in mem_str else mem_str
        ram_used_mb = _parse_size_str_to_mb(used_mem_part)

        net_str = str(data.get("NetIO", "0B / 0B"))
        net_parts = net_str.split("/")
        net_rx_mb = _parse_size_str_to_mb(net_parts[0]) if len(net_parts) > 0 else 0.0
        net_tx_mb = _parse_size_str_to_mb(net_parts[1]) if len(net_parts) > 1 else 0.0

        block_str = str(data.get("BlockIO", "0B / 0B"))
        block_parts = block_str.split("/")
        block_read_mb = _parse_size_str_to_mb(block_parts[0]) if len(block_parts) > 0 else 0.0
        block_write_mb = _parse_size_str_to_mb(block_parts[1]) if len(block_parts) > 1 else 0.0

        stats = ContainerStats(
            name=name,
            cpu_percent=cpu_percent,
            ram_used_mb=ram_used_mb,
            net_rx_mb=net_rx_mb,
            net_tx_mb=net_tx_mb,
            block_read_mb=block_read_mb,
            block_write_mb=block_write_mb,
        )
        result[name] = stats
        cid = data.get("Container")
        if cid and cid != name:
            result[cid] = stats

    return result


_BACKEND_DIR = Path(__file__).resolve().parents[4]


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


def _resolve_server_properties_path(
    server_id: str,
    properties_path: str | None,
    server_name: str | None = None,
) -> str | None:
    """Resolve ``server.properties`` with fallback for stale/nested ``root_path``."""
    if properties_path:
        candidate = _resolve_properties_path(properties_path)
        if candidate.is_file():
            return str(candidate)

    try:
        from app.core.config import AppSettings
        from app.modules.server.application.services.jar_service import server_dir_name

        raw_data_dir = Path(AppSettings().servers_data_dir)
        search_roots = (
            [raw_data_dir]
            if raw_data_dir.is_absolute()
            else [Path.cwd() / raw_data_dir, _BACKEND_DIR / raw_data_dir]
        )
        suffix = f"-{server_id[:8]}"
        for base_dir in search_roots:
            if not base_dir.is_dir():
                continue
            direct = base_dir / server_id / "server.properties"
            if direct.is_file():
                return str(direct)
            if server_name:
                named = base_dir / server_dir_name(server_name, server_id) / "server.properties"
                if named.is_file():
                    return str(named)
            with contextlib.suppress(OSError):
                for entry in sorted(base_dir.iterdir()):
                    if entry.is_dir() and entry.name.endswith(suffix):
                        prop_file = entry / "server.properties"
                        if prop_file.is_file():
                            return str(prop_file)
    except Exception:
        logger.debug("Fallback server.properties lookup failed for %s", server_id, exc_info=True)

    return properties_path


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


_TPS_CMD_CACHE: dict[str, str] = {}


async def _collect_rcon_metrics(
    client: PersistentRCONClient,
) -> tuple[float | None, int]:
    tps: float | None = None
    players = 0
    cache_key = f"{getattr(client, 'host', '')}:{getattr(client, 'port', '')}"
    try:
        # Order: Paper/Spigot 'tps' FIRST (avoids 1.20.3+ 'tick query' shadowing it),
        # then NeoForge/Forge, then 'tick query'. Cache working command per endpoint.
        ordered_cmds = [
            ("tps", parse_tps),
            ("neoforge tps", _parse_forge_tps),
            ("forge tps", _parse_forge_tps),
            ("tick query", _parse_tick_query),
        ]
        cached_cmd = _TPS_CMD_CACHE.get(cache_key) if cache_key != ":" else None
        if cached_cmd:
            ordered_cmds.sort(key=lambda pair: 0 if pair[0] == cached_cmd else 1)

        for cmd, parser in ordered_cmds:
            resp = await client.send_command(cmd)
            parsed = parser(resp)
            if parsed is not None:
                tps = parsed
                if cache_key != ":":
                    _TPS_CMD_CACHE[cache_key] = cmd
                break

        list_response = await client.send_command("list")
        players = parse_player_count(list_response)
    except Exception as exc:
        logger.debug("RCON metrics failed: %s", exc)
    return tps, players


def _parse_tick_query(response: str) -> float | None:
    """Parse real TPS from Minecraft 1.20.3+ '/tick query' output.

    NEVER parses 'Target tick rate: 20.0 per second' (which is the static target,
    not actual TPS). Parses explicit 'with X ticks per second' or derives real
    TPS from reported MSPT: min(20.0, 1000.0 / mspt).
    """
    import re

    match = re.search(r"with\s+([\d.]+)\s+ticks per second", response, re.IGNORECASE)
    if match:
        try:
            return _clamp_tps(float(match.group(1)))
        except ValueError:
            pass

    mspt_match = re.search(
        r"(?:average\s+(?:time\s+per\s+tick|tick\s+time)\s*(?:is|:)?\s*)([\d.]+)\s*ms",
        response,
        re.IGNORECASE,
    )
    if mspt_match:
        try:
            mspt = float(mspt_match.group(1))
            if mspt > 0:
                return _clamp_tps(min(20.0, 1000.0 / mspt))
            return 20.0
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
            return _clamp_tps(float(matches[0]))
        except ValueError:
            pass

    # NeoForge: Overall: 20.000 TPS or Overworld: 20.000 TPS or <value> TPS
    matches = re.findall(r"([\d.]+)\s*TPS", response, re.IGNORECASE)
    if matches:
        try:
            return _clamp_tps(float(matches[0]))
        except ValueError:
            pass

    return None


_CONTAINER_STATS_STALE_SECONDS = 60.0


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
        self._docker_stats_cache: dict[str, ContainerStats] = {}
        self._last_valid_container_stats: dict[str, tuple[float, ContainerStats]] = {}

    async def close(self) -> None:
        for client in self._rcon_clients.values():
            with contextlib.suppress(Exception):
                await client.close()
        self._rcon_clients.clear()

    def set_known_servers(self, server_ids: list[str]) -> None:
        self._known_servers = list(server_ids)

    async def evict_server(self, server_id: str) -> None:
        """Evict a deleted/removed server from in-memory polling and cached clients."""
        self._known_servers = [sid for sid in self._known_servers if sid != server_id]
        self._docker_stats_cache.pop(f"onx-{server_id}", None)
        self._last_valid_container_stats.pop(server_id, None)
        client = self._rcon_clients.pop(server_id, None)
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()

    async def fetch_docker_stats(self) -> dict[str, ContainerStats]:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0 and stdout:
                return parse_docker_stats_output(stdout.decode("utf-8", errors="replace"))
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await proc.wait()
            raise
        except (FileNotFoundError, TimeoutError, OSError, Exception) as exc:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
            logger.debug("docker stats batch query failed: %s", exc)
        return {}

    async def collect_test_run(self, test_id: str) -> ServerMetrics | None:
        """Collect metrics for an ephemeral test container from the docker stats cache."""
        container_name = f"onx-test-{test_id}"
        cstats = self._docker_stats_cache.get(container_name)
        if cstats is None:
            logger.debug("Test container %s not found in docker stats sweep", container_name)
            return None

        metric = ServerMetrics(
            server_id=f"test:{test_id}",
            tps=None,
            players=0,
            ram_used_mb=cstats.ram_used_mb,
            cpu_percent=cstats.cpu_percent,
            net_rx_mb=cstats.net_rx_mb,
            net_tx_mb=cstats.net_tx_mb,
            block_read_mb=cstats.block_read_mb,
            block_write_mb=cstats.block_write_mb,
        )

        if self._event_bus:
            await self._event_bus.publish(
                MetricCollectedEvent(
                    server_id=f"test:{test_id}",
                    tps=None,
                    players=0,
                    ram_mb=metric.ram_used_mb,
                    cpu=metric.cpu_percent,
                ),
            )
        return metric

    async def collect(self, server_id: str) -> ServerMetrics:
        metric = ServerMetrics(server_id=server_id)
        try:
            tps: float | None = None
            players = 0
            ram_used_mb = 0.0
            cpu_percent = 0.0
            net_rx_mb = 0.0
            net_tx_mb = 0.0
            block_read_mb = 0.0
            block_write_mb = 0.0

            container_name: str | None = None
            pid: int | None = None
            server_status: str | None = None
            rcon_host = "127.0.0.1"
            raw_props_path: str | None = None
            server_name: str | None = None
            try:
                async with database.session_factory() as session:
                    server_repo = SQLServerRepository(session)
                    server = await server_repo.get(ServerId(server_id))
                    if server is not None:
                        if isinstance(getattr(server, "name", None), str) and server.name:
                            server_name = server.name
                        raw_status = getattr(getattr(server, "status", None), "value", None)
                        if isinstance(raw_status, str):
                            server_status = raw_status
                        if server.runtime is not None:
                            raw_pid = server.runtime.pid
                            if isinstance(raw_pid, int) and not isinstance(raw_pid, bool):
                                pid = raw_pid
                            raw_ext_id = server.runtime.external_id
                            if isinstance(raw_ext_id, str) and raw_ext_id.strip():
                                container_name = raw_ext_id.strip()
                            raw_host = (
                                server.runtime.host
                                if isinstance(getattr(server.runtime, "host", None), str)
                                else ""
                            )
                            cleaned_host = raw_host.strip()
                            rcon_host = (
                                "127.0.0.1"
                                if cleaned_host in ("", "0.0.0.0", "::", "*")
                                else cleaned_host
                            )
                        if server.deployment and server.deployment.root_path:
                            raw_props_path = server.deployment.properties_path()
            except Exception:
                logger.debug("Server lookup failed for %s, using defaults", server_id)

            props_path = _resolve_server_properties_path(
                server_id, raw_props_path, server_name=server_name
            )

            # Check docker stats first for CPU/RAM/Net/Block.
            # When `docker stats` times out for a running container, never emit
            # synthetic 0.0 MB / 0.0% samples into history or WebSocket.
            cstats = None
            stats_collection_failed = False
            if container_name and container_name in self._docker_stats_cache:
                cstats = self._docker_stats_cache[container_name]

            if cstats is not None:
                ram_used_mb = cstats.ram_used_mb
                cpu_percent = cstats.cpu_percent
                net_rx_mb = cstats.net_rx_mb
                net_tx_mb = cstats.net_tx_mb
                block_read_mb = cstats.block_read_mb
                block_write_mb = cstats.block_write_mb
                self._last_valid_container_stats[server_id] = (time.monotonic(), cstats)
            elif pid is not None:
                ram_used_mb, cpu_percent = _collect_process_metrics(pid, self._proc_cache)
                if (
                    container_name
                    and ram_used_mb == 0.0
                    and cpu_percent == 0.0
                    and server_status not in ("stopped", "crashed")
                ):
                    cached = self._last_valid_container_stats.get(server_id)
                    if (
                        cached is not None
                        and (time.monotonic() - cached[0]) <= _CONTAINER_STATS_STALE_SECONDS
                    ):
                        prev = cached[1]
                        ram_used_mb = prev.ram_used_mb
                        cpu_percent = prev.cpu_percent
                        net_rx_mb = prev.net_rx_mb
                        net_tx_mb = prev.net_tx_mb
                        block_read_mb = prev.block_read_mb
                        block_write_mb = prev.block_write_mb
                    else:
                        stats_collection_failed = True
            elif container_name and server_status not in ("stopped", "crashed"):
                cached = self._last_valid_container_stats.get(server_id)
                if (
                    cached is not None
                    and (time.monotonic() - cached[0]) <= _CONTAINER_STATS_STALE_SECONDS
                ):
                    prev = cached[1]
                    ram_used_mb = prev.ram_used_mb
                    cpu_percent = prev.cpu_percent
                    net_rx_mb = prev.net_rx_mb
                    net_tx_mb = prev.net_tx_mb
                    block_read_mb = prev.block_read_mb
                    block_write_mb = prev.block_write_mb
                else:
                    stats_collection_failed = True
            elif server_status in ("stopped", "crashed"):
                self._last_valid_container_stats.pop(server_id, None)

            rcon_port = 25575
            rcon_password = ""
            if props_path:
                props = _read_server_properties(props_path)
                if props.get("enable-rcon", "").lower() in ("true", "yes", "1"):
                    try:
                        rcon_port = int(props.get("rcon.port", "25575"))
                    except (ValueError, TypeError):
                        rcon_port = 25575
                    rcon_password = props.get("rcon.password", "")

            if (
                rcon_password
                and server is not None
                and getattr(server.runtime, "provider", None) == "docker"
                and isinstance(container_name, str)
                and container_name
            ):
                with contextlib.suppress(Exception):
                    from app.modules.server.domain.value_objects import build_server_handle
                    from app.modules.server.infrastructure.providers import provider_factory

                    docker_prov = provider_factory.get("docker")
                    if hasattr(docker_prov, "resolve_rcon_endpoint"):
                        srv_dir = (
                            server.deployment.server_directory()
                            if server.deployment and server.deployment.root_path
                            else None
                        )
                        ep = await docker_prov.resolve_rcon_endpoint(
                            build_server_handle(server, "docker", server_dir=srv_dir)
                        )
                        if ep is not None:
                            rcon_host, rcon_port, rcon_password = ep

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

            point = MetricPoint(
                tps=tps,
                players=players,
                ram_used_mb=ram_used_mb,
                cpu_percent=cpu_percent,
                timestamp=datetime.now(UTC),
            )

            metric = ServerMetrics(
                server_id=server_id,
                tps=point.tps,
                players=players,
                ram_used_mb=ram_used_mb,
                cpu_percent=cpu_percent,
                net_rx_mb=net_rx_mb,
                net_tx_mb=net_tx_mb,
                block_read_mb=block_read_mb,
                block_write_mb=block_write_mb,
            )

            if stats_collection_failed:
                logger.debug(
                    "Skipping metrics persistence/broadcast for %s: container stats unavailable",
                    server_id,
                )
                return metric

            for attempt in range(3):
                try:
                    async with database.session_factory() as session:
                        repo = SQLMetricRepository(session)
                        sid = ServerId(server_id)
                        await repo.record(sid, point)
                        await session.commit()
                    break
                except Exception as exc:
                    is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    if is_lock and attempt < 2:
                        await asyncio.sleep(0.05 * (attempt + 1))
                        continue
                    if is_lock:
                        logger.warning("Metrics record dropped due to database lock: %s", exc)
                        break
                    raise

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

    async def collect_all(self, test_ids: list[str] | None = None) -> dict[str, ServerMetrics]:
        if not self._known_servers and not test_ids:
            self._docker_stats_cache = {}
            return {}

        # Batch refresh docker stats for all containers in one command
        self._docker_stats_cache = await self.fetch_docker_stats()

        results: dict[str, ServerMetrics] = {}
        if self._known_servers:
            semaphore = asyncio.Semaphore(2)

            async def collect_one(server_id: str) -> ServerMetrics:
                async with semaphore:
                    try:
                        return await asyncio.wait_for(
                            self.collect(server_id),
                            timeout=self._per_server_timeout,
                        )
                    except TimeoutError:
                        logger.warning("Metrics collection timed out for %s", server_id)
                        return ServerMetrics(server_id=server_id)

            collected = await asyncio.gather(
                *(collect_one(server_id) for server_id in self._known_servers)
            )
            for m in collected:
                results[m.server_id] = m

        if test_ids:
            for tid in test_ids:
                try:
                    tm = await self.collect_test_run(tid)
                    if tm is not None:
                        results[tm.server_id] = tm
                except Exception as exc:
                    logger.debug("Test container %s metric collection skipped: %s", tid, exc)

        return results


class MetricCollectedEvent(DomainEvent):
    server_id: str
    tps: float | None = None
    players: int = 0
    ram_mb: float = 0.0
    cpu: float = 0.0
