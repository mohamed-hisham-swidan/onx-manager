"""Tests for native Git repository initialization (P2-2)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import GitRepositoryStateError, OversizedGitTrackedFileError
from app.core.host_state import (
    HostStateContainmentError,
    HostStateLayout,
    ensure_host_state_layout,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
)
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    LOCKFILE_RELPATH,
    MAIN_BRANCH,
    MAX_GIT_TRACKED_FILE_BYTES,
    PANEL_GITATTRIBUTES_CONTENT,
    GitRepositoryService,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only; Windows remains Simple-only",
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"png-payload"


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(
            LockfileFile(
                path="plugins/sample.jar",
                sha256="a" * 64,
                size=3,
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
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


def _git_bytes(repo_git: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--git-dir", str(repo_git), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
    ).stdout


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


def _populate_server(root: Path) -> None:
    _write(
        root,
        "server.properties",
        "#Minecraft server properties\r\n"
        "#Fri Nov 13 00:00:00 UTC 2026\r\n"
        "motd=Hello\r\n"
        "max-players=20\r\n"
        "server-port=25565\r\n"
        "rcon.password=secret\r\n"
        "management-server-token=secret\r\n"
        "online-mode=true\r\n",
    )
    _write(root, "config/app.yml", "enabled: true\r\n")
    _write(root, "plugins/sample/config.yml", "key: value\r\n")
    _write(root, "server-icon.png", PNG_BYTES)
    _write(root, "server.jar", b"class-a-jar-bytes")
    _write(root, "plugins/sample.jar", b"class-a-jar-bytes")
    _write(root, "ops.json", b"[]")
    _write(root, "whitelist.json", b"[]")
    _write(root, "world/level.dat", b"class-e-world")
    _write(root, "eula.txt", b"eula=true\n")
    _write(root, ".gitattributes", "* filter=evil\n")
    _write(root, "logs/latest.log", b"class-e-log")
    _write(root, ".onx/tests/legacy.txt", b"legacy-panel-data")
    # A stale server-tree lockfile must never replace the authoritative host lockfile.
    _write(root, LOCKFILE_RELPATH, b'{"format":1}\n')


def test_initialize_creates_external_repo_main_commit_and_worktree(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _populate_server(root)
    lockfile = _lockfile()

    result = GitRepositoryService(layout).initialize("srv-1", root, lockfile)

    repo_git = layout.repos / "srv-1" / "repo.git"
    assert result.status == "created"
    assert result.repo_path == repo_git
    assert result.config_path == layout.repos / "srv-1" / "gitconfig"
    assert result.worktree_path == root / ".onx" / "worktrees" / MAIN_BRANCH
    assert result.file_count == 6
    assert len(result.main_sha) == 40

    # Repository storage is outside the server tree; the server tree has no .git.
    with pytest.raises(ValueError):
        result.repo_path.relative_to(root)
    assert not (root / ".git").exists()

    assert _git(repo_git, "rev-parse", "--is-bare-repository").stdout.strip() == "true"
    assert (
        _git(repo_git, "rev-parse", f"refs/heads/{MAIN_BRANCH}").stdout.strip() == result.main_sha
    )

    expected_paths = [
        GITATTRIBUTES_RELPATH,
        "config/app.yml",
        LOCKFILE_RELPATH,
        "plugins/sample/config.yml",
        "server-icon.png",
        "server.properties",
    ]
    assert _git(repo_git, "ls-tree", "-r", "--name-only", MAIN_BRANCH).stdout.splitlines() == (
        expected_paths
    )

    committed_properties = _git(repo_git, "show", f"{MAIN_BRANCH}:server.properties").stdout
    assert committed_properties == "max-players=20\nmotd=Hello\nonline-mode=true\n"
    assert _git(repo_git, "show", f"{MAIN_BRANCH}:config/app.yml").stdout == "enabled: true\n"
    assert (
        _git(repo_git, "show", f"{MAIN_BRANCH}:{GITATTRIBUTES_RELPATH}").stdout.encode("utf-8")
        == PANEL_GITATTRIBUTES_CONTENT
    )
    assert _git(repo_git, "show", f"{MAIN_BRANCH}:{LOCKFILE_RELPATH}").stdout.encode("utf-8") == (
        dump_lockfile(lockfile)
    )
    assert _git_bytes(repo_git, "show", f"{MAIN_BRANCH}:server-icon.png") == PNG_BYTES

    assert (result.worktree_path / ".git").is_file()
    assert (result.worktree_path / ".git").read_text(encoding="utf-8").startswith("gitdir: ")
    assert _worktree_git(
        result.worktree_path, "rev-parse", "--abbrev-ref", "HEAD"
    ).stdout.strip() == (MAIN_BRANCH)
    assert _worktree_git(result.worktree_path, "status", "--porcelain").stdout == ""
    assert (result.worktree_path / "server.properties").read_text(encoding="utf-8") == (
        "max-players=20\nmotd=Hello\nonline-mode=true\n"
    )
    assert (result.worktree_path / "config/app.yml").read_text(encoding="utf-8") == (
        "enabled: true\n"
    )
    assert (result.worktree_path / ".gitattributes").read_bytes() == PANEL_GITATTRIBUTES_CONTENT
    assert (result.worktree_path / "server-icon.png").read_bytes() == PNG_BYTES
    assert not (result.worktree_path / "server.jar").exists()
    assert not (result.worktree_path / "plugins/sample.jar").exists()
    assert not (result.worktree_path / "ops.json").exists()
    assert not (result.worktree_path / "world").exists()
    assert not (result.worktree_path / "eula.txt").exists()

    assert stat.S_IMODE((layout.repos / "srv-1").stat().st_mode) == 0o700
    assert stat.S_IMODE(result.config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(repo_git.stat().st_mode) == 0o700


def test_initialize_works_with_only_lockfile_and_gitattributes(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root

    result = GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    repo_git = layout.repos / "srv-1" / "repo.git"
    assert result.status == "created"
    assert result.file_count == 2
    assert _git(repo_git, "ls-tree", "-r", "--name-only", MAIN_BRANCH).stdout.splitlines() == [
        GITATTRIBUTES_RELPATH,
        LOCKFILE_RELPATH,
    ]
    assert (result.worktree_path / LOCKFILE_RELPATH).is_file()
    assert (result.worktree_path / GITATTRIBUTES_RELPATH).is_file()


def test_initialize_is_idempotent_and_never_rewrites_main(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _write(root, "server.properties", "motd=first\n")
    service = GitRepositoryService(layout)

    first = service.initialize("srv-1", root, _lockfile())
    _write(root, "server.properties", "motd=second\n")
    second = service.initialize("srv-1", root, _lockfile())

    assert second.status == "already_initialized"
    assert second.main_sha == first.main_sha
    assert second.repo_path == first.repo_path
    assert second.worktree_path == first.worktree_path
    assert (
        _git(second.repo_path, "show", f"{MAIN_BRANCH}:server.properties").stdout == "motd=first\n"
    )
    assert (second.worktree_path / "server.properties").read_text(encoding="utf-8") == (
        "motd=first\n"
    )


def test_initialize_rejects_oversized_class_b_before_creating_repo(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _write(root, "server-icon.png", b"x" * (MAX_GIT_TRACKED_FILE_BYTES + 1))

    with pytest.raises(OversizedGitTrackedFileError) as exc_info:
        GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    error = exc_info.value
    assert error.code == "GIT_TRACKED_FILE_TOO_LARGE"
    assert error.http_status == 413
    assert error.details["path"] == "server-icon.png"
    assert error.details["size_bytes"] == MAX_GIT_TRACKED_FILE_BYTES + 1
    assert not (layout.repos / "srv-1" / "repo.git").exists()
    assert not list((layout.repos / "srv-1").glob(".stage-*"))


def test_initialize_rejects_existing_unregistered_main_worktree(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    (root / ".onx" / "worktrees" / MAIN_BRANCH).mkdir(parents=True)

    with pytest.raises(GitRepositoryStateError, match="Main worktree path already exists"):
        GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    assert not (layout.repos / "srv-1" / "repo.git").exists()


def test_repository_storage_may_not_sit_inside_server_tree(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    host_state = root / "host-state"
    layout = HostStateLayout(
        root=host_state,
        server_meta=host_state / "server-meta",
        class_c_vault=host_state / "class-c-vault",
        quarantine=host_state / "quarantine",
        lec=host_state / "lec",
        cas=host_state / "cas",
        repos=host_state / "repos",
        locks=host_state / "locks",
        journal=host_state / "journal",
    )

    with pytest.raises(HostStateContainmentError) as exc_info:
        GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    assert exc_info.value.code == "HOST_STATE_CONTAINMENT_VIOLATION"
    assert not host_state.exists()
