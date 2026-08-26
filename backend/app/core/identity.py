from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    # Project / package names
    project_name: str = "onx-manager"  # PyPI package, Docker label prefix base
    pypi_name: str = "onx-manager"
    npm_name: str = "onx-manager"
    dist_name: str = "onx-manager"  # importlib.metadata distribution name

    # CLI command
    cli_command: str = "onx"  # replaces "mcs"

    # On-disk identity directory & file (per-server)
    identity_dir_legacy: str = ".mcsmanager"  # OLD — read & write during transition
    identity_dir_new: str = ".onx-manager"  # NEW — write alongside legacy; becomes primary after transition
    identity_file: str = "server.json"

    # Identity document schema
    identity_version: int = 1
    schema_version: int = 1
    manager_field_legacy: str = "mcsmanager"  # value written by old code
    manager_field_new: str = "onx-manager"  # value written by new code

    # Docker labels (container ownership)
    docker_label_prefix_legacy: str = "com.mcsmanager"
    docker_label_prefix_new: str = "com.onx-manager"

    # Logger prefix (structlog logger_name)
    logger_prefix_legacy: str = "mcs"
    logger_prefix_new: str = "onx"

    # Database file (backend root)
    db_filename_legacy: str = "mcs.db"
    db_filename_new: str = "onx.db"

    # Docker volume names (docker-compose.yml)
    db_volume_legacy: str = "mcs-db-data"
    db_volume_new: str = "onx-db-data"
    server_data_volume_legacy: str = "mcs-server-data"
    server_data_volume_new: str = "onx-server-data"

    # Environment variable prefix
    env_prefix_legacy: str = "MCS_"
    env_prefix_new: str = "ONX_"

    # Process ownership marker
    process_marker_legacy: str = "MCS_MANAGED"
    process_marker_new: str = "ONX_MANAGED"

    # Temp directory prefixes
    temp_prefix_legacy: str = "mcs-"
    temp_prefix_new: str = "onx-"

    # Prometheus metric namespace
    # DECISION: Keep "mcs_" prefix on metrics to avoid breaking existing dashboards.
    # This is a deliberate exception to the rename — documented in release notes.
    metrics_prefix_legacy: str = "mcs_"
    metrics_prefix_new: str = "mcs_"  # unchanged


IDENTITY = Identity()
