"""P3-2 Alembic b1e2100000028 schema tests."""

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

PRIOR_HEAD = "b1e2100000027"
P32_REVISION = "b1e2100000028"


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _tables(db_url: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_p32_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p32-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    cfg = reconciler.get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [P32_REVISION]
    assert script.get_revision(P32_REVISION).down_revision == PRIOR_HEAD
    assert RELEASE_MINIMUM_DB_REVISION == P32_REVISION == EXPECTED_ALEMBIC_HEAD
    assert "server_dynamic_class_c" in _tables(db_url)

    # downgrade
    alembic_command.downgrade(cfg, PRIOR_HEAD)
    assert "server_dynamic_class_c" not in _tables(db_url)
    # re-upgrade
    alembic_command.upgrade(cfg, P32_REVISION)
    assert "server_dynamic_class_c" in _tables(db_url)


def test_p32_fresh_db(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p32-fresh.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()
    alembic_command.upgrade(cfg, "head")
    assert "server_dynamic_class_c" in _tables(db_url)


def test_p32_fk_cascade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p32-fk.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    cfg = reconciler.get_alembic_config()
    alembic_command.upgrade(cfg, "head")

    engine = create_engine(_sync_url(db_url))
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.exec_driver_sql(
                "INSERT INTO servers (id, name, server_type, minecraft_version) "
                "VALUES ('srv-1', 'Server', 'paper', '1.20.4')"
            )
            conn.exec_driver_sql(
                "INSERT INTO server_dynamic_class_c "
                "(id, server_id, relpath, reason, promoted_at, updated_at) "
                "VALUES ('row-1', 'srv-1', 'config/foo.yml', 'ast_diverged', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            conn.exec_driver_sql("DELETE FROM servers WHERE id = 'srv-1'")
            remaining = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM server_dynamic_class_c"
            ).scalar_one()
        assert remaining == 0
    finally:
        engine.dispose()
