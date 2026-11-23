from __future__ import annotations

import uuid
from typing import Any

from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetServerBranchesQuery(Query):
    server_id: str


def _branch_row(branch: Any) -> dict[str, Any]:
    status = getattr(branch.status, "value", branch.status)
    policy = (
        branch.protection_policy.to_dict()
        if getattr(branch, "protection_policy", None) is not None
        else None
    )
    created_at = branch.created_at
    active_runtime_id = getattr(branch, "active_runtime_id", None)
    runtime_status = getattr(branch, "runtime_status", None) or "stopped"
    return {
        "id": branch.id,
        "server_id": branch.server_id,
        "name": branch.name,
        "head_commit_id": branch.head_commit_id,
        "created_at": created_at.isoformat()
        if hasattr(created_at, "isoformat")
        else str(created_at),
        "status": str(status),
        "is_protected": bool(branch.is_protected),
        "protection_policy": policy,
        "worktree_path": None,
        "worktree_locked": False,
        "runtime_status": runtime_status,
        "container_provisioned": bool(active_runtime_id),
        "port_set": getattr(branch, "port_set", None),
        "active_runtime_id": active_runtime_id,
        "active_commit_sha": getattr(branch, "active_commit_sha", None),
        "active_data_template_id": getattr(branch, "active_data_template_id", None),
        "pending_merge_on_restart": bool(getattr(branch, "pending_merge_on_restart", False)),
        "pending_merge_status": getattr(branch, "pending_merge_status", None),
        "pending_merge_error": getattr(branch, "pending_merge_error", None),
    }


def _with_git_metadata(server: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overlay Git refs/worktrees and keep create/delete/list 1:1 with Git."""
    from app.modules.versioning.application.git_branch_adapter import git_branch_context

    context = git_branch_context(server)
    if context is None:
        return rows

    git_branches = context.service.list_branches(str(server.id), context.server_root)
    git_by_name = {info.name: info for info in git_branches}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        if row.get("name") == "main":
            row["is_protected"] = True
        info = git_by_name.get(row["name"])
        if info is None:
            # Git is authoritative for ref existence.
            continue
        row["head_commit_id"] = info.sha
        row["worktree_path"] = str(info.worktree_path) if info.worktree_path else None
        row["worktree_locked"] = info.worktree_locked
        if info.worktree_path is not None:
            row["status"] = "active"
        merged.append(row)
        seen.add(row["name"])

    for info in git_branches:
        if info.name in seen:
            continue
        merged.append(
            {
                "id": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"onx-branch:{server.id}:{info.name}",
                    )
                ),
                "server_id": str(server.id),
                "name": info.name,
                "head_commit_id": info.sha,
                "created_at": "",
                "status": "active" if info.worktree_path is not None else "created",
                "is_protected": info.name == "main",
                "protection_policy": None,
                "worktree_path": str(info.worktree_path) if info.worktree_path else None,
                "worktree_locked": info.worktree_locked,
            }
        )

    merged.sort(key=lambda item: item["name"])
    return merged


class GetServerBranchesHandler(QueryHandler[GetServerBranchesQuery]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerBranchesQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.domain.value_objects import ServerMode
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            branches = await self._versioning_repo.list_branches(server_id=query.server_id)
            return [_branch_row(branch) for branch in branches]

        async with database.session_factory() as session:
            server = await SQLServerRepository(session).get(ServerId(query.server_id))
            repo = SQLVersioningRepository(session)
            branches = await repo.list_branches(server_id=query.server_id)
            rows = [_branch_row(branch) for branch in branches]
            if server is not None and server.mode == ServerMode.ADVANCED:
                rows = _with_git_metadata(server, rows)
        return rows
