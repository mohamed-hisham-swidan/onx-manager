from __future__ import annotations

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import UserId


class GetCurrentUserQuery(Query):
    user_id: str


class GetCurrentUserHandler(QueryHandler[GetCurrentUserQuery]):
    async def handle(self, query: GetCurrentUserQuery) -> dict | None:
        async with database.session_factory() as session:
            repo = SQLUserRepository(session)
            user = await repo.get(UserId(query.user_id))
            if user is None:
                return None
            return {
                "user_id": str(user.user_id),
                "username": user.username,
                "email": str(user.email) if user.email is not None else None,
                "display_name": user.display_name,
                "is_active": user.is_active,
                "roles": [r.name for r in user.roles],
                "created_at": user.created_at,
                "last_login_at": user.last_login_at,
            }
