from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from alembic import command as alembic_command
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus

PRIOR_HEAD = "b1e2100000023"


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _server_columns(db_url: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns("servers")}
    finally:
        engine.dispose()


def test_mode_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'server-mode.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message

    cfg = reconciler.get_alembic_config()

    columns = _server_columns(db_url)
    assert "mode" in columns
    mode_column = columns["mode"]
    assert mode_column["nullable"] is False
    assert "simple" in str(mode_column["default"])

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    head = heads[0]
    revision = script.get_revision(head)
    assert revision.down_revision == PRIOR_HEAD
    assert head == RELEASE_MINIMUM_DB_REVISION == EXPECTED_ALEMBIC_HEAD

    alembic_command.downgrade(cfg, PRIOR_HEAD)

    downgraded = _server_columns(db_url)
    assert "mode" not in downgraded
