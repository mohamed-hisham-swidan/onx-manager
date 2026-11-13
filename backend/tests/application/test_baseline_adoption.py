"""Integration and unit tests for simple baseline adoption service.

P2-1 Core Substrate — B4d
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.allowlist import SymlinkEscapeError
from app.core.exceptions import (
    CasUnsupportedPlatformError,
    LockfileFormatError,
    LockfileInvalidError,
    ValidationError,
)
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.domain.aggregate import (
    Server,
    ServerDeployment,
    ServerId,
    ServerMode,
    ServerType,
)
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.application.baseline_adoption import (
    BaselineAdoptionResult,
    ensure_simple_baseline_lockfile,
)
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.server_tree_scanner import (
    ScannedFile,
    ScanReport,
)


@pytest.fixture(autouse=True)
def _setup_host_state_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    host_state_dir = tmp_path / "host-state"
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(host_state_dir))
    return host_state_dir


async def _seed_test_server(
    server_id: str,
    server_root: Path | None = None,
    *,
    root_path: str | None = None,
    mode: ServerMode = ServerMode.SIMPLE,
    server_type: ServerType = ServerType.PAPER,
    startup_jar: str = "paper-1.20.4-499.jar",
    working_directory: str = ".",
    has_deployment: bool = True,
) -> Server:
    deployment = None
    if has_deployment:
        resolved_root = root_path if root_path is not None else str(server_root or "")
        deployment = ServerDeployment(
            root_path=resolved_root,
            working_directory=working_directory,
            startup_jar=startup_jar,
        )

    server = Server.create(
        server_id=ServerId(server_id),
        name="test-server",
        server_type=server_type,
        minecraft_version=MinecraftVersion.parse("1.20.4"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(None),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=deployment,
        mode=mode,
    )

    async with UnitOfWork() as uow:
        repo = SQLServerRepository(uow.session)
        await repo.save(server)
        await uow.commit()

    return server


class TestBaselineAdoption:
    @pytest.mark.asyncio
    async def test_simple_paper_server_created_successfully(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        mods_dir = server_dir / "mods"
        mods_dir.mkdir()
        plugins_dir = server_dir / "plugins"
        plugins_dir.mkdir()

        (server_dir / "server.jar").write_bytes(b"content-server-jar")
        (mods_dir / "a.jar").write_bytes(b"content-mod-a")
        (plugins_dir / "b.jar").write_bytes(b"content-plugin-b")

        server_id = "srv-paper-1"
        await _seed_test_server(server_id, server_dir)

        res = await ensure_simple_baseline_lockfile(server_id)
        assert isinstance(res, BaselineAdoptionResult)
        assert res.status == "created"
        assert res.files_count == 3
        assert res.cas_ingested == 3
        assert res.quarantined == ()
        assert res.warnings == ()

        layout = ensure_host_state_layout()
        service = LockfileService(layout)
        assert service.exists(server_id) is True

        lockfile = service.read(server_id)
        assert lockfile is not None
        assert lockfile.format == 2
        assert lockfile.mc == "1.20.4"
        assert lockfile.loader.id == "paper"
        assert lockfile.loader.version == "499"
        assert lockfile.base_overrides == {}
        assert lockfile.lec is None
        assert lockfile.modpack is None

        file_paths = [f.path for f in lockfile.files]
        assert file_paths == ["mods/a.jar", "plugins/b.jar", "server.jar"]

        cas = ArtifactCas(layout.cas)
        for lf_file in lockfile.files:
            assert cas.has(lf_file.sha256) is True
            expected_hash = hashlib.sha256((server_dir / lf_file.path).read_bytes()).hexdigest()
            assert lf_file.sha256 == expected_hash

    @pytest.mark.asyncio
    async def test_rerun_returns_already_present_without_rescanning(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"jar-bytes")

        server_id = "srv-rerun"
        await _seed_test_server(server_id, server_dir)

        res1 = await ensure_simple_baseline_lockfile(server_id)
        assert res1.status == "created"

        # On re-run, scan_server_tree must not be called
        with patch(
            "app.modules.versioning.application.baseline_adoption.scan_server_tree",
            side_effect=AssertionError("scanner should not be called"),
        ):
            res2 = await ensure_simple_baseline_lockfile(server_id)

        assert res2.status == "already_present"
        assert res2.reason == "lockfile_already_exists"
        assert res2.files_count == 1

    @pytest.mark.asyncio
    async def test_malformed_existing_lockfile_propagates_domain_error(
        self, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"jar-bytes")

        server_id = "srv-malformed"
        await _seed_test_server(server_id, server_dir)

        layout = ensure_host_state_layout()
        service = LockfileService(layout)
        lockfile_path = service.path_for(server_id)
        lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        malformed_bytes = b'{"format": 2, "mc":'
        lockfile_path.write_bytes(malformed_bytes)

        with pytest.raises((LockfileFormatError, LockfileInvalidError)):
            await ensure_simple_baseline_lockfile(server_id)

        assert lockfile_path.read_bytes() == malformed_bytes

    @pytest.mark.asyncio
    async def test_advanced_server_skipped(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        server_id = "srv-advanced"
        await _seed_test_server(server_id, server_dir, mode=ServerMode.ADVANCED)

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "skipped"
        assert res.reason == "not_simple"

    @pytest.mark.asyncio
    async def test_no_deployment_skipped(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        server_id = "srv-no-dep"
        await _seed_test_server(server_id, server_dir, has_deployment=False)

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "skipped"
        assert res.reason == "no_deployment"

    @pytest.mark.asyncio
    async def test_deployment_empty_root_path_skipped_no_deployment(self) -> None:
        server_id = "srv-empty-root"
        await _seed_test_server(server_id, root_path="")

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "skipped"
        assert res.reason == "no_deployment"

    @pytest.mark.asyncio
    async def test_working_directory_honoured(self, tmp_path: Path) -> None:
        raw_root = tmp_path / "raw_root"
        raw_root.mkdir()
        sub_dir = raw_root / "minecraft_server"
        sub_dir.mkdir()

        (sub_dir / "server.jar").write_bytes(b"nested-server-jar")
        (raw_root / "decoy.jar").write_bytes(b"decoy-should-not-be-scanned")

        server_id = "srv-workdir"
        await _seed_test_server(
            server_id,
            raw_root,
            working_directory="minecraft_server",
        )

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "created"
        assert res.files_count == 1

        layout = ensure_host_state_layout()
        service = LockfileService(layout)
        lockfile = service.read(server_id)
        assert lockfile is not None
        assert [f.path for f in lockfile.files] == ["server.jar"]

    @pytest.mark.asyncio
    async def test_quarantined_evil_jar_recorded_and_excluded(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        config_dir = server_dir / "config"
        config_dir.mkdir()

        (server_dir / "server.jar").write_bytes(b"valid-server")
        (config_dir / "evil.jar").write_bytes(b"evil-jar-content")

        server_id = "srv-quarantine"
        await _seed_test_server(server_id, server_dir)

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "created"
        assert res.quarantined == ("config/evil.jar",)
        assert res.files_count == 1
        assert res.cas_ingested == 1

        layout = ensure_host_state_layout()
        service = LockfileService(layout)
        lockfile = service.read(server_id)
        assert lockfile is not None
        assert [f.path for f in lockfile.files] == ["server.jar"]

    @pytest.mark.asyncio
    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks only")
    async def test_symlinked_jar_skipped_and_directory_swap_fails(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        mods_dir = server_dir / "mods"
        mods_dir.mkdir()

        outside_target = tmp_path / "outside.jar"
        outside_target.write_bytes(b"outside-jar")
        os.symlink(outside_target, mods_dir / "sym.jar")
        (server_dir / "server.jar").write_bytes(b"normal-server")

        server_id = "srv-symlink"
        await _seed_test_server(server_id, server_dir)

        res = await ensure_simple_baseline_lockfile(server_id)
        assert res.status == "created"
        assert res.files_count == 1

        # Test safe-fd failure on directory swap
        server_id_swap = "srv-swap"
        server_dir_swap = tmp_path / "server_swap"
        server_dir_swap.mkdir()
        (server_dir_swap / "server.jar").write_bytes(b"server")
        await _seed_test_server(server_id_swap, server_dir_swap)

        layout = ensure_host_state_layout()
        service = LockfileService(layout)

        with (
            patch(
                "app.modules.versioning.application.baseline_adoption.open_safe_path_fd",
                side_effect=SymlinkEscapeError("Directory swapped for symlink"),
            ),
            pytest.raises(SymlinkEscapeError, match="Directory swapped for symlink"),
        ):
            await ensure_simple_baseline_lockfile(server_id_swap)

        assert service.exists(server_id_swap) is False

    @pytest.mark.asyncio
    async def test_truncated_scan_raises_validation_error(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"server")

        server_id = "srv-truncated"
        await _seed_test_server(server_id, server_dir)

        truncated_report = ScanReport(
            root=server_dir,
            files=(ScannedFile(path="server.jar", classification="A-JAR", size=6),),
            by_class={"A-JAR": 1},
            quarantined=(),
            skipped_symlinks=(),
            skipped_dirs=(),
            case_collisions=(),
            total_bytes=6,
            truncated=True,
        )

        layout = ensure_host_state_layout()
        service = LockfileService(layout)

        with (
            patch(
                "app.modules.versioning.application.baseline_adoption.scan_server_tree",
                return_value=truncated_report,
            ),
            pytest.raises(ValidationError, match="Server tree scan was truncated"),
        ):
            await ensure_simple_baseline_lockfile(server_id)

        assert service.exists(server_id) is False

    @pytest.mark.asyncio
    async def test_cas_ingest_failure_leaves_no_lockfile_or_tmp(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"server")

        server_id = "srv-cas-fail"
        await _seed_test_server(server_id, server_dir)

        layout = ensure_host_state_layout()
        service = LockfileService(layout)

        with (
            patch.object(ArtifactCas, "put_file", side_effect=OSError("CAS disk error")),
            pytest.raises(OSError, match="CAS disk error"),
        ):
            await ensure_simple_baseline_lockfile(server_id)

        assert service.exists(server_id) is False
        server_meta = layout.server_meta_dir(server_id)
        if server_meta.exists():
            assert list(server_meta.glob(".*.tmp")) == []

    @pytest.mark.asyncio
    @pytest.mark.skipif(os.name != "posix", reason="fsync error path is POSIX-only")
    async def test_copy_phase_error_cleans_up_staged_tmp(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"server")

        server_id = "srv-fsync-fail"
        await _seed_test_server(server_id, server_dir)

        layout = ensure_host_state_layout()
        service = LockfileService(layout)

        with (
            patch("os.fsync", side_effect=OSError(28, "No space left on device")),
            pytest.raises(OSError, match="No space left on device"),
        ):
            await ensure_simple_baseline_lockfile(server_id)

        assert service.exists(server_id) is False
        server_meta = layout.server_meta_dir(server_id)
        if server_meta.exists():
            assert list(server_meta.glob(".onx-adopt.*.tmp")) == []

    @pytest.mark.asyncio
    async def test_non_posix_preflight_raises_cas_unsupported(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server_data"
        server_dir.mkdir()
        (server_dir / "server.jar").write_bytes(b"server")

        server_id = "srv-non-posix"
        await _seed_test_server(server_id, server_dir)

        with (
            patch(
                "app.modules.versioning.application.baseline_adoption._platform_is_posix",
                return_value=False,
            ),
            pytest.raises(CasUnsupportedPlatformError, match="only supported on POSIX"),
        ):
            await ensure_simple_baseline_lockfile(server_id)

    @pytest.mark.asyncio
    async def test_containment_violation_rejected(self) -> None:
        layout = ensure_host_state_layout()
        server_inside_layout = layout.root / "sub_server"
        server_inside_layout.mkdir(parents=True, exist_ok=True)

        server_id = "srv-containment"
        await _seed_test_server(server_id, server_inside_layout)

        with pytest.raises(ValidationError, match="cannot be inside host-state directory"):
            await ensure_simple_baseline_lockfile(server_id)
