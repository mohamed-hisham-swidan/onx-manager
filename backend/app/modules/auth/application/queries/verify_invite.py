from __future__ import annotations

import hashlib

from app.core.persistence.unit_of_work import UnitOfWork
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.infrastructure.repository import SQLInvitationRepository


class VerifyInviteQuery(Query):
    token: str


class VerifyInviteHandler(QueryHandler[VerifyInviteQuery]):
    async def handle(self, query: VerifyInviteQuery) -> dict:
        token_hash = hashlib.sha256(query.token.encode("utf-8")).hexdigest()
        async with UnitOfWork() as uow:
            repo = SQLInvitationRepository(uow.session)
            invitation = await repo.get_by_token_hash(token_hash)

            if invitation is None:
                return {"valid": False, "email": None, "expires_at": None}

            return {
                "valid": invitation.is_valid,
                "email": invitation.email,
                "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
            }
