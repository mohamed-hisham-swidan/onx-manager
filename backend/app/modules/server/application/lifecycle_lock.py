from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.command_bus import Command, CommandResult, Middleware

logger = logging.getLogger(__name__)

# Same-task reentrancy: maps server_id -> owner_token for the active async task
_held_leases: ContextVar[dict[str, str] | None] = ContextVar("_held_leases", default=None)


def _assert_repo_lock_order() -> None:
    """Global lock order is lifecycle -> repo; a held repo lease forbids this."""
    from app.modules.versioning.application.repo_lease import assert_no_repo_lease_held

    assert_no_repo_lease_held()


@dataclass
class LeaseToken:
    server_id: str
    owner_token: str
    holder: str
    reentrant: bool = False
    is_lost: bool = False


class ServerLifecycleLockTimeoutError(Exception):
    def __init__(self, server_id: str, holder: str | None = None) -> None:
        self.server_id = server_id
        self.holder = holder
        super().__init__(f"Timed out waiting for lifecycle lease on server {server_id}")


class ServerLifecycleLeaseManager:
    DEFAULT_TTL_SECONDS: float = 90.0
    DEFAULT_WAIT_TIMEOUT_SECONDS: float = 60.0
    HEARTBEAT_INTERVAL_SECONDS: float = 25.0
    MAX_RENEW_RETRIES: int = 3

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        from app.core.persistence.db import database

        return database.session_factory

    async def _ensure_table(self, session: AsyncSession) -> None:
        """Create server_lifecycle_leases table if missing (e.g. unmigrated test fixtures)."""
        ddl = text(
            "CREATE TABLE IF NOT EXISTS server_lifecycle_leases ("
            "server_id VARCHAR(36) PRIMARY KEY, "
            "holder VARCHAR(128), "
            "owner_token VARCHAR(64), "
            "acquired_at TIMESTAMP, "
            "expires_at TIMESTAMP, "
            "updated_at TIMESTAMP NOT NULL"
            ")"
        )
        try:
            await session.execute(ddl)
            await session.commit()
        except Exception as exc:
            logger.debug("Table check/creation error: %s", exc)
            await session.rollback()

    async def try_acquire(
        self,
        server_id: str,
        *,
        holder: str,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> LeaseToken | None:
        """Atomically acquire an unheld or expired lease row for `server_id`."""
        _assert_repo_lock_order()
        factory = self._get_session_factory()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        async with factory() as session:
            for attempt in range(2):
                try:
                    conn = await session.connection()
                    dialect_name = conn.dialect.name

                    if dialect_name == "sqlite":
                        with contextlib.suppress(Exception):
                            await conn.exec_driver_sql("BEGIN IMMEDIATE")
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO server_lifecycle_leases "
                                "(server_id, updated_at) VALUES (:sid, :now)"
                            ),
                            {"sid": server_id, "now": now},
                        )
                        res = await session.execute(
                            text(
                                "SELECT holder, owner_token, expires_at "
                                "FROM server_lifecycle_leases WHERE server_id = :sid"
                            ),
                            {"sid": server_id},
                        )
                    else:
                        await session.execute(
                            text(
                                "INSERT INTO server_lifecycle_leases (server_id, updated_at) "
                                "VALUES (:sid, :now) ON CONFLICT (server_id) DO NOTHING"
                            ),
                            {"sid": server_id, "now": now},
                        )
                        res = await session.execute(
                            text(
                                "SELECT holder, owner_token, expires_at "
                                "FROM server_lifecycle_leases WHERE server_id = :sid FOR UPDATE"
                            ),
                            {"sid": server_id},
                        )

                    row = res.fetchone()
                    if row is None:
                        current_holder, current_owner, current_expires = None, None, None
                    else:
                        current_holder, current_owner, current_expires = row

                    if current_expires is not None:
                        if isinstance(current_expires, str):
                            try:
                                current_expires = datetime.fromisoformat(current_expires)
                            except Exception:
                                current_expires = None
                        if current_expires is not None:
                            if current_expires.tzinfo is None:
                                current_expires = current_expires.replace(tzinfo=UTC)
                            else:
                                current_expires = current_expires.astimezone(UTC)

                    is_free = (
                        current_owner is None
                        or current_expires is None
                        or current_expires < now
                    )

                    if is_free:
                        token_val = uuid.uuid4().hex
                        await session.execute(
                            text(
                                "UPDATE server_lifecycle_leases "
                                "SET holder = :holder, owner_token = :token, "
                                "acquired_at = :now, expires_at = :exp, updated_at = :now "
                                "WHERE server_id = :sid"
                            ),
                            {
                                "holder": holder,
                                "token": token_val,
                                "now": now,
                                "exp": expires_at,
                                "sid": server_id,
                            },
                        )
                        await session.commit()
                        return LeaseToken(
                            server_id=server_id,
                            owner_token=token_val,
                            holder=holder,
                            reentrant=False,
                        )

                    await session.rollback()
                    return None

                except (OperationalError, DBAPIError) as exc:
                    await session.rollback()
                    if attempt == 0 and "no such table" in str(exc).lower():
                        await self._ensure_table(session)
                        continue
                    logger.debug("try_acquire DB error for %s: %s", server_id, exc)
                    return None
                except Exception as exc:
                    await session.rollback()
                    logger.debug("try_acquire unexpected error for %s: %s", server_id, exc)
                    return None
        return None

    async def _renew(self, token: LeaseToken, ttl_seconds: float) -> bool:
        """Renew expires_at on held lease."""
        factory = self._get_session_factory()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        async with factory() as session:
            try:
                res = await session.execute(
                    text(
                        "UPDATE server_lifecycle_leases "
                        "SET expires_at = :exp, updated_at = :now "
                        "WHERE server_id = :sid AND owner_token = :tok"
                    ),
                    {
                        "exp": expires_at,
                        "now": now,
                        "sid": token.server_id,
                        "tok": token.owner_token,
                    },
                )
                await session.commit()
                return (cast(CursorResult[Any], res).rowcount or 0) > 0
            except Exception as exc:
                await session.rollback()
                logger.debug("Lease renewal failed for %s: %s", token.server_id, exc)
                return False

    async def release(self, token: LeaseToken) -> bool:
        """Release lease row iff server_id and owner_token match."""
        if token.reentrant:
            return True
        factory = self._get_session_factory()
        now = datetime.now(UTC)
        async with factory() as session:
            try:
                res = await session.execute(
                    text(
                        "UPDATE server_lifecycle_leases "
                        "SET holder = NULL, owner_token = NULL, acquired_at = NULL, "
                        "expires_at = NULL, updated_at = :now "
                        "WHERE server_id = :sid AND owner_token = :tok"
                    ),
                    {"now": now, "sid": token.server_id, "tok": token.owner_token},
                )
                await session.commit()
                return (cast(CursorResult[Any], res).rowcount or 0) > 0
            except Exception as exc:
                await session.rollback()
                logger.debug("Lease release failed for %s: %s", token.server_id, exc)
                return False

    async def _heartbeat_loop(
        self, token: LeaseToken, ttl_seconds: float, interval_seconds: float
    ) -> None:
        while True:
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

            renewed = False
            for attempt in range(1 + self.MAX_RENEW_RETRIES):
                try:
                    renewed = await self._renew(token, ttl_seconds)
                    if renewed:
                        break
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    logger.debug(
                        "Lease renewal attempt %d failed for %s: %s",
                        attempt + 1,
                        token.server_id,
                        exc,
                    )

                if attempt < self.MAX_RENEW_RETRIES:
                    backoff = 0.05 * random.uniform(0.8, 1.2)
                    try:
                        await asyncio.sleep(backoff)
                    except asyncio.CancelledError:
                        return

            if not renewed:
                logger.error(
                    "Lease heartbeat renewal permanently failed for server %s; marking lease lost",
                    token.server_id,
                )
                token.is_lost = True
                break

    @asynccontextmanager
    async def acquire(
        self,
        server_id: str,
        *,
        holder: str,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> AsyncIterator[LeaseToken]:
        """Acquire per-server lease with jittered polling, ContextVar reentrancy, and renewal."""
        # 1. ContextVar reentrancy check. Re-entering lifecycle while already
        # holding it is legal even when a repo lease is also held; only a new
        # lifecycle acquisition must obey lifecycle -> repo ordering.
        current_held = _held_leases.get() or {}
        if server_id in current_held:
            token = LeaseToken(
                server_id=server_id,
                owner_token=current_held[server_id],
                holder=holder,
                reentrant=True,
            )
            # Renew in background
            await self._renew(token, ttl_seconds)
            yield token
            return

        _assert_repo_lock_order()
        # 2. Polling acquisition
        token: LeaseToken | None = None
        if wait_timeout <= 0:
            token = await self.try_acquire(server_id, holder=holder, ttl_seconds=ttl_seconds)
            if token is None:
                raise ServerLifecycleLockTimeoutError(server_id, holder)
        else:
            deadline = time.monotonic() + wait_timeout
            backoff = 0.1
            while True:
                token = await self.try_acquire(server_id, holder=holder, ttl_seconds=ttl_seconds)
                if token is not None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ServerLifecycleLockTimeoutError(server_id, holder)
                jittered = backoff * random.uniform(0.8, 1.2)
                sleep_time = min(jittered, remaining)
                await asyncio.sleep(sleep_time)
                backoff = min(backoff * 1.5, 0.5)

        # 3. Register held lease in ContextVar and spawn heartbeat
        new_held = dict(current_held)
        new_held[server_id] = token.owner_token
        reset_tok = _held_leases.set(new_held)

        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(token, ttl_seconds, self.HEARTBEAT_INTERVAL_SECONDS)
        )

        try:
            yield token
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            try:
                await asyncio.shield(self.release(token))
            finally:
                _held_leases.reset(reset_tok)


_global_lease_manager: ServerLifecycleLeaseManager | None = None


def get_lifecycle_lease_manager() -> ServerLifecycleLeaseManager:
    global _global_lease_manager
    if _global_lease_manager is None:
        _global_lease_manager = ServerLifecycleLeaseManager()
    return _global_lease_manager


def set_lifecycle_lease_manager(manager: ServerLifecycleLeaseManager | None) -> None:
    global _global_lease_manager
    _global_lease_manager = manager


class ServerLifecycleLockMiddleware(Middleware):
    LOCKED_COMMAND_NAMES = {
        "StartServerCommand",
        "StopServerCommand",
        "RestartServerCommand",
        "DeleteServerCommand",
        "RetryProvisioningCommand",
        "RefreshServerCommand",
        "RollbackRefreshCommand",
        "ConfirmUpgradeCommand",
        "ReleaseRefreshPinsCommand",
    }

    def __init__(self, manager: ServerLifecycleLeaseManager | None = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> ServerLifecycleLeaseManager:
        if self._manager is None:
            self._manager = get_lifecycle_lease_manager()
        return self._manager

    async def __call__(
        self,
        command: Command,
        next_middleware: Any,
    ) -> CommandResult:
        cmd_name = command.__class__.__name__
        server_id_attr = getattr(command, "server_id", None)
        if cmd_name in self.LOCKED_COMMAND_NAMES and server_id_attr:
            server_id = str(server_id_attr)
            holder = f"{cmd_name}:{os.getpid()}"
            try:
                async with self.manager.acquire(
                    server_id, holder=holder, wait_timeout=60.0
                ) as token:
                    result = await next_middleware(command)
                    if token.is_lost:
                        logger.error(
                            "Lifecycle lock for server %s was lost during %s execution",
                            server_id,
                            cmd_name,
                        )
                        return CommandResult(
                            success=False,
                            error="Lifecycle lock was lost during operation execution",
                            error_code="OPERATION_CONCURRENCY_CONFLICT",
                        )
                    return result
            except ServerLifecycleLockTimeoutError:
                logger.warning(
                    "Timed out waiting for lifecycle lock on server %s for %s",
                    server_id,
                    cmd_name,
                )
                return CommandResult(
                    success=False,
                    error="Another lifecycle operation is already in progress for this server",
                    error_code="OPERATION_CONCURRENCY_CONFLICT",
                )
        return await next_middleware(command)
