from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.diff import diff_trees
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import Tree
from app.modules.versioning.infrastructure.manifest_builder import ManifestBuilder


class ScanLiveChangesQuery(Query):
    server_id: str
    source: str  # commit_id or branch_name


def extract_classified_changes(source_tree: Tree, live_tree: Tree) -> list[dict[str, Any]]:
    """Diff two Trees and extract classified changes."""
    tree_diff = diff_trees(source_tree, live_tree)
    changes: list[dict[str, Any]] = []

    for path in sorted(tree_diff.configs.added.keys()):
        changes.append({"path": path, "change": "added", "classification": "tracked"})
    for path in sorted(tree_diff.configs.modified.keys()):
        changes.append({"path": path, "change": "modified", "classification": "tracked"})
    for path in sorted(tree_diff.configs.removed.keys()):
        changes.append({"path": path, "change": "removed", "classification": "tracked"})

    for mod in tree_diff.mods.added:
        fn = mod.get("filename", "")
        if fn:
            changes.append({"path": fn, "change": "added", "classification": "tracked"})
    for mod in tree_diff.mods.modified:
        fn = mod.get("filename", "")
        if fn:
            changes.append({"path": fn, "change": "modified", "classification": "tracked"})
    for mod in tree_diff.mods.removed:
        fn = mod.get("filename", "")
        if fn:
            changes.append({"path": fn, "change": "removed", "classification": "tracked"})

    changes.sort(key=lambda c: c["path"])
    return changes


class ScanLiveChangesHandler(QueryHandler[ScanLiveChangesQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: ScanLiveChangesQuery) -> dict[str, Any]:
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
        query: ScanLiveChangesQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        # Resolve source commit
        commit: ServerCommit | None = await versioning_repo.get_commit(query.source)
        if commit is None or commit.server_id != query.server_id:
            branch = await versioning_repo.get_branch_by_name(query.server_id, query.source)
            if branch is not None and branch.head_commit_id:
                commit = await versioning_repo.get_commit(branch.head_commit_id)

        if commit is None:
            raise NotFoundError(
                f"Source '{query.source}' (commit or branch) not found on server "
                f"'{query.server_id}'"
            )


        server_dir = (
            server.deployment.server_directory()
            if server.deployment
            else getattr(server, "root_path", "")
        )
        if not server_dir or not Path(server_dir).is_dir():
            return {"changes": [], "auto_commit": None}

        live_manifest = ManifestBuilder.build_manifest(
            server_dir=server_dir,
            server_type=getattr(server, "server_type", "vanilla"),
            minecraft_version=getattr(server, "minecraft_version", "1.21.1"),
        )
        live_tree = Tree.from_manifest(live_manifest)

        changes = extract_classified_changes(commit.tree, live_tree)
        return {"changes": changes, "auto_commit": None}
