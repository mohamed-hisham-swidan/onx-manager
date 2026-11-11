from __future__ import annotations

import pytest

from app.core.persistence.db import database
from app.modules.server.application.read_models import ServerDetailReadModel, ServerReadModel
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _server_mode():
    from app.modules.server.domain import value_objects

    return value_objects.ServerMode


def _build_server(mode=None) -> Server:
    kwargs = {
        "server_id": ServerId(),
        "name": "persisted-mode",
        "server_type": ServerType.VANILLA,
        "minecraft_version": MinecraftVersion.parse("1.20.4"),
        "memory": MemoryAllocation(min_mb=1024, max_mb=2048),
        "java_args": JavaArguments(None),
        "properties": ServerProperties(port=PortNumber(25565)),
    }
    if mode is not None:
        kwargs["mode"] = mode
    return Server.create(**kwargs)


class TestServerModeColumn:
    def test_mode_column_is_non_null_with_simple_default(self) -> None:
        column = ServerModel.__table__.c.mode
        assert column.nullable is False
        default = column.default.arg if column.default is not None else None
        assert default == "simple"


class TestServerModeRoundTrip:
    @pytest.mark.asyncio
    async def test_default_mode_round_trips_as_simple(self) -> None:
        server = _build_server()
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        async with database.session_factory() as session:
            loaded = await SQLServerRepository(session).get(server.id)

        assert loaded.mode is _server_mode().SIMPLE

    @pytest.mark.asyncio
    async def test_explicit_advanced_mode_round_trips(self) -> None:
        server = _build_server(mode=_server_mode().ADVANCED)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        async with database.session_factory() as session:
            loaded = await SQLServerRepository(session).get(server.id)

        assert loaded.mode is _server_mode().ADVANCED


class TestServerModeReadModels:
    def test_read_model_exposes_mode_string(self) -> None:
        model = ServerReadModel.from_domain(_build_server(mode=_server_mode().ADVANCED))
        assert model.mode == "advanced"

    def test_detail_read_model_exposes_mode_string(self) -> None:
        model = ServerDetailReadModel.from_domain(_build_server())
        assert model.mode == "simple"
