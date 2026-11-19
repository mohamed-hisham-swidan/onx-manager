"""P5.5-4 API tests: Modpacks, 1-Click Safe Upgrades, Panel CurseForge Key, LEC, RBAC & Activity."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.main import app
from app.modules.auth.infrastructure.models import UserModel
from app.modules.operations.application.services.operation_service import (
    get_operation_service,
    reset_operation_service,
)
from app.modules.operations.infrastructure.models import OperationModel
from app.modules.plugin.infrastructure.providers.base import PluginFile, PluginVersionsPage
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthProjectMeta,
    ModrinthVersionRecord,
)
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.application.modpack_upgrade_service import ModpackUpgradeService
from app.modules.versioning.application.refresh_orchestrator import (
    HealthGateResult,
    LiveRefreshService,
)
from app.modules.versioning.application.repo_lease import RepoLeaseManager
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    parse_lockfile,
)
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.branch_runtime_service import BranchStartResult
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import CleanExportService
from app.modules.versioning.infrastructure.download_allowlist import VerifiedDownloadResult
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.lec_builder import LecBuildResult
from app.modules.versioning.infrastructure.lec_store import LecStore
from app.modules.versioning.infrastructure.models import (
    LoaderEnvCacheEntryModel,
    PanelIntegrationSecretModel,
    ServerUpgradeModel,
)
from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRepository
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P5.5 CAS / LEC / staging swap routes require a POSIX host",
)

SIMPLE_SERVER_ID = "srv-p55-simple"
ADV_SERVER_ID = "srv-p55-adv"
CF_SECRET_KEY = "cf-super-secret-api-key-9876"


def _hashes(data: bytes) -> tuple[str, str, str]:
    return (
        hashlib.sha256(data).hexdigest(),
        hashlib.sha512(data).hexdigest(),
        hashlib.sha1(data).hexdigest(),
    )


def _make_mrpack_bytes(
    *,
    mc_version: str = "1.20.4",
    loader_key: str = "fabric-loader",
    loader_version: str = "0.16.0",
    files: list[dict[str, Any]] | None = None,
    overrides: dict[str, bytes] | None = None,
    client_overrides: dict[str, bytes] | None = None,
    name: str = "Test Modpack",
) -> bytes:
    buf = io.BytesIO()
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": name,
        "dependencies": {
            "minecraft": mc_version,
            loader_key: loader_version,
        },
        "files": files or [],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        for rel, content in (overrides or {}).items():
            zf.writestr(f"overrides/{rel}", content)
        for rel, content in (client_overrides or {}).items():
            zf.writestr(f"client-overrides/{rel}", content)
    return buf.getvalue()


def _make_cf_zip_bytes(
    *,
    mc_version: str = "1.20.4",
    loader_id: str = "fabric-0.16.0",
    files: list[dict[str, Any]] | None = None,
    overrides: dict[str, bytes] | None = None,
    name: str = "CF Test Pack",
) -> bytes:
    buf = io.BytesIO()
    manifest = {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": name,
        "version": "1.0.0",
        "minecraft": {
            "version": mc_version,
            "modLoaders": [{"id": loader_id, "primary": True}],
        },
        "overrides": "overrides",
        "files": files or [],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for rel, content in (overrides or {}).items():
            zf.writestr(f"overrides/{rel}", content)
    return buf.getvalue()


class _FakeModrinth:
    def __init__(self, updates: dict[str, ModrinthVersionRecord] | None = None) -> None:
        self._updates = updates or {}

    async def lookup_version_files_by_hashes(
        self, hashes: list[str], *, algorithm: str = "sha512"
    ) -> dict[str, ModrinthVersionRecord]:
        del hashes, algorithm
        return {}

    async def lookup_version_updates_by_hashes(
        self, hashes: list[str], **_kwargs: Any
    ) -> dict[str, ModrinthVersionRecord]:
        return {h: self._updates[h] for h in hashes if h in self._updates}

    async def get_versions_by_ids(
        self, version_ids: list[str]
    ) -> dict[str, ModrinthVersionRecord]:
        del version_ids
        return {}

    async def get_projects_by_ids(
        self, project_ids: list[str]
    ) -> dict[str, ModrinthProjectMeta]:
        del project_ids
        return {}

    async def get_project_versions(
        self, project_id: str, **_kwargs: Any
    ) -> PluginVersionsPage:
        del project_id
        return PluginVersionsPage(items=[], total=0)

    async def classify_client_only_jars_by_sha512(
        self, sha512_hashes: list[str]
    ) -> tuple[set[str], dict[str, ModrinthVersionRecord], dict[str, ModrinthProjectMeta]]:
        del sha512_hashes
        return set(), {}, {}


@dataclass
class _FakeBackupService:
    pinned: dict[str, bool] = field(default_factory=dict)
    snapshots: dict[str, bytes] = field(default_factory=dict)
    counter: int = 0

    async def create_pinned_backup(self, server_id: str, live_dir: Path) -> str:
        del server_id
        self.counter += 1
        bid = f"bkp-{self.counter}"
        self.pinned[bid] = True
        marker = live_dir / "world" / "level.dat"
        self.snapshots[bid] = marker.read_bytes() if marker.exists() else b""
        return bid

    async def restore_backup(self, server_id: str, backup_id: str, live_dir: Path) -> None:
        del server_id
        world_dir = live_dir / "world"
        world_dir.mkdir(parents=True, exist_ok=True)
        (world_dir / "level.dat").write_bytes(self.snapshots.get(backup_id, b""))

    async def set_pinned(self, server_id: str, backup_id: str, pinned: bool) -> None:
        del server_id
        self.pinned[backup_id] = pinned


@dataclass
class _FakeRuntime:
    running: bool = True

    def is_running(self) -> bool:
        return self.running

    def process_alive(self) -> bool:
        return self.running

    def stop(self) -> bool:
        self.running = False
        return True

    def start(self) -> bool:
        self.running = True
        return True

    def ready(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return True

    def boot_log(self) -> str:
        return 'Done (1.0s)! For help, type "help"'

    def last_boot_log(self) -> str:
        return 'Done (1.0s)! For help, type "help"'


class _FakeHealthGate:
    def __init__(self, passed: bool, reason: str | None = None) -> None:
        self._passed = passed
        self._reason = reason

    async def evaluate(self) -> HealthGateResult:
        return HealthGateResult(
            passed=self._passed,
            failed_step=None if self._passed else "nbt_data_version",
            reason=self._reason,
        )


class _FakeBranchRuntimeService:
    def __init__(self) -> None:
        self.started: list[Any] = []
        self.stopped: list[str] = []

    async def start_branch_runtime(self, request: Any) -> BranchStartResult:
        self.started.append(request)
        return BranchStartResult(
            runtime_id=f"rt-{uuid.uuid4().hex[:8]}",
            server_id=request.server_id,
            branch_name=request.branch_name,
            commit_sha=request.commit_sha or "0" * 40,
            container_name=f"onx-test-{request.server_id}",
            container_id="cid-1234",
            port_set=HostPortSet(game_port=25610, rcon_port=25611),
            export_path=str(request.server_root),
            data_template_id=request.data_template_id,
            allow_public_test_join=request.allow_public_test_join,
            memory_max_mb=request.requested_memory_mb or 2048,
            cpu_cores=request.requested_cpu_cores or 2,
            uncommitted_changes_warning=False,
        )

    async def stop_branch_runtime(
        self, server_id: str, server_root: str | Path, branch_name: str
    ) -> None:
        del server_id, server_root
        self.stopped.append(branch_name)


class _FakeLecBuilder:
    def __init__(self, lec_store: LecStore) -> None:
        self._store = lec_store

    async def ensure_lec(self, lec_key: str) -> LecBuildResult:
        staging = self._store.create_staging_dir(lec_key)
        lib = staging / "libraries" / "net" / "fabricmc" / "fabric-loader" / "loader.jar"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_bytes(b"loader-payload")
        meta = await self._store.publish_staged_entry(staging, lec_key, java_major=21)
        return LecBuildResult(
            lec_key=lec_key,
            entry_dir=self._store.entry_dir(lec_key),
            file_count=meta.file_count,
            total_bytes=meta.total_bytes,
            java_major=meta.java_major,
            unix_args_relpath=None,
        )


def _write_basic_server_tree(root: Path, *, level_bytes: bytes = b"world-v1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text("motd=P554\n", encoding="utf-8")
    (root / "server.jar").write_bytes(b"server-jar-v1")
    (root / "world").mkdir(exist_ok=True)
    (root / "world" / "level.dat").write_bytes(level_bytes)


async def _wait_for_operation(operation_id: str, timeout: float = 15.0) -> OperationModel:
    deadline = asyncio.get_running_loop().time() + timeout
    row: OperationModel | None = None
    while asyncio.get_running_loop().time() < deadline:
        async with database.session_factory() as session:
            row = await session.get(OperationModel, operation_id)
        if row is not None and row.status in ("COMPLETED", "FAILED"):
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"Operation {operation_id} did not finish: {row!r}")


@pytest.fixture
async def p55_api(
    client: AsyncClient,
    created_user: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    buses: tuple[Any, Any, Any],
) -> Any:
    from app.api.v1.routers import modpacks_upgrades as router_mod

    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_MASTER_KEK", "22" * 32)
    monkeypatch.delenv("ONX_CURSEFORGE_API_KEY", raising=False)

    reset_operation_service()
    layout = ensure_host_state_layout()
    cas = ArtifactCas(layout.cas)
    lec_store = LecStore(layout)
    fake_lec_builder = _FakeLecBuilder(lec_store)
    fake_branch_runtime = _FakeBranchRuntimeService()
    fake_backup = _FakeBackupService()
    fake_runtime = _FakeRuntime()
    health_gate_state = {"passed": True, "reason": None}
    download_map: dict[str, bytes] = {}

    async def _fake_download_to_cas(
        url: str,
        target_cas: ArtifactCas,
        *,
        expected_size: int | None = None,
        expected_sha512: str | None = None,
        expected_sha1: str | None = None,
        **_kwargs: Any,
    ) -> VerifiedDownloadResult:
        del expected_size, expected_sha512, expected_sha1
        data = download_map[url]
        sha256, sha512, sha1 = _hashes(data)
        target_cas.put_bytes(data)
        return VerifiedDownloadResult(
            sha256=sha256,
            sha512=sha512,
            sha1=sha1,
            size=len(data),
            final_url=url,
            redirect_count=0,
        )

    fake_modrinth = _FakeModrinth()
    upgrade_service = ModpackUpgradeService(
        layout,
        database.session_factory,
        cas=cas,
        modrinth_client=fake_modrinth,  # type: ignore[arg-type]
        lec_store=lec_store,
        lec_builder=fake_lec_builder,  # type: ignore[arg-type]
        branch_runtime_service=fake_branch_runtime,  # type: ignore[arg-type]
        download_to_cas=_fake_download_to_cas,
    )

    simple_root = tmp_path / "servers" / SIMPLE_SERVER_ID
    adv_root = tmp_path / "servers" / ADV_SERVER_ID
    _write_basic_server_tree(simple_root)
    _write_basic_server_tree(adv_root)

    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SIMPLE_SERVER_ID,
                name="Simple P55",
                server_type="fabric",
                minecraft_version="1.20.4",
                status="STOPPED",
                mode="simple",
                provider="docker",
                root_path=str(simple_root),
                owner_id=created_user["user_id"],
            )
        )
        session.add(
            ServerModel(
                id=ADV_SERVER_ID,
                name="Advanced P55",
                server_type="fabric",
                minecraft_version="1.20.4",
                status="STOPPED",
                mode="advanced",
                provider="docker",
                root_path=str(adv_root),
                owner_id=created_user["user_id"],
            )
        )
        await session.commit()

    async def _refresh_factory(server_id: str) -> LiveRefreshService:
        lockfile = LockfileService(layout).read(server_id)
        journal_repo = RefreshJournalRepository(
            layout, session_factory=database.session_factory
        )
        class_c = ClassCSnapshotService(layout, session_factory=database.session_factory)
        clean_export = CleanExportService(layout, cas=cas)

        def _adv_stage(
            staging: Path,
            commit_sha: str,
            *,
            export_id: str,
            fencing_verifier: Any,
        ) -> None:
            del commit_sha
            lf = LockfileService(layout).read(server_id) or lockfile
            assert lf is not None
            dest = clean_export._prepare_destination(staging)
            clean_export._materialize_class_a(dest, lf)
            if lf.lec is not None and lec_store.is_ready(lf.lec.key):
                lec_store.attach_to_target(lf.lec.key, dest)
            for rel, digest in lf.base_overrides.items():
                if cas.has(digest):
                    target_file = dest / rel
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    with cas.open_blob(digest) as fh:
                        target_file.write_bytes(fh.read())
            (dest / "eula.txt").write_text("eula=true\n", encoding="utf-8")
            (dest / "server.properties").write_text("motd=upgraded\n", encoding="utf-8")
            fencing_verifier()
            fc, tb = clean_export._measure_export(dest)
            clean_export._write_marker(dest, fc, tb, export_id)

        return LiveRefreshService(
            layout,
            repository=journal_repo,
            class_c_service=class_c,
            backup_service=fake_backup,
            runtime=fake_runtime,
            stage_export=_adv_stage if server_id == ADV_SERVER_ID else None,
            repo_lease=RepoLeaseManager(
                locks_dir=layout.locks, session_factory=database.session_factory
            ),
            servers_data_dir=tmp_path / "servers",
        )

    def _health_gate_factory(_upgrade: Any, _server: ServerModel) -> _FakeHealthGate:
        return _FakeHealthGate(
            passed=bool(health_gate_state["passed"]),
            reason=health_gate_state["reason"],  # type: ignore[arg-type]
        )

    app.dependency_overrides[router_mod.get_lec_store] = lambda: lec_store
    app.dependency_overrides[router_mod.get_lec_builder] = lambda: fake_lec_builder
    app.dependency_overrides[router_mod.get_modpack_upgrade_service] = lambda: upgrade_service
    app.dependency_overrides[router_mod.get_upgrade_refresh_service_factory] = (
        lambda: _refresh_factory
    )
    app.dependency_overrides[router_mod.get_upgrade_health_gate_factory] = (
        lambda: _health_gate_factory
    )

    admin_headers = await _seed_api_key_header(
        client, created_user["user_id"], ["admin:full"]
    )

    try:
        yield SimpleNamespace(
            client=client,
            headers=admin_headers,
            user=created_user,
            tmp_path=tmp_path,
            layout=layout,
            cas=cas,
            lec_store=lec_store,
            lec_builder=fake_lec_builder,
            branch_runtime=fake_branch_runtime,
            backup=fake_backup,
            runtime=fake_runtime,
            health_gate_state=health_gate_state,
            download_map=download_map,
            fake_modrinth=fake_modrinth,
            upgrade_service=upgrade_service,
            simple_root=simple_root,
            adv_root=adv_root,
            event_bus=buses[2],
        )
    finally:
        executor = get_operation_service(buses[2]).executor
        for task in list(executor._running_tasks.values()):
            if not task.done():
                task.cancel()
        executor._running_tasks.clear()
        for key in (
            router_mod.get_lec_store,
            router_mod.get_lec_builder,
            router_mod.get_modpack_upgrade_service,
            router_mod.get_upgrade_refresh_service_factory,
            router_mod.get_upgrade_health_gate_factory,
        ):
            app.dependency_overrides.pop(key, None)
        reset_operation_service()


@pytest.mark.asyncio
async def test_curseforge_integration_key_lifecycle_and_secret_hygiene(p55_api: Any) -> None:
    api = p55_api
    # 1. Initially unconfigured
    res = await api.client.get(
        "/api/v1/settings/integrations/curseforge", headers=api.headers
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"configured": False, "source": "none", "hint": None}

    # 2. Validation: extra="forbid", blank/control-char rejected with 422
    bad_extra = await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": CF_SECRET_KEY, "unexpected": True},
        headers=api.headers,
    )
    assert bad_extra.status_code == 422

    bad_ctrl = await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": "abc\ndef"},
        headers=api.headers,
    )
    assert bad_ctrl.status_code == 422

    bad_blank = await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": "   "},
        headers=api.headers,
    )
    assert bad_blank.status_code == 422

    # 3. PUT encrypts & stores key, returns hint only; raw key never appears in HTTP or DB
    put_res = await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": CF_SECRET_KEY},
        headers=api.headers,
    )
    assert put_res.status_code == 200, put_res.text
    body = put_res.json()
    assert body == {"configured": True, "source": "panel", "hint": "***...9876"}
    assert CF_SECRET_KEY not in put_res.text

    get_res = await api.client.get(
        "/api/v1/settings/integrations/curseforge", headers=api.headers
    )
    assert get_res.status_code == 200
    assert get_res.json() == {"configured": True, "source": "panel", "hint": "***...9876"}
    assert CF_SECRET_KEY not in get_res.text

    async with database.session_factory() as session:
        row = await session.get(PanelIntegrationSecretModel, "curseforge_api_key")
        assert row is not None
        row_any = cast(Any, row)
        assert CF_SECRET_KEY.encode("utf-8") not in bytes(row_any.ciphertext)
        assert row_any.key_hint == "***...9876"

    # 4. DELETE removes DB row and returns none
    del_res = await api.client.delete(
        "/api/v1/settings/integrations/curseforge", headers=api.headers
    )
    assert del_res.status_code == 200
    assert del_res.json() == {"configured": False, "source": "none", "hint": None}


@pytest.mark.asyncio
async def test_mrpack_inspect_and_install_simple_and_advanced_modes(p55_api: Any) -> None:
    api = p55_api
    mod_bytes = b"modrinth-server-jar-bytes"
    _, mod_sha512, mod_sha1 = _hashes(mod_bytes)
    mod_url = "https://cdn.modrinth.com/data/modA/versions/1.0/modA.jar"
    api.download_map[mod_url] = mod_bytes

    client_mod_bytes = b"client-only-jar"
    _, cm_sha512, cm_sha1 = _hashes(client_mod_bytes)

    mrpack = _make_mrpack_bytes(
        mc_version="1.20.4",
        loader_key="fabric-loader",
        loader_version="0.16.0",
        files=[
            {
                "path": "mods/server-mod.jar",
                "hashes": {"sha1": mod_sha1, "sha512": mod_sha512},
                "fileSize": len(mod_bytes),
                "downloads": [mod_url],
                "env": {"server": "required", "client": "required"},
            },
            {
                "path": "mods/client-only.jar",
                "hashes": {"sha1": cm_sha1, "sha512": cm_sha512},
                "fileSize": len(client_mod_bytes),
                "downloads": ["https://cdn.modrinth.com/data/client/1.0/client.jar"],
                "env": {"server": "unsupported", "client": "required"},
            },
        ],
        overrides={"config/pack.toml": b"enabled = true\n"},
        client_overrides={"config/client-only.toml": b"client = true\n"},
    )

    # Pre-warm LEC so install attaches it
    await api.lec_builder.ensure_lec("fabric/1.20.4/0.16.0/1.0.1")

    # 1. Inspect Simple mode: filters client-only and ignores client-overrides
    # before writing server_root
    inspect_res = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/inspect",
        files={"file": ("pack.mrpack", mrpack, "application/zip")},
        headers=api.headers,
    )
    assert inspect_res.status_code == 200, inspect_res.text
    inspected = inspect_res.json()
    assert inspected["has_unresolved_blockers"] is False
    assert [f["path"] for f in inspected["plan"]["files"]] == ["mods/server-mod.jar"]
    assert inspected["plan"]["skipped_client_files"] == ["mods/client-only.jar"]
    assert "ignored_override_layer:client-overrides" in inspected["plan"]["warnings"]
    assert not (api.simple_root / "config" / "pack.toml").exists()
    assert not (api.simple_root / "mods" / "server-mod.jar").exists()

    # 2. Install Simple mode (sync)
    install_res = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/install",
        json={"staged_pack_id": inspected["staged_pack_id"]},
        headers=api.headers,
    )
    assert install_res.status_code == 200, install_res.text
    inst = install_res.json()
    assert inst["status"] == "confirmed"
    assert inst["files_installed"] == 1
    assert inst["base_overrides_count"] == 1
    assert inst["lec_key"] == "fabric/1.20.4/0.16.0/1.0.1"
    assert (api.simple_root / "config" / "pack.toml").read_bytes() == b"enabled = true\n"
    assert (api.simple_root / "mods" / "server-mod.jar").read_bytes() == mod_bytes
    host_lf = LockfileService(api.layout).read(SIMPLE_SERVER_ID)
    assert host_lf is not None
    assert host_lf.mc == "1.20.4"
    assert host_lf.lec is not None and host_lf.lec.key == "fabric/1.20.4/0.16.0/1.0.1"

    # 3. Inspect + Install Advanced mode with async_mode=True (202 -> COMPLETED)
    adv_inspect = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/modpacks/inspect",
        files={"file": ("pack.mrpack", mrpack, "application/zip")},
        headers=api.headers,
    )
    assert adv_inspect.status_code == 200, adv_inspect.text
    adv_staged_id = adv_inspect.json()["staged_pack_id"]

    adv_install = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/modpacks/install",
        json={"staged_pack_id": adv_staged_id, "async_mode": True},
        headers=api.headers,
    )
    assert adv_install.status_code == 202, adv_install.text
    op_id = adv_install.json()["operation_id"]
    assert op_id is not None
    op_row = await _wait_for_operation(op_id)
    assert str(op_row.status) == "COMPLETED"

    main_wt = api.adv_root / ".onx" / "worktrees" / "main"
    assert (main_wt / "onx-jars.lock.json").is_file()
    committed_lf = parse_lockfile((main_wt / "onx-jars.lock.json").read_bytes())
    assert committed_lf.mc == "1.20.4"
    assert "config/pack.toml" in committed_lf.base_overrides


@pytest.mark.asyncio
async def test_curseforge_missing_key_and_manual_download_unblock(
    p55_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = p55_api
    manual_jar = b"curseforge-manual-mod-jar"
    _, _sha512, sha1 = _hashes(manual_jar)
    cf_zip = _make_cf_zip_bytes(
        files=[{"projectID": 1001, "fileID": 2002, "required": True}],
        overrides={"config/cf.cfg": b"cf=true\n"},
    )

    # 1. No CurseForge key configured -> 409 CURSEFORGE_API_KEY_MISSING (never 401!)
    no_key = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/inspect",
        files={"file": ("cf.zip", cf_zip, "application/zip")},
        headers=api.headers,
    )
    assert no_key.status_code == 409, no_key.text
    assert no_key.json()["code"] == "CURSEFORGE_API_KEY_MISSING"

    # 2. Configure key via PUT /settings/integrations/curseforge
    put_res = await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": CF_SECRET_KEY},
        headers=api.headers,
    )
    assert put_res.status_code == 200

    # Mock CurseForge batch API returning downloadUrl: null
    async def _fake_fetch_file_metadata(
        api_key: str, file_ids: list[int], **_kwargs: Any
    ) -> dict[int, dict[str, Any]]:
        assert api_key == CF_SECRET_KEY
        assert file_ids == [2002]
        return {
            2002: {
                "id": 2002,
                "modId": 1001,
                "fileName": "blocked-mod.jar",
                "fileLength": len(manual_jar),
                "downloadUrl": None,
                "hashes": [{"algo": 1, "value": sha1}],
            }
        }

    monkeypatch.setattr(
        "app.modules.versioning.infrastructure.curseforge_adapter._fetch_file_metadata",
        _fake_fetch_file_metadata,
    )

    inspected_res = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/inspect",
        files={"file": ("cf.zip", cf_zip, "application/zip")},
        headers=api.headers,
    )
    assert inspected_res.status_code == 200, inspected_res.text
    inspected = inspected_res.json()
    assert inspected["has_unresolved_blockers"] is True
    assert len(inspected["plan"]["manual_blockers"]) == 1
    staged_id = inspected["staged_pack_id"]

    # 3. Attempting install before manual upload returns 409 MANUAL_DOWNLOAD_REQUIRED
    blocked_install = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/install",
        json={"staged_pack_id": staged_id},
        headers=api.headers,
    )
    assert blocked_install.status_code == 409, blocked_install.text
    assert blocked_install.json()["code"] == "MANUAL_DOWNLOAD_REQUIRED"

    # 4. Corrupted manual upload is rejected (503/422)
    bad_upload = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{staged_id}/manual-upload",
        files={"file": ("blocked-mod.jar", b"wrong-bytes", "application/java-archive")},
        data={"file_id": "2002"},
        headers=api.headers,
    )
    assert bad_upload.status_code in (422, 503), bad_upload.text

    # 5. Verified manual upload clears the blocker and allows install to succeed
    good_upload = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{staged_id}/manual-upload",
        files={"file": ("blocked-mod.jar", manual_jar, "application/java-archive")},
        data={"file_id": "2002"},
        headers=api.headers,
    )
    assert good_upload.status_code == 200, good_upload.text
    assert good_upload.json()["status"] == "planned"
    assert good_upload.json()["manual_blockers"][0]["resolved"] is True

    ok_install = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/install",
        json={"staged_pack_id": staged_id},
        headers=api.headers,
    )
    assert ok_install.status_code == 200, ok_install.text
    assert ok_install.json()["status"] == "confirmed"
    assert (api.simple_root / "mods" / "blocked-mod.jar").read_bytes() == manual_jar


@pytest.mark.asyncio
async def test_one_click_upgrade_simple_and_advanced_e2e_confirm_and_rollback(
    p55_api: Any,
) -> None:
    api = p55_api
    # Seed initial mod + lockfile in Simple and Advanced servers
    old_mod = b"old-mod-v1"
    old_sha256, old_sha512, old_sha1 = _hashes(old_mod)
    api.cas.put_bytes(old_mod)

    new_mod = b"new-mod-v2"
    new_sha256, new_sha512, new_sha1 = _hashes(new_mod)
    new_url = "https://cdn.modrinth.com/data/proj1/versions/v2/mod-v2.jar"
    api.download_map[new_url] = new_mod

    v3_mod = b"new-mod-v3"
    _, v3_sha512, v3_sha1 = _hashes(v3_mod)
    v3_url = "https://cdn.modrinth.com/data/proj1/versions/v3/mod-v3.jar"
    api.download_map[v3_url] = v3_mod

    api.fake_modrinth._updates[old_sha512] = ModrinthVersionRecord(
        version_id="v2",
        project_id="proj1",
        name="Mod v2",
        version_number="2.0.0",
        version_type="release",
        game_versions=("1.21.1", "1.21.2"),
        loaders=("fabric",),
        environment=None,
        files=(
            PluginFile(
                url=new_url,
                filename="mod-v2.jar",
                size_bytes=len(new_mod),
                sha1=new_sha1,
                sha512=new_sha512,
                primary=True,
            ),
        ),
        dependencies=(),
    )
    api.fake_modrinth._updates[new_sha512] = ModrinthVersionRecord(
        version_id="v3",
        project_id="proj1",
        name="Mod v3",
        version_number="3.0.0",
        version_type="release",
        game_versions=("1.21.2",),
        loaders=("fabric",),
        environment=None,
        files=(
            PluginFile(
                url=v3_url,
                filename="mod-v3.jar",
                size_bytes=len(v3_mod),
                sha1=v3_sha1,
                sha512=v3_sha512,
                primary=True,
            ),
        ),
        dependencies=(),
    )

    await api.lec_builder.ensure_lec("fabric/1.20.4/0.16.0/1.0.1")
    await api.lec_builder.ensure_lec("fabric/1.21.1/0.16.5/1.0.1")
    await api.lec_builder.ensure_lec("fabric/1.21.2/0.16.5/1.0.1")

    # Seed Simple server baseline lockfile
    simple_lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.16.0"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/mod.jar",
                sha256=old_sha256,
                size=len(old_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                sha512=old_sha512,
                sha1=old_sha1,
                project_id="proj1",
                version_id="v1",
            ),
        ),
        lec=None,
    )
    LockfileService(api.layout).write(SIMPLE_SERVER_ID, simple_lf)
    (api.simple_root / "mods").mkdir(parents=True, exist_ok=True)
    (api.simple_root / "mods" / "mod.jar").write_bytes(old_mod)

    # ── Simple Mode: Plan -> Prepare-test (409) -> Apply -> Banner + 72h -> Confirm
    plan_res = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/plan",
        json={
            "target_mc": "1.21.1",
            "target_loader_id": "fabric",
            "target_loader_version": "0.16.5",
            "target_lec_key": "fabric/1.21.1/0.16.5/1.0.1",
        },
        headers=api.headers,
    )
    assert plan_res.status_code == 201, plan_res.text
    simple_upg = plan_res.json()
    simple_upg_id = simple_upg["id"]
    assert simple_upg["status"] == "planned"
    assert simple_upg["mode"] == "simple"

    prep_simple = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{simple_upg_id}/prepare-test",
        json={},
        headers=api.headers,
    )
    assert prep_simple.status_code == 409
    assert prep_simple.json()["code"] == "SERVER_MODE_VERSIONING_DISABLED"

    apply_simple = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{simple_upg_id}/apply",
        json={},
        headers=api.headers,
    )
    assert apply_simple.status_code == 200, apply_simple.text
    applied = apply_simple.json()
    assert applied["status"] == "active_pinned"
    assert applied["pinned_until_confirm"] is True
    assert applied["health_gate_passed"] is True

    # Age updated_at by 73h to test reminder_72h_overdue=True
    async with database.session_factory() as session:
        row = await session.get(ServerUpgradeModel, simple_upg_id)
        assert row is not None
        cast(Any, row).updated_at = datetime.now(UTC) - timedelta(hours=73)
        await session.commit()

    list_res = await api.client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades", headers=api.headers
    )
    assert list_res.status_code == 200, list_res.text
    listed = list_res.json()
    assert listed["banner_active"] is True
    assert listed["reminder_72h_overdue"] is True
    assert listed["active_upgrade"]["id"] == simple_upg_id

    get_res = await api.client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{simple_upg_id}",
        headers=api.headers,
    )
    assert get_res.status_code == 200
    assert get_res.json()["reminder_72h_overdue"] is True

    confirm_res = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{simple_upg_id}/confirm",
        headers=api.headers,
    )
    assert confirm_res.status_code == 200, confirm_res.text
    assert confirm_res.json()["status"] == "confirmed"
    assert confirm_res.json()["pinned_until_confirm"] is False

    list_after_confirm = await api.client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades", headers=api.headers
    )
    assert list_after_confirm.json()["banner_active"] is False

    # ── Simple Mode Upgrade: Health Gate Fail -> Automatic Triad Rollback
    plan_fail = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/plan",
        json={
            "target_mc": "1.21.2",
            "target_loader_id": "fabric",
            "target_loader_version": "0.16.5",
            "target_lec_key": "fabric/1.21.2/0.16.5/1.0.1",
        },
        headers=api.headers,
    )
    # Force an update entry by resetting health gate to fail
    assert plan_fail.status_code == 201, plan_fail.text
    fail_upg_id = plan_fail.json()["id"]
    api.health_gate_state["passed"] = False
    api.health_gate_state["reason"] = "DataVersion below target"

    apply_fail = await api.client.post(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{fail_upg_id}/apply",
        json={},
        headers=api.headers,
    )
    assert apply_fail.status_code == 200, apply_fail.text
    assert apply_fail.json()["status"] == "rolled_back"
    assert apply_fail.json()["health_gate_passed"] is False
    # Simple host lockfile restored back to 1.21.1
    restored_lf = LockfileService(api.layout).read(SIMPLE_SERVER_ID)
    assert restored_lf is not None
    assert restored_lf.mc == "1.21.1"
    api.health_gate_state["passed"] = True
    api.health_gate_state["reason"] = None

    # ── Advanced Mode Upgrade: Plan -> Prepare-Test -> Apply (active_pinned) -> Emergency Rollback
    adv_lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.16.0"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/mod.jar",
                sha256=old_sha256,
                size=len(old_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                sha512=old_sha512,
                sha1=old_sha1,
                project_id="proj1",
                version_id="v1",
            ),
        ),
    )
    GitRepositoryService(api.layout).initialize(ADV_SERVER_ID, api.adv_root, adv_lf)
    LockfileService(api.layout).write(ADV_SERVER_ID, adv_lf)

    adv_plan = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/upgrades/plan",
        json={
            "target_mc": "1.21.1",
            "target_loader_id": "fabric",
            "target_loader_version": "0.16.5",
            "target_lec_key": "fabric/1.21.1/0.16.5/1.0.1",
        },
        headers=api.headers,
    )
    assert adv_plan.status_code == 201, adv_plan.text
    adv_upg_id = adv_plan.json()["id"]

    prep_adv = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/upgrades/{adv_upg_id}/prepare-test",
        json={"target_slug": "1.21.1", "start_test": True},
        headers=api.headers,
    )
    assert prep_adv.status_code == 200, prep_adv.text
    prep_body = prep_adv.json()
    assert prep_body["upgrade"]["status"] == "testing"
    assert prep_body["upgrade"]["upgrade_branch"] == "upgrade/1.21.1"
    assert prep_body["runtime"] is not None
    assert prep_body["runtime"]["branch_name"] == "upgrade/1.21.1"

    apply_adv = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/upgrades/{adv_upg_id}/apply",
        json={},
        headers=api.headers,
    )
    assert apply_adv.status_code == 200, apply_adv.text
    assert apply_adv.json()["status"] == "active_pinned"

    rollback_adv = await api.client.post(
        f"/api/v1/servers/{ADV_SERVER_ID}/upgrades/{adv_upg_id}/rollback",
        json={"reason": "player reported issue"},
        headers=api.headers,
    )
    assert rollback_adv.status_code == 200, rollback_adv.text
    assert rollback_adv.json()["status"] == "rolled_back"

    # Verify Activity Log captured all P5.5 upgrade lifecycle events
    simple_act = await api.client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/activity?limit=100",
        headers=api.headers,
    )
    assert simple_act.status_code == 200
    simple_types = {item["event_type"] for item in simple_act.json()["items"]}
    assert {
        "upgrade.planned",
        "upgrade.applied",
        "upgrade.confirmed",
        "upgrade.rolled_back",
    } <= simple_types

    adv_act = await api.client.get(
        f"/api/v1/servers/{ADV_SERVER_ID}/activity?limit=100",
        headers=api.headers,
    )
    assert adv_act.status_code == 200
    adv_types = {item["event_type"] for item in adv_act.json()["items"]}
    assert {
        "upgrade.planned",
        "upgrade.branch_prepared",
        "upgrade.test_started",
        "upgrade.applied",
        "upgrade.rolled_back",
    } <= adv_types


@pytest.mark.asyncio
async def test_p55_server_settings_and_host_lec_endpoints(p55_api: Any) -> None:
    api = p55_api

    # 1. P5.5 Server Settings in Simple & Advanced modes
    for sid in (SIMPLE_SERVER_ID, ADV_SERVER_ID):
        g = await api.client.get(
            f"/api/v1/servers/{sid}/p55-settings", headers=api.headers
        )
        assert g.status_code == 200, g.text
        assert g.json()["health_gate_boot_timeout_seconds"] == 300
        assert "cdn.modrinth.com" in g.json()["default_allowed_hosts"]

        u = await api.client.put(
            f"/api/v1/servers/{sid}/p55-settings",
            json={
                "health_gate_boot_timeout_seconds": 600,
                "install_optional_server_files": False,
                "allow_experimental_paper_builds": True,
                "download_host_allowlist": ["Example.COM", "example.com"],
            },
            headers=api.headers,
        )
        assert u.status_code == 200, u.text
        assert u.json()["health_gate_boot_timeout_seconds"] == 600
        assert u.json()["install_optional_server_files"] is False
        assert u.json()["allow_experimental_paper_builds"] is True
        assert u.json()["download_host_allowlist"] == ["example.com"]

    # Bounds & host validation (422)
    for bad_timeout in (299, 901):
        r = await api.client.put(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/p55-settings",
            json={"health_gate_boot_timeout_seconds": bad_timeout},
            headers=api.headers,
        )
        assert r.status_code == 422

    for bad_host in ("127.0.0.1", "https://example.com", "*.example.com"):
        r = await api.client.put(
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/p55-settings",
            json={"download_host_allowlist": [bad_host]},
            headers=api.headers,
        )
        assert r.status_code == 422

    # 2. Host LEC endpoints: prewarm (sync 201 + async 202), entries, gc
    pre_sync = await api.client.post(
        "/api/v1/lec/prewarm",
        json={
            "loader_id": "fabric",
            "mc_version": "1.20.4",
            "loader_version": "0.16.0",
            "installer_version": "1.0.1",
            "async_mode": False,
        },
        headers=api.headers,
    )
    assert pre_sync.status_code == 201, pre_sync.text
    assert pre_sync.json()["lec_key"] == "fabric/1.20.4/0.16.0/1.0.1"
    assert pre_sync.json()["status"] == "ready"

    pre_async = await api.client.post(
        "/api/v1/lec/prewarm",
        json={"lec_key": "paper/1.20.4/499", "async_mode": True},
        headers=api.headers,
    )
    assert pre_async.status_code == 202, pre_async.text
    op_row = await _wait_for_operation(pre_async.json()["operation_id"])
    assert str(op_row.status) == "COMPLETED"

    entries_res = await api.client.get("/api/v1/lec/entries", headers=api.headers)
    assert entries_res.status_code == 200, entries_res.text
    keys = [e["lec_key"] for e in entries_res.json()]
    assert "fabric/1.20.4/0.16.0/1.0.1" in keys
    assert "paper/1.20.4/499" in keys

    # Age paper/1.20.4/499 > 7 days and run GC
    async with database.session_factory() as session:
        row = await session.get(LoaderEnvCacheEntryModel, "paper/1.20.4/499")
        assert row is not None
        cast(Any, row).last_used_at = datetime.now(UTC) - timedelta(days=10)
        await session.commit()

    gc_res = await api.client.post(
        "/api/v1/lec/gc", json={"min_age_days": 7}, headers=api.headers
    )
    assert gc_res.status_code == 200, gc_res.text
    assert "paper/1.20.4/499" in gc_res.json()["pruned_lec_keys"]


@pytest.mark.asyncio
async def test_p55_rbac_unauthenticated_and_activity_log_zero_secret_leakage(
    p55_api: Any,
) -> None:
    api = p55_api

    # Create a separate viewer user with server.{id}.view + settings:read
    viewer_id = "usr-p55-viewer"
    async with database.session_factory() as session:
        session.add(
            UserModel(
                id=viewer_id,
                email="viewer@test.com",
                display_name="Viewer",
                password_hash="not-used",
            )
        )
        session.add(
            ServerMembershipModel(
                id="mem-p55-viewer",
                server_id=SIMPLE_SERVER_ID,
                user_id=viewer_id,
                role="viewer",
            )
        )
        await session.commit()
    viewer_headers = await _seed_api_key_header(
        api.client, viewer_id, ["settings:read"]
    )

    # Seed an upgrade row so GET /upgrades/{id} returns 200 for viewer
    upg_row = await api.upgrade_service._upgrade_repo.create(
        server_id=SIMPLE_SERVER_ID,
        target_mc="1.21.1",
        target_loader_id="fabric",
        target_loader_version="0.16.5",
        mode="simple",
    )

    # 1. All 18 routes reject unauthenticated calls with 401
    all_routes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/api/v1/settings/integrations/curseforge", None),
        ("PUT", "/api/v1/settings/integrations/curseforge", {"api_key": CF_SECRET_KEY}),
        ("DELETE", "/api/v1/settings/integrations/curseforge", None),
        ("GET", "/api/v1/lec/entries", None),
        ("POST", "/api/v1/lec/prewarm", {"lec_key": "paper/1.20.4/499"}),
        ("POST", "/api/v1/lec/gc", {"min_age_days": 7}),
        ("GET", f"/api/v1/servers/{SIMPLE_SERVER_ID}/p55-settings", None),
        ("PUT", f"/api/v1/servers/{SIMPLE_SERVER_ID}/p55-settings", {}),
        ("POST", f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/inspect", None),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/modpacks/install",
            {"staged_pack_id": "x"},
        ),
        ("GET", f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades", None),
        ("GET", f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}", None),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/plan",
            {
                "target_mc": "1.21.1",
                "target_loader_id": "fabric",
                "target_loader_version": "0.16.5",
            },
        ),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}/manual-upload",
            None,
        ),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}/prepare-test",
            {},
        ),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}/apply",
            {},
        ),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}/confirm",
            None,
        ),
        (
            "POST",
            f"/api/v1/servers/{SIMPLE_SERVER_ID}/upgrades/{upg_row.id}/rollback",
            {},
        ),
    ]
    assert len(all_routes) == 18

    for method, path, body in all_routes:
        if body is None:
            res = await api.client.request(method, path)
        else:
            res = await api.client.request(method, path, json=body)
        assert res.status_code == 401, (method, path, res.text)

    # 2. Viewer gets 200 on all 5 GET routes and 403 on all 13 mutating routes
    for method, path, body in all_routes:
        if method == "GET":
            res = await api.client.get(path, headers=viewer_headers)
            assert res.status_code == 200, (path, res.text)
        else:
            if path.endswith("/modpacks/inspect") or path.endswith("/manual-upload"):
                res = await api.client.post(
                    path,
                    files={"file": ("dummy.zip", b"zip", "application/zip")},
                    headers=viewer_headers,
                )
            elif body is None:
                res = await api.client.request(method, path, headers=viewer_headers)
            else:
                res = await api.client.request(
                    method, path, json=body, headers=viewer_headers
                )
            assert res.status_code == 403, (method, path, res.text)

    # 3. Activity log records P5.5 events with zero secret leakage
    await api.client.put(
        "/api/v1/settings/integrations/curseforge",
        json={"api_key": CF_SECRET_KEY},
        headers=api.headers,
    )
    await api.client.put(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/p55-settings",
        json={"health_gate_boot_timeout_seconds": 450},
        headers=api.headers,
    )
    act_res = await api.client.get(
        f"/api/v1/servers/{SIMPLE_SERVER_ID}/activity?limit=100",
        headers=api.headers,
    )
    assert act_res.status_code == 200, act_res.text
    event_types = {item["event_type"] for item in act_res.json()["items"]}
    assert "server.p55_settings_updated" in event_types
    assert CF_SECRET_KEY not in act_res.text
