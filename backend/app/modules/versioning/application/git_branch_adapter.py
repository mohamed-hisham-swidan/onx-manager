"""Resolve the native Git repository context for branch commands.

Branch commands stay DB-only for legacy/dummy Advanced servers that have no
repository (D8). Git is authoritative only when ``repo.git`` exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.host_state import HostStateLayout, resolve_host_state_layout
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import ServerMode
from app.modules.versioning.infrastructure.git_branches import GitBranchService


@dataclass(frozen=True)
class GitBranchContext:
    """Git repository wiring for one Advanced server."""

    layout: HostStateLayout
    server_root: Path
    service: GitBranchService


def git_branch_context(server: Server) -> GitBranchContext | None:
    """Return the Git context when this server has a native repository."""
    if getattr(server, "mode", None) != ServerMode.ADVANCED:
        return None
    deployment = getattr(server, "deployment", None)
    if not deployment or not getattr(deployment, "root_path", None):
        return None

    layout = resolve_host_state_layout()
    repo_git = layout.repo_dir(str(server.id)) / "repo.git"
    if repo_git.is_symlink() or not repo_git.is_dir():
        return None

    return GitBranchContext(
        layout=layout,
        server_root=Path(os.path.abspath(deployment.server_directory())),
        service=GitBranchService(layout),
    )


__all__ = ["GitBranchContext", "git_branch_context"]
