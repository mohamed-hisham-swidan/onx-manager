from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    app_name: str = "mcs-manager"
    version: str = "4.0.0"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True
    database_url: str = "sqlite+aiosqlite:///./mcs.db"
    database_echo: bool = False
    secret_key: str = "change-me-in-production"
    cors_origins: list[str] = ["*"]
    rate_limit_per_minute: int = 60
    idempotency_ttl_hours: int = 24
    circuit_breaker_timeout_seconds: int = 30
    circuit_breaker_max_failures: int = 5
    event_bus_retry_attempts: int = 3
    event_bus_subscriber_timeout: float = 10.0
    saga_timeout_seconds: int = 300
    jwt_private_key: str = ""
    jwt_private_key_path: str = ""
    servers_data_dir: str = "data/servers"
    backup_encryption_key_path: str = ""
    storage_backend: str = "local"
    backup_storage_path: str = "data/backups"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_endpoint_url: str = ""

    model_config = {"env_prefix": "MCS_"}


@dataclass(frozen=True)
class ServerConfig:
    server_id: str
    name: str
    minecraft_version: str = "1.20.4"
    memory_min_mb: int = 1024
    memory_max_mb: int = 2048
    port: int = 25565
    auto_start: bool = False
    auto_restart: bool = True
    backup_enabled: bool = True
    backup_interval_minutes: int = 60
    provider: str = "local"
    java_args: list[str] = field(default_factory=lambda: ["-XX:+UseG1GC"])
    env_vars: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "name": self.name,
            "minecraft_version": self.minecraft_version,
            "memory_min_mb": self.memory_min_mb,
            "memory_max_mb": self.memory_max_mb,
            "port": self.port,
            "auto_start": self.auto_start,
            "auto_restart": self.auto_restart,
            "backup_enabled": self.backup_enabled,
            "backup_interval_minutes": self.backup_interval_minutes,
            "provider": self.provider,
            "java_args": list(self.java_args),
            "env_vars": dict(self.env_vars),
        }


class ConfigFactory:
    @staticmethod
    def global_settings() -> AppSettings:
        return AppSettings()

    @staticmethod
    def for_server(server_id: str, overrides: dict[str, Any] | None = None) -> ServerConfig:
        base = ServerConfig(server_id=server_id, name=server_id)

        config_dir = Path("config") / "servers"
        file_path = config_dir / f"{server_id}.yaml"
        if file_path.exists():
            with open(file_path) as f:
                raw = yaml.safe_load(f) or {}
            base = _merge_config(base, raw)

        env_prefix = f"MCS_SERVER_{server_id.upper().replace('-', '_')}_"
        env_overrides = _read_env_overrides(env_prefix)
        if env_overrides:
            base = _merge_config(base, env_overrides)

        if overrides:
            base = _merge_config(base, overrides)

        return base

    @staticmethod
    def load_file(path: str) -> dict[str, Any]:
        with open(path) as f:
            return yaml.safe_load(f) or {}


def _merge_config(base: ServerConfig, overrides: dict[str, Any]) -> ServerConfig:
    kwargs = {
        "server_id": base.server_id,
        "name": base.name,
        "minecraft_version": base.minecraft_version,
        "memory_min_mb": base.memory_min_mb,
        "memory_max_mb": base.memory_max_mb,
        "port": base.port,
        "auto_start": base.auto_start,
        "auto_restart": base.auto_restart,
        "backup_enabled": base.backup_enabled,
        "backup_interval_minutes": base.backup_interval_minutes,
        "provider": base.provider,
        "java_args": list(base.java_args),
        "env_vars": dict(base.env_vars),
    }
    for key, value in overrides.items():
        if key in kwargs:
            if key == "java_args" and isinstance(value, list):
                kwargs[key] = value
            elif key == "env_vars" and isinstance(value, dict):
                kwargs[key] = value
            else:
                kwargs[key] = value
    return ServerConfig(**kwargs)


def _read_env_overrides(prefix: str) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    type_map = {
        "MEMORY_MIN_MB": int,
        "MEMORY_MAX_MB": int,
        "PORT": int,
        "AUTO_START": _to_bool,
        "AUTO_RESTART": _to_bool,
        "BACKUP_ENABLED": _to_bool,
        "BACKUP_INTERVAL_MINUTES": int,
    }
    for key, converter in type_map.items():
        env_key = f"{prefix}{key}"
        value = os.environ.get(env_key)
        if value is not None:
            target_key = key.lower()
            overrides[target_key] = converter(value)
    return overrides


def _to_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes")
