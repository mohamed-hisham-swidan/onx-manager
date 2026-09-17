from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateBranchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    head_commit_id: str | None = None


class BranchResponse(BaseModel):
    id: str
    server_id: str
    name: str
    head_commit_id: str | None = None
    created_at: str
    status: str = "created"


class CreateCommitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    branch_name: str = Field(default="main", min_length=1, max_length=100)
    author_id: str | None = None


class CommitResponse(BaseModel):
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


class TagResponse(BaseModel):
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


class DiffResponse(BaseModel):
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


class TestRunResponse(BaseModel):
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


class PromoteCommitRequest(BaseModel):
    keep_world_changes: bool = False
    force: bool = False
    force_reason: str | None = None


class BotSettingsRequest(BaseModel):
    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None


class BotSettingsResponse(BaseModel):
    server_id: str
    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None
    effective_bot_count: int
    effective_duration_minutes: int
    effective_bot_tech: str
    effective_placement_mode: str


class PreflightResponse(BaseModel):
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


class MaterializationCreateResponse(BaseModel):
    materialization_id: str
    revision: str
    mode: str
    status: str
    root: str


class MaterializationListItemResponse(BaseModel):
    id: str
    revision: str
    mode: str
    status: str
    stale: bool
    created_at: str


class MaterializationTreeEntry(BaseModel):
    path: str
    classification: str
    size_bytes: int
    origin: str


class MaterializationTreeResponse(BaseModel):
    entries: list[MaterializationTreeEntry]


class MaterializationFileResponse(BaseModel):
    content: str
    encoding: str
    path: str
    size_bytes: int


class SetEditModeRequest(BaseModel):
    enabled: bool


class SetEditModeResponse(BaseModel):
    mode: str


class WriteMaterializedFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str


class WriteMaterializedFileResponse(BaseModel):
    path: str
    bytes_written: int


class ScanLiveChangesRequest(BaseModel):
    source: str = Field(..., min_length=1)


class LiveChangeEntry(BaseModel):
    path: str
    change: str
    classification: str


class ScanLiveChangesResponse(BaseModel):
    changes: list[LiveChangeEntry]
    auto_commit: str | None = None


class AutoCommitLiveChangesRequest(BaseModel):
    branch: str = Field(default="main", min_length=1)


class AutoCommitLiveChangesResponse(BaseModel):
    commit_id: str | None = None
    review_id: str | None = None
    changes: list[LiveChangeEntry] = Field(default_factory=list)


class ImportReviewActionResponse(BaseModel):
    status: str
    revert_commit_id: str | None = None

