"""Unit tests for Pre-Backend Database Reconciler."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from alembic import command

from app.core.persistence.reconciler import (
    DatabaseReconciler,
    ReconcileAction,
    ReconcileLock,
    ReconcileStatus,
    redact_db_url,
)


def test_redact_db_url():
    assert redact_db_url("sqlite+aiosqlite:///data/onx.db") == "sqlite+aiosqlite:///data/onx.db"
    assert redact_db_url("postgresql+asyncpg://user:secret@localhost:5432/db") == "postgresql+asyncpg://user:****@localhost:5432/db"
    assert redact_db_url("") == ""


def test_reconcile_fresh_database():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "fresh.db"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        
        reconciler = DatabaseReconciler(db_url=db_url)
        parents, target_head, _ = reconciler.resolve_migration_graph()
        assert target_head is not None

        result = reconciler.reconcile(auto_upgrade=True)
        assert result.status == ReconcileStatus.RECONCILED
        assert result.action_taken == ReconcileAction.INITIALIZE
        assert result.verified_revision == target_head
        assert result.target_revision == target_head
        assert test_db.is_file()

        # Second run should report READY
        result2 = reconciler.reconcile(auto_upgrade=True)
        assert result2.status == ReconcileStatus.READY
        assert result2.action_taken == ReconcileAction.NONE
        assert result2.verified_revision == target_head


def test_reconcile_outdated_database_with_backup():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "outdated.db"
        backup_dir = Path(tmpdir) / "backups"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        
        reconciler = DatabaseReconciler(db_url=db_url)
        parents, target_head, _ = reconciler.resolve_migration_graph()

        # Initialize to an older revision (e.g. 001)
        cfg = reconciler.get_alembic_config()
        orig_url = os.environ.get("ONX_DATABASE_URL")
        try:
            os.environ["ONX_DATABASE_URL"] = db_url
            command.upgrade(cfg, "001")
        finally:
            if orig_url:
                os.environ["ONX_DATABASE_URL"] = orig_url
            else:
                os.environ.pop("ONX_DATABASE_URL", None)

        # Inspect should show revision '001'
        initial_revs, _ = reconciler.inspect_current_revisions()
        assert initial_revs == ["001"]

        # Run reconciler with backup
        result = reconciler.reconcile(auto_upgrade=True)
        assert result.status == ReconcileStatus.RECONCILED
        assert result.action_taken == ReconcileAction.UPGRADE
        assert result.verified_revision == target_head
        assert result.backup_path is not None
        assert Path(result.backup_path).is_file()


def test_reconcile_blocked_on_unknown_revision():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "unknown.db"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        
        # Create table with unknown revision
        with sqlite3.connect(str(test_db)) as conn:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            conn.execute("INSERT INTO alembic_version VALUES ('unknown_rev_xyz_999')")
            conn.commit()

        reconciler = DatabaseReconciler(db_url=db_url)
        result = reconciler.reconcile(auto_upgrade=True)

        assert result.status == ReconcileStatus.BLOCKED_UNSAFE
        assert "unknown schema revision" in result.message
        assert result.action_taken == ReconcileAction.NONE


def test_reconcile_blocked_on_multiple_heads():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "multi_head.db"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        
        # Create table with two revisions recorded
        with sqlite3.connect(str(test_db)) as conn:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES ('001')")
            conn.execute("INSERT INTO alembic_version VALUES ('002')")
            conn.commit()

        reconciler = DatabaseReconciler(db_url=db_url)
        result = reconciler.reconcile(auto_upgrade=True)

        assert result.status == ReconcileStatus.BLOCKED_UNSAFE
        assert "multiple" in result.message


def test_reconcile_check_only_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "check_only.db"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"

        reconciler = DatabaseReconciler(db_url=db_url)
        result = reconciler.reconcile(auto_upgrade=False)

        assert result.status == ReconcileStatus.BLOCKED_UNSAFE
        assert "auto_upgrade is False" in result.message


def test_reconcile_cli_interface():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "cli.db"
        db_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"

        proc = subprocess.run(
            [sys.executable, "-m", "app.core.persistence.reconciler", "--json", "--db-url", db_url],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout.strip())
        assert data["status"] == "RECONCILED"
        assert data["action_taken"] == "INITIALIZE"


def test_reconcile_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file = Path(tmpdir) / "reconcile.lock"
        
        lock1 = ReconcileLock(lock_path=lock_file, timeout_sec=1.0)
        assert lock1.acquire() is True
        
        lock2 = ReconcileLock(lock_path=lock_file, timeout_sec=0.2)
        assert lock2.acquire() is False
        
        lock1.release()
        assert lock2.acquire() is True
        lock2.release()


def test_canonicalize_relative_sqlite_url():
    from app.core.persistence.reconciler import canonicalize_db_url
    anchor = Path("/tmp/app_root/backend")
    
    # Relative path
    res = canonicalize_db_url("sqlite+aiosqlite:///data/onx.db", anchor)
    assert res == f"sqlite+aiosqlite:///{anchor.as_posix()}/data/onx.db"
    
    # Non-SQLite / memory
    assert canonicalize_db_url("sqlite+aiosqlite:///:memory:", anchor) == "sqlite+aiosqlite:///:memory:"
    assert canonicalize_db_url("postgresql+asyncpg://localhost/db", anchor) == "postgresql+asyncpg://localhost/db"


def test_target_consistency_reconciler_and_backend_engine():
    """Prove that after reconciler initializes a database, backend Database engine sees the exact same DB and passes."""
    import asyncio
    from app.core.config import AppSettings
    from app.core.persistence.db import database
    from app.core.persistence.db_revision import check_database_compatibility
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "unified.db"
        canonical_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        
        # 1. Run reconciler synchronously on fresh DB (same as launcher subprocess)
        reconciler = DatabaseReconciler(db_url=canonical_url)
        res = reconciler.reconcile(auto_upgrade=True)
        assert res.status == ReconcileStatus.RECONCILED
        assert res.verified_revision is not None
        
        # 2. In async backend context, verify compatibility check passes on backend's engine
        async def _check_backend():
            settings = AppSettings(database_url=canonical_url)
            database.init(settings=settings)
            try:
                status = await check_database_compatibility()
                assert status.ok is True
            finally:
                await database.engine.dispose()
                
        asyncio.run(_check_backend())

