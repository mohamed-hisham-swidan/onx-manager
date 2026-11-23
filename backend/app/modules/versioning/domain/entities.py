from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.versioning.domain.value_objects import (
    BotTech,
    BranchStatus,
    CommitManifest,
    ImportReviewStatus,
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
    PlacementMode,
    RuntimeStatus,
    TestRunStatus,
    Tree,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Project:
    """Logical root environment.

    Stage A scope: maps 1:1 with the existing Server identity.
    """

    id: str  # server_id

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Project id cannot be empty")


@dataclass
class Repository:
    """Owns commit history and branch references for a Project."""

    project_id: str  # server_id

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("Repository project_id cannot be empty")


@dataclass(frozen=True)
class BranchProtectionPolicy:
    """Configurable policy for a protected branch."""

    require_test_pass: bool = True
    allow_direct_commit: bool = False
    allow_force_bypass: bool = True
    prevent_deletion: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_test_pass": self.require_test_pass,
            "allow_direct_commit": self.allow_direct_commit,
            "allow_force_bypass": self.allow_force_bypass,
            "prevent_deletion": self.prevent_deletion,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BranchProtectionPolicy:
        if not data:
            return cls()
        return cls(
            require_test_pass=bool(data.get("require_test_pass", True)),
            allow_direct_commit=bool(data.get("allow_direct_commit", False)),
            allow_force_bypass=bool(data.get("allow_force_bypass", True)),
            prevent_deletion=bool(data.get("prevent_deletion", True)),
        )


@dataclass
class ServerBranch:
    """A named pointer to a Commit in a Repository.

    Lifecycle: created -> active -> archived.
    """

    id: str
    server_id: str
    name: str
    head_commit_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    status: BranchStatus = BranchStatus.CREATED
    is_protected: bool = False
    protection_policy: BranchProtectionPolicy | None = None
    port_set: dict[str, Any] | None = None
    runtime_status: str = "stopped"
    active_runtime_id: str | None = None
    active_commit_sha: str | None = None
    active_data_template_id: str | None = None
    pending_merge_on_restart: bool = False
    pending_merge_status: str | None = None
    pending_merge_error: str | None = None

    def __post_init__(self) -> None:
        if not self.server_id:
            raise ValueError("Branch server_id cannot be empty")
        if not self.name:
            raise ValueError("Branch name cannot be empty")

    def activate(self) -> None:
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot activate archived branch '{self.name}'")
        self.status = BranchStatus.ACTIVE

    def archive(self) -> None:
        if self.name == "main":
            raise ValueError("Branch 'main' is system-protected and cannot be archived")
        self.status = BranchStatus.ARCHIVED

    def advance_head(self, commit_id: str) -> None:
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot commit to archived branch '{self.name}'")
        if not commit_id:
            raise ValueError("Cannot advance branch head to empty commit_id")
        self.head_commit_id = commit_id
        if self.status == BranchStatus.CREATED:
            self.status = BranchStatus.ACTIVE

    def protect(self, policy: BranchProtectionPolicy | None = None) -> None:
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot configure protection on archived branch '{self.name}'")
        self.is_protected = True
        self.protection_policy = policy or BranchProtectionPolicy()

    def unprotect(self) -> None:
        if self.name == "main":
            raise ValueError("Branch 'main' is system-protected and cannot be unprotected")
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot unprotect archived branch '{self.name}'")
        self.is_protected = False
        self.protection_policy = None

    def can_commit_directly(self) -> bool:
        if self.status == BranchStatus.ARCHIVED:
            return False
        if not self.is_protected:
            return True
        policy = self.protection_policy or BranchProtectionPolicy()
        return policy.allow_direct_commit

    def can_archive(self) -> bool:
        if self.name == "main":
            return False
        if not self.is_protected:
            return True
        policy = self.protection_policy or BranchProtectionPolicy()
        return not policy.prevent_deletion


Branch = ServerBranch


@dataclass
class ServerWorldSnapshot:
    id: str
    server_id: str
    storage_path: str
    size_bytes: int = 0
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class ServerCommit:
    """Immutable snapshot of a Tree with DAG ancestry (multi-parent capable)."""

    id: str
    server_id: str
    message: str
    manifest: CommitManifest
    branch_id: str | None = None
    parent_commit_id: str | None = None
    parent_commit_ids: list[str] = field(default_factory=list)
    author_id: str | None = None
    world_snapshot_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Commit id cannot be empty")
        if not self.server_id:
            raise ValueError("Commit server_id cannot be empty")

        # Synchronize parent_commit_id and parent_commit_ids
        if not self.parent_commit_ids and self.parent_commit_id:
            self.parent_commit_ids = [self.parent_commit_id]
        elif self.parent_commit_ids and not self.parent_commit_id:
            self.parent_commit_id = self.parent_commit_ids[0]

        # Prevent duplicate parents in parent_commit_ids
        if len(self.parent_commit_ids) != len(set(self.parent_commit_ids)):
            raise ValueError("Duplicate parent commit references are not allowed")

        # Prevent self-parenting
        if self.id in self.parent_commit_ids:
            raise ValueError(
                f"Self-parenting rejected: commit '{self.id}' cannot be its own parent"
            )

    @property
    def tree(self) -> Tree:
        return Tree.from_manifest(self.manifest)

    def validate_parent(self, parent: ServerCommit | None) -> None:
        """Validates parent commit ancestry and server ownership."""
        if self.parent_commit_id is not None:
            if parent is None:
                raise ValueError(
                    f"Dangling parent_commit_id '{self.parent_commit_id}': parent commit not found"
                )
            if parent.id != self.parent_commit_id:
                raise ValueError(
                    f"Parent commit ID mismatch: expected '{self.parent_commit_id}', "
                    f"got '{parent.id}'"
                )
            if parent.server_id != self.server_id:
                raise ValueError(
                    f"Cross-server parent rejected: parent server '{parent.server_id}' "
                    f"does not match commit server '{self.server_id}'"
                )

    def validate_parents(self, parents: list[ServerCommit]) -> None:
        """Validates all parent commits for multi-parent merge commits."""
        parent_map = {p.id: p for p in parents}
        for pid in self.parent_commit_ids:
            if pid not in parent_map:
                raise ValueError(f"Dangling parent commit '{pid}': parent commit not found")
            p = parent_map[pid]
            if p.server_id != self.server_id:
                raise ValueError(
                    f"Cross-server parent rejected: parent server '{p.server_id}' "
                    f"does not match commit server '{self.server_id}'"
                )


Commit = ServerCommit


@dataclass(frozen=True)
class Tag:
    """Immutable named pointer to a specific Commit within a repository/server."""

    id: str
    server_id: str
    name: str
    commit_id: str
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Tag id cannot be empty")
        if not self.server_id:
            raise ValueError("Tag server_id cannot be empty")
        if not self.name or not self.name.strip():
            raise ValueError("Tag name cannot be empty")
        if not self.commit_id:
            raise ValueError("Tag commit_id cannot be empty")


ServerTag = Tag


@dataclass
class Materialization:
    """Represents an isolated filesystem working tree derived from versioned state.

    Lifecycle: pending -> ready -> stale -> removed.
    Enforces path isolation under an isolated .onx/tests or .onx/worktrees root.
    """

    id: str
    commit_id: str
    root_path: str
    status: MaterializationStatus = MaterializationStatus.PENDING
    path_classification: dict[str, PathClassification] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    mode: MaterializationMode = MaterializationMode.READONLY
    server_id: str = ""
    revision: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Materialization id cannot be empty")
        if not self.commit_id:
            raise ValueError("Materialization commit_id cannot be empty")
        norm = os.path.normpath(self.root_path)
        is_managed_root = (
            (".onx" in norm and "tests" in norm) or (".onx" in norm and "worktrees" in norm)
        )
        if not is_managed_root or ".." in self.root_path:
            raise ValueError(
                "Materialization root_path must be an isolated .onx/tests directory "
                f"or .onx/worktrees directory without traversal escapes: {self.root_path}"
            )

    def mark_ready(self) -> None:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot transition removed materialization to ready")
        self.status = MaterializationStatus.READY

    def mark_stale(self) -> None:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot transition removed materialization to stale")
        self.status = MaterializationStatus.STALE

    def mark_removed(self) -> None:
        self.status = MaterializationStatus.REMOVED

    def set_mode(self, mode: MaterializationMode) -> None:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot set edit mode on removed materialization")
        self.mode = mode

    def stage_path(self, relative_path: str, classification: PathClassification) -> str:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot stage path into removed materialization")
        norm_rel = os.path.normpath(relative_path)
        if norm_rel.startswith("..") or os.path.isabs(relative_path):
            raise ValueError(f"Staging path escapes materialization root: {relative_path}")
        target = os.path.normpath(os.path.join(self.root_path, norm_rel))
        if not Path(target).is_relative_to(Path(self.root_path)):
            raise ValueError(f"Staging path escapes materialization root: {relative_path}")
        self.path_classification[norm_rel] = classification
        return target


@dataclass
class ImportReview:
    """Represents a review record for changes imported automatically from live disk."""

    id: str
    server_id: str
    commit_id: str
    parent_commit_id: str | None = None
    branch_name: str = "main"
    status: ImportReviewStatus = ImportReviewStatus.PENDING
    changes: list[dict[str, Any]] = field(default_factory=list)
    revert_commit_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ImportReview id cannot be empty")
        if not self.server_id:
            raise ValueError("ImportReview server_id cannot be empty")
        if not self.commit_id:
            raise ValueError("ImportReview commit_id cannot be empty")

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ImportReviewStatus.CONFIRMED,
            ImportReviewStatus.REVERTED,
            ImportReviewStatus.DISMISSED,
        )

    def confirm(self) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot confirm terminal import review ({self.status})")
        self.status = ImportReviewStatus.CONFIRMED
        self.updated_at = _utcnow()

    def dismiss(self) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot dismiss terminal import review ({self.status})")
        self.status = ImportReviewStatus.DISMISSED
        self.updated_at = _utcnow()

    def revert(self, revert_commit_id: str) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot revert terminal import review ({self.status})")
        if not revert_commit_id:
            raise ValueError("revert_commit_id cannot be empty")
        self.status = ImportReviewStatus.REVERTED
        self.revert_commit_id = revert_commit_id
        self.updated_at = _utcnow()


@dataclass
class Runtime:
    """Represents a running execution instance bound to an immutable Commit ID.

    SAFETY INVARIANT 1:
    A Runtime MUST be pinned to an immutable Commit ID.
    Never make a Runtime depend directly on a moving Branch reference.
    """

    id: str
    commit_id: str
    materialization_id: str | None = None
    provider_type: str = "docker"
    server_id: str | None = None
    container_id: str | None = None
    pid: int | None = None
    port: int | None = None
    status: RuntimeStatus = RuntimeStatus.STARTING
    exit_code: int | None = None
    oom_killed: bool = False
    started_at: datetime = field(default_factory=_utcnow)
    stopped_at: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)
    branch_name: str | None = None
    data_template_id: str | None = None
    port_set: dict[str, Any] | None = None
    allow_public_test_join: bool = False
    export_path: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Runtime id cannot be empty")
        if not self.commit_id:
            raise ValueError("Runtime commit_id cannot be empty")
        if self.materialization_id == "":
            raise ValueError("Runtime materialization_id cannot be empty string")
        if self.commit_id.startswith("branch:") or self.commit_id.startswith("refs/"):
            raise ValueError("Runtime cannot bind directly to a mutable branch reference")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "commit_id" and hasattr(self, "commit_id"):
            raise ValueError("Runtime commit_id is immutable and cannot be changed after creation")
        super().__setattr__(name, value)

    def mark_running(
        self,
        container_id: str | None = None,
        pid: int | None = None,
        port: int | None = None,
    ) -> None:
        self.status = RuntimeStatus.RUNNING
        if container_id is not None:
            self.container_id = container_id
        if pid is not None:
            self.pid = pid
        if port is not None:
            self.port = port

    def mark_terminated(self, exit_code: int = 0) -> None:
        self.status = RuntimeStatus.TERMINATED
        self.exit_code = exit_code
        self.stopped_at = _utcnow()

    def mark_crashed(self, exit_code: int | None = None, oom_killed: bool = False) -> None:
        self.status = RuntimeStatus.CRASHED
        self.exit_code = exit_code
        self.oom_killed = oom_killed
        self.stopped_at = _utcnow()

    @classmethod
    def create(
        cls,
        id: str,
        commit_id: str,
        materialization: Materialization | None = None,
        provider_type: str = "docker",
        server_id: str | None = None,
        container_id: str | None = None,
        pid: int | None = None,
        port: int | None = None,
        status: RuntimeStatus = RuntimeStatus.STARTING,
    ) -> Runtime:
        if materialization is not None and materialization.status == MaterializationStatus.REMOVED:
            raise ValueError("Runtime cannot reference a removed Materialization")
        if not commit_id or commit_id.startswith("branch:") or commit_id.startswith("refs/"):
            raise ValueError("Runtime cannot bind directly to a mutable branch reference")
        return cls(
            id=id,
            commit_id=commit_id,
            materialization_id=materialization.id if materialization is not None else None,
            provider_type=provider_type,
            server_id=server_id,
            container_id=container_id,
            pid=pid,
            port=port,
            status=status,
        )


@dataclass
class TestDefinition:
    """Reusable, persistent test specification aggregate (DECISION-2026-09-17-003)."""

    __test__ = False

    id: str
    server_id: str
    name: str
    description: str = ""
    server_type: str = "vanilla"
    bot_technology: BotTech = BotTech.MINEFLAYER
    bot_count: int = 5
    duration_seconds: int = 60
    join_stagger_seconds: float = 1.0
    connect_grace_seconds: int = 20
    placement_mode: PlacementMode = PlacementMode.SIDECAR
    assertion_rules: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("TestDefinition id cannot be empty")
        if not self.server_id:
            raise ValueError("TestDefinition server_id cannot be empty")
        if not self.name or not self.name.strip():
            raise ValueError("TestDefinition name cannot be empty")
        if self.bot_count < 0 or self.bot_count > 100:
            raise ValueError(f"Invalid bot_count: {self.bot_count} (must be between 0 and 100)")
        if self.duration_seconds < 10 or self.duration_seconds > 3600:
            raise ValueError(f"Invalid duration_seconds: {self.duration_seconds} (must be 10-3600)")
        if self.timeout_seconds < 30 or self.timeout_seconds > 7200:
            raise ValueError(f"Invalid timeout_seconds: {self.timeout_seconds} (must be 30-7200)")
        if self.assertion_rules:
            from app.modules.versioning.domain.value_objects import AssertionRulesConfig

            AssertionRulesConfig.from_dict(self.assertion_rules)

    def update(
        self,
        name: str | None = None,
        description: str | None = None,
        server_type: str | None = None,
        bot_technology: BotTech | None = None,
        bot_count: int | None = None,
        duration_seconds: int | None = None,
        join_stagger_seconds: float | None = None,
        connect_grace_seconds: int | None = None,
        placement_mode: PlacementMode | None = None,
        assertion_rules: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        if name is not None:
            if not name.strip():
                raise ValueError("TestDefinition name cannot be empty")
            self.name = name.strip()
        if description is not None:
            self.description = description
        if server_type is not None:
            self.server_type = server_type
        if bot_technology is not None:
            self.bot_technology = bot_technology
        if bot_count is not None:
            if bot_count < 0 or bot_count > 100:
                raise ValueError(f"Invalid bot_count: {bot_count}")
            self.bot_count = bot_count
        if duration_seconds is not None:
            if duration_seconds < 10 or duration_seconds > 3600:
                raise ValueError(f"Invalid duration_seconds: {duration_seconds}")
            self.duration_seconds = duration_seconds
        if join_stagger_seconds is not None:
            self.join_stagger_seconds = join_stagger_seconds
        if connect_grace_seconds is not None:
            self.connect_grace_seconds = connect_grace_seconds
        if placement_mode is not None:
            self.placement_mode = placement_mode
        if assertion_rules is not None:
            from app.modules.versioning.domain.value_objects import AssertionRulesConfig

            AssertionRulesConfig.from_dict(assertion_rules)
            self.assertion_rules = assertion_rules
        if timeout_seconds is not None:
            if timeout_seconds < 30 or timeout_seconds > 7200:
                raise ValueError(f"Invalid timeout_seconds: {timeout_seconds}")
            self.timeout_seconds = timeout_seconds
        self.updated_at = _utcnow()


@dataclass
class PersistentDataset:
    """Represents mutable persistent data outside immutable versioned state.

    SAFETY INVARIANT 3:
    Writes to PersistentDataset MUST NOT silently mutate Commit, Tree, or Branch.
    """

    id: str
    runtime_id: str
    dataset_root: str
    server_id: str
    classification: PathClassification = PathClassification.PERSISTENT
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("PersistentDataset id cannot be empty")
        if not self.runtime_id:
            raise ValueError("PersistentDataset runtime_id cannot be empty")
        if not self.dataset_root:
            raise ValueError("PersistentDataset dataset_root cannot be empty")

    def validate_write_path(
        self, relative_path: str, tracked_tree: Tree | CommitManifest | None = None
    ) -> None:
        """Validates that writes to mutable datasets do not overlap tracked tree files."""
        norm_path = os.path.normpath(relative_path).replace("\\", "/")
        if tracked_tree is not None:
            tracked_configs = (
                tracked_tree.configs if hasattr(tracked_tree, "configs") else {}
            )
            if norm_path in tracked_configs:
                raise ValueError(
                    f"PersistentDataset write to '{relative_path}' violates boundary: "
                    f"overlaps tracked configuration in Tree"
                )
            tracked_mods = tracked_tree.mods if hasattr(tracked_tree, "mods") else []
            for m in tracked_mods:
                if isinstance(m, dict) and m.get("filename") == norm_path:
                    raise ValueError(
                        f"PersistentDataset write to '{relative_path}' violates boundary: "
                        f"overlaps tracked mod in Tree"
                    )


@dataclass
class ServerTestRun:
    """Represents an execution instance with result/evidence state."""

    __test__ = False

    id: str
    server_id: str
    commit_id: str
    node_id: str = "local"
    status: TestRunStatus = TestRunStatus.PENDING
    ephemeral_port: int | None = None
    log_output: str | None = None
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    expires_at: datetime | None = None
    bot_count: int = 10
    duration_minutes: int = 15
    placement_mode: PlacementMode = PlacementMode.SIDECAR
    bot_tech: BotTech = BotTech.AUTO
    # Stage D admission earmarks (nullable: runs created before b1e2100000017
    # carry None and fall back to recomputation; all Stage D rows write values).
    reserved_ram_mb: int | None = None
    reserved_cores: int | None = None
    # Stage F: Runtime attach, TestDefinition link, structured evidence & retention
    runtime_id: str | None = None
    test_definition_id: str | None = None
    evidence_bundle: dict[str, Any] | None = None
    artifacts_purged: bool = False
    operation_id: str | None = None
    branch_name: str | None = None
    data_template_id: str | None = None
    port_set: dict[str, Any] | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TestRunStatus.PASSED,
            TestRunStatus.FAILED,
            TestRunStatus.CANCELLED,
        )

    def mark_booting(self) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to BOOTING")
        self.status = TestRunStatus.BOOTING

    def mark_running(self, ephemeral_port: int | None = None) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to RUNNING")
        self.status = TestRunStatus.RUNNING
        self.ephemeral_port = ephemeral_port

    def mark_passed(self, log_output: str | None = None) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to PASSED")
        self.status = TestRunStatus.PASSED
        if log_output:
            self.log_output = log_output

    def mark_failed(self, reason: str, log_output: str | None = None) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to FAILED")
        self.status = TestRunStatus.FAILED
        self.failure_reason = reason
        if log_output:
            self.log_output = log_output

    def mark_cancelled(self, reason: str = "Cancelled by user") -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to CANCELLED")
        self.status = TestRunStatus.CANCELLED
        self.failure_reason = reason


Run = ServerTestRun
TestRun = ServerTestRun


@dataclass
class DataTemplate:
    """Stored quiescent data template for a server."""

    id: str
    server_id: str
    name: str
    description: str = ""
    source_branch_name: str | None = None
    source_commit_sha: str | None = None
    storage_path: str = ""
    file_count: int = 0
    total_bytes: int = 0
    status: str = "ready"
    operation_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("DataTemplate id cannot be empty")
        if not self.server_id:
            raise ValueError("DataTemplate server_id cannot be empty")
        if not self.name:
            raise ValueError("DataTemplate name cannot be empty")
