import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.v1.schemas.common import BaseResponse

VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


class ServerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    server_type: str = Field(default="vanilla")
    minecraft_version: str = Field(default="1.20.4")

    @field_validator("minecraft_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not VERSION_PATTERN.match(v):
            raise ValueError(f"Invalid Minecraft version format: {v!r}")
        return v

    min_memory_mb: int = Field(default=1024, ge=128)
    max_memory_mb: int = Field(default=2048, ge=128)
    port: int = Field(default=25565, ge=1, le=65535)
    motd: str = Field(default="A Minecraft Server")
    max_players: int = Field(default=20, ge=1, le=500)
    gamemode: str = Field(default="survival")
    difficulty: str = Field(default="easy")
    spawn_protection: int = Field(default=16, ge=0)
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = Field(default=10, ge=2, le=32)
    simulation_distance: int = Field(default=10, ge=2, le=32)
    java_args: list[str] | None = None
    group_id: str = Field(default="default")
    install_dir: str | None = None
    provider: str | None = Field(default=None)
    startup_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    mode: str = Field(default="simple")

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("simple", "advanced"):
            raise ValueError(f"Invalid mode: {v!r}. Must be 'simple' or 'advanced'")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if not normalized:
            return None
        if normalized != "docker":
            raise ValueError(
                "Local runtime providers are no longer supported; "
                "'docker' is the only supported runtime provider."
            )
        return "docker"


class ServerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    properties: dict[str, object] = Field(default_factory=dict)
    min_memory_mb: int | None = None
    max_memory_mb: int | None = None
    cpu_cores: int | None = None
    cpu_affinity: str | None = None
    java_args: list[str] | None = None
    startup_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Server name must not be empty")
        if len(trimmed) > 128:
            raise ValueError("Server name must be at most 128 characters")
        return trimmed


class ServerActionRequest(BaseModel):
    reason: str = ""


class ServerResponse(BaseResponse):
    server_id: str
    name: str
    server_type: str
    minecraft_version: str
    status: str
    group_id: str
    port: int
    motd: str
    max_players: int
    gamemode: str
    difficulty: str
    created_at: datetime
    updated_at: datetime
    provisioning_error: str | None = None
    provisioning_retryable: bool = False
    startup_timeout_seconds: int | None = None
    mode: str = "simple"
    max_memory_mb: int | None = None
    cpu_cores: float | None = None
    uptime_seconds: int | None = None
    deployment_host: str | None = None
    public_address: str | None = None
    active_branch: str | None = None
    icon_data_url: str | None = None
    provisioning_progress: dict[str, Any] | None = None


class ServerDetailResponse(ServerResponse):
    min_memory_mb: int
    max_memory_mb: int
    java_args: str
    cpu_cores: int = 0
    cpu_affinity: str = ""
    raw_properties: dict[str, str] = Field(default_factory=dict)
    spawn_protection: int
    pvp: bool
    enable_command_block: bool
    online_mode: bool
    whitelist: bool
    view_distance: int
    simulation_distance: int
    provider: str | None = None
    deployment_host: str | None = None
    deployment_port: int | None = None
    deployment_pid: int | None = None
    location_type: str | None = None
    location_uri: str | None = None
    root_path: str | None = None
    working_directory: str | None = None
    startup_jar: str | None = None
    startup_command: str | None = None
    primary_world: str | None = None
    branch_name: str | None = None
    pending_settings_branch: dict | None = None


class ConsoleResponse(BaseResponse):
    server_id: str
    lines: list[str]


class CrashReportSummaryResponse(BaseResponse):
    filename: str
    timestamp: str
    failure_code: str
    blamed_mod: str | None = None
    stack_trace_snippet: str = ""
    suggested_remediation: str = ""
    raw_content: str = ""


class RuntimeDiagnosticsResponse(BaseResponse):
    server_id: str
    server_name: str = ""
    status: str
    alive: bool
    pid: int | None = None
    provider: str | None = None
    uptime_seconds: float = 0.0
    heartbeat_age_seconds: float | None = None
    startup_duration_seconds: float | None = None
    restart_count: int = 0
    failure_code: str | None = None
    failure_reason: str | None = None
    last_logs: list[str] | None = None
    last_exception: str | None = None
    last_verification_timestamp: float | None = None
    supervised: bool = False
    runtime_handle: str | None = None
    provider_status: str | None = None
    last_crash_time: float | None = None
    port: int | None = None
    port_owner: str | None = None
    tmux_session: str | None = None
    jvm_command: str | None = None
    owner_conflicts: list[dict] = []
    validation_chain: list[str] = []


class RuntimeOwnershipResponse(BaseResponse):
    timestamp: float
    active_servers: list[dict] = []
    orphan_tmux: list[dict] = []
    orphan_processes: list[dict] = []
    stale_db_records: list[dict] = []
    conflicts: list[dict] = []
    localhost_owner: str | None = None
    total_orphans: int = 0


class ClaimLocalhostResponse(BaseResponse):
    success: bool
    actions: list[str] = []
    conflicts_resolved: int = 0


class ValidationChainResponse(BaseResponse):
    server_id: str
    healthy: bool
    chain: list[str] = []


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1)

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        if any(c in v for c in ("\r", "\n", "\0")):
            raise ValueError("Command cannot contain CR, LF or NUL characters")
        return v


class ReconcileRequest(BaseModel):
    scope: str = Field(
        default="project_owned",
        pattern=r"^(project_owned|system_wide)$",
        description=(
            "'project_owned' (default) — only kill processes with positive ownership "
            "marker/cwd inside project data dir. "
            "'system_wide' — kill any managed tmux session or Minecraft Java PID not in DB "
            "(legacy behavior)."
        ),
    )


class ReconciliationResultResponse(BaseResponse):
    imported: list[dict] = []
    updated: list[dict] = []
    deleted: list[dict] = []
    missing: list[dict] = []
    broken: list[dict] = []
    unchanged: list[dict] = []
    ignored: list[dict] = []
    invalid_identity: list[dict] = []
    errors: list[dict] = []
    identity_written: list[dict] = []
    total_imported: int = 0
    total_updated: int = 0
    total_deleted: int = 0
    total_missing: int = 0
    total_broken: int = 0
    total_unchanged: int = 0
    total_ignored: int = 0
    total_invalid_identity: int = 0
    total_errors: int = 0
    total_dirs_found: int = 0
    total_minecraft_dirs: int = 0
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    dry_run: bool = False
