from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.v1.schemas.common import BaseResponse


class CreateBranchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    head_commit_id: str | None = None


class BranchResponse(BaseResponse):
    id: str
    server_id: str
    name: str
    head_commit_id: str | None = None
    created_at: str
    status: str = "created"
    is_protected: bool = False
    protection_policy: dict[str, Any] | None = None
    worktree_path: str | None = None
    worktree_locked: bool = False
    runtime_status: str = "stopped"
    port_set: dict[str, Any] | None = None
    active_runtime_id: str | None = None
    active_commit_sha: str | None = None
    active_data_template_id: str | None = None
    worktree_lock_reason: str | None = None


class CreateCommitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    branch_name: str = Field(default="main", min_length=1, max_length=100)
    author_id: str | None = None
    force: bool = False
    force_reason: str | None = None


class CommitResponse(BaseResponse):
    id: str
    server_id: str
    branch_id: str | None = None
    parent_commit_id: str | None = None
    parent_commit_ids: list[str] = Field(default_factory=list)
    author_id: str | None = None
    message: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    world_snapshot_id: str | None = None
    created_at: str
    snapshot_hash: str | None = None
    changes_summary: dict[str, Any] | None = None
    warnings: list[Any] = Field(default_factory=list)
    noop: bool = False


class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    commit_id: str = Field(..., min_length=1)


class TagResponse(BaseResponse):
    id: str
    server_id: str
    name: str
    commit_id: str
    created_at: str


class MergeCommitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_branch_name: str = Field(..., min_length=1, max_length=100)
    parent_commit_ids: list[str] = Field(default_factory=list)
    source_branch_name: str | None = Field(default=None, min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=500)
    author_id: str | None = None
    manifest: dict[str, Any] | None = None
    force: bool = False
    force_reason: str | None = None
    force_bypass_protection: bool = False

    @model_validator(mode="after")
    def _normalize_parents(self) -> MergeCommitsRequest:
        if not self.parent_commit_ids and self.source_branch_name:
            self.parent_commit_ids = [self.target_branch_name, self.source_branch_name]
        if len(self.parent_commit_ids) < 2:
            raise ValueError("At least 2 parent_commit_ids or source_branch_name must be provided")
        return self


class DiffResponse(BaseResponse):
    from_commit_id: str
    to_commit_id: str
    has_changes: bool
    server_type: dict[str, str] | None = None
    minecraft_version: dict[str, str] | None = None
    java_args: dict[str, str] | None = None
    configs: dict[str, Any]
    env_vars: dict[str, Any]
    mods: dict[str, Any]


class RunIsolatedTestRequest(BaseModel):
    commit_id: str | None = None
    bot_count: int | None = None
    duration_minutes: int | None = None
    placement_mode: str | None = None
    bot_tech: str | None = None
    test_definition_id: str | None = None


class TestRunResponse(BaseResponse):
    id: str
    server_id: str
    commit_id: str
    node_id: str
    status: str
    ephemeral_port: int | None = None
    log_output: str | None = None
    failure_reason: str | None = None
    created_at: str
    expires_at: str | None = None
    bot_count: int
    duration_minutes: int
    placement_mode: str
    bot_tech: str
    runtime_id: str | None = None
    test_definition_id: str | None = None
    artifacts_purged: bool = False
    evidence_bundle: dict[str, Any] | None = None
    reserved_ram_mb: int | None = None
    reserved_cores: int | None = None
    operation_id: str | None = None


class TestDefinitionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    server_type: str = Field(default="vanilla", min_length=1, max_length=50)
    bot_technology: str = Field(default="mineflayer")
    bot_count: int = Field(default=5, ge=0, le=100)
    duration_seconds: int = Field(default=60, ge=10, le=3600)
    join_stagger_seconds: float = Field(default=1.0, ge=0.0)
    connect_grace_seconds: int = Field(default=20, ge=0)
    placement_mode: str = Field(default="sidecar")
    assertion_rules: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=30, le=7200)

    @field_validator("assertion_rules")
    @classmethod
    def validate_assertion_rules(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v:
            from app.modules.versioning.domain.value_objects import AssertionRulesConfig

            AssertionRulesConfig.from_dict(v)
        return v


class TestDefinitionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    server_type: str | None = Field(default=None, min_length=1, max_length=50)
    bot_technology: str | None = None
    bot_count: int | None = Field(default=None, ge=0, le=100)
    duration_seconds: int | None = Field(default=None, ge=10, le=3600)
    join_stagger_seconds: float | None = Field(default=None, ge=0.0)
    connect_grace_seconds: int | None = Field(default=None, ge=0)
    placement_mode: str | None = None
    assertion_rules: dict[str, Any] | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)

    @field_validator("assertion_rules")
    @classmethod
    def validate_assertion_rules(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None:
            from app.modules.versioning.domain.value_objects import AssertionRulesConfig

            AssertionRulesConfig.from_dict(v)
        return v


class TestDefinitionResponse(BaseResponse):
    id: str
    server_id: str
    name: str
    description: str = ""
    server_type: str = "vanilla"
    bot_technology: str = "mineflayer"
    bot_count: int = 5
    duration_seconds: int = 60
    join_stagger_seconds: float = 1.0
    connect_grace_seconds: int = 20
    placement_mode: str = "sidecar"
    assertion_rules: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300
    created_at: str
    updated_at: str


class EvidenceBundleResponse(BaseResponse):
    test_id: str
    server_id: str
    commit_id: str
    runtime: dict[str, Any] = Field(default_factory=dict)
    assertions: dict[str, Any] = Field(default_factory=dict)
    crash_analysis: dict[str, Any] = Field(default_factory=dict)
    log_tail: list[str] = Field(default_factory=list)


class BotSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None
    previous_tree_retention: str | int | None = None


class BotSettingsResponse(BaseResponse):
    server_id: str
    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None
    effective_bot_count: int
    effective_duration_minutes: int
    effective_bot_tech: str
    effective_placement_mode: str
    previous_tree_retention: str = "until_health_gate"


class PreflightResponse(BaseResponse):
    reflink_supported: bool
    available_ram_mb: int
    available_cores: int
    min_required_ram_mb: int
    min_required_cores: int
    passed: bool
    error: str | None = None


# --- Stage C Schemas ---


class CreateMaterializationRequest(BaseModel):
    revision_type: str = Field(..., pattern="^(commit|branch|tag)$")
    ref: str = Field(..., min_length=1)
    mode: str = Field(default="readonly", pattern="^(readonly|editable)$")


class MaterializationCreateResponse(BaseResponse):
    materialization_id: str
    revision: str
    mode: str
    status: str
    root: str


class MaterializationListItemResponse(BaseResponse):
    id: str
    revision: str
    mode: str
    status: str
    stale: bool
    created_at: str


class MaterializationTreeEntry(BaseResponse):
    path: str
    classification: str
    size_bytes: int
    origin: str


class MaterializationTreeResponse(BaseResponse):
    entries: list[MaterializationTreeEntry]


class MaterializationFileResponse(BaseResponse):
    content: str
    encoding: str
    path: str
    size_bytes: int


class SetEditModeRequest(BaseModel):
    enabled: bool


class SetEditModeResponse(BaseResponse):
    mode: str


class WriteMaterializedFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str


class WriteMaterializedFileResponse(BaseResponse):
    path: str
    bytes_written: int


class ScanLiveChangesRequest(BaseModel):
    source: str = Field(..., min_length=1)


class LiveChangeEntry(BaseResponse):
    path: str
    change: str
    classification: str


class ScanLiveChangesResponse(BaseResponse):
    changes: list[LiveChangeEntry]
    auto_commit: str | None = None


class AutoCommitLiveChangesRequest(BaseModel):
    branch: str = Field(default="main", min_length=1)


class AutoCommitLiveChangesResponse(BaseResponse):
    commit_id: str | None = None
    review_id: str | None = None
    changes: list[LiveChangeEntry] = Field(default_factory=list)


class ImportReviewActionResponse(BaseResponse):
    status: str
    revert_commit_id: str | None = None


class BranchProtectionPolicySchema(BaseResponse):
    require_test_pass: bool = Field(True, description="Require a passing test run before merging")
    allow_direct_commit: bool = Field(
        False, description="Allow direct commits without testing or merging"
    )
    allow_force_bypass: bool = Field(
        True, description="Allow admins with bypass permission to force commit"
    )
    prevent_deletion: bool = Field(True, description="Prevent branch archival or deletion")


class SetBranchProtectionRequest(BaseModel):
    policy: BranchProtectionPolicySchema | None = None


class BranchProtectionResponse(BaseResponse):
    server_id: str
    branch_name: str
    is_protected: bool
    policy: BranchProtectionPolicySchema | None = None


# --- P3-4 Batch B schemas ---


class RefreshJournalSummaryResponse(BaseModel):
    journal_id: str
    server_id: str
    phase: str
    terminal: bool
    target_main_sha: str
    previous_main_sha: str
    class_c_snapshot_id: str | None = None
    class_c_Manifest_sha256: str | None = None  # noqa: N815
    previous_dir: str | None = None
    retention_policy: str
    retain_until: datetime | None = None
    rollback_reason: str | None = None
    error_detail: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RefreshStateResponse(BaseModel):
    server_id: str
    active_journal: RefreshJournalSummaryResponse | None = None
    latest_journal: RefreshJournalSummaryResponse | None = None
    can_confirm_upgrade: bool = False
    can_rollback: bool = False
    previous_tree_retention: str = "until_health_gate"


class RefreshServerHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_main_sha: str | None = Field(default=None, min_length=1, max_length=64)
    retention_policy: str | int | None = None
    stop_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    health_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)


class RefreshServerResponse(BaseModel):
    server_id: str
    journal_id: str | None = None
    phase: str | None = None
    status: str = "ok"


class RollbackRefreshHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_id: str | None = None
    reason: str = Field(default="operator_requested", min_length=1, max_length=500)
    stop_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    health_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)


class RollbackRefreshResponse(BaseModel):
    server_id: str
    journal_id: str | None = None
    phase: str | None = None
    status: str = "ok"


class ConfirmUpgradeHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_id: str | None = None


class ConfirmUpgradeResponse(BaseModel):
    server_id: str
    journal_id: str | None = None
    phase: str | None = None
    status: str = "ok"


class CreateClassCSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pinned: bool = False


class ClassCSnapshotResponse(BaseModel):
    snapshot_id: str
    server_id: str
    created_at: str | None = None
    manifest_sha256: str | None = None
    pinned: bool = False
    entry_count: int = 0
    archive_size_bytes: int = 0


class ClassCSnapshotRestoreResponse(BaseModel):
    status: str = "restored"
    server_id: str
    snapshot_id: str


class ClassCSnapshotDeleteResponse(BaseModel):
    status: str = "deleted"
    server_id: str
    snapshot_id: str


class DynamicClassCEntryResponse(BaseModel):
    server_id: str
    relpath: str
    promoted_at: str | None = None
    main_commit_sha: str | None = None
    ast_Node_summary: Any = None  # noqa: N815


class DynamicClassCResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)


class DynamicClassCResetResponse(BaseModel):
    server_id: str
    path: str
    reset: bool


class SecretMetadataResponse(BaseModel):
    server_id: str
    key_name: str
    placeholder: str
    kek_version: int
    created_at: str | None = None
    updated_at: str | None = None


class ExtractSecretHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch: str = Field(..., min_length=1, max_length=100)
    path: str = Field(..., min_length=1)
    key_name: str = Field(..., min_length=1, max_length=128)
    secret_value: str = Field(..., min_length=1)


class ExtractSecretResponse(BaseModel):
    server_id: str
    branch: str
    path: str
    key_name: str
    placeholder: str
    replaced_occurrences: int
    remaining_findings: list[dict[str, Any]] = Field(default_factory=list)


class DeleteSecretResponse(BaseModel):
    server_id: str
    key_name: str
    status: str = "deleted"


# --- P4-3 schemas ---

class DataTemplateResponse(BaseResponse):
    id: str
    server_id: str
    name: str
    description: str = ""
    source_branch_name: str | None = None
    source_commit_sha: str | None = None
    file_count: int = 0
    total_bytes: int = 0
    status: str = "ready"
    operation_id: str | None = None
    created_at: str
    updated_at: str


class CreateDataTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    source: str = Field(default="live", pattern="^(live|branch)$")
    branch_name: str | None = Field(default=None, min_length=1, max_length=100)
    async_mode: bool = Field(default=False)


class DeleteDataTemplateResponse(BaseResponse):
    status: str = "deleted"
    server_id: str
    template_id: str


class PortSetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_port: int = Field(..., ge=1024, le=65535)
    rcon_port: int = Field(..., ge=1024, le=65535)
    query_port: int | None = Field(default=None, ge=1024, le=65535)
    plugin_ports: dict[str, int] = Field(default_factory=dict)
    container_game_port: int = Field(default=25565)
    container_rcon_port: int = Field(default=25575)


class AllocatePortSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_query: bool = False
    plugin_port_names: list[str] = Field(default_factory=list, max_length=16)
    check_os_ports: bool = True


class BranchPortSetResponse(BaseResponse):
    server_id: str
    branch_name: str
    port_set: PortSetSchema


class SetPortSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_port: int = Field(..., ge=1024, le=65535)
    rcon_port: int = Field(..., ge=1024, le=65535)
    query_port: int | None = Field(default=None, ge=1024, le=65535)
    plugin_ports: dict[str, int] = Field(default_factory=dict)
    check_os_ports: bool = True


class BranchRuntimeStatusResponse(BaseResponse):
    server_id: str
    branch_name: str
    runtime_status: str = "stopped"
    runtime_id: str | None = None
    active_commit_sha: str | None = None
    data_template_id: str | None = None
    allow_public_test_join: bool = False
    container_liveness: bool | None = None
    port_set: PortSetSchema | None = None
    worktree_locked: bool = False
    worktree_lock_reason: str | None = None


class StartBranchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_sha: str | None = Field(default=None, min_length=4, max_length=64)
    data_template_id: str | None = Field(default=None, min_length=1, max_length=64)
    allow_public_test_join: bool = False
    port_set: PortSetSchema | None = None
    include_query: bool = False
    plugin_port_names: list[str] = Field(default_factory=list, max_length=16)
    requested_memory_mb: int | None = Field(default=None, ge=256, le=262144)
    requested_cpu_cores: int | None = Field(default=None, ge=1, le=256)
    check_os_ports: bool = True


class StartBranchRunResponse(BaseResponse):
    runtime_id: str
    server_id: str
    branch_name: str
    commit_sha: str
    container_name: str
    container_id: str
    port_set: PortSetSchema
    data_template_id: str | None = None
    allow_public_test_join: bool = False
    uncommitted_changes_warning: bool = False
    memory_max_mb: int
    cpu_cores: int


class StopBranchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: str | None = Field(default=None, min_length=1, max_length=64)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    keep_port_assignment: bool = False
    save_template_name: str | None = Field(default=None, min_length=1, max_length=100)
    save_template_description: str = Field(default="", max_length=500)


class StopBranchRunResponse(BaseResponse):
    runtime_id: str
    server_id: str
    branch_name: str
    status: str = "stopped"
    exit_code: int | None = None
    oom_killed: bool = False
    saved_template_id: str | None = None
    saved_template_name: str | None = None


class SaveBranchDataTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    runtime_id: str | None = Field(default=None, min_length=1, max_length=64)


class BranchConsoleLogsResponse(BaseResponse):
    server_id: str
    branch_name: str
    runtime_id: str
    container_name: str
    lines: list[str]


class BranchConsoleCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(..., min_length=1, max_length=1000)


class BranchConsoleCommandResponse(BaseResponse):
    server_id: str
    branch_name: str
    runtime_id: str
    command: str
    output: str


# --- P5-3 GitHub sync schemas ---


class GenerateGitHubDeployKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, min_length=1, max_length=128)


class ConnectGitHubRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remote_url: str = Field(..., min_length=1, max_length=512)
    auth_method: Literal["pat", "ssh_deploy_key"]
    credential_secret: str = Field(..., min_length=1, max_length=16384)
    deploy_public_key: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_secret: str | None = Field(default=None, min_length=16, max_length=512)
    enable_webhook: bool = False


class RotateGitHubCredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_secret: str | None = Field(default=None, min_length=1, max_length=16384)
    auth_method: Literal["pat", "ssh_deploy_key"] | None = None
    deploy_public_key: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_secret: str | None = Field(default=None, min_length=16, max_length=512)
    enable_webhook: bool | None = None
    regenerate_webhook_secret: bool = False
    disable_webhook: bool = False

    @model_validator(mode="after")
    def _validate_rotation_action(self) -> RotateGitHubCredentialsRequest:
        has_action = (
            self.credential_secret is not None
            or self.auth_method is not None
            or self.deploy_public_key is not None
            or self.webhook_secret is not None
            or self.enable_webhook is not None
            or self.regenerate_webhook_secret
            or self.disable_webhook
        )
        if not has_action:
            raise ValueError(
                "At least one GitHub credential or webhook rotation action is required"
            )
        if self.disable_webhook and (
            self.webhook_secret is not None
            or self.regenerate_webhook_secret
            or self.enable_webhook is True
        ):
            raise ValueError(
                "disable_webhook cannot be combined with enabling or rotating a webhook secret"
            )
        return self


class PushGitHubBranchRequest(BaseModel):
    """Push a branch to GitHub. Force-push is deliberately absent and forbidden."""

    model_config = ConfigDict(extra="forbid")

    branch_name: str = Field(default="main", min_length=1, max_length=128)


class GenerateGitHubDeployKeyResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    public_key_openssh: str
    private_key_pem: str
    fingerprint_sha256: str


class GitHubBranchSyncStateResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    branch: str
    status: Literal["synced", "ahead", "behind", "diverged", "local_only", "remote_only"]
    local_sha: str | None = None
    remote_sha: str | None = None
    ahead_count: int = 0
    behind_count: int = 0


class GitHubConnectionStatusResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    connected: bool
    remote_url: str | None = None
    auth_method: str | None = None
    credential_hint: str | None = None
    deploy_public_key: str | None = None
    webhook_enabled: bool = False
    webhook_path: str | None = None
    sync_status: str = "disconnected"
    needs_reauth: bool = False
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_fetch_at: datetime | None = None
    last_push_at: datetime | None = None
    remote_default_branch: str | None = None
    remote_head_sha: str | None = None
    branches: list[GitHubBranchSyncStateResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    generated_webhook_secret: str | None = None


class GitHubDisconnectResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    disconnected: bool
    remote_url: str
    local_history_preserved: bool = True
    purged_deliveries: int = 0


class GitHubSyncResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    sync_status: str
    trigger: str
    main_fast_forwarded: bool
    previous_main_sha: str | None = None
    main_sha: str | None = None
    remote_default_branch: str | None = None
    remote_head_sha: str | None = None
    branches: list[GitHubBranchSyncStateResponse] = Field(default_factory=list)
    fetched_at: datetime


class GitHubPushResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    branch_name: str
    commit_sha: str
    remote_url: str
    sync_status: str
    branches: list[GitHubBranchSyncStateResponse] = Field(default_factory=list)
    pushed_at: datetime


class GitHubWebhookIngestResponse(BaseResponse):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    delivery_id: str
    event_type: str
    status: Literal["queued", "deduplicated", "ignored"]
    deduplicated: bool = False
    redelivered: bool = False
    redelivery_count: int = 0
    operation_id: str | None = None
    received_at: datetime | None = None


class GitHubWebhookDeliveryResponse(BaseResponse):
    """Secret-free delivery ledger row (deliberately omits raw_payload)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    server_id: str
    delivery_id: str
    event_type: str
    ref: str | None = None
    before_sha: str | None = None
    after_sha: str | None = None
    payload_sha256: str
    signature_valid: bool
    status: str
    operation_id: str | None = None
    error_message: str | None = None
    redelivery_count: int = 0
    received_at: datetime
    processed_at: datetime | None = None
