"""P5.5-1 ``.mrpack`` quarantine, parser, and lockfile builder tests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from app.core.allowlist import SymlinkEscapeError
from app.core.exceptions import (
    CaseCollisionError,
    HostileExecutableError,
    ManualDownloadRequiredError,
    ModpackFormatError,
    OversizedGitTrackedFileError,
    UnsupportedForgeVersionError,
)
from app.modules.versioning.application.modpack_lockfile_builder import (
    advance_base_overrides_per_file,
    build_lockfile_from_install_plan,
    store_base_overrides_in_cas,
)
from app.modules.versioning.domain.lockfile import (
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure import modpack_parser
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import (
    VerifiedDownloadResult,
)
from app.modules.versioning.infrastructure.modpack_parser import (
    DISCARDED_ROOT_FILES,
    FORBIDDEN_PREFIXES,
    InstallPlan,
    classify_and_validate_target_path,
    extract_overrides_safely,
    parse_mrpack,
    read_zip_member_bounded,
    validate_archive_quarantine,
    validate_forge_mc_version,
)

CDN = "https://cdn.modrinth.com/data/abc/versions/1/file.jar"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(path: str, data: bytes) -> dict:
    return {
        "path": path,
        "hashes": {"sha1": _sha1(data), "sha512": _sha512(data)},
        "fileSize": len(data),
        "downloads": [CDN],
    }


def _index(
    *,
    files: list[dict] | None = None,
    dependencies: dict | None = None,
    format_version: int = 1,
    game: str = "minecraft",
    name: str = "Test Pack",
) -> dict:
    return {
        "formatVersion": format_version,
        "game": game,
        "versionId": "1.0.0",
        "name": name,
        "files": files or [],
        "dependencies": dependencies
        if dependencies is not None
        else {"minecraft": "1.20.1", "fabric-loader": "0.15.11"},
    }


def _write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            # Preserve raw names on Windows so zipfile._sanitize_filename
            # does not rewrite backslashes before archive quarantine sees them.
            info = zipfile.ZipInfo(name)
            info.filename = name
            info.compress_type = zf.compression
            zf.writestr(info, data)
    return path


def _write_mrpack(path: Path, index: dict, overrides: dict[str, bytes] | None = None) -> Path:
    entries = {
        "modrinth.index.json": json.dumps(index).encode("utf-8"),
    }
    entries.update(overrides or {})
    return _write_zip(path, entries)


class _FakeModrinth:
    def __init__(self, client_only: set[str] | None = None) -> None:
        self.client_only = client_only or set()
        self.calls: list[list[str]] = []

    async def classify_client_only_jars_by_sha512(
        self, hashes: list[str]
    ) -> tuple[set[str], dict, dict]:
        self.calls.append(list(hashes))
        return (self.client_only & set(hashes), {}, {})


class _ExplodingModrinth:
    async def classify_client_only_jars_by_sha512(self, _hashes: object) -> tuple:
        raise AssertionError("Modrinth must not be queried for index files")


def _downloaded_map(cas: ArtifactCas, contents: dict[str, bytes]) -> dict:
    results = {}
    for path, data in contents.items():
        cas.put_bytes(data)
        results[path] = VerifiedDownloadResult(
            sha256=_sha256(data),
            sha512=_sha512(data),
            sha1=_sha1(data),
            size=len(data),
            final_url=CDN,
            redirect_count=0,
        )
    return results


def _base_lockfile_kwargs(cas: ArtifactCas, plan: InstallPlan, data: bytes):
    cas.put_bytes(data)
    result = VerifiedDownloadResult(
        sha256=_sha256(data),
        sha512=_sha512(data),
        sha1=_sha1(data),
        size=len(data),
        final_url=CDN,
        redirect_count=0,
    )
    return {plan.files[0].path: result}


@pytest.mark.asyncio
async def test_mrpack_happy_path_and_lockfile_roundtrip(tmp_path: Path) -> None:
    index_data = b"downloaded-mod-content"
    index = _index(
        files=[
            _entry("mods/mod.jar", index_data),
            {
                **_entry("mods/optional.jar", b"optional"),
                "env": {"server": "optional"},
            },
        ]
    )
    archive = _write_mrpack(
        tmp_path / "pack.mrpack",
        index,
        {
            "overrides/config/a.toml": b"from-overrides",
            "server-overrides/config/a.toml": b"from-server-overrides",
            "overrides/config/b.toml": b"b-value",
            "overrides/mods/ov.jar": b"override-jar",
            "overrides/server-icon.png": b"png",
            "overrides/run.sh": b"#!/bin/sh\n",
            "client-overrides/config/c.toml": b"client-only",
        },
    )
    fake = _FakeModrinth()
    plan, override_blobs = await parse_mrpack(archive, modrinth_client=fake)

    assert plan.source == "modrinth"
    assert plan.mc_version == "1.20.1"
    assert plan.loader_id == "fabric"
    assert plan.loader_version == "0.15.11"
    assert plan.version_label == "Test Pack"
    assert [f.path for f in plan.files] == ["mods/mod.jar", "mods/optional.jar"]
    assert plan.files[1].optional is True
    assert "overrides/config/a.toml" not in override_blobs
    assert override_blobs["config/a.toml"] == b"from-server-overrides"
    assert override_blobs["config/b.toml"] == b"b-value"
    assert override_blobs["mods/ov.jar"] == b"override-jar"
    assert override_blobs["server-icon.png"] == b"png"
    assert "config/c.toml" not in override_blobs
    assert "run.sh" in plan.discarded_paths
    assert len(fake.calls) == 1

    if os.name != "posix":
        return

    cas = ArtifactCas(tmp_path / "cas")
    downloaded = _downloaded_map(
        cas,
        {
            "mods/mod.jar": index_data,
            "mods/optional.jar": b"optional",
        },
    )
    lockfile = build_lockfile_from_install_plan(
        plan,
        cas=cas,
        downloaded_files=downloaded,
        override_blobs=override_blobs,
    )
    assert lockfile.format == 2
    assert lockfile.modpack is not None
    assert lockfile.modpack.source == "modrinth"
    assert lockfile.base_overrides["config/a.toml"] == _sha256(
        b"from-server-overrides"
    )
    assert lockfile.base_overrides["config/b.toml"] == _sha256(b"b-value")
    assert lockfile.base_overrides["server-icon.png"] == _sha256(b"png")
    files_by_path = {f.path: f for f in lockfile.files}
    assert files_by_path["mods/mod.jar"].origin == Origin.MODRINTH
    assert files_by_path["mods/ov.jar"].origin == Origin.OVERRIDE
    assert cas.has(files_by_path["mods/ov.jar"].sha256)

    raw = dump_lockfile(lockfile)
    parsed = parse_lockfile(raw)
    assert dict(parsed.base_overrides) == dict(lockfile.base_overrides)
    assert [f.path for f in parsed.files] == [f.path for f in lockfile.files]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "index",
    [
        _index(format_version=2),
        _index(game="not-minecraft"),
        _index(dependencies={"minecraft": "1.20.1"}),
        _index(
            dependencies={
                "minecraft": "1.20.1",
                "fabric-loader": "0.15.11",
                "forge": "47.2.0",
            }
        ),
    ],
)
async def test_mrpack_structure_failures(tmp_path: Path, index: dict) -> None:
    archive = _write_mrpack(tmp_path / "bad.mrpack", index)
    with pytest.raises(ModpackFormatError):
        await parse_mrpack(archive, modrinth_client=_FakeModrinth())


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.20.2", "1.16.5", "1.21.4"])
async def test_forge_version_range_rejected(tmp_path: Path, version: str) -> None:
    index = _index(dependencies={"minecraft": version, "forge": "47.2.0"})
    archive = _write_mrpack(tmp_path / "forge.mrpack", index)
    with pytest.raises(UnsupportedForgeVersionError):
        await parse_mrpack(archive, modrinth_client=_FakeModrinth())


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.17.1", "1.20.1"])
async def test_forge_version_range_accepted(tmp_path: Path, version: str) -> None:
    index = _index(dependencies={"minecraft": version, "forge": "47.2.0"})
    archive = _write_mrpack(tmp_path / "forge-ok.mrpack", index)
    plan, _blobs = await parse_mrpack(archive, modrinth_client=_FakeModrinth())
    assert plan.loader_id == "forge"
    assert plan.mc_version == version


def test_validate_forge_version_helper_boundaries() -> None:
    validate_forge_mc_version("1.17.1")
    validate_forge_mc_version("1.20.1")
    with pytest.raises(UnsupportedForgeVersionError):
        validate_forge_mc_version("1.20.2")
    with pytest.raises(UnsupportedForgeVersionError):
        validate_forge_mc_version("1.16.5")


@pytest.mark.asyncio
async def test_index_dedicated_filter_and_environment_authority(
    tmp_path: Path,
) -> None:
    index = _index(
        files=[
            {**_entry("mods/client.jar", b"client"), "env": {"server": "unsupported"}},
            {**_entry("mods/optional.jar", b"optional"), "env": {"server": "optional"}},
            {**_entry("mods/required.jar", b"required"), "env": {"server": "required"}},
        ]
    )
    archive = _write_mrpack(tmp_path / "filter.mrpack", index)
    plan, _ = await parse_mrpack(
        archive,
        install_optional_server_files=False,
        modrinth_client=_ExplodingModrinth(),
    )
    assert plan.skipped_client_files == ("mods/client.jar",)
    assert plan.skipped_optional_files == ("mods/optional.jar",)
    assert [f.path for f in plan.files] == ["mods/required.jar"]

    plan_with_optional, _ = await parse_mrpack(
        archive,
        install_optional_server_files=True,
        modrinth_client=_ExplodingModrinth(),
    )
    optional = next(f for f in plan_with_optional.files if f.path == "mods/optional.jar")
    assert optional.optional is True
    assert optional.env_server == "optional"


@pytest.mark.asyncio
async def test_override_client_only_jar_is_dropped(tmp_path: Path) -> None:
    jar = b"client-only-jar-bytes"
    archive = _write_mrpack(
        tmp_path / "override.mrpack",
        _index(),
        {
            "overrides/mods/client.jar": jar,
            "overrides/mods/server.jar": b"server-jar",
            "overrides/plugins/plugin.jar": b"plugin-jar",
        },
    )
    fake = _FakeModrinth({_sha512(jar)})
    plan, blobs = await parse_mrpack(archive, modrinth_client=fake)
    assert plan.skipped_client_override_jars == ("mods/client.jar",)
    assert "mods/client.jar" not in blobs
    assert "mods/server.jar" in blobs
    assert "plugins/plugin.jar" in blobs
    assert all(o.path != "mods/client.jar" for o in plan.overrides)


def _quarantine(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as zf:
        validate_archive_quarantine(zf)


@pytest.mark.parametrize(
    "member",
    ["../evil.txt", "/etc/passwd", "cafe\u0301.txt", "dir\\evil.txt", "dir:evil"],
)
def test_quarantine_rejects_invalid_paths(tmp_path: Path, member: str) -> None:
    archive = _write_zip(tmp_path / "bad-path.zip", {member: b"x"})
    with pytest.raises(ModpackFormatError):
        _quarantine(archive)


def test_quarantine_rejects_symlink_member(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, b"../target")
    with pytest.raises(ModpackFormatError):
        _quarantine(archive)


def test_quarantine_rejects_high_ratio_large_member(tmp_path: Path) -> None:
    archive = _write_zip(
        tmp_path / "bomb.zip",
        {"big.bin": b"\x00" * (17 * 1024 * 1024)},
    )
    with pytest.raises(ModpackFormatError):
        _quarantine(archive)


def test_quarantine_accepts_high_ratio_small_member(tmp_path: Path) -> None:
    archive = _write_zip(
        tmp_path / "small.zip",
        {"small.bin": b"\x00" * (1024 * 1024)},
    )
    _quarantine(archive)


def test_quarantine_rejects_total_size_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modpack_parser, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 10)
    archive = _write_zip(tmp_path / "large.zip", {"file.bin": b"x" * 11})
    with pytest.raises(ModpackFormatError):
        _quarantine(archive)


def test_quarantine_rejects_entry_count_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modpack_parser, "MAX_ARCHIVE_ENTRIES", 2)
    archive = _write_zip(
        tmp_path / "many.zip",
        {"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"},
    )
    with pytest.raises(ModpackFormatError):
        _quarantine(archive)


def test_quarantine_rejects_casefold_collision(tmp_path: Path) -> None:
    archive = _write_zip(
        tmp_path / "case.zip",
        {"mods/Mod.jar": b"a", "mods/mod.jar": b"b"},
    )
    with pytest.raises(CaseCollisionError):
        _quarantine(archive)


@pytest.mark.parametrize("prefix", FORBIDDEN_PREFIXES)
def test_forbidden_prefixes_rejected(prefix: str) -> None:
    with pytest.raises(ModpackFormatError):
        classify_and_validate_target_path(f"{prefix}/file.txt", 10)


def test_lockfile_target_rejected() -> None:
    with pytest.raises(ModpackFormatError):
        classify_and_validate_target_path("onx-jars.lock.json", 10)


@pytest.mark.parametrize("name", sorted(DISCARDED_ROOT_FILES))
def test_discarded_root_files(name: str) -> None:
    assert classify_and_validate_target_path(name, 10) == "DISCARD"


@pytest.mark.parametrize(
    "path",
    [
        "config/x.jar",
        "plugins/sub/x.jar",
        "resourcepacks/x.jar",
        "kubejs/x.class",
        "tools/x.sh",
        "tools/x.dll",
        "tools/x.ps1",
    ],
)
def test_hostile_executables_rejected(path: str) -> None:
    with pytest.raises(HostileExecutableError):
        classify_and_validate_target_path(path, 10)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("mods/x.jar", "A-JAR"),
        ("mods/sub/x.jar", "A-JAR"),
        ("plugins/x.jar", "A-JAR"),
        ("root.jar", "A-JAR"),
        ("config/x.toml", "B"),
        ("resourcepacks/pack.zip", "A-CAS"),
    ],
)
def test_allowed_target_classification(path: str, expected: str) -> None:
    assert classify_and_validate_target_path(path, 100) == expected


def test_class_b_size_rules() -> None:
    with pytest.raises(OversizedGitTrackedFileError) as exc:
        classify_and_validate_target_path(
            "server-icon.png", 1024 * 1024 + 1
        )
    assert exc.value.http_status == 413
    with pytest.raises(OversizedGitTrackedFileError):
        classify_and_validate_target_path("config/big.toml", 16 * 1024 * 1024 + 1)
    assert (
        classify_and_validate_target_path("config/medium.toml", 2 * 1024 * 1024)
        == "B-ROUTED-CAS"
    )
    assert classify_and_validate_target_path("config/small.toml", 100) == "B"


def test_read_member_bounded_rejects_declared_size_spoof(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "spoof.zip", {"file.txt": b"x" * 10})
    with zipfile.ZipFile(archive, "r") as zf:
        info = zf.getinfo("file.txt")
        info.file_size = 5
        with pytest.raises(ModpackFormatError):
            read_zip_member_bounded(zf, info)


@pytest.mark.asyncio
async def test_extract_overrides_rejects_symlinked_component(tmp_path: Path) -> None:
    archive = _write_mrpack(
        tmp_path / "extract.mrpack",
        _index(),
        {"overrides/config/foo.toml": b"value"},
    )
    plan, _blobs = await parse_mrpack(archive, modrinth_client=_FakeModrinth())
    dest = tmp_path / "dest"
    dest.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / "config").symlink_to(outside, target_is_directory=True)
    with zipfile.ZipFile(archive, "r") as zf, pytest.raises(SymlinkEscapeError):
        extract_overrides_safely(zf, plan.overrides, dest)


@pytest.mark.asyncio
async def test_extract_overrides_happy_path(tmp_path: Path) -> None:
    archive = _write_mrpack(
        tmp_path / "extract-ok.mrpack",
        _index(),
        {
            "overrides/config/foo.toml": b"value",
            "server-overrides/config/foo.toml": b"server-value",
        },
    )
    plan, _blobs = await parse_mrpack(archive, modrinth_client=_FakeModrinth())
    dest = tmp_path / "dest-ok"
    with zipfile.ZipFile(archive, "r") as zf:
        written = extract_overrides_safely(zf, plan.overrides, dest)
    assert written
    assert (dest / "config" / "foo.toml").read_bytes() == b"server-value"


@pytest.mark.asyncio
async def test_extract_overrides_safely_non_posix_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_mrpack(
        tmp_path / "extract-nt.mrpack",
        _index(),
        {"overrides/config/foo.toml": b"nt-value"},
    )
    plan, _blobs = await parse_mrpack(archive, modrinth_client=_FakeModrinth())
    monkeypatch.setattr(modpack_parser, "_is_posix_host", lambda: False)

    dest = tmp_path / "dest-nt"
    with zipfile.ZipFile(archive, "r") as zf:
        written = extract_overrides_safely(zf, plan.overrides, dest)
    assert written
    assert (dest / "config" / "foo.toml").read_bytes() == b"nt-value"

    bad_dest = tmp_path / "dest-nt-bad"
    bad_dest.mkdir()
    outside = tmp_path / "outside-nt"
    outside.mkdir()
    (bad_dest / "config").symlink_to(outside, target_is_directory=True)
    with zipfile.ZipFile(archive, "r") as zf, pytest.raises(SymlinkEscapeError):
        extract_overrides_safely(zf, plan.overrides, bad_dest)


@pytest.mark.skipif(
    os.name != "posix",
    reason="ArtifactCas requires a POSIX environment; Windows = Simple-only",
)
def test_base_override_store_validation(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    stored = store_base_overrides_in_cas(
        cas, {"config/a.toml": b"value", "config/b.toml": b"other"}
    )
    assert list(stored) == sorted(stored)
    assert stored["config/a.toml"] == _sha256(b"value")
    with pytest.raises(ModpackFormatError):
        store_base_overrides_in_cas(cas, {"mods/x.jar": b"jar"})
    with pytest.raises(OversizedGitTrackedFileError):
        store_base_overrides_in_cas(
            cas, {"config/large.toml": b"x" * (1024 * 1024 + 1)}
        )


def test_builder_refuses_unresolved_blockers(tmp_path: Path) -> None:
    plan = InstallPlan(
        source="curseforge",
        project_id="local",
        version_id="local",
        version_label="Pack",
        index_sha256="a" * 64,
        mc_version="1.20.1",
        loader_id="forge",
        loader_version="47.2.0",
        files=(),
        overrides=(),
        manual_blockers=(),
    )
    from app.modules.versioning.infrastructure.modpack_parser import (
        ManualDownloadBlocker,
    )

    blocked = InstallPlan(
        source=plan.source,
        project_id=plan.project_id,
        version_id=plan.version_id,
        version_label=plan.version_label,
        index_sha256=plan.index_sha256,
        mc_version=plan.mc_version,
        loader_id=plan.loader_id,
        loader_version=plan.loader_version,
        files=(),
        overrides=(),
        manual_blockers=(
            ManualDownloadBlocker(path="mods/x.jar", filename="x.jar"),
        ),
    )
    with pytest.raises(ManualDownloadRequiredError):
        build_lockfile_from_install_plan(
            blocked,
            cas=ArtifactCas(tmp_path / "cas"),
            downloaded_files={},
            override_blobs={},
        )


def test_advance_base_overrides_per_file() -> None:
    current = {
        "a.toml": "1" * 64,
        "b.toml": "2" * 64,
        "c.toml": "3" * 64,
        "d.toml": "4" * 64,
    }
    target = {
        "a.toml": "9" * 64,
        "b.toml": "8" * 64,
        "c.toml": "7" * 64,
        "e.toml": "6" * 64,
    }
    result = advance_base_overrides_per_file(
        current,
        target,
        resolved_paths={"a.toml", "c.toml", "e.toml"},
        removed_paths={"d.toml"},
    )
    assert result == {
        "a.toml": "9" * 64,
        "b.toml": "2" * 64,
        "c.toml": "7" * 64,
        "e.toml": "6" * 64,
    }
    assert list(result) == sorted(result)


@pytest.mark.asyncio
async def test_class_a_overrides_over_16_mib_succeed(tmp_path: Path) -> None:
    big_size = 17 * 1024 * 1024
    big_jar = b"J" * big_size
    big_pack = b"R" * big_size
    archive = tmp_path / "large-class-a.mrpack"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(_index()).encode("utf-8"))
        zf.writestr("overrides/mods/big.jar", big_jar)
        zf.writestr("overrides/resourcepacks/big.zip", big_pack)

    plan, blobs = await parse_mrpack(archive, modrinth_client=_FakeModrinth())
    by_path = {ov.path: ov for ov in plan.overrides}
    assert by_path["mods/big.jar"].classification == "A-JAR"
    assert by_path["mods/big.jar"].size == big_size
    assert by_path["resourcepacks/big.zip"].classification == "A-CAS"
    assert by_path["resourcepacks/big.zip"].size == big_size
    assert len(blobs["mods/big.jar"]) == big_size
    assert len(blobs["resourcepacks/big.zip"]) == big_size

    dest = tmp_path / "dest-big"
    with zipfile.ZipFile(archive, "r") as zf:
        written = extract_overrides_safely(zf, plan.overrides, dest)
    assert len(written) == 2
    assert (dest / "mods" / "big.jar").stat().st_size == big_size
    assert (dest / "resourcepacks" / "big.zip").stat().st_size == big_size


@pytest.mark.asyncio
async def test_index_discard_and_skip_paths_omitted_from_plan_files(
    tmp_path: Path,
) -> None:
    index = _index(
        files=[
            _entry("mods/kept.jar", b"kept"),
            _entry("run.sh", b"#!/bin/sh\n"),
            _entry("eula.txt", b"eula=true\n"),
            _entry("world/level.dat", b"world-data"),
        ]
    )
    archive = _write_mrpack(tmp_path / "discard-skip.mrpack", index)
    plan, _ = await parse_mrpack(archive, modrinth_client=_ExplodingModrinth())
    assert [f.path for f in plan.files] == ["mods/kept.jar"]
    assert plan.discarded_paths == ("eula.txt", "run.sh", "world/level.dat")
    assert "skipped_path:world/level.dat" in plan.warnings
