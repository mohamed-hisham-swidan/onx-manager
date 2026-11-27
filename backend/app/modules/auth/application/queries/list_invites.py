from __future__ import annotations

from app.core.persistence.unit_of_work import UnitOfWork
from app.core.query_bus import Query, QueryHandler
from app.core.timeutil import format_datetime_utc
from app.modules.auth.application.access_policy import resolve_invite_policy
from app.modules.auth.infrastructure.repository import SQLInvitationRepository


class ListInvitesQuery(Query):
    pass


class ListInvitesHandler(QueryHandler[ListInvitesQuery]):
    async def handle(self, query: ListInvitesQuery) -> list[dict]:
        async with UnitOfWork() as uow:
            repo = SQLInvitationRepository(uow.session)
            invites = await repo.list()

            items: list[dict] = []
            for inv in invites:
                role, server_ids, all_servers, denied = resolve_invite_policy(
                    global_role=inv.global_role,
                    server_role=inv.server_role,
                    server_id=inv.server_id,
                    server_ids=inv.server_ids,
                    all_servers_access=inv.all_servers_access,
                    denied_permissions=inv.denied_permissions,
                )
                items.append(
                    {
                        "invite_id": inv.invitation_id,
                        "token_prefix": inv.token_prefix,
                        "creator_id": inv.creator_id or "",
                        "email": inv.email,
                        "role": role,
                        "global_role": inv.global_role,
                        "server_id": inv.server_id,
                        "server_ids": server_ids,
                        "server_role": inv.server_role,
                        "all_servers_access": all_servers,
                        "denied_permissions": denied,
                        "status": (
                            inv.status.value
                            if hasattr(inv.status, "value")
                            else str(inv.status)
                        ),
                        "max_uses": inv.max_uses,
                        "use_count": inv.use_count,
                        "expires_at": (
                            format_datetime_utc(inv.expires_at) if inv.expires_at else None
                        ),
                        "used_at": format_datetime_utc(inv.used_at) if inv.used_at else None,
                        "created_at": (
                            format_datetime_utc(inv.created_at) if inv.created_at else None
                        ),
                    }
                )
            return items
