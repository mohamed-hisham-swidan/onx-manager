from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Any


class TestRunStatus(enum.StrEnum):
    __test__ = False

    PENDING = "PENDING"
    BOOTING = "BOOTING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RuntimeStatus(enum.StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    TERMINATED = "terminated"
    CRASHED = "crashed"


class BranchStatus(enum.StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    ARCHIVED = "archived"


class MaterializationStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    STALE = "stale"
    REMOVED = "removed"


class MaterializationMode(enum.StrEnum):
    READONLY = "readonly"
    EDITABLE = "editable"


class ImportReviewStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REVERTED = "reverted"
    DISMISSED = "dismissed"


MATERIALIZATION_ROOT_TESTS: str = ".onx/tests"
MATERIALIZATION_ROOT_WORKTREES: str = ".onx/worktrees"
ALLOWED_MATERIALIZATION_ROOTS: tuple[str, ...] = (
    MATERIALIZATION_ROOT_TESTS,
    MATERIALIZATION_ROOT_WORKTREES,
)


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


def normalize_server_type_str(value: Any) -> str:
    """Normalize ServerType enum or persisted 'ServerType.X' strings to lowercase slug."""
    raw = value.value if hasattr(value, "value") else str(value)
    if raw.startswith("ServerType."):
        raw = raw[len("ServerType.") :]
    return raw.strip().lower()


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
            "server_type": normalize_server_type_str(self.server_type),
            "minecraft_version": str(self.minecraft_version),
            "configs": self.configs,
            "mods": self.mods,
            "env_vars": self.env_vars,
            "java_args": self.java_args,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommitManifest:
        return cls(
            server_type=normalize_server_type_str(data.get("server_type", "vanilla")),
            minecraft_version=data.get("minecraft_version", "1.21.1"),
            configs=data.get("configs", {}),
            mods=data.get("mods", []),
            env_vars=data.get("env_vars", {}),
            java_args=data.get("java_args", ""),
        )


@dataclass(frozen=True)
class AssertionRulesConfig:
    """Declarative validation rules applied against test execution outcomes."""

    min_connected_bots_ratio: float | None = None
    max_disconnects: int = 0
    min_boot_seconds: float = 0.0
    max_boot_seconds: float | None = None
    disallow_crash_reports: bool = True
    disallow_error_logs: bool = False
    required_log_markers: list[str] = field(default_factory=list)
    forbidden_log_markers: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AssertionRulesConfig:
        if not data:
            return cls()
        raw_ratio = data.get("min_connected_bots_ratio")
        ratio = float(raw_ratio) if raw_ratio is not None else None
        if ratio is not None and not 0.0 <= ratio <= 1.0:
            raise ValueError(f"min_connected_bots_ratio must be between 0.0 and 1.0, got {ratio}")
        max_disc = int(data.get("max_disconnects", 0))
        if max_disc < 0:
            raise ValueError(f"max_disconnects cannot be negative, got {max_disc}")
        min_boot = float(data.get("min_boot_seconds", 0.0))
        if min_boot < 0:
            raise ValueError(f"min_boot_seconds cannot be negative, got {min_boot}")
        max_boot = data.get("max_boot_seconds")
        max_boot_val = float(max_boot) if max_boot is not None else None
        if max_boot_val is not None and max_boot_val < min_boot:
            raise ValueError(
                f"max_boot_seconds ({max_boot_val}) cannot be less than "
                f"min_boot_seconds ({min_boot})"
            )
        return cls(
            min_connected_bots_ratio=ratio,
            max_disconnects=max_disc,
            min_boot_seconds=min_boot,
            max_boot_seconds=max_boot_val,
            disallow_crash_reports=bool(data.get("disallow_crash_reports", True)),
            disallow_error_logs=bool(data.get("disallow_error_logs", False)),
            required_log_markers=list(data.get("required_log_markers", [])),
            forbidden_log_markers=list(data.get("forbidden_log_markers", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_connected_bots_ratio": self.min_connected_bots_ratio,
            "max_disconnects": self.max_disconnects,
            "min_boot_seconds": self.min_boot_seconds,
            "max_boot_seconds": self.max_boot_seconds,
            "disallow_crash_reports": self.disallow_crash_reports,
            "disallow_error_logs": self.disallow_error_logs,
            "required_log_markers": self.required_log_markers,
            "forbidden_log_markers": self.forbidden_log_markers,
        }


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
    duration_seconds: float = 900.0
    watchdog_overrun_seconds: float = 300.0
    assertion_rules: AssertionRulesConfig = field(default_factory=AssertionRulesConfig)

    def __post_init__(self) -> None:
        # Reconcile duration_seconds and duration_minutes
        if self.duration_seconds == 900.0 and self.duration_minutes != 15:
            object.__setattr__(self, "duration_seconds", float(self.duration_minutes * 60))
        elif self.duration_seconds != 900.0:
            object.__setattr__(
                self, "duration_minutes", max(1, math.ceil(self.duration_seconds / 60.0))
            )

        # Reconcile watchdog_overrun_seconds and watchdog_overrun_minutes
        if self.watchdog_overrun_seconds == 300.0 and self.watchdog_overrun_minutes != 5.0:
            object.__setattr__(
                self, "watchdog_overrun_seconds", float(self.watchdog_overrun_minutes * 60)
            )
        elif self.watchdog_overrun_seconds != 300.0:
            object.__setattr__(
                self, "watchdog_overrun_minutes", self.watchdog_overrun_seconds / 60.0
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_count": self.bot_count,
            "duration_minutes": self.duration_minutes,
            "duration_seconds": self.duration_seconds,
            "bot_tech": (
                self.bot_tech.value
                if isinstance(self.bot_tech, BotTech)
                else self.bot_tech
            ),
            "placement_mode": (
                self.placement_mode.value
                if isinstance(self.placement_mode, PlacementMode)
                else self.placement_mode
            ),
            "join_stagger_seconds": self.join_stagger_seconds,
            "connect_grace_seconds": self.connect_grace_seconds,
            "watchdog_overrun_minutes": self.watchdog_overrun_minutes,
            "watchdog_overrun_seconds": self.watchdog_overrun_seconds,
            "assertion_rules": self.assertion_rules.to_dict(),
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
