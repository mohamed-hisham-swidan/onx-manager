"""Resolve the Files API root for an Advanced branch worktree (P2-4).

The Files API is branch-aware only for servers with the native Git repository
created by P2-2. Simple servers and legacy DB-only Advanced servers keep the
live deployment root; repositories without a checked-out worktree are rejected
instead of silently falling back to the live root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import ConflictError, NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.infrastructure.git_repository import MAIN_BRANCH


@dataclass(frozen=True)
class BranchFilesRoot:
    """Filesystem scope and write policy for one branch."""

    branch: str
    root_path: Path
    read_only: bool


class GetBranchFilesRootQuery(Query):
    server_id: str
    branch: str | None = None


class GetBranchFilesRootHandler(QueryHandler[GetBranchFilesRootQuery]):
    async def handle(self, query: GetBranchFilesRootQuery) -> BranchFilesRoot | None:
        from app.core.persistence.db import database
        from app.modules.server.domain.value_objects import ServerMode
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.application.git_branch_adapter import git_branch_context

        async with database.session_factory() as session:
            server = await SQLServerRepository(session).get(ServerId(query.server_id))

        if server is None:
            raise NotFoundError(f"Server '{query.server_id}' not found")

        if server.mode != ServerMode.ADVANCED:
            return None

        context = git_branch_context(server)
        if context is None:
            if query.branch is None:
                return None
            raise ConflictError("Branch-scoped Files require a native Git repository")

        name = query.branch or MAIN_BRANCH
        branch = context.service.get_branch(str(server.id), context.server_root, name)
        if branch is None:
            raise NotFoundError(f"Branch '{name}' not found")
        if branch.worktree_path is None:
            raise ConflictError(
                f"Branch '{name}' has no active worktree; restore or recreate it first"
            )

        return BranchFilesRoot(
            branch=branch.name,
            root_path=branch.worktree_path,
            read_only=branch.name == MAIN_BRANCH,
        )


__all__ = ["BranchFilesRoot", "GetBranchFilesRootHandler", "GetBranchFilesRootQuery"]
