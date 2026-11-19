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


class BranchRuntimeStartedEvent(DomainEvent):
    server_id: str
    branch_name: str
    runtime_id: str
    commit_sha: str
    data_template_id: str | None = None
    allow_public_test_join: bool = False
    actor_type: str = "user"
    actor_id: str | None = None


class BranchRuntimeStoppedEvent(DomainEvent):
    server_id: str
    branch_name: str
    runtime_id: str
    exit_code: int | None = None
    oom_killed: bool = False
    saved_template_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class DataTemplateSavedEvent(DomainEvent):
    server_id: str
    template_id: str
    template_name: str
    branch_name: str | None = None
    commit_sha: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


# DEPRECATED (P3-1): retained for historical event-log deserialization only; never emitted
class CommitPromotedEvent(DomainEvent):
    server_id: str
    commit_id: str
    test_id: str
    keep_world_changes: bool = False
    forced: bool = False
    actor_id: str | None = None


# --- P5 GitHub sync events (never carry raw secrets or HMAC digests) ---


class GitHubConnectedEvent(DomainEvent):
    server_id: str
    remote_url: str
    auth_method: str
    webhook_enabled: bool = False
    remote_default_branch: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class GitHubDisconnectedEvent(DomainEvent):
    server_id: str
    remote_url: str
    local_history_preserved: bool = True
    actor_type: str = "user"
    actor_id: str | None = None


class GitHubCredentialsRotatedEvent(DomainEvent):
    server_id: str
    auth_method: str
    credential_rotated: bool = False
    webhook_secret_rotated: bool = False
    webhook_enabled: bool = False
    actor_type: str = "user"
    actor_id: str | None = None


class GitHubSyncedEvent(DomainEvent):
    server_id: str
    sync_status: str
    trigger: str = "manual"
    main_fast_forwarded: bool = False
    previous_main_sha: str | None = None
    main_sha: str | None = None
    remote_head_sha: str | None = None
    branch_name: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None


class GitHubPushedEvent(DomainEvent):
    server_id: str
    branch_name: str
    commit_sha: str
    remote_url: str
    actor_type: str = "user"
    actor_id: str | None = None


class GitHubWebhookReceivedEvent(DomainEvent):
    server_id: str
    delivery_id: str
    webhook_event: str = ""
    ref: str | None = None
    deduplicated: bool = False
    redelivered: bool = False
    operation_id: str | None = None
    actor_type: str = "webhook"
    actor_id: str | None = None
