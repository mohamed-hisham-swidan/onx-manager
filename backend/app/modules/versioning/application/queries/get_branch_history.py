from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.dag import traverse_history
from app.modules.versioning.domain.repository import VersioningRepository


class GetBranchHistoryQuery(Query):
    server_id: str
    branch_name: str
    limit: int = 100


class GetBranchHistoryHandler(QueryHandler[GetBranchHistoryQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetBranchHistoryQuery) -> list[dict[str, Any]]:
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
        query: GetBranchHistoryQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> list[dict[str, Any]]:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        git_context = git_branch_context(server) if server is not None else None
        if git_context is not None:
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            ref = f"refs/heads/{query.branch_name}"
            check = runner.run("show-ref", "--verify", "--quiet", ref, check=False)
            if check.returncode == 0:
                result = runner.run(
                    "log",
                    ref,
                    f"-n{query.limit}",
                    "--format=%H%x1f%P%x1f%an%x1f%aI%x1f%s%x1e",
                    check=False,
                )
                records = [r for r in result.stdout.split("\x1e") if r.strip()]
                if records:
                    out = []
                    for rec in records:
                        parts = rec.strip("\n").split("\x1f")
                        if len(parts) < 5:
                            continue
                        sha = parts[0].strip()
                        parents = [p for p in parts[1].split() if p]
                        author = parts[2].strip()
                        created = parts[3].strip()
                        subject = parts[4].strip()
                        db_commit = await versioning_repo.get_commit(sha)
                        out.append(
                            {
                                "id": sha,
                                "server_id": query.server_id,
                                "message": db_commit.message if db_commit else subject,
                                "branch_id": db_commit.branch_id if db_commit else None,
                                "parent_commit_id": parents[0] if parents else None,
                                "parent_commit_ids": parents,
                                "author_id": (db_commit.author_id if db_commit else author),
                                "world_snapshot_id": db_commit.world_snapshot_id
                                if db_commit
                                else None,
                                "created_at": created,
                                "manifest": db_commit.manifest.to_dict() if db_commit else {},
                                "snapshot_hash": sha,
                                "changes_summary": None,
                                "warnings": [],
                                "noop": False,
                            }
                        )
                    return out

        branch = await versioning_repo.get_branch_by_name(query.server_id, query.branch_name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{query.branch_name}' not found on server '{query.server_id}'"
            )

        if branch.head_commit_id is None:
            return []

        commits = await traverse_history(
            start_commit_id=branch.head_commit_id,
            get_commit_func=versioning_repo.get_commit,
            get_parents_func=versioning_repo.get_commit_parents,
            limit=query.limit,
        )

        return [
            {
                "id": c.id,
                "server_id": c.server_id,
                "message": c.message,
                "branch_id": c.branch_id,
                "parent_commit_id": c.parent_commit_id,
                "parent_commit_ids": c.parent_commit_ids,
                "author_id": c.author_id,
                "world_snapshot_id": c.world_snapshot_id,
                "created_at": c.created_at.isoformat(),
                "manifest": c.manifest.to_dict(),
            }
            for c in commits
        ]
