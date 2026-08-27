from __future__ import annotations

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.infrastructure.repository import SQLUserRepository


class ListUsersQuery(Query):
    pass


class ListUsersHandler(QueryHandler[ListUsersQuery]):
    async def handle(self, query: ListUsersQuery) -> list[dict]:
        async with database.session_factory() as session:
            repo = SQLUserRepository(session)
            users = await repo.list()
            return [
                {
                    "user_id": str(u.user_id),
                    "email": str(u.email),
                    "display_name": u.display_name,
                    "is_active": u.is_active,
                    "roles": [r.name for r in u.roles],
                    "created_at": u.created_at,
                    "last_login_at": u.last_login_at,
                }
                for u in users
            ]
