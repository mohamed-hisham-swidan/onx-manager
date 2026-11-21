"""P7-2 conversion API and service tests (OD-v8.6-3).

Covers the acceptance criteria for Simple -> Advanced and Advanced -> Simple
conversion, including the safety triad, copy-first CAS ingest, Git bootstrap,
clean-export verification, rollback semantics, RBAC, error mapping, and the
activity event labels.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.routers import conversion as conversion_router
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import (
    CasUnsupportedPlatformError,
    ConflictError,
    GitRepositoryStateError,
    SecretFileInGitForbiddenError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.activity.application.subscriber import ActivityEventSubscriber
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.backup.application.services import conversion_service as conversion_service_module
from app.modules.backup.application.services.conversion_service import (
    ConversionError,
    ConversionResult,
    ConversionService,
)
from app.modules.backup.domain.aggregate import BackupStatus, BackupTier
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.domain.events import (
    ServerConvertedToAdvancedEvent,
    ServerConvertedToSimpleEvent,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.versioning.application.baseline_adoption import (
    ensure_simple_baseline_lockfile,
)
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.domain.lockfile import dump_lockfile
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.clean_export import CleanExportService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import ClassCSnapshotModel
from app.registration import register_handlers

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Advanced mode is POSIX-only")

SIMPLE_ID = "srv-p72-simple"
ADVANCED_ID = "srv-p72-advanced"
COPY_ID = "srv-p72-copy"
COPY_FAIL_ID = "srv-p72-copy-fail"
GITHUB_PAT = "ghp_" + ("A" * 36)
ADVANCED_PATH = f"/api/v1/servers/{ADVANCED_ID}/convert/to-advanced"
SIMPLE_PATH = f"/api/v1/servers/{ADVANCED_ID}/convert/to-simple"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def host_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HostStateLayout:
    """Configure an isolated host-state, server-data, backup, and KEK environment."""
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_BACKUP_STORAGE_PATH", str(tmp_path / "backups"))
    monkeypatch.setenv("ONX_MASTER_KEK", "a5" * 32)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    monkeypatch.delenv("ONX_HOST_STATE_HOST_DIR", raising=False)
    return ensure_host_state_layout()


@pytest.fixture
def activity_bus() -> EventBus:
    bus = EventBus()
    subscriber = ActivityEventSubscriber(SQLActivityRepository())
    bus.subscribe("ServerConvertedToAdvancedEvent", subscriber)
    bus.subscribe("ServerConvertedToSimpleEvent", subscriber)
    return bus


def _write_server_tree(root: Path, *, include_secret: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.jar").write_bytes(b"fake-server-jar")
    (root / "server.properties").write_text(
        "motd=Test Server\nserver-port=25565\n", encoding="utf-8"
    )
    (root / "ops.json").write_text('["alice"]', encoding="utf-8")
    (root / "world").mkdir(exist_ok=True)
    (root / "world" / "level.dat").write_bytes(b"level-data")
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "example.yml").write_text("enabled: true\n", encoding="utf-8")
    (root / "plugins" / "Demo").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "Demo" / "config.yml").write_text(
        "demo: true\n", encoding="utf-8"
    )
    if include_secret:
        (root / "config" / "secret.yml").write_text(
            f"github_token: {GITHUB_PAT}\n", encoding="utf-8"
        )


async def _seed_server(
    server_id: str,
    root: Path,
    *,
    mode: str = "simple",
    status: str = "stopped",
    port: int = 25565,
    name: str | None = None,
) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=name or server_id,
                server_type="paper",
                minecraft_version="1.20.4",
                status=status,
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                deployment_port=port,
                port=port,
                java_args="-Xmx1G",
                mode=mode,
                provider="local",
                location_type="local",
                max_concurrent_branch_runs=3,
            )
        )
        await session.commit()


async def _server_row(server_id: str) -> ServerModel | None:
    async with database.session_factory() as session:
        return await session.get(ServerModel, server_id)


async def _prepare_advanced_source(
    layout: HostStateLayout,
    server_id: str,
    root: Path,
    *,
    port: int = 25566,
) -> tuple[Any, Any]:
    """Seed a Simple server, adopt its baseline, initialize Git, then flip to Advanced."""
    _write_server_tree(root)
    await _seed_server(server_id, root, mode="simple", status="stopped", port=port)

    adoption = await ensure_simple_baseline_lockfile(server_id)
    assert adoption.status in {"created", "already_present"}
    lockfile = LockfileService(layout).read(server_id)
    assert lockfile is not None

    repo_result = GitRepositoryService(layout).initialize(server_id, root, lockfile)

    async with database.session_factory() as session:
        model = await session.get(ServerModel, server_id)
        assert model is not None
        cast(Any, model).mode = "advanced"
        await session.commit()

    return lockfile, repo_result


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            snapshot[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return snapshot


async def _activity_types(server_id: str) -> list[str]:
    logs, _ = await SQLActivityRepository().list_by_server(server_id, limit=20)
    return [entry.event_type for entry in logs]


# ---------------------------------------------------------------------------
# Service: Simple -> Advanced
# ---------------------------------------------------------------------------


async def test_simple_to_advanced_success_is_in_place_and_persists_safety_triad(
    host_env: HostStateLayout, activity_bus: EventBus, tmp_path: Path
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root)
    await _seed_server(SIMPLE_ID, root, mode="simple", status="stopped", port=25567)
    original_tree = _tree_snapshot(root)

    service = ConversionService(host_env)
    result = await service.convert_simple_to_advanced(
        SIMPLE_ID, event_bus=activity_bus, actor_id="usr-p72", actor_type="user"
    )

    # Same server id, same port, mode flipped in place.
    assert result.server_id == SIMPLE_ID
    assert result.from_mode == "simple"
    assert result.to_mode == "advanced"
    assert result.new_server_id is None
    assert result.backup_id
    assert result.class_c_snapshot_id
    assert result.details["main_commit_sha"]

    row = cast(Any, await _server_row(SIMPLE_ID))
    assert row is not None
    assert row.mode == "advanced"
    assert row.port == 25567

    # Pinned Tier-1 job row, completed, backed by a real snapshot directory.
    async with database.session_factory() as session:
        backup = await SQLBackupRepository(session).get_job(BackupJobId(result.backup_id))
    assert backup.status is BackupStatus.COMPLETED
    assert backup.pinned is True
    assert backup.tier is BackupTier.TIER_1
    assert backup.storage_path
    assert Path(backup.storage_path).is_dir()
    assert Path(backup.storage_path).name == result.backup_id

    # Pinned encrypted Class-C ledger row.
    async with database.session_factory() as session:
        snapshot = cast(
            Any, await session.get(ClassCSnapshotModel, result.class_c_snapshot_id)
        )
    assert snapshot is not None
    assert snapshot.server_id == SIMPLE_ID
    assert bool(snapshot.pinned) is True

    # Host lockfile + copy-first CAS ingest; the source jar is still present.
    lockfile = LockfileService(host_env).read(SIMPLE_ID)
    assert lockfile is not None
    assert result.details["lockfile_path"] == str(LockfileService(host_env).path_for(SIMPLE_ID))
    jar_entries = [entry for entry in lockfile.files if entry.path == "server.jar"]
    assert len(jar_entries) == 1
    assert ArtifactCas(host_env.cas).has(jar_entries[0].sha256)
    assert (root / "server.jar").read_bytes() == b"fake-server-jar"

    # Native repo, main worktree, and initial commit contents.
    repo_dir = host_env.repo_dir(SIMPLE_ID)
    assert (repo_dir / "repo.git").is_dir()
    worktree = root / ".onx" / "worktrees" / "main"
    assert worktree.is_dir()
    assert result.details["worktree_path"] == str(worktree)
    assert (worktree / "onx-jars.lock.json").is_file()
    assert (worktree / ".gitattributes").is_file()
    assert (worktree / "server.properties").is_file()
    assert (worktree / "config" / "example.yml").is_file()

    # Scratch export directory was removed.
    assert not list(root.parent.glob(".onx-scratch-*"))

    # Class-A jars are never moved or deleted; only the repo/worktree are added.
    after_tree = _tree_snapshot(root)
    for relpath, digest in original_tree.items():
        assert after_tree.get(relpath) == digest
    assert after_tree.get("server.jar") == original_tree["server.jar"]

    # Activity event label + actor are persisted.
    logs, total = await SQLActivityRepository().list_by_server(SIMPLE_ID, limit=20)
    assert total >= 1
    advanced_logs = [
        entry for entry in logs if entry.event_type == "server.converted.to_advanced"
    ]
    assert len(advanced_logs) == 1
    assert advanced_logs[0].actor_id == "usr-p72"
    assert advanced_logs[0].actor_type == "user"


async def test_simple_to_advanced_missing_server_returns_404(host_env: HostStateLayout) -> None:
    service = ConversionService(host_env)
    with pytest.raises(ConversionError) as exc_info:
        await service.convert_simple_to_advanced("srv-does-not-exist")
    assert exc_info.value.http_status == 404
    assert exc_info.value.code == "NOT_FOUND"


async def test_simple_to_advanced_rejects_wrong_mode_and_running_status(
    host_env: HostStateLayout, tmp_path: Path
) -> None:
    advanced_root = tmp_path / "servers" / "srv-already-advanced"
    _write_server_tree(advanced_root)
    await _seed_server("srv-already-advanced", advanced_root, mode="advanced")

    running_root = tmp_path / "servers" / "srv-running"
    _write_server_tree(running_root)
    await _seed_server("srv-running", running_root, mode="simple", status="running")

    service = ConversionService(host_env)

    with pytest.raises(ConversionError) as advanced_exc:
        await service.convert_simple_to_advanced("srv-already-advanced")
    assert advanced_exc.value.http_status == 409

    with pytest.raises(ConflictError):
        await service.convert_simple_to_advanced("srv-running")


async def test_simple_to_advanced_non_posix_is_501(
    host_env: HostStateLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "name", "nt")
    service = ConversionService(host_env)
    with pytest.raises(CasUnsupportedPlatformError) as exc_info:
        await service.convert_simple_to_advanced(SIMPLE_ID)
    assert exc_info.value.http_status == 501


async def test_simple_to_advanced_secret_guard_rolls_back_repo_and_keeps_source(
    host_env: HostStateLayout, tmp_path: Path
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root, include_secret=True)
    await _seed_server(SIMPLE_ID, root, mode="simple", status="stopped")
    original_tree = _tree_snapshot(root)

    service = ConversionService(host_env)
    with pytest.raises(SecretFileInGitForbiddenError):
        await service.convert_simple_to_advanced(SIMPLE_ID)

    row = cast(Any, await _server_row(SIMPLE_ID))
    assert row is not None
    assert row.mode == "simple"

    # Newly created repo/worktree are removed; the source tree is byte-identical.
    assert not (host_env.repo_dir(SIMPLE_ID) / "repo.git").exists()
    assert not (root / ".onx" / "worktrees" / "main").exists()
    assert not list(root.parent.glob(".onx-scratch-*"))
    assert _tree_snapshot(root) == original_tree

    # The pre-conversion safety triad was already persisted before the Git step:
    # the secret guard must never silently skip the pinned Tier-1/Class-C backups.
    async with database.session_factory() as session:
        jobs = await SQLBackupRepository(session).list_jobs(
            ServerId(SIMPLE_ID), tier=BackupTier.TIER_1
        )
        snapshots = (
            await session.execute(
                select(ClassCSnapshotModel).where(
                    ClassCSnapshotModel.server_id == SIMPLE_ID
                )
            )
        ).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status is BackupStatus.COMPLETED
    assert jobs[0].pinned is True
    assert len(snapshots) == 1
    assert bool(snapshots[0].pinned) is True
    lockfile = LockfileService(host_env).read(SIMPLE_ID)
    assert lockfile is not None


async def test_simple_to_advanced_tier1_snapshot_failure_marks_job_failed(
    host_env: HostStateLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root)
    await _seed_server(SIMPLE_ID, root, mode="simple", status="stopped")

    async def _fail(**_kwargs: Any) -> Any:
        raise OSError("snapshot failed")

    monkeypatch.setattr(conversion_service_module, "create_tier1_snapshot", _fail)

    service = ConversionService(host_env)
    with pytest.raises(OSError, match="snapshot failed"):
        await service.convert_simple_to_advanced(SIMPLE_ID)

    async with database.session_factory() as session:
        jobs = await SQLBackupRepository(session).list_jobs(
            ServerId(SIMPLE_ID), tier=BackupTier.TIER_1
        )
    assert len(jobs) == 1
    assert jobs[0].status is BackupStatus.FAILED
    assert "snapshot failed" in jobs[0].error_message

    row = cast(Any, await _server_row(SIMPLE_ID))
    assert row is not None
    assert row.mode == "simple"
    assert not (host_env.repo_dir(SIMPLE_ID) / "repo.git").exists()


async def test_simple_to_advanced_mid_conversion_failure_removes_new_repo_and_worktree(
    host_env: HostStateLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root)
    await _seed_server(SIMPLE_ID, root, mode="simple", status="stopped")
    original_tree = _tree_snapshot(root)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("clean export failed")

    monkeypatch.setattr(CleanExportService, "export", _boom)

    service = ConversionService(host_env)
    with pytest.raises(OSError, match="clean export failed"):
        await service.convert_simple_to_advanced(SIMPLE_ID)

    row = cast(Any, await _server_row(SIMPLE_ID))
    assert row is not None
    assert row.mode == "simple"
    assert not (host_env.repo_dir(SIMPLE_ID) / "repo.git").exists()
    assert not (root / ".onx" / "worktrees" / "main").exists()
    assert not list(root.parent.glob(".onx-scratch-*"))
    assert _tree_snapshot(root) == original_tree


async def test_simple_to_advanced_failure_preserves_preexisting_repo_and_worktree(
    host_env: HostStateLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root)
    await _seed_server(SIMPLE_ID, root, mode="simple", status="stopped")

    adoption = await ensure_simple_baseline_lockfile(SIMPLE_ID)
    assert adoption.status == "created"
    lockfile = LockfileService(host_env).read(SIMPLE_ID)
    assert lockfile is not None
    GitRepositoryService(host_env).initialize(SIMPLE_ID, root, lockfile)

    repo_git = host_env.repo_dir(SIMPLE_ID) / "repo.git"
    worktree = root / ".onx" / "worktrees" / "main"
    assert repo_git.is_dir()
    assert worktree.is_dir()

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("clean export failed")

    monkeypatch.setattr(CleanExportService, "export", _boom)

    service = ConversionService(host_env)
    with pytest.raises(OSError, match="clean export failed"):
        await service.convert_simple_to_advanced(SIMPLE_ID)

    # A retry must never delete a repository/worktree it did not create.
    assert repo_git.is_dir()
    assert worktree.is_dir()
    row = cast(Any, await _server_row(SIMPLE_ID))
    assert row is not None
    assert row.mode == "simple"


# ---------------------------------------------------------------------------
# Service: Advanced -> Simple
# ---------------------------------------------------------------------------


async def test_advanced_to_simple_creates_new_server_and_leaves_source_untouched(
    host_env: HostStateLayout, activity_bus: EventBus, tmp_path: Path
) -> None:
    source_root = tmp_path / "servers" / ADVANCED_ID
    lockfile, _ = await _prepare_advanced_source(
        host_env, ADVANCED_ID, source_root, port=25566
    )
    source_tree = _tree_snapshot(source_root)
    source_repo_git = host_env.repo_dir(ADVANCED_ID) / "repo.git"
    source_worktree = source_root / ".onx" / "worktrees" / "main"

    service = ConversionService(host_env)
    result = await service.convert_advanced_to_simple(
        ADVANCED_ID,
        new_server_id=COPY_ID,
        new_name="Copy of Advanced",
        new_port=25570,
        event_bus=activity_bus,
        actor_id="usr-p72",
        actor_type="user",
    )

    assert result.server_id == ADVANCED_ID
    assert result.from_mode == "advanced"
    assert result.to_mode == "simple"
    assert result.new_server_id == COPY_ID

    new_root = tmp_path / "servers" / COPY_ID
    assert Path(result.details["root_path"]) == new_root
    assert new_root.is_dir()

    # New Simple row: new id, simple mode, stopped, requested name/port, local root.
    new_row = cast(Any, await _server_row(COPY_ID))
    assert new_row is not None
    assert new_row.mode == "simple"
    assert new_row.status == "stopped"
    assert new_row.name == "Copy of Advanced"
    assert new_row.port == 25570
    assert new_row.root_path == str(new_root)
    assert new_row.location_type == "local"
    assert new_row.location_uri is None
    assert new_row.deployment_host is None
    assert new_row.deployment_port is None
    assert new_row.deployment_pid is None
    assert new_row.running_start_time is None
    assert new_row.external_id is None
    assert new_row.max_concurrent_branch_runs == 3

    # Clean Export materializes Class A/B, then live Class C/E files are copied.
    assert (new_root / "server.jar").read_bytes() == b"fake-server-jar"
    assert (new_root / "server.properties").is_file()
    assert (new_root / "ops.json").read_text(encoding="utf-8") == '["alice"]'
    assert (new_root / "world" / "level.dat").read_bytes() == b"level-data"
    assert (new_root / "config" / "example.yml").is_file()

    # Zero Git association in the new root.
    assert not (new_root / ".git").exists()
    assert not (new_root / ".onx").exists()
    assert not (new_root / ".onx" / "worktrees").exists()
    assert not list(new_root.rglob(".git"))

    # Authoritative host lockfile + informational copy.
    authoritative = LockfileService(host_env).path_for(COPY_ID)
    assert authoritative.is_file()
    assert result.details["lockfile_path"] == str(authoritative)
    info_copy = new_root / ".onx-manager" / "onx-jars.lock.json"
    assert info_copy.is_file()
    assert info_copy.read_bytes() == dump_lockfile(lockfile)

    # The source Advanced server, its row, repo, worktree, and tree are untouched.
    source_row = cast(Any, await _server_row(ADVANCED_ID))
    assert source_row is not None
    assert source_row.mode == "advanced"
    assert source_repo_git.is_dir()
    assert source_worktree.is_dir()
    assert (source_repo_git / "HEAD").is_file()
    assert _tree_snapshot(source_root) == source_tree

    # Activity event label + actor are persisted against the source server.
    logs, _ = await SQLActivityRepository().list_by_server(ADVANCED_ID, limit=20)
    simple_logs = [
        entry for entry in logs if entry.event_type == "server.converted.to_simple"
    ]
    assert len(simple_logs) == 1
    assert simple_logs[0].actor_id == "usr-p72"
    assert simple_logs[0].actor_type == "user"


async def test_advanced_to_simple_rejects_simple_source(
    host_env: HostStateLayout, tmp_path: Path
) -> None:
    root = tmp_path / "servers" / SIMPLE_ID
    _write_server_tree(root)
    await _seed_server(SIMPLE_ID, root, mode="simple")

    service = ConversionService(host_env)
    with pytest.raises(ConversionError) as exc_info:
        await service.convert_advanced_to_simple(SIMPLE_ID)
    assert exc_info.value.http_status == 409


async def test_advanced_to_simple_rejects_existing_target_root(
    host_env: HostStateLayout, tmp_path: Path
) -> None:
    source_root = tmp_path / "servers" / ADVANCED_ID
    await _prepare_advanced_source(host_env, ADVANCED_ID, source_root)

    existing_target = tmp_path / "servers" / COPY_ID
    existing_target.mkdir(parents=True)

    service = ConversionService(host_env)
    with pytest.raises(ConflictError):
        await service.convert_advanced_to_simple(ADVANCED_ID, new_server_id=COPY_ID)

    assert existing_target.is_dir()
    assert await _server_row(COPY_ID) is None
    source_row = cast(Any, await _server_row(ADVANCED_ID))
    assert source_row is not None
    assert source_row.mode == "advanced"


async def test_advanced_to_simple_requires_lockfile_and_repo(
    host_env: HostStateLayout, tmp_path: Path
) -> None:
    root = tmp_path / "servers" / ADVANCED_ID
    _write_server_tree(root)
    await _seed_server(ADVANCED_ID, root, mode="advanced")

    service = ConversionService(host_env)
    with pytest.raises(GitRepositoryStateError):
        await service.convert_advanced_to_simple(ADVANCED_ID, new_server_id=COPY_ID)


async def test_advanced_to_simple_copy_failure_removes_orphans_and_keeps_source(
    host_env: HostStateLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "servers" / ADVANCED_ID
    await _prepare_advanced_source(host_env, ADVANCED_ID, source_root)
    source_tree = _tree_snapshot(source_root)

    real_copy2 = shutil.copy2

    def _failing_copy2(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(dst).name == "ops.json":
            raise PermissionError("copy denied")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(conversion_service_module.shutil, "copy2", _failing_copy2)

    service = ConversionService(host_env)
    with pytest.raises(PermissionError, match="copy denied"):
        await service.convert_advanced_to_simple(
            ADVANCED_ID, new_server_id=COPY_FAIL_ID, new_name="Copy Fail"
        )

    new_root = tmp_path / "servers" / COPY_FAIL_ID
    assert not new_root.exists()
    assert not LockfileService(host_env).path_for(COPY_FAIL_ID).exists()
    assert not host_env.server_meta_dir(COPY_FAIL_ID).exists()
    assert await _server_row(COPY_FAIL_ID) is None

    source_row = cast(Any, await _server_row(ADVANCED_ID))
    assert source_row is not None
    assert source_row.mode == "advanced"
    assert _tree_snapshot(source_root) == source_tree


# ---------------------------------------------------------------------------
# Activity subscriber mapping
# ---------------------------------------------------------------------------


async def test_activity_subscriber_maps_both_conversion_event_labels() -> None:
    bus = EventBus()
    bus.subscribe(
        "ServerConvertedToAdvancedEvent",
        ActivityEventSubscriber(SQLActivityRepository()),
    )
    bus.subscribe(
        "ServerConvertedToSimpleEvent",
        ActivityEventSubscriber(SQLActivityRepository()),
    )

    await bus.publish(
        ServerConvertedToAdvancedEvent(
            ServerId("srv-event-advanced"),
            main_commit_sha="a" * 40,
            backup_id="b1",
            class_c_snapshot_id="c1",
            actor_id="usr-event",
            actor_type="user",
        )
    )
    await bus.publish(
        ServerConvertedToSimpleEvent(
            ServerId("srv-event-simple"),
            new_server_id="srv-event-copy",
            name="Copy",
            actor_id="usr-event",
            actor_type="user",
        )
    )

    assert await _activity_types("srv-event-advanced") == ["server.converted.to_advanced"]
    assert await _activity_types("srv-event-simple") == ["server.converted.to_simple"]


async def test_registration_subscribes_conversion_events() -> None:
    bus = EventBus()
    register_handlers(CommandBus(), QueryBus(), bus)
    registered = set(bus._subscribers)  # noqa: SLF001 - intentional wiring assertion
    assert "ServerConvertedToAdvancedEvent" in registered
    assert "ServerConvertedToSimpleEvent" in registered


# ---------------------------------------------------------------------------
# HTTP API: RBAC, response models, and error mapping
# ---------------------------------------------------------------------------


class _StubConversionService:
    def __init__(self, *, result: ConversionResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def convert_simple_to_advanced(self, server_id: str, **kwargs: Any) -> ConversionResult:
        self.calls.append((server_id, kwargs))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def convert_advanced_to_simple(self, server_id: str, **kwargs: Any) -> ConversionResult:
        self.calls.append((server_id, kwargs))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture
def install_stub_service():
    installed: list[Any] = []

    def _install(service: _StubConversionService) -> None:
        app.dependency_overrides[conversion_router._build_conversion_service] = lambda: service
        installed.append(service)

    yield _install

    app.dependency_overrides.pop(conversion_router._build_conversion_service, None)
    installed.clear()


def _headers(*permissions: str) -> dict[str, str]:
    from app.modules.auth.infrastructure.jwt import create_access_token

    token = create_access_token(
        user_id="usr-p72-api",
        roles=["admin"] if "admin:full" in permissions else [],
        permissions=list(permissions),
    )
    return {"Authorization": f"Bearer {token}"}


async def _post(path: str, *, headers: dict[str, str] | None = None, body: Any = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, headers=headers, json=body)


def _advanced_result() -> ConversionResult:
    return ConversionResult(
        server_id=SIMPLE_ID,
        from_mode="simple",
        to_mode="advanced",
        backup_id="backup-1",
        class_c_snapshot_id="class-c-1",
        details={
            "main_commit_sha": "a" * 40,
            "lockfile_path": "/host/server-meta/srv-p72-simple/onx-jars.lock.json",
            "files_count": 2,
            "cas_ingested": 1,
            "worktree_path": "/servers/srv-p72-simple/.onx/worktrees/main",
        },
    )


def _simple_result() -> ConversionResult:
    return ConversionResult(
        server_id=ADVANCED_ID,
        from_mode="advanced",
        to_mode="simple",
        new_server_id=COPY_ID,
        details={
            "name": "Copy",
            "root_path": "/servers/srv-p72-copy",
            "lockfile_path": "/host/server-meta/srv-p72-copy/onx-jars.lock.json",
            "files_count": 2,
        },
    )


async def test_rbac_requires_authentication_and_permission(install_stub_service) -> None:
    stub = _StubConversionService(result=_advanced_result())
    install_stub_service(stub)

    unauthenticated = await _post(ADVANCED_PATH)
    assert unauthenticated.status_code == 401

    forbidden = await _post(ADVANCED_PATH, headers=_headers("server.read"))
    assert forbidden.status_code == 403

    allowed = await _post(ADVANCED_PATH, headers=_headers("server.versioning.manage"))
    assert allowed.status_code == 200

    admin = await _post(ADVANCED_PATH, headers=_headers("admin:full"))
    assert admin.status_code == 200

    assert len(stub.calls) == 2
    assert stub.calls[0][0] == ADVANCED_ID
    assert stub.calls[0][1]["actor_id"] == "usr-p72-api"
    assert stub.calls[0][1]["actor_type"] == "user"


async def test_api_returns_typed_advanced_response(install_stub_service) -> None:
    install_stub_service(_StubConversionService(result=_advanced_result()))

    response = await _post(
        ADVANCED_PATH, headers=_headers("server.versioning.manage"), body={}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_id"] == SIMPLE_ID
    assert payload["mode"] == "advanced"
    assert payload["main_commit_sha"] == "a" * 40
    assert payload["backup_id"] == "backup-1"
    assert payload["class_c_snapshot_id"] == "class-c-1"
    assert payload["files_count"] == 2
    assert payload["cas_ingested"] == 1
    assert payload["worktree_path"].endswith(".onx/worktrees/main")


async def test_api_returns_typed_simple_response(install_stub_service) -> None:
    install_stub_service(_StubConversionService(result=_simple_result()))

    response = await _post(
        SIMPLE_PATH,
        headers=_headers("server.versioning.manage"),
        body={"name": "Copy", "port": 25570},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_server_id"] == ADVANCED_ID
    assert payload["new_server_id"] == COPY_ID
    assert payload["name"] == "Copy"
    assert payload["mode"] == "simple"
    assert payload["root_path"] == "/servers/srv-p72-copy"
    assert payload["files_count"] == 2


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (ConversionError("missing", http_status=404, code="NOT_FOUND"), 404, "NOT_FOUND"),
        (ConversionError("busy", http_status=409, code="CONFLICT"), 409, "CONFLICT"),
        (ConflictError("mode conflict"), 409, "CONFLICT"),
        (GitRepositoryStateError("repo missing"), 409, "GIT_REPOSITORY_STATE"),
        (ValidationError("bad root", field="root_path"), 422, "VALIDATION_ERROR"),
        (
            SecretFileInGitForbiddenError("config/secret.yml", findings=[]),
            422,
            "SECRET_FILE_IN_GIT_FORBIDDEN",
        ),
        (CasUnsupportedPlatformError(), 501, "CAS_UNSUPPORTED_PLATFORM"),
    ],
)
async def test_api_maps_conversion_errors(
    install_stub_service,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    install_stub_service(_StubConversionService(error=error))

    response = await _post(ADVANCED_PATH, headers=_headers("admin:full"))

    assert response.status_code == expected_status
    payload = response.json()
    detail = payload.get("detail")
    router_code = detail.get("error_code") if isinstance(detail, dict) else None
    actual_code = router_code or payload.get("error_code") or payload.get("code")
    assert actual_code == expected_code
