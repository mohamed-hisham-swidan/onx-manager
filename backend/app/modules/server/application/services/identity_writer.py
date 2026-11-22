from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.identity import IDENTITY
from app.modules.server.infrastructure.fs import FileSystem, local_fs

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.services.identity_writer")


def build_server_identity_doc(
    uid: str,
    provider: str = "docker",
    created_at: str | None = None,
) -> dict:
    """Build the canonical identity document dictionary."""
    return {
        "version": IDENTITY.identity_version,
        "uid": uid,
        "server_id": uid,
        "provider": provider,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "manager": IDENTITY.manager_field_new,
        "schema_version": IDENTITY.schema_version,
    }


def write_server_identity(
    dir_path: str | Path,
    uid: str,
    provider: str = "docker",
    fs: FileSystem | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically stamp .onx-manager/server.json with server_id and provider.

    Per DECISION-2026-09-13 (Bug 3 Design Spec §3.1), new creation, import,
    and reconciliation writes stamp exclusively to .onx-manager/server.json
    without duplicating to the legacy .mcsmanager directory.
    """
    fs_impl = fs or local_fs
    target_dir = Path(dir_path) / IDENTITY.identity_dir_new
    target_file = target_dir / IDENTITY.identity_file

    doc = build_server_identity_doc(uid=uid, provider=provider, created_at=created_at)
    content = json.dumps(doc, indent=2).encode("utf-8")

    fs_impl.write_binary_atomic(str(target_file), content)
    logger.info("Stamped identity for server %s (provider=%s) at %s", uid, provider, target_file)
    return target_file
