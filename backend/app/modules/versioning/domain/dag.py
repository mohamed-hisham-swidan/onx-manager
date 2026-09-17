from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable

from app.modules.versioning.domain.entities import ServerCommit


async def check_cycle(
    candidate_id: str,
    parent_ids: list[str],
    get_parents_func: Callable[[str], Awaitable[list[str]]],
) -> bool:
    """Checks if adding `candidate_id` with parents `parent_ids` introduces a cycle.

    A cycle exists if `candidate_id` is already an ancestor of any of its parents,
    or if candidate_id is in parent_ids.
    """
    if candidate_id in parent_ids:
        return True

    visited: set[str] = set()
    queue = deque(parent_ids)

    while queue:
        current = queue.popleft()
        if current == candidate_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        parents = await get_parents_func(current)
        for p in parents:
            if p == candidate_id:
                return True
            if p not in visited:
                queue.append(p)

    return False


async def traverse_history(
    start_commit_id: str,
    get_commit_func: Callable[[str], Awaitable[ServerCommit | None]],
    get_parents_func: Callable[[str], Awaitable[list[str]]],
    limit: int = 100,
) -> list[ServerCommit]:
    """Deterministically traverses the commit DAG starting from `start_commit_id`.

    Ordering:
    Deterministic topological/chronological order:
    Commits are collected, then sorted by (created_at DESC, id DESC).
    """
    start_commit = await get_commit_func(start_commit_id)
    if not start_commit:
        return []

    visited: set[str] = set()
    commits_by_id: dict[str, ServerCommit] = {}
    queue = deque([start_commit_id])

    while queue:
        cid = queue.popleft()
        if cid in visited:
            continue
        visited.add(cid)

        c = await get_commit_func(cid)
        if c is not None:
            commits_by_id[cid] = c
            parents = await get_parents_func(cid)
            for p in parents:
                if p not in visited:
                    queue.append(p)

    # Deterministic sort: created_at descending, then id descending
    sorted_commits = sorted(
        commits_by_id.values(),
        key=lambda commit: (commit.created_at, commit.id),
        reverse=True,
    )
    return sorted_commits[:limit]
