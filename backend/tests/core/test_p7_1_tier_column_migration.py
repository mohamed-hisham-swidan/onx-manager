"""P7-1: Tier column migration (b1e2100000032) adds `tier` to backup_jobs."""

from __future__ import annotations

from pathlib import Path

from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)


def test_release_minimum_db_revision_bumped_to_b1e2100000032():
    """F001: RELEASE_MINIMUM_DB_REVISION and EXPECTED_ALEMBIC_HEAD are b1e2100000032."""
    assert RELEASE_MINIMUM_DB_REVISION == "b1e2100000032"
    assert EXPECTED_ALEMBIC_HEAD == "b1e2100000032"
    assert len(RELEASE_MINIMUM_DB_REVISION) == 13


def test_migration_file_exists_with_correct_revision_chain():
    """F002: Migration b1e2100000032 exists and revises b1e2100000031."""
    mig_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    mig_file = mig_dir / "b1e2100000032_add_tier_column_to_backup_jobs.py"
    assert mig_file.exists(), f"Migration file missing: {mig_file}"
    content = mig_file.read_text(encoding="utf-8")
    assert 'revision: str = "b1e2100000032"' in content
    assert 'down_revision: str | None = "b1e2100000031"' in content
    assert "tier" in content
    assert "backup_jobs" in content


def test_alembic_head_is_b1e2100000032():
    """F003: Alembic head is b1e2100000032 after P7-1 migration."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_current_head() == "b1e2100000032"
