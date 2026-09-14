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


class CreateCommitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    branch_name: str = Field(default="main", min_length=1, max_length=100)
    author_id: str | None = None


class CommitResponse(BaseModel):
    id: str
    server_id: str
    branch_id: str | None = None
    parent_commit_id: str | None = None
    author_id: str | None = None
    message: str
    manifest: dict[str, Any]
    world_snapshot_id: str | None = None
    created_at: str


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
