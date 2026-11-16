"""P3-3 Alembic b1e2100000027 schema, guard, and downgrade tests."""

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
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus

PRIOR_HEAD = "b1e2100000026"
P33_REVISION = "b1e2100000027"
CLASS_C_INDEXES = {
    "ix_class_c_snapshots_server_id",
    "ix_class_c_snapshots_server_created_at",
}


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _tables(db_url: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(db_url: str, table: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _insert_journal(
    db_url: str,
    journal_id: str,
    *,
    terminal: bool,
    snapshot_id: str | None,
) -> None:
    engine = create_engine(_sync_url(db_url))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO refresh_journals "
                    "(journal_id, server_id, fencing_token, phase, terminal, "
                    "class_c_snapshot_id, live_path, staging_path, created_at, updated_at) "
                    "VALUES (:journal_id, 'server-1', 1, :phase, :terminal, "
                    ":snapshot_id, '/live', '/staging', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "journal_id": journal_id,
                    "phase": "COMPLETED" if terminal else "SWAPPING",
                    "terminal": terminal,
                    "snapshot_id": snapshot_id,
                },
            )
    finally:
        engine.dispose()


def test_p33_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p33-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    cfg = reconciler.get_alembic_config()

    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [P33_REVISION]
    assert script.get_revision(P33_REVISION).down_revision == PRIOR_HEAD
    assert RELEASE_MINIMUM_DB_REVISION == P33_REVISION == EXPECTED_ALEMBIC_HEAD

    assert {"class_c_snapshots", "server_secrets"} <= _tables(db_url)

    snapshot_columns = _columns(db_url, "class_c_snapshots")
    assert set(snapshot_columns) == {
        "snapshot_id",
        "server_id",
        "created_at",
        "manifest_sha256",
        "kek_version",
        "file_count",
        "total_bytes",
        "pinned",
        "status",
    }
    assert snapshot_columns["snapshot_id"]["nullable"] is False
    assert snapshot_columns["manifest_sha256"]["nullable"] is False
    assert snapshot_columns["pinned"]["nullable"] is False
    assert snapshot_columns["status"]["nullable"] is False
    assert "active" in str(snapshot_columns["status"]["default"])
    assert _indexes(db_url, "class_c_snapshots") >= CLASS_C_INDEXES

    secret_columns = _columns(db_url, "server_secrets")
    assert set(secret_columns) == {
        "id",
        "server_id",
        "key_name",
        "wrapped_dek",
        "kek_version",
        "nonce",
        "ciphertext",
        "created_at",
        "updated_at",
    }
    assert "ix_server_secrets_server_id" in _indexes(db_url, "server_secrets")

    # downgrade() drops only the two ledger tables; on-disk vault files stay.
    vault_file = (
        tmp_path / "host-state" / "class-c-vault" / "server-1" / "snap-1" / "manifest.json"
    )
    vault_file.parent.mkdir(parents=True)
    vault_file.write_text("{}", encoding="utf-8")

    alembic_command.downgrade(cfg, PRIOR_HEAD)
    remaining = _tables(db_url)
    assert "class_c_snapshots" not in remaining
    assert "server_secrets" not in remaining
    assert vault_file.is_file()

    alembic_command.upgrade(cfg, P33_REVISION)
    assert {"class_c_snapshots", "server_secrets"} <= _tables(db_url)


def test_p33_migration_refuses_open_v1_journal(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p33-guard.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()
    alembic_command.upgrade(cfg, PRIOR_HEAD)
    _insert_journal(
        db_url,
        "journal-open",
        terminal=False,
        snapshot_id="snapshot-v1",
    )

    with pytest.raises(RuntimeError) as exc:
        alembic_command.upgrade(cfg, P33_REVISION)

    message = str(exc.value)
    assert "journal-open" in message
    assert "server-1" in message
    assert "snapshot-v1" in message
    assert "terminal" in message.lower()

    # Settling the journal lets the same migration succeed.
    engine = create_engine(_sync_url(db_url))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE refresh_journals SET terminal = :term, phase = 'COMPLETED' "
                    "WHERE journal_id = 'journal-open'"
                ),
                {"term": True},
            )
    finally:
        engine.dispose()
    alembic_command.upgrade(cfg, P33_REVISION)
    assert {"class_c_snapshots", "server_secrets"} <= _tables(db_url)


def test_p33_migration_allows_terminal_or_empty_snapshot_references(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p33-terminal.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()
    alembic_command.upgrade(cfg, PRIOR_HEAD)
    _insert_journal(db_url, "journal-terminal", terminal=True, snapshot_id="snapshot-v1")
    _insert_journal(db_url, "journal-open-empty", terminal=False, snapshot_id=None)

    alembic_command.upgrade(cfg, P33_REVISION)
    assert {"class_c_snapshots", "server_secrets"} <= _tables(db_url)


def test_p33_migration_upgrades_fresh_database(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p33-fresh.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()

    alembic_command.upgrade(cfg, "head")

    tables = _tables(db_url)
    assert {"class_c_snapshots", "server_secrets", "refresh_journals"} <= tables
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [P33_REVISION]
