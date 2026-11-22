from __future__ import annotations

from app.core.local_auth import (
    ensure_local_admin_provisioned,
    is_local_profile_and_loopback_bound,
)
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.query_bus import Query, QueryHandler
from app.core.version import get_app_version
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository, SQLUserRepository


class GetSystemStatusQuery(Query):
    pass


class GetSystemStatusHandler(QueryHandler[GetSystemStatusQuery]):
    async def handle(self, query: GetSystemStatusQuery) -> dict:
        async with UnitOfWork() as uow:
            if is_local_profile_and_loopback_bound():
                provisioned = await ensure_local_admin_provisioned(uow.session)
                if provisioned:
                    await uow.commit()

            sys_repo = SQLSystemStateRepository(uow.session)
            user_repo = SQLUserRepository(uow.session)

            state = await sys_repo.get("default")
            user_count = await user_repo.count_users()

            return {
                "initialized": state.initialized,
                "access_mode": state.access_mode.value
                if hasattr(state.access_mode, "value")
                else str(state.access_mode),
                "user_count": user_count,
                "version": get_app_version(),
                "password_configured": state.password_configured,
            }
