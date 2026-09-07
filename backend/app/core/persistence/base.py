from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Column, DateTime, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdentifiedMixin:
    id = Column(String(36), primary_key=True)


T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self._session = session
        self._model = model

    async def add(self, entity: T) -> T:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get(self, id: str) -> T | None:
        return await self._session.get(self._model, id)

    async def list(self, **filters: Any) -> list[T]:
        stmt = select(self._model)
        for key, value in filters.items():
            column = getattr(self._model, key, None)
            if column is not None:
                stmt = stmt.where(column == value)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, entity: T) -> T:
        merged = await self._session.merge(entity)
        await self._session.flush()
        return merged

    async def delete(self, entity: T) -> None:
        await self._session.delete(entity)
        await self._session.flush()
