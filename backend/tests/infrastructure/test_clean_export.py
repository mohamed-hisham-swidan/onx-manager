"""Clean Export tests for P2-3 (fixed five-step composition)."""

from __future__ import annotations

import io
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import ValidationError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LecRef,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.clean_export import (
    EXPORT_MARKER_NAME,
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode clean export is POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-clean-export"
PAPER_LEC_KEY = "paper/1.20.4/499"
FORGE_LEC_KEY = "forge/1.20.1/47.2.0"
FORGE_ARGS_RELPATH = "libraries/net/minecraftforge/forge/1.20.1-47.2.0/unix_args.txt"


def _lockfile(
    *files: LockfileFile,
    lec: LecRef | None = None,
    loader: LoaderRef | None = None,
    mc: str = "1.20.4",
) -> LockfileV21:
    return LockfileV21(
        format=2,
        mc=mc,
        loader=loader or LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=tuple(files),
        lec=lec,
    )


def _write(root: Path, relpath: str, data: str | bytes) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[HostStateLayout, Path, str]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / SERVER_ID
    root.mkdir(parents=True)
    _write(
        root,
        "server.properties",
        "#Minecraft server properties\r\n"
        "motd=Repo MOTD\r\n"
        "server-port=25565\r\n"
        "rcon.password=repo-secret\r\n"
        "max-players=42\r\n"
        "online-mode=true\r\n",
    )
    _write(root, "config/app.yml", "feature: true\n")
    _write(root, "plugins/sample/config.yml", "token: ${ONX_SECRET_PLUGIN_TOKEN}\n")
    _write(root, "server-icon.png", b"\x89PNG\r\n\x1a\nicons")

    result = GitRepositoryService(layout).initialize(SERVER_ID, root, _lockfile())
    return layout, root, result.main_sha


def _request(
    _layout: HostStateLayout,
    root: Path,
    sha: str,
    *,
    destination: Path,
    lockfile: LockfileV21 | None = None,
    **overrides: object,
) -> CleanExportRequest:
    values: dict[str, object] = {
        "server_id": SERVER_ID,
        "server_root": root,
        "commit_sha": sha,
        "destination": destination,
        "lockfile": lockfile or _lockfile(lec=LecRef(key=PAPER_LEC_KEY)),
        "panel_properties": {
            "motd": "Panel MOTD",
            "server-port": "25566",
            "rcon.password": "${ONX_SECRET_RCON_PASSWORD}",
        },
        "jvm_args": "-Xmx2G\n-Dtoken=${ONX_SECRET_PLUGIN_TOKEN}",
        "secrets": {
            "RCON_PASSWORD": "rcon-secret",
            "PLUGIN_TOKEN": "plugin-secret",
        },
        "joinable_test_container": True,
    }
    values.update(overrides)
    return CleanExportRequest(**values)  # type: ignore[arg-type]


def _prepare_lec(layout: HostStateLayout) -> None:
    lec = layout.lec / "paper" / "1.20.4" / "499"
    _write(lec, "cache/patched.jar", b"patched-paper")
    _write(lec, "versions/1.20.4/server.jar", b"vanilla-paper")


def _write_marker(path: Path, file_count: int = 1) -> None:
    _write(
        path,
        EXPORT_MARKER_NAME,
        json.dumps(
            {
                "completed_at": "2026-11-13T00:00:00Z",
                "file_count": file_count,
                "total_bytes": 128,
            }
        ),
    )


def _prepare_overlays(tmp_path: Path) -> tuple[Path, Path]:
    template = tmp_path / "data-template"
    _write(template, "world/level.dat", b"level-data")
    _write(template, "world/playerdata/steve.dat", b"player-data")
    _write(template, "run.sh", "#!/bin/sh\nexit 1\n")
    _write_marker(template, file_count=2)
    class_c = tmp_path / "class-c-snapshot"
    _write(class_c, "ops.json", b'{"uuid": {"level": 4}}')
    _write(class_c, "plugins/Essentials/warps/home.yml", "world: world\n")
    _write_marker(class_c, file_count=2)
    return template, class_c


def test_export_composes_five_steps_and_writes_marker(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    template, class_c = _prepare_overlays(tmp_path)
    jar_bytes = b"PK\x03\x04paper-server-jar"
    digest = ArtifactCas(layout.cas).put_bytes(jar_bytes)
    lockfile = _lockfile(
        LockfileFile(
            path="server.jar",
            sha256=digest,
            size=len(jar_bytes),
            optional=False,
            env_server=EnvServer.REQUIRED,
            origin=Origin.PAPERMC,
        ),
        lec=LecRef(key=PAPER_LEC_KEY),
    )
    destination = tmp_path / "export"

    result = CleanExportService(layout).export(
        _request(
            layout,
            root,
            sha,
            destination=destination,
            lockfile=lockfile,
            data_template_dir=template,
            class_c_overlay_dir=class_c,
        )
    )

    assert result.root == destination
    assert result.marker_path == destination / EXPORT_MARKER_NAME
    assert (destination / "config" / "app.yml").read_text() == "feature: true\n"
    assert (destination / "server-icon.png").read_bytes() == b"\x89PNG\r\n\x1a\nicons"

    assert (destination / "server.jar").read_bytes() == jar_bytes
    assert stat.S_ISREG((destination / "server.jar").stat().st_mode)

    assert (destination / "cache" / "patched.jar").read_bytes() == b"patched-paper"
    assert (destination / "versions" / "1.20.4" / "server.jar").read_bytes() == b"vanilla-paper"

    assert (destination / "world" / "level.dat").read_bytes() == b"level-data"
    assert (destination / "world" / "playerdata" / "steve.dat").read_bytes() == b"player-data"
    assert (destination / "ops.json").read_text() == '{"uuid": {"level": 4}}'
    assert (destination / "plugins" / "Essentials" / "warps" / "home.yml").read_text() == (
        "world: world\n"
    )
    assert not (destination / "run.sh").exists()
    assert [path.name for path in destination.rglob(EXPORT_MARKER_NAME)] == [EXPORT_MARKER_NAME]
    properties = (destination / "server.properties").read_text()
    assert "motd=Panel MOTD" in properties
    assert "server-port=25566" in properties
    assert "rcon.password=rcon-secret" in properties
    assert "max-players=42" in properties
    assert "white-list=true" in properties
    assert "enforce-whitelist=true" in properties
    assert "repo-secret" not in properties
    assert "server-port=25565" not in properties

    assert (destination / "eula.txt").read_text() == "eula=true\n"
    assert (destination / "user_jvm_args.txt").read_text() == ("-Xmx2G\n-Dtoken=plugin-secret\n")
    assert (destination / "plugins" / "sample" / "config.yml").read_text() == (
        "token: plugin-secret\n"
    )

    assert not (destination / ".git").exists()
    marker = json.loads(result.marker_path.read_text())
    assert marker["file_count"] == result.file_count
    assert marker["total_bytes"] == result.total_bytes
    all_files = [path for path in destination.rglob("*") if path.is_file()]
    assert len(all_files) == result.file_count + 1
    assert all(path.stat().st_nlink == 1 for path in all_files)


def test_optional_missing_class_a_is_skipped(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    entry = LockfileFile(
        path="mods/optional.jar",
        sha256="0" * 64,
        size=10,
        optional=True,
        env_server=EnvServer.OPTIONAL,
        origin=Origin.USER,
    )
    result = CleanExportService(layout).export(
        _request(
            layout,
            root,
            sha,
            destination=tmp_path / "export",
            lockfile=_lockfile(entry, lec=LecRef(key=PAPER_LEC_KEY)),
        )
    )
    assert not (result.root / "mods" / "optional.jar").exists()
    assert result.marker_path.is_file()


def test_mandatory_missing_class_a_fails_and_removes_export(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    entry = LockfileFile(
        path="server.jar",
        sha256="1" * 64,
        size=10,
        optional=False,
        env_server=EnvServer.REQUIRED,
        origin=Origin.PAPERMC,
    )
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="CAS blob is missing"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                lockfile=_lockfile(entry, lec=LecRef(key=PAPER_LEC_KEY)),
            )
        )
    assert not destination.exists()


def test_invalid_commit_fails_and_removes_export(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, _sha = repo
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="does not exist"):
        CleanExportService(layout).export(_request(layout, root, "0" * 40, destination=destination))
    assert not destination.exists()


def test_existing_destination_is_rejected(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    destination = tmp_path / "export"
    destination.mkdir()
    with pytest.raises(ValidationError, match="already exists"):
        CleanExportService(layout).export(_request(layout, root, sha, destination=destination))
    assert destination.is_dir()


def test_unresolved_secret_fails_and_removes_export(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="Unresolved secret"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                secrets={},
            )
        )
    assert not destination.exists()


def test_symlink_in_data_template_is_rejected(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    template = tmp_path / "data-template"
    target = tmp_path / "outside.txt"
    target.write_text("outside\n")
    template.mkdir()
    _write_marker(template)
    (template / "link").symlink_to(target)
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="symlink"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                data_template_dir=template,
            )
        )
    assert not destination.exists()


def test_data_template_without_marker_is_rejected(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    template = tmp_path / "data-template"
    _write(template, "world/level.dat", b"level-data")
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="marker"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                data_template_dir=template,
            )
        )
    assert not destination.exists()


def test_data_template_rejects_non_class_e_paths(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    template = tmp_path / "data-template"
    _write(template, "config/template.yml", "template: true\n")
    _write_marker(template)
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="class-E"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                data_template_dir=template,
            )
        )
    assert not destination.exists()


def test_class_c_overlay_rejects_non_class_c_paths(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    snapshot = tmp_path / "class-c-snapshot"
    _write(snapshot, "world/level.dat", b"level-data")
    _write_marker(snapshot)
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="class-C"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                class_c_overlay_dir=snapshot,
            )
        )
    assert not destination.exists()


def test_plain_copy_fallback_is_used_when_reflink_is_unavailable(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, root, sha = repo
    _prepare_lec(layout)
    jar_bytes = b"PK\x03\x04plain-copy"
    digest = ArtifactCas(layout.cas).put_bytes(jar_bytes)
    lockfile = _lockfile(
        LockfileFile(
            path="server.jar",
            sha256=digest,
            size=len(jar_bytes),
            optional=False,
            env_server=EnvServer.REQUIRED,
            origin=Origin.PAPERMC,
        ),
        lec=LecRef(key=PAPER_LEC_KEY),
    )
    monkeypatch.setattr(
        CleanExportService,
        "_try_reflink",
        staticmethod(lambda *_args: False),
    )
    result = CleanExportService(layout).export(
        _request(
            layout,
            root,
            sha,
            destination=tmp_path / "export",
            lockfile=lockfile,
        )
    )
    assert (result.root / "server.jar").read_bytes() == jar_bytes
    assert (result.root / "server.jar").stat().st_nlink == 1


def test_forge_lec_requires_non_empty_unix_args(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, root, sha = repo
    lec = layout.lec / "forge" / "1.20.1" / "47.2.0"
    _write(lec, FORGE_ARGS_RELPATH, b"")
    destination = tmp_path / "export"
    with pytest.raises(ValidationError, match="non-empty unix_args"):
        CleanExportService(layout).export(
            _request(
                layout,
                root,
                sha,
                destination=destination,
                lockfile=_lockfile(
                    lec=LecRef(key=FORGE_LEC_KEY),
                    loader=LoaderRef(id="forge", version="47.2.0"),
                    mc="1.20.1",
                ),
            )
        )
    assert not destination.exists()

    _write(lec, FORGE_ARGS_RELPATH, "-p libraries/forge.jar\n")
    result = CleanExportService(layout).export(
        _request(
            layout,
            root,
            sha,
            destination=tmp_path / "export-forge",
            lockfile=_lockfile(
                lec=LecRef(key=FORGE_LEC_KEY),
                loader=LoaderRef(id="forge", version="47.2.0"),
                mc="1.20.1",
            ),
        )
    )
    assert (result.root / FORGE_ARGS_RELPATH).read_text() == "-p libraries/forge.jar\n"


def test_archive_symlink_and_traversal_are_rejected(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
) -> None:
    layout, _root, _sha = repo
    service = CleanExportService(layout)
    target = tmp_path / "extract"
    target.mkdir()

    symlink_tar = tmp_path / "symlink.tar"
    with tarfile.open(symlink_tar, "w") as archive:
        member = tarfile.TarInfo("escape")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ValidationError, match="non-regular"):
        service._extract_archive(symlink_tar, target)

    traversal_tar = tmp_path / "traversal.tar"
    with tarfile.open(traversal_tar, "w") as archive:
        member = tarfile.TarInfo("../escape.txt")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValidationError, match="canonical relative path"):
        service._extract_archive(traversal_tar, target)


@pytest.mark.parametrize(
    "member_name",
    ["run.sh", "run.bat", "user_jvm_args.txt", "libraries/net/x.jar", ".fabric/server/x.jar"],
)
def test_archive_reserved_paths_are_rejected(
    repo: tuple[HostStateLayout, Path, str],
    tmp_path: Path,
    member_name: str,
) -> None:
    layout, _root, _sha = repo
    service = CleanExportService(layout)
    target = tmp_path / "extract"
    target.mkdir()
    archive_path = tmp_path / "reserved.tar"
    with tarfile.open(archive_path, "w") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValidationError, match="reserved for the export service"):
        service._extract_archive(archive_path, target)
