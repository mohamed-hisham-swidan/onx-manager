"""Integration tests for Lockfile Format 2.1 domain model and ArtifactCas."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.exceptions import CasCorruptionError
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas


def test_lockfile_cas_roundtrip(tmp_path: Path) -> None:
    cas_dir = tmp_path / "cas"
    cas = ArtifactCas(cas_dir)

    payload_mod = b"PK\x03\x04FAKE_JAR_CONTENT_MOD"
    payload_override = b"option.enable=true\n"

    src_override = tmp_path / "options.txt"
    src_override.write_bytes(payload_override)

    # Put both into CAS (one via put_bytes, one via put_file)
    digest_mod = cas.put_bytes(payload_mod)
    digest_override = cas.put_file(src_override)

    # Construct LockfileV21 referencing these digests
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={
            "config/fancymenu/options.txt": digest_override,
        },
        files=(
            LockfileFile(
                path="mods/example.jar",
                sha256=digest_mod,
                size=len(payload_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
            ),
        ),
    )

    # Serialize and re-parse lockfile
    raw_lockfile = dump_lockfile(lockfile)
    parsed_lockfile = parse_lockfile(raw_lockfile)
    assert parsed_lockfile == lockfile

    # Verify CAS blobs can be opened and match content
    mod_file_entry = parsed_lockfile.files[0]
    with cas.open_blob(mod_file_entry.sha256) as f:
        assert f.read() == payload_mod

    override_digest = parsed_lockfile.base_overrides["config/fancymenu/options.txt"]
    with cas.open_blob(override_digest) as f:
        assert f.read() == payload_override

    # Corrupt one blob in CAS
    mod_blob_path = cas.blob_path(mod_file_entry.sha256)
    os.chmod(mod_blob_path, 0o600)
    mod_blob_path.write_bytes(b"corrupted_bytes")
    os.chmod(mod_blob_path, 0o400)

    # Domain parsing remains pure and succeeds
    re_parsed = parse_lockfile(raw_lockfile)
    assert re_parsed == lockfile

    # But opening the corrupt blob from CAS raises CasCorruptionError
    with pytest.raises(CasCorruptionError) as exc_info:
        cas.open_blob(mod_file_entry.sha256)
    assert exc_info.value.code == "CAS_CORRUPTION"
