"""Shared test builders and database seeding helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.core.security import hash_api_key
from app.main import create_app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.auth.infrastructure.models import (
    ApiKeyModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from app.modules.server.infrastructure.models import ServerModel
from app.registration import register_handlers
from app.websocket import endpoint as ws_endpoint


def build_test_app() -> tuple[FastAPI, CommandBus, QueryBus, EventBus]:
    """Create a FastAPI app wired to fresh buses against the active isolated test DB."""
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI):
        yield

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    deps.init_buses(command_bus, query_bus, event_bus)
    ws_endpoint.init_websocket(event_bus)

    async def _get_cb() -> CommandBus:
        return command_bus

    async def _get_qb() -> QueryBus:
        return query_bus

    async def _get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = _get_cb
    app.dependency_overrides[deps.get_query_bus] = _get_qb
    app.dependency_overrides[deps.get_event_bus] = _get_eb
    return app, command_bus, query_bus, event_bus


async def build_file_backed_app(tmp_path: Path, db_name: str = "test.db") -> tuple[FastAPI, Any]:
    """Create a FastAPI app backed by a temporary file SQLite DB (for Alembic/concurrency tests)."""
    db_file = tmp_path / db_name
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    app, _, _, _ = build_test_app()
    return app, engine


async def seed_user(
    user_id: str,
    username: str,
    role: str = "owner",
    *,
    password_hash: str = "hashed-pw",
    is_active: bool = True,
    denied_permissions: list[str] | None = None,
) -> None:
    """Seed a user + role binding into the active test database."""
    assert database._session_factory is not None
    now = datetime.now(UTC)
    async with database._session_factory() as session:
        existing_role = await session.get(RoleModel, role)
        if existing_role is None:
            session.add(RoleModel(id=role, name=role, description=f"{role} role"))
        session.add(
            UserModel(
                id=user_id,
                username=username,
                email=f"{username}@test.local",
                password_hash=password_hash,
                is_active=is_active,
                denied_permissions=denied_permissions or [],
                created_at=now,
                updated_at=now,
            )
        )
        session.add(UserRoleModel(user_id=user_id, role_id=role))
        await session.commit()


async def seed_api_key(
    key_id: str,
    user_id: str,
    raw_key: str,
    *,
    name: str = "test-key",
    permissions: list[str] | None = None,
    is_active: bool = True,
) -> dict[str, str]:
    """Seed an API key and return its X-API-Key header dict."""
    assert database._session_factory is not None
    now = datetime.now(UTC)
    async with database._session_factory() as session:
        session.add(
            ApiKeyModel(
                id=key_id,
                user_id=user_id,
                name=name,
                key_prefix=raw_key[:12],
                key_hash=hash_api_key(raw_key),
                permissions=permissions if permissions is not None else ["*"],
                is_active=is_active,
                created_at=now,
            )
        )
        await session.commit()
    return {"X-API-Key": raw_key}


def bearer_header(user_id: str, username: str, role: str = "owner") -> dict[str, str]:
    """Return an Authorization Bearer header for a seeded user."""
    token = create_access_token(user_id=user_id, username=username, role=role)
    return {"Authorization": f"Bearer {token}"}


async def seed_server(
    server_id: str,
    name: str,
    root_dir: Path,
    *,
    port: int = 25565,
    mode: str = "simple",
    server_type: str = "paper",
    minecraft_version: str = "1.21.1",
    status: str = "STOPPED",
    location_type: str = "local",
) -> ServerModel:
    """Seed a ServerModel row and ensure its root directory exists."""
    root_dir.mkdir(parents=True, exist_ok=True)
    assert database._session_factory is not None
    now = datetime.now(UTC)
    srv = ServerModel(
        id=server_id,
        name=name,
        server_type=server_type,
        minecraft_version=minecraft_version,
        port=port,
        root_path=str(root_dir),
        mode=mode,
        status=status,
        location_type=location_type,
        created_at=now,
        updated_at=now,
    )
    async with database._session_factory() as session:
        session.add(srv)
        await session.commit()
    return srv
