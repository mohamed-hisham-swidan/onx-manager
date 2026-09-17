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


class BranchStatus(enum.StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    ARCHIVED = "archived"


class MaterializationStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    STALE = "stale"
    REMOVED = "removed"


class PathClassification(enum.StrEnum):
    TRACKED = "tracked"
    PERSISTENT = "persistent"
    GENERATED = "generated"
    IGNORED = "ignored"
    EPHEMERAL = "ephemeral"


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


@dataclass(frozen=True)
class Tree:
    """Represents tracked files and configuration associated with a commit snapshot.

    Formalizes CommitManifest into the version control domain model.
    """

    server_type: str
    minecraft_version: str
    configs: dict[str, str] = field(default_factory=dict)
    mods: list[dict[str, Any]] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    java_args: str = ""

    @classmethod
    def from_manifest(cls, manifest: CommitManifest) -> Tree:
        return cls(
            server_type=str(
                manifest.server_type.value
                if hasattr(manifest.server_type, "value")
                else manifest.server_type
            ),
            minecraft_version=str(manifest.minecraft_version),
            configs=dict(manifest.configs),
            mods=list(manifest.mods),
            env_vars=dict(manifest.env_vars),
            java_args=manifest.java_args,
        )

    def to_manifest(self) -> CommitManifest:
        return CommitManifest(
            server_type=self.server_type,
            minecraft_version=self.minecraft_version,
            configs=dict(self.configs),
            mods=list(self.mods),
            env_vars=dict(self.env_vars),
            java_args=self.java_args,
        )


@dataclass(frozen=True)
class Revision:
    """Immutable value object binding a specific resolved Commit ID.

    Formalizes commit resolution. A Revision represents an explicit, fixed
    resolved version. Moving a Branch reference does not alter an already-resolved
    Revision.
    """

    commit_id: str
    server_id: str
    resolved_from: str
    source_branch: str | None = None

    def __post_init__(self) -> None:
        if not self.commit_id:
            raise ValueError("Revision commit_id cannot be empty")
        if not self.server_id:
            raise ValueError("Revision server_id cannot be empty")

    @classmethod
    def from_commit(cls, commit_id: str, server_id: str) -> Revision:
        if not commit_id:
            raise ValueError("Cannot create Revision from empty commit_id")
        if not server_id:
            raise ValueError("Cannot create Revision from empty server_id")
        return cls(
            commit_id=commit_id,
            server_id=server_id,
            resolved_from=f"commit:{commit_id}",
        )

    @classmethod
    def from_branch(
        cls,
        branch_name: str,
        head_commit_id: str,
        branch_server_id: str,
        target_server_id: str,
    ) -> Revision:
        if branch_server_id != target_server_id:
            raise ValueError(
                f"Cannot resolve branch '{branch_name}' from server '{branch_server_id}' "
                f"for target server '{target_server_id}'"
            )
        if not head_commit_id:
            raise ValueError(f"Branch '{branch_name}' has no head commit to resolve")
        return cls(
            commit_id=head_commit_id,
            server_id=target_server_id,
            resolved_from=f"branch:{branch_name}@{head_commit_id}",
            source_branch=branch_name,
        )

    @classmethod
    def from_tag(
        cls,
        tag_name: str,
        commit_id: str,
        tag_server_id: str,
        target_server_id: str,
    ) -> Revision:
        if tag_server_id != target_server_id:
            raise ValueError(
                f"Cannot resolve tag '{tag_name}' from server '{tag_server_id}' "
                f"for target server '{target_server_id}'"
            )
        if not commit_id:
            raise ValueError(f"Tag '{tag_name}' has no target commit to resolve")
        return cls(
            commit_id=commit_id,
            server_id=target_server_id,
            resolved_from=f"tag:{tag_name}@{commit_id}",
        )
