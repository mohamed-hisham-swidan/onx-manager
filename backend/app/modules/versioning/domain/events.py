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


# --- P5.5 Modpack & 1-Click Safe Upgrade events ---


class ModpackInstalledEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    source: str
    project_id: str
    version_id: str
    version_label: str
    mc_version: str
    loader_id: str
    loader_version: str
    file_count: int = 0
    operation_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradePlannedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    source_mc: str | None = None
    target_mc: str
    target_loader_id: str
    target_loader_version: str
    status: str
    blockers_count: int = 0
    warnings_count: int = 0
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeManualBlockerResolvedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    path: str | None = None
    file_id: int | None = None
    status: str
    remaining_blockers: int = 0
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeBranchPreparedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    branch_name: str
    target_mc: str
    status: str
    commit_sha: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeTestStartedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    branch_name: str
    runtime_id: str
    data_template_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeAppliedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    mode: str
    target_mc: str
    target_loader_id: str
    target_loader_version: str
    journal_id: str | None = None
    pre_upgrade_backup_id: str | None = None
    class_c_snapshot_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeConfirmedEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    target_mc: str
    journal_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class UpgradeRolledBackEvent(DomainEvent):
    server_id: str
    upgrade_id: str
    target_mc: str
    journal_id: str | None = None
    reason: str = ""
    automatic: bool = False
    actor_type: str = "user"
    actor_id: str | None = None


class ServerP55SettingsUpdatedEvent(DomainEvent):
    server_id: str
    health_gate_boot_timeout_seconds: int
    install_optional_server_files: bool
    allow_experimental_paper_builds: bool
    download_host_allowlist: list[str]
    actor_type: str = "user"
    actor_id: str | None = None


# --- Multi-Tab Branch Isolation & Settings Workflow events ---


class BranchDeletedEvent(DomainEvent):
    server_id: str
    branch_name: str
    branch_id: str
    actor_type: str = "user"
    actor_id: str | None = None


class BranchRuntimeCreatedEvent(DomainEvent):
    server_id: str
    branch_name: str
    runtime_id: str
    commit_sha: str
    actor_type: str = "user"
    actor_id: str | None = None


class BranchRuntimeDestroyedEvent(DomainEvent):
    server_id: str
    branch_name: str
    runtime_id: str
    actor_type: str = "user"
    actor_id: str | None = None


class SettingsCommittedEvent(DomainEvent):
    server_id: str
    branch_name: str
    commit_id: str
    message: str
    actor_type: str = "user"
    actor_id: str | None = None


class SettingsBranchCreatedEvent(DomainEvent):
    server_id: str
    branch_name: str
    source_branch: str = "main"
    commit_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None


class SettingsBranchAutoMergedOnRestartEvent(DomainEvent):
    server_id: str
    branch_name: str = "main"
    source_branch: str
    commit_id: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
