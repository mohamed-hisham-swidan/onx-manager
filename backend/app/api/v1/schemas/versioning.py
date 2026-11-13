from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

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
    manifest: dict[str, Any]
    world_snapshot_id: str | None = None
    created_at: str


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
    target_branch_name: str = Field(..., min_length=1, max_length=100)
    parent_commit_ids: list[str] = Field(..., min_length=2)
    message: str = Field(..., min_length=1, max_length=500)
    author_id: str | None = None
    manifest: dict[str, Any] | None = None


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


class PromoteCommitRequest(BaseModel):
    keep_world_changes: bool = False
    force: bool = False
    force_reason: str | None = None


class BotSettingsRequest(BaseModel):
    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None


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
    require_test_pass: bool = Field(
        True, description="Require a passing test run before commit promotion"
    )
    allow_direct_commit: bool = Field(
        False, description="Allow direct commits without test/promotion"
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

