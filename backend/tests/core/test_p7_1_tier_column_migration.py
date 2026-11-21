from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _make_alembic_cfg(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def test_p7_1_revision_constants() -> None:
    assert RELEASE_MINIMUM_DB_REVISION == "b1e2100000032"
    assert EXPECTED_ALEMBIC_HEAD == "b1e2100000032"


def test_p7_1_migration_upgrade_downgrade_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "p7_1_mig.db"
    cfg = _make_alembic_cfg(db_path)

    command.upgrade(cfg, "b1e2100000031")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO backup_jobs "
            "(id, server_id, backup_type, status, size_bytes, checksum, pinned, created_at, updated_at) "
            "VALUES ('b-pre', 'srv-1', 'full', 'completed', 123, 'abc', 0, '2026-11-20T00:00:00', '2026-11-20T00:00:00')"
        )
        conn.commit()

    command.upgrade(cfg, "b1e2100000032")
    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(backup_jobs)").fetchall()
        }
        assert "tier" in cols
        assert cols["tier"][3] == 1  # notnull == 1

        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(backup_jobs)").fetchall()
        }
        assert "ix_backup_jobs_server_tier" in indexes
        assert "ix_backup_jobs_server_id" in indexes

        tier_val = conn.execute(
            "SELECT tier FROM backup_jobs WHERE id='b-pre'"
        ).fetchone()
        assert tier_val == ("tier_1",)

    command.downgrade(cfg, "b1e2100000031")
    with sqlite3.connect(db_path) as conn:
        cols_after = {
            row[1] for row in conn.execute("PRAGMA table_info(backup_jobs)").fetchall()
        }
        assert "tier" not in cols_after

    command.upgrade(cfg, "b1e2100000032")
    with sqlite3.connect(db_path) as conn:
        tier_val_re = conn.execute(
            "SELECT tier FROM backup_jobs WHERE id='b-pre'"
        ).fetchone()
        assert tier_val_re == ("tier_1",)
