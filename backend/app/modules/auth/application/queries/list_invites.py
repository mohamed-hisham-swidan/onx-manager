from __future__ import annotations

from app.core.persistence.unit_of_work import UnitOfWork
from app.core.query_bus import Query, QueryHandler
from app.core.timeutil import format_datetime_utc
from app.modules.auth.infrastructure.repository import SQLInvitationRepository


class ListInvitesQuery(Query):
    pass


class ListInvitesHandler(QueryHandler[ListInvitesQuery]):
    async def handle(self, query: ListInvitesQuery) -> list[dict]:
        async with UnitOfWork() as uow:
            repo = SQLInvitationRepository(uow.session)
            invites = await repo.list()

            return [
                {
                    "invite_id": inv.invitation_id,
                    "token_prefix": inv.token_prefix,
                    "creator_id": inv.creator_id,
                    "email": inv.email,
                    "global_role": inv.global_role,
                    "server_id": inv.server_id,
                    "server_role": inv.server_role,
                    "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                    "max_uses": inv.max_uses,
                    "use_count": inv.use_count,
                    "expires_at": format_datetime_utc(inv.expires_at) if inv.expires_at else None,
                    "used_at": format_datetime_utc(inv.used_at) if inv.used_at else None,
                    "created_at": format_datetime_utc(inv.created_at) if inv.created_at else None,
                }
                for inv in invites
            ]
