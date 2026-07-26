from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import AppSettings


class DatabaseEngine:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._session_factory

    def init(self, settings: AppSettings | None = None) -> None:
        if settings:
            self._settings = settings

        kw: dict[str, Any] = {
            "echo": self._settings.database_echo,
        }
        if "sqlite" not in self._settings.database_url:
            kw["pool_size"] = 20
            kw["max_overflow"] = 10
            kw["pool_pre_ping"] = True

        self._engine = create_async_engine(self._settings.database_url, **kw)

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized")
        async with self._session_factory() as session:
            yield session


database = DatabaseEngine()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in database.get_session():
        yield session
