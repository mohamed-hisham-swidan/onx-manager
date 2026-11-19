"""Async SQLAlchemy persistence for P5 GitHub connections and webhook deliveries.

The repository owns no transaction policy: callers decide whether to commit or
flush. :meth:`SQLGitHubSyncRepository.create_webhook_delivery` is the one
exception — it wraps the insert in a savepoint so a concurrent duplicate
``(server_id, delivery_id)`` insert cannot poison the caller's outer
transaction. It never stores, logs, or returns plaintext secrets; encrypted
columns are opaque ciphertext produced by :mod:`github_vault`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerGitHubConnectionModel,
)

_UTC = UTC


class SQLGitHubSyncRepository:
    """Persistence gateway for GitHub connection and webhook delivery rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    async def get_connection(
        self, server_id: str
    ) -> ServerGitHubConnectionModel | None:
        stmt = select(ServerGitHubConnectionModel).where(
            ServerGitHubConnectionModel.server_id == server_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_connection(
        self, conn: ServerGitHubConnectionModel
    ) -> ServerGitHubConnectionModel:
        now = datetime.now(_UTC)
        conn.updated_at = now
        if getattr(conn, "created_at", None) is None:
            conn.created_at = now
        self._session.add(conn)
        await self._session.flush()
        return conn

    async def delete_connection(self, server_id: str) -> bool:
        conn = await self.get_connection(server_id)
        if conn is None:
            return False
        await self._session.delete(conn)
        await self._session.flush()
        return True

    # ------------------------------------------------------------------
    # Webhook deliveries
    # ------------------------------------------------------------------

    async def get_webhook_delivery(
        self, server_id: str, delivery_id: str
    ) -> GitHubWebhookDeliveryModel | None:
        stmt = select(GitHubWebhookDeliveryModel).where(
            GitHubWebhookDeliveryModel.server_id == server_id,
            GitHubWebhookDeliveryModel.delivery_id == delivery_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_webhook_delivery_by_ref(
        self, server_id: str, delivery_id_or_row_id: str
    ) -> GitHubWebhookDeliveryModel | None:
        """Resolve an operator-supplied delivery ref scoped to one server.

        The GitHub ``X-GitHub-Delivery`` header is tried first; the primary-key
        UUID is the fallback so operator redelivery accepts either identifier.
        Both lookups include ``server_id`` so a row from another server can
        never be read or redelivered through this endpoint.
        """
        delivery = await self.get_webhook_delivery(server_id, delivery_id_or_row_id)
        if delivery is not None:
            return delivery

        if not isinstance(delivery_id_or_row_id, str) or not delivery_id_or_row_id:
            return None
        stmt = select(GitHubWebhookDeliveryModel).where(
            GitHubWebhookDeliveryModel.server_id == server_id,
            GitHubWebhookDeliveryModel.id == delivery_id_or_row_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_webhook_deliveries(
        self, server_id: str, *, limit: int = 50
    ) -> list[GitHubWebhookDeliveryModel]:
        try:
            effective_limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            effective_limit = 50
        stmt = (
            select(GitHubWebhookDeliveryModel)
            .where(GitHubWebhookDeliveryModel.server_id == server_id)
            .order_by(
                desc(GitHubWebhookDeliveryModel.received_at),
                desc(GitHubWebhookDeliveryModel.id),
            )
            .limit(effective_limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_webhook_delivery(
        self, delivery: GitHubWebhookDeliveryModel
    ) -> tuple[GitHubWebhookDeliveryModel, bool]:
        """Insert one delivery atomically and report whether it was new.

        The insert runs inside a SAVEPOINT. A duplicate unique key raises
        :class:`IntegrityError`, the savepoint rolls back on its own, and the
        caller's outer transaction stays usable. The existing row is then
        re-read and returned with ``created=False``.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(delivery)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_webhook_delivery(
                delivery.server_id, delivery.delivery_id
            )
            if existing is None:
                raise
            return existing, False
        return delivery, True

    async def save_webhook_delivery(
        self, delivery: GitHubWebhookDeliveryModel
    ) -> GitHubWebhookDeliveryModel:
        self._session.add(delivery)
        await self._session.flush()
        return delivery

    async def delete_webhook_deliveries(self, server_id: str) -> int:
        stmt = delete(GitHubWebhookDeliveryModel).where(
            GitHubWebhookDeliveryModel.server_id == server_id
        )
        result = await self._session.execute(stmt)
        return getattr(result, "rowcount", 0) or 0


__all__ = ["SQLGitHubSyncRepository"]
