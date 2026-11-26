from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass

from sqlalchemy import select

from app.core.query_bus import Query, QueryHandler
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository

_SUMMARY_HEX_PLUGIN_RE = re.compile(r"'([0-9a-f]{32})'", re.IGNORECASE)
_HEX_32_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_VERSION_ONLY_RE = re.compile(r"^v?\d+(?:\.\d+)+(?:[+-].*)?$", re.IGNORECASE)


def _readable_plugin_label(name: str | None, filename: str | None) -> str | None:
    clean_name = (name or "").strip()
    clean_file = (filename or "").strip()
    if clean_file:
        stem = clean_file
        for suffix in (".jar.disabled", ".jar", ".disabled"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
    else:
        stem = ""

    if clean_name and not _HEX_32_RE.fullmatch(clean_name):
        if _VERSION_ONLY_RE.fullmatch(clean_name) and stem:
            return stem
        return clean_name
    if stem:
        return stem
    return clean_file or None


class GetServerActivityQuery(Query):
    server_id: str
    limit: int = 50
    offset: int = 0
    event_type: str | None = None
    from_date: float | None = None
    to_date: float | None = None
    branch_name: str | None = None


@dataclass
class PaginatedActivityLogs:
    items: list[ServerActivityLog]
    total: int
    limit: int
    offset: int


class GetServerActivityHandler(QueryHandler[GetServerActivityQuery]):
    def __init__(self, repository: ActivityRepository | None = None) -> None:
        self._repository = repository

    async def handle(self, query: GetServerActivityQuery) -> PaginatedActivityLogs:
        repo = self._repository
        if repo is None:
            from app.modules.activity.infrastructure.repository import SQLActivityRepository

            repo = SQLActivityRepository()

        items, total = await repo.list_by_server(
            server_id=query.server_id,
            limit=query.limit,
            offset=query.offset,
            event_type=query.event_type,
            from_date=query.from_date,
            to_date=query.to_date,
            branch_name=query.branch_name,
        )
        await self._enrich_plugin_summaries(query.server_id, items)
        return PaginatedActivityLogs(
            items=items,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def _enrich_plugin_summaries(
        self,
        server_id: str,
        items: list[ServerActivityLog],
    ) -> None:
        """Replace raw 32-char hex plugin_ids in historical plugin activity logs."""
        if not items:
            return

        hex_ids: set[str] = set()
        for item in items:
            if not item.event_type.startswith("plugin."):
                continue
            details = item.details if isinstance(item.details, dict) else {}
            inline_label = _readable_plugin_label(
                details.get("name") or details.get("plugin_name"),
                details.get("filename") or details.get("file_name"),
            )
            if inline_label:
                if item.summary and _SUMMARY_HEX_PLUGIN_RE.search(item.summary):
                    item.summary = _SUMMARY_HEX_PLUGIN_RE.sub(
                        f"'{inline_label}'", item.summary
                    )
                details.setdefault("plugin_name", inline_label)
                continue

            pid = details.get("plugin_id")
            if isinstance(pid, str) and _HEX_32_RE.fullmatch(pid):
                hex_ids.add(pid)
            if item.summary:
                for match in _SUMMARY_HEX_PLUGIN_RE.finditer(item.summary):
                    hex_ids.add(match.group(1))

        if not hex_ids:
            return

        label_by_id: dict[str, str] = {}
        with contextlib.suppress(Exception):
            from app.core.persistence.db import database
            from app.modules.plugin.infrastructure.models import PluginModel

            async with database.session_factory() as session:
                stmt = select(PluginModel.id, PluginModel.name, PluginModel.filename).where(
                    PluginModel.server_id == server_id,
                    PluginModel.id.in_(list(hex_ids)),
                )
                result = await session.execute(stmt)
                for pid, name, filename in result.all():
                    label = _readable_plugin_label(name, filename)
                    if label:
                        label_by_id[str(pid)] = label

        if not label_by_id:
            return

        for item in items:
            if not item.event_type.startswith("plugin."):
                continue
            details = item.details if isinstance(item.details, dict) else {}
            pid = str(details.get("plugin_id") or "")
            if pid and pid in label_by_id:
                details.setdefault("plugin_name", label_by_id[pid])
            if item.summary:
                item.summary = _SUMMARY_HEX_PLUGIN_RE.sub(
                    lambda m: f"'{label_by_id[m.group(1)]}'"
                    if m.group(1) in label_by_id
                    else m.group(0),
                    item.summary,
                )
