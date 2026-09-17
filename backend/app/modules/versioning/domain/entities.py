from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.server.domain.aggregate import Server
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BranchStatus,
    CommitManifest,
    MaterializationStatus,
    PathClassification,
    PlacementMode,
    TestRunStatus,
    Tree,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


Project = Server


class Repository:
    """Represents the version control repository aggregate for a project/server."""

    def __init__(self, server_id: str) -> None:
        if not server_id:
            raise ValueError("Repository server_id cannot be empty")
        self.server_id = server_id


@dataclass
class ServerBranch:
    id: str
    server_id: str
    name: str
    head_commit_id: str | None = None
    status: BranchStatus = BranchStatus.CREATED
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.server_id:
            raise ValueError("Branch server_id cannot be empty")
        if not self.name:
            raise ValueError("Branch name cannot be empty")

    def advance_head(self, commit_id: str) -> None:
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot commit to archived branch '{self.name}'")
        if not commit_id:
            raise ValueError("Cannot advance head to empty commit_id")
        self.head_commit_id = commit_id
        if self.status == BranchStatus.CREATED:
            self.status = BranchStatus.ACTIVE

    def archive(self) -> None:
        self.status = BranchStatus.ARCHIVED

    def activate(self) -> None:
        if self.status == BranchStatus.ARCHIVED:
            raise ValueError(f"Cannot activate archived branch '{self.name}'")
        self.status = BranchStatus.ACTIVE


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
    id: str
    server_id: str
    message: str
    manifest: CommitManifest
    author_id: str | None = None
    parent_commit_id: str | None = None
    parent_commit_ids: list[str] = field(default_factory=list)
    world_snapshot_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Commit id cannot be empty")
        if not self.server_id:
            raise ValueError("Commit server_id cannot be empty")
        if not self.parent_commit_ids and self.parent_commit_id:
            self.parent_commit_ids = [self.parent_commit_id]
        elif self.parent_commit_ids and not self.parent_commit_id:
            self.parent_commit_id = self.parent_commit_ids[0]

    def validate_parent(self, parent_commit: ServerCommit | None) -> None:
        if self.parent_commit_id is not None:
            if parent_commit is None:
                raise ValueError(f"Parent commit '{self.parent_commit_id}' not found")
            if parent_commit.server_id != self.server_id:
                raise ValueError("Parent commit belongs to a different server")


Commit = ServerCommit


@dataclass
class Materialization:
    """Represents materialized filesystem state for a specific commit."""

    id: str
    server_id: str
    commit_id: str
    root_path: str
    status: MaterializationStatus = MaterializationStatus.PENDING
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Materialization id cannot be empty")
        if not self.commit_id:
            raise ValueError("Materialization commit_id cannot be empty")
        if not self.root_path:
            raise ValueError("Materialization root_path cannot be empty")
        norm = os.path.normpath(self.root_path).replace("\\", "/")
        if ".." in norm.split("/"):
            raise ValueError(f"Materialization root_path contains path traversal: {self.root_path}")
        if not (norm.startswith(".onx/tests/") or "/.onx/tests/" in norm):
            raise ValueError(f"Materialization root_path must be under .onx/tests/: {self.root_path}")

    @property
    def is_ready(self) -> bool:
        return self.status == MaterializationStatus.READY

    @property
    def is_stale(self) -> bool:
        return self.status == MaterializationStatus.STALE

    @property
    def is_removed(self) -> bool:
        return self.status == MaterializationStatus.REMOVED

    def mark_ready(self) -> None:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot transition removed materialization to ready")
        self.status = MaterializationStatus.READY

    def mark_stale(self) -> None:
        if self.status == MaterializationStatus.REMOVED:
            raise ValueError("Cannot mark removed materialization as stale")
        self.status = MaterializationStatus.STALE

    def mark_removed(self) -> None:
        self.status = MaterializationStatus.REMOVED


@dataclass
class Runtime:
    """Represents a running execution instance bound to an immutable Commit ID.

    SAFETY INVARIANT 1:
    A Runtime MUST be pinned to an immutable Commit ID.
    Never make a Runtime depend directly on a moving Branch reference.
    """

    id: str
    commit_id: str
    materialization_id: str
    provider_type: str = "docker"
    server_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Runtime id cannot be empty")
        if not self.commit_id:
            raise ValueError("Runtime commit_id cannot be empty")
        if not self.materialization_id:
            raise ValueError("Runtime materialization_id cannot be empty")
        if self.commit_id.startswith("branch:") or self.commit_id.startswith("refs/"):
            raise ValueError("Runtime cannot bind directly to a mutable branch reference")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "commit_id" and hasattr(self, "commit_id"):
            raise ValueError("Runtime commit_id is immutable and cannot be changed after creation")
        super().__setattr__(name, value)

    @classmethod
    def create(
        cls,
        id: str,
        commit_id: str,
        materialization: Materialization,
        provider_type: str = "docker",
        server_id: str | None = None,
    ) -> Runtime:
        if materialization.status == MaterializationStatus.REMOVED:
            raise ValueError("Runtime cannot reference a removed Materialization")
        if not commit_id or commit_id.startswith("branch:") or commit_id.startswith("refs/"):
            raise ValueError("Runtime cannot bind directly to a mutable branch reference")
        return cls(
            id=id,
            commit_id=commit_id,
            materialization_id=materialization.id,
            provider_type=provider_type,
            server_id=server_id,
        )


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
    status: TestRunStatus = TestRunStatus.PENDING
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ephemeral_port: int | None = None
    container_id: str | None = None
    failure_reason: str | None = None
    log_output: str | None = None
    bot_count: int = 5
    duration_minutes: int = 15
    placement_mode: PlacementMode = PlacementMode.SIDECAR
    bot_tech: BotTech = BotTech.AUTO

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TestRunStatus.PASSED,
            TestRunStatus.FAILED,
            TestRunStatus.CANCELLED,
        )

    def mark_running(self, ephemeral_port: int | None = None) -> None:
        if self.is_terminal:
            raise ValueError(f"Cannot transition terminal test run ({self.status}) to RUNNING")
        self.status = TestRunStatus.RUNNING
        self.ephemeral_port = ephemeral_port

    def mark_passed(self) -> None:
        self.status = TestRunStatus.PASSED
        self.completed_at = _utcnow()

    def mark_failed(self, reason: str | None = None) -> None:
        self.status = TestRunStatus.FAILED
        self.failure_reason = reason
        self.completed_at = _utcnow()

    def mark_cancelled(self, reason: str = "Cancelled by user") -> None:
        self.status = TestRunStatus.CANCELLED
        self.failure_reason = reason


Run = ServerTestRun
TestRun = ServerTestRun
