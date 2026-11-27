from __future__ import annotations

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.application.access_policy import build_user_profile_dict


class GetCurrentUserQuery(Query):
    user_id: str


class GetCurrentUserHandler(QueryHandler[GetCurrentUserQuery]):
    async def handle(self, query: GetCurrentUserQuery) -> dict | None:
        async with database.session_factory() as session:
            return await build_user_profile_dict(session, query.user_id)
