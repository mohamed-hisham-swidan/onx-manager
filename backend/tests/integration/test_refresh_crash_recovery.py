"""P2-5c crash recovery, unified refresh journal, and path-safety tests."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    FencingTokenMismatchError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
)
from app.modules.versioning.application.refresh_recovery import (
    RefreshStartupReconciler,
)
from app.modules.versioning.infrastructure.directory_swap import (
    PHASE_PREPARED,
    PHASE_SWAP_COMPLETED,
    PHASE_SWAP_ROLLED_BACK,
    PHASE_SWAPPING_IN_STAGING,
    PHASE_SWAPPING_OUT_LIVE,
    DirectorySwapJournal,
    SwapJournalRecord,
    classify_swap_state,
    rename_exchange,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    RefreshJournalRepository,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode refresh recovery is POSIX-only",
)

SERVER_ID = "srv-refresh"


@dataclass
class RecoveryEnv:
    layout: HostStateLayout
    repository: RefreshJournalRepository
    servers_root: Path
    db_path: Path
    async_factory: async_sessionmaker
    sync_factory: sessionmaker[Session]


@pytest.fixture
def recovery_env(tmp_path: Path):
    db_path = tmp_path / "refresh.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    result = DatabaseReconciler(db_url=db_url).reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message

    async_engine = create_async_engine(db_url)
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    async_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    servers_root = tmp_path / "servers"
    servers_root.mkdir(parents=True, exist_ok=True)
    repository = RefreshJournalRepository(
        layout,
        session_factory=async_factory,
        sync_session_factory=sync_factory,
    )
    env = RecoveryEnv(
        layout=layout,
        repository=repository,
        servers_root=servers_root,
        db_path=db_path,
        async_factory=async_factory,
        sync_factory=sync_factory,
    )
    try:
        yield env
    finally:
        repository.close()
        sync_engine.dispose()
        asyncio.run(async_engine.dispose())


def _write(path: Path, name: str, value: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(value, encoding="utf-8")


def _marker(directory: Path, export_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".onx-complete.json").write_text(
        json.dumps({"export_id": export_id, "file_count": 1}), encoding="utf-8"
    )


def _swap_record(
    env: RecoveryEnv,
    server_id: str,
    phase: str,
    *,
    export_id: str = "",
    keep_previous: bool = False,
) -> SwapJournalRecord:
    live = env.servers_root / server_id
    staging = env.servers_root / f"{server_id}.staging"
    return SwapJournalRecord(
        journal_id=f"swap-{server_id}",
        server_id=server_id,
        phase=phase,
        live_path=str(live),
        staging_path=str(staging),
        previous_path=str(live.with_name(live.name + ".prev")),
        export_id=export_id,
        keep_previous=keep_previous,
    )


def _write_swap_journal(env: RecoveryEnv, record: SwapJournalRecord) -> DirectorySwapJournal:
    journal = DirectorySwapJournal(
        env.layout.journal / record.server_id / "swap.json"
    )
    journal.write(record)
    return journal


def _reconciler(env: RecoveryEnv) -> RefreshStartupReconciler:
    return RefreshStartupReconciler(
        env.layout,
        repository=env.repository,
        servers_data_dir=env.servers_root,
    )


def test_exchange_crash_before_journal_completion_preserves_old_live_tree(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    _write(live, "old.txt", "old")
    _write(staging, "new.txt", "new")
    _marker(staging, "export-1")

    if not rename_exchange(live, staging):
        pytest.skip("filesystem does not support RENAME_EXCHANGE")

    record = _swap_record(
        env, SERVER_ID, PHASE_PREPARED, export_id="export-1", keep_previous=True
    )
    journal = _write_swap_journal(env, record)
    assert classify_swap_state(record).state == "already_swapped"

    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=7,
        phase="SWAPPING",
        live_path=live,
        staging_path=staging,
        previous_path=live.with_name(live.name + ".prev"),
        export_id="export-1",
    )

    summary = _reconciler(env).reconcile_sync()

    recovered = journal.read()
    assert recovered is not None
    assert recovered.phase == PHASE_SWAP_COMPLETED
    assert recovered.used_exchange is True
    assert (live / "new.txt").read_text() == "new"
    assert (staging / "old.txt").read_text() == "old"

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "SWAP_COMPLETED"
    assert stored.terminal is False
    assert stored.used_exchange is True
    assert stored.export_id == "export-1"
    assert (staging / "old.txt").exists()
    assert SERVER_ID in summary.recovered_swaps
    assert created.journal_id in summary.transitioned_journals
    assert not summary.errors


@pytest.mark.parametrize(
    "phase",
    [PHASE_SWAPPING_OUT_LIVE, PHASE_SWAPPING_IN_STAGING],
)
def test_interrupted_two_step_swap_restores_live_in_disk_and_db(
    recovery_env: RecoveryEnv, phase: str
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    previous = env.servers_root / f"{SERVER_ID}.prev"
    staging = env.servers_root / f"{SERVER_ID}.staging"
    _write(previous, "old.txt", "old")
    _write(staging, "new.txt", "new")
    record = _swap_record(env, SERVER_ID, phase)
    journal = _write_swap_journal(env, record)

    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=3,
        phase="SWAPPING",
        live_path=live,
        staging_path=staging,
        previous_path=previous,
    )

    summary = _reconciler(env).reconcile_sync()

    assert (live / "old.txt").read_text() == "old"
    assert not previous.exists()
    recovered = journal.read()
    assert recovered is not None
    assert recovered.phase == PHASE_SWAP_ROLLED_BACK
    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "SWAP_ROLLED_BACK"
    assert SERVER_ID in summary.recovered_swaps
    assert created.journal_id in summary.transitioned_journals
    assert not summary.errors


def test_startup_removes_partial_staging_and_prunes_only_expired_previous(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    now = datetime.now(UTC)
    expired_server = "srv-expired"
    kept_server = "srv-kept"

    partial = env.servers_root / f"{expired_server}.staging"
    _write(partial, "partial.txt", "partial")
    expired_previous = env.servers_root / f"{expired_server}.prev"
    _write(expired_previous, "old.txt", "old")
    kept_previous = env.servers_root / f"{kept_server}.prev"
    _write(kept_previous, "keep.txt", "keep")
    _write(env.servers_root / expired_server, "server.properties", "motd=expired\n")
    _write(env.servers_root / kept_server, "server.properties", "motd=kept\n")

    expired = env.repository.create_sync(
        server_id=expired_server,
        fencing_token=1,
        live_path=env.servers_root / expired_server,
        staging_path=partial,
        previous_path=expired_previous,
    )
    expired = env.repository.transition_sync(
        expired.journal_id,
        fencing_token=1,
        phase="COMPLETED",
        previous_tree_retained=True,
        previous_tree_expires_at=now - timedelta(hours=1),
    )
    kept = env.repository.create_sync(
        server_id=kept_server,
        fencing_token=1,
        live_path=env.servers_root / kept_server,
        staging_path=env.servers_root / f"{kept_server}.staging",
        previous_path=kept_previous,
    )
    kept = env.repository.transition_sync(
        kept.journal_id,
        fencing_token=1,
        phase="COMPLETED",
        previous_tree_retained=True,
        previous_tree_expires_at=now + timedelta(hours=1),
    )

    summary = _reconciler(env).reconcile_sync()

    assert not partial.exists()
    assert not expired_previous.exists()
    assert (kept_previous / "keep.txt").read_text() == "keep"
    assert str(partial) in summary.removed_staging
    assert str(expired_previous) in summary.pruned_previous_trees
    assert not summary.errors

    expired_after = env.repository.get_sync(expired.journal_id)
    assert expired_after is not None
    assert expired_after.previous_tree_retained is False
    assert expired_after.previous_tree_expires_at is None
    kept_after = env.repository.get_sync(kept.journal_id)
    assert kept_after is not None
    assert kept_after.previous_tree_retained is True
    assert kept_after.previous_tree_expires_at is not None


def test_scan_filesystem_ignores_internal_swap_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers_root = tmp_path / "servers"
    for name in ("alpha", "alpha.staging", "alpha.prev", ".onx-work"):
        (servers_root / name).mkdir(parents=True)
    (servers_root / "readme.txt").write_text("not a server", encoding="utf-8")
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(servers_root))

    service = FilesystemReconciliationService(object())  # type: ignore[arg-type]
    entries = service._scan_filesystem()

    assert [entry.name for entry in entries] == ["alpha"]


def test_transition_rejects_stale_fencing_token_and_mirrors_json(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=5,
        phase="QUIESCED",
        live_path=live,
        staging_path=staging,
    )

    with pytest.raises(FencingTokenMismatchError) as stale:
        env.repository.transition_sync(
            created.journal_id, fencing_token=6, phase="STAGING"
        )
    assert stale.value.http_status == 409
    assert stale.value.code == "FENCING_TOKEN_MISMATCH"
    assert stale.value.details["expected_token"] == 6
    assert stale.value.details["actual_token"] == 5

    unchanged = env.repository.get_sync(created.journal_id)
    assert unchanged is not None
    assert unchanged.phase == "QUIESCED"

    completed = env.repository.transition_sync(
        created.journal_id, fencing_token=5, phase="COMPLETED"
    )
    assert completed.terminal is True

    mirror = json.loads(
        (env.layout.journal / SERVER_ID / "refresh.json").read_text(encoding="utf-8")
    )
    assert mirror["phase"] == "COMPLETED"
    assert mirror["terminal"] is True
    assert mirror["fencing_token"] == 5

    with pytest.raises(FencingTokenMismatchError):
        env.repository.transition_sync(
            created.journal_id, fencing_token=5, phase="FAILED_CLEAN"
        )


def test_retained_exchange_staging_survives_sweep_until_expiry(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    now = datetime.now(UTC)
    kept_server = "srv-retained"
    expired_server = "srv-retained-expired"

    for server_id, expires_at in (
        (kept_server, now + timedelta(hours=1)),
        (expired_server, now - timedelta(hours=1)),
    ):
        live = env.servers_root / server_id
        staging = env.servers_root / f"{server_id}.staging"
        _write(live, "new.txt", "new")
        _marker(live, f"export-{server_id}")
        _write(staging, "old.txt", "old")
        record = env.repository.create_sync(
            server_id=server_id,
            fencing_token=4,
            phase="SWAPPING",
            live_path=live,
            staging_path=staging,
            previous_path=live.with_name(live.name + ".prev"),
            export_id=f"export-{server_id}",
        )
        env.repository.transition_sync(
            record.journal_id,
            fencing_token=4,
            phase="COMPLETED",
            used_exchange=True,
            previous_tree_retained=True,
            previous_tree_expires_at=expires_at,
        )

    summary = _reconciler(env).reconcile_sync()

    kept_staging = env.servers_root / f"{kept_server}.staging"
    expired_staging = env.servers_root / f"{expired_server}.staging"
    assert (kept_staging / "old.txt").read_text() == "old"
    assert not expired_staging.exists()
    assert str(kept_staging) not in summary.removed_staging
    assert str(expired_staging) in summary.pruned_previous_trees
    assert not summary.errors


def test_create_rejects_second_active_journal_for_server(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=1,
        phase="QUIESCED",
        live_path=live,
        staging_path=staging,
    )

    with pytest.raises(ConflictError, match="active refresh journal"):
        env.repository.create_sync(
            server_id=SERVER_ID,
            fencing_token=2,
            phase="QUIESCED",
            live_path=live,
            staging_path=staging,
        )


def test_path_safety_rejects_out_of_root_previous_tree_before_rmtree(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    outside = env.servers_root.parent / "outside-tree"
    _write(outside, "victim.txt", "keep me")
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    _write(live, "server.properties", "motd=live\n")

    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=2,
        phase="QUIESCED",
        live_path=live,
        staging_path=staging,
        previous_path=outside,
    )
    created = env.repository.transition_sync(
        created.journal_id,
        fencing_token=2,
        phase="COMPLETED",
        previous_tree_retained=True,
        previous_tree_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    reconciler = _reconciler(env)
    with pytest.raises(ValidationError, match="servers_data_dir"):
        reconciler.validate_swap_path(
            SERVER_ID, outside, field="previous_path"
        )

    summary = reconciler.reconcile_sync()

    assert (outside / "victim.txt").read_text() == "keep me"
    assert summary.errors
    assert not summary.pruned_previous_trees
    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.previous_tree_retained is True


def test_interrupted_carrying_with_completed_swap_advances_to_swap_completed(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    _write(live, "old.txt", "old")
    _write(staging, "new.txt", "new")
    _marker(staging, "export-carry")

    if not rename_exchange(live, staging):
        pytest.skip("filesystem does not support RENAME_EXCHANGE")

    record = _swap_record(
        env, SERVER_ID, PHASE_PREPARED, export_id="export-carry", keep_previous=True
    )
    _write_swap_journal(env, record)
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=5,
        phase="CARRYING",
        live_path=live,
        staging_path=staging,
        previous_path=live.with_name(live.name + ".prev"),
        export_id="export-carry",
    )

    summary = _reconciler(env).reconcile_sync()

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "SWAP_COMPLETED"
    assert stored.terminal is False
    assert stored.used_exchange is True
    assert (live / "new.txt").read_text() == "new"
    assert created.journal_id in summary.transitioned_journals
    assert not summary.errors


def test_interrupted_carrying_without_swap_journal_fails_clean_and_unblocks(
    recovery_env: RecoveryEnv,
) -> None:
    env = recovery_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / f"{SERVER_ID}.staging"
    _write(live, "server.properties", "motd=live\n")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=6,
        phase="CARRYING",
        live_path=live,
        staging_path=staging,
        previous_path=live.with_name(live.name + ".prev"),
    )

    summary = _reconciler(env).reconcile_sync()

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "FAILED_CLEAN"
    assert stored.terminal is True
    assert "complement carry" in stored.error
    assert (live / "server.properties").read_text() == "motd=live\n"
    assert created.journal_id in summary.transitioned_journals
    assert not summary.errors

    # The one-active-journal partial unique index is no longer wedged.
    fresh = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=7,
        phase="QUIESCED",
        live_path=live,
        staging_path=staging,
        previous_path=live.with_name(live.name + ".prev"),
    )
    assert fresh.phase == "QUIESCED"
