"""Pre-backend Database Readiness & Reconciliation Layer.

This module provides independent inspection, safety classification, automatic
reconciliation, and post-migration verification for the database schema before
the FastAPI backend is launched.

Design constraints:
  1. Decoupled from FastAPI: No imports of app routers, middleware, lifespan,
     or domain handlers.
  2. Single Source of Truth: The migration target is resolved dynamically from
     Alembic's ScriptDirectory head revision.
  3. Strict Safety Policy: Only forward migrations along a known ancestry path
     are automatically applied. Downgrades, unknown revisions, and divergent
     heads are blocked.
  4. ACID SQLite Backups: Uses sqlite3.Connection.backup() to produce a
     consistent checkpointed snapshot before modifying existing SQLite databases.
  5. Concurrency Control: Uses .onx/locks/reconcile.lock to serialize startup
     reconciliation attempts.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError


class ReconcileStatus(str, Enum):
    READY = "READY"
    RECONCILED = "RECONCILED"
    BLOCKED_UNSAFE = "BLOCKED_UNSAFE"
    FAILED = "FAILED"
    UNREACHABLE = "UNREACHABLE"


class ReconcileAction(str, Enum):
    NONE = "NONE"
    INITIALIZE = "INITIALIZE"
    UPGRADE = "UPGRADE"


@dataclass(frozen=True)
class ReconcileResult:
    status: ReconcileStatus
    action_taken: ReconcileAction
    initial_revisions: list[str]
    target_revision: str | None
    verified_revision: str | None
    backup_path: str | None
    message: str
    duration_ms: float
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["action_taken"] = self.action_taken.value
        return data


def redact_db_url(url: str) -> str:
    """Mask credentials in database connection strings for safe logging."""
    if not url:
        return ""
    try:
        # SQLite URLs do not contain network credentials
        if "sqlite" in url.lower():
            return url
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username or ''}:****@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url
    except Exception:
        return "<redacted-db-url>"


def find_project_root() -> Path:
    """Determine the canonical project root directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend" / "pyproject.toml").is_file() or (parent / ".git").is_dir():
            return parent
    return current.parents[4]


PROJECT_ROOT = find_project_root()
BACKEND_DIR = PROJECT_ROOT / "backend"
ALEMBIC_DIR = BACKEND_DIR / "alembic"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ONX_DIR = PROJECT_ROOT / ".onx"
LOGS_DIR = ONX_DIR / "logs"
LOCKS_DIR = ONX_DIR / "locks"
RECONCILIATION_LOG = LOGS_DIR / "reconciliation.log"
RECONCILE_LOCK_FILE = LOCKS_DIR / "reconcile.lock"


def get_configured_db_url() -> str:
    """Resolve database URL following authoritative project precedence."""
    env_url = os.environ.get("ONX_DATABASE_URL") or os.environ.get("MCS_DATABASE_URL")
    if env_url:
        return env_url

    if ALEMBIC_INI.is_file():
        cfg = AlembicConfig(str(ALEMBIC_INI))
        url = cfg.get_main_option("sqlalchemy.url")
        if url:
            return url

    return "sqlite+aiosqlite:///data/onx.db"


def parse_sqlite_file_path(db_url: str) -> Path | None:
    """Extract filesystem Path from a SQLite database URL."""
    if "sqlite" not in db_url.lower():
        return None

    # Strip dialect prefixes: sqlite+aiosqlite:///path -> path, sqlite:///path -> path
    raw_path = db_url.split(":///", 1)[-1] if ":///" in db_url else db_url.split("://", 1)[-1]
    if raw_path == ":memory:" or not raw_path:
        return None

    p = Path(raw_path)
    if not p.is_absolute():
        p = (BACKEND_DIR / p).resolve()
    return p


class ReconcileLock:
    """File-based mutual exclusion lock with stale-lock detection."""

    def __init__(self, lock_path: Path = RECONCILE_LOCK_FILE, timeout_sec: float = 15.0):
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec
        self.acquired = False
        self._fd: int | None = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_sec

        while time.time() < deadline:
            try:
                # O_CREAT | O_EXCL ensures atomic creation
                self._fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                )
                pid_info = f"pid={os.getpid()}\ntime={datetime.now(timezone.utc).isoformat()}\n"
                os.write(self._fd, pid_info.encode("utf-8"))
                self.acquired = True
                return True
            except FileExistsError:
                # Check for stale lock
                if self._is_stale():
                    try:
                        self.lock_path.unlink()
                        continue
                    except OSError:
                        pass
                time.sleep(0.1)

        return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self.acquired:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
            self.acquired = False

    def _is_stale(self) -> bool:
        """Inspect lockfile to see if holding process has died."""
        try:
            content = self.lock_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("pid="):
                    pid = int(line.split("=", 1)[1].strip())
                    if not self._pid_alive(pid):
                        return True
            # If lock is older than 60s, consider stale
            mtime = self.lock_path.stat().st_mtime
            if (time.time() - mtime) > 60.0:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if not handle:
                    return False
                kernel32.CloseHandle(handle)
                return True
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def __enter__(self) -> ReconcileLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire reconciliation lock at {self.lock_path} within {self.timeout_sec}s")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class DatabaseReconciler:
    """Orchestrates database inspection, safe migration, and verification."""

    def __init__(
        self,
        db_url: str | None = None,
        alembic_ini_path: Path = ALEMBIC_INI,
        alembic_dir_path: Path = ALEMBIC_DIR,
    ):
        self.db_url = db_url or get_configured_db_url()
        self.alembic_ini = alembic_ini_path
        self.alembic_dir = alembic_dir_path
        self.sqlite_file = parse_sqlite_file_path(self.db_url)

    def get_alembic_config(self) -> AlembicConfig:
        cfg = AlembicConfig(str(self.alembic_ini))
        cfg.set_main_option("script_location", str(self.alembic_dir))
        cfg.set_main_option("sqlalchemy.url", self.db_url)
        return cfg

    def resolve_migration_graph(self) -> tuple[dict[str, str | None], str | None, list[str]]:
        """Load the migration graph and dynamic head(s) from Alembic scripts.

        Returns:
            (parents_dict, current_head, all_heads)
        """
        cfg = self.get_alembic_config()
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        current_head = script.get_current_head() if len(heads) == 1 else None
        parents = {rev.revision: rev.down_revision for rev in script.walk_revisions()}
        return parents, current_head, heads

    def inspect_current_revisions(self) -> tuple[list[str], str | None]:
        """Read actual revision(s) recorded in the target database.

        Returns:
            (revisions_list, error_message)
        """
        # For SQLite: handle absent file cleanly
        if self.sqlite_file is not None:
            if not self.sqlite_file.is_file() or self.sqlite_file.stat().st_size == 0:
                return [], None
            try:
                # Direct read via standard sqlite3 with WAL support and short busy timeout
                with sqlite3.connect(f"file:{self.sqlite_file.as_posix()}?mode=ro", uri=True, timeout=5.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
                    if not cursor.fetchone():
                        return [], None
                    cursor.execute("SELECT version_num FROM alembic_version")
                    rows = cursor.fetchall()
                    return [r[0] for r in rows if r and r[0]], None
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    return [], f"SQLite database is locked: {exc}"
                return [], f"SQLite operational error: {exc}"
            except Exception as exc:
                return [], f"Failed to inspect SQLite database: {exc}"

        # For PostgreSQL or non-SQLite: Use synchronous SQLAlchemy engine
        sync_url = self.db_url.replace("+aiosqlite", "").replace("+asyncpg", "")
        try:
            engine = create_engine(sync_url, connect_args={"connect_timeout": 5} if "postgresql" in sync_url else {})
            with engine.connect() as conn:
                res = conn.execute(text("SELECT version_num FROM alembic_version"))
                rows = res.fetchall()
                engine.dispose()
                return [r[0] for r in rows if r and r[0]], None
        except OperationalError as exc:
            return [], f"Database connection/operational error: {exc}"
        except DBAPIError:
            # Table does not exist -> uninitialized
            return [], None
        except Exception as exc:
            return [], f"Database inspection failed: {exc}"

    def backup_sqlite_database(self, backup_dir: Path | None = None) -> Path | None:
        """Create an ACID-consistent snapshot of the SQLite database using native backup API."""
        if self.sqlite_file is None or not self.sqlite_file.is_file() or self.sqlite_file.stat().st_size == 0:
            return None

        target_dir = backup_dir or (BACKEND_DIR / "backups")
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = target_dir / f"{self.sqlite_file.stem}_backup_{timestamp}.db"

        with sqlite3.connect(str(self.sqlite_file), timeout=10.0) as src_conn:
            with sqlite3.connect(str(backup_path)) as dst_conn:
                src_conn.backup(dst_conn)

        return backup_path

    def reconcile(self, auto_upgrade: bool = True) -> ReconcileResult:
        """Execute the full inspect -> plan -> reconcile -> verify lifecycle."""
        start_time = time.perf_counter()

        # Step 1: Resolve migration graph dynamically
        try:
            parents, target_head, all_heads = self.resolve_migration_graph()
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000.0
            return ReconcileResult(
                status=ReconcileStatus.FAILED,
                action_taken=ReconcileAction.NONE,
                initial_revisions=[],
                target_revision=None,
                verified_revision=None,
                backup_path=None,
                message=f"Failed to load migration graph from {self.alembic_dir}: {exc}",
                duration_ms=duration,
                error_detail=str(exc),
            )

        if len(all_heads) > 1 or target_head is None:
            duration = (time.perf_counter() - start_time) * 1000.0
            heads_str = ", ".join(sorted(all_heads))
            return ReconcileResult(
                status=ReconcileStatus.BLOCKED_UNSAFE,
                action_taken=ReconcileAction.NONE,
                initial_revisions=[],
                target_revision=None,
                verified_revision=None,
                backup_path=None,
                message=f"Migration graph contains multiple heads ({heads_str}). Manual branch resolution required.",
                duration_ms=duration,
            )

        # Step 2: Inspect current live database state
        initial_revs, inspect_err = self.inspect_current_revisions()
        if inspect_err is not None:
            duration = (time.perf_counter() - start_time) * 1000.0
            return ReconcileResult(
                status=ReconcileStatus.UNREACHABLE,
                action_taken=ReconcileAction.NONE,
                initial_revisions=[],
                target_revision=target_head,
                verified_revision=None,
                backup_path=None,
                message=f"Database unreachable or locked: {inspect_err}",
                duration_ms=duration,
                error_detail=inspect_err,
            )

        # Step 3: Classify state & determine plan
        action = ReconcileAction.NONE

        if not initial_revs:
            # Uninitialized / fresh database -> safe to initialize to head
            action = ReconcileAction.INITIALIZE
        elif len(initial_revs) > 1:
            duration = (time.perf_counter() - start_time) * 1000.0
            return ReconcileResult(
                status=ReconcileStatus.BLOCKED_UNSAFE,
                action_taken=ReconcileAction.NONE,
                initial_revisions=initial_revs,
                target_revision=target_head,
                verified_revision=None,
                backup_path=None,
                message=f"Database reports multiple recorded revisions ({', '.join(initial_revs)}). Automatic reconciliation blocked.",
                duration_ms=duration,
            )
        else:
            current_rev = initial_revs[0]
            if current_rev == target_head:
                duration = (time.perf_counter() - start_time) * 1000.0
                return ReconcileResult(
                    status=ReconcileStatus.READY,
                    action_taken=ReconcileAction.NONE,
                    initial_revisions=initial_revs,
                    target_revision=target_head,
                    verified_revision=current_rev,
                    backup_path=None,
                    message=f"Database schema is up to date at head revision '{target_head}'.",
                    duration_ms=duration,
                )
            elif current_rev not in parents:
                duration = (time.perf_counter() - start_time) * 1000.0
                return ReconcileResult(
                    status=ReconcileStatus.BLOCKED_UNSAFE,
                    action_taken=ReconcileAction.NONE,
                    initial_revisions=initial_revs,
                    target_revision=target_head,
                    verified_revision=None,
                    backup_path=None,
                    message=f"Database contains unknown schema revision '{current_rev}' not in repository migration history. Automatic migration blocked.",
                    duration_ms=duration,
                )
            else:
                # Verify that current_rev is indeed an ancestor of target_head
                ancestry: set[str] = set()
                curr: str | None = target_head
                while curr is not None and curr not in ancestry:
                    ancestry.add(curr)
                    curr = parents.get(curr)

                if current_rev in ancestry:
                    action = ReconcileAction.UPGRADE
                else:
                    duration = (time.perf_counter() - start_time) * 1000.0
                    return ReconcileResult(
                        status=ReconcileStatus.BLOCKED_UNSAFE,
                        action_taken=ReconcileAction.NONE,
                        initial_revisions=initial_revs,
                        target_revision=target_head,
                        verified_revision=None,
                        backup_path=None,
                        message=f"Database revision '{current_rev}' is divergent from target head '{target_head}'. Automatic migration blocked.",
                        duration_ms=duration,
                    )

        if not auto_upgrade:
            duration = (time.perf_counter() - start_time) * 1000.0
            return ReconcileResult(
                status=ReconcileStatus.BLOCKED_UNSAFE,
                action_taken=ReconcileAction.NONE,
                initial_revisions=initial_revs,
                target_revision=target_head,
                verified_revision=None,
                backup_path=None,
                message=f"Database requires reconciliation ({action.value} to '{target_head}') but auto_upgrade is False.",
                duration_ms=duration,
            )

        # Step 4: Perform safe reconciliation
        backup_created: Path | None = None
        try:
            # Create ACID backup if SQLite file exists and is populated
            if action == ReconcileAction.UPGRADE and self.sqlite_file is not None:
                backup_created = self.backup_sqlite_database()

            cfg = self.get_alembic_config()
            # Set environment variable so alembic/env.py picks it up consistently, restoring afterwards
            orig_onx_url = os.environ.get("ONX_DATABASE_URL")
            try:
                os.environ["ONX_DATABASE_URL"] = self.db_url
                command.upgrade(cfg, "head")
            finally:
                if orig_onx_url is not None:
                    os.environ["ONX_DATABASE_URL"] = orig_onx_url
                else:
                    os.environ.pop("ONX_DATABASE_URL", None)

        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000.0
            return ReconcileResult(
                status=ReconcileStatus.FAILED,
                action_taken=action,
                initial_revisions=initial_revs,
                target_revision=target_head,
                verified_revision=None,
                backup_path=str(backup_created) if backup_created else None,
                message=f"Alembic migration execution failed: {exc}",
                duration_ms=duration,
                error_detail=str(exc),
            )

        # Step 5: Post-migration verification
        verified_revs, verify_err = self.inspect_current_revisions()
        duration = (time.perf_counter() - start_time) * 1000.0

        if verify_err or not verified_revs or verified_revs[0] != target_head:
            got = verified_revs[0] if verified_revs else "none"
            return ReconcileResult(
                status=ReconcileStatus.FAILED,
                action_taken=action,
                initial_revisions=initial_revs,
                target_revision=target_head,
                verified_revision=got,
                backup_path=str(backup_created) if backup_created else None,
                message=f"Post-migration verification failed: expected '{target_head}', got '{got}' (Error: {verify_err or 'mismatch'}).",
                duration_ms=duration,
                error_detail=verify_err,
            )

        action_desc = "initialized and upgraded" if action == ReconcileAction.INITIALIZE else "upgraded"
        return ReconcileResult(
            status=ReconcileStatus.RECONCILED,
            action_taken=action,
            initial_revisions=initial_revs,
            target_revision=target_head,
            verified_revision=target_head,
            backup_path=str(backup_created) if backup_created else None,
            message=f"Database successfully {action_desc} to head revision '{target_head}'.",
            duration_ms=duration,
        )


def log_reconciliation_event(result: ReconcileResult, db_url: str, log_file: Path = RECONCILIATION_LOG) -> None:
    """Append structured diagnostic log entry to .onx/logs/reconciliation.log."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_db": redact_db_url(db_url),
            "status": result.status.value,
            "action_taken": result.action_taken.value,
            "initial_revisions": result.initial_revisions,
            "target_revision": result.target_revision,
            "verified_revision": result.verified_revision,
            "backup_path": result.backup_path,
            "message": result.message,
            "duration_ms": round(result.duration_ms, 2),
            "error_detail": result.error_detail,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="onx-manager Pre-Backend Database Reconciler")
    parser.add_argument("--json", action="store_true", help="Emit result as JSON to stdout")
    parser.add_argument("--check-only", action="store_true", help="Inspect without applying migrations")
    parser.add_argument("--db-url", type=str, default=None, help="Explicit database connection URL")
    args = parser.parse_args()

    reconciler = DatabaseReconciler(db_url=args.db_url)

    try:
        with ReconcileLock():
            result = reconciler.reconcile(auto_upgrade=not args.check_only)
    except TimeoutError as exc:
        result = ReconcileResult(
            status=ReconcileStatus.UNREACHABLE,
            action_taken=ReconcileAction.NONE,
            initial_revisions=[],
            target_revision=None,
            verified_revision=None,
            backup_path=None,
            message=f"Failed to acquire reconciliation lock: {exc}",
            duration_ms=0.0,
            error_detail=str(exc),
        )
    except Exception as exc:
        result = ReconcileResult(
            status=ReconcileStatus.FAILED,
            action_taken=ReconcileAction.NONE,
            initial_revisions=[],
            target_revision=None,
            verified_revision=None,
            backup_path=None,
            message=f"Unexpected reconciliation error: {exc}",
            duration_ms=0.0,
            error_detail=str(exc),
        )

    log_reconciliation_event(result, reconciler.db_url)

    if args.json:
        print(json.dumps(result.to_dict()))
    else:
        if result.status in (ReconcileStatus.READY, ReconcileStatus.RECONCILED):
            print(f"  [Database] {result.status.value}: {result.message}")
        else:
            print(f"  [Database ERROR] {result.status.value}: {result.message}", file=sys.stderr)

    return 0 if result.status in (ReconcileStatus.READY, ReconcileStatus.RECONCILED) else 1


if __name__ == "__main__":
    sys.exit(main())
