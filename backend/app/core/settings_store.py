"""Live settings store.

Provides a single in-process mutable instance of the persisted settings.
On startup, :func:`init_settings_store` loads from ``config/settings.yaml``
(if it exists), falling back to env-var/default values.  All code that
previously called ``ConfigFactory.global_settings()`` to read the 12 user-
facing settings fields should call :func:`get_live_settings` instead.

The store is intentionally separate from ``AppSettings`` (which remains
read-only/env-var backed) so that the non-editable infrastructure fields
(secret_key, database_url, …) are never touched by the PATCH endpoint.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.identity import IDENTITY

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path("config/settings.yaml")
_LEGACY_APP_NAME = "mcs-manager"  # hardcoded legacy default for migration check

# Fields that require a backend restart to take effect.
RESTART_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"app_name", "log_level", "debug", "panel_bind_host"}
)

# All editable fields with their default values.  Keep in sync with
# AppSettings (core/config.py) and the fields exposed by the API.
_DEFAULTS: dict[str, Any] = {
    "app_name": IDENTITY.project_name,
    "log_level": "INFO",
    "debug": False,
    "rate_limit_per_minute": 60,
    "idempotency_ttl_hours": 24,
    "circuit_breaker_max_failures": 5,
    "circuit_breaker_timeout_seconds": 30,
    "event_bus_retry_attempts": 3,
    "saga_timeout_seconds": 300,
    "panel_bind_host": "127.0.0.1",
    "metrics_interval_seconds": 1.5,
    "post_running_grace_seconds": 30.0,
    "bot_verify_defaults": {
        "bot_count": 10,
        "duration_minutes": 15,
        "bot_tech": "auto",
        "placement_mode": "sidecar",
        "join_stagger_seconds": 3.0,
        "connect_grace_seconds": 60.0,
        "watchdog_overrun_minutes": 5.0,
    },
    "bot_pool_idle": 2,
    "bot_pool_max": 4,
    "bot_pool_acquire_retries": 2,
    "bot_resource_floor_mb": 4096,
    "bot_resource_floor_cores": 2,
    "bot_join_stagger_seconds": 3.0,
    "bot_connect_grace_seconds": 60.0,
    "bot_watchdog_overrun_minutes": 5.0,
    "global_max_concurrent_runs": 3,
    "stale_run_timeout_hours": 6.0,
}

_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass
class LiveSettings:
    """Mutable settings that can be updated without a restart (except where noted)."""

    app_name: str = IDENTITY.project_name
    log_level: str = "INFO"
    debug: bool = False
    rate_limit_per_minute: int = 60
    idempotency_ttl_hours: int = 24
    circuit_breaker_max_failures: int = 5
    circuit_breaker_timeout_seconds: int = 30
    event_bus_retry_attempts: int = 3
    saga_timeout_seconds: int = 300
    panel_bind_host: str = "127.0.0.1"
    metrics_interval_seconds: float = 1.5
    post_running_grace_seconds: float = 30.0
    bot_verify_defaults: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "bot_count": 10,
            "duration_minutes": 15,
            "bot_tech": "auto",
            "placement_mode": "sidecar",
            "join_stagger_seconds": 3.0,
            "connect_grace_seconds": 60.0,
            "watchdog_overrun_minutes": 5.0,
        }
    )
    bot_pool_idle: int = 2
    bot_pool_max: int = 4
    bot_pool_acquire_retries: int = 2
    bot_resource_floor_mb: int = 4096
    bot_resource_floor_cores: int = 2
    bot_join_stagger_seconds: float = 3.0
    bot_connect_grace_seconds: float = 60.0
    bot_watchdog_overrun_minutes: float = 5.0
    global_max_concurrent_runs: int = 3
    stale_run_timeout_hours: float = 6.0


_live: LiveSettings | None = None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load YAML file; return empty dict if file is absent."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("settings.yaml is not a mapping — ignoring")
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to read %s — using defaults", path)
        return {}


def _coerce(field: str, value: Any) -> Any:
    """Coerce a raw YAML value to the expected Python type for the field."""
    default = _DEFAULTS[field]
    target_type = type(default)
    if target_type is bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes")
    if field == "metrics_interval_seconds":
        try:
            return round(max(0.1, min(60.0, float(value))), 2)
        except (TypeError, ValueError):
            return default
    if field == "post_running_grace_seconds":
        try:
            return round(max(1.0, min(300.0, float(value))), 1)
        except (TypeError, ValueError):
            return default
    try:
        return target_type(value)
    except (TypeError, ValueError):
        logger.warning(
            "Could not coerce setting %r=%r to %s — using default", field, value, target_type
        )
        return default


def init_settings_store(path: Path | None = None) -> None:
    """Load settings from YAML and initialise the live store.

    Should be called once at application startup *after* env-var settings
    are available (i.e. in the FastAPI lifespan, just after
    ``ConfigFactory.global_settings()``).

    Migration: if the persisted YAML contains the exact legacy default
    "mcs-manager" for app_name, silently upgrade it to the new default.
    """
    global _live
    effective_path = path or _SETTINGS_FILE
    raw = _load_yaml_file(effective_path)

    # MIGRATION: check RAW YAML before any defaults are applied
    # Use hardcoded legacy string, not _DEFAULTS (which may already be new value)
    migrated = False
    if raw.get("app_name") == _LEGACY_APP_NAME:
        raw["app_name"] = IDENTITY.project_name  # "onx-manager"
        migrated = True

    kwargs: dict[str, Any] = {}
    for field, default in _DEFAULTS.items():
        if field in raw:
            kwargs[field] = _coerce(field, raw[field])
        elif field == "panel_bind_host":
            kwargs[field] = os.environ.get("ONX_PANEL_BIND_HOST") or os.environ.get(
                "MCS_PANEL_BIND_HOST", default
            )
        else:
            kwargs[field] = default

    _live = LiveSettings(**kwargs)

    # Persist migrated value immediately (idempotent: only writes if changed)
    if migrated:
        _persist(_live, effective_path)
        logger.info(
            "Migrated settings.yaml app_name from legacy default to %s",
            IDENTITY.project_name,
        )
    else:
        logger.info(
            "Settings store initialised from %s",
            effective_path if raw else "defaults",
        )


def get_live_settings() -> LiveSettings:
    """Return the current live settings instance.

    Initialises with defaults/settings.yaml if init_settings_store() was not
    explicitly called yet.
    """
    global _live
    if _live is None:
        init_settings_store()
    return _live


def update_settings(updates: dict[str, Any]) -> tuple[LiveSettings, list[str]]:
    """Apply *updates* to the live store, persist to YAML, and return
    ``(updated_instance, list_of_restart_required_fields_that_were_changed)``.

    Only the 9 known editable fields are accepted; unknown keys are ignored.
    """
    live = get_live_settings()
    restart_fields: list[str] = []

    for field in _DEFAULTS:
        if field not in updates:
            continue
        new_value = _coerce(field, updates[field])
        if getattr(live, field) != new_value:
            setattr(live, field, new_value)
            if field in RESTART_REQUIRED_FIELDS:
                restart_fields.append(field)

    _persist(live)
    return live, restart_fields


def _persist(live: LiveSettings, path: Path | None = None) -> None:
    """Write the current live settings to ``config/settings.yaml`` (or specified path)."""
    target_path = path or _SETTINGS_FILE
    target_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {k: getattr(live, k) for k in _DEFAULTS}
    try:
        with open(target_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
    except Exception:
        logger.exception("Failed to persist settings to %s", target_path)
        raise
