from __future__ import annotations

import os

from sqlalchemy import select

from app.core.exceptions import NotFoundError, ServerModeVersioningDisabledError
from app.core.persistence.db import database
from app.modules.server.domain.value_objects import ServerMode
from app.modules.server.infrastructure.models import ServerModel


async def require_advanced_mode(server_id: str) -> None:
    async with database.session_factory() as session:
        result = await session.execute(
            select(ServerModel.mode).where(ServerModel.id == server_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError(f"Server '{server_id}' not found")
        mode = row[0]

    if mode == ServerMode.SIMPLE.value or mode == "simple":
        raise ServerModeVersioningDisabledError(
            f"Versioning operations are disabled for server '{server_id}' in simple mode"
        )

    if os.name != "posix":
        raise ServerModeVersioningDisabledError(
            "Versioning operations are disabled on non-POSIX hosts in this release"
        )
