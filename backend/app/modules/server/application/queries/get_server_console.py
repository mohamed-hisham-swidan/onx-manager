from pathlib import Path

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
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


class GetServerConsoleHandler(QueryHandler[GetServerConsoleQuery]):
    async def handle(self, query: GetServerConsoleQuery) -> ConsoleReadModel:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))

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
                except Exception:
                    pass

            # 2. Fall back to reading logs/latest.log on disk if permitted
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
                    log_file = server_dir / "logs" / "latest.log"
                    if log_file.is_file():
                        disk_lines = read_log_tail_from_disk(
                            log_file,
                            tail=query.tail,
                        )
                        return ConsoleReadModel(server_id=query.server_id, lines=disk_lines)

            # 3. Fall back to recorded evidence crash log tail
            try:
                import json

                from sqlalchemy import select

                from app.modules.health.infrastructure.models import EvidenceBundleModel

                stmt = (
                    select(EvidenceBundleModel)
                    .where(EvidenceBundleModel.server_id == query.server_id)
                    .order_by(EvidenceBundleModel.recorded_at.desc())
                    .limit(1)
                )
                ev_res = await session.execute(stmt)
                ev_bundle = ev_res.scalars().first()
                if ev_bundle and ev_bundle.latest_log_tail:
                    cached_lines = json.loads(ev_bundle.latest_log_tail)
                    if cached_lines:
                        return ConsoleReadModel(
                            server_id=query.server_id,
                            lines=cached_lines[-query.tail:],
                        )
            except Exception:
                pass

            # 4. Fall back to in-memory cached crash log lines if present
            if server.runtime and getattr(server.runtime, "last_log_lines", None):
                return ConsoleReadModel(
                    server_id=query.server_id,
                    lines=server.runtime.last_log_lines[-query.tail:],
                )

            # 5. Clean empty state
            return ConsoleReadModel(
                server_id=query.server_id,
                lines=["No log file exists on disk yet"],
            )
