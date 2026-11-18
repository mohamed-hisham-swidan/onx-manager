from __future__ import annotations

from typing import Any

from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetCommitHistoryQuery(Query):
    server_id: str
    branch_id: str | None = None
    branch_name: str | None = None
    limit: int = 50


class GetCommitHistoryHandler(QueryHandler[GetCommitHistoryQuery]):
    def __init__(
        self,
        versioning_repo: VersioningRepository | None = None,
        server_repo=None,
    ) -> None:
        self._versioning_repo = versioning_repo
        self._server_repo = server_repo

    async def handle(self, query: GetCommitHistoryQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None and self._server_repo is not None:
            return await self._execute(query, self._server_repo, self._versioning_repo)

        if self._versioning_repo is not None:
            # no server repo; db-only
            repo = self._versioning_repo
            commits = await repo.list_commits(
                server_id=query.server_id, branch_id=query.branch_id, limit=query.limit
            )
            return self._map_commits(commits)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            return await self._execute(query, server_repo, versioning_repo)

    async def _execute(self, query, server_repo, versioning_repo):
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.application.git_branch_adapter import git_branch_context

        try:
            server = await server_repo.get(ServerId(query.server_id))
        except Exception:
            server = None
        git_context = git_branch_context(server) if server is not None else None

        if git_context is not None:
            runner = git_context.service.open_runner(str(server.id), git_context.server_root)
            # determine ref
            ref = None
            if query.branch_name:
                ref = f"refs/heads/{query.branch_name}"
            elif query.branch_id:
                if query.branch_id == "git:main":
                    ref = "refs/heads/main"
                else:
                    db_branch = await versioning_repo.get_branch(query.branch_id)
                    if db_branch is not None:
                        ref = f"refs/heads/{db_branch.name}"

            if ref is not None:
                check = runner.run(
                    "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False
                )
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
                                    "branch_id": db_commit.branch_id
                                    if db_commit
                                    else query.branch_id,
                                    "parent_commit_id": parents[0] if parents else None,
                                    "parent_commit_ids": parents,
                                    "author_id": db_commit.author_id if db_commit else author,
                                    "message": db_commit.message if db_commit else subject,
                                    "manifest": db_commit.manifest.to_dict() if db_commit else {},
                                    "world_snapshot_id": db_commit.world_snapshot_id
                                    if db_commit
                                    else None,
                                    "created_at": created,
                                    "snapshot_hash": sha,
                                    "changes_summary": None,
                                    "warnings": [],
                                    "noop": False,
                                }
                            )
                        return out
            else:
                result = runner.run(
                    "log",
                    "--branches",
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
                        if db_commit is not None and db_commit.server_id != query.server_id:
                            db_commit = None
                        out.append(
                            {
                                "id": sha,
                                "server_id": query.server_id,
                                "branch_id": db_commit.branch_id if db_commit else None,
                                "parent_commit_id": parents[0] if parents else None,
                                "parent_commit_ids": parents,
                                "author_id": db_commit.author_id if db_commit else author,
                                "message": db_commit.message if db_commit else subject,
                                "manifest": db_commit.manifest.to_dict() if db_commit else {},
                                "world_snapshot_id": db_commit.world_snapshot_id
                                if db_commit
                                else None,
                                "created_at": created,
                                "snapshot_hash": sha,
                                "changes_summary": None,
                                "warnings": [],
                                "noop": False,
                            }
                        )
                    return out

        # fallback db
        commits = await versioning_repo.list_commits(
            server_id=query.server_id, branch_id=query.branch_id, limit=query.limit
        )
        return self._map_commits(commits)

    def _map_commits(self, commits):
        return [
            {
                "id": c.id,
                "server_id": c.server_id,
                "branch_id": c.branch_id,
                "parent_commit_id": c.parent_commit_id,
                "parent_commit_ids": c.parent_commit_ids,
                "author_id": c.author_id,
                "message": c.message,
                "manifest": c.manifest.to_dict(),
                "world_snapshot_id": c.world_snapshot_id,
                "created_at": c.created_at.isoformat()
                if hasattr(c.created_at, "isoformat")
                else str(c.created_at),
            }
            for c in commits
        ]
