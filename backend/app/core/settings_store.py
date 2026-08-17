"""Live settings store.

Provides a single in-process mutable instance of the persisted settings.
On startup, :func:`init_settings_store` loads from ``config/settings.yaml``
(if it exists), falling back to env-var/default values.  All code that
previously called ``ConfigFactory.global_settings()`` to read the 9 user-
facing settings fields should call :func:`get_live_settings` instead.

The store is intentionally separate from ``AppSettings`` (which remains
read-only/env-var backed) so that the non-editable infrastructure fields
(secret_key, database_url, …) are never touched by the PATCH endpoint.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path("config/settings.yaml")

# Fields that require a backend restart to take effect.
RESTART_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"app_name", "log_level", "debug", "panel_bind_host"}
)

# All editable fields with their default values.  Keep in sync with
# AppSettings (core/config.py) and the fields exposed by the API.
_DEFAULTS: dict[str, Any] = {
    "app_name": "mcs-manager",
    "log_level": "INFO",
    "debug": False,
    "rate_limit_per_minute": 60,
    "idempotency_ttl_hours": 24,
    "circuit_breaker_max_failures": 5,
    "circuit_breaker_timeout_seconds": 30,
    "event_bus_retry_attempts": 3,
    "saga_timeout_seconds": 300,
    "panel_bind_host": "127.0.0.1",
    "metrics_interval_seconds": 0.2,
}

_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass
class LiveSettings:
    """Mutable settings that can be updated without a restart (except where noted)."""

    app_name: str = "mcs-manager"
    log_level: str = "INFO"
    debug: bool = False
    rate_limit_per_minute: int = 60
    idempotency_ttl_hours: int = 24
    circuit_breaker_max_failures: int = 5
    circuit_breaker_timeout_seconds: int = 30
    event_bus_retry_attempts: int = 3
    saga_timeout_seconds: int = 300
    panel_bind_host: str = "127.0.0.1"
    metrics_interval_seconds: float = 0.2


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
    try:
        return target_type(value)
    except (TypeError, ValueError):
        logger.warning("Could not coerce setting %r=%r to %s — using default", field, value, target_type)
        return default


def init_settings_store(path: Path | None = None) -> None:
    """Load settings from YAML and initialise the live store.

    Should be called once at application startup *after* env-var settings
    are available (i.e. in the FastAPI lifespan, just after
    ``ConfigFactory.global_settings()``).
    """
    global _live
    effective_path = path or _SETTINGS_FILE
    raw = _load_yaml_file(effective_path)

    kwargs: dict[str, Any] = {}
    for field, default in _DEFAULTS.items():
        if field in raw:
            kwargs[field] = _coerce(field, raw[field])
        elif field == "panel_bind_host":
            kwargs[field] = os.environ.get("MCS_PANEL_BIND_HOST", default)
        else:
            kwargs[field] = default

    _live = LiveSettings(**kwargs)
    logger.info("Settings store initialised from %s", effective_path if raw else "defaults")


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


def _persist(live: LiveSettings) -> None:
    """Write the current live settings to ``config/settings.yaml``."""
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {k: getattr(live, k) for k in _DEFAULTS}
    try:
        with open(_SETTINGS_FILE, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
    except Exception:
        logger.exception("Failed to persist settings to %s", _SETTINGS_FILE)
        raise
