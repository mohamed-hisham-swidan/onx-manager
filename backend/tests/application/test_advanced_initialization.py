"""Tests for the Advanced Git bootstrap (P2-2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.exceptions import (
    CasUnsupportedPlatformError,
    SecretFileInGitForbiddenError,
    ValidationError,
)
from app.core.host_state import ensure_host_state_layout
from app.modules.server.domain.aggregate import (
    Server,
    ServerDeployment,
    ServerId,
    ServerMode,
    ServerType,
)
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
)
from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.application.advanced_initialization import (
    initialize_advanced_server,
)
from app.modules.versioning.application.lockfile_service import LockfileService

GITHUB_PAT = "ghp_" + ("A" * 36)


@pytest.fixture(autouse=True)
def _host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    host_state_dir = tmp_path / "host-state"
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(host_state_dir))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return host_state_dir


def _make_server(root: Path, *, mode: ServerMode = ServerMode.ADVANCED) -> Server:
    return Server.create(
        server_id=ServerId("srv-adv-init"),
        name="advanced-init",
        server_type=ServerType.PAPER,
        minecraft_version=MinecraftVersion.parse("1.20.4"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(None),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=ServerDeployment(
            root_path=str(root),
            working_directory=".",
            startup_jar="server.jar",
        ),
        mode=mode,
    )


def _write(root: Path, relpath: str, data: bytes | str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _populate(root: Path) -> None:
    _write(root, "server.jar", b"PK\x03\x04paper-server")
    _write(root, "server.properties", "motd=Hello\nmax-players=20\n")
    _write(root, "config/app.yml", "enabled: true\n")
    _write(root, "eula.txt", "eula=true\n")
    _write(root, "libraries/vendor/lib.jar", b"PK\x03\x04library")
    _write(root, "world/level.dat", b"level")


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Advanced Git/CAS initialization; Windows = Simple-only",
)
def test_initialize_creates_lockfile_repo_and_main_worktree(
    tmp_path: Path, _host_state: Path
) -> None:
    root = tmp_path / "server"
    root.mkdir()
    _populate(root)
    server = _make_server(root)

    result = initialize_advanced_server(server)

    assert result.server_id == "srv-adv-init"
    assert result.repository.status == "created"
    assert result.files_count == 1
    assert result.cas_ingested == 1
    assert len(result.repository.main_sha) == 40

    repo_git = _host_state / "repos" / "srv-adv-init" / "repo.git"
    assert repo_git.is_dir()
    assert (repo_git / "HEAD").is_file()

    worktree = root / ".onx" / "worktrees" / "main"
    assert (worktree / "server.properties").is_file()
    assert (worktree / "config" / "app.yml").is_file()
    assert (worktree / "onx-jars.lock.json").is_file()
    assert (worktree / ".gitattributes").is_file()
    assert not (worktree / "server.jar").exists()
    assert not (worktree / "eula.txt").exists()
    assert not (worktree / "libraries").exists()
    assert not (worktree / "world").exists()
    assert not (root / "onx-jars.lock.json").exists()

    layout = ensure_host_state_layout()
    lockfile = LockfileService(layout).read("srv-adv-init")
    assert lockfile is not None
    assert [item.path for item in lockfile.files] == ["server.jar"]
    assert lockfile.loader.id == "paper"


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Advanced Git/CAS initialization; Windows = Simple-only",
)
def test_initialize_is_idempotent_and_skips_reingest(tmp_path: Path, _host_state: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    _populate(root)
    server = _make_server(root)

    first = initialize_advanced_server(server)
    second = initialize_advanced_server(server)

    assert second.repository.status == "already_initialized"
    assert second.repository.main_sha == first.repository.main_sha
    assert second.cas_ingested == 0
    assert second.files_count == first.files_count


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Advanced Git/CAS initialization; Windows = Simple-only",
)
def test_initialize_blocks_secret_before_repository_exists(
    tmp_path: Path, _host_state: Path
) -> None:
    root = tmp_path / "server"
    root.mkdir()
    _write(root, "server.properties", "motd=Hello\n")
    _write(root, "config/app.yml", f"bot-token: {GITHUB_PAT}\n")
    server = _make_server(root)

    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        initialize_advanced_server(server)

    assert GITHUB_PAT not in str(exc_info.value)
    assert not (_host_state / "repos" / "srv-adv-init" / "repo.git").exists()
    assert not (root / ".onx" / "worktrees" / "main").exists()


def test_initialize_rejects_simple_server(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    server = _make_server(root, mode=ServerMode.SIMPLE)

    with pytest.raises(ValidationError):
        initialize_advanced_server(server)


def test_initialize_fails_closed_on_non_posix_host(
    tmp_path: Path, _host_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows = Simple-only: Advanced initialization must fail closed before Git/CAS."""
    root = tmp_path / "server"
    root.mkdir()
    _populate(root)
    server = _make_server(root)

    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(CasUnsupportedPlatformError, match="POSIX"):
        initialize_advanced_server(server)
    assert not (_host_state / "repos" / "srv-adv-init" / "repo.git").exists()
