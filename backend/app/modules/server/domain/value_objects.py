from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.server.infrastructure.providers.base import ServerHandle

from app.core.exceptions import InvalidValueError

_REJECTED_SHELL_CHARS: frozenset[str] = frozenset("`$;|&<>()!{}")


def _reject_shell_metachars(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise InvalidValueError(field=field, value=value, reason="Must be a string")
    if len(value) > 1024:
        raise InvalidValueError(
            field=field,
            value=value,
            reason="Exceeds maximum length of 1024 characters",
        )
    if any(c in value for c in _REJECTED_SHELL_CHARS) or any(
        c in value for c in ("\n", "\r", "\0")
    ):
        raise InvalidValueError(
            field=field,
            value=value,
            reason="Contains forbidden shell metacharacters or control characters",
        )


def default_provider_for_platform() -> str:
    """Return the default provider type for the current platform."""
    if sys.platform == "win32":
        return "local_windows"
    return "local"


@dataclass(frozen=True)
class MemoryAllocation:
    min_mb: int
    max_mb: int

    def __post_init__(self) -> None:
        if self.min_mb < 128:
            raise ValueError(f"min_mb must be at least 128, got {self.min_mb}")
        if self.max_mb < self.min_mb:
            raise ValueError(f"max_mb ({self.max_mb}) must be >= min_mb ({self.min_mb})")
        if self.max_mb > 262144:
            raise ValueError(f"max_mb must be at most 262144 (256GB), got {self.max_mb}")

    @property
    def delta_mb(self) -> int:
        return self.max_mb - self.min_mb

    def __str__(self) -> str:
        return f"{self.min_mb}-{self.max_mb}M"


@dataclass(frozen=True)
class CpuAllocation:
    cores: int = 0          # 0 = unconstrained (default), >= 1 = max logical processors
    affinity: str = ""      # "" = unconstrained (default), e.g. "0-3" or "0,2,4"

    def __post_init__(self) -> None:
        if self.cores < 0:
            raise ValueError(f"cores must be ≥0, got {self.cores}")
        if self.affinity:
            # Validate affinity format: "0-3" or "0,2,4" (ranges or comma-separated)
            if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*", self.affinity):
                raise ValueError(
                    f"Invalid affinity format: {self.affinity!r} (expected e.g. '0-3' or '0,2,4')"
                )
            # Parse and validate each core ID is non-negative
            parts = self.affinity.replace(",", " ").split()
            for part in parts:
                if "-" in part:
                    start, end = part.split("-")
                    if int(start) < 0 or int(end) < 0 or int(start) > int(end):
                        raise ValueError(f"Invalid affinity range: {part}")
                elif int(part) < 0:
                    raise ValueError(f"Invalid affinity core ID: {part}")

    def __str__(self) -> str:
        parts = []
        if self.cores > 0:
            parts.append(f"cores={self.cores}")
        if self.affinity:
            parts.append(f"affinity={self.affinity}")
        return " ".join(parts) if parts else "unconstrained"

    @classmethod
    def validate(cls, cores: int, affinity: str) -> None:
        """Static validation gate for provider startup — raises ValueError on invalid input."""
        cls(cores=cores, affinity=affinity)  # triggers __post_init__


@dataclass(frozen=True)
class PortNumber:
    value: int

    def __post_init__(self) -> None:
        if self.value < 1 or self.value > 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {self.value}")

    def __str__(self) -> str:
        return str(self.value)


FORBIDDEN_JVM_HOOK_FLAGS = (
    "-XX:OnError",
    "-XX:OnOutOfMemoryError",
    "-XX:Flags=",
    "-XX:VMOptionsFile",
    "-javaagent:",
    "-agentpath:",
    "-agentlib:",
    "-Xrun",
)


@dataclass(frozen=True)
class JavaArguments:
    args: tuple[str, ...]

    def __init__(self, args: list[str] | tuple[str, ...] | None = None) -> None:
        validated = tuple(args or [])
        for arg in validated:
            if not isinstance(arg, str) or not arg.startswith("-"):
                raise InvalidValueError(
                    field="java_args",
                    value=arg,
                    reason="Invalid JVM argument (must start with '-')",
                )
            for forbidden_flag in FORBIDDEN_JVM_HOOK_FLAGS:
                if arg.lower().startswith(forbidden_flag.lower()):
                    raise InvalidValueError(
                        field="java_args",
                        value=arg,
                        reason=f"Disallowed JVM flag: {forbidden_flag}",
                    )
            _reject_shell_metachars(arg, "java_args")
        object.__setattr__(self, "args", validated)

    def __str__(self) -> str:
        return shlex.join(self.args)

    def as_list(self) -> list[str]:
        return list(self.args)


@dataclass(frozen=True)
class ServerProperties:
    port: PortNumber
    motd: str = "A Minecraft Server"
    max_players: int = 20
    gamemode: str = "survival"
    difficulty: str = "easy"
    spawn_protection: int = 16
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = 10
    simulation_distance: int = 10

    _valid_gamemodes: tuple[str, ...] = ("survival", "creative", "adventure", "spectator")
    _valid_difficulties: tuple[str, ...] = ("peaceful", "easy", "normal", "hard")

    def __post_init__(self) -> None:
        if self.gamemode not in self._valid_gamemodes:
            raise ValueError(f"Invalid gamemode: {self.gamemode!r}")
        if self.difficulty not in self._valid_difficulties:
            raise ValueError(f"Invalid difficulty: {self.difficulty!r}")
        if self.max_players < 1 or self.max_players > 500:
            raise ValueError(f"max_players must be 1-500, got {self.max_players}")
        if self.view_distance < 2 or self.view_distance > 32:
            raise ValueError(f"view_distance must be 2-32, got {self.view_distance}")


class ServerType(str, Enum):
    VANILLA = "vanilla"
    PAPER = "paper"
    PURPUR = "purpur"
    FABRIC = "fabric"
    FORGE = "forge"
    NEOFORGE = "neoforge"
    SPIGOT = "spigot"
    BUKKIT = "bukkit"

    @classmethod
    def known_types(cls) -> list[str]:
        return [e.value for e in cls]

    @classmethod
    def display_name(cls, value: str) -> str:
        mapping = {
            "vanilla": "Vanilla",
            "paper": "Paper",
            "purpur": "Purpur",
            "fabric": "Fabric",
            "forge": "Forge",
            "neoforge": "NeoForge",
            "spigot": "Spigot",
            "bukkit": "Bukkit",
        }
        return mapping.get(value, value.capitalize())


class LocationType(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"
    SSH = "ssh"
    NETWORK = "network"


@dataclass(frozen=True)
class ServerDeployment:
    location_type: LocationType = LocationType.LOCAL
    location_uri: str = ""
    root_path: str = ""
    working_directory: str = "."
    startup_jar: str = "server.jar"
    startup_command: str = ""
    primary_world: str = "world"

    @property
    def server_dir(self) -> str:
        return self.server_directory()

    def server_directory(self) -> str:
        if self.working_directory and self.working_directory != ".":
            return os.path.join(self.root_path, self.working_directory)
        return self.root_path

    def jar_path(self) -> str:
        return os.path.join(self.server_directory(), self.startup_jar)

    def properties_path(self) -> str:
        return os.path.join(self.server_directory(), "server.properties")

    def eula_path(self) -> str:
        return os.path.join(self.server_directory(), "eula.txt")

    def world_path(self, world_name: str | None = None) -> str:
        return os.path.join(self.server_directory(), world_name or self.primary_world)


@dataclass(frozen=True)
class LaunchConfiguration:
    java_executable: str = "java"
    startup_command: list[str] | tuple[str, ...] | None = None
    startup_jar: str = "server.jar"
    jvm_flags: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    working_directory: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.java_executable, str) or not self.java_executable.strip():
            raise InvalidValueError(
                field="java_executable",
                value=self.java_executable,
                reason="java_executable must be a non-empty string",
            )
        _reject_shell_metachars(self.java_executable, "java_executable")
        if re.search(r"\s+-", self.java_executable):
            raise InvalidValueError(
                field="java_executable",
                value=self.java_executable,
                reason="java_executable cannot contain command-line flags",
            )
        segments = [seg for seg in re.split(r"[/\\]", self.java_executable) if seg]
        if ".." in segments:
            raise InvalidValueError(
                field="java_executable",
                value=self.java_executable,
                reason="java_executable cannot contain '..' path traversal segments",
            )

        if self.startup_command is not None:
            if isinstance(self.startup_command, str):
                raise TypeError(
                    "startup_command must be a list[str] or tuple[str, ...], "
                    f"got str: {self.startup_command!r}"
                )
            if not isinstance(self.startup_command, (list, tuple)):
                raise TypeError(
                    "startup_command must be a list[str] or tuple[str, ...], "
                    f"got {type(self.startup_command).__name__}"
                )
            if len(self.startup_command) == 0:
                raise ValueError("startup_command cannot be empty when provided")
            for i, arg in enumerate(self.startup_command):
                if not isinstance(arg, str):
                    raise TypeError(
                        f"startup_command element at index {i} must be a str, "
                        f"got {type(arg).__name__}: {arg!r}"
                    )
                if not arg.strip():
                    raise ValueError(
                        f"startup_command element at index {i} cannot be empty "
                        f"or whitespace only: {arg!r}"
                    )
                _reject_shell_metachars(arg, "startup_command")
            object.__setattr__(self, "startup_command", tuple(self.startup_command))

        if isinstance(self.jvm_flags, list):
            object.__setattr__(self, "jvm_flags", tuple(self.jvm_flags))
        for flag in self.jvm_flags:
            _reject_shell_metachars(flag, "jvm_flags")

    def effective_command(self) -> list[str]:
        if self.startup_command is not None:
            return list(self.startup_command)
        return [self.java_executable, *self.jvm_flags, "-jar", self.startup_jar, "nogui"]


@dataclass
class RuntimeInfo:
    status: str = "created"
    provider: str = ""
    host: str = ""
    port: int = 25565
    pid: int | None = None
    start_time: int | None = None
    running_start_time: float | None = None
    uptime_seconds: float = 0.0
    last_crash_time: float | None = None
    restart_count: int = 0
    external_id: str = ""
    last_log_lines: list[str] = field(default_factory=list)


def build_server_handle(
    server: Any,
    provider_name: str,
    server_dir: Path | str | None = None,
) -> ServerHandle:
    from app.modules.server.infrastructure.providers.base import ServerHandle

    server_id = str(server.id)
    external_id = (
        server.runtime.external_id
        if hasattr(server, "runtime") and server.runtime and server.runtime.external_id
        else ""
    )
    port_val = (
        server.runtime.port
        if hasattr(server, "runtime") and server.runtime and server.runtime.port
        else (
            server.port.value
            if hasattr(server, "port") and hasattr(server.port, "value")
            else getattr(server, "port", 25565)
        )
    )
    pid_val = (
        server.runtime.pid
        if hasattr(server, "runtime") and server.runtime
        else None
    )
    start_time_val = (
        server.runtime.start_time
        if hasattr(server, "runtime") and server.runtime
        else None
    )
    server_name = str(server.name) if hasattr(server, "name") else ""
    metadata = {
        "server_name": server_name,
        "pid": pid_val,
        "start_time": start_time_val,
        "port": port_val,
        "server_dir": str(server_dir) if server_dir else None,
    }
    return ServerHandle(
        provider=provider_name,
        server_id=server_id,
        external_id=external_id,
        metadata=metadata,
    )

