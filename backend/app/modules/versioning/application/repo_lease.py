"""Per-server repository lease with monotonic fencing (P2-5b).

A repo lease serializes refresh/rollback mutations for one server. The DB row is
the authority: every acquire increments ``fencing_token`` by one and expiry is
computed with the database clock, so worker clock skew cannot split the lease.
An OS thread renews the lease while a sync or async holder is active, and an
optional per-server kernel ``flock`` serializes hosts that share a state dir.

Lock order is fixed: lifecycle lease first, repo lease second.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import ConflictError, FencingTokenMismatchError, MCSError
from app.core.host_state import validate_server_segment

try:
    import fcntl
except ImportError:  # pragma: no cover - Advanced mode is POSIX-only
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS: float = 30.0
HEARTBEAT_INTERVAL_SECONDS: float = 10.0
DEFAULT_WAIT_TIMEOUT_SECONDS: float = 30.0
_MAX_HEARTBEAT_JOIN_SECONDS: float = 5.0
_POLL_SECONDS: float = 0.05

_HELD_REPO_LEASES: ContextVar[frozenset[str] | None] = ContextVar(
    "_held_repo_leases", default=None
)
_SYNC_HELD_REPO_LEASES = threading.local()


@dataclass
class RepoLeaseToken:
    server_id: str
    holder: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    is_lost: bool = False


class RepoLeaseTimeoutError(ConflictError):
    def __init__(self, server_id: str) -> None:
        MCSError.__init__(
            self,
            f"Timed out waiting for repo lease on server '{server_id}'",
            code="REPO_LEASE_TIMEOUT",
            http_status=409,
            details={"server_id": server_id},
        )


def _sync_held_servers() -> set[str]:
    servers = getattr(_SYNC_HELD_REPO_LEASES, "servers", None)
    if servers is None:
        servers = set()
        _SYNC_HELD_REPO_LEASES.servers = servers  # type: ignore[attr-defined]
    return servers


def repo_lease_held_in_context() -> bool:
    """True when this async task or OS thread currently holds a repo lease."""
    if _HELD_REPO_LEASES.get():
        return True
    return bool(getattr(_SYNC_HELD_REPO_LEASES, "servers", None))


def assert_no_repo_lease_held() -> None:
    """Enforce the global lock order ``lifecycle -> repo``."""
    if repo_lease_held_in_context():
        raise RuntimeError(
            "Lock order violation: lifecycle lease must be acquired before repo lease"
        )


def _db_now(dialect: str) -> str:
    if dialect == "postgresql":
        return "NOW()"
    return "strftime('%Y-%m-%d %H:%M:%f','now')"


def _db_expires(dialect: str) -> str:
    if dialect == "postgresql":
        return "NOW() + (CAST(:ttl_seconds AS double precision) * INTERVAL '1 second')"
    return "strftime('%Y-%m-%d %H:%M:%f','now','+' || :ttl_seconds || ' seconds')"


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported DB timestamp: {value!r}")
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


class RepoLeaseManager:
    """Acquire, renew, verify, and release per-server repo leases."""

    def __init__(
        self,
        *,
        sync_session_factory: sessionmaker[Session] | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        locks_dir: Path | str | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        self._sync_session_factory = sync_session_factory
        self._session_factory = session_factory
        self._locks_dir = Path(locks_dir) if locks_dir is not None else None
        self._ttl_seconds = ttl_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._wait_timeout_seconds = wait_timeout_seconds
        self._owned_engine: Engine | None = None
        self._factory_lock = threading.Lock()
        # Fail at construction, not inside the heartbeat thread where the
        # exception would be logged and the lease would silently run unfenced.
        if sync_session_factory is None and session_factory is not None:
            bind = session_factory.kw.get("bind")
            if bind is not None and bind.dialect.name != "sqlite":
                raise RuntimeError(
                    "RepoLeaseManager requires sync_session_factory for non-SQLite "
                    "backends"
                )

    # ------------------------------------------------------------------
    # Session factories and dialect
    # ------------------------------------------------------------------

    def _get_sync_factory(self) -> sessionmaker[Session]:
        if self._sync_session_factory is not None:
            return self._sync_session_factory
        with self._factory_lock:
            if self._sync_session_factory is None:
                self._sync_session_factory = self._derive_sync_factory()
            return self._sync_session_factory

    def _derive_sync_factory(self) -> sessionmaker[Session]:
        url = None
        if self._session_factory is not None:
            bind = self._session_factory.kw.get("bind")
            if bind is not None:
                url = bind.url
        if url is None:
            from app.core.persistence.db import database

            url = database.engine.url
        if url.get_backend_name() != "sqlite":
            raise RuntimeError(
                "RepoLeaseManager requires sync_session_factory for non-SQLite backends"
            )
        sync_url = url.set(drivername="sqlite")
        self._owned_engine = create_engine(
            sync_url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        return sessionmaker(bind=self._owned_engine, expire_on_commit=False)

    def _get_async_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        from app.core.persistence.db import database

        return database.session_factory

    @staticmethod
    def _sync_dialect(factory: sessionmaker[Session]) -> str:
        bind = factory.kw.get("bind")
        if bind is None:  # pragma: no cover - defensive
            raise RuntimeError("RepoLeaseManager sync session factory has no bind")
        return bind.dialect.name

    @staticmethod
    def _async_dialect(factory: async_sessionmaker[AsyncSession]) -> str:
        bind = factory.kw.get("bind")
        if bind is None:  # pragma: no cover - defensive
            raise RuntimeError("RepoLeaseManager async session factory has no bind")
        return bind.dialect.name

    # ------------------------------------------------------------------
    # SQL fragments
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_placeholder_sql(dialect: str) -> str:
        now = _db_now(dialect)
        if dialect == "sqlite":
            return (
                "INSERT OR IGNORE INTO server_repo_leases "
                "(server_id, fencing_token, updated_at) "
                f"VALUES (:sid, 0, {now})"
            )
        return (
            "INSERT INTO server_repo_leases (server_id, fencing_token, updated_at) "
            f"VALUES (:sid, 0, {now}) "
            "ON CONFLICT (server_id) DO NOTHING"
        )

    @staticmethod
    def _acquire_update_sql(dialect: str, *, returning: bool) -> str:
        now = _db_now(dialect)
        expires = _db_expires(dialect)
        sql = (
            "UPDATE server_repo_leases SET "
            "holder = :holder, "
            "fencing_token = fencing_token + 1, "
            f"acquired_at = {now}, expires_at = {expires}, updated_at = {now} "
            "WHERE server_id = :sid AND (holder IS NULL OR expires_at <= " + now + ")"
        )
        if returning:
            sql += " RETURNING fencing_token, acquired_at, expires_at"
        return sql

    @staticmethod
    def _renew_sql(dialect: str) -> str:
        now = _db_now(dialect)
        expires = _db_expires(dialect)
        return (
            "UPDATE server_repo_leases SET "
            f"expires_at = {expires}, updated_at = {now} "
            "WHERE server_id = :sid AND fencing_token = :token "
            "AND holder = :holder AND expires_at > " + now
        )

    # ------------------------------------------------------------------
    # Sync primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _begin_immediate_sync(session: Session, dialect: str) -> None:
        if dialect != "sqlite":
            return
        with contextlib.suppress(Exception):
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def try_acquire_sync(
        self,
        server_id: str,
        *,
        holder: str,
        ttl_seconds: float | None = None,
    ) -> RepoLeaseToken | None:
        sid = validate_server_segment(server_id)
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        factory = self._get_sync_factory()
        dialect = self._sync_dialect(factory)
        params = {"sid": sid, "holder": holder, "ttl_seconds": ttl}

        with factory() as session:
            self._begin_immediate_sync(session, dialect)
            session.execute(text(self._insert_placeholder_sql(dialect)), {"sid": sid})
            try:
                result = session.execute(
                    text(self._acquire_update_sql(dialect, returning=True)), params
                )
                row = result.fetchone()
            except OperationalError as exc:
                if "returning" not in str(exc).lower():
                    raise
                result = session.execute(
                    text(self._acquire_update_sql(dialect, returning=False)), params
                )
                row = None
                if result.rowcount:
                    row = session.execute(
                        text(
                            "SELECT fencing_token, acquired_at, expires_at "
                            "FROM server_repo_leases WHERE server_id = :sid"
                        ),
                        {"sid": sid},
                    ).fetchone()
            session.commit()

        if row is None:
            return None
        fencing_token, acquired_at, expires_at = row
        return RepoLeaseToken(
            server_id=sid,
            holder=holder,
            fencing_token=int(fencing_token),
            acquired_at=_to_datetime(acquired_at),
            expires_at=_to_datetime(expires_at),
        )

    def _renew_sync(self, token: RepoLeaseToken, ttl_seconds: float) -> bool:
        factory = self._get_sync_factory()
        dialect = self._sync_dialect(factory)
        with factory() as session:
            result = session.execute(
                text(self._renew_sql(dialect)),
                {
                    "sid": token.server_id,
                    "token": token.fencing_token,
                    "holder": token.holder,
                    "ttl_seconds": ttl_seconds,
                },
            )
            session.commit()
        return (result.rowcount or 0) > 0

    def assert_fencing_token_sync(self, server_id: str, fencing_token: int) -> None:
        sid = validate_server_segment(server_id)
        factory = self._get_sync_factory()
        dialect = self._sync_dialect(factory)
        now = _db_now(dialect)
        with factory() as session:
            row = session.execute(
                text(
                    "SELECT holder, fencing_token, "
                    f"CASE WHEN expires_at > {now} THEN 1 ELSE 0 END "
                    "FROM server_repo_leases WHERE server_id = :sid"
                ),
                {"sid": sid},
            ).fetchone()
        actual = None if row is None else int(row[1])
        holder = None if row is None else row[0]
        alive = False if row is None else bool(row[2])
        if row is None or holder is None or actual != fencing_token or not alive:
            raise FencingTokenMismatchError(
                server_id=sid,
                expected_token=fencing_token,
                actual_token=actual,
            )

    def release_sync(self, token: RepoLeaseToken) -> bool:
        factory = self._get_sync_factory()
        dialect = self._sync_dialect(factory)
        now = _db_now(dialect)
        with factory() as session:
            result = session.execute(
                text(
                    "UPDATE server_repo_leases SET holder = NULL, acquired_at = NULL, "
                    f"expires_at = NULL, updated_at = {now} "
                    "WHERE server_id = :sid AND fencing_token = :token"
                ),
                {"sid": token.server_id, "token": token.fencing_token},
            )
            session.commit()
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Async primitives
    # ------------------------------------------------------------------

    @staticmethod
    async def _begin_immediate_async(session: AsyncSession, dialect: str) -> None:
        if dialect != "sqlite":
            return
        with contextlib.suppress(Exception):
            conn = await session.connection()
            await conn.exec_driver_sql("BEGIN IMMEDIATE")

    async def try_acquire(
        self,
        server_id: str,
        *,
        holder: str,
        ttl_seconds: float | None = None,
    ) -> RepoLeaseToken | None:
        sid = validate_server_segment(server_id)
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        factory = self._get_async_factory()
        dialect = self._async_dialect(factory)
        params = {"sid": sid, "holder": holder, "ttl_seconds": ttl}

        async with factory() as session:
            await self._begin_immediate_async(session, dialect)
            await session.execute(
                text(self._insert_placeholder_sql(dialect)), {"sid": sid}
            )
            try:
                result = await session.execute(
                    text(self._acquire_update_sql(dialect, returning=True)), params
                )
                row = result.fetchone()
            except OperationalError as exc:
                if "returning" not in str(exc).lower():
                    raise
                result = await session.execute(
                    text(self._acquire_update_sql(dialect, returning=False)), params
                )
                row = None
                if result.rowcount:
                    row = (
                        await session.execute(
                            text(
                                "SELECT fencing_token, acquired_at, expires_at "
                                "FROM server_repo_leases WHERE server_id = :sid"
                            ),
                            {"sid": sid},
                        )
                    ).fetchone()
            await session.commit()

        if row is None:
            return None
        fencing_token, acquired_at, expires_at = row
        return RepoLeaseToken(
            server_id=sid,
            holder=holder,
            fencing_token=int(fencing_token),
            acquired_at=_to_datetime(acquired_at),
            expires_at=_to_datetime(expires_at),
        )

    async def _renew(self, token: RepoLeaseToken, ttl_seconds: float) -> bool:
        factory = self._get_async_factory()
        dialect = self._async_dialect(factory)
        async with factory() as session:
            result = await session.execute(
                text(self._renew_sql(dialect)),
                {
                    "sid": token.server_id,
                    "token": token.fencing_token,
                    "holder": token.holder,
                    "ttl_seconds": ttl_seconds,
                },
            )
            await session.commit()
        return (result.rowcount or 0) > 0

    async def assert_fencing_token(self, server_id: str, fencing_token: int) -> None:
        sid = validate_server_segment(server_id)
        factory = self._get_async_factory()
        dialect = self._async_dialect(factory)
        now = _db_now(dialect)
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT holder, fencing_token, "
                        f"CASE WHEN expires_at > {now} THEN 1 ELSE 0 END "
                        "FROM server_repo_leases WHERE server_id = :sid"
                    ),
                    {"sid": sid},
                )
            ).fetchone()
        actual = None if row is None else int(row[1])
        holder = None if row is None else row[0]
        alive = False if row is None else bool(row[2])
        if row is None or holder is None or actual != fencing_token or not alive:
            raise FencingTokenMismatchError(
                server_id=sid,
                expected_token=fencing_token,
                actual_token=actual,
            )

    async def release(self, token: RepoLeaseToken) -> bool:
        factory = self._get_async_factory()
        dialect = self._async_dialect(factory)
        now = _db_now(dialect)
        async with factory() as session:
            result = await session.execute(
                text(
                    "UPDATE server_repo_leases SET holder = NULL, acquired_at = NULL, "
                    f"expires_at = NULL, updated_at = {now} "
                    "WHERE server_id = :sid AND fencing_token = :token"
                ),
                {"sid": token.server_id, "token": token.fencing_token},
            )
            await session.commit()
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Per-server kernel flock
    # ------------------------------------------------------------------

    def _lock_path(self, server_id: str) -> Path:
        if self._locks_dir is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("RepoLeaseManager has no locks_dir")
        return self._locks_dir / f"repo-{server_id}.lock"

    def _acquire_flock_sync(self, server_id: str, deadline: float) -> int | None:
        if self._locks_dir is None or fcntl is None:
            return None
        self._locks_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self._lock_path(server_id), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RepoLeaseTimeoutError(server_id) from None
                    time.sleep(_POLL_SECONDS)
        except BaseException:
            os.close(fd)
            raise

    async def _acquire_flock_async(self, server_id: str, deadline: float) -> int | None:
        if self._locks_dir is None or fcntl is None:
            return None
        self._locks_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self._lock_path(server_id), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RepoLeaseTimeoutError(server_id) from None
                    await asyncio.sleep(_POLL_SECONDS)
        except BaseException:
            os.close(fd)
            raise

    def _release_flock(self, fd: int | None) -> None:
        if fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Heartbeat (OS thread, independent of the event loop)
    # ------------------------------------------------------------------

    def _heartbeat_loop(
        self, token: RepoLeaseToken, ttl_seconds: float, stop: threading.Event
    ) -> None:
        while not stop.wait(self._heartbeat_interval_seconds):
            try:
                renewed = self._renew_sync(token, ttl_seconds)
            except Exception:
                logger.exception("Repo lease heartbeat failed for %s", token.server_id)
                continue
            if not renewed:
                logger.error(
                    "Repo lease lost for server %s at fencing token %d",
                    token.server_id,
                    token.fencing_token,
                )
                token.is_lost = True
                return

    # ------------------------------------------------------------------
    # Acquire (sync + async context managers)
    # ------------------------------------------------------------------

    def _wait_sync(
        self,
        server_id: str,
        holder: str,
        ttl_seconds: float,
        deadline: float,
    ) -> RepoLeaseToken:
        while True:
            token = self.try_acquire_sync(server_id, holder=holder, ttl_seconds=ttl_seconds)
            if token is not None:
                return token
            if time.monotonic() >= deadline:
                raise RepoLeaseTimeoutError(server_id)
            time.sleep(_POLL_SECONDS)

    async def _wait_async(
        self,
        server_id: str,
        holder: str,
        ttl_seconds: float,
        deadline: float,
    ) -> RepoLeaseToken:
        while True:
            token = await self.try_acquire(server_id, holder=holder, ttl_seconds=ttl_seconds)
            if token is not None:
                return token
            if time.monotonic() >= deadline:
                raise RepoLeaseTimeoutError(server_id)
            await asyncio.sleep(_POLL_SECONDS)

    @contextmanager
    def acquire_sync(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float | None = None,
        ttl_seconds: float | None = None,
    ) -> Iterator[RepoLeaseToken]:
        sid = validate_server_segment(server_id)
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        timeout = self._wait_timeout_seconds if wait_timeout is None else wait_timeout
        deadline = time.monotonic() + timeout
        fd = self._acquire_flock_sync(sid, deadline)
        try:
            token = self._wait_sync(sid, holder, ttl, deadline)
            _sync_held_servers().add(sid)
            stop = threading.Event()
            thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(token, ttl, stop),
                name=f"repo-lease-heartbeat-{sid}",
                daemon=True,
            )
            thread.start()
            try:
                yield token
            finally:
                stop.set()
                thread.join(timeout=_MAX_HEARTBEAT_JOIN_SECONDS)
                with contextlib.suppress(Exception):
                    self.release_sync(token)
                _sync_held_servers().discard(sid)
        finally:
            self._release_flock(fd)

    @asynccontextmanager
    async def acquire(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float | None = None,
        ttl_seconds: float | None = None,
    ) -> AsyncIterator[RepoLeaseToken]:
        sid = validate_server_segment(server_id)
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        timeout = self._wait_timeout_seconds if wait_timeout is None else wait_timeout
        deadline = time.monotonic() + timeout
        fd = await self._acquire_flock_async(sid, deadline)
        try:
            token = await self._wait_async(sid, holder, ttl, deadline)
            held = _HELD_REPO_LEASES.get() or frozenset()
            reset_token = _HELD_REPO_LEASES.set(held | {sid})
            stop = threading.Event()
            thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(token, ttl, stop),
                name=f"repo-lease-heartbeat-{sid}",
                daemon=True,
            )
            thread.start()
            try:
                yield token
            finally:
                stop.set()
                thread.join(timeout=_MAX_HEARTBEAT_JOIN_SECONDS)
                with contextlib.suppress(Exception):
                    await self.release(token)
                _HELD_REPO_LEASES.reset(reset_token)
        finally:
            self._release_flock(fd)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "HEARTBEAT_INTERVAL_SECONDS",
    "RepoLeaseManager",
    "RepoLeaseTimeoutError",
    "RepoLeaseToken",
    "assert_no_repo_lease_held",
    "repo_lease_held_in_context",
]
