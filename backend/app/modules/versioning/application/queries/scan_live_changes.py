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

        source = (query.source or "").strip()

        from app.modules.versioning.application.git_branch_adapter import git_branch_context

        git_context = git_branch_context(server)
        if git_context is not None:
            return await self._execute_native_git(
                query, server, source, git_context, versioning_repo
            )

        # Legacy non-Git path: resolve source commit from SQLite
        commit: ServerCommit | None = await versioning_repo.get_commit(source)
        if commit is None or commit.server_id != query.server_id:
            branch = await versioning_repo.get_branch_by_name(query.server_id, source)
            if branch is not None and branch.head_commit_id:
                commit = await versioning_repo.get_commit(branch.head_commit_id)

        # Fallback to main branch if source was pseudo-source 'server' or empty
        if commit is None and source in ("server", ""):
            branch = await versioning_repo.get_branch_by_name(query.server_id, "main")
            if branch is not None and branch.head_commit_id:
                commit = await versioning_repo.get_commit(branch.head_commit_id)

        if commit is None:
            if source in ("server", "main", ""):
                return {"changes": [], "auto_commit": None}
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

    async def _execute_native_git(
        self,
        query: ScanLiveChangesQuery,
        server: Any,
        source: str,
        git_context: Any,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        # On native-Git servers, 'main' has no editable working tree; live disk
        # is governed by Deploy/Refresh & Class-C exclusions, never auto-commit.
        if source in ("", "server", "main"):
            return {"changes": [], "auto_commit": None}

        from app.core.exceptions import ValidationError

        info = None
        if "/" not in source and source:
            try:
                info = git_context.service.get_branch(
                    str(server.id), git_context.server_root, source
                )
            except ValidationError:
                info = None
        if info is None:
            # Verify source exists as a commit/branch in Git or DB
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            rev = runner.run(
                "rev-parse", "--verify", "--quiet", f"{source}^{{commit}}", check=False
            )
            if rev.returncode == 0:
                return {"changes": [], "auto_commit": None}
            db_branch = await versioning_repo.get_branch_by_name(query.server_id, source)
            db_commit = await versioning_repo.get_commit(source)
            if db_branch is not None or (
                db_commit is not None and db_commit.server_id == query.server_id
            ):
                return {"changes": [], "auto_commit": None}
            raise NotFoundError(
                f"Source '{query.source}' (commit or branch) not found on server "
                f"'{query.server_id}'"
            )

        if info.worktree_path is None or not info.worktree_path.is_dir():
            return {"changes": [], "auto_commit": None}

        runner = git_context.service.open_runner(str(server.id), git_context.server_root)
        result = runner.run(
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            cwd=info.worktree_path,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"changes": [], "auto_commit": None}

        changes: list[dict[str, Any]] = []
        for raw_line in result.stdout.splitlines():
            if len(raw_line) < 4:
                continue
            xy = raw_line[:2]
            relpath = raw_line[3:].strip()
            if " -> " in relpath:
                relpath = relpath.split(" -> ", 1)[1].strip()
            if len(relpath) >= 2 and relpath.startswith('"') and relpath.endswith('"'):
                relpath = relpath[1:-1]
            if not relpath:
                continue
            if "?" in xy or "A" in xy:
                change_type = "added"
            elif "D" in xy:
                change_type = "removed"
            else:
                change_type = "modified"
            changes.append(
                {
                    "path": relpath,
                    "change": change_type,
                    "classification": "tracked",
                }
            )

        changes.sort(key=lambda c: c["path"])
        return {"changes": changes, "auto_commit": None}
