from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.modules.backup.infrastructure.envelope_crypto import EnvelopeBackupCipher
from app.modules.backup.infrastructure.tier2_archive import (
    collect_tier2_gc_roots,
    create_tier2_archive,
)
from app.modules.storage.local import LocalStorage
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.vault_crypto import MasterKek

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="ArtifactCas requires POSIX",
)


class FakeS3Storage(LocalStorage):
    backend_type = "s3"


def _seed_server(server_dir: Path, cas: ArtifactCas, *, with_class_c: bool = True) -> tuple[str, str]:
    (server_dir / "world").mkdir(parents=True, exist_ok=True)
    (server_dir / "world" / "level.dat").write_bytes(b"world-bytes")
    (server_dir / "server.properties").write_text("motd=Tier2\n", encoding="utf-8")
    if with_class_c:
        (server_dir / "ops.json").write_text('[{"name":"admin"}]', encoding="utf-8")
    user_sha = cas.put_bytes(b"custom-user-mod-jar")
    modrinth_sha = cas.put_bytes(b"public-modrinth-jar")
    (server_dir / "onx-jars.lock.json").write_text(
        json.dumps(
            {
                "files": [
                    {"path": "mods/user.jar", "sha256": user_sha, "origin": "user"},
                    {"path": "mods/public.jar", "sha256": modrinth_sha, "origin": "modrinth"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return user_sha, modrinth_sha


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["tar.zst", "tar.gz"])
async def test_tier2_archive_formats_cas_bundling_and_encryption(tmp_path: Path, fmt: str) -> None:
    server_dir = tmp_path / "srv"
    cas = ArtifactCas(tmp_path / "cas")
    storage = LocalStorage(str(tmp_path / "backups"))
    kek = MasterKek(kek_version=1, key_bytes=b"\x44" * 32)
    user_sha, modrinth_sha = _seed_server(server_dir, cas, with_class_c=True)

    # Default include_cas_jars=False
    res_light = await create_tier2_archive(
        server_id="srv-1",
        server_dir=server_dir,
        backup_id=f"b-light-{fmt}",
        storage=storage,
        archive_format=fmt,  # type: ignore[arg-type]
        include_cas_jars=False,
        kek=kek,
        cas=cas,
    )
    assert res_light.encrypted is True
    assert res_light.bundled_cas_digests == ()
    assert set(res_light.lockfile_cas_digests) == {user_sha, modrinth_sha}

    # Explicit include_cas_jars=True -> only origin=="user" bundled
    res_user = await create_tier2_archive(
        server_id="srv-1",
        server_dir=server_dir,
        backup_id=f"b-user-{fmt}",
        storage=storage,
        archive_format=fmt,  # type: ignore[arg-type]
        include_cas_jars=True,
        kek=kek,
        cas=cas,
    )
    assert res_user.bundled_cas_digests == (user_sha,)
    enc_bytes = await storage.read(res_user.storage_path)
    assert hashlib.sha256(enc_bytes).hexdigest() == res_user.checksum
    dec_bytes = EnvelopeBackupCipher(kek).decrypt_bytes(enc_bytes)
    assert len(dec_bytes) > 0

    assert collect_tier2_gc_roots([server_dir]) == {user_sha, modrinth_sha}


@pytest.mark.asyncio
async def test_tier2_mandatory_encryption_rejects_opt_out_for_class_c_and_s3(tmp_path: Path) -> None:
    server_dir = tmp_path / "srv"
    cas = ArtifactCas(tmp_path / "cas")
    local_store = LocalStorage(str(tmp_path / "local"))
    s3_store = FakeS3Storage(str(tmp_path / "s3"))
    _seed_server(server_dir, cas, with_class_c=True)

    with pytest.raises(ValidationError, match="mandatory"):
        await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id="b-noenc-c",
            storage=local_store,
            archive_format="tar.gz",
            encrypt=False,
        )

    # Remove Class C -> local opt-out allowed, S3 still mandatory
    (server_dir / "ops.json").unlink()
    res_plain = await create_tier2_archive(
        server_id="srv-1",
        server_dir=server_dir,
        backup_id="b-plain-local",
        storage=local_store,
        archive_format="tar.gz",
        encrypt=False,
    )
    assert res_plain.encrypted is False
    raw_tar = tmp_path / "local" / res_plain.storage_path
    with tarfile.open(raw_tar, "r:gz") as tf:
        manifest = json.loads(tf.extractfile("manifest.json").read().decode("utf-8"))  # type: ignore[union-attr]
        assert manifest["tier"] == "tier_2"
        assert manifest["contains_class_c"] is False

    with pytest.raises(ValidationError, match="mandatory"):
        await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id="b-noenc-s3",
            storage=s3_store,
            archive_format="tar.gz",
            encrypt=False,
        )
