from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


@dataclass(frozen=True)
class CrashReportSummary:
    filename: str
    timestamp: str
    failure_code: str
    blamed_mod: str | None
    stack_trace_snippet: str
    suggested_remediation: str
    raw_content: str

    def to_dict(self) -> dict:
        return asdict(self)


class GetServerCrashReportsQuery(Query):
    server_id: str
    limit: int = 5


class GetServerCrashReportsHandler(QueryHandler[GetServerCrashReportsQuery]):
    def __init__(self, analyzer: PatternCrashAnalyzer | None = None) -> None:
        self._analyzer = analyzer or PatternCrashAnalyzer()

    async def handle(self, query: GetServerCrashReportsQuery) -> list[CrashReportSummary]:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))
            if server is None:
                return []

            server_dir: Path | None = None
            if server.deployment and server.deployment.root_path:
                server_dir = Path(server.deployment.server_directory())
            if not server_dir or not server_dir.is_dir():
                from app.core.config import AppSettings

                default_dir = Path(AppSettings().servers_data_dir).resolve() / query.server_id
                if default_dir.is_dir():
                    server_dir = default_dir

            if not server_dir or not server_dir.is_dir():
                return []

            crash_dir = server_dir / "crash-reports"
            if not crash_dir.is_dir():
                return []

            files = [
                f
                for f in crash_dir.iterdir()
                if f.is_file() and f.suffix == ".txt" and f.name.startswith("crash-")
            ]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            summaries: list[CrashReportSummary] = []
            for f in files[: query.limit]:
                try:
                    with open(f, "rb") as fp:
                        raw_bytes = fp.read(256 * 1024)
                    content = raw_bytes.decode("utf-8", errors="replace")

                    analysis = self._analyzer.analyze_crash_content(content)

                    mtime_ts = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat()
                    ts_match = re.search(
                        r"crash-(\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2})",
                        f.name,
                    )
                    if ts_match:
                        try:
                            dt = datetime.strptime(
                                ts_match.group(1), "%Y-%m-%d_%H.%M.%S"
                            ).replace(tzinfo=UTC)
                            ts_str = dt.isoformat()
                        except ValueError:
                            ts_str = mtime_ts
                    else:
                        ts_str = mtime_ts

                    summaries.append(
                        CrashReportSummary(
                            filename=f.name,
                            timestamp=ts_str,
                            failure_code=analysis.failure_code.value,
                            blamed_mod=analysis.blamed_mod,
                            stack_trace_snippet=analysis.stack_trace_snippet,
                            suggested_remediation=analysis.suggested_remediation,
                            raw_content=content[:10000],
                        )
                    )
                except (OSError, PermissionError):
                    continue

            return summaries
