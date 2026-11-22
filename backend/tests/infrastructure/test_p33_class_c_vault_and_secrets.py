"""P3-3 encrypted Class-C vault and ``server_secrets`` verification.

Covers the mandatory ten-item crypto / verification plan from the P3-3
architecture brief: nonce uniqueness, AAD binding, tamper and truncation,
``manifest_sha256`` ledger checks, KEK version and permission errors,
crash reconciliation, zero leakage, retention/GC/concurrency, and the
retired ``format_version = 1`` layout.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
import app.modules.versioning.infrastructure.models  # noqa: F401
from app.core.config import AppSettings
from app.core.exceptions import (
    MasterKekInvalidError,
    MasterKekMissingError,
    MasterKekVersionMismatchError,
    SecurityPermissionError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.refresh_orchestrator import (
    RETENTION_UNTIL_CONFIRM,
    RETENTION_UNTIL_HEALTH_GATE,
    parse_retention_policy,
)
from app.modules.versioning.application.refresh_recovery import RefreshStartupReconciler
from app.modules.versioning.application.repo_lease import RepoLeaseManager
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure import runtime_adapters
from app.modules.versioning.infrastructure.class_c_snapshot import (
    BLOBS_DIRNAME,
    CHUNK_SIZE,
    COMPLETE_MARKER_NAME,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    ClassCReconcileSummary,
    ClassCSnapshotService,
    chunk_aad,
    dek_wrap_aad,
    derive_chunk_nonce,
)
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportResult,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import ServerSecretModel
from app.modules.versioning.infrastructure.runtime_adapters import (
    CleanExportStageAdapter,
)
from app.modules.versioning.infrastructure.server_secret_vault import (
    ServerSecretVault,
    extract_secret_from_bytes,
    normalize_key_name,
)
from app.modules.versioning.infrastructure.vault_crypto import (
    MasterKek,
    load_master_kek,
)

SERVER_A = "srv-p33-a"
SERVER_B = "srv-p33-b"
SERVER_RETENTION = "srv-p33-retention"
SERVER_LEASE = "srv-p33-lease"
SERVER_SECRETS = "srv-p33-secrets"
SECRET = "correct-horse-battery-staple"
KEY_A = bytes.fromhex("a5" * 32)
KEY_B = bytes.fromhex("5a" * 32)

_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P3-3 Class-C / secret vault / Git / POSIX KEK contract requires POSIX; Windows = Simple-only",
)


@dataclass
class P33Env:
    layout: HostStateLayout
    engine: Any
    factory: sessionmaker[Session]
    service: ClassCSnapshotService
    vault: ServerSecretVault

    def add_server(self, server_id: str) -> None:
        with self.factory() as session:
            if session.get(ServerModel, server_id) is None:
                session.add(
                    ServerModel(
                        id=server_id,
                        name=server_id,
                        minecraft_version="1.21",
                        server_type="paper",
                    )
                )
                session.commit()


@pytest.fixture
def p33_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> P33Env:
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    monkeypatch.setenv("ONX_MASTER_KEK", KEY_A.hex())
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'p33-ledger.db'}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        for server_id in (
            SERVER_A,
            SERVER_B,
            SERVER_RETENTION,
            SERVER_LEASE,
            SERVER_SECRETS,
        ):
            session.add(
                ServerModel(
                    id=server_id,
                    name=server_id,
                    minecraft_version="1.21",
                    server_type="paper",
                )
            )
        session.commit()
    service = ClassCSnapshotService(layout, sync_session_factory=factory)
    vault = ServerSecretVault(layout, sync_session_factory=factory)
    env = P33Env(
        layout=layout,
        engine=engine,
        factory=factory,
        service=service,
        vault=vault,
    )
    try:
        yield env
    finally:
        vault.close()
        service.close()
        engine.dispose()


def _set_env_kek(
    monkeypatch: pytest.MonkeyPatch, key: bytes, *, version: int | None = None
) -> None:
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    material = key.hex() if version in (None, 1) else f"{version}:{key.hex()}"
    monkeypatch.setenv("ONX_MASTER_KEK", material)


def _clear_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONX_MASTER_KEK", raising=False)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)


def _write_big_live(live: Path) -> bytes:
    live.mkdir(parents=True)
    (live / "ops.json").write_text('["alice"]', encoding="utf-8")
    warps_dir = live / "plugins" / "Essentials" / "warps"
    warps_dir.mkdir(parents=True)
    payload = bytes(range(256)) * (CHUNK_SIZE * 2 // 256) + b"tail" * 25
    (warps_dir / "big.yml").write_bytes(payload)
    return payload


def _write_small_live(live: Path) -> None:
    live.mkdir(parents=True)
    (live / "ops.json").write_text('["alice"]', encoding="utf-8")
    (live / "plugins" / "Essentials" / "warps").mkdir(parents=True)
    (live / "plugins" / "Essentials" / "warps" / "home.yml").write_text(
        "home: 1\n", encoding="utf-8"
    )


def _manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _rewrite_manifest(
    env: P33Env,
    server_id: str,
    snapshot_id: str,
    manifest: dict[str, Any],
    *,
    sync_db: bool = True,
) -> str:
    root = env.layout.class_c_vault_dir(server_id) / snapshot_id
    raw = _canonical_bytes(manifest)
    (root / MANIFEST_FILENAME).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if sync_db:
        env.service.repository.update_snapshot(
            server_id, snapshot_id, manifest_sha256=digest
        )
    return digest


def _frames(blob: bytes) -> list[bytes]:
    frames: list[bytes] = []
    offset = 0
    while offset < len(blob):
        length = int.from_bytes(blob[offset : offset + 4], "big")
        offset += 4
        frames.append(blob[offset : offset + length])
        offset += length
    assert offset == len(blob)
    return frames


def _frame(chunk: bytes) -> bytes:
    return len(chunk).to_bytes(4, "big") + chunk


def _entry(manifest: dict[str, Any], relpath: str) -> dict[str, Any]:
    return next(item for item in manifest["files"] if item["relpath"] == relpath)


def _refresh_ciphertext_metadata(entry: dict[str, Any], blob: bytes) -> None:
    entry["ciphertext_size"] = len(blob)
    entry["ciphertext_sha256"] = hashlib.sha256(blob).hexdigest()


def _rewrite_blob(
    env: P33Env,
    server_id: str,
    snapshot_id: str,
    relpath: str,
    blob: bytes,
) -> dict[str, Any]:
    root = env.layout.class_c_vault_dir(server_id) / snapshot_id
    manifest = _manifest(root)
    entry = _entry(manifest, relpath)
    (root / entry["blob_relpath"]).write_bytes(blob)
    _refresh_ciphertext_metadata(entry, blob)
    _rewrite_manifest(env, server_id, snapshot_id, manifest)
    return manifest


def _target_with_sentinel(tmp_path: Path) -> Path:
    target = tmp_path / "restore-target"
    target.mkdir()
    (target / "sentinel.txt").write_text("keep", encoding="utf-8")
    return target


def _assert_untouched(target: Path) -> None:
    assert (target / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in target.iterdir()) == ["sentinel.txt"]


def _unwrap_dek(
    manifest: dict[str, Any], server_id: str, snapshot_id: str, key: bytes
) -> bytes:
    return AESGCM(key).decrypt(
        bytes.fromhex(manifest["dek_wrap_nonce"]),
        bytes.fromhex(manifest["wrapped_dek"]),
        dek_wrap_aad(server_id, snapshot_id, int(manifest["kek_version"])),
    )


# ----------------------------------------------------------------------
# 1. Nonce and DEK uniqueness
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_nonce_and_dek_uniqueness(p33_env: P33Env, tmp_path: Path) -> None:
    live = tmp_path / "live-big"
    payload = _write_big_live(live)

    first = p33_env.service.create_snapshot(
        SERVER_A, live, snapshot_id="snap-nonce-1"
    )
    second = p33_env.service.create_snapshot(
        SERVER_A, live, snapshot_id="snap-nonce-2"
    )
    first_manifest = _manifest(first.root)
    second_manifest = _manifest(second.root)
    entry = _entry(first_manifest, "plugins/Essentials/warps/big.yml")

    assert entry["chunk_count"] == 3
    assert entry["size"] == len(payload)
    base_nonce = bytes.fromhex(entry["base_nonce"])
    derived = [derive_chunk_nonce(base_nonce, index) for index in range(3)]
    assert len(set(derived)) == 3
    assert len({bytes.fromhex(item["base_nonce"]) for item in first_manifest["files"]}) == 2

    # A new snapshot gets a fresh DEK envelope (and random wrap nonce).
    assert first_manifest["wrapped_dek"] != second_manifest["wrapped_dek"]
    assert first_manifest["dek_wrap_nonce"] != second_manifest["dek_wrap_nonce"]
    assert (
        _entry(first_manifest, "ops.json")["base_nonce"]
        != _entry(second_manifest, "ops.json")["base_nonce"]
    )


def test_derive_chunk_nonce_rejects_invalid_parameters() -> None:
    with pytest.raises(ValidationError):
        derive_chunk_nonce(b"short", 0)
    with pytest.raises(ValidationError):
        derive_chunk_nonce(b"0" * 12, -1)
    with pytest.raises(ValidationError):
        derive_chunk_nonce(b"0" * 12, 1 << 32)


@_POSIX_ONLY
def test_secret_reextraction_rotates_dek_and_nonce(p33_env: P33Env) -> None:
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", "first-secret")
    first = _stored_secret_row(p33_env, SERVER_SECRETS, "RCON_PASSWORD")

    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", "second-secret")
    second = _stored_secret_row(p33_env, SERVER_SECRETS, "RCON_PASSWORD")

    assert bytes(first.wrapped_dek) != bytes(second.wrapped_dek)
    assert bytes(first.nonce) != bytes(second.nonce)
    assert bytes(first.ciphertext) != bytes(second.ciphertext)
    assert p33_env.vault.load_server_secrets(SERVER_SECRETS) == {
        "RCON_PASSWORD": "second-secret"
    }


def _stored_secret_row(env: P33Env, server_id: str, key_name: str) -> ServerSecretModel:
    with env.factory() as session:
        return session.execute(
            select(ServerSecretModel).where(
                ServerSecretModel.server_id == server_id,
                ServerSecretModel.key_name == key_name,
            )
        ).scalar_one()


# ----------------------------------------------------------------------
# 2. AAD binding
# ----------------------------------------------------------------------


@_POSIX_ONLY
@pytest.mark.parametrize(
    ("wrong_server", "wrong_snapshot", "wrong_relpath"),
    [
        (SERVER_B, "snap-aad", "ops.json"),
        (SERVER_A, "snap-other", "ops.json"),
        (SERVER_A, "snap-aad", "plugins/other.yml"),
    ],
)
def test_snapshot_chunk_aad_rejects_substitution(
    p33_env: P33Env,
    tmp_path: Path,
    wrong_server: str,
    wrong_snapshot: str,
    wrong_relpath: str,
) -> None:
    live = tmp_path / "live-aad"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-aad")
    root = p33_env.layout.class_c_vault_dir(SERVER_A) / "snap-aad"
    manifest = _manifest(root)
    entry = _entry(manifest, "ops.json")
    dek = _unwrap_dek(manifest, SERVER_A, "snap-aad", KEY_A)
    plaintext = b'["alice"]'
    base_nonce = bytes.fromhex(entry["base_nonce"])

    forged = AESGCM(dek).encrypt(
        derive_chunk_nonce(base_nonce, 0),
        plaintext,
        chunk_aad(
            wrong_server,
            wrong_snapshot,
            wrong_relpath,
            0,
            is_final=True,
        ),
    )
    _rewrite_blob(
        p33_env, SERVER_A, "snap-aad", "ops.json", _frame(forged)
    )

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="authentication failed"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-aad", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_secret_aad_rejects_cross_server_and_cross_key(
    p33_env: P33Env,
) -> None:
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)
    with p33_env.factory() as session:
        row = session.execute(
            select(ServerSecretModel).where(
                ServerSecretModel.server_id == SERVER_SECRETS,
                ServerSecretModel.key_name == "RCON_PASSWORD",
            )
        ).scalar_one()
        row.key_name = "OTHER_KEY"
        session.commit()

    with pytest.raises(ValidationError, match="Unable to decrypt server secret"):
        p33_env.vault.load_server_secrets(SERVER_SECRETS)

    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)
    with p33_env.factory() as session:
        row = session.execute(
            select(ServerSecretModel).where(
                ServerSecretModel.server_id == SERVER_SECRETS,
                ServerSecretModel.key_name == "RCON_PASSWORD",
            )
        ).scalar_one()
        row.server_id = SERVER_A
        session.commit()

    with pytest.raises(ValidationError, match="Unable to decrypt server secret"):
        p33_env.vault.load_server_secrets(SERVER_A)


@_POSIX_ONLY
def test_secret_aad_and_placeholder_normalization(p33_env: P33Env) -> None:
    assert normalize_key_name("  rcon_password ") == "RCON_PASSWORD"
    with pytest.raises(ValidationError):
        normalize_key_name("bad-key!")

    result = extract_secret_from_bytes(
        SERVER_SECRETS,
        "plugins/example/config.yml",
        b"password: hunter2\n",
        secret_value="hunter2",
        key_name="example_password",
        vault=p33_env.vault,
    )
    assert result.content == b"password: ${ONX_SECRET_EXAMPLE_PASSWORD}\n"
    assert result.replaced_count == 1
    assert result.updated_content == result.content
    assert p33_env.vault.load_server_secrets(SERVER_SECRETS) == {
        "EXAMPLE_PASSWORD": "hunter2"
    }


# ----------------------------------------------------------------------
# 3. Truncation and tamper
# ----------------------------------------------------------------------


def _create_big_snapshot(env: P33Env, tmp_path: Path, snapshot_id: str) -> Path:
    live = tmp_path / f"live-{snapshot_id}"
    _write_big_live(live)
    env.service.create_snapshot(SERVER_A, live, snapshot_id=snapshot_id)
    return env.layout.class_c_vault_dir(SERVER_A) / snapshot_id


@_POSIX_ONLY
def test_restore_rejects_dropped_final_chunk(
    p33_env: P33Env, tmp_path: Path
) -> None:
    root = _create_big_snapshot(p33_env, tmp_path, "snap-truncated")
    manifest = _manifest(root)
    entry = _entry(manifest, "plugins/Essentials/warps/big.yml")
    blob = (root / entry["blob_relpath"]).read_bytes()
    frames = _frames(blob)
    assert len(frames) == 3
    _rewrite_blob(
        p33_env,
        SERVER_A,
        "snap-truncated",
        "plugins/Essentials/warps/big.yml",
        _frame(frames[0]) + _frame(frames[1]),
    )

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="truncated"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-truncated", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_restore_rejects_swapped_chunks(p33_env: P33Env, tmp_path: Path) -> None:
    root = _create_big_snapshot(p33_env, tmp_path, "snap-swapped")
    manifest = _manifest(root)
    entry = _entry(manifest, "plugins/Essentials/warps/big.yml")
    frames = _frames((root / entry["blob_relpath"]).read_bytes())
    _rewrite_blob(
        p33_env,
        SERVER_A,
        "snap-swapped",
        "plugins/Essentials/warps/big.yml",
        _frame(frames[1]) + _frame(frames[0]) + _frame(frames[2]),
    )

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="authentication failed"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-swapped", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_restore_rejects_flipped_ciphertext_byte(
    p33_env: P33Env, tmp_path: Path
) -> None:
    root = _create_big_snapshot(p33_env, tmp_path, "snap-flipped")
    manifest = _manifest(root)
    entry = _entry(manifest, "plugins/Essentials/warps/big.yml")
    blob = bytearray((root / entry["blob_relpath"]).read_bytes())
    blob[-1] ^= 0x01
    (root / entry["blob_relpath"]).write_bytes(bytes(blob))

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="digest"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-flipped", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_restore_rejects_altered_manifest_aad_fields(
    p33_env: P33Env, tmp_path: Path
) -> None:
    root = _create_big_snapshot(p33_env, tmp_path, "snap-aad-manifest")
    manifest = _manifest(root)
    _entry(manifest, "plugins/Essentials/warps/big.yml")["relpath"] = (
        "plugins/Essentials/renamed.bin"
    )
    _rewrite_manifest(p33_env, SERVER_A, "snap-aad-manifest", manifest)

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="authentication failed"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-aad-manifest", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_restore_rejects_corrupt_manifest_and_missing_marker(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-corrupt"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-corrupt")
    root = p33_env.layout.class_c_vault_dir(SERVER_A) / "snap-corrupt"
    target = _target_with_sentinel(tmp_path)

    (root / MANIFEST_FILENAME).write_bytes(b"{not-json")
    with pytest.raises(ValidationError, match="not valid JSON"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-corrupt", target)
    _assert_untouched(target)

    # Rewrite a valid manifest, then remove the completion marker.
    payload = {
        "created_at": "2026-11-16T00:00:00Z",
        "dek_wrap_nonce": "0" * 24,
        "files": [],
        "format_version": FORMAT_VERSION,
        "kek_version": 1,
        "pinned": True,
        "server_id": SERVER_A,
        "snapshot_id": "snap-corrupt",
        "wrapped_dek": "0" * 96,
    }
    (root / MANIFEST_FILENAME).write_bytes(_canonical_bytes(payload))
    (root / COMPLETE_MARKER_NAME).unlink()
    with pytest.raises(ValidationError, match="missing"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-corrupt", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_empty_file_round_trip_and_tamper_rejection(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-empty"
    live.mkdir()
    (live / "ops.json").write_text("[]", encoding="utf-8")
    empty = live / "plugins" / "Essentials" / "warps" / "empty.yml"
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")

    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-empty")
    root = p33_env.layout.class_c_vault_dir(SERVER_A) / "snap-empty"
    manifest = _manifest(root)
    entry = _entry(manifest, "plugins/Essentials/warps/empty.yml")
    assert entry["size"] == 0
    assert entry["chunk_count"] == 1
    # A 0-byte plaintext produces one 16-byte GCM tag, framed by 4 length bytes.
    assert entry["ciphertext_size"] == 20
    assert len(_frames((root / entry["blob_relpath"]).read_bytes())) == 1

    restore = tmp_path / "restore-empty"
    restore.mkdir()
    assert p33_env.service.restore_snapshot(SERVER_A, "snap-empty", restore) == 2
    assert (
        restore / "plugins" / "Essentials" / "warps" / "empty.yml"
    ).read_bytes() == b""
    assert (restore / "ops.json").read_text(encoding="utf-8") == "[]"

    blob = bytearray((root / entry["blob_relpath"]).read_bytes())
    blob[-1] ^= 0x80
    (root / entry["blob_relpath"]).write_bytes(bytes(blob))
    with pytest.raises(ValidationError):
        p33_env.service.restore_snapshot(SERVER_A, "snap-empty", restore)
    assert (
        restore / "plugins" / "Essentials" / "warps" / "empty.yml"
    ).read_bytes() == b""


# ----------------------------------------------------------------------
# 4. manifest_sha256 DB-vs-disk verification (H2)
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_restore_rejects_on_disk_manifest_not_in_ledger(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-manifest"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-manifest")
    root = p33_env.layout.class_c_vault_dir(SERVER_A) / "snap-manifest"
    manifest = _manifest(root)
    manifest["pinned"] = False
    raw = _canonical_bytes(manifest)
    (root / MANIFEST_FILENAME).write_bytes(raw)

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="manifest digest"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-manifest", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_restore_rejects_missing_or_mismatched_ledger_row(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-ledger"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-ledger")
    target = _target_with_sentinel(tmp_path)

    p33_env.service.repository.update_snapshot(
        SERVER_A, "snap-ledger", manifest_sha256="0" * 64
    )
    with pytest.raises(ValidationError, match="manifest digest"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-ledger", target)
    _assert_untouched(target)

    p33_env.service.repository.update_snapshot(
        SERVER_A, "snap-ledger", status="missing"
    )
    with pytest.raises(ValidationError, match="not active"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-ledger", target)
    _assert_untouched(target)

    p33_env.service.repository.delete_snapshot(SERVER_A, "snap-ledger")
    with pytest.raises(ValidationError, match="no active database ledger row"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-ledger", target)
    _assert_untouched(target)


# ----------------------------------------------------------------------
# 5. kek_version mismatch (M2)
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_snapshot_restore_rejects_kek_version_mismatch(
    p33_env: P33Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live-kek-version"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-kek-v1")

    _set_env_kek(monkeypatch, KEY_B, version=2)
    target = _target_with_sentinel(tmp_path)
    with pytest.raises(MasterKekVersionMismatchError) as exc:
        p33_env.service.restore_snapshot(SERVER_A, "snap-kek-v1", target)

    assert exc.value.code == "MASTER_KEK_VERSION_MISMATCH"
    assert exc.value.http_status == 409
    assert exc.value.details["stored_kek_version"] == 1
    assert exc.value.details["active_kek_version"] == 2
    assert "stored kek_version=1" in str(exc.value)
    assert "active kek_version=2" in str(exc.value)
    _assert_untouched(target)


@_POSIX_ONLY
def test_secret_vault_rejects_kek_version_mismatch(
    p33_env: P33Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)
    _set_env_kek(monkeypatch, KEY_B, version=3)

    with pytest.raises(MasterKekVersionMismatchError) as exc:
        p33_env.vault.load_server_secrets(SERVER_SECRETS)

    assert exc.value.details == {
        "stored_kek_version": 1,
        "active_kek_version": 3,
    }
    assert "stored kek_version=1" in str(exc.value)
    assert "active kek_version=3" in str(exc.value)


# ----------------------------------------------------------------------
# 6. KEK error / precedence / permissions + Simple-mode isolation
# ----------------------------------------------------------------------


def test_missing_and_invalid_kek_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_kek(monkeypatch)
    with pytest.raises(MasterKekMissingError) as missing:
        load_master_kek()
    assert missing.value.code == "MASTER_KEK_MISSING"
    assert missing.value.http_status == 503

    monkeypatch.setenv("ONX_MASTER_KEK", "not-a-valid-key")
    with pytest.raises(MasterKekInvalidError) as invalid:
        load_master_kek()
    assert invalid.value.code == "MASTER_KEK_INVALID"
    assert invalid.value.http_status == 503

    monkeypatch.setenv("ONX_MASTER_KEK", "0:" + KEY_A.hex())
    with pytest.raises(MasterKekInvalidError):
        load_master_kek()

    monkeypatch.setenv("ONX_MASTER_KEK", "1:" + "ab" * 31)
    with pytest.raises(MasterKekInvalidError):
        load_master_kek()


def test_kek_file_precedence_warns_without_key_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    kek_file = tmp_path / "master-kek"
    kek_file.write_text(KEY_A.hex(), encoding="utf-8")
    os.chmod(kek_file, 0o600)
    monkeypatch.setenv("ONX_MASTER_KEK_FILE", str(kek_file))
    monkeypatch.setenv("ONX_MASTER_KEK", KEY_B.hex())

    with caplog.at_level(
        logging.WARNING,
        logger="app.modules.versioning.infrastructure.vault_crypto",
    ):
        loaded = load_master_kek()

    assert loaded.key_bytes == KEY_A
    assert loaded.kek_version == 1
    assert any(
        "Both ONX_MASTER_KEK_FILE and ONX_MASTER_KEK are set" in record.getMessage()
        for record in caplog.records
    )
    assert str(kek_file) in caplog.text
    assert KEY_A.hex() not in caplog.text
    assert KEY_B.hex() not in caplog.text


@_POSIX_ONLY
def test_insecure_kek_permissions_fail_closed_before_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_kek(monkeypatch)
    kek_file = tmp_path / "insecure-kek"
    kek_file.write_text(KEY_A.hex(), encoding="utf-8")
    os.chmod(kek_file, 0o644)

    settings = AppSettings(
        master_kek_file=str(kek_file),
        allow_insecure_keys=True,
    )
    with pytest.raises(SecurityPermissionError) as exc:
        load_master_kek(settings)

    assert exc.value.code == "SECURITY_PERMISSION_ERROR"
    assert "Insecure file permissions" in str(exc.value)
    assert KEY_A.hex() not in str(exc.value)
    assert stat.S_IMODE(kek_file.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != "posix", reason="POSIX KEK permission contract")
def test_kek_symlink_and_non_regular_files_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_kek(monkeypatch)
    target = tmp_path / "real-kek"
    target.write_text(KEY_A.hex(), encoding="utf-8")
    os.chmod(target, 0o600)
    link = tmp_path / "linked-kek"
    link.symlink_to(target)

    with pytest.raises(SecurityPermissionError):
        load_master_kek(AppSettings(master_kek_file=str(link)))

    directory = tmp_path / "kek-dir"
    directory.mkdir()
    with pytest.raises(SecurityPermissionError):
        load_master_kek(AppSettings(master_kek_file=str(directory)))


def test_kek_file_encodings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_kek(monkeypatch)

    raw_file = tmp_path / "raw-kek"
    raw_file.write_bytes(bytes(range(32)))
    os.chmod(raw_file, 0o600)
    raw = load_master_kek(AppSettings(master_kek_file=str(raw_file)))
    assert raw.kek_version == 1
    assert raw.key_bytes == bytes(range(32))

    versioned = tmp_path / "versioned-kek"
    versioned.write_text(f"7:{KEY_A.hex()}", encoding="utf-8")
    os.chmod(versioned, 0o600)
    loaded = load_master_kek(AppSettings(master_kek_file=str(versioned)))
    assert loaded.kek_version == 7
    assert loaded.key_bytes == KEY_A

    import base64

    encoded = tmp_path / "base64-kek"
    encoded.write_text(base64.b64encode(KEY_B).decode("ascii"), encoding="utf-8")
    os.chmod(encoded, 0o600)
    assert load_master_kek(AppSettings(master_kek_file=str(encoded))).key_bytes == KEY_B


def test_simple_mode_and_empty_secrets_need_no_kek(
    p33_env: P33Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_kek(monkeypatch)

    # Lazy loading: an empty per-server vault and an empty vault directory must
    # not require a KEK for Simple-mode/startup reconciliation paths.
    assert p33_env.vault.load_server_secrets(SERVER_A) == {}
    assert p33_env.service.reconcile_snapshots() == ClassCReconcileSummary()
    assert AppSettings().advanced_mode_enabled is (os.name == "posix")


@_POSIX_ONLY
def test_standalone_ledger_fallback_uses_layout_root(
    p33_env: P33Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.persistence.db import database

    assert p33_env.layout.root.is_dir()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "standalone-host-state"),
        servers_data_dir=str(tmp_path / "standalone-servers"),
    )
    layout = ensure_host_state_layout(settings)
    service = ClassCSnapshotService(layout)
    vault = ServerSecretVault(layout)
    live = tmp_path / "live-standalone"
    _write_small_live(live)
    try:
        service.create_snapshot("srv-standalone", live, snapshot_id="snap-standalone")
        assert (layout.root / "class-c-vault.db").is_file()
        assert service.repository.get_snapshot(
            "srv-standalone", "snap-standalone"
        ) is not None
        restore = tmp_path / "standalone-restore"
        restore.mkdir()
        assert (
            service.restore_snapshot("srv-standalone", "snap-standalone", restore)
            == 2
        )
        vault.store_secret("srv-standalone", "RCON_PASSWORD", SECRET)
        assert vault.load_server_secrets("srv-standalone") == {
            "RCON_PASSWORD": SECRET
        }
    finally:
        vault.close()
        service.close()


# ----------------------------------------------------------------------
# 7. Disk/DB crash reconciliation (M3)
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_reconcile_removes_orphans_and_marks_missing(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-reconcile"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-keep")
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-orphan-db")
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-missing-disk")
    vault = p33_env.layout.class_c_vault_dir(SERVER_A)

    # Crash after rename, before the ledger insert.
    p33_env.service.repository.delete_snapshot(SERVER_A, "snap-orphan-db")
    # Crash after ledger insert, before every marker/blob lands.
    (vault / "snap-missing-disk" / COMPLETE_MARKER_NAME).unlink()
    staging = vault / ".onx-snapshot-crash-abc"
    staging.mkdir()
    (staging / "partial").write_text("x", encoding="utf-8")
    incomplete = vault / "snap-incomplete-dir"
    incomplete.mkdir()
    (incomplete / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

    summary = p33_env.service.reconcile_snapshots(SERVER_A)

    assert "srv-p33-a/snap-orphan-db" in summary.removed_directories
    assert "srv-p33-a/snap-incomplete-dir" in summary.removed_directories
    assert "srv-p33-a/.onx-snapshot-crash-abc" in summary.removed_directories
    assert summary.removed_dirs == summary.removed_directories
    assert "srv-p33-a/snap-missing-disk" in summary.marked_missing
    assert summary.missing_snapshots == summary.marked_missing
    assert not (vault / "snap-orphan-db").exists()
    assert not staging.exists()
    assert not incomplete.exists()
    assert (vault / "snap-keep").is_dir()

    row = p33_env.service.repository.get_snapshot(SERVER_A, "snap-missing-disk")
    assert row is not None and row.status == "missing"

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="not found"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-missing-disk", target)
    _assert_untouched(target)


@_POSIX_ONLY
def test_startup_reconciler_runs_class_c_reconciliation(
    p33_env: P33Env,
) -> None:
    vault = p33_env.layout.class_c_vault_dir(SERVER_A)
    orphan = vault / "snap-startup-orphan"
    orphan.mkdir(parents=True)
    (orphan / COMPLETE_MARKER_NAME).write_text("{}", encoding="utf-8")
    (orphan / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

    reconciler = RefreshStartupReconciler(
        p33_env.layout,
        repository=SimpleNamespace(
            _session_factory=None,
            _sync_session_factory=p33_env.factory,
        ),
        servers_data_dir=p33_env.layout.root / "servers",
    )
    errors: list[str] = []
    reconciler._reconcile_class_c_vault(errors)

    assert errors == []
    assert not orphan.exists()


# ----------------------------------------------------------------------
# 8. Zero secret leakage and POSIX modes
# ----------------------------------------------------------------------


def test_posix_modes_and_no_plaintext_in_vault(
    p33_env: P33Env, tmp_path: Path
) -> None:
    if os.name != "posix":
        pytest.skip("POSIX mode contract")
    live = tmp_path / "live-modes"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-modes")
    vault = p33_env.layout.class_c_vault_dir(SERVER_A)
    root = vault / "snap-modes"

    assert stat.S_IMODE(vault.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / BLOBS_DIRNAME).stat().st_mode) == 0o700
    assert stat.S_IMODE((root / MANIFEST_FILENAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((root / COMPLETE_MARKER_NAME).stat().st_mode) == 0o600
    for blob in (root / BLOBS_DIRNAME).rglob("*.enc"):
        assert stat.S_IMODE(blob.stat().st_mode) == 0o600
        assert b'["alice"]' not in blob.read_bytes()
        assert b"home: 1" not in blob.read_bytes()


@_POSIX_ONLY
def test_failure_paths_never_leak_key_dek_or_secret(
    p33_env: P33Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONX_MASTER_KEK", KEY_A.hex())
    live = tmp_path / "live-leak"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-leak")
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)

    redacted = repr(MasterKek(kek_version=9, key_bytes=KEY_A))
    assert KEY_A.hex() not in redacted
    assert "***REDACTED***" in redacted
    assert KEY_A.hex() not in str(MasterKek(kek_version=9, key_bytes=KEY_A))

    _set_env_kek(monkeypatch, KEY_B)
    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError) as wrong_key:
        p33_env.service.restore_snapshot(SERVER_A, "snap-leak", target)
    assert KEY_A.hex() not in repr(wrong_key.value)
    assert KEY_B.hex() not in repr(wrong_key.value)
    assert "REDACTED" not in repr(wrong_key.value)

    with p33_env.factory() as session:
        row = session.execute(
            select(ServerSecretModel).where(
                ServerSecretModel.server_id == SERVER_SECRETS
            )
        ).scalar_one()
        row.ciphertext = b"\x00" * 17
        session.commit()
    with pytest.raises(ValidationError) as secret_error:
        p33_env.vault.load_server_secrets(SERVER_SECRETS)
    assert SECRET not in repr(secret_error.value)
    assert SECRET not in json.dumps(secret_error.value.details, default=str)
    assert "Unable to decrypt server secret" in str(secret_error.value)


# ----------------------------------------------------------------------
# 9. Retention, GC roots and RepoLeaseManager concurrency
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_retention_pinned_exempt_and_gc_roots(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-retention"
    live.mkdir()
    (live / "ops.json").write_text("[]", encoding="utf-8")

    for index in range(12):
        p33_env.service.create_snapshot(
            SERVER_RETENTION,
            live,
            snapshot_id=f"snap-{index:02d}",
            pinned=False,
        )
    for index in range(2):
        p33_env.service.create_snapshot(
            SERVER_RETENTION,
            live,
            snapshot_id=f"pin-{index}",
            pinned=True,
        )

    active = p33_env.service.repository.list_active(SERVER_RETENTION)
    assert len(active) == 12
    ids = {row.snapshot_id for row in active}
    assert "snap-00" not in ids and "snap-01" not in ids
    assert {"pin-0", "pin-1"} <= ids
    assert sum(1 for row in active if row.pinned) == 2
    vault = p33_env.layout.class_c_vault_dir(SERVER_RETENTION)
    assert not (vault / "snap-00").exists()
    assert not (vault / "snap-01").exists()

    roots = p33_env.service.collect_gc_roots(SERVER_RETENTION)
    assert len(roots.snapshot_ids) == 12
    assert len(roots.snapshot_dirs) == 12
    assert len(roots.manifest_sha256s) == 12
    assert roots.blob_paths
    assert all(path.is_file() for path in roots.blob_paths)

    p33_env.service.unpin_snapshot(SERVER_RETENTION, "pin-0")
    assert len(p33_env.service.repository.list_active(SERVER_RETENTION)) == 11
    p33_env.service.unpin_snapshot(SERVER_RETENTION, "pin-1")
    remaining = p33_env.service.repository.list_active(SERVER_RETENTION)
    assert len(remaining) == 10
    assert all(not row.pinned for row in remaining)
    assert {row.snapshot_id for row in remaining} == {
        f"snap-{index:02d}" for index in range(4, 12)
    } | {"pin-0", "pin-1"}
    roots_after = p33_env.service.collect_gc_roots(SERVER_RETENTION)
    assert len(roots_after.snapshot_ids) == 10


@_POSIX_ONLY
def test_repo_lease_serializes_encrypted_snapshot_creation(
    p33_env: P33Env, tmp_path: Path
) -> None:
    live = tmp_path / "live-lease"
    live.mkdir()
    (live / "ops.json").write_text("[]", encoding="utf-8")
    # ``Base.metadata`` does not carry the migration-only server_default for
    # previous_tree_retention, so seed the placeholder lease row explicitly.
    with p33_env.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO server_repo_leases "
                "(server_id, fencing_token, previous_tree_retention, updated_at) "
                "VALUES (:sid, 0, 'until_health_gate', CURRENT_TIMESTAMP)"
            ),
            {"sid": SERVER_LEASE},
        )
    lease = RepoLeaseManager(
        sync_session_factory=p33_env.factory,
        ttl_seconds=30.0,
        heartbeat_interval_seconds=10.0,
        wait_timeout_seconds=10.0,
    )
    barrier = threading.Barrier(2)
    intervals: list[tuple[float, float]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            with lease.acquire_sync(SERVER_LEASE, holder=f"worker-{index}"):
                started = time.monotonic()
                time.sleep(0.1)
                p33_env.service.create_snapshot(
                    SERVER_LEASE,
                    live,
                    snapshot_id=f"lease-{index}",
                )
                finished = time.monotonic()
            with lock:
                intervals.append((started, finished))
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(index,), name=f"lease-worker-{index}")
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not errors
    assert len(intervals) == 2
    first, second = sorted(intervals)
    assert first[1] <= second[0]
    assert {
        row.snapshot_id
        for row in p33_env.service.repository.list_active(SERVER_LEASE)
    } == {"lease-0", "lease-1"}


def test_previous_tree_retention_policies() -> None:
    assert RETENTION_UNTIL_HEALTH_GATE == "until_health_gate"
    assert RETENTION_UNTIL_CONFIRM == "until_confirm"
    assert parse_retention_policy("until_health_gate") == (
        "until_health_gate",
        None,
    )
    assert parse_retention_policy("until_confirm") == ("until_confirm", None)
    policy, window = parse_retention_policy("24h")
    assert policy == "24h"
    assert window is not None and window.total_seconds() == 24 * 3600


class _RecordingExportService:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.secret_checks: list[dict[str, str]] = []

    def assert_no_unresolved_secrets(
        self,
        _server_id: str,
        _server_root: str | Path,
        _commit_sha: str,
        *,
        secrets: dict[str, str] | None = None,
    ) -> None:
        self.secret_checks.append(dict(secrets or {}))

    def export(self, request: Any, *, fencing_verifier: Any) -> CleanExportResult:
        fencing_verifier()
        self.requests.append(request)
        return CleanExportResult(
            root=Path(request.destination),
            marker_path=Path(request.destination) / ".onx-complete.json",
            file_count=0,
            total_bytes=0,
            export_id=request.export_id,
        )


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_clean_export_adapter_substitutes_vault_secrets(
    p33_env: P33Env, tmp_path: Path
) -> None:
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)
    recorder = _RecordingExportService()
    adapter = CleanExportStageAdapter(
        p33_env.layout,
        server_id=SERVER_SECRETS,
        server_root=tmp_path,
        lockfile=SimpleNamespace(lec=None),  # type: ignore[arg-type]
        loop=asyncio.get_running_loop(),
        export_service=recorder,  # type: ignore[arg-type]
        panel_properties={"rcon.password": "${ONX_SECRET_RCON_PASSWORD}"},
        jvm_args="",
        secret_vault=p33_env.vault,
    )

    result = await adapter(
        tmp_path / "staging",
        "0" * 40,
        export_id="exp-p33",
        fencing_verifier=lambda: None,
    )

    assert result.export_id == "exp-p33"
    assert recorder.requests[0].secrets == {"RCON_PASSWORD": SECRET}

    empty = _RecordingExportService()
    adapter_empty = CleanExportStageAdapter(
        p33_env.layout,
        server_id=SERVER_A,
        server_root=tmp_path,
        lockfile=SimpleNamespace(lec=None),  # type: ignore[arg-type]
        loop=asyncio.get_running_loop(),
        export_service=empty,  # type: ignore[arg-type]
        secret_vault=p33_env.vault,
    )
    await adapter_empty(
        tmp_path / "staging-empty",
        "0" * 40,
        export_id="exp-empty",
        fencing_verifier=lambda: None,
    )
    assert empty.requests[0].secrets == {}


# ----------------------------------------------------------------------
# 10. format_version = 1 retirement
# ----------------------------------------------------------------------


@_POSIX_ONLY
def test_format_version_one_is_retired(p33_env: P33Env, tmp_path: Path) -> None:
    live = tmp_path / "live-v1"
    _write_small_live(live)
    p33_env.service.create_snapshot(SERVER_A, live, snapshot_id="snap-v1")
    root = p33_env.layout.class_c_vault_dir(SERVER_A) / "snap-v1"
    for name in (MANIFEST_FILENAME, COMPLETE_MARKER_NAME):
        payload = json.loads((root / name).read_text(encoding="utf-8"))
        payload["format_version"] = 1
        (root / name).write_bytes(_canonical_bytes(payload))

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="format_version"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-v1", target)
    _assert_untouched(target)

    # The reconciler deletes v1 directories instead of leaving unreadable data.
    summary = p33_env.service.reconcile_snapshots(SERVER_A)
    assert "srv-p33-a/snap-v1" in summary.removed_directories
    assert not root.exists()


# ----------------------------------------------------------------------
# 11. Red-team fix round 1 regressions
# ----------------------------------------------------------------------


def _export_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.21",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


def _init_export_repo(
    env: P33Env,
    server_id: str,
    tmp_path: Path,
    files: dict[str, str],
) -> tuple[Path, str]:
    root = tmp_path / f"export-root-{server_id}"
    root.mkdir(parents=True)
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    result = GitRepositoryService(env.layout).initialize(
        server_id, root, _export_lockfile()
    )
    return root, result.main_sha


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_clean_export_adapter_defaults_to_server_secret_vault(
    p33_env: P33Env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix 1: production-default construction must load vault secrets."""
    p33_env.vault.store_secret(SERVER_SECRETS, "RCON_PASSWORD", SECRET)
    root, sha = _init_export_repo(
        p33_env,
        SERVER_SECRETS,
        tmp_path,
        {"config/rcon.yml": "password: ${ONX_SECRET_RCON_PASSWORD}\n"},
    )
    default_vaults: list[ServerSecretVault] = []

    def _default_vault(layout: HostStateLayout) -> ServerSecretVault:
        vault = ServerSecretVault(layout, sync_session_factory=p33_env.factory)
        default_vaults.append(vault)
        return vault

    monkeypatch.setattr(runtime_adapters, "ServerSecretVault", _default_vault)
    adapter = CleanExportStageAdapter(
        p33_env.layout,
        server_id=SERVER_SECRETS,
        server_root=root,
        lockfile=_export_lockfile(),
        loop=asyncio.get_running_loop(),
        panel_properties={},
        jvm_args="",
    )

    await asyncio.to_thread(
        adapter.assert_no_unresolved_secrets, SERVER_SECRETS, root, sha
    )
    result = await adapter(
        tmp_path / "default-vault-export",
        sha,
        export_id="exp-default-vault",
        fencing_verifier=lambda: None,
    )

    assert default_vaults, "adapter must construct the default vault"
    exported = (result.root / "config" / "rcon.yml").read_text(encoding="utf-8")
    assert exported == f"password: {SECRET}\n"
    assert "${ONX_SECRET_" not in exported
    for vault in default_vaults:
        vault.close()


@_POSIX_ONLY
def test_preflight_rejects_lowercase_secret_placeholder(
    p33_env: P33Env,
    tmp_path: Path,
) -> None:
    """Fix 2: exact-case key matching in preflight and substitution."""
    root, sha = _init_export_repo(
        p33_env,
        SERVER_SECRETS,
        tmp_path,
        {"config/rcon.yml": "password: ${ONX_SECRET_rcon_pass}\n"},
    )
    service = CleanExportService(p33_env.layout)

    with pytest.raises(ValidationError, match="unresolved secret placeholders"):
        service.assert_no_unresolved_secrets(
            SERVER_SECRETS, root, sha, secrets={"RCON_PASS": "hunter2"}
        )

    # Exact-case metadata remains valid so operators can intentionally use it.
    service.assert_no_unresolved_secrets(
        SERVER_SECRETS, root, sha, secrets={"rcon_pass": "hunter2"}
    )


@_POSIX_ONLY
def test_javascript_text_secret_is_substituted_and_fails_closed(
    p33_env: P33Env,
    tmp_path: Path,
) -> None:
    """Fix 3: script suffixes must be scanned and substituted in Step 5."""
    root, sha = _init_export_repo(
        p33_env,
        SERVER_SECRETS,
        tmp_path,
        {"kubejs/server_scripts/hook.js": "const apiKey = '${ONX_SECRET_API_KEY}';\n"},
    )
    service = CleanExportService(p33_env.layout)

    result = service.export(
        CleanExportRequest(
            server_id=SERVER_SECRETS,
            server_root=root,
            commit_sha=sha,
            destination=tmp_path / "js-export",
            lockfile=_export_lockfile(),
            secrets={"API_KEY": "api-secret"},
        )
    )
    exported = (result.root / "kubejs" / "server_scripts" / "hook.js").read_text(
        encoding="utf-8"
    )
    assert exported == "const apiKey = 'api-secret';\n"
    assert "${ONX_SECRET_" not in exported

    missing = tmp_path / "js-export-missing"
    with pytest.raises(ValidationError, match="Unresolved secret"):
        service.export(
            CleanExportRequest(
                server_id=SERVER_SECRETS,
                server_root=root,
                commit_sha=sha,
                destination=missing,
                lockfile=_export_lockfile(),
                secrets={},
            )
        )
    assert not missing.exists()


@_POSIX_ONLY
def test_reconcile_marks_missing_when_vault_root_deleted(
    p33_env: P33Env,
    tmp_path: Path,
) -> None:
    """Fix 4: a deleted vault root must orphan active DB rows as missing."""
    live = tmp_path / "live-lost-vault"
    _write_small_live(live)
    p33_env.service.create_snapshot(
        SERVER_A, live, snapshot_id="snap-lost-vault"
    )
    shutil.rmtree(p33_env.layout.class_c_vault)

    summary = p33_env.service.reconcile_snapshots()

    assert "srv-p33-a/snap-lost-vault" in summary.marked_missing
    row = p33_env.service.repository.get_snapshot(SERVER_A, "snap-lost-vault")
    assert row is not None and row.status == "missing"

    target = _target_with_sentinel(tmp_path)
    with pytest.raises(ValidationError, match="not found"):
        p33_env.service.restore_snapshot(SERVER_A, "snap-lost-vault", target)
    _assert_untouched(target)

    outside = tmp_path / "outside-vault"
    outside.mkdir()
    p33_env.layout.class_c_vault.symlink_to(outside)
    with pytest.raises(ValidationError, match="symlink"):
        p33_env.service.reconcile_snapshots()
