from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command as alembic_command
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler

PRIOR_HEAD = "b1e2100000024"
PINNED_REVISION = "b1e2100000025"


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _backup_columns(db_url: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns("backup_jobs")}
    finally:
        engine.dispose()


def _backup_indexes(db_url: str) -> list[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return [idx["name"] for idx in inspect(engine).get_indexes("backup_jobs")]
    finally:
        engine.dispose()


def test_upgrade_adds_pinned_and_preserves_legacy_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONX_DATABASE_URL", raising=False)
    monkeypatch.delenv("MCS_DATABASE_URL", raising=False)

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'backup-pinned.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()

    # 1. Build schema up to the prior head (b1e2100000024)
    alembic_command.upgrade(cfg, PRIOR_HEAD)

    pre_columns = _backup_columns(db_url)
    assert "pinned" not in pre_columns

    # 2. Insert legacy row omitting pinned
    sync_engine = create_engine(_sync_url(db_url))
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO backup_jobs (id, server_id) "
                    "VALUES ('legacy-bak-1', 'srv-1')"
                )
            )
    finally:
        sync_engine.dispose()

    # 3. Upgrade to head (b1e2100000025)
    alembic_command.upgrade(cfg, "head")

    # 4. Inspect columns and verify pinned definition
    post_columns = _backup_columns(db_url)
    assert "pinned" in post_columns
    col = post_columns["pinned"]
    assert col["nullable"] is False
    assert col["default"] is not None
    # Empirical observation: SQLite inspector reports boolean server_default as '0'
    # (normalized boolean false in SQLite; Postgres reports false)
    raw_default = str(col["default"]).lower()
    assert col["default"] in ("0", "'0'", "false", "'false'") or any(
        token in raw_default for token in ("0", "false")
    ), f"Unexpected default value: {col['default']!r}"

    # 5. Assert legacy row survives and pinned defaults to false
    sync_engine = create_engine(_sync_url(db_url))
    try:
        with sync_engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, server_id, pinned FROM backup_jobs "
                    "WHERE id = 'legacy-bak-1'"
                )
            ).mappings().first()
            assert row is not None
            assert row["id"] == "legacy-bak-1"
            assert row["server_id"] == "srv-1"
            assert bool(row["pinned"]) is False
    finally:
        sync_engine.dispose()

    # 6. Verify index ix_backup_jobs_server_id was preserved across SQLite batch alter
    indexes = _backup_indexes(db_url)
    assert "ix_backup_jobs_server_id" in indexes

    # 7. Check revision head alignment
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == [PINNED_REVISION]
    head = heads[0]
    rev = script.get_revision(head)
    assert rev.down_revision == PRIOR_HEAD
    assert head == RELEASE_MINIMUM_DB_REVISION == EXPECTED_ALEMBIC_HEAD


def test_downgrade_removes_pinned_and_preserves_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONX_DATABASE_URL", raising=False)
    monkeypatch.delenv("MCS_DATABASE_URL", raising=False)

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'backup-pinned-roundtrip.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()

    # Upgrade directly to head
    alembic_command.upgrade(cfg, "head")

    # Insert a job
    sync_engine = create_engine(_sync_url(db_url))
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO backup_jobs (id, server_id, pinned) "
                    "VALUES ('bak-rt-1', 'srv-rt-1', 1)"
                )
            )
    finally:
        sync_engine.dispose()

    # Downgrade to PRIOR_HEAD
    alembic_command.downgrade(cfg, PRIOR_HEAD)
    downgraded_cols = _backup_columns(db_url)
    assert "pinned" not in downgraded_cols

    # Verify row still exists
    sync_engine = create_engine(_sync_url(db_url))
    try:
        with sync_engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, server_id FROM backup_jobs WHERE id = 'bak-rt-1'")
            ).mappings().first()
            assert row is not None
            assert row["id"] == "bak-rt-1"
    finally:
        sync_engine.dispose()

    # Re-upgrade to head
    alembic_command.upgrade(cfg, "head")
    reupgraded_cols = _backup_columns(db_url)
    assert "pinned" in reupgraded_cols

    sync_engine = create_engine(_sync_url(db_url))
    try:
        with sync_engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, server_id, pinned FROM backup_jobs "
                    "WHERE id = 'bak-rt-1'"
                )
            ).mappings().first()
            assert row is not None
            assert bool(row["pinned"]) is False
    finally:
        sync_engine.dispose()


def test_revision_chain_is_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONX_DATABASE_URL", raising=False)
    monkeypatch.delenv("MCS_DATABASE_URL", raising=False)

    reconciler = DatabaseReconciler(db_url="sqlite+aiosqlite:///:memory:")
    cfg = reconciler.get_alembic_config()
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert heads == [PINNED_REVISION]

    current = script.get_revision(PINNED_REVISION)
    assert current.down_revision == PRIOR_HEAD

    # Walk all revisions down to root
    count = 0
    visited = set()
    while current is not None:
        assert current.revision not in visited
        visited.add(current.revision)
        count += 1
        if current.down_revision is None:
            break
        current = script.get_revision(current.down_revision)

    assert count >= 25
