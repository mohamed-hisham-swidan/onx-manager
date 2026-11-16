"""Native Git Save & Commit tests for P2-4 acceptance #3."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import (
    BranchProtectedError,
    ConflictError,
    OversizedGitTrackedFileError,
    SecretFileInGitForbiddenError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import (
    LoaderRef,
    LockfileV21,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    LOCKFILE_RELPATH,
    PANEL_GITATTRIBUTES_CONTENT,
    GitRepositoryService,
)
from app.modules.versioning.infrastructure.git_save_commit import (
    GitSaveCommitService,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-save-commit"
MAIN_SHA = ""


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


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> tuple[HostStateLayout, Path, Path]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / SERVER_ID
    root.mkdir(parents=True)
    _write(
        root,
        "server.properties",
        "#Minecraft server properties\r\n"
        "motd=Hello\r\n"
        "server-port=25565\r\n"
        "rcon.password=secret\r\n"
        "online-mode=true\r\n",
    )
    _write(root, "config/app.yml", "enabled: true\n")
    _write(root, "plugins/sample/config.yml", "key: value\n")
    _write(root, "server-icon.png", b"\x89PNG\r\n\x1a\npng")

    result = GitRepositoryService(layout).initialize(SERVER_ID, root, _lockfile())
    global MAIN_SHA
    MAIN_SHA = result.main_sha
    GitBranchService(layout).create_branch(SERVER_ID, root, "dev")
    worktree = root / ".onx" / "worktrees" / "dev"
    return layout, root, worktree


def _save(
    layout: HostStateLayout,
    root: Path,
    message: str = "Save branch changes",
):
    return GitSaveCommitService(layout).save(SERVER_ID, root, "dev", message)


def _head(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()


def _show(worktree: Path, relpath: str) -> str:
    return _git(worktree, "show", f"HEAD:{relpath}").stdout


def test_normalizes_server_properties_and_commits_allowed_paths(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    _write(
        worktree,
        "server.properties",
        "#Minecraft server properties\r\n"
        "#Fri Nov 13 00:00:00 UTC 2026\r\n"
        "motd=Changed\r\n"
        "server-port=25566\r\n"
        "rcon.password=another-secret\r\n"
        "management-server-token=secret\r\n"
        "max-players=30\r\n"
        "online-mode=false\r\n",
    )
    _write(worktree, "config/feature.yml", "feature: true\r\n")

    result = _save(layout, root, "Update config")

    assert result.branch_name == "dev"
    assert result.parent_commit_id == MAIN_SHA
    assert result.commit_id == _head(worktree)
    assert "server.properties" in result.files
    assert "config/feature.yml" in result.files

    properties = _show(worktree, "server.properties")
    assert properties == (
        "max-players=30\n"
        "motd=Changed\n"
        "online-mode=false\n"
    )
    assert "rcon.password" not in properties
    assert "management-server-token" not in properties
    assert _show(worktree, "config/feature.yml") == "feature: true\n"
    assert _show(worktree, GITATTRIBUTES_RELPATH) == PANEL_GITATTRIBUTES_CONTENT.decode()
    assert "rcon.password" not in _show(worktree, LOCKFILE_RELPATH)
    assert _git(worktree, "log", "-1", "--format=%s").stdout.strip() == "Update config"
    assert _git(worktree, "status", "--porcelain").stdout == ""


def test_secret_is_rejected_without_leaking_the_value(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    before = _head(worktree)
    _write(worktree, "plugins/sample/config.yml", "api-key: super-secret-value\n")

    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        _save(layout, root)

    assert exc_info.value.http_status == 422
    assert "super-secret-value" not in str(exc_info.value)
    assert "super-secret-value" not in repr(exc_info.value.details)
    assert _head(worktree) == before


@pytest.mark.parametrize(
    ("relpath", "payload"),
    [
        ("config/broken.yml", "key: [unterminated\n"),
        ("config/broken.json", '{"key": }\n'),
        ("config/broken.toml", "key = [\n"),
        ("config/markers.yml", "key: value\n<<<<<<< HEAD\nother: value\n"),
    ],
)
def test_invalid_or_conflicted_configs_are_rejected(
    repo: tuple[HostStateLayout, Path, Path],
    relpath: str,
    payload: str,
) -> None:
    layout, root, worktree = repo
    before = _head(worktree)
    _write(worktree, relpath, payload)

    with pytest.raises(ValidationError):
        _save(layout, root)

    assert _head(worktree) == before


def test_valid_multi_document_yaml_saves_cleanly(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    payload = "---\nenabled: true\n---\nmotd: Hello\n"
    _write(worktree, "config/multi.yml", payload)

    result = _save(layout, root, "Add multi-document config")

    assert "config/multi.yml" in result.files
    assert _show(worktree, "config/multi.yml") == payload


def test_multi_document_yaml_secret_in_second_document_is_rejected(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    before = _head(worktree)
    _write(
        worktree,
        "config/multi.yml",
        "---\nfoo: bar\n---\ndata:\n  password: multi-doc-secret-value\n",
    )

    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        _save(layout, root)

    assert "multi-doc-secret-value" not in str(exc_info.value)
    assert "multi-doc-secret-value" not in repr(exc_info.value.details)
    assert _head(worktree) == before
    with pytest.raises(subprocess.CalledProcessError):
        _git(worktree, "cat-file", "-e", "HEAD:config/multi.yml")


def test_malformed_multi_document_yaml_is_rejected(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    before = _head(worktree)
    _write(worktree, "config/multi.yml", "---\nkey: value\n---\n: [unclosed\n")

    with pytest.raises(ValidationError):
        _save(layout, root)

    assert _head(worktree) == before


def test_oversized_icon_is_rejected(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    _write(worktree, "server-icon.png", b"x" * (1024 * 1024 + 1))

    with pytest.raises(OversizedGitTrackedFileError) as exc_info:
        _save(layout, root)

    assert exc_info.value.http_status == 413
    assert exc_info.value.details["max_bytes"] == 1024 * 1024


def test_class_b_over_16_mib_is_rejected(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    path = worktree / "config" / "huge.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)

    with pytest.raises(OversizedGitTrackedFileError) as exc_info:
        _save(layout, root)

    assert exc_info.value.details["max_bytes"] == 16 * 1024 * 1024


def test_large_class_b_is_routed_to_cas_and_lockfile(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    payload = b"key: " + b"x" * (1024 * 1024) + b"\n"
    _write(worktree, "config/big.yml", payload)

    result = _save(layout, root)

    assert result.routed_to_cas == ("config/big.yml",)
    assert not (worktree / "config" / "big.yml").exists()
    lockfile = parse_lockfile((worktree / LOCKFILE_RELPATH).read_bytes())
    entry = next(item for item in lockfile.files if item.path == "config/big.yml")
    assert entry.size == len(payload)
    assert ArtifactCas(layout.cas).has(entry.sha256)
    assert "config/big.yml" not in result.files


def test_tracked_class_b_growth_is_routed_and_removed_from_head(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    payload = b"key: " + b"x" * (1024 * 1024) + b"\n"
    _write(worktree, "config/app.yml", payload)

    result = _save(layout, root)

    assert result.routed_to_cas == ("config/app.yml",)
    assert "config/app.yml" in result.files
    assert not (worktree / "config" / "app.yml").exists()
    lockfile = parse_lockfile((worktree / LOCKFILE_RELPATH).read_bytes())
    entry = next(item for item in lockfile.files if item.path == "config/app.yml")
    assert ArtifactCas(layout.cas).has(entry.sha256)
    with pytest.raises(subprocess.CalledProcessError):
        _git(worktree, "cat-file", "-e", "HEAD:config/app.yml")
    assert _git(worktree, "status", "--porcelain").stdout == ""


def test_class_a_jar_is_ingested_and_removed_from_worktree(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    _write(worktree, "mods/example.jar", b"jar-bytes")

    result = _save(layout, root)

    assert result.routed_to_cas == ("mods/example.jar",)
    assert not (worktree / "mods" / "example.jar").exists()
    lockfile = parse_lockfile((worktree / LOCKFILE_RELPATH).read_bytes())
    entry = next(item for item in lockfile.files if item.path == "mods/example.jar")
    assert entry.size == len(b"jar-bytes")
    assert ArtifactCas(layout.cas).has(entry.sha256)


def test_hostile_config_executable_is_quarantined_not_committed(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    _write(worktree, "config/evil.sh", "#!/bin/sh\nrm -rf /\n")
    _write(worktree, "config/app.yml", "enabled: false\n")

    result = _save(layout, root)

    assert result.quarantined == ("config/evil.sh",)
    assert not (worktree / "config" / "evil.sh").exists()
    quarantine = layout.quarantine_dir(SERVER_ID) / "config" / "evil.sh"
    assert quarantine.read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert "config/evil.sh" not in result.files
    assert "config/app.yml" in result.files


def test_class_c_and_e_changes_are_not_committed(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    _write(worktree, "config/server.pem", "-----BEGIN PRIVATE KEY-----\n")
    _write(worktree, "world/level.dat", b"world-data")
    _write(worktree, "notes.txt", "untracked")
    _write(worktree, "config/app.yml", "enabled: false\n")

    result = _save(layout, root)

    assert result.files == ("config/app.yml",)
    assert (worktree / "config" / "server.pem").exists()
    assert (worktree / "world" / "level.dat").exists()
    assert (worktree / "notes.txt").exists()
    assert _git(worktree, "status", "--porcelain").stdout != ""


def test_no_changes_returns_conflict(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, _ = repo
    with pytest.raises(ConflictError):
        _save(layout, root)


def test_main_branch_cannot_be_committed(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, _ = repo
    with pytest.raises(BranchProtectedError, match="Direct commits to branch 'main' are forbidden"):
        GitSaveCommitService(layout).save(SERVER_ID, root, "main", "Save main")


def test_deleted_lockfile_is_rejected(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, worktree = repo
    (worktree / LOCKFILE_RELPATH).unlink()

    with pytest.raises(ValidationError):
        _save(layout, root)


def test_archived_branch_cannot_be_committed(
    repo: tuple[HostStateLayout, Path, Path],
) -> None:
    layout, root, _ = repo
    GitBranchService(layout).archive_branch(SERVER_ID, root, "dev")

    with pytest.raises(ConflictError):
        _save(layout, root)
