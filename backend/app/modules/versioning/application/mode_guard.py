from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    GuardConfigurationError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ServerNotFoundError,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import ServerMode
from app.modules.server.infrastructure.models import ServerModel
from app.modules.shared.value_objects import ServerId

if TYPE_CHECKING:
    from app.modules.server.domain.repository import ServerRepository


async def ensure_versioning_allowed(
    server_or_id: Server | str | ServerId,
    *,
    session: AsyncSession | None = None,
    server_repo: ServerRepository | None = None,
) -> None:
    """Ensure that versioning operations are permitted for the given server.

    Requires exactly one mode source:
    - Server aggregate passed as server_or_id (with session and server_repo omitted)
    - server_repo passed as keyword argument
    - session passed as keyword argument

    Raises GuardConfigurationError (HTTP 500) if no source (or more than one) is provided,
    or if mode is missing.
    Raises NotFoundError (HTTP 404) if the server does not exist.
    Raises ServerModeVersioningDisabledError (HTTP 409) if the server is in SIMPLE mode.
    """
    is_server_obj = isinstance(server_or_id, Server)
    sources = sum([
        1 if is_server_obj else 0,
        1 if server_repo is not None else 0,
        1 if session is not None else 0,
    ])
    if sources != 1:
        raise GuardConfigurationError("Mode guard requires exactly one mode source")

    if is_server_obj:
        assert isinstance(server_or_id, Server)
        mode = getattr(server_or_id, "mode", None)
        if mode is None:
            raise GuardConfigurationError("Server aggregate is missing mode")
        if (
            mode is ServerMode.SIMPLE
            or mode == "simple"
            or (hasattr(mode, "value") and mode.value == "simple")
        ):
            raise ServerModeVersioningDisabledError(
                f"Versioning operations are disabled for server '{server_or_id.id}' in simple mode"
            )
        return

    sid = str(server_or_id)

    if server_repo is not None:
        try:
            server = await server_repo.get(ServerId(sid))
        except ServerNotFoundError:
            raise NotFoundError(f"Server '{sid}' not found") from None

        if server is None:
            raise NotFoundError(f"Server '{sid}' not found")

        mode = getattr(server, "mode", None)
        if mode is None:
            raise GuardConfigurationError(f"Server '{sid}' is missing mode")
        if (
            mode is ServerMode.SIMPLE
            or mode == "simple"
            or (hasattr(mode, "value") and mode.value == "simple")
        ):
            raise ServerModeVersioningDisabledError(
                f"Versioning operations are disabled for server '{sid}' in simple mode"
            )
        return

    if session is not None:
        result = await session.execute(select(ServerModel.mode).where(ServerModel.id == sid))
        row = result.first()
        if row is None:
            raise NotFoundError(f"Server '{sid}' not found")
        mode = row[0]
        if mode is None:
            raise GuardConfigurationError(f"Server '{sid}' is missing mode")
        if (
            mode is ServerMode.SIMPLE
            or mode == "simple"
            or (hasattr(mode, "value") and mode.value == "simple")
        ):
            raise ServerModeVersioningDisabledError(
                f"Versioning operations are disabled for server '{sid}' in simple mode"
            )
        return
