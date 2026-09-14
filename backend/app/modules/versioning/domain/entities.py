from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.modules.versioning.domain.value_objects import (
    BotTech,
    CommitManifest,
    PlacementMode,
    TestRunStatus,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ServerBranch:
    id: str
    server_id: str
    name: str
    head_commit_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


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
    branch_id: str | None = None
    parent_commit_id: str | None = None
    author_id: str | None = None
    world_snapshot_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class ServerTestRun:
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

    def mark_running(self, ephemeral_port: int | None = None) -> None:
        self.status = TestRunStatus.RUNNING
        self.ephemeral_port = ephemeral_port

    def mark_passed(self, log_output: str | None = None) -> None:
        self.status = TestRunStatus.PASSED
        if log_output:
            self.log_output = log_output

    def mark_failed(self, reason: str, log_output: str | None = None) -> None:
        self.status = TestRunStatus.FAILED
        self.failure_reason = reason
        if log_output:
            self.log_output = log_output

    def mark_cancelled(self, reason: str = "Cancelled by user") -> None:
        self.status = TestRunStatus.CANCELLED
        self.failure_reason = reason
