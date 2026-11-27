from __future__ import annotations

from sqlalchemy import select

from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.auth.application.access_policy import build_user_profile_dict
from app.modules.auth.infrastructure.models import UserModel


class ListUsersQuery(Query):
    pass


class ListUsersHandler(QueryHandler[ListUsersQuery]):
    async def handle(self, query: ListUsersQuery) -> list[dict]:
        async with database.session_factory() as session:
            ids = (
                await session.execute(select(UserModel.id).order_by(UserModel.created_at.asc()))
            ).scalars().all()
            out: list[dict] = []
            for uid in ids:
                profile = await build_user_profile_dict(session, str(uid))
                if profile is not None:
                    out.append(profile)
            return out
