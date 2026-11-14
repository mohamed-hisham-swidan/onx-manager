"""P2-5d1 disk-full policy, mountpoint, and worktree-lock tests."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    InsufficientStorageError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.application import refresh_orchestrator
from app.modules.versioning.application.refresh_orchestrator import (
    RefreshOrchestrator,
    carry_complement_entries,
    check_refresh_free_space,
    check_swap_preconditions,
    check_worktree_locks,
    required_free_bytes,
    staging_enospc_guard,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure import clean_export
from app.modules.versioning.infrastructure.clean_export import (
    EXPORT_MARKER_NAME,
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode refresh preflight is POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-disk-policy"


@pytest.fixture
def disk_env(
    tmp_path: Path,
) -> tuple[HostStateLayout, Path, CleanExportRequest]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / SERVER_ID
    root.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "app.yml").write_text("feature: true\n", encoding="utf-8")
    (root / "server.properties").write_text("motd=Live\n", encoding="utf-8")
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
        lec=None,
    )
    initialized = GitRepositoryService(layout).initialize(SERVER_ID, root, lockfile)
    request = CleanExportRequest(
        server_id=SERVER_ID,
        server_root=root,
        commit_sha=initialized.main_sha,
        destination=tmp_path / "export",
        lockfile=lockfile,
    )
    return layout, root, request


def _live_and_staging(tmp_path: Path) -> tuple[Path, Path]:
    live = tmp_path / "servers" / SERVER_ID
    live.mkdir(parents=True, exist_ok=True)
    (live / "server.properties").write_text("motd=Live\n", encoding="utf-8")
    staging = tmp_path / "servers" / f"{SERVER_ID}.staging"
    return live, staging


# ----------------------------------------------------------------------
# Total free-space preflight
# ----------------------------------------------------------------------


def test_required_free_bytes_applies_headroom() -> None:
    assert required_free_bytes(0) == 0
    assert required_free_bytes(1000) == 1100
    assert required_free_bytes(1001) == 1102


def test_preflight_rejects_below_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, _staging = _live_and_staging(tmp_path)
    monkeypatch.setattr(refresh_orchestrator, "_free_bytes", lambda _path: 1099)
    with pytest.raises(InsufficientStorageError) as exc:
        check_refresh_free_space(live, export_bytes=1000)
    assert exc.value.http_status == 507
    assert exc.value.details["required_bytes"] == 1100
    assert exc.value.details["free_bytes"] == 1099

    monkeypatch.setattr(refresh_orchestrator, "_free_bytes", lambda _path: 1100)
    assert check_refresh_free_space(live, export_bytes=1000) == 1100


def test_preflight_counts_every_budget_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, _staging = _live_and_staging(tmp_path)
    monkeypatch.setattr(refresh_orchestrator, "_free_bytes", lambda _path: 1000)
    with pytest.raises(InsufficientStorageError) as exc:
        check_refresh_free_space(
            live,
            export_bytes=500,
            backup_bytes=200,
            class_c_snapshot_bytes=100,
            retained_prev_tree_bytes=100,
            rollback_headroom=100,
        )
    assert exc.value.details["required_bytes"] == 1100


def test_negative_budget_is_rejected(tmp_path: Path) -> None:
    live, _staging = _live_and_staging(tmp_path)
    with pytest.raises(ValidationError):
        check_refresh_free_space(live, export_bytes=-1)


# ----------------------------------------------------------------------
# Mountpoint / same-device preflight
# ----------------------------------------------------------------------


def test_mountpoint_live_dir_rejected_before_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, staging = _live_and_staging(tmp_path)
    monkeypatch.setattr(
        refresh_orchestrator.os.path,
        "ismount",
        lambda path: Path(path) == live,
    )
    with pytest.raises(ConflictError) as exc:
        check_swap_preconditions(live, staging)
    assert exc.value.http_status == 409
    assert "mountpoint" in str(exc.value)
    assert str(live) in str(exc.value)


def test_cross_device_staging_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, staging = _live_and_staging(tmp_path)
    monkeypatch.setattr(
        refresh_orchestrator,
        "_st_dev",
        lambda path: 1 if Path(path) == live else 2,
    )
    with pytest.raises(ValidationError, match="share one filesystem"):
        check_swap_preconditions(live, staging)


def test_staging_must_not_be_a_symlink(tmp_path: Path) -> None:
    live, staging = _live_and_staging(tmp_path)
    real = tmp_path / "real-staging"
    real.mkdir()
    staging.symlink_to(real)
    with pytest.raises(ValidationError, match="plain directory"):
        check_swap_preconditions(live, staging)


# ----------------------------------------------------------------------
# Worktree lock guard
# ----------------------------------------------------------------------


def test_gitdir_locked_marker_fails_closed(tmp_path: Path) -> None:
    live = tmp_path / "servers" / SERVER_ID
    worktree = live / ".onx" / "worktrees" / "feature"
    worktree.mkdir(parents=True)
    gitdir = tmp_path / "repo.git" / "worktrees" / "feature"
    gitdir.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "locked").write_text("locked by operator\n", encoding="utf-8")

    with pytest.raises(ConflictError) as exc:
        check_worktree_locks(live)
    assert exc.value.http_status == 409
    assert "feature" in str(exc.value)


def test_repo_git_worktree_lock_is_detected(tmp_path: Path) -> None:
    live = tmp_path / "servers" / SERVER_ID
    live.mkdir(parents=True)
    repo_git = tmp_path / "repos" / SERVER_ID / "repo.git"
    locked_dir = repo_git / "worktrees" / "review"
    locked_dir.mkdir(parents=True)
    (locked_dir / "locked").write_text("locked\n", encoding="utf-8")

    with pytest.raises(ConflictError):
        check_worktree_locks(live, repo_git_dir=repo_git)


def test_preflight_fails_on_lock_before_space(
    disk_env: tuple[HostStateLayout, Path, CleanExportRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, root, _request = disk_env
    worktree = root / ".onx" / "worktrees" / "feature"
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / "locked").write_text("locked\n", encoding="utf-8")
    monkeypatch.setattr(refresh_orchestrator, "_free_bytes", lambda _path: 0)
    orchestrator = RefreshOrchestrator(layout)

    with pytest.raises(ConflictError):
        orchestrator.preflight(
            SERVER_ID,
            live_dir=root,
            staging_dir=root.with_name(root.name + ".staging"),
            export_bytes=10,
        )


# ----------------------------------------------------------------------
# ENOSPC handling
# ----------------------------------------------------------------------


def test_staging_guard_removes_partial_tree_and_keeps_live(tmp_path: Path) -> None:
    live = tmp_path / "servers" / SERVER_ID
    live.mkdir(parents=True)
    (live / "keep.txt").write_text("live\n", encoding="utf-8")
    staging = tmp_path / "servers" / f"{SERVER_ID}.staging"
    staging.mkdir()
    (staging / "partial.bin").write_bytes(b"partial")

    with (
        pytest.raises(InsufficientStorageError) as exc,
        staging_enospc_guard(staging, live_dir=live),
    ):
        raise OSError(errno.ENOSPC, "No space left on device")

    assert exc.value.http_status == 507
    assert not staging.exists()
    assert (live / "keep.txt").read_text(encoding="utf-8") == "live\n"


def test_carry_enospc_restores_live_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "servers" / SERVER_ID
    staging = tmp_path / "servers" / f"{SERVER_ID}.staging"
    live.mkdir(parents=True)
    staging.mkdir(parents=True)
    (live / "server.properties").write_text("live\n", encoding="utf-8")
    (staging / "server.properties").write_text("staged\n", encoding="utf-8")
    for name in ("world", "logs", ".onx-manager"):
        (live / name).mkdir()
        (live / name / "data.txt").write_text(name, encoding="utf-8")

    real_rename = os.rename
    calls = {"count": 0}

    def flaky_rename(source: str, target: str) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_rename(source, target)

    monkeypatch.setattr(refresh_orchestrator.os, "rename", flaky_rename)
    with pytest.raises(InsufficientStorageError):
        carry_complement_entries(live, staging)

    for name in ("world", "logs", ".onx-manager"):
        assert (live / name / "data.txt").is_file()
        assert not (staging / name).exists()
    assert (staging / "server.properties").read_text(encoding="utf-8") == "staged\n"


# ----------------------------------------------------------------------
# Clean export: POSIX guard and ENOSPC
# ----------------------------------------------------------------------


def test_posix_export_no_longer_raises_cow_unavailable(
    disk_env: tuple[HostStateLayout, Path, CleanExportRequest],
) -> None:
    layout, _root, request = disk_env

    result = CleanExportService(layout).export(request)

    assert result.root == Path(request.destination)
    assert (result.root / EXPORT_MARKER_NAME).is_file()
    assert (result.root / "server.properties").is_file()


def test_windows_export_is_simple_only(
    disk_env: tuple[HostStateLayout, Path, CleanExportRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, _root, request = disk_env
    service = CleanExportService(layout)
    monkeypatch.setattr(clean_export.os, "name", "nt")

    with pytest.raises(ServerModeVersioningDisabledError) as exc:
        service.export(request)

    assert exc.value.http_status == 409
    assert not Path(request.destination).exists()


def test_enospc_during_export_cleans_destination_and_keeps_live(
    disk_env: tuple[HostStateLayout, Path, CleanExportRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, root, request = disk_env
    live_properties = (root / "server.properties").read_text(encoding="utf-8")

    def fail_injection(
        _self: CleanExportService,
        _destination: Path,
        _request: CleanExportRequest,
    ) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(CleanExportService, "_inject_class_d", fail_injection)
    with pytest.raises(InsufficientStorageError) as exc:
        CleanExportService(layout).export(request)

    assert exc.value.http_status == 507
    assert exc.value.details["path"] == str(request.destination)
    assert not Path(request.destination).exists()
    assert (root / "server.properties").read_text(encoding="utf-8") == live_properties
