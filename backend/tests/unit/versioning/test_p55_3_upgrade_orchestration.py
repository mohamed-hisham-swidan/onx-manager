"""P5.5-3 tests for upgrade orchestration, Simple 5-step swap, and Advanced flow."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import MergeConflictError, UpgradeBlockerError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.plugin.infrastructure.providers.base import PluginFile, PluginVersionsPage
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthProjectMeta,
    ModrinthVersionRecord,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.application.modpack_lockfile_builder import (
    store_base_overrides_in_cas,
)
from app.modules.versioning.application.modpack_upgrade_service import (
    ModpackUpgradeService,
)
from app.modules.versioning.application.refresh_orchestrator import (
    RETENTION_UNTIL_CONFIRM,
    RETENTION_UNTIL_HEALTH_GATE,
    HealthGateResult,
    LiveRefreshRequest,
    LiveRefreshService,
)
from app.modules.versioning.application.repo_lease import RepoLeaseManager
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LecRef,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchStartRequest,
    BranchStartResult,
)
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.download_allowlist import VerifiedDownloadResult
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.lec_store import LecStore
from app.modules.versioning.infrastructure.models import ServerDataTemplateModel
from app.modules.versioning.infrastructure.modpack_parser import (
    InstallPlan,
    ManualDownloadBlocker,
)
from app.modules.versioning.infrastructure.refresh_journal import RefreshJournalRepository

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="Live refresh / CAS / staging swap is POSIX-only in this slice",
)


def _hashes(payload: bytes) -> tuple[str, str, str]:
    return (
        hashlib.sha256(payload).hexdigest(),
        hashlib.sha512(payload).hexdigest(),
        hashlib.sha1(payload).hexdigest(),
    )


@dataclass
class _UpgradeEnv:
    layout: HostStateLayout
    servers_root: Path
    async_factory: async_sessionmaker
    sync_factory: sessionmaker[Session]
    journal_repo: RefreshJournalRepository
    repo_lease: RepoLeaseManager
    cas: ArtifactCas
    lec_store: LecStore


@pytest.fixture
def upgrade_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    monkeypatch.setenv("ONX_MASTER_KEK", "7d" * 32)
    db_path = tmp_path / "p55_3_orch.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    reconcile = DatabaseReconciler(db_url=db_url).reconcile(auto_upgrade=True)
    assert reconcile.status == ReconcileStatus.RECONCILED, reconcile.message

    async_engine = create_async_engine(db_url)
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    async_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    servers_root = tmp_path / "servers"
    servers_root.mkdir(parents=True, exist_ok=True)
    journal_repo = RefreshJournalRepository(
        layout,
        session_factory=async_factory,
        sync_session_factory=sync_factory,
    )
    repo_lease = RepoLeaseManager(
        locks_dir=layout.locks,
        session_factory=async_factory,
        sync_session_factory=sync_factory,
    )
    env = _UpgradeEnv(
        layout=layout,
        servers_root=servers_root,
        async_factory=async_factory,
        sync_factory=sync_factory,
        journal_repo=journal_repo,
        repo_lease=repo_lease,
        cas=ArtifactCas(layout.cas),
        lec_store=LecStore(layout),
    )
    try:
        yield env
    finally:
        journal_repo.close()
        sync_engine.dispose()
        asyncio.run(async_engine.dispose())


def _insert_server(env: _UpgradeEnv, server_id: str, mode: str, root: Path) -> None:
    with env.sync_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=server_id,
                server_type="fabric",
                minecraft_version="1.20.4",
                mode=mode,
                provider="docker",
                root_path=str(root),
            )
        )
        session.commit()


async def _seed_ready_lec(env: _UpgradeEnv, lec_key: str) -> None:
    staging = env.lec_store.create_staging_dir(lec_key)
    lib_file = (
        staging / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.16.0" / "loader.jar"
    )
    lib_file.parent.mkdir(parents=True, exist_ok=True)
    lib_file.write_bytes(b"fabric-loader-bytes")
    await env.lec_store.publish_staged_entry(staging, lec_key, java_major=21)
    assert env.lec_store.is_ready(lec_key)


class _FakeModrinth:
    def __init__(
        self,
        version_files: dict[str, ModrinthVersionRecord] | None = None,
        updates: dict[str, ModrinthVersionRecord] | None = None,
    ) -> None:
        self._version_files = version_files or {}
        self._updates = updates or {}

    async def lookup_version_files_by_hashes(
        self, hashes: list[str], *, algorithm: str = "sha512"
    ) -> dict[str, ModrinthVersionRecord]:
        del algorithm
        return {h: self._version_files[h] for h in hashes if h in self._version_files}

    async def lookup_version_updates_by_hashes(
        self, hashes: list[str], **_kwargs: Any
    ) -> dict[str, ModrinthVersionRecord]:
        return {h: self._updates[h] for h in hashes if h in self._updates}

    async def get_versions_by_ids(self, version_ids: list[str]) -> dict[str, ModrinthVersionRecord]:
        del version_ids
        return {}

    async def get_projects_by_ids(self, project_ids: list[str]) -> dict[str, ModrinthProjectMeta]:
        del project_ids
        return {}

    async def get_project_versions(self, project_id: str, **_kwargs: Any) -> PluginVersionsPage:
        del project_id
        return PluginVersionsPage(items=[], total=0)

    async def classify_client_only_jars_by_sha512(
        self, sha512_hashes: list[str]
    ) -> tuple[set[str], dict[str, ModrinthVersionRecord], dict[str, ModrinthProjectMeta]]:
        del sha512_hashes
        return set(), {}, {}


@dataclass
class _FakeBackupService:
    events: list[str] = field(default_factory=list)
    pinned: dict[str, bool] = field(default_factory=dict)
    snapshots: dict[str, bytes] = field(default_factory=dict)
    counter: int = 0

    async def create_pinned_backup(self, server_id: str, live_dir: Path) -> str:
        del server_id
        self.counter += 1
        bid = f"backup-{self.counter}"
        self.pinned[bid] = True
        world_marker = live_dir / "world" / "data.txt"
        self.snapshots[bid] = world_marker.read_bytes() if world_marker.exists() else b""
        self.events.append(f"backup_create:{bid}")
        return bid

    async def restore_backup(self, server_id: str, backup_id: str, live_dir: Path) -> None:
        del server_id
        self.events.append(f"backup_restore:{backup_id}")
        world_dir = live_dir / "world"
        world_dir.mkdir(parents=True, exist_ok=True)
        (world_dir / "data.txt").write_bytes(self.snapshots.get(backup_id, b""))

    async def set_pinned(self, server_id: str, backup_id: str, pinned: bool) -> None:
        del server_id
        self.pinned[backup_id] = pinned
        self.events.append(f"backup_pin:{backup_id}={pinned}")


@dataclass
class _FakeRuntime:
    events: list[str] = field(default_factory=list)
    running: bool = True
    ready_ok: bool = True

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> bool:
        self.events.append("runtime_stop")
        self.running = False
        return True

    def start(self) -> bool:
        self.events.append("runtime_start")
        self.running = True
        return True

    def process_alive(self) -> bool:
        return self.running

    def boot_log(self) -> str:
        return '[12:00:00 INFO]: Done (1.0s)! For help, type "help"'

    def ready(self) -> bool:
        return self.ready_ok


@dataclass
class _FakeHealthGate:
    passed: bool = True
    failed_step: str | None = None
    reason: str | None = None

    async def evaluate(self) -> HealthGateResult:
        return HealthGateResult(
            passed=self.passed,
            failed_step=self.failed_step,
            reason=self.reason,
        )


@dataclass
class _FakeBranchRuntimeService:
    events: list[str] = field(default_factory=list)
    started_requests: list[BranchStartRequest] = field(default_factory=list)

    async def start_branch_runtime(self, request: BranchStartRequest) -> BranchStartResult:
        self.events.append(f"branch_start:{request.branch_name}:{request.data_template_id}")
        self.started_requests.append(request)
        return BranchStartResult(
            runtime_id="rt-test-1",
            server_id=request.server_id,
            branch_name=request.branch_name,
            commit_sha=request.commit_sha or ("a" * 40),
            container_name=f"onx-branch-{request.server_id}-test",
            container_id="cid-1",
            port_set=None,
            export_path=str(request.server_root),
            data_template_id=request.data_template_id,
            allow_public_test_join=False,
            memory_max_mb=2048,
            cpu_cores=2,
        )

    async def stop_branch_runtime(
        self, server_id: str, server_root: str | Path, branch_name: str, **_kwargs: Any
    ) -> Any:
        del server_id, server_root
        self.events.append(f"branch_stop:{branch_name}")
        return None


@dataclass
class _FakeDataTemplateService:
    layout: HostStateLayout
    events: list[str] = field(default_factory=list)

    async def clone(
        self,
        server_id: str,
        source_root: str | Path,
        template_id: str,
        *,
        session: Any = None,
        **_kwargs: Any,
    ) -> Path:
        del source_root
        self.events.append(f"template_clone:{template_id}")
        tdir = self.layout.data_templates_dir(server_id) / template_id
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "world").mkdir(exist_ok=True)
        (tdir / "world" / "mutated_by_test.txt").write_text("mutated")
        if session is not None:
            session.add(
                ServerDataTemplateModel(
                    id=template_id,
                    server_id=server_id,
                    name=template_id,
                    storage_path=str(tdir),
                    total_bytes=7,
                    file_count=1,
                    status="ready",
                )
            )
            await session.flush()
        return tdir


@pytest.mark.asyncio
async def test_blocker_aborts_before_branch_or_staging_and_manual_upload_clears(
    upgrade_env: _UpgradeEnv,
) -> None:
    server_id = "srv-blk"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True)
    _insert_server(upgrade_env, server_id, "simple", server_root)

    mod_old = b"old-mod-jar"
    sha256_o, sha512_o, sha1_o = _hashes(mod_old)
    upgrade_env.cas.put_bytes(mod_old)
    lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/existing.jar",
                sha256=sha256_o,
                sha512=sha512_o,
                sha1=sha1_o,
                size=len(mod_old),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-e",
                version_id="ver-e",
            ),
        ),
    )
    LockfileService(upgrade_env.layout).write(server_id, lf)

    manual_payload = b"manual-curseforge-jar"
    _, m_sha512, m_sha1 = _hashes(manual_payload)
    plan = InstallPlan(
        source="curseforge",
        project_id="1",
        version_id="2",
        version_label="v2",
        index_sha256="a" * 64,
        mc_version="1.21.1",
        loader_id="fabric",
        loader_version="0.16.0",
        files=(),
        overrides=(),
        manual_blockers=(
            ManualDownloadBlocker(
                path="mods/manual.jar",
                filename="manual.jar",
                project_id=10,
                file_id=20,
                webpage_url="https://www.curseforge.com/x",
                expected_size=len(manual_payload),
                expected_sha1=m_sha1,
                expected_sha512=m_sha512,
            ),
        ),
    )

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=_FakeModrinth(),  # type: ignore[arg-type]
    )
    upgrade, _matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        mode="simple",
        target_install_plan=plan,
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert str(upgrade.status) == "awaiting_manual_uploads"

    # Must abort BEFORE creating staging directory or branch
    with pytest.raises(UpgradeBlockerError):
        await svc.execute_simple_upgrade(
            str(upgrade.id),
            server_root=server_root,
            refresh_service=None,  # type: ignore[arg-type]
            ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
        )
    assert not server_root.with_name(f"{server_root.name}.staging").exists()

    with pytest.raises(UpgradeBlockerError):
        await svc.prepare_advanced_upgrade_branch(
            str(upgrade.id),
            server_root=server_root,
        )
    assert not (upgrade_env.layout.repo_dir(server_id) / "repo.git").exists()

    # Upload manual jar -> clears blocker and transitions status to "planned"
    updated = await svc.resolve_manual_upload(
        str(upgrade.id),
        file_id=20,
        data=manual_payload,
    )
    assert str(updated.status) == "planned"


@pytest.mark.asyncio
async def test_version_bump_promotion_in_live_refresh_service(
    upgrade_env: _UpgradeEnv,
) -> None:
    server_id = "srv-promo"
    live = upgrade_env.servers_root / server_id
    staging = upgrade_env.servers_root / f"{server_id}.staging"
    live.mkdir(parents=True)
    (live / "world").mkdir()
    (live / "world" / "data.txt").write_text("v1")
    (live / "eula.txt").write_text("eula=true\n")

    lf1 = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides={},
        files=(),
    )
    lf2 = LockfileV21(
        format=2,
        mc="1.21.1",
        loader=LoaderRef(id="fabric", version="0.16.0"),
        base_overrides={},
        files=(),
    )

    def _stage(
        staging: Path, commit_sha: str, *, export_id: str, fencing_verifier: Any
    ) -> None:
        del commit_sha, export_id
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "eula.txt").write_text("eula=true\n")
        fencing_verifier()

    backup = _FakeBackupService()
    runtime = _FakeRuntime()
    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        backup_service=backup,
        runtime=runtime,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
        stage_export=_stage,
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
    )

    # Caller passes UNTIL_HEALTH_GATE, but version bump promotes to UNTIL_CONFIRM!
    req = LiveRefreshRequest(
        server_id=server_id,
        live_dir=live,
        staging_dir=staging,
        export_bytes=10,
        retention_policy=RETENTION_UNTIL_HEALTH_GATE,
        deployed_lockfile=lf1,
        target_lockfile=lf2,
    )
    assert req.is_full_upgrade is True
    res = await refresh_svc.refresh(req)
    assert res.rolled_back is False
    assert res.journal.retention_policy == RETENTION_UNTIL_CONFIRM
    assert res.journal.previous_tree_retained is True
    assert backup.pinned[res.pre_upgrade_backup_id] is True

    confirmed = await refresh_svc.confirm_upgrade_unpin(server_id, res.journal.journal_id)
    assert confirmed.phase == "UPGRADE_CONFIRMED"
    assert backup.pinned[res.pre_upgrade_backup_id] is False


@pytest.mark.asyncio
async def test_advanced_upgrade_flow_template_cleanup_backup_before_merge_and_rollback(
    upgrade_env: _UpgradeEnv,
) -> None:
    server_id = "srv-adv"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True)
    (server_root / "world").mkdir()
    (server_root / "world" / "data.txt").write_text("live-world-v1")
    (server_root / "config").mkdir()
    (server_root / "config" / "app.yml").write_text("setting: old\n")
    (server_root / "secrets.txt").write_text("ok\n")
    _insert_server(upgrade_env, server_id, "advanced", server_root)

    lec_old = "fabric/1.20.4/0.15.11/1.0.1"
    lec_new = "fabric/1.21.1/0.16.0/1.0.1"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)

    mod_old = b"mod-old-jar"
    sha256_o, sha512_o, sha1_o = _hashes(mod_old)
    upgrade_env.cas.put_bytes(mod_old)
    mod_new = b"mod-new-jar"
    sha256_n, sha512_n, sha1_n = _hashes(mod_new)

    base_overrides = store_base_overrides_in_cas(
        upgrade_env.cas, {"config/app.yml": b"setting: old\n"}
    )
    initial_lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides=base_overrides,
        lec=LecRef(key=lec_old),
        files=(
            LockfileFile(
                path="mods/demo.jar",
                sha256=sha256_o,
                sha512=sha512_o,
                sha1=sha1_o,
                size=len(mod_old),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-demo",
                version_id="ver-old",
            ),
        ),
    )
    init_res = GitRepositoryService(upgrade_env.layout).initialize(
        server_id, server_root, initial_lf
    )
    prev_main_sha = init_res.main_sha

    # Seed Class-C secret file so Class-C vault has a real file to snapshot/restore
    (server_root / "secret-c.json").write_text('{"token":"v1"}')

    fake_modrinth = _FakeModrinth(
        version_files={
            sha512_o: ModrinthVersionRecord(
                version_id="ver-old",
                project_id="proj-demo",
                name="old",
                version_number="1.0",
                version_type="release",
                game_versions=("1.20.4",),
                loaders=("fabric",),
                environment="client_and_server",
                files=(),
                dependencies=(),
            )
        },
        updates={
            sha512_o: ModrinthVersionRecord(
                version_id="ver-new",
                project_id="proj-demo",
                name="new",
                version_number="2.0",
                version_type="release",
                game_versions=("1.21.1",),
                loaders=("fabric",),
                environment="client_and_server",
                files=(
                    PluginFile(
                        url="https://cdn.modrinth.com/data/demo/demo-2.0.jar",
                        filename="demo.jar",
                        size_bytes=len(mod_new),
                        sha1=sha1_n,
                        sha512=sha512_n,
                        primary=True,
                    ),
                ),
                dependencies=(),
            )
        },
    )

    async def fake_download(
        _url: str, cas: ArtifactCas, **_kwargs: Any
    ) -> VerifiedDownloadResult:
        dig = cas.put_bytes(mod_new)
        return VerifiedDownloadResult(
            sha256=dig,
            sha512=sha512_n,
            sha1=sha1_n,
            size=len(mod_new),
            final_url="https://cdn.modrinth.com/data/demo/demo-2.0.jar",
            redirect_count=0,
        )

    events: list[str] = []
    fake_branch_rt = _FakeBranchRuntimeService(events=events)
    fake_tpl = _FakeDataTemplateService(upgrade_env.layout, events=events)
    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=fake_modrinth,  # type: ignore[arg-type]
        data_template_service=fake_tpl,  # type: ignore[arg-type]
        branch_runtime_service=fake_branch_rt,  # type: ignore[arg-type]
        download_to_cas=fake_download,
    )

    upgrade, matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        mode="advanced",
        server_root=server_root,
        target_lec_key=lec_new,
    )
    assert not matrix.has_blockers

    prepared = await svc.prepare_advanced_upgrade_branch(
        str(upgrade.id),
        server_root=server_root,
        target_overrides={"config/app.yml": b"setting: new\n"},
    )
    assert str(prepared.status) == "staging"
    assert str(prepared.upgrade_branch) == "upgrade-1.21.1"

    start_res = await svc.start_advanced_upgrade_test(
        str(upgrade.id),
        server_root=server_root,
    )
    assert start_res.data_template_id is not None
    tpl_id = start_res.data_template_id
    tpl_dir = upgrade_env.layout.data_templates_dir(server_id) / tpl_id
    assert tpl_dir.is_dir()

    # Track exact ordering of backup/snapshot vs git merge!
    backup = _FakeBackupService(events=events)
    runtime = _FakeRuntime(events=events)
    class_c_svc = ClassCSnapshotService(upgrade_env.layout)
    orig_create_snap = class_c_svc.create_snapshot

    def tracked_snap(*args: Any, **kwargs: Any):
        events.append("class_c_snapshot")
        return orig_create_snap(*args, **kwargs)

    class_c_svc.create_snapshot = tracked_snap  # type: ignore[method-assign]

    clean_export = CleanExportService(upgrade_env.layout, cas=upgrade_env.cas)
    branch_svc = GitBranchService(upgrade_env.layout)

    def stage_export(
        staging: Path, commit_sha: str, *, export_id: str, fencing_verifier: Any
    ) -> None:
        events.append(f"stage_export:{commit_sha}")
        main_wt = branch_svc.get_branch(server_id, server_root, "main")
        assert main_wt is not None and main_wt.worktree_path is not None
        from app.modules.versioning.domain.lockfile import parse_lockfile

        committed_lf = parse_lockfile((main_wt.worktree_path / "onx-jars.lock.json").read_bytes())
        clean_export.export(
            CleanExportRequest(
                server_id=server_id,
                server_root=server_root,
                commit_sha=commit_sha,
                destination=staging,
                lockfile=committed_lf,
                export_id=export_id,
            ),
            fencing_verifier=fencing_verifier,
        )

    def reset_main(sid: str, sha: str) -> None:
        events.append(f"reset_main:{sha}")
        runner = branch_svc.open_runner(sid, server_root)
        runner.run("update-ref", "refs/heads/main", sha)
        main_wt = branch_svc.get_branch(sid, server_root, "main")
        if main_wt and main_wt.worktree_path:
            runner.run("reset", "--hard", sha, cwd=main_wt.worktree_path)

    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        class_c_service=class_c_svc,
        backup_service=backup,
        runtime=runtime,
        stage_export=stage_export,
        reset_main_ref=reset_main,
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
    )

    # 1. Fail Health Gate -> triad rollback + main reset + mutated template deleted!
    res_fail = await svc.apply_advanced_upgrade_to_live(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=False, failed_step="nbt_data_version", reason="bad nbt"),  # type: ignore[arg-type]
    )
    assert res_fail.rolled_back is True
    assert not tpl_dir.exists()
    assert not (server_root / "world" / "mutated_by_test.txt").exists()
    assert (server_root / "world" / "data.txt").read_text() == "live-world-v1"
    assert (server_root / "config" / "app.yml").read_text() == "setting: old\n"
    main_after_fail = branch_svc.get_branch(server_id, server_root, "main")
    assert main_after_fail is not None and main_after_fail.sha == prev_main_sha
    # Verify OD-v8.7-14 order: runtime_stop -> class_c_snapshot -> backup_create -> stage_export
    assert events.index("runtime_stop") < events.index("class_c_snapshot")
    assert events.index("class_c_snapshot") < events.index("backup_create:backup-1")
    stage_idx = next(i for i, e in enumerate(events) if e.startswith("stage_export:"))
    assert events.index("backup_create:backup-1") < stage_idx

    # 2. Pass Health Gate -> active_pinned until confirm_upgrade_and_unpin
    res_pass = await svc.apply_advanced_upgrade_to_live(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
    )
    assert res_pass.rolled_back is False
    assert (server_root / "config" / "app.yml").read_text() == "setting: new\n"
    row_pinned = await svc._upgrade_repo.get(str(upgrade.id))
    assert row_pinned is not None
    assert str(row_pinned.status) == "active_pinned"
    assert bool(row_pinned.pinned_until_confirm) is True
    assert backup.pinned[res_pass.pre_upgrade_backup_id] is True

    confirmed = await svc.confirm_upgrade_and_unpin(
        str(upgrade.id), refresh_service=refresh_svc
    )
    assert str(confirmed.status) == "confirmed"
    assert bool(confirmed.pinned_until_confirm) is False
    assert backup.pinned[res_pass.pre_upgrade_backup_id] is False


@pytest.mark.asyncio
async def test_simple_mode_5_step_swap_rollback_and_confirm(
    upgrade_env: _UpgradeEnv,
) -> None:
    server_id = "srv-simp"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True)
    (server_root / "world").mkdir()
    (server_root / "world" / "data.txt").write_text("simple-world-v1")
    (server_root / "config").mkdir()
    (server_root / "config" / "simple.yml").write_text("mode: live_edit\n")
    (server_root / "mods").mkdir()
    mod_old = b"simple-old-mod"
    (server_root / "mods" / "simple.jar").write_bytes(mod_old)
    sha256_o, sha512_o, sha1_o = _hashes(mod_old)
    upgrade_env.cas.put_bytes(mod_old)
    _insert_server(upgrade_env, server_id, "simple", server_root)

    lec_old = "fabric/1.20.4/0.15.11/1.0.1"
    lec_new = "fabric/1.21.1/0.16.0/1.0.1"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)

    base_overrides = store_base_overrides_in_cas(
        upgrade_env.cas, {"config/simple.yml": b"mode: old\n"}
    )
    baseline_lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides=base_overrides,
        lec=LecRef(key=lec_old),
        files=(
            LockfileFile(
                path="mods/simple.jar",
                sha256=sha256_o,
                sha512=sha512_o,
                sha1=sha1_o,
                size=len(mod_old),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-s",
                version_id="ver-s-old",
            ),
        ),
    )
    lock_svc = LockfileService(upgrade_env.layout)
    lock_svc.write(server_id, baseline_lf)

    mod_new = b"simple-new-mod"
    sha256_n, sha512_n, sha1_n = _hashes(mod_new)
    fake_modrinth = _FakeModrinth(
        version_files={
            sha512_o: ModrinthVersionRecord(
                version_id="ver-s-old",
                project_id="proj-s",
                name="old",
                version_number="1.0",
                version_type="release",
                game_versions=("1.20.4",),
                loaders=("fabric",),
                environment="client_and_server",
                files=(),
                dependencies=(),
            )
        },
        updates={
            sha512_o: ModrinthVersionRecord(
                version_id="ver-s-new",
                project_id="proj-s",
                name="new",
                version_number="2.0",
                version_type="release",
                game_versions=("1.21.1",),
                loaders=("fabric",),
                environment="client_and_server",
                files=(
                    PluginFile(
                        url="https://cdn.modrinth.com/data/s/simple-2.0.jar",
                        filename="simple.jar",
                        size_bytes=len(mod_new),
                        sha1=sha1_n,
                        sha512=sha512_n,
                        primary=True,
                    ),
                ),
                dependencies=(),
            )
        },
    )

    async def fake_download(
        _url: str, cas: ArtifactCas, **_kwargs: Any
    ) -> VerifiedDownloadResult:
        dig = cas.put_bytes(mod_new)
        return VerifiedDownloadResult(
            sha256=dig,
            sha512=sha512_n,
            sha1=sha1_n,
            size=len(mod_new),
            final_url="https://cdn.modrinth.com/data/s/simple-2.0.jar",
            redirect_count=0,
        )

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=fake_modrinth,  # type: ignore[arg-type]
        download_to_cas=fake_download,
    )

    upgrade, _ = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        mode="simple",
        target_lec_key=lec_new,
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )

    backup = _FakeBackupService()
    runtime = _FakeRuntime()
    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        backup_service=backup,
        runtime=runtime,
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
    )

    # 1. Conflict aborts before stopping live or creating .staging
    with pytest.raises(MergeConflictError):
        await svc.execute_simple_upgrade(
            str(upgrade.id),
            server_root=server_root,
            refresh_service=refresh_svc,
            target_overrides={"config/simple.yml": b"mode: conflict\n"},
            ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
        )
    # No .staging created and server wasn't stopped
    assert not server_root.with_name(f"{server_root.name}.staging").exists()
    assert runtime.running is True

    # 2. Failed Health Gate rolls back root AND restores previous host lockfile
    failing_gate = _FakeHealthGate(
        passed=False, failed_step="stdout_done_regex", reason="no done"
    )
    res_fail = await svc.execute_simple_upgrade(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=failing_gate,  # type: ignore[arg-type]
        target_overrides={"config/simple.yml": b"mode: new\n"},
        resolved_conflicts={"config/simple.yml": b"mode: new\n"},
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert res_fail.rolled_back is True
    assert (server_root / "mods" / "simple.jar").read_bytes() == mod_old
    assert (server_root / "config" / "simple.yml").read_text() == "mode: live_edit\n"
    restored_lf = lock_svc.read(server_id)
    assert restored_lf is not None and restored_lf.mc == "1.20.4"

    # 3. Clean Simple upgrade -> st_nlink == 1, .onx-complete.json, active_pinned -> rollback
    res_ok = await svc.execute_simple_upgrade(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
        target_overrides={"config/simple.yml": b"mode: new\n"},
        resolved_conflicts={"config/simple.yml": b"mode: new\n"},
        panel_properties={"server-port": "25577", "rcon.password": "${ONX_SECRET_RCON}"},
        secrets={"RCON": "s3cr3t"},
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert res_ok.rolled_back is False
    assert (server_root / "mods" / "simple.jar").read_bytes() == mod_new
    assert (server_root / "mods" / "simple.jar").lstat().st_nlink == 1
    assert (server_root / ".onx-complete.json").is_file()
    assert "server-port=25577" in (server_root / "server.properties").read_text()
    assert "rcon.password=s3cr3t" in (server_root / "server.properties").read_text()
    updated_lf = lock_svc.read(server_id)
    assert updated_lf is not None and updated_lf.mc == "1.21.1"

    # Emergency rollback restores triad + host lockfile back to 1.20.4
    await svc.emergency_rollback_upgrade(str(upgrade.id), refresh_service=refresh_svc)
    assert (server_root / "mods" / "simple.jar").read_bytes() == mod_old
    lf_after_emg = lock_svc.read(server_id)
    assert lf_after_emg is not None and lf_after_emg.mc == "1.20.4"


@pytest.mark.asyncio
async def test_upgrade_branch_collision_suffix_and_upsert_hook(upgrade_env: Any) -> None:
    from sqlalchemy import select

    from app.modules.versioning.application.modpack_upgrade_service import (
        SQLServerUpgradeRepository,
    )
    from app.modules.versioning.infrastructure.models import ServerBranchModel

    server_id = "srv-branch-collision"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True, exist_ok=True)
    _insert_server(upgrade_env, server_id, "advanced", server_root)
    lec_old = "fabric/1.20.4/0.16.0/1.0.1"
    lec_new = "fabric/1.21.4/0.16.0/1.0.1"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)

    old_mod = b"old-mod"
    sha256_o, sha512_o, sha1_o = _hashes(old_mod)
    upgrade_env.cas.put_bytes(old_mod)

    lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.16.0"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/legacy.jar",
                sha256=sha256_o,
                size=len(old_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                sha512=sha512_o,
                sha1=sha1_o,
                project_id="legacy",
                version_id="v1",
            ),
        ),
        lec=LecRef(key=lec_old),
    )
    GitRepositoryService(upgrade_env.layout).initialize(server_id, server_root, lf)
    # Pre-create upgrade-1.21.4 branch so prepare_advanced_upgrade_branch must suffix it
    GitBranchService(upgrade_env.layout).create_branch(
        server_id, server_root, "upgrade-1.21.4", start_point="main"
    )

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=_FakeModrinth(version_files={}, updates={}),  # type: ignore[arg-type]
        upgrade_repo=SQLServerUpgradeRepository(upgrade_env.async_factory),
    )

    upgrade, matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.4",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        mode="advanced",
        server_root=server_root,
        target_lec_key=lec_new,
        keep_paths=["mods/legacy.jar"],
    )
    assert not matrix.has_blockers

    prepared = await svc.prepare_advanced_upgrade_branch(
        str(upgrade.id),
        server_root=server_root,
    )
    assert prepared.upgrade_branch is not None
    assert "/" not in prepared.upgrade_branch
    assert prepared.upgrade_branch.startswith("upgrade-1.21.4-")
    assert len(prepared.upgrade_branch) <= 63

    async with upgrade_env.async_factory() as session:
        row = (
            await session.execute(
                select(ServerBranchModel).where(
                    ServerBranchModel.server_id == server_id,
                    ServerBranchModel.name == prepared.upgrade_branch,
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.head_commit_id == prepared.target_main_sha


@pytest.mark.asyncio
async def test_short_prefixed_server_dir_swap_validation_and_simple_upgrade(
    upgrade_env: _UpgradeEnv,
) -> None:
    """Short-prefixed server dirs (server-5a206ead) pass swap validation & Simple upgrade."""
    from app.core.exceptions import ValidationError
    from app.modules.versioning.application.refresh_recovery import RefreshStartupReconciler

    server_id = "5a206ead96d94c388ee4be3c246237aa"
    server_root = upgrade_env.servers_root / "server-5a206ead"
    server_root.mkdir(parents=True)
    (server_root / "world").mkdir()
    (server_root / "world" / "data.txt").write_text("simple-world-v1")
    (server_root / "plugins").mkdir()
    _insert_server(upgrade_env, server_id, "simple", server_root)

    staging_dir = upgrade_env.servers_root / "server-5a206ead.staging"
    prev_dir = upgrade_env.servers_root / "server-5a206ead.prev"
    other_prev = upgrade_env.servers_root / "server-deadbeef.prev"

    reconciler = RefreshStartupReconciler(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        servers_data_dir=upgrade_env.servers_root,
    )
    # 1a. Valid short-prefixed paths pass both with and without explicit live_root
    assert reconciler.validate_swap_path(server_id, prev_dir, field="previous_path") == prev_dir
    assert (
        reconciler.validate_swap_path(
            server_id, prev_dir, field="previous_path", live_root=server_root
        )
        == prev_dir
    )
    assert (
        reconciler.validate_swap_path(
            server_id, staging_dir, field="staging_path", live_root=server_root
        )
        == staging_dir
    )

    # 1b. Another server's directory MUST still be rejected
    with pytest.raises(ValidationError, match="does not belong to server"):
        reconciler.validate_swap_path(server_id, other_prev, field="previous_path")
    with pytest.raises(ValidationError, match="does not belong to server"):
        reconciler.validate_swap_path(
            server_id, other_prev, field="previous_path", live_root=server_root
        )

    # 2. Seed an orphaned prior .prev tree & verify Simple-mode execute_simple_upgrade succeeds
    lec_old = "paper/1.21.1/100"
    lec_new = "paper/1.21.4/200"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)

    LockfileService(upgrade_env.layout).write(
        server_id,
        LockfileV21(
            format=2,
            mc="1.21.1",
            loader=LoaderRef(id="paper", version="100"),
            base_overrides={},
            lec=LecRef(key=lec_old),
            files=(),
        ),
    )

    prev_dir.mkdir(parents=True)
    (prev_dir / "old-marker.txt").write_text("stale")
    stale_journal = await upgrade_env.journal_repo.create(
        server_id=server_id,
        fencing_token=1,
        live_path=server_root,
        staging_path=staging_dir,
        previous_path=prev_dir,
        phase="ROLLING_BACK",
        retention_policy="until_confirm",
        previous_tree_retained=True,
    )
    assert stale_journal.phase == "ROLLING_BACK"

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=_FakeModrinth(version_files={}, updates={}),  # type: ignore[arg-type]
    )
    upgrade, matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.4",
        target_loader=LoaderRef(id="paper", version="200"),
        mode="simple",
        target_lec_key=lec_new,
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert not matrix.has_blockers

    backup = _FakeBackupService()
    runtime = _FakeRuntime()
    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        backup_service=backup,
        runtime=runtime,
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
        live_root=server_root,
    )

    res = await svc.execute_simple_upgrade(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert res.rolled_back is False
    confirmed = await svc.confirm_upgrade_and_unpin(
        str(upgrade.id), refresh_service=refresh_svc
    )
    assert str(confirmed.status) == "confirmed"
    assert not prev_dir.exists()


@pytest.mark.asyncio
async def test_orphaned_until_confirm_journal_without_active_pinned_reclaimed_before_apply(
    upgrade_env: _UpgradeEnv,
) -> None:
    """Orphaned until_confirm journal with no active_pinned upgrade never blocks apply."""
    server_id = "server-orphan-prev"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True)
    (server_root / "world").mkdir()
    (server_root / "world" / "data.txt").write_text("world-v1")
    (server_root / "plugins").mkdir()
    _insert_server(upgrade_env, server_id, "simple", server_root)

    staging_dir = upgrade_env.servers_root / f"{server_id}.staging"
    prev_dir = upgrade_env.servers_root / f"{server_id}.prev"
    prev_dir.mkdir(parents=True)
    (prev_dir / "legacy.txt").write_text("orphaned")

    # Seed an orphaned COMPLETED until_confirm journal WITH .prev still on disk,
    # while NO ServerUpgradeModel in status='active_pinned' exists!
    orphaned = await upgrade_env.journal_repo.create(
        server_id=server_id,
        fencing_token=1,
        live_path=server_root,
        staging_path=staging_dir,
        previous_path=prev_dir,
        phase="QUIESCED",
        retention_policy="until_confirm",
        previous_tree_retained=True,
    )
    await upgrade_env.journal_repo.transition(
        orphaned.journal_id,
        fencing_token=1,
        phase="COMPLETED",
        previous_tree_retained=True,
        retention_policy="until_confirm",
    )

    lec_old = "paper/1.21.1/100"
    lec_new = "paper/1.21.4/200"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)
    LockfileService(upgrade_env.layout).write(
        server_id,
        LockfileV21(
            format=2,
            mc="1.21.1",
            loader=LoaderRef(id="paper", version="100"),
            base_overrides={},
            lec=LecRef(key=lec_old),
            files=(),
        ),
    )

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=_FakeModrinth(version_files={}, updates={}),  # type: ignore[arg-type]
    )
    upgrade, matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.4",
        target_loader=LoaderRef(id="paper", version="200"),
        mode="simple",
        target_lec_key=lec_new,
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert not matrix.has_blockers

    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        backup_service=_FakeBackupService(),
        runtime=_FakeRuntime(),
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
        live_root=server_root,
    )
    res = await svc.execute_simple_upgrade(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert res.rolled_back is False
    reclaimed = await upgrade_env.journal_repo.get(orphaned.journal_id)
    assert reclaimed is not None
    assert reclaimed.previous_tree_retained is False


@pytest.mark.asyncio
async def test_simple_purpur_upgrade_replaces_server_jar_and_excludes_superseded_plugins(
    upgrade_env: _UpgradeEnv,
) -> None:
    """Simple Purpur upgrade writes target server.jar & plugins without carrying old 1.21.4 jars."""
    server_id = "server-purpur-upg"
    server_root = upgrade_env.servers_root / server_id
    server_root.mkdir(parents=True)
    (server_root / "world").mkdir()
    (server_root / "world" / "level.dat").write_bytes(b"world-data")
    (server_root / "server.properties").write_text("enable-rcon=false\n", encoding="utf-8")
    (server_root / "plugins" / ".paper-remapped").mkdir(parents=True)
    (server_root / "plugins" / ".paper-remapped" / "old.jar").write_bytes(b"old-remap")
    (server_root / "versions" / "1.21.4").mkdir(parents=True)
    (server_root / "versions" / "1.21.4" / "purpur-1.21.4.jar").write_bytes(b"old-patched")

    old_server_jar = b"old-purpur-1.21.4-server-jar"
    old_plugin_bytes = b"old-veinminer-2.6.0"
    new_server_jar = b"NEW-PURPUR-1.21.11-SERVER-JAR"
    new_plugin_bytes = b"NEW-VEINMINER-2.7.0"

    (server_root / "server.jar").write_bytes(old_server_jar)
    (server_root / "plugins" / "veinminer-paper-2.6.0.jar").write_bytes(old_plugin_bytes)
    _insert_server(upgrade_env, server_id, "simple", server_root)

    cas = upgrade_env.cas
    old_srv_sha256, _old_srv_512, _old_srv_1 = _hashes(old_server_jar)
    cas.put_bytes(old_server_jar)
    old_plug_256, old_plug_512, old_plug_1 = _hashes(old_plugin_bytes)
    cas.put_bytes(old_plugin_bytes)
    new_plug_512 = _hashes(new_plugin_bytes)[1]
    new_plug_1 = _hashes(new_plugin_bytes)[2]

    lec_old = "purpur/1.21.4/latest"
    lec_new = "purpur/1.21.11/latest"
    await _seed_ready_lec(upgrade_env, lec_old)
    await _seed_ready_lec(upgrade_env, lec_new)

    old_lockfile = LockfileV21(
        format=2,
        mc="1.21.4",
        loader=LoaderRef(id="purpur", version="latest"),
        base_overrides={},
        lec=LecRef(key=lec_old),
        files=(
            LockfileFile(
                path="plugins/veinminer-paper-2.6.0.jar",
                sha256=old_plug_256,
                size=len(old_plugin_bytes),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
                sha512=old_plug_512,
                sha1=old_plug_1,
            ),
            LockfileFile(
                path="server.jar",
                sha256=old_srv_sha256,
                size=len(old_server_jar),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
    )
    LockfileService(upgrade_env.layout).write(server_id, old_lockfile)

    identified = ModrinthVersionRecord(
        project_id="proj-vein",
        version_id="ver-260",
        version_number="2.6.0",
        name="Veinminer",
        version_type="release",
        loaders=("purpur", "paper"),
        game_versions=("1.21.4",),
        environment="client_and_server",
        files=(
            PluginFile(
                filename="veinminer-paper-2.6.0.jar",
                url="https://cdn.modrinth.com/data/proj-vein/versions/ver-260/veinminer-paper-2.6.0.jar",
                primary=True,
                size_bytes=len(old_plugin_bytes),
                sha512=old_plug_512,
                sha1=old_plug_1,
            ),
        ),
        dependencies=(),
    )
    target_rec = ModrinthVersionRecord(
        project_id="proj-vein",
        version_id="ver-270",
        version_number="2.7.0",
        name="Veinminer 2.7.0",
        version_type="release",
        game_versions=("1.21.11",),
        loaders=("purpur", "paper"),
        environment="client_and_server",
        dependencies=(),
        files=(
            PluginFile(
                filename="veinminer-paper-2.7.0.jar",
                url="https://cdn.modrinth.com/data/proj-vein/versions/ver-270/veinminer-paper-2.7.0.jar",
                primary=True,
                size_bytes=len(new_plugin_bytes),
                sha512=new_plug_512,
                sha1=new_plug_1,
            ),
        ),
    )

    async def fake_download_to_cas(
        url: str,
        target_cas: ArtifactCas,
        **_kwargs: Any,
    ) -> VerifiedDownloadResult:
        payload = new_server_jar if "purpurmc.org" in url else new_plugin_bytes
        sha256, sha512, sha1 = _hashes(payload)
        target_cas.put_bytes(payload)
        return VerifiedDownloadResult(
            final_url=url,
            redirect_count=0,
            sha256=sha256,
            sha512=sha512,
            sha1=sha1,
            size=len(payload),
        )

    svc = ModpackUpgradeService(
        upgrade_env.layout,
        upgrade_env.async_factory,
        modrinth_client=_FakeModrinth(
            version_files={old_plug_512: identified},
            updates={old_plug_512: target_rec},
        ),  # type: ignore[arg-type]
        download_to_cas=fake_download_to_cas,
    )

    upgrade, matrix = await svc.plan_upgrade(
        server_id,
        target_mc="1.21.11",
        target_loader=LoaderRef(id="purpur", version="latest"),
        mode="simple",
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
    )
    assert str(upgrade.target_lec_key) == lec_new
    assert not matrix.has_blockers

    refresh_svc = LiveRefreshService(
        upgrade_env.layout,
        repository=upgrade_env.journal_repo,
        backup_service=_FakeBackupService(),
        runtime=_FakeRuntime(),
        repo_lease=upgrade_env.repo_lease,
        servers_data_dir=upgrade_env.servers_root,
        live_root=server_root,
    )
    stages_seen: list[str] = []

    async def _record_stage(stage: str) -> None:
        stages_seen.append(stage)

    res = await svc.execute_simple_upgrade(
        str(upgrade.id),
        server_root=server_root,
        refresh_service=refresh_svc,
        health_gate=_FakeHealthGate(passed=True),  # type: ignore[arg-type]
        ensure_baseline_fn=lambda _sid: asyncio.sleep(0),
        on_stage=_record_stage,
    )
    assert res.rolled_back is False
    assert stages_seen == ["STAGE_FILES", "SWAP_LIVE_TREE", "HEALTH_GATE", "FINALIZE"]

    # New target server.jar and upgraded plugin filename materialized cleanly
    assert (server_root / "server.jar").read_bytes() == new_server_jar
    assert (server_root / "plugins" / "veinminer-paper-2.7.0.jar").read_bytes() == new_plugin_bytes

    # Superseded plugin JAR and old 1.21.4 caches were NOT carried over!
    assert not (server_root / "plugins" / "veinminer-paper-2.6.0.jar").exists()
    assert not (server_root / "plugins" / ".paper-remapped").exists()
    assert not (server_root / "versions" / "1.21.4").exists()

    # Live world data remained intact
    assert (server_root / "world" / "level.dat").read_bytes() == b"world-data"
