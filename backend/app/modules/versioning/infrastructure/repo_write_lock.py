"""Single per-repository write lock with monotonic fencing (P5-1, D-J).

``RepoWriteLock`` composes :class:`RepoLeaseManager` rather than duplicating its
database/fencing/heartbeat logic. One lease covers every repository write
operation (``add``/``commit``/``merge``/``fetch``/``push``/``gc``/``worktree``
and higher-level sync/refresh/rollback flows).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import FencingTokenMismatchError, ValidationError
from app.core.host_state import HostStateLayout
from app.modules.versioning.application.repo_lease import (
    DEFAULT_TTL_SECONDS,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    RepoLeaseManager,
    RepoLeaseTimeoutError,
    RepoLeaseToken,
)

REPO_WRITE_OPERATIONS: frozenset[str] = frozenset(
    {
        "add",
        "commit",
        "merge",
        "fetch",
        "push",
        "gc",
        "worktree",
        "sync",
        "refresh",
        "rollback",
    }
)


@dataclass
class RepoWriteLease:
    """One held repository write lease and its fencing verifier."""

    token: RepoLeaseToken
    operation: str
    _manager: RepoLeaseManager

    @property
    def server_id(self) -> str:
        return self.token.server_id

    @property
    def holder(self) -> str:
        return self.token.holder

    @property
    def fencing_token(self) -> int:
        return self.token.fencing_token

    @property
    def acquired_at(self):
        return self.token.acquired_at

    @property
    def expires_at(self):
        return self.token.expires_at

    @property
    def is_lost(self) -> bool:
        return self.token.is_lost

    def assert_valid_sync(self) -> None:
        """Fail closed if this lease was lost or fenced out by a new holder."""
        if self.token.is_lost:
            raise FencingTokenMismatchError(
                server_id=self.server_id,
                expected_token=self.fencing_token,
            )
        self._manager.assert_fencing_token_sync(
            self.server_id, self.fencing_token
        )

    async def assert_valid(self) -> None:
        """Async counterpart of :meth:`assert_valid_sync`."""
        if self.token.is_lost:
            raise FencingTokenMismatchError(
                server_id=self.server_id,
                expected_token=self.fencing_token,
            )
        await self._manager.assert_fencing_token(
            self.server_id, self.fencing_token
        )

    def fencing_verifier(self) -> Callable[[], None]:
        """Return a zero-argument callable suitable for write callbacks."""
        return self.assert_valid_sync


class RepoWriteLock:
    """Serialize all writes for one repository behind a fenced DB lease."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
        layout: HostStateLayout | None = None,
        locks_dir: Path | str | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        resolved_locks_dir = (
            locks_dir
            if locks_dir is not None
            else (layout.locks if layout is not None else None)
        )
        self._manager = RepoLeaseManager(
            sync_session_factory=sync_session_factory,
            session_factory=session_factory,
            locks_dir=resolved_locks_dir,
            ttl_seconds=ttl_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    @staticmethod
    def _validate_operation(operation: str) -> str:
        if not isinstance(operation, str) or operation not in REPO_WRITE_OPERATIONS:
            raise ValidationError(
                "Unsupported repository write operation",
                field="operation",
                details={"operation": str(operation)[:64]},
            )
        return operation

    def _holder(self, operation: str, holder_id: str | None) -> str:
        suffix = holder_id or uuid.uuid4().hex[:12]
        return f"{operation}:{suffix}"[:128]

    @asynccontextmanager
    async def acquire(
        self,
        server_id: str,
        *,
        operation: str,
        holder_id: str | None = None,
        wait_timeout: float | None = None,
        ttl_seconds: float | None = None,
        fail_fast: bool = False,
    ) -> AsyncIterator[RepoWriteLease]:
        """Acquire the repository write lease for one async operation."""
        resolved_operation = self._validate_operation(operation)
        holder = self._holder(resolved_operation, holder_id)
        effective_wait = 0.0 if fail_fast else wait_timeout

        async with self._manager.acquire(
            server_id,
            holder=holder,
            wait_timeout=effective_wait,
            ttl_seconds=ttl_seconds,
        ) as token:
            yield RepoWriteLease(
                token=token,
                operation=resolved_operation,
                _manager=self._manager,
            )

    @contextmanager
    def acquire_sync(
        self,
        server_id: str,
        *,
        operation: str,
        holder_id: str | None = None,
        wait_timeout: float | None = None,
        ttl_seconds: float | None = None,
        fail_fast: bool = False,
    ) -> Iterator[RepoWriteLease]:
        """Synchronous counterpart of :meth:`acquire`."""
        resolved_operation = self._validate_operation(operation)
        holder = self._holder(resolved_operation, holder_id)
        effective_wait = 0.0 if fail_fast else wait_timeout

        with self._manager.acquire_sync(
            server_id,
            holder=holder,
            wait_timeout=effective_wait,
            ttl_seconds=ttl_seconds,
        ) as token:
            yield RepoWriteLease(
                token=token,
                operation=resolved_operation,
                _manager=self._manager,
            )

    async def assert_fencing_token(
        self, server_id: str, fencing_token: int
    ) -> None:
        await self._manager.assert_fencing_token(server_id, fencing_token)

    def assert_fencing_token_sync(
        self, server_id: str, fencing_token: int
    ) -> None:
        self._manager.assert_fencing_token_sync(server_id, fencing_token)

    def close(self) -> None:
        """Dispose the manager's derived engine, if it created one."""
        engine = getattr(self._manager, "_owned_engine", None)
        if engine is not None:
            engine.dispose()


__all__ = [
    "REPO_WRITE_OPERATIONS",
    "RepoLeaseTimeoutError",
    "RepoWriteLease",
    "RepoWriteLock",
]
