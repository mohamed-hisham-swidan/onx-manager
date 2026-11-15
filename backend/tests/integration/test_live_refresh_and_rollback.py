"""P2-5d2 live refresh, 4-step health gate, and triad rollback tests."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    FencingTokenMismatchError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.versioning.application.refresh_orchestrator import (
    STEP_BOOT_LOG,
    STEP_PROCESS_ALIVE,
    STEP_READINESS,
    STEP_STABILITY,
    ConfirmUpgradeCommand,
    ConfirmUpgradeCommandHandler,
    FencingGuard,
    HealthGateEvaluator,
    LiveRefreshRequest,
    LiveRefreshService,
    RefreshOrchestrator,
    RefreshServerCommand,
    RefreshServerCommandHandler,
    ReleaseRefreshPinsCommand,
    ReleaseRefreshPinsCommandHandler,
    RollbackRefreshCommand,
    RollbackRefreshCommandHandler,
    TriadRollbackService,
    previous_tree_path,
    run_health_gate,
)
from app.modules.versioning.application.refresh_recovery import (
    RefreshStartupReconciler,
)
from app.modules.versioning.application.repo_lease import (
    RepoLeaseManager,
    RepoLeaseToken,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    RefreshJournalRecord,
    RefreshJournalRepository,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode live refresh is POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-live"
STAGING = f"{SERVER_ID}.staging"
BACKUP_ID = "backup-1"
PREV_SHA = "a" * 40
TARGET_SHA = "b" * 40


@dataclass
class LiveEnv:
    layout: HostStateLayout
    repository: RefreshJournalRepository
    servers_root: Path
    async_factory: async_sessionmaker
    sync_factory: sessionmaker[Session]


@pytest.fixture
def live_env(tmp_path: Path):
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
    env = LiveEnv(
        layout=layout,
        repository=repository,
        servers_root=servers_root,
        async_factory=async_factory,
        sync_factory=sync_factory,
    )
    try:
        yield env
    finally:
        repository.close()
        sync_engine.dispose()
        asyncio.run(async_engine.dispose())


@dataclass
class FakeRuntime:
    running: bool = True
    stop_confirmed: bool = True
    start_ok: bool = True
    alive: bool = True
    log: str = "Done (1.234s)! For help, type help"
    ready_ok: bool = True
    events: list[str] = field(default_factory=list)
    start_hooks: list[str] = field(default_factory=list)
    refresh_start: datetime | None = None
    prepared_journal: str | None = None

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> bool:
        self.events.append("stop")
        if not self.stop_confirmed:
            return False
        self.running = False
        return True

    def start(self) -> bool:
        self.events.append("start")
        self.start_hooks.append("start")
        if not self.start_ok:
            return False
        self.running = True
        return True

    def mark_refresh_start(self, started_at: datetime) -> None:
        self.refresh_start = started_at
        self.start_hooks.append("mark_refresh_start")

    def prepare_start(self, journal_id: str) -> None:
        self.prepared_journal = journal_id
        self.start_hooks.append(f"prepare:{journal_id}")

    def process_alive(self) -> bool:
        return self.alive

    def boot_log(self) -> str:
        return self.log

    def ready(self) -> bool:
        return self.ready_ok


@dataclass
class StuckStopRuntime(FakeRuntime):
    """stop() claims success but the container keeps running (B-2)."""

    def stop(self) -> bool:
        self.events.append("stop")
        return True


@dataclass
class FakeBackupService:
    backup_id: str = BACKUP_ID
    pinned: dict[str, bool] = field(default_factory=dict)
    created: list[tuple[str, Path]] = field(default_factory=list)
    restored: list[tuple[str, str, Path]] = field(default_factory=list)
    unpinned: list[str] = field(default_factory=list)

    async def create_pinned_backup(self, server_id: str, live_dir: Path) -> str:
        self.created.append((server_id, Path(live_dir)))
        self.pinned[self.backup_id] = True
        return self.backup_id

    async def restore_backup(
        self, server_id: str, backup_id: str, live_dir: Path
    ) -> None:
        self.restored.append((server_id, backup_id, Path(live_dir)))
        target = Path(live_dir)
        (target / "world").mkdir(parents=True, exist_ok=True)
        (target / "world" / "level.dat").write_text("backup-world", encoding="utf-8")

    async def set_pinned(
        self, server_id: str, backup_id: str, pinned: bool
    ) -> None:
        del server_id
        self.pinned[backup_id] = pinned
        if not pinned:
            self.unpinned.append(backup_id)


class FakeExporter:
    def __init__(self, export_id: str = "exp-1", ops: str = '["staged"]') -> None:
        self.export_id = export_id
        self.ops = ops
        self.calls: list[tuple[Path, str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.fencing_calls = 0

    async def __call__(
        self,
        staging: Path,
        commit_sha: str,
        *,
        export_id: str = "",
        fencing_verifier: Callable[[], None] | None = None,
    ) -> None:
        self.calls.append((Path(staging), commit_sha))
        self.kwargs.append(
            {"export_id": export_id, "fencing_verifier": fencing_verifier}
        )
        if fencing_verifier is not None:
            fencing_verifier()
            self.fencing_calls += 1
        staging.mkdir(parents=True, exist_ok=False)
        (staging / "server.properties").write_text(
            f"motd={commit_sha}\n", encoding="utf-8"
        )
        (staging / "config").mkdir()
        (staging / "config" / "app.yml").write_text(
            f"config={commit_sha}\n", encoding="utf-8"
        )
        (staging / "ops.json").write_text(self.ops, encoding="utf-8")
        (staging / "plugins" / "sample").mkdir(parents=True)
        (staging / "plugins" / "sample" / "config.yml").write_text(
            "sample: true\n", encoding="utf-8"
        )
        (staging / ".onx-complete.json").write_text(
            json.dumps({"export_id": self.export_id, "file_count": 5}),
            encoding="utf-8",
        )


class _FakeLeaseContext:
    def __init__(self, log: list[str], name: str, token: int) -> None:
        self._log = log
        self._name = name
        self._token = token

    async def __aenter__(self) -> SimpleNamespace:
        self._log.append(f"{self._name}:enter")
        return SimpleNamespace(fencing_token=self._token)

    async def __aexit__(self, *_exc: object) -> bool:
        self._log.append(f"{self._name}:exit")
        return False


class FakeLeaseManager:
    def __init__(self, log: list[str], name: str, token: int) -> None:
        self._log = log
        self._name = name
        self._token = token

    def acquire(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float | None = None,
    ) -> _FakeLeaseContext:
        del server_id, holder, wait_timeout
        return _FakeLeaseContext(self._log, self._name, self._token)


def _write(root: Path, relpath: str, data: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _populate_live(live: Path) -> None:
    _write(live, "server.properties", "motd=live\n")
    _write(live, "config/app.yml", "app: live\n")
    _write(live, "ops.json", '["alice"]')
    _write(live, "plugins/Essentials/warps/home.yml", "home: world\n")
    _write(live, "world/level.dat", "live-world")
    _write(live, ".onx/worktrees/feature/notes.txt", "uncommitted\n")


def _request(
    env: LiveEnv,
    *,
    retention: str = "until_health_gate",
    previous_sha: str = PREV_SHA,
    target_sha: str = TARGET_SHA,
) -> LiveRefreshRequest:
    return LiveRefreshRequest(
        server_id=SERVER_ID,
        live_dir=env.servers_root / SERVER_ID,
        staging_dir=env.servers_root / STAGING,
        export_bytes=0,
        retention_policy=retention,
        previous_main_sha=previous_sha,
        target_main_sha=target_sha,
        export_id="exp-1",
    )


def _repo_lease(env: LiveEnv) -> RepoLeaseManager:
    return RepoLeaseManager(
        locks_dir=env.layout.locks,
        session_factory=env.async_factory,
        sync_session_factory=env.sync_factory,
        wait_timeout_seconds=5.0,
    )


class LoggingRepoLeaseManager(RepoLeaseManager):
    """Real fenced repo lease that records acquire/exit ordering."""

    def __init__(self, log: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._log = log

    @asynccontextmanager
    async def acquire(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float | None = None,
        ttl_seconds: float | None = None,
    ):
        self._log.append("repo:enter")
        try:
            async with super().acquire(
                server_id,
                holder=holder,
                wait_timeout=wait_timeout,
                ttl_seconds=ttl_seconds,
            ) as token:
                yield token
        finally:
            self._log.append("repo:exit")


class LostRepoLeaseManager:
    """Lease manager returning an already-lost token."""

    def __init__(self) -> None:
        self.acquired = 0

    @asynccontextmanager
    async def acquire(self, server_id: str, *, holder: str, wait_timeout=None):
        del server_id, holder, wait_timeout
        self.acquired += 1
        yield SimpleNamespace(fencing_token=7, is_lost=True)


def _service(
    env: LiveEnv,
    *,
    runtime: FakeRuntime,
    backup: FakeBackupService,
    exporter: FakeExporter,
    lifecycle: Any | None = None,
    repo: Any | None = None,
    reset_main_ref: Callable[[str, str], None] | None = None,
    now: datetime | None = None,
) -> LiveRefreshService:
    return LiveRefreshService(
        env.layout,
        repository=env.repository,
        runtime=runtime,
        backup_service=backup,
        stage_export=exporter,
        lifecycle_lease=lifecycle,
        repo_lease=repo if repo is not None else _repo_lease(env),
        reset_main_ref=reset_main_ref,
        servers_data_dir=env.servers_root,
        now=(lambda: now) if now is not None else None,
    )


def _snapshot_manifest(env: LiveEnv, snapshot_id: str) -> dict[str, object]:
    path = env.layout.class_c_vault_dir(SERVER_ID) / snapshot_id / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _retained_tree(journal: RefreshJournalRecord) -> Path:
    """Where the previous tree actually lives for this journal."""
    if journal.used_exchange:
        return Path(journal.staging_path)
    if journal.previous_path:
        return Path(journal.previous_path)
    return previous_tree_path(journal.live_path)


# ----------------------------------------------------------------------
# Seven-step happy path and retention policies
# ----------------------------------------------------------------------


async def test_until_health_gate_refresh_completes_and_cleans_previous(
    live_env: LiveEnv,
) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    runtime = FakeRuntime()
    backup = FakeBackupService()
    exporter = FakeExporter()

    result = await _service(
        env, runtime=runtime, backup=backup, exporter=exporter
    ).refresh(_request(env))

    journal = result.journal
    assert result.health.passed is True
    assert result.rolled_back is False
    assert journal.phase == "COMPLETED"
    assert journal.terminal is True
    assert journal.pre_upgrade_backup_id == BACKUP_ID
    assert journal.class_c_snapshot_id
    assert journal.previous_tree_retained is False
    assert journal.retention_policy == "until_health_gate"
    assert exporter.calls[0][1] == TARGET_SHA
    assert exporter.kwargs[0]["export_id"] == "exp-1"
    assert exporter.kwargs[0]["fencing_verifier"] is not None
    assert exporter.fencing_calls == 1
    assert runtime.refresh_start is not None
    assert runtime.prepared_journal == journal.journal_id
    assert runtime.start_hooks == [
        "mark_refresh_start",
        f"prepare:{journal.journal_id}",
        "start",
    ]

    assert (live / "server.properties").read_text(encoding="utf-8") == f"motd={TARGET_SHA}\n"
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "live-world"
    assert (live / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    assert (live / "plugins" / "Essentials" / "warps" / "home.yml").is_file()
    assert (live / "ops.json").read_text(encoding="utf-8") == '["staged"]'
    assert not _retained_tree(journal).exists()
    assert runtime.events == ["stop", "start"]

    assert backup.pinned[BACKUP_ID] is True
    manifest = _snapshot_manifest(env, journal.class_c_snapshot_id)
    assert manifest["pinned"] is True


async def test_until_confirm_retains_until_explicit_unpin(live_env: LiveEnv) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    runtime = FakeRuntime()
    backup = FakeBackupService()
    exporter = FakeExporter()
    service = _service(env, runtime=runtime, backup=backup, exporter=exporter)

    result = await service.refresh(_request(env, retention="until_confirm"))

    previous = _retained_tree(result.journal)
    assert result.journal.phase == "COMPLETED"
    assert result.journal.previous_tree_retained is True
    assert previous.is_dir()
    assert backup.pinned[BACKUP_ID] is True

    confirmed = await service.confirm_upgrade_unpin(SERVER_ID)

    assert confirmed.phase == "UPGRADE_CONFIRMED"
    assert confirmed.terminal is True
    assert not previous.exists()
    assert confirmed.previous_tree_retained is False
    assert backup.pinned[BACKUP_ID] is False
    assert backup.unpinned == [BACKUP_ID]
    manifest = _snapshot_manifest(env, confirmed.class_c_snapshot_id)
    assert manifest["pinned"] is False

    again = await service.confirm_upgrade_unpin(SERVER_ID)
    assert again.phase == "UPGRADE_CONFIRMED"


async def test_hour_policy_retains_previous_tree_with_expiry(live_env: LiveEnv) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    moment = datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
    service = _service(
        env,
        runtime=FakeRuntime(),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
        now=moment,
    )

    result = await service.refresh(_request(env, retention="24h"))

    assert result.journal.phase == "COMPLETED"
    assert result.journal.previous_tree_retained is True
    assert result.journal.previous_tree_expires_at == moment + timedelta(hours=24)
    assert _retained_tree(result.journal).is_dir()


async def test_carry_and_swap_persists_retention_override(live_env: LiveEnv) -> None:
    """GLM F1: the validated override must persist to DB and mirror JSON."""
    env = live_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _populate_live(live)
    _write(staging, "server.properties", "motd=staged\n")
    _write(staging, "config/app.yml", "config=staged\n")
    _write(
        staging,
        ".onx-complete.json",
        json.dumps({"export_id": "exp-1", "file_count": 2}),
    )
    journal = await env.repository.create(
        server_id=SERVER_ID,
        fencing_token=3,
        live_path=live,
        staging_path=staging,
        previous_path=previous_tree_path(live),
        phase="QUIESCED",
        retention_policy="until_health_gate",
    )
    orchestrator = RefreshOrchestrator(
        env.layout,
        repository=env.repository,
        servers_data_dir=env.servers_root,
    )

    result = await orchestrator.carry_and_swap(
        journal, retention_policy="until_confirm", exchange_supported=False
    )

    assert result.journal.retention_policy == "until_confirm"
    assert result.journal.previous_tree_expires_at is None
    stored = await env.repository.get(journal.journal_id)
    assert stored is not None
    assert stored.retention_policy == "until_confirm"
    mirror = json.loads(
        env.repository.journal_path(SERVER_ID).read_text(encoding="utf-8")
    )
    assert mirror["retention_policy"] == "until_confirm"

    with pytest.raises(ConflictError, match="confirmation"):
        await orchestrator.prepare_prior_previous_tree(SERVER_ID)


# ----------------------------------------------------------------------
# Health gate
# ----------------------------------------------------------------------


async def test_health_gate_process_death_fails_first_step() -> None:
    result = await run_health_gate(process_alive=lambda: False)
    assert result.passed is False
    assert result.failed_step == STEP_PROCESS_ALIVE


async def test_health_gate_crash_pattern_fails_boot_log_step() -> None:
    result = await run_health_gate(
        process_alive=lambda: True,
        boot_log=lambda: "Encountered an unexpected exception",
    )
    assert result.passed is False
    assert result.failed_step == STEP_BOOT_LOG
    assert "unexpected exception" in (result.reason or "")


async def test_health_gate_readiness_failure() -> None:
    result = await run_health_gate(
        process_alive=lambda: True,
        boot_log=None,
        ready=lambda: False,
    )
    assert result.passed is False
    assert result.failed_step == STEP_READINESS


async def test_health_gate_stability_window_rechecks_process() -> None:
    calls = {"count": 0}

    def alive() -> bool:
        calls["count"] += 1
        return calls["count"] == 1

    async def fake_sleep(_delay: float) -> None:
        return None

    result = await run_health_gate(
        process_alive=alive,
        stability_window=0.01,
        sleep=fake_sleep,
    )
    assert result.passed is False
    assert result.failed_step == STEP_STABILITY


async def test_health_gate_readiness_timeout_uses_configured_bound() -> None:
    def slow_ready() -> bool:
        time.sleep(0.2)
        return True

    result = await HealthGateEvaluator(
        process_alive=lambda: True,
        ready=slow_ready,
        timeout=0.01,
    ).evaluate()
    assert result.passed is False
    assert result.failed_step == STEP_READINESS
    assert "within" in (result.reason or "")


async def test_health_gate_rejects_negative_window() -> None:
    with pytest.raises(ValidationError):
        HealthGateEvaluator(process_alive=lambda: True, stability_window=-1)


# ----------------------------------------------------------------------
# Automatic triad rollback
# ----------------------------------------------------------------------


async def test_health_failure_rolls_back_from_previous_tree(live_env: LiveEnv) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    runtime = FakeRuntime(log="Exception in server tick loop")
    backup = FakeBackupService()
    exporter = FakeExporter()
    resets: list[tuple[str, str]] = []

    def reset_main_ref(server_id: str, sha: str) -> None:
        resets.append((server_id, sha))

    result = await _service(
        env,
        runtime=runtime,
        backup=backup,
        exporter=exporter,
        reset_main_ref=reset_main_ref,
    ).refresh(_request(env))

    journal = result.journal
    assert result.health.passed is False
    assert result.health.failed_step == STEP_BOOT_LOG
    assert result.rolled_back is True
    assert journal.phase == "ROLLED_BACK"
    assert journal.terminal is True
    assert journal.pre_upgrade_backup_id == BACKUP_ID
    assert journal.class_c_snapshot_id

    # Class A+B fast rename restored the old tree, then the complement was
    # carried back from the broken tree.
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=live\n"
    assert (live / "config" / "app.yml").read_text(encoding="utf-8") == "app: live\n"
    assert (live / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    # Class C snapshot and Class E backup restore overwrite their class.
    assert (live / "ops.json").read_text(encoding="utf-8") == '["alice"]'
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "backup-world"
    # The main ref is reset to the previous release.
    assert resets == [(SERVER_ID, PREV_SHA)]
    # Pinned artifacts stay pinned after an automatic rollback.
    assert backup.pinned[BACKUP_ID] is True
    manifest = _snapshot_manifest(env, journal.class_c_snapshot_id)
    assert manifest["pinned"] is True
    # The retained previous tree was consumed by the rollback.
    assert not _retained_tree(journal).exists()
    assert not previous_tree_path(live).exists()


async def test_rollback_reexports_previous_release_without_previous_tree(
    live_env: LiveEnv,
) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _write(live, "server.properties", f"motd={TARGET_SHA}\n")
    _write(live, "config/app.yml", f"config={TARGET_SHA}\n")
    _write(live, "world/level.dat", "new-world")
    _write(live, ".onx/worktrees/feature/notes.txt", "uncommitted\n")
    create = env.repository.create_sync
    created = create(
        server_id=SERVER_ID,
        fencing_token=11,
        live_path=live,
        staging_path=staging,
        previous_path=previous_tree_path(live),
        phase="CARRIED",
        export_id="exp-1",
        previous_main_sha=PREV_SHA,
        target_main_sha=TARGET_SHA,
    )
    exporter = FakeExporter(export_id="exp-prev")
    resets: list[tuple[str, str]] = []

    def reset_main_ref(server_id: str, sha: str) -> None:
        resets.append((server_id, sha))

    rollback = TriadRollbackService(
        env.layout,
        repository=env.repository,
        runtime=FakeRuntime(running=False),
        stage_export=exporter,
        reset_main_ref=reset_main_ref,
        servers_data_dir=env.servers_root,
    )

    result = await rollback.rollback(SERVER_ID, created.journal_id, reason="test")

    assert result.used_previous_tree is False
    assert result.restored_class_c is False
    assert result.restored_backup is False
    assert result.journal.phase == "ROLLED_BACK"
    assert exporter.calls[-1][1] == PREV_SHA
    assert (live / "server.properties").read_text(encoding="utf-8") == f"motd={PREV_SHA}\n"
    assert (live / "config" / "app.yml").read_text(encoding="utf-8") == f"config={PREV_SHA}\n"
    # Complement entries were carried from the broken tree into the re-export.
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "new-world"
    assert (live / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    assert resets == [(SERVER_ID, PREV_SHA)]


# ----------------------------------------------------------------------
# session.lock guard, lock order, and commands
# ----------------------------------------------------------------------


async def test_session_lock_blocks_refresh_before_any_mutation(
    live_env: LiveEnv,
) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    (live / "session.lock").write_bytes(b"locked")
    runtime = FakeRuntime()
    backup = FakeBackupService()

    with pytest.raises(ConflictError, match="session.lock"):
        await _service(
            env, runtime=runtime, backup=backup, exporter=FakeExporter()
        ).refresh(_request(env))

    assert await env.repository.get_active_for_server(SERVER_ID) is None
    assert backup.created == []
    assert (env.servers_root / STAGING).exists() is False
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=live\n"
    assert runtime.events == ["stop"]


async def test_lifecycle_lease_is_acquired_before_repo_lease(live_env: LiveEnv) -> None:
    env = live_env
    _populate_live(env.servers_root / SERVER_ID)
    log: list[str] = []
    lifecycle = FakeLeaseManager(log, "lifecycle", token=1)
    repo = LoggingRepoLeaseManager(
        log,
        locks_dir=env.layout.locks,
        session_factory=env.async_factory,
        sync_session_factory=env.sync_factory,
        wait_timeout_seconds=5.0,
    )

    result = await _service(
        env,
        runtime=FakeRuntime(running=False),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
        lifecycle=lifecycle,
        repo=repo,
    ).refresh(_request(env))

    assert log == ["lifecycle:enter", "repo:enter", "repo:exit", "lifecycle:exit"]
    assert result.journal.fencing_token >= 1


async def test_refresh_command_handler_delegates(live_env: LiveEnv) -> None:
    env = live_env
    _populate_live(env.servers_root / SERVER_ID)
    service = _service(
        env,
        runtime=FakeRuntime(),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
    )
    handler = RefreshServerCommandHandler(service)
    request = _request(env)

    result = await handler(RefreshServerCommand(server_id=SERVER_ID, request=request))

    assert result.journal.phase == "COMPLETED"

    confirm = ConfirmUpgradeCommandHandler(service)
    record = await confirm(ConfirmUpgradeCommand(server_id=SERVER_ID))
    assert record.phase == "UPGRADE_CONFIRMED"

    mismatch = LiveRefreshRequest(
        server_id="srv-other",
        live_dir=request.live_dir,
        staging_dir=request.staging_dir,
        export_bytes=0,
    )
    with pytest.raises(ValidationError):
        await handler(RefreshServerCommand(server_id=SERVER_ID, request=mismatch))


class _StubRefreshService:
    def __init__(self, label: str) -> None:
        self.label = label
        self.requests: list[LiveRefreshRequest] = []

    async def refresh(self, request: LiveRefreshRequest) -> Any:
        self.requests.append(request)
        return SimpleNamespace(label=self.label)


async def test_refresh_command_handler_builds_a_fresh_service_per_request(
    live_env: LiveEnv,
) -> None:
    env = live_env
    built: list[_StubRefreshService] = []

    async def factory(server_id: str) -> Any:
        assert server_id == SERVER_ID
        service = _StubRefreshService(f"svc-{len(built) + 1}")
        built.append(service)
        return service

    handler = RefreshServerCommandHandler(cast(Any, factory))
    request = _request(env)

    first = await handler(RefreshServerCommand(server_id=SERVER_ID, request=request))
    second = await handler(RefreshServerCommand(server_id=SERVER_ID, request=request))

    assert cast(Any, first).label == "svc-1"
    assert cast(Any, second).label == "svc-2"
    assert len(built) == 2
    assert built[0] is not built[1]
    assert built[0].requests == [request]
    assert built[1].requests == [request]


# ----------------------------------------------------------------------
# P2-5d3 red-team remediation
# ----------------------------------------------------------------------


class RejectingRepoLease:
    """Lease manager whose token was bumped by another writer."""

    def assert_fencing_token_sync(self, server_id: str, fencing_token: int) -> None:
        raise FencingTokenMismatchError(
            server_id=server_id,
            expected_token=fencing_token,
            actual_token=fencing_token + 1,
        )


async def test_lost_repo_lease_aborts_before_any_mutation(live_env: LiveEnv) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    backup = FakeBackupService()
    exporter = FakeExporter()
    lost = LostRepoLeaseManager()

    with pytest.raises(FencingTokenMismatchError):
        await _service(
            env,
            runtime=FakeRuntime(),
            backup=backup,
            exporter=exporter,
            repo=lost,
        ).refresh(_request(env))

    assert lost.acquired == 1
    assert backup.created == []
    assert exporter.calls == []
    assert not (env.servers_root / STAGING).exists()
    assert await env.repository.get_active_for_server(SERVER_ID) is None
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=live\n"


def test_fencing_guard_rejects_lost_token() -> None:
    guard = FencingGuard(
        SERVER_ID,
        cast(RepoLeaseToken, SimpleNamespace(fencing_token=3, is_lost=True)),
        None,
    )
    with pytest.raises(FencingTokenMismatchError):
        guard.check()


async def test_compensate_carrying_uses_orchestrator_path_guard(
    live_env: LiveEnv,
) -> None:
    """Regression: _compensate must resolve validate_swap_path on the orchestrator."""
    env = live_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _write(live, "server.properties", "motd=live\n")
    _write(staging, "world/level.dat", "carried-world")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=1,
        phase="CARRYING",
        live_path=live,
        staging_path=staging,
        previous_path=previous_tree_path(live),
        carried_entries=["world"],
    )
    service = _service(
        env,
        runtime=FakeRuntime(),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
    )

    await service._compensate(created, 1, RuntimeError("simulated carry failure"))

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "FAILED_CLEAN"
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "carried-world"
    assert not (staging / "world").exists()


async def test_bumped_fencing_token_aborts_rollback_before_previous_tree_swap(
    live_env: LiveEnv,
) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    previous = previous_tree_path(live)
    _write(live, "server.properties", "motd=broken\n")
    _write(previous, "server.properties", "motd=previous\n")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=11,
        live_path=live,
        staging_path=env.servers_root / STAGING,
        previous_path=previous,
        phase="CARRIED",
    )
    rollback = TriadRollbackService(
        env.layout,
        repository=env.repository,
        runtime=FakeRuntime(running=False),
        servers_data_dir=env.servers_root,
        repo_lease=RejectingRepoLease(),  # type: ignore[arg-type]
    )

    with pytest.raises(FencingTokenMismatchError):
        await rollback.rollback(SERVER_ID, created.journal_id, reason="tampered")

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "CARRIED"
    assert (previous / "server.properties").read_text(encoding="utf-8") == "motd=previous\n"
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=broken\n"


async def test_crash_recovery_rollback_separates_lease_and_journal_tokens(
    live_env: LiveEnv,
) -> None:
    """B-A1: startup recovery holds lease token 2 while the journal has token 1.

    The journal compare-and-swap must keep using the journal row's token; only
    the live-writer fence check may use the newly acquired lease token.
    """
    env = live_env
    live = env.servers_root / SERVER_ID
    previous = previous_tree_path(live)
    _write(live, "server.properties", f"motd={TARGET_SHA}\n")
    _write(live, "world/level.dat", "new-world")
    _write(previous, "server.properties", "motd=previous\n")

    repo_lease = _repo_lease(env)
    # The crashed refresh acquired the lease once (token 1) and died.
    async with repo_lease.acquire(SERVER_ID, holder="crashed-refresh") as token:
        assert token.fencing_token == 1

    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=1,
        live_path=live,
        staging_path=env.servers_root / STAGING,
        previous_path=previous,
        phase="STARTING",
        export_id="exp-1",
        previous_main_sha=PREV_SHA,
        target_main_sha=TARGET_SHA,
    )

    reconciler = RefreshStartupReconciler(
        env.layout,
        repository=env.repository,
        servers_data_dir=env.servers_root,
        repo_lease=repo_lease,
    )
    summary = await reconciler.reconcile()

    recovered = env.repository.get_sync(created.journal_id)
    assert recovered is not None
    assert recovered.phase == "ROLLBACK_REQUIRED"
    assert created.journal_id in summary.transitioned_journals

    service = _service(
        env,
        runtime=FakeRuntime(running=False),
        backup=FakeBackupService(),
        exporter=FakeExporter(export_id="exp-prev"),
        repo=repo_lease,
    )
    result = await RollbackRefreshCommandHandler(service)(
        RollbackRefreshCommand(
            server_id=SERVER_ID,
            journal_id=created.journal_id,
            reason="crash recovery",
        )
    )

    # The rollback acquired token 2; the journal CAS used its recorded token 1.
    assert result.journal.phase == "ROLLED_BACK"
    assert result.journal.terminal is True
    assert result.used_previous_tree is True
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=previous\n"
    assert not previous.exists()


async def test_rollback_aborts_before_swap_when_runtime_survives_stop(
    live_env: LiveEnv,
) -> None:
    """B-2: a stop claim without a dead container must not touch the live tree."""
    env = live_env
    live = env.servers_root / SERVER_ID
    previous = previous_tree_path(live)
    _write(live, "server.properties", "motd=broken\n")
    _write(previous, "server.properties", "motd=previous\n")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=3,
        live_path=live,
        staging_path=env.servers_root / STAGING,
        previous_path=previous,
        phase="STARTING",
    )
    runtime = StuckStopRuntime(running=True)
    rollback = TriadRollbackService(
        env.layout,
        repository=env.repository,
        runtime=runtime,
        servers_data_dir=env.servers_root,
    )

    with pytest.raises(ConflictError, match="still running after stop"):
        await rollback.rollback(SERVER_ID, created.journal_id, reason="test")

    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "ROLLING_BACK"
    assert runtime.events == ["stop"]
    # Neither tree was swapped and the rollback artifact is untouched.
    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=broken\n"
    assert (
        previous / "server.properties"
    ).read_text(encoding="utf-8") == "motd=previous\n"


async def test_reexport_rollback_restores_carried_entries_when_swap_fails(
    live_env: LiveEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.versioning.application.refresh_orchestrator as refresh_module

    env = live_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _write(live, "server.properties", f"motd={TARGET_SHA}\n")
    _write(live, "world/level.dat", "new-world")
    _write(live, ".onx/worktrees/feature/notes.txt", "uncommitted\n")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=5,
        live_path=live,
        staging_path=staging,
        previous_path=previous_tree_path(live),
        phase="CARRIED",
        export_id="exp-1",
        previous_main_sha=PREV_SHA,
        target_main_sha=TARGET_SHA,
    )

    def failing_swap(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated swap failure")

    monkeypatch.setattr(refresh_module, "swap_directories", failing_swap)
    rollback = TriadRollbackService(
        env.layout,
        repository=env.repository,
        runtime=FakeRuntime(running=False),
        stage_export=FakeExporter(export_id="exp-prev"),
        servers_data_dir=env.servers_root,
    )

    with pytest.raises(RuntimeError, match="simulated swap failure"):
        await rollback.rollback(SERVER_ID, created.journal_id, reason="test")

    # The journaled carry plan was restored to live before the error escaped.
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "new-world"
    assert (live / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "ROLLING_BACK"
    assert "world" in stored.carried_entries


async def test_until_health_gate_marks_completed_before_previous_cleanup(
    live_env: LiveEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    service = _service(
        env,
        runtime=FakeRuntime(),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
    )
    observed: list[str] = []
    original = service._orchestrator.clean_previous_tree

    def wrapper(record: RefreshJournalRecord) -> bool:
        stored = env.repository.get_sync(record.journal_id)
        assert stored is not None
        observed.append(stored.phase)
        return original(record)

    monkeypatch.setattr(service._orchestrator, "clean_previous_tree", wrapper)

    result = await service.refresh(_request(env))

    assert observed == ["COMPLETED"]
    assert result.journal.phase == "COMPLETED"
    assert not _retained_tree(result.journal).exists()


async def test_prepare_prior_previous_tree_refuses_non_terminal_retained_tree(
    live_env: LiveEnv,
) -> None:
    """F1: a stuck journal's rollback artifact is never deleted by a refresh."""
    env = live_env
    live = env.servers_root / SERVER_ID
    previous = env.servers_root / f"{SERVER_ID}.prev"
    _write(live, "server.properties", "motd=live\n")
    _write(previous, "old.txt", "old")
    created = env.repository.create_sync(
        server_id=SERVER_ID,
        fencing_token=1,
        phase="CARRIED",
        live_path=live,
        staging_path=env.servers_root / STAGING,
        previous_path=previous,
    )
    env.repository.transition_sync(
        created.journal_id,
        fencing_token=1,
        phase="ROLLBACK_REQUIRED",
        retention_policy="1h",
        previous_tree_retained=True,
        previous_tree_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    orchestrator = RefreshOrchestrator(
        env.layout,
        repository=env.repository,
        servers_data_dir=env.servers_root,
    )

    with pytest.raises(ConflictError, match=created.journal_id) as blocked:
        await orchestrator.prepare_prior_previous_tree(SERVER_ID)

    assert blocked.value.http_status == 409
    assert (previous / "old.txt").read_text(encoding="utf-8") == "old"
    stored = env.repository.get_sync(created.journal_id)
    assert stored is not None
    assert stored.phase == "ROLLBACK_REQUIRED"
    assert stored.previous_tree_retained is True


async def test_release_pins_unpins_rolled_back_artifacts(live_env: LiveEnv) -> None:
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    backup = FakeBackupService()
    service = _service(
        env,
        runtime=FakeRuntime(log="Exception in server tick loop"),
        backup=backup,
        exporter=FakeExporter(),
    )

    result = await service.refresh(_request(env))
    assert result.journal.phase == "ROLLED_BACK"
    assert backup.pinned[BACKUP_ID] is True
    snapshot_id = result.journal.class_c_snapshot_id
    assert _snapshot_manifest(env, snapshot_id)["pinned"] is True

    handler = ReleaseRefreshPinsCommandHandler(service)
    released = await handler(
        ReleaseRefreshPinsCommand(server_id=SERVER_ID, journal_id=result.journal.journal_id)
    )

    assert released.phase == "ROLLED_BACK"
    assert backup.pinned[BACKUP_ID] is False
    assert backup.unpinned == [BACKUP_ID]
    assert _snapshot_manifest(env, snapshot_id)["pinned"] is False


async def test_service_operations_fail_closed_on_non_posix(
    live_env: LiveEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows is Simple-only: no live-refresh path may acquire leases or preflight."""
    env = live_env
    live = env.servers_root / SERVER_ID
    _populate_live(live)
    service = _service(
        env,
        runtime=FakeRuntime(),
        backup=FakeBackupService(),
        exporter=FakeExporter(),
    )

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("POSIX-only refresh path reached on a non-POSIX host")

    monkeypatch.setattr(os, "statvfs", _forbidden, raising=False)
    monkeypatch.setattr(os, "name", "nt")

    with pytest.raises(ServerModeVersioningDisabledError, match="POSIX hosts"):
        await service.refresh(_request(env))
    with pytest.raises(ServerModeVersioningDisabledError, match="POSIX hosts"):
        await service.rollback(SERVER_ID)
    with pytest.raises(ServerModeVersioningDisabledError, match="POSIX hosts"):
        await service.confirm_upgrade_unpin(SERVER_ID)
    with pytest.raises(ServerModeVersioningDisabledError, match="POSIX hosts"):
        await service.release_pins(SERVER_ID)


def test_live_refresh_request_generates_export_id(live_env: LiveEnv) -> None:
    import re

    request = LiveRefreshRequest(
        server_id=SERVER_ID,
        live_dir=live_env.servers_root / SERVER_ID,
        staging_dir=live_env.servers_root / STAGING,
        export_bytes=0,
    )

    assert re.fullmatch(r"[0-9a-f]{32}", request.export_id)
