from __future__ import annotations

from app.core.query_bus import Query, QueryHandler


class GetBotSettingsQuery(Query):
    server_id: str


class GetBotSettingsHandler(QueryHandler[GetBotSettingsQuery]):
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def handle(self, query: GetBotSettingsQuery) -> dict:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.models import ServerModel
        from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel

        async with database.session_factory() as session:
            server = await session.get(ServerModel, query.server_id)
            if server is None:
                from app.core.exceptions import NotFoundError

                raise NotFoundError(f"Server '{query.server_id}' not found")
            stored = server.bot_verification_settings or {}
            lease = await session.get(ServerRepoLeaseModel, query.server_id)
            retention = (
                lease.previous_tree_retention
                if lease is not None
                else stored.get("previous_tree_retention", "until_health_gate")
            )
            return {
                "server_id": query.server_id,
                "bot_count": stored.get("bot_count"),
                "duration_minutes": stored.get("duration_minutes"),
                "bot_tech": stored.get("bot_tech"),
                "placement_mode": stored.get("placement_mode"),
                "previous_tree_retention": retention,
            }
