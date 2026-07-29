from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator


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


class ServerUpdateRequest(BaseModel):
    properties: dict[str, object] = {}
    min_memory_mb: int | None = None
    max_memory_mb: int | None = None


class ServerActionRequest(BaseModel):
    reason: str = ""


class ServerResponse(BaseModel):
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


class ServerDetailResponse(ServerResponse):
    min_memory_mb: int
    max_memory_mb: int
    java_args: str
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


class ConsoleResponse(BaseModel):
    server_id: str
    lines: list[str]


class RuntimeDiagnosticsResponse(BaseModel):
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


class RuntimeOwnershipResponse(BaseModel):
    timestamp: float
    active_servers: list[dict] = []
    orphan_tmux: list[dict] = []
    orphan_processes: list[dict] = []
    stale_db_records: list[dict] = []
    conflicts: list[dict] = []
    localhost_owner: str | None = None
    total_orphans: int = 0


class ClaimLocalhostResponse(BaseModel):
    success: bool
    actions: list[str] = []
    conflicts_resolved: int = 0


class ValidationChainResponse(BaseModel):
    server_id: str
    healthy: bool
    chain: list[str] = []


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1)


class ReconciliationResultResponse(BaseModel):
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