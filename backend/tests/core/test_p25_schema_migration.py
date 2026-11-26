from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command as alembic_command
from app.core.exceptions import ConflictError, FencingTokenMismatchError
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus

PRIOR_HEAD = "b1e2100000025"
JOURNAL_REVISION = "b1e2100000026"
HEAD_REVISION = EXPECTED_ALEMBIC_HEAD
ACTIVE_JOURNAL_INDEX = "ix_refresh_journals_server_active"

LEASE_COLUMNS = {
    "server_id": False,
    "holder": True,
    "fencing_token": False,
    "previous_tree_retention": False,
    "acquired_at": True,
    "expires_at": True,
    "updated_at": False,
}

JOURNAL_COLUMNS = {
    "journal_id": False,
    "server_id": False,
    "export_id": True,
    "fencing_token": False,
    "phase": False,
    "terminal": False,
    "previous_main_sha": True,
    "target_main_sha": True,
    "pre_upgrade_backup_id": True,
    "class_c_snapshot_id": True,
    "live_path": False,
    "staging_path": False,
    "previous_path": True,
    "used_exchange": False,
    "carried_entries_json": False,
    "retention_policy": False,
    "previous_tree_retained": False,
    "previous_tree_expires_at": True,
    "error": True,
    "created_at": False,
    "updated_at": False,
}


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _columns(db_url: str, table: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _tables(db_url: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {ix["name"]: ix for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _insert_journal(db_url: str, journal_id: str, server_id: str, terminal: bool) -> None:
    engine = create_engine(_sync_url(db_url))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO refresh_journals "
                    "(journal_id, server_id, fencing_token, phase, terminal, "
                    "live_path, staging_path, created_at, updated_at) "
                    "VALUES (:journal_id, :server_id, 1, 'ready', :terminal, "
                    "'/live', '/staging', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "journal_id": journal_id,
                    "server_id": server_id,
                    "terminal": terminal,
                },
            )
    finally:
        engine.dispose()


def test_journal_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p25-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)

    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    cfg = reconciler.get_alembic_config()

    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(JOURNAL_REVISION).down_revision == PRIOR_HEAD
    assert RELEASE_MINIMUM_DB_REVISION == HEAD_REVISION == EXPECTED_ALEMBIC_HEAD

    # Downgrade to the previous head, then upgrade the migration under test.
    alembic_command.downgrade(cfg, PRIOR_HEAD)
    tables = _tables(db_url)
    assert "server_repo_leases" not in tables
    assert "refresh_journals" not in tables

    alembic_command.upgrade(cfg, JOURNAL_REVISION)
    tables = _tables(db_url)
    assert "server_repo_leases" in tables
    assert "refresh_journals" in tables

    lease_columns = _columns(db_url, "server_repo_leases")
    assert set(lease_columns) == set(LEASE_COLUMNS)
    assert {name: col["nullable"] for name, col in lease_columns.items()} == LEASE_COLUMNS
    assert "0" in str(lease_columns["fencing_token"]["default"])
    assert "until_health_gate" in str(lease_columns["previous_tree_retention"]["default"])

    journal_columns = _columns(db_url, "refresh_journals")
    assert set(journal_columns) == set(JOURNAL_COLUMNS)
    assert {name: col["nullable"] for name, col in journal_columns.items()} == JOURNAL_COLUMNS
    assert "until_health_gate" in str(journal_columns["retention_policy"]["default"])
    assert "[]" in str(journal_columns["carried_entries_json"]["default"])
    assert "rcon_save_off_active" not in journal_columns

    indexes = _indexes(db_url, "refresh_journals")
    assert ACTIVE_JOURNAL_INDEX in indexes
    assert indexes[ACTIVE_JOURNAL_INDEX]["unique"] == 1

    engine = create_engine(_sync_url(db_url))
    try:
        with engine.connect() as conn:
            ddl = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = :name"
                ),
                {"name": ACTIVE_JOURNAL_INDEX},
            ).scalar_one()
    finally:
        engine.dispose()
    assert "WHERE terminal = 0" in ddl

    # One active (terminal=0) journal per server, but unlimited terminal rows.
    _insert_journal(db_url, "journal-active-1", "server-1", terminal=False)
    with pytest.raises(IntegrityError):
        _insert_journal(db_url, "journal-active-2", "server-1", terminal=False)

    _insert_journal(db_url, "journal-done-1", "server-1", terminal=True)
    _insert_journal(db_url, "journal-done-2", "server-1", terminal=True)
    _insert_journal(db_url, "journal-active-3", "server-2", terminal=False)

    alembic_command.downgrade(cfg, PRIOR_HEAD)
    tables = _tables(db_url)
    assert "server_repo_leases" not in tables
    assert "refresh_journals" not in tables

    # Re-upgrade proves the inspect(conn) guards recreate cleanly after a downgrade.
    alembic_command.upgrade(cfg, JOURNAL_REVISION)
    assert {"server_repo_leases", "refresh_journals"} <= _tables(db_url)
    assert ACTIVE_JOURNAL_INDEX in _indexes(db_url, "refresh_journals")


def test_fencing_token_mismatch_error() -> None:
    error = FencingTokenMismatchError(
        server_id="server-1",
        expected_token=3,
        actual_token=2,
    )
    assert isinstance(error, ConflictError)
    assert error.code == "FENCING_TOKEN_MISMATCH"
    assert error.http_status == 409
    assert error.details == {
        "server_id": "server-1",
        "expected_token": 3,
        "actual_token": 2,
    }

    bare = FencingTokenMismatchError()
    assert bare.code == "FENCING_TOKEN_MISMATCH"
    assert bare.http_status == 409
    assert bare.details == {}
