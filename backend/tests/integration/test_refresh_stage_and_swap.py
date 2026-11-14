"""P2-5d1 refresh staging, complement carry, swap, and retention tests."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import ConflictError, ValidationError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.versioning.application import refresh_orchestrator
from app.modules.versioning.application.refresh_orchestrator import (
    RefreshOrchestrator,
    carry_complement_entries,
    discover_complement_entries,
    parse_retention_policy,
    previous_tree_path,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.directory_swap import DirectorySwapJournal
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRepository

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode refresh staging and swap are POSIX-only",
)

SERVER_ID = "srv-swap"
STAGING = f"{SERVER_ID}.staging"


@dataclass
class RefreshEnv:
    layout: HostStateLayout
    repository: RefreshJournalRepository
    servers_root: Path
    async_factory: async_sessionmaker
    sync_factory: sessionmaker[Session]


@pytest.fixture
def refresh_env(tmp_path: Path):
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
    env = RefreshEnv(
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


def _write(root: Path, relpath: str, data: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _marker(directory: Path, export_id: str = "exp-1") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".onx-complete.json").write_text(
        json.dumps({"export_id": export_id, "file_count": 4}),
        encoding="utf-8",
    )


def _populate_live(live: Path) -> None:
    _write(live, "server.properties", "motd=live\n")
    _write(live, "config/app.yml", "live: true\n")
    _write(live, "config/custom.yml", "custom: true\n")
    _write(live, "plugins/sample/config.yml", "live: true\n")
    _write(live, "plugins/Essentials/warps/home.yml", "world: world\n")
    _write(live, "world/level.dat", "live-world")
    _write(live, "world_nether/region/r.0.0.mca", "nether")
    _write(live, "world_custom/level.dat", "custom-world")
    _write(live, "logs/latest.log", "log")
    _write(live, "ops.json", '["alice"]')
    _write(live, "whitelist.json", '["alice"]')
    _write(live, ".onx/worktrees/feature/notes.txt", "uncommitted")
    _write(live, ".onx-manager/server.json", '{"mode": "advanced"}')


def _stage_export(staging: Path) -> None:
    _write(staging, "server.properties", "motd=staged\n")
    _write(staging, "config/app.yml", "staged: true\n")
    _write(staging, "plugins/sample/config.yml", "staged: true\n")
    _marker(staging)


EXPECTED_CARRIED = (
    ".onx",
    ".onx-manager",
    "config/custom.yml",
    "logs",
    "ops.json",
    "plugins/Essentials",
    "whitelist.json",
    "world",
    "world_custom",
    "world_nether",
)


def _orchestrator(env: RefreshEnv) -> RefreshOrchestrator:
    return RefreshOrchestrator(
        env.layout,
        repository=env.repository,
        servers_data_dir=env.servers_root,
    )


async def _create_journal(
    env: RefreshEnv,
    *,
    fencing_token: int = 1,
    live: Path | None = None,
    staging: Path | None = None,
    export_id: str = "exp-1",
) -> object:
    live_path = live or env.servers_root / SERVER_ID
    staging_path = staging or env.servers_root / STAGING
    return await env.repository.create(
        server_id=SERVER_ID,
        fencing_token=fencing_token,
        live_path=live_path,
        staging_path=staging_path,
        export_id=export_id,
    )


# ----------------------------------------------------------------------
# Retention policy validation
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "policy", "delta"),
    [
        ("until_health_gate", "until_health_gate", None),
        ("until_confirm", "until_confirm", None),
        (24, "24h", timedelta(hours=24)),
        ("1h", "1h", timedelta(hours=1)),
        ("168h", "168h", timedelta(hours=168)),
        ("72", "72h", timedelta(hours=72)),
    ],
)
def test_parse_retention_policy_accepts(
    raw: str | int, policy: str, delta: timedelta | None
) -> None:
    assert parse_retention_policy(raw) == (policy, delta)


@pytest.mark.parametrize(
    "raw",
    [0, 169, -1, True, 3.0, "0", "0h", "-1h", "169h", "1.5h", "weekly"],
)
def test_parse_retention_policy_rejects(raw: object) -> None:
    with pytest.raises(ValidationError):
        parse_retention_policy(raw)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Complement carry
# ----------------------------------------------------------------------


def test_complement_carry_moves_only_unowned_entries(tmp_path: Path) -> None:
    live = tmp_path / "servers" / SERVER_ID
    staging = tmp_path / "servers" / STAGING
    live.mkdir(parents=True)
    staging.mkdir(parents=True)
    _populate_live(live)
    _stage_export(staging)

    assert discover_complement_entries(live, staging) == list(EXPECTED_CARRIED)
    assert carry_complement_entries(live, staging) == list(EXPECTED_CARRIED)

    assert (staging / "server.properties").read_text(encoding="utf-8") == "motd=staged\n"
    assert (staging / "config" / "app.yml").read_text(encoding="utf-8") == "staged: true\n"
    assert (staging / "config" / "custom.yml").read_text(encoding="utf-8") == "custom: true\n"
    assert (staging / "plugins" / "Essentials" / "warps" / "home.yml").is_file()
    assert (staging / "world" / "level.dat").read_text(encoding="utf-8") == "live-world"
    assert (staging / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    assert (staging / ".onx-manager" / "server.json").is_file()
    assert not (live / "world").exists()
    assert not (live / ".onx").exists()
    assert (live / "server.properties").is_file()


async def test_carry_and_swap_journals_phases_and_retains_previous(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _populate_live(live)
    _stage_export(staging)
    journal = await _create_journal(env, fencing_token=7)

    result = await _orchestrator(env).carry_and_swap(
        journal, exchange_supported=False
    )

    assert result.journal.phase == "CARRIED"
    assert result.journal.carried_entries == EXPECTED_CARRIED
    assert result.journal.previous_tree_retained is True
    assert result.journal.previous_tree_expires_at is None
    assert result.swap.used_exchange is False
    assert result.swap.previous_tree_path == previous_tree_path(live)

    previous = previous_tree_path(live)
    assert previous.is_dir()
    assert (previous / "server.properties").read_text(encoding="utf-8") == "motd=live\n"
    assert not (previous / "world").exists()

    assert (live / "server.properties").read_text(encoding="utf-8") == "motd=staged\n"
    assert (live / "world" / "level.dat").read_text(encoding="utf-8") == "live-world"
    assert (live / ".onx" / "worktrees" / "feature" / "notes.txt").is_file()
    assert (live / ".onx-complete.json").is_file()

    swap_journal = DirectorySwapJournal(
        env.layout.journal / SERVER_ID / "swap.json"
    )
    swap_record = swap_journal.read()
    assert swap_record is not None
    assert swap_record.phase == "SWAP_COMPLETED"
    assert swap_record.keep_previous is True


async def test_hour_policy_records_previous_tree_expiry(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _populate_live(live)
    _stage_export(staging)
    journal = await _create_journal(env)
    moment = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    result = await _orchestrator(env).carry_and_swap(
        journal,
        retention_policy="2h",
        exchange_supported=False,
        now=moment,
    )

    assert result.journal.retention_policy == "until_health_gate"
    assert result.journal.previous_tree_expires_at == moment + timedelta(hours=2)


# ----------------------------------------------------------------------
# Real Git worktree survival and the lock guard
# ----------------------------------------------------------------------


def _git_env(live: Path, env: RefreshEnv) -> None:
    live.mkdir(parents=True, exist_ok=True)
    _write(live, "server.properties", "motd=live\n")
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
        lec=None,
    )
    GitRepositoryService(env.layout).initialize(SERVER_ID, live, lockfile)
    GitBranchService(env.layout).create_branch(SERVER_ID, live, "feature")


@pytest.mark.skipif(shutil.which("git") is None, reason="git binary is required")
async def test_git_worktree_and_uncommitted_edits_survive_swap(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _git_env(live, env)
    worktree = live / ".onx" / "worktrees" / "feature"
    (worktree / "notes.txt").write_text("uncommitted\n", encoding="utf-8")
    _stage_export(staging)
    journal = await _create_journal(env)

    result = await _orchestrator(env).carry_and_swap(
        journal, exchange_supported=False
    )

    assert ".onx" in result.carried_entries
    runner = GitBranchService(env.layout).open_runner(SERVER_ID, live)
    listing = runner.run("worktree", "list", "--porcelain").stdout
    assert str(worktree) in listing
    assert "feature" in listing
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == "uncommitted\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="git binary is required")
async def test_locked_worktree_blocks_preflight_before_stop(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    _git_env(live, env)
    gitdir = env.layout.repo_dir(SERVER_ID) / "repo.git" / "worktrees" / "feature"
    (gitdir / "locked").write_text("locked\n", encoding="utf-8")

    with pytest.raises(ConflictError) as exc:
        _orchestrator(env).preflight(
            SERVER_ID,
            live_dir=live,
            staging_dir=staging,
            export_bytes=1024,
        )

    assert exc.value.http_status == 409
    assert "feature" in str(exc.value)
    assert not previous_tree_path(live).exists()
    assert (live / ".onx" / "worktrees" / "feature").is_dir()


# ----------------------------------------------------------------------
# Prior previous-tree retention
# ----------------------------------------------------------------------


async def _retained_journal(
    env: RefreshEnv,
    *,
    policy: str = "until_health_gate",
    phase: str = "COMPLETED",
) -> object:
    token = 3
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    record = await env.repository.create(
        server_id=SERVER_ID,
        fencing_token=token,
        live_path=live,
        staging_path=staging,
        previous_path=previous_tree_path(live),
        retention_policy=policy,
    )
    return await env.repository.transition(
        record.journal_id,
        fencing_token=token,
        phase=phase,
        previous_tree_retained=True,
    )


async def test_unconfirmed_until_confirm_prior_tree_blocks_refresh(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    previous = previous_tree_path(env.servers_root / SERVER_ID)
    previous.mkdir(parents=True)
    _write(previous, "server.properties", "old\n")
    record = await _retained_journal(env, policy="until_confirm")

    with pytest.raises(ConflictError) as exc:
        await _orchestrator(env).prepare_prior_previous_tree(SERVER_ID)

    assert exc.value.http_status == 409
    assert "confirmation" in str(exc.value)
    assert previous.is_dir()
    stored = await env.repository.get(record.journal_id)
    assert stored is not None
    assert stored.previous_tree_retained is True


async def test_non_until_confirm_prior_tree_is_cleaned(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    previous = previous_tree_path(env.servers_root / SERVER_ID)
    previous.mkdir(parents=True)
    _write(previous, "server.properties", "old\n")
    record = await _retained_journal(env, policy="until_health_gate")

    removed = await _orchestrator(env).prepare_prior_previous_tree(SERVER_ID)

    assert removed == (str(previous),)
    assert not previous.exists()
    stored = await env.repository.get(record.journal_id)
    assert stored is not None
    assert stored.previous_tree_retained is False


async def test_confirmed_until_confirm_prior_tree_is_cleaned(
    refresh_env: RefreshEnv,
) -> None:
    env = refresh_env
    previous = previous_tree_path(env.servers_root / SERVER_ID)
    previous.mkdir(parents=True)
    _write(previous, "server.properties", "old\n")
    await _retained_journal(env, policy="until_confirm", phase="UPGRADE_CONFIRMED")

    removed = await _orchestrator(env).prepare_prior_previous_tree(SERVER_ID)

    assert removed == (str(previous),)
    assert not previous.exists()


# ----------------------------------------------------------------------
# Thread-shielded swap
# ----------------------------------------------------------------------


async def test_thread_shielded_swap_joins_worker_on_cancellation(
    refresh_env: RefreshEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = refresh_env
    live = env.servers_root / SERVER_ID
    staging = env.servers_root / STAGING
    live.mkdir(parents=True)
    _write(live, "server.properties", "live\n")
    _stage_export(staging)
    journal = await _create_journal(env)

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    thread_box: dict[str, threading.Thread] = {}

    def fake_swap(
        _live: Path, _staging: Path, _journal_path: DirectorySwapJournal, **_kwargs: object
    ) -> SimpleNamespace:
        thread_box["thread"] = threading.current_thread()
        started.set()
        release.wait(5)
        finished.set()
        return SimpleNamespace(used_exchange=False)

    monkeypatch.setattr(refresh_orchestrator, "swap_directories", fake_swap)
    task = asyncio.create_task(
        _orchestrator(env).carry_and_swap(journal, exchange_supported=False)
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert finished.is_set()
    worker = thread_box["thread"]
    assert worker.name == "onx-refresh-swap"
    assert worker.is_alive() is False
    stored = await env.repository.get(journal.journal_id)
    assert stored is not None
    assert stored.phase == "CARRYING"
