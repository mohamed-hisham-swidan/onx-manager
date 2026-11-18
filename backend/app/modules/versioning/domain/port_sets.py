"""Host port sets for P4 branch runtimes."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ServerModeVersioningDisabledError, ValidationError

_PLUGIN_KEY_RE = re.compile(r"\A[a-z0-9][a-z0-9_-]{0,31}\Z")


@dataclass(frozen=True)
class HostPortSet:
    game_port: int
    rcon_port: int
    query_port: int | None = None
    plugin_ports: dict[str, int] = field(default_factory=dict)
    container_game_port: int = 25565
    container_rcon_port: int = 25575

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        # Validate host ports are ints (not bools) in range.
        host_ports: list[int] = [self.game_port, self.rcon_port]
        if self.query_port is not None:
            host_ports.append(self.query_port)
        host_ports.extend(self.plugin_ports.values())

        for port in host_ports:
            if isinstance(port, bool) or not isinstance(port, int):
                raise ValidationError(
                    "Host port must be an integer", field="port_set"
                )
            if port < 1024 or port > 65535:
                raise ValidationError(
                    f"Host port {port} outside 1024..65535", field="port_set"
                )

        if self.container_game_port != 25565:
            raise ValidationError(
                "container_game_port must be 25565", field="port_set"
            )
        if self.container_rcon_port != 25575:
            raise ValidationError(
                "container_rcon_port must be 25575", field="port_set"
            )

        for key in self.plugin_ports:
            if not _PLUGIN_KEY_RE.match(key):
                raise ValidationError(
                    f"Invalid plugin port key '{key}'", field="port_set"
                )

        if len(set(host_ports)) != len(host_ports):
            raise ValidationError(
                "Duplicate host port within port set", field="port_set"
            )

    def all_host_ports(self) -> frozenset[int]:
        ports = {self.game_port, self.rcon_port}
        if self.query_port is not None:
            ports.add(self.query_port)
        ports.update(self.plugin_ports.values())
        return frozenset(ports)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_port": self.game_port,
            "rcon_port": self.rcon_port,
            "query_port": self.query_port,
            "plugin_ports": dict(self.plugin_ports),
            "container_game_port": self.container_game_port,
            "container_rcon_port": self.container_rcon_port,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HostPortSet:
        data = dict(data or {})
        return cls(
            game_port=int(data["game_port"]),
            rcon_port=int(data["rcon_port"]),
            query_port=(
                None if data.get("query_port") is None else int(data["query_port"])
            ),
            plugin_ports=dict(data.get("plugin_ports") or {}),
            container_game_port=int(data.get("container_game_port", 25565)),
            container_rcon_port=int(data.get("container_rcon_port", 25575)),
        )

    def to_panel_properties(self, rcon_password: str) -> dict[str, str]:
        props: dict[str, str] = {
            "server-port": "25565",
            "enable-rcon": "true",
            "rcon.port": "25575",
            "rcon.password": rcon_password,
        }
        if self.query_port is not None:
            props["enable-query"] = "true"
            props["query.port"] = str(self.query_port)
        return props

    def to_docker_port_bindings(
        self, host_ip: str | None = None, protocol: str = "tcp"  # noqa: ARG002
    ) -> list[str]:
        specs: list[str] = []
        prefix = f"{host_ip}:" if host_ip else ""
        specs.append(f"{prefix}{self.game_port}:{self.container_game_port}")
        specs.append(f"127.0.0.1:{self.rcon_port}:{self.container_rcon_port}")
        if self.query_port is not None:
            specs.append(f"{prefix}{self.query_port}:{self.query_port}/udp")
        for port in self.plugin_ports.values():
            specs.append(f"{prefix}{port}:{port}")
        return specs
