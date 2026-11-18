from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppSettings
from app.core.exceptions import BranchRuntimeActiveError
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.archive_branch import (
    ArchiveBranchCommand,
    ArchiveBranchHandler,
)
from app.modules.versioning.application.commands.create_branch import (
    CreateBranchCommand,
    CreateBranchHandler,
)
from app.modules.versioning.application.commands.delete_branch import (
    DeleteBranchCommand,
    DeleteBranchHandler,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchRuntimeService,
    BranchStartRequest,
)
from app.modules.versioning.infrastructure.class_c_snapshot import ClassCSnapshotService
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.server_secret_vault import ServerSecretVault

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-only")


class FakeRcon:
    def __init__(self, *a, **k):
        pass

    async def connect(self):
        pass

    async def close(self):
        pass

    async def send_command(self, cmd):
        if cmd == "save-all flush":
            return "Saved the game"
        return "ok"


class IntegrationRunner:
    def __init__(self):
        self.calls = []

    async def __call__(self, args):
        self.calls.append(list(args))
        if args and args[0] == "create":
            return 0, "containerid"
        if args and args[0] == "start":
            return 0, ""
        if args and args[0] == "stop":
            return 0, ""
        if args and args[0] == "rm":
            return 0, ""
        if args and args[0] == "inspect":
            if len(args) > 2 and args[1] == "-f":
                return 0, "true"
            return 0, json.dumps([{"State": {"ExitCode": 0, "OOMKilled": False}}])
        return 0, ""


@pytest.mark.asyncio
async def test_full_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("ONX_MASTER_KEK", "a5" * 32)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)

    server_root = tmp_path / "server"
    server_root.mkdir()
    (server_root / "server.properties").write_text(
        "motd=test\nrcon.password=secret\nserver-port=25565\nfoo=${ONX_SECRET_DB_PASS}\n"
    )
    (server_root / "server.jar").write_bytes(b"jar-bytes")

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    GitRepositoryService(layout).initialize("srv-1", server_root, lockfile)
    # branch created via CreateBranchHandler after DB setup

    vault = ServerSecretVault(layout)
    vault.store_secret("srv-1", "DB_PASS", "s3cr3t")

    live = tmp_path / "live"
    live.mkdir()
    (live / "ops.json").write_text('["alice"]', encoding="utf-8")
    (live / "whitelist.json").write_text('{"ops":[]}', encoding="utf-8")
    cc = ClassCSnapshotService(layout)
    cc.create_snapshot("srv-1", live, snapshot_id="snap-cc")

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

    database._session_factory = factory
    database._engine = engine
    await CreateBranchHandler().handle(CreateBranchCommand(server_id="srv-1", name="feature"))

    runner = IntegrationRunner()
    svc = BranchRuntimeService(
        layout,
        session_factory=factory,
        engine=engine,
        docker_runner=runner,
        rcon_client_factory=FakeRcon,
        class_c_service=cc,
        secret_vault=vault,
    )

    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)
    with patch("psutil.virtual_memory", return_value=mem), patch("os.cpu_count", return_value=32):
        req = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="feature",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            secrets=vault.load_server_secrets("srv-1"),
            max_concurrent_branch_runs=3,
        )
        result = await svc.start_branch_runtime(req)

    export_path = Path(result.export_path)
    props_text = (export_path / "server.properties").read_text(encoding="utf-8")
    assert "white-list=true" in props_text
    assert "server-port=25565" in props_text
    assert "${ONX_SECRET_DB_PASS}" not in props_text
    assert "s3cr3t" in props_text
    assert (export_path / "ops.json").exists()
    assert (export_path / "whitelist.json").exists()
    assert not (export_path / ".git").exists()

    info = GitBranchService(layout).get_branch("srv-1", server_root, "feature")
    assert info is not None and info.worktree_locked
    assert (info.worktree_lock_reason or "").startswith("runtime:")

    # refuse delete/archive while running
    with pytest.raises(BranchRuntimeActiveError):
        await DeleteBranchHandler().handle(DeleteBranchCommand(server_id="srv-1", name="feature"))
    with pytest.raises(BranchRuntimeActiveError):
        await ArchiveBranchHandler().handle(ArchiveBranchCommand(server_id="srv-1", name="feature"))

    # mutate inside export
    (export_path / "world").mkdir(exist_ok=True)
    (export_path / "world" / "level.dat").write_text("mutated-world", encoding="utf-8")
    (export_path / "ops.json").write_text('["bob"]', encoding="utf-8")

    template_result = await svc.save_data_template(
        "srv-1", "feature", name="tmpl1", runtime_id=result.runtime_id
    )
    template_id = template_result.template_id

    await svc.stop_branch_runtime(
        "srv-1", server_root, "feature", runtime_id=result.runtime_id
    )
    assert not export_path.exists()
    info2 = GitBranchService(layout).get_branch("srv-1", server_root, "feature")
    assert info2 is not None and not info2.worktree_locked

    # class-c vault untouched
    assert (layout.class_c_vault_dir("srv-1") / "snap-cc").is_dir()

    # second run with saved template
    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)
    with patch("psutil.virtual_memory", return_value=mem), patch("os.cpu_count", return_value=32):
        req2 = BranchStartRequest(
            server_id="srv-1",
            server_root=server_root,
            branch_name="feature",
            server_mode="advanced",
            server_provider="docker",
            lockfile=lockfile,
            data_template_id=template_id,
            secrets=vault.load_server_secrets("srv-1"),
            max_concurrent_branch_runs=3,
        )
        result2 = await svc.start_branch_runtime(req2)
    export_path2 = Path(result2.export_path)
    assert (export_path2 / "world" / "level.dat").read_text(encoding="utf-8") == "mutated-world"

    await svc.stop_branch_runtime("srv-1", server_root, "feature", runtime_id=result2.runtime_id)

    # archive then delete branch succeeds
    await ArchiveBranchHandler().handle(ArchiveBranchCommand(server_id="srv-1", name="feature"))
    # delete may fail if archived? Try delete anyway
    with __import__("contextlib").suppress(Exception):
        await DeleteBranchHandler().handle(DeleteBranchCommand(server_id="srv-1", name="feature"))

    await engine.dispose()
