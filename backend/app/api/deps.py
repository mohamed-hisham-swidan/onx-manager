from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_utils import resolve_bearer_token
from app.core.command_bus import CommandBus
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.core.persistence.db import get_db

_command_bus: CommandBus | None = None
_query_bus: QueryBus | None = None
_event_bus: EventBus | None = None


def init_buses(command_bus: CommandBus, query_bus: QueryBus, event_bus: EventBus) -> None:
    global _command_bus, _query_bus, _event_bus
    _command_bus = command_bus
    _query_bus = query_bus
    _event_bus = event_bus


async def get_command_bus() -> CommandBus:
    if _command_bus is None:
        raise RuntimeError("CommandBus not initialized")
    return _command_bus


async def get_query_bus() -> QueryBus:
    if _query_bus is None:
        raise RuntimeError("QueryBus not initialized")
    return _query_bus


async def get_event_bus() -> EventBus:
    if _event_bus is None:
        raise RuntimeError("EventBus not initialized")
    return _event_bus


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(default=""),
) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    try:
        return await resolve_bearer_token(token, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


async def get_settings() -> AppSettings:
    return ConfigFactory.global_settings()
