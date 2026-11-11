from __future__ import annotations

import pytest

from app.core import exceptions as core_exceptions
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _server_mode():
    from app.modules.server.domain import value_objects

    return value_objects.ServerMode


def _disabled_error():
    return core_exceptions.ServerModeVersioningDisabledError


def _create_server(**overrides):
    kwargs = {
        "server_id": ServerId(),
        "name": "mode-aware",
        "server_type": ServerType.VANILLA,
        "minecraft_version": MinecraftVersion.parse("1.20.4"),
        "memory": MemoryAllocation(min_mb=1024, max_mb=2048),
        "java_args": JavaArguments(None),
        "properties": ServerProperties(port=PortNumber(25565)),
    }
    kwargs.update(overrides)
    return Server.create(**kwargs)


class TestServerModeValueObject:
    def test_values_are_simple_and_advanced(self) -> None:
        mode = _server_mode()
        assert mode.SIMPLE.value == "simple"
        assert mode.ADVANCED.value == "advanced"

    def test_is_str_enum(self) -> None:
        mode = _server_mode()
        assert issubclass(mode, str)
        assert mode("simple") is mode.SIMPLE
        assert mode("advanced") is mode.ADVANCED

    def test_unknown_value_is_rejected(self) -> None:
        mode = _server_mode()
        with pytest.raises(ValueError):
            mode("creative")


class TestServerModeVersioningDisabledError:
    def test_is_conflict_with_409_and_stable_code(self) -> None:
        error_type = _disabled_error()
        error = error_type("versioning disabled for simple servers")
        assert isinstance(error, core_exceptions.ConflictError)
        assert error.http_status == 409
        assert error.code == "SERVER_MODE_VERSIONING_DISABLED"

    def test_error_status_map_resolves_to_409(self) -> None:
        from app.api.errors import _ERROR_STATUS_MAP

        assert _ERROR_STATUS_MAP["SERVER_MODE_VERSIONING_DISABLED"] == 409


class TestServerAggregateMode:
    def test_defaults_to_simple(self) -> None:
        server = _create_server()
        assert server.mode is _server_mode().SIMPLE

    def test_explicit_advanced_is_kept(self) -> None:
        server = _create_server(mode=_server_mode().ADVANCED)
        assert server.mode is _server_mode().ADVANCED
