"""Pydantic schemas for P5.5 Modpacks, 1-Click Safe Upgrades, LEC, and CurseForge integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.v1.schemas.common import BaseResponse
from app.api.v1.schemas.versioning import StartBranchRunResponse
from app.core.allowlist import validate_canonical_relpath
from app.core.exceptions import UntrustedDownloadHostError, ValidationError
from app.modules.versioning.domain.lockfile import parse_lec_key
from app.modules.versioning.infrastructure.download_allowlist import normalize_allowed_host


def _validate_and_normalize_lec_key(raw_key: str) -> str:
    try:
        norm = validate_canonical_relpath(raw_key)
        parse_lec_key(norm)
    except (ValueError, ValidationError) as exc:
        raise ValueError(str(exc)) from exc
    return norm


class CurseForgeIntegrationKeySetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_key must not be blank")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in stripped):
            raise ValueError("api_key must not contain control characters")
        return stripped


class CurseForgeIntegrationStatusResponse(BaseResponse):
    configured: bool
    source: Literal["panel", "env", "none"]
    hint: str | None = None


class LecEntryResponse(BaseResponse):
    lec_key: str
    loader_id: str
    mc_version: str
    loader_version: str
    installer_version: str | None = None
    java_major: int | None = None
    status: str
    size_bytes: int
    file_count: int
    complete_manifest_sha256: str | None = None
    ready_on_disk: bool = False
    last_used_at: datetime | None = None
    updated_at: datetime | None = None


class LecPrewarmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lec_key: str | None = Field(default=None, min_length=3, max_length=256)
    loader_id: Literal["fabric", "quilt", "forge", "neoforge", "paper", "purpur"] | None = None
    mc_version: str | None = Field(default=None, min_length=1, max_length=32)
    loader_version: str | None = Field(default=None, min_length=1, max_length=64)
    installer_version: str | None = Field(default=None, min_length=1, max_length=64)
    async_mode: bool = False

    @model_validator(mode="after")
    def _validate_lec_selector(self) -> LecPrewarmRequest:
        if self.lec_key is not None:
            norm = _validate_and_normalize_lec_key(self.lec_key)
            parts = parse_lec_key(norm)
            self.lec_key = norm
            self.loader_id = parts.loader  # type: ignore[assignment]
            self.mc_version = parts.mc
            self.loader_version = parts.version
            self.installer_version = parts.installer
            return self

        if not self.loader_id or not self.mc_version or not self.loader_version:
            raise ValueError(
                "Provide either lec_key or (loader_id, mc_version, loader_version)"
            )
        if self.loader_id == "fabric":
            if not self.installer_version:
                raise ValueError(
                    "installer_version is required when loader_id is 'fabric'"
                )
            raw = (
                f"fabric/{self.mc_version}/{self.loader_version}/{self.installer_version}"
            )
        else:
            raw = f"{self.loader_id}/{self.mc_version}/{self.loader_version}"
        self.lec_key = _validate_and_normalize_lec_key(raw)
        return self


class LecPrewarmResponse(BaseResponse):
    lec_key: str
    status: str
    file_count: int = 0
    total_bytes: int = 0
    java_major: int | None = None
    unix_args_relpath: str | None = None
    operation_id: str | None = None


class LecGcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_age_days: int = Field(default=7, ge=0, le=3650)


class LecGcResponse(BaseResponse):
    pruned_lec_keys: list[str]
    pruned_cas_digests: list[str]
    freed_bytes: int


class ServerP55SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health_gate_boot_timeout_seconds: int | None = Field(default=None, ge=300, le=900)
    install_optional_server_files: bool | None = None
    allow_experimental_paper_builds: bool | None = None
    download_host_allowlist: list[str] | None = Field(default=None, max_length=64)

    @field_validator("download_host_allowlist")
    @classmethod
    def _validate_allowlist(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            try:
                host = normalize_allowed_host(raw)
            except UntrustedDownloadHostError as exc:
                raise ValueError(str(exc)) from exc
            if host not in seen:
                seen.add(host)
                normalized.append(host)
        return normalized


class ServerP55SettingsResponse(BaseResponse):
    server_id: str
    health_gate_boot_timeout_seconds: int
    install_optional_server_files: bool
    allow_experimental_paper_builds: bool
    download_host_allowlist: list[str]
    default_allowed_hosts: list[str]


class ModpackInspectResponse(BaseResponse):
    server_id: str
    staged_pack_id: str
    source: str
    mc_version: str
    loader_id: str
    loader_version: str
    has_unresolved_blockers: bool
    plan: dict[str, Any]


class ModpackInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staged_pack_id: str = Field(..., min_length=1, max_length=64)
    lec_key: str | None = Field(default=None, min_length=3, max_length=256)
    build_lec: bool = False
    fabric_installer_version: str = Field(default="1.0.1", min_length=1, max_length=64)
    async_mode: bool = False

    @field_validator("lec_key")
    @classmethod
    def _validate_lec_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_and_normalize_lec_key(value)


class ModpackInstallResponse(BaseResponse):
    server_id: str
    upgrade_id: str
    status: str
    mc_version: str
    loader_id: str
    loader_version: str
    lec_key: str | None = None
    files_installed: int = 0
    base_overrides_count: int = 0
    commit_sha: str | None = None
    operation_id: str | None = None


class PlanUpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_mc: str = Field(..., min_length=1, max_length=32)
    target_loader_id: Literal["fabric", "quilt", "forge", "neoforge", "paper", "purpur"]
    target_loader_version: str = Field(..., min_length=1, max_length=64)
    target_lec_key: str | None = Field(default=None, min_length=3, max_length=256)
    staged_pack_id: str | None = Field(default=None, min_length=1, max_length=64)
    excluded_paths: list[str] = Field(default_factory=list, max_length=500)
    keep_paths: list[str] = Field(default_factory=list, max_length=500)
    version_types: list[Literal["release", "beta", "alpha"]] = Field(
        default_factory=lambda: ["release"], min_length=1, max_length=3
    )
    verify_public_network: bool | None = None

    @field_validator("target_lec_key")
    @classmethod
    def _validate_target_lec_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_and_normalize_lec_key(value)


class PrepareUpgradeTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_slug: str | None = Field(default=None, min_length=1, max_length=64)
    resolved_conflicts: dict[str, str] = Field(default_factory=dict)
    start_test: bool = True
    allow_public_test_join: bool = False
    requested_memory_mb: int | None = Field(default=None, ge=256, le=262144)
    requested_cpu_cores: int | None = Field(default=None, ge=1, le=256)
    check_os_ports: bool = True


class ApplyUpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_conflicts: dict[str, str] = Field(default_factory=dict)
    async_mode: bool = False
    verify_public_network: bool | None = None


class RollbackUpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        default="operator emergency rollback", min_length=1, max_length=500
    )


class ServerUpgradeResponse(BaseResponse):
    id: str
    server_id: str
    kind: str
    mode: str
    status: str
    source_mc: str | None = None
    target_mc: str
    source_loader_id: str | None = None
    source_loader_version: str | None = None
    target_loader_id: str
    target_loader_version: str
    target_lec_key: str | None = None
    upgrade_branch: str | None = None
    operation_id: str | None = None
    journal_id: str | None = None
    previous_main_sha: str | None = None
    target_main_sha: str | None = None
    pre_upgrade_backup_id: str | None = None
    class_c_snapshot_id: str | None = None
    data_template_id: str | None = None
    plan: dict[str, Any] | None = None
    matrix: dict[str, Any] | None = None
    manual_blockers: list[dict[str, Any]] | None = None
    pinned_until_confirm: bool = False
    health_gate_passed: bool = False
    reminder_72h_overdue: bool = False
    error_code: str | None = None
    error_message: str | None = None
    confirmed_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ServerUpgradeListResponse(BaseResponse):
    server_id: str
    items: list[ServerUpgradeResponse]
    active_upgrade: ServerUpgradeResponse | None = None
    banner_active: bool = False
    reminder_72h_overdue: bool = False


class PrepareUpgradeTestResponse(BaseResponse):
    upgrade: ServerUpgradeResponse
    runtime: StartBranchRunResponse | None = None
