from __future__ import annotations

from app.core.event_bus import DomainEvent


class BranchCreatedEvent(DomainEvent):
    server_id: str
    branch_name: str
    branch_id: str


class CommitCreatedEvent(DomainEvent):
    server_id: str
    commit_id: str
    message: str
    branch_name: str


class TestRunStartedEvent(DomainEvent):
    __test__ = False
    server_id: str
    test_id: str
    commit_id: str
    bot_count: int
    duration_minutes: int


class TestRunCompletedEvent(DomainEvent):
    __test__ = False
    server_id: str
    test_id: str
    commit_id: str
    passed: bool
    failure_reason: str | None = None


class CommitPromotedEvent(DomainEvent):
    server_id: str
    commit_id: str
    test_id: str
    keep_world_changes: bool = False
