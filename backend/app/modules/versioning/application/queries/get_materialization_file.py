from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from app.core.exceptions import (
    MaterializationFileTooLargeError,
    NotFoundError,
    ValidationError,
)
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    MaterializationStatus,
    PathClassification,
)

MAX_FILE_READ_BYTES = 1024 * 1024  # 1 MiB cap per spec


class GetMaterializationFileQuery(Query):
    materialization_id: str
    server_id: str
    path: str


class GetMaterializationFileHandler(QueryHandler[GetMaterializationFileQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetMaterializationFileQuery) -> dict[str, Any]:
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
        query: GetMaterializationFileQuery,
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

        norm_path = os.path.normpath(query.path).replace("\\", "/")
        if norm_path.startswith("..") or os.path.isabs(query.path):
            raise ValidationError(f"Path escapes materialization root: {query.path}")

        classification = mat.path_classification.get(norm_path)
        if classification != PathClassification.TRACKED:
            raise NotFoundError(
                f"Path '{query.path}' is not materialized (classification: {classification})"
            )

        file_path = (Path(mat.root_path) / norm_path).resolve()
        resolved_root = Path(mat.root_path).resolve()
        if not file_path.is_relative_to(resolved_root):
            raise ValidationError(f"Path escapes materialization root: {query.path}")

        if not file_path.is_file():
            raise NotFoundError(f"File '{query.path}' not found in materialization")

        size_bytes = file_path.stat().st_size
        if size_bytes > MAX_FILE_READ_BYTES:
            raise MaterializationFileTooLargeError(
                query.path, size_bytes, MAX_FILE_READ_BYTES
            )

        raw_bytes = file_path.read_bytes()
        try:
            content_str = raw_bytes.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content_str = base64.b64encode(raw_bytes).decode("ascii")
            encoding = "base64"

        return {
            "content": content_str,
            "encoding": encoding,
            "path": norm_path,
            "size_bytes": size_bytes,
        }
