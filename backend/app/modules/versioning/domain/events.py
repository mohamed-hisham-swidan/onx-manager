from __future__ import annotations

from app.core.event_bus import DomainEvent


class BranchCreatedEvent(DomainEvent):
    server_id: str
    branch_name: str
    branch_id: str


class BranchArchivedEvent(DomainEvent):
    server_id: str
    branch_name: str
    branch_id: str


class TagCreatedEvent(DomainEvent):
    server_id: str
    tag_name: str
    commit_id: str


class CommitCreatedEvent(DomainEvent):
    server_id: str
    commit_id: str
    message: str
    branch_name: str


class MergeCommitCreatedEvent(DomainEvent):
    server_id: str
    commit_id: str
    parent_commit_ids: list[str]
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


class TestRunFailedEvent(DomainEvent):
    __test__ = False
    server_id: str
    test_id: str
    commit_id: str
    failure_code: str | None = None
    blamed_mod: str | None = None


# DEPRECATED (P3-1): retained for historical event-log deserialization only; never emitted
class CommitPromotedEvent(DomainEvent):
    server_id: str
    commit_id: str
    test_id: str
    keep_world_changes: bool = False
    forced: bool = False
    actor_id: str | None = None
