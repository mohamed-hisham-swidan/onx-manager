"""Tests for native Git branch and worktree lifecycle (P2-2)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import (
    BranchProtectedError,
    ConflictError,
    GitRefValidationError,
    GitRepositoryStateError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    GitRepositoryService,
    RepositoryInitResult,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only; Windows remains Simple-only",
)


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


def _write(root: Path, relpath: str, data: str | bytes) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(repo_git: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--git-dir", str(repo_git), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
        text=True,
    )


def _git_check(repo_git: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--git-dir", str(repo_git), *args],
        capture_output=True,
        check=False,
        env=_git_env(),
        text=True,
    )


def _worktree_git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
        text=True,
    )


@pytest.fixture
def layout_and_root(tmp_path: Path) -> tuple[HostStateLayout, Path]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-1"
    root.mkdir(parents=True)
    return layout, root


def _initialize(layout: HostStateLayout, root: Path) -> RepositoryInitResult:
    _write(root, "server.properties", "motd=Hello\n")
    _write(root, "config/app.yml", "enabled: true\n")
    return GitRepositoryService(layout).initialize("srv-1", root, _lockfile())


def _repo_git(layout: HostStateLayout) -> Path:
    return layout.repos / "srv-1" / "repo.git"


def test_create_branch_creates_real_ref_and_worktree(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    init = _initialize(layout, root)
    service = GitBranchService(layout)

    info = service.create_branch("srv-1", root, "feature/x")

    assert info.name == "feature/x"
    assert info.sha == init.main_sha
    assert info.worktree_locked is False
    assert info.worktree_path == root / ".onx" / "worktrees" / "feature" / "x"
    assert _git(_repo_git(layout), "rev-parse", "refs/heads/feature/x").stdout.strip() == (
        init.main_sha
    )

    worktree = info.worktree_path
    assert worktree is not None
    assert (worktree / ".git").is_file()
    assert _worktree_git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == (
        "feature/x"
    )
    assert _worktree_git(worktree, "status", "--porcelain").stdout == ""
    assert (worktree / "server.properties").read_text(encoding="utf-8") == "motd=Hello\n"
    assert (worktree / "config/app.yml").read_text(encoding="utf-8") == "enabled: true\n"
    assert not (worktree / "server.jar").exists()

    branches = service.list_branches("srv-1", root)
    assert [branch.name for branch in branches] == ["feature/x", "main"]
    by_name = {branch.name: branch for branch in branches}
    assert by_name["feature/x"].worktree_path == worktree
    assert by_name["main"].worktree_path == root / ".onx" / "worktrees" / "main"
    assert by_name["main"].sha == init.main_sha


def test_create_branch_rejects_main_duplicate_and_unsafe_names(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)

    with pytest.raises(ConflictError, match="eagerly"):
        service.create_branch("srv-1", root, "main")

    service.create_branch("srv-1", root, "dev")
    with pytest.raises(ConflictError, match="already exists"):
        service.create_branch("srv-1", root, "dev")

    unsafe = (
        "bad name",
        "../escape",
        "-bad",
        "/bad",
        "bad/",
        "feat//x",
        "a/b.lock",
        "x" * 101,
        "ümlaut",
    )
    for name in unsafe:
        with pytest.raises(GitRefValidationError):
            service.create_branch("srv-1", root, name)

    assert not (root / ".onx" / "worktrees" / "escape").exists()
    assert not (root.parent / "escape").exists()


def test_create_branch_rejects_worktree_path_collisions(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)

    service.create_branch("srv-1", root, "feat")
    with pytest.raises(GitRepositoryStateError, match="collides"):
        service.create_branch("srv-1", root, "feat/nested")

    (root / ".onx" / "worktrees" / "ghost").mkdir(parents=True)
    with pytest.raises(GitRepositoryStateError, match="already exists"):
        service.create_branch("srv-1", root, "ghost")


def test_archive_removes_clean_worktree_but_keeps_ref(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)
    info = service.create_branch("srv-1", root, "feature/x")
    worktree = info.worktree_path
    assert worktree is not None

    result = service.archive_branch("srv-1", root, "feature/x")

    assert result.name == "feature/x"
    assert result.sha == info.sha
    assert result.worktree_removed is True
    assert result.ref_deleted is False
    assert not worktree.exists()
    assert not (root / ".onx" / "worktrees" / "feature").exists()
    assert _git(_repo_git(layout), "rev-parse", "refs/heads/feature/x").stdout.strip() == (info.sha)

    branches = {branch.name: branch for branch in service.list_branches("srv-1", root)}
    assert branches["feature/x"].worktree_path is None
    assert branches["feature/x"].sha == info.sha

    # Archiving an already-retired branch is idempotent for the worktree.
    again = service.archive_branch("srv-1", root, "feature/x")
    assert again.worktree_removed is False
    assert again.sha == info.sha


def test_archive_refuses_dirty_worktree_and_main(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)

    with pytest.raises(BranchProtectedError, match="main"):
        service.archive_branch("srv-1", root, "main")

    info = service.create_branch("srv-1", root, "dirty")
    worktree = info.worktree_path
    assert worktree is not None
    (worktree / "config" / "app.yml").write_text("changed: true\n", encoding="utf-8")

    with pytest.raises(GitRepositoryStateError, match="uncommitted changes"):
        service.archive_branch("srv-1", root, "dirty")
    assert worktree.exists()
    assert (worktree / "config" / "app.yml").read_text(encoding="utf-8") == "changed: true\n"

    (worktree / "untracked.txt").write_text("keep me\n", encoding="utf-8")
    _worktree_git(worktree, "checkout", "--", "config/app.yml")
    with pytest.raises(GitRepositoryStateError, match="uncommitted changes"):
        service.archive_branch("srv-1", root, "dirty")
    assert (worktree / "untracked.txt").read_text(encoding="utf-8") == "keep me\n"


def test_archive_refuses_locked_worktree(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)
    info = service.create_branch("srv-1", root, "locked")
    worktree = info.worktree_path
    assert worktree is not None
    _git(_repo_git(layout), "worktree", "lock", str(worktree))

    try:
        with pytest.raises(GitRepositoryStateError, match="locked"):
            service.archive_branch("srv-1", root, "locked")
    finally:
        _git(_repo_git(layout), "worktree", "unlock", str(worktree))

    assert worktree.exists()
    assert service.archive_branch("srv-1", root, "locked").worktree_removed is True


def test_delete_branch_requires_merged_history_and_protects_main(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _initialize(layout, root)
    service = GitBranchService(layout)
    repo_git = _repo_git(layout)

    with pytest.raises(BranchProtectedError, match="main"):
        service.delete_branch("srv-1", root, "main")

    merged = service.create_branch("srv-1", root, "merged")
    result = service.delete_branch("srv-1", root, "merged")
    assert result.ref_deleted is True
    assert result.worktree_removed is True
    assert merged.worktree_path is not None
    assert not merged.worktree_path.exists()
    assert _git_check(repo_git, "rev-parse", "--verify", "refs/heads/merged").returncode != 0

    unmerged = service.create_branch("srv-1", root, "wip")
    worktree = unmerged.worktree_path
    assert worktree is not None
    (worktree / "server.properties").write_text("motd=Changed\n", encoding="utf-8")
    _worktree_git(
        worktree,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-am",
        "wip commit",
    )

    with pytest.raises(GitRepositoryStateError, match="not merged into main"):
        service.delete_branch("srv-1", root, "wip")
    assert _git_check(repo_git, "rev-parse", "--verify", "refs/heads/wip").returncode == 0
    assert worktree.exists()


def test_branch_operations_fail_closed_without_a_repository(tmp_path: Path) -> None:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-1"
    root.mkdir(parents=True)
    service = GitBranchService(layout)

    with pytest.raises(GitRepositoryStateError, match="does not exist"):
        service.list_branches("srv-1", root)
    with pytest.raises(GitRepositoryStateError, match="does not exist"):
        service.create_branch("srv-1", root, "dev")
    with pytest.raises(GitRepositoryStateError, match="does not exist"):
        service.archive_branch("srv-1", root, "dev")
