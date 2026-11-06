from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.auth.application.commands.update_user import (
    UpdateUserCommand,
    UpdateUserHandler,
)
from app.modules.auth.domain.aggregate import Role, User
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, Permission, RoleId, UserId


@pytest.fixture
async def db_session_factory(tmp_path):
    db_file = tmp_path / "test_auth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    database._engine = engine
    database._session_factory = session_factory
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_user_handler_activates_user(db_session_factory, event_bus: EventBus) -> None:
    user_id = UserId("user-act-1")
    async with db_session_factory() as session:
        repo = SQLUserRepository(session)
        user = User.create(
            user_id=user_id,
            email=EmailAddress("active@example.com"),
            password_hash="hash123",
            display_name="Test User",
        )
        user.deactivate()
        await repo.save(user)
        await session.commit()

    handler = UpdateUserHandler(event_bus)
    result = await handler.handle(
        UpdateUserCommand(user_id=str(user_id), is_active=True)
    )
    assert result.success is True
    assert result.data["is_active"] is True

    async with db_session_factory() as session:
        repo = SQLUserRepository(session)
        saved_user = await repo.get(user_id)
        assert saved_user.is_active is True


@pytest.mark.asyncio
async def test_sql_user_repository_persists_role_removals(db_session_factory) -> None:
    role1 = Role(RoleId("role-1"), name="Admin", permissions=[Permission.parse("system:*")])
    role2 = Role(RoleId("role-2"), name="Viewer", permissions=[Permission.parse("system:view")])
    user_id = UserId("user-roles-1")

    async with db_session_factory() as session:
        repo = SQLUserRepository(session)
        await repo.save_role(role1)
        await repo.save_role(role2)
        user = User.create(
            user_id=user_id,
            email=EmailAddress("roles@example.com"),
            password_hash="hash123",
            display_name="Roles User",
        )
        user.add_role(role1)
        user.add_role(role2)
        await repo.save(user)
        await session.commit()

    async with db_session_factory() as session:
        repo = SQLUserRepository(session)
        loaded = await repo.get(user_id)
        assert {r.name for r in loaded.roles} == {"Admin", "Viewer"}

        loaded.remove_role(role1)
        assert len(loaded.roles) == 1
        await repo.save(loaded)
        await session.commit()

    async with db_session_factory() as session:
        repo = SQLUserRepository(session)
        reloaded = await repo.get(user_id)
        assert [r.name for r in reloaded.roles] == ["Viewer"]
