from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppSettings
from app.core.exceptions import (
    HotCloneRefusedError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchRuntimeService,
    BranchStartRequest,
    build_branch_container_name,
    build_branch_docker_create_args,
    sanitize_branch_slug,
)
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.clean_export import CleanExportService
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import (
    ServerDynamicClassCModel,
    ServerRuntimeModel,
)


@pytest.fixture
def layout(tmp_path):
    from app.core.config import AppSettings

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    return ensure_host_state_layout(settings)


def test_sanitize_slug() -> None:
    assert sanitize_branch_slug("feature/My_Test") == "feature-my-test"


def test_container_name() -> None:
    name = build_branch_container_name("server1234", "feature/My_Test", "runtime5678")
    assert name == "onx-branch-server12-feature-my-test-runtime5"


_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P4 branch runtime / HostPortSet / Git require POSIX; Windows = Simple-only",
)


@_POSIX_ONLY
def test_hardening_flags() -> None:
    ps = HostPortSet(
        game_port=25600,
        rcon_port=25601,
        query_port=25602,
        plugin_ports={"voice": 25603},
    )
    args = build_branch_docker_create_args(
        container_name="c1",
        image="itzg/minecraft-server:latest",
        network="bridge",
        port_set=ps,
        memory_max_mb=4096,
        cpu_cores=2,
        export_root="/tmp/export",
        host_mount="/tmp/export",
        uid=1000,
        gid=1000,
        server_id="srv",
        branch_name="dev",
        runtime_id="rt",
        commit_sha="sha",
    )
    joined = " ".join(args)
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges:true" in args
    assert "--pids-limit=2048" in args
    assert any(a.startswith("--user") for a in args)
    assert "--memory" in args
    assert "--cpus" in args
    assert "--network" in args and args[args.index("--network") + 1] == "bridge"
    assert "25600:25565" in joined
    assert "127.0.0.1:25601:25575" in joined
    assert "25602:25565/udp" in joined or "25602/udp" in joined
    # single data mount
    vols = [i for i, a in enumerate(args) if a == "-v"]
    assert len(vols) == 1
    # never 0:0
    user_idx = args.index("--user")
    assert args[user_idx + 1] != "0:0"


def test_fail_closed_windows(layout, monkeypatch) -> None:
    from app.modules.versioning.infrastructure.branch_runtime_service import BranchRuntimeService

    svc = BranchRuntimeService(layout)
    monkeypatch.setattr(os, "name", "nt")
    req = BranchStartRequest(server_id="s", server_root="/tmp", branch_name="dev")
    with pytest.raises(ServerModeVersioningDisabledError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(svc.start_branch_runtime(req))
    with pytest.raises(ServerModeVersioningDisabledError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(svc.stop_branch_runtime("s", "/tmp", "dev"))
    with pytest.raises(ServerModeVersioningDisabledError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(svc.save_data_template("s", "dev", name="n"))
    with pytest.raises(ServerModeVersioningDisabledError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(svc.get_branch_runtime_status("s", "dev"))


@_POSIX_ONLY
def test_main_branch_fail_closed(layout) -> None:
    from app.modules.versioning.infrastructure.branch_runtime_service import BranchRuntimeService

    svc = BranchRuntimeService(layout)
    req = BranchStartRequest(
        server_id="s", server_root="/tmp", branch_name="main", server_mode="advanced"
    )
    with pytest.raises(ValidationError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(svc.start_branch_runtime(req))


def test_errors_mapping() -> None:
    from app.api.errors import _ERROR_STATUS_MAP

    for code in (
        "BRANCH_RUNTIME_ACTIVE",
        "BRANCH_CONCURRENCY_LIMIT",
        "DUPLICATE_PORT_SET",
        "PORT_ALLOCATION_EXHAUSTED",
        "HOT_CLONE_REFUSED",
    ):
        assert _ERROR_STATUS_MAP[code] == 409


def _big_headroom():
    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)
    return patch("psutil.virtual_memory", return_value=mem), patch("os.cpu_count", return_value=32)


async def _setup(tmp_path, monkeypatch, *, server_properties: str | None = None):
    monkeypatch.setenv("ONX_MASTER_KEK", "a5" * 32)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    server_root = tmp_path / "server"
    server_root.mkdir()
    if server_properties is not None:
        (server_root / "server.properties").write_text(server_properties)
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    GitRepositoryService(layout).initialize("srv-1", server_root, lockfile)
    GitBranchService(layout).create_branch("srv-1", server_root, "dev")
    GitBranchService(layout).create_branch("srv-1", server_root, "dev2")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/rt.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ServerModel(
                id="srv-1",
                name="srv",
                server_type="vanilla",
                minecraft_version="1.20.4",
                mode="advanced",
                provider="docker",
                root_path=str(server_root),
                memory_max_mb=4096,
                cpu_cores=2,
            )
        )
        await session.commit()
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    return layout, server_root, engine, factory, lockfile


def _runner(start_rc=0, inspect_running="false"):
    calls = []

    async def runner(args):
        calls.append(list(args))
        if args and args[0] == "create":
            return 0, "containerid"
        if args and args[0] == "start":
            return start_rc, "boom" if start_rc else ""
        if args and args[0] == "inspect":
            if len(args) > 2 and args[1] == "-f":
                return 0, inspect_running
            return 0, json.dumps([{"State": {"ExitCode": 0, "OOMKilled": False}}])
        return 0, ""

    runner.calls = calls
    return runner


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_ephemeral_class_c_overlay_success_and_failure(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(tmp_path, monkeypatch)
    live = tmp_path / "live"
    live.mkdir()
    (live / "ops.json").write_text('["alice"]', encoding="utf-8")
    cc = ClassCSnapshotService(layout)
    cc.create_snapshot("srv-1", live, snapshot_id="snap-cc")

    # success
    captured = {}

    _orig_export = CleanExportService.export

    def patched_export(self, request, *_a, **_k):
        overlay = Path(request.class_c_overlay_dir)
        captured["overlay"] = overlay
        assert overlay.is_dir()
        assert (overlay / "ops.json").read_text(encoding="utf-8") == '["alice"]'
        return _orig_export(self, request, *_a, **_k)

    monkeypatch.setattr(CleanExportService, "export", patched_export)
    p1, p2 = _big_headroom()
    with p1, p2:
        svc = BranchRuntimeService(
            layout,
            session_factory=factory,
            engine=engine,
            docker_runner=_runner(),
            class_c_service=cc,
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
        )
        res = await svc.start_branch_runtime(req)
        assert res is not None
    overlay = captured["overlay"]
    assert not overlay.exists()

    # failure injection
    captured2 = {}

    def failing_export(_self, request, *_a, **_k):
        overlay = Path(request.class_c_overlay_dir)
        captured2["overlay"] = overlay
        assert overlay.is_dir()
        assert (overlay / "ops.json").read_text(encoding="utf-8") == '["alice"]'
        raise RuntimeError("injected export failure")

    monkeypatch.setattr(CleanExportService, "export", failing_export)
    p1, p2 = _big_headroom()
    with p1, p2:
        svc = BranchRuntimeService(
            layout,
            session_factory=factory,
            engine=engine,
            docker_runner=_runner(),
            class_c_service=cc,
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev2",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
        )
        with pytest.raises(RuntimeError):
            await svc.start_branch_runtime(req)
    overlay2 = captured2["overlay"]
    assert not overlay2.exists()


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_allow_public_test_join_props(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(tmp_path, monkeypatch)
    p1, p2 = _big_headroom()
    with p1, p2:
        # False -> whitelist true
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
            allow_public_test_join=False,
        )
        res = await svc.start_branch_runtime(req)
        props = (Path(res.export_path) / "server.properties").read_text(encoding="utf-8")
        assert "white-list=true" in props
        assert "enforce-whitelist=true" in props

        # True -> not set
        svc2 = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req2 = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev2",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
            allow_public_test_join=True,
        )
        res2 = await svc2.start_branch_runtime(req2)
        props2 = (Path(res2.export_path) / "server.properties").read_text(encoding="utf-8")
        assert "white-list=true" not in props2
        assert "enforce-whitelist=true" not in props2


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_dynamic_class_c_overlay(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(tmp_path, monkeypatch)
    async with factory() as session:
        session.add(ServerDynamicClassCModel(id="d1", server_id="srv-1", relpath="ops.json"))
        session.add(ServerDynamicClassCModel(id="d2", server_id="srv-1", relpath="plugins/x.yml"))
        await session.commit()

    captured = {}

    _orig_export = CleanExportService.export

    def patched_export(self, request, *_a, **_k):
        captured["dynamic"] = request.dynamic_class_c
        return _orig_export(self, request, *_a, **_k)

    monkeypatch.setattr(CleanExportService, "export", patched_export)
    p1, p2 = _big_headroom()
    with p1, p2:
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
        )
        await svc.start_branch_runtime(req)
    assert captured["dynamic"] == frozenset({"ops.json", "plugins/x.yml"})


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_d8_secret_injection_and_unresolved(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(
        tmp_path, monkeypatch, server_properties="motd=test\nsecret=${ONX_SECRET_FOO}\n"
    )
    # unresolved fail-closed
    p1, p2 = _big_headroom()
    with p1, p2:
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
            secrets={},
        )
        with pytest.raises(ValidationError):
            await svc.start_branch_runtime(req)

    # resolved injection
    p1, p2 = _big_headroom()
    with p1, p2:
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev2",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
            secrets={"FOO": "bar"},
        )
        res = await svc.start_branch_runtime(req)
        # check substituted in some file
        export = Path(res.export_path)
        found = False
        for fp in export.rglob("*"):
            if fp.is_file():
                try:
                    if "bar" in fp.read_text(encoding="utf-8", errors="replace"):
                        found = True
                except Exception:
                    pass
        assert found


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_rollback_on_docker_start_failure(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(tmp_path, monkeypatch)
    p1, p2 = _big_headroom()
    with p1, p2:
        runner = _runner(start_rc=1)
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=runner
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
        )
        with pytest.raises(RuntimeError):
            await svc.start_branch_runtime(req)
        # docker rm -f called
        assert any(c and c[0] == "rm" and "-f" in c for c in runner.calls)
        # branch unlocked
        gb = GitBranchService(layout)
        info = gb.get_branch("srv-1", server_root, "dev")
        assert info is not None
        assert info.worktree_locked is False
        # runtime crashed, branch stopped
        async with factory() as session:
            from sqlalchemy import select

            rt = (
                (
                    await session.execute(
                        select(ServerRuntimeModel).where(ServerRuntimeModel.branch_name == "dev")
                    )
                )
                .scalars()
                .first()
            )
            assert rt is not None
            assert rt.status == "crashed"
        # export deleted: find export root? check no branch-exports with content
        exports = server_root / ".onx" / "branch-exports"
        # all export dirs should be gone
        if exports.exists():
            assert list(exports.iterdir()) == [] or all(not p.exists() for p in exports.iterdir())


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_save_data_template_live_and_stopped(tmp_path, monkeypatch):
    layout, server_root, engine, factory, lockfile = await _setup(tmp_path, monkeypatch)
    p1, p2 = _big_headroom()
    with p1, p2:
        # start runtime
        svc = BranchRuntimeService(
            layout, session_factory=factory, engine=engine, docker_runner=_runner()
        )
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="dev",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            max_concurrent_branch_runs=3,
        )
        res = await svc.start_branch_runtime(req)
        rid = res.runtime_id

        # live: container running, RCON fails -> HotCloneRefusedError
        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def connect(self):
                pass

            async def close(self):
                pass

            async def send_command(self, cmd):
                if cmd == "save-all flush":
                    return "nope"
                return "ok"

        svc_live = BranchRuntimeService(
            layout,
            session_factory=factory,
            engine=engine,
            docker_runner=_runner(inspect_running="true"),
            rcon_client_factory=lambda *_: FakeClient(),
        )
        with pytest.raises(HotCloneRefusedError):
            await svc_live.save_data_template("srv-1", "dev", name="tmpl-live", runtime_id=rid)

        # stopped: container not running -> success
        svc_stopped = BranchRuntimeService(
            layout,
            session_factory=factory,
            engine=engine,
            docker_runner=_runner(inspect_running="false"),
        )
        out = await svc_stopped.save_data_template(
            "srv-1", "dev", name="tmpl-stopped", runtime_id=rid
        )
        assert out.template_id is not None


@pytest.mark.asyncio
async def test_simple_mode_and_nondocker_fail_closed(tmp_path):
    from app.core.config import AppSettings
    from app.core.host_state import ensure_host_state_layout

    settings = AppSettings(
        host_state_dir=str(tmp_path / "hs"), servers_data_dir=str(tmp_path / "srv")
    )
    layout = ensure_host_state_layout(settings)
    svc = BranchRuntimeService(layout)
    req = BranchStartRequest(
        server_id="s",
        server_root="/tmp",
        branch_name="dev",
        server_mode="simple",
        server_provider="docker",
    )
    with pytest.raises(ServerModeVersioningDisabledError):
        await svc.start_branch_runtime(req)
    req2 = BranchStartRequest(
        server_id="s",
        server_root="/tmp",
        branch_name="dev",
        server_mode="advanced",
        server_provider="podman",
    )
    with pytest.raises(ServerModeVersioningDisabledError):
        await svc.start_branch_runtime(req2)
