from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


class GetServerConsoleQuery(Query):
    server_id: str
    tail: int = 100
    fallback_to_disk: bool = True


class ConsoleReadModel:
    def __init__(self, server_id: str, lines: list[str]) -> None:
        self.server_id = server_id
        self.lines = lines


def read_log_tail_from_disk(
    log_file: Path,
    tail: int = 100,
    buffer_size: int = 256 * 1024,
) -> list[str]:
    """Reads up to `tail` lines from the end of a log file safely without memory exhaustion."""
    if not log_file.is_file():
        return ["No log file exists on disk yet"]
    try:
        file_size = log_file.stat().st_size
        if file_size == 0:
            return ["No log file exists on disk yet"]
        with open(log_file, "rb") as f:
            if file_size > buffer_size:
                f.seek(file_size - buffer_size)
                chunk = f.read(buffer_size)
                lines = chunk.decode("utf-8", errors="replace").splitlines()
                if len(lines) > 1:
                    lines = lines[1:]  # Discard partial first line
            else:
                chunk = f.read()
                lines = chunk.decode("utf-8", errors="replace").splitlines()
        clean = [line.rstrip("\r\n") for line in lines]
        return clean[-tail:] if clean else ["No log file exists on disk yet"]
    except (OSError, PermissionError):
        return ["No log file exists on disk yet"]


def _normalize_crash_lines(
    raw_lines: list[str], *, prefix_error: bool = False
) -> list[str]:
    """Flatten embedded newlines in crash log entries cleanly."""
    lines: list[str] = []
    for entry in raw_lines:
        for subline in str(entry).splitlines():
            cleaned = subline.rstrip("\r")
            if cleaned.strip():
                lines.append(cleaned)
    if prefix_error and lines and not lines[0].startswith("["):
        lines[0] = f"[ERROR] {lines[0]}"
    return lines


async def _load_crash_fallback_lines(
    session: Any,
    server: Any,
    server_id: str,
) -> list[str] | None:
    """Resolve persisted crash log lines from evidence bundles, runtime, or crash events."""
    from sqlalchemy import select

    # 1. Recorded evidence crash log tail
    try:
        from app.modules.health.infrastructure.models import EvidenceBundleModel

        stmt = (
            select(EvidenceBundleModel)
            .where(EvidenceBundleModel.server_id == server_id)
            .order_by(EvidenceBundleModel.recorded_at.desc())
            .limit(1)
        )
        ev_res = await session.execute(stmt)
        ev_bundle = ev_res.scalars().first()
        if ev_bundle and ev_bundle.latest_log_tail:
            cached_lines = json.loads(ev_bundle.latest_log_tail)
            if isinstance(cached_lines, list) and cached_lines:
                normalized = _normalize_crash_lines(cached_lines)
                if normalized:
                    return normalized
    except Exception:
        pass

    # 2. In-memory cached crash log lines if present
    if server.runtime and getattr(server.runtime, "last_log_lines", None):
        normalized = _normalize_crash_lines(list(server.runtime.last_log_lines))
        if normalized:
            return normalized

    # 3. Latest ServerCrashedEvent activity log entry (covers fast-crash events)
    try:
        from app.modules.activity.infrastructure.models import ServerActivityLogModel

        act_stmt = (
            select(ServerActivityLogModel)
            .where(
                ServerActivityLogModel.server_id == server_id,
                ServerActivityLogModel.event_type == "server.crashed",
            )
            .order_by(ServerActivityLogModel.timestamp.desc())
            .limit(1)
        )
        act_res = await session.execute(act_stmt)
        act_row = act_res.scalars().first()
        if act_row and act_row.details_json:
            details = json.loads(act_row.details_json)
            event_lines = details.get("last_log_lines") if isinstance(details, dict) else None
            if isinstance(event_lines, list) and event_lines:
                normalized = _normalize_crash_lines(event_lines, prefix_error=True)
                if normalized:
                    return normalized
    except Exception:
        pass

    return None


class GetServerConsoleHandler(QueryHandler[GetServerConsoleQuery]):
    async def handle(self, query: GetServerConsoleQuery) -> ConsoleReadModel:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))

            is_active_runtime = server.status in (
                ServerStatus.STARTING,
                ServerStatus.RUNNING,
            )

            # 1. Query live or container logs if runtime has external handle
            if server.runtime and server.runtime.external_id:
                from app.modules.server.domain.value_objects import (
                    default_provider_for_platform,
                )
                from app.modules.server.infrastructure.providers import provider_factory
                from app.modules.server.infrastructure.providers.base import ServerHandle

                provider_type = server.runtime.provider or default_provider_for_platform()
                provider = provider_factory.get(provider_type)

                handle = ServerHandle(
                    provider=provider_type,
                    server_id=str(server.id),
                    external_id=server.runtime.external_id,
                )
                try:
                    lines = await provider.console(handle, tail=query.tail)
                    if lines:
                        return ConsoleReadModel(server_id=query.server_id, lines=lines)
                    if is_active_runtime:
                        # Active STARTING/RUNNING container has not emitted stdout yet:
                        # never fall back to stale crash evidence from a previous run.
                        return ConsoleReadModel(server_id=query.server_id, lines=[])
                except Exception:
                    if is_active_runtime:
                        return ConsoleReadModel(server_id=query.server_id, lines=[])

            # Server is actively booting before external_id is recorded:
            # return clean empty stream instead of stale crash logs from an earlier failure.
            if server.status == ServerStatus.STARTING:
                return ConsoleReadModel(server_id=query.server_id, lines=[])

            log_file: Path | None = None
            if query.fallback_to_disk:
                server_dir: Path | None = None
                if server.deployment and server.deployment.root_path:
                    server_dir = Path(server.deployment.server_directory())
                if not server_dir or not server_dir.is_dir():
                    from app.core.config import AppSettings

                    default_dir = Path(AppSettings().servers_data_dir).resolve() / query.server_id
                    if default_dir.is_dir():
                        server_dir = default_dir

                if server_dir and server_dir.is_dir():
                    candidate_log = server_dir / "logs" / "latest.log"
                    if candidate_log.is_file():
                        log_file = candidate_log

            # When a server crashed fast (e.g. docker start failure with no container),
            # surface crash evidence immediately rather than returning an older latest.log.
            is_fast_crash = server.status == ServerStatus.CRASHED and not (
                server.runtime and server.runtime.external_id
            )
            if is_fast_crash:
                prefer_crash_over_disk = log_file is None
                if log_file is not None and server.runtime and server.runtime.last_crash_time:
                    with contextlib.suppress(OSError):
                        prefer_crash_over_disk = (
                            log_file.stat().st_mtime < server.runtime.last_crash_time
                        )
                if prefer_crash_over_disk:
                    crash_lines = await _load_crash_fallback_lines(
                        session, server, query.server_id
                    )
                    if crash_lines:
                        return ConsoleReadModel(
                            server_id=query.server_id,
                            lines=crash_lines[-query.tail :],
                        )

            # 2. Fall back to reading logs/latest.log on disk if permitted
            if log_file is not None:
                disk_lines = read_log_tail_from_disk(
                    log_file,
                    tail=query.tail,
                )
                return ConsoleReadModel(server_id=query.server_id, lines=disk_lines)

            # 3. Fall back to recorded crash evidence / activity crash log
            crash_lines = await _load_crash_fallback_lines(session, server, query.server_id)
            if crash_lines:
                return ConsoleReadModel(
                    server_id=query.server_id,
                    lines=crash_lines[-query.tail :],
                )

            # 4. Clean empty state
            return ConsoleReadModel(
                server_id=query.server_id,
                lines=["No log file exists on disk yet"],
            )
