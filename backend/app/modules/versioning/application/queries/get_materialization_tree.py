from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    MaterializationStatus,
    PathClassification,
)


class GetMaterializationTreeQuery(Query):
    materialization_id: str
    server_id: str
    path: str = ""


class GetMaterializationTreeHandler(QueryHandler[GetMaterializationTreeQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetMaterializationTreeQuery) -> dict[str, Any]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(query, self._server_repo, self._versioning_repo)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            return await self._execute(query, server_repo, versioning_repo)

    async def _execute(
        self,
        query: GetMaterializationTreeQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        _ = server_repo
        mat = await versioning_repo.get_materialization(query.materialization_id)
        if mat is None or (mat.server_id and mat.server_id != query.server_id):
            raise NotFoundError(
                f"Materialization '{query.materialization_id}' not found on server "
                f"'{query.server_id}'"
            )

        if mat.status == MaterializationStatus.REMOVED:
            raise NotFoundError(
                f"Materialization '{query.materialization_id}' has been removed"
            )

        filter_path = os.path.normpath(query.path).replace("\\", "/") if query.path else ""
        if filter_path == ".":
            filter_path = ""

        root = Path(mat.root_path)
        entries: list[dict[str, Any]] = []

        for rel_path, classification in mat.path_classification.items():
            norm_rel = os.path.normpath(rel_path).replace("\\", "/")
            if filter_path and not (
                norm_rel == filter_path or norm_rel.startswith(f"{filter_path}/")
            ):
                continue


            target_file = root / norm_rel
            if target_file.is_file():
                origin = "materialized"
                try:
                    size_bytes = target_file.stat().st_size
                except Exception:
                    size_bytes = 0
            elif target_file.is_dir():
                origin = "materialized"
                size_bytes = 0
            else:
                if classification == PathClassification.TRACKED:
                    origin = "unavailable"
                    size_bytes = 0
                else:
                    origin = "live-ref"
                    size_bytes = 0

            entries.append(
                {
                    "path": norm_rel,
                    "classification": classification.value,
                    "size_bytes": size_bytes,
                    "origin": origin,
                }
            )

        entries.sort(key=lambda e: e["path"])
        return {"entries": entries}
