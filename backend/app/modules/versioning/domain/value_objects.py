from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class TestRunStatus(enum.StrEnum):
    __test__ = False

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BotTech(enum.StrEnum):
    AUTO = "auto"
    MINEFLAYER = "mineflayer"
    FAKEPLAYER_NEXT = "fakeplayer_next"


class PlacementMode(enum.StrEnum):
    SIDECAR = "sidecar"
    IN_CONTAINER = "in_container"


@dataclass(frozen=True)
class ModReference:
    filename: str
    mod_id: str = ""
    name: str = ""
    version: str = ""
    loader: str = ""
    sha256: str = ""
    source: str = "custom"  # custom | modrinth


@dataclass(frozen=True)
class CommitManifest:
    """Immutable manifest of all non-world server state captured in a commit."""

    server_type: str
    minecraft_version: str
    configs: dict[str, str] = field(default_factory=dict)  # relative path -> content
    mods: list[dict[str, Any]] = field(default_factory=list)  # list of ModReference dicts
    env_vars: dict[str, str] = field(default_factory=dict)
    java_args: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_type": str(
                self.server_type.value if hasattr(self.server_type, "value") else self.server_type
            ),
            "minecraft_version": str(self.minecraft_version),
            "configs": self.configs,
            "mods": self.mods,
            "env_vars": self.env_vars,
            "java_args": self.java_args,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommitManifest:
        return cls(
            server_type=data.get("server_type", "vanilla"),
            minecraft_version=data.get("minecraft_version", "1.21.1"),
            configs=data.get("configs", {}),
            mods=data.get("mods", []),
            env_vars=data.get("env_vars", {}),
            java_args=data.get("java_args", ""),
        )


@dataclass(frozen=True)
class BotVerificationConfig:
    """Resolved configuration for a bot verification run."""

    bot_count: int = 10
    duration_minutes: int = 15
    bot_tech: BotTech = BotTech.AUTO
    placement_mode: PlacementMode = PlacementMode.SIDECAR
    join_stagger_seconds: float = 3.0
    connect_grace_seconds: float = 60.0
    watchdog_overrun_minutes: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_count": self.bot_count,
            "duration_minutes": self.duration_minutes,
            "bot_tech": self.bot_tech.value
            if isinstance(self.bot_tech, BotTech)
            else self.bot_tech,
            "placement_mode": (
                self.placement_mode.value
                if isinstance(self.placement_mode, PlacementMode)
                else self.placement_mode
            ),
            "join_stagger_seconds": self.join_stagger_seconds,
            "connect_grace_seconds": self.connect_grace_seconds,
            "watchdog_overrun_minutes": self.watchdog_overrun_minutes,
        }
