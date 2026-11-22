from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.host_state import HostStateLayout
from app.modules.versioning.infrastructure.data_templates import (
    DataTemplateService,
    reconcile_data_templates_and_save_off,
)

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P2/P4 Advanced-mode data templates & clean export are POSIX-only; Windows = Simple-only",
)


class FakeContainer:
    def __init__(self, running: bool = False) -> None:
        self._running = running

    def is_running(self) -> bool:
        return self._running


class FakeRcon:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.save_off_active = False

    async def save_off(self) -> str:
        self.calls.append("save-off")
        return "ok"

    async def save_all_flush(self, timeout: float = 30.0) -> str:  # noqa: ARG002
        self.calls.append("save-all")
        return "Saved the game"

    async def save_on(self) -> str:
        self.calls.append("save-on")
        return "ok"


class FakeStore:
    def __init__(self) -> None:
        self.active = False

    async def set_save_off_active(self, server_id: str, active: bool) -> None:  # noqa: ARG002
        self.active = active


@POSIX_ONLY
@pytest.mark.asyncio
async def test_stopped_clone(tmp_path: Path) -> None:
    # build layout manually
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (
        layout.server_meta,
        layout.class_c_vault,
        layout.quarantine,
        layout.lec,
        layout.cas,
        layout.repos,
        layout.locks,
        layout.journal,
        layout.data_templates,
    ):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")
    (src / "world" / "region").mkdir()
    (src / "world" / "region" / "r.0.0.mca").write_bytes(b"region")
    (src / "mods").mkdir()
    (src / "mods" / "a.jar").write_bytes(b"mod")
    (src / "session.lock").write_bytes(b"lock")

    service = DataTemplateService(layout=layout)
    out = await service.clone(
        server_id="srv1",
        source_root=src,
        template_id="tmpl1",
        container_state=FakeContainer(False),
    )
    assert (out / "world" / "level.dat").exists()
    assert (out / ".onx-complete.json").exists()
    assert not (out / "mods" / "a.jar").exists()
    assert not (out / "session.lock").exists()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_running_reflink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")

    rcon = FakeRcon()
    store = FakeStore()
    container = FakeContainer(True)

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: True)
    monkeypatch.setattr(dt, "_try_reflink_fd", lambda *_a, **_k: True)

    service = DataTemplateService(
        layout=layout, rcon=rcon, container_state=container, save_off_store=store
    )
    out = await service.clone(
        server_id="srv1",
        source_root=src,
        template_id="tmpl2",
        rcon=rcon,
        container_state=container,
        save_off_store=store,
    )
    assert rcon.calls == ["save-off", "save-all", "save-on"]
    assert store.active is False
    assert (out / ".onx-complete.json").exists()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_running_two_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")

    rcon = FakeRcon()
    store = FakeStore()
    container = FakeContainer(True)

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: False)

    service = DataTemplateService(layout=layout)
    out = await service.clone(
        server_id="srv1",
        source_root=src,
        template_id="tmpl3",
        rcon=rcon,
        container_state=container,
        save_off_store=store,
    )
    assert "save-on" in rcon.calls
    assert (out / ".onx-complete.json").exists()


@POSIX_ONLY
def test_reconcile(tmp_path: Path) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    layout.data_templates.mkdir(parents=True, exist_ok=True)
    (layout.data_templates / "srv1").mkdir(parents=True, exist_ok=True)
    incomplete = layout.data_templates / "srv1" / "badtmpl"
    incomplete.mkdir()
    reconcile_data_templates_and_save_off(layout)
    assert not incomplete.exists()


def test_class_e_matrix(tmp_path: Path) -> None:
    src = tmp_path / "server"
    (src / "world" / "serverconfig").mkdir(parents=True)
    (src / "world" / "serverconfig" / "forge.toml").write_text("x")
    (src / "plugins" / "LuckPerms").mkdir(parents=True)
    (src / "plugins" / "LuckPerms" / "luckperms-h2.db").write_bytes(b"db")
    (src / "config").mkdir()
    (src / "config" / "a.toml").write_text("a")
    (src).joinpath("ops.json").write_text("{}")
    (src).joinpath("server.properties").write_text("p")
    (src / "world" / "datapacks" / "pack").mkdir(parents=True)
    (src / "world" / "datapacks" / "pack" / "pack.mcmeta").write_text("{}")
    (src / "world" / "level.dat").write_bytes(b"l")

    from app.modules.versioning.infrastructure.data_templates import _iter_class_e_files

    files = _iter_class_e_files(src)
    assert "world/serverconfig/forge.toml" in files
    assert "plugins/LuckPerms/luckperms-h2.db" in files
    assert "world/level.dat" in files
    for excluded in ("config/a.toml", "ops.json", "server.properties"):
        assert excluded not in files


def test_class_e_file_symlink_raises(tmp_path: Path) -> None:
    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"l")
    (src / "world" / "evil.dat").symlink_to(src / "world" / "level.dat")
    from app.core.allowlist import SymlinkEscapeError
    from app.modules.versioning.infrastructure.data_templates import _iter_class_e_files

    with pytest.raises(SymlinkEscapeError):
        _iter_class_e_files(src)


@pytest.mark.asyncio
async def test_async_persist_template(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.data_templates import _persist_template_async
    from app.modules.versioning.infrastructure.models import ServerDataTemplateModel

    d = tmp_path
    engine = create_async_engine(f"sqlite+aiosqlite:///{d / 't.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await _persist_template_async(
            session, "srv1", "tmpl1", tmp_path / "storage", 1, 5, "sha", "main", "ready"
        )
        from sqlalchemy import select

        res = await session.execute(select(ServerDataTemplateModel))
        rows = res.scalars().all()
        assert len(rows) == 1
    await engine.dispose()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_reconcile_save_on_and_flag(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.versioning.infrastructure.data_templates import (
        reconcile_data_templates_and_save_off_async,
    )

    d = tmp_path
    engine = create_async_engine(f"sqlite+aiosqlite:///{d / 't.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        srv = ServerModel(
            id="s1",
            name="s1",
            minecraft_version="1.20",
            root_path="/tmp",
            working_directory="/tmp",
            startup_jar="x.jar",
            rcon_save_off_active=True,
        )
        session.add(srv)
        await session.commit()

        layout = tmp_path / "host-state"
        (layout / "data-templates").mkdir(parents=True, exist_ok=True)
        from app.core.host_state import HostStateLayout

        hs = HostStateLayout(
            root=layout,
            server_meta=layout / "server-meta",
            class_c_vault=layout / "class-c-vault",
            quarantine=layout / "quarantine",
            lec=layout / "lec",
            cas=layout / "cas",
            repos=layout / "repos",
            locks=layout / "locks",
            journal=layout / "journal",
            data_templates=layout / "data-templates",
        )
        for p in (
            hs.server_meta,
            hs.class_c_vault,
            hs.quarantine,
            hs.lec,
            hs.cas,
            hs.repos,
            hs.locks,
            hs.journal,
            hs.data_templates,
        ):
            p.mkdir(parents=True, exist_ok=True)

        class Rcon:
            async def save_on(self):
                return "ok"

        rcon = Rcon()
        await reconcile_data_templates_and_save_off_async(
            hs, db_session=session, rcon_callback=lambda _sid: rcon  # noqa: ARG005
        )
        await session.refresh(srv)
        assert srv.rcon_save_off_active is False
    await engine.dispose()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_reconcile_no_callback_keeps_flag(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.versioning.infrastructure.data_templates import (
        reconcile_data_templates_and_save_off_async,
    )

    d = tmp_path
    engine = create_async_engine(f"sqlite+aiosqlite:///{d / 't.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        srv = ServerModel(
            id="s1",
            name="s1",
            minecraft_version="1.20",
            root_path="/tmp",
            working_directory="/tmp",
            startup_jar="x.jar",
            rcon_save_off_active=True,
        )
        session.add(srv)
        await session.commit()

        layout = tmp_path / "host-state2"
        (layout / "data-templates").mkdir(parents=True, exist_ok=True)
        from app.core.host_state import HostStateLayout

        hs = HostStateLayout(
            root=layout,
            server_meta=layout / "server-meta",
            class_c_vault=layout / "class-c-vault",
            quarantine=layout / "quarantine",
            lec=layout / "lec",
            cas=layout / "cas",
            repos=layout / "repos",
            locks=layout / "locks",
            journal=layout / "journal",
            data_templates=layout / "data-templates",
        )
        for p in (
            hs.server_meta,
            hs.class_c_vault,
            hs.quarantine,
            hs.lec,
            hs.cas,
            hs.repos,
            hs.locks,
            hs.journal,
            hs.data_templates,
        ):
            p.mkdir(parents=True, exist_ok=True)

        await reconcile_data_templates_and_save_off_async(hs, db_session=session)
        await session.refresh(srv)
        assert srv.rcon_save_off_active is True
    await engine.dispose()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_flush_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")

    class BadRcon(FakeRcon):
        async def save_all_flush(self, timeout: float = 30.0):  # noqa: ARG002
            self.calls.append("save-all")
            return "nope"

    rcon = BadRcon()
    store = FakeStore()
    container = FakeContainer(True)

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: False)

    service = DataTemplateService(layout=layout)
    from app.core.exceptions import HotCloneRefusedError

    with pytest.raises(HotCloneRefusedError):
        await service.clone(
            server_id="srv1",
            source_root=src,
            template_id="tmpl",
            rcon=rcon,
            container_state=container,
            save_off_store=store,
        )


@POSIX_ONLY
def test_clean_export_overlays_data_template(tmp_path: Path) -> None:
    import json

    from app.core.config import AppSettings
    from app.core.host_state import ensure_host_state_layout
    from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
    from app.modules.versioning.infrastructure.clean_export import (
        EXPORT_MARKER_NAME,
        CleanExportRequest,
        CleanExportService,
    )
    from app.modules.versioning.infrastructure.git_repository import GitRepositoryService

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-clean-export"
    root.mkdir(parents=True)
    (root / "server.properties").write_text("motd=x\n")

    init = GitRepositoryService(layout).initialize(
        "srv-clean-export",
        root,
        LockfileV21(
            format=2,
            mc="1.20.4",
            loader=LoaderRef(id="paper", version="499"),
            base_overrides={},
            files=(),
        ),
    )

    template_root = tmp_path / "template-root"
    template_root.mkdir()
    (template_root / "world").mkdir()
    (template_root / "world" / "level.dat").write_bytes(b"level-data")
    (template_root / EXPORT_MARKER_NAME).write_text(
        json.dumps({"completed_at": "2026-01-01T00:00:00Z", "file_count": 1, "total_bytes": 10})
    )

    destination = tmp_path / "export"
    req = CleanExportRequest(
        server_id="srv-clean-export",
        server_root=root,
        commit_sha=init.main_sha,
        destination=destination,
        lockfile=LockfileV21(
            format=2,
            mc="1.20.4",
            loader=LoaderRef(id="paper", version="499"),
            base_overrides={},
            files=(),
        ),
        data_template_dir=template_root,
    )
    CleanExportService(layout).export(req)
    assert (destination / "world" / "level.dat").read_bytes() == b"level-data"


@POSIX_ONLY
@pytest.mark.asyncio
async def test_two_pass_60s_save_off_cap_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: False)

    class CapRcon(FakeRcon):
        def __init__(self, source: Path) -> None:
            super().__init__()
            self.source = source

        async def save_all_flush(self, timeout: float = 30.0) -> str:  # noqa: ARG002
            self.calls.append("save-all")
            (self.source / "world" / "level.dat").write_bytes(b"level-mutated")
            return "Saved the game"

    rcon = CapRcon(src)
    store = FakeStore()
    container = FakeContainer(True)

    times = iter([0.0, 5.0, 70.0, 70.0])
    def clock() -> float:
        return next(times)

    service = DataTemplateService(layout=layout)
    from app.core.exceptions import HotCloneRefusedError

    with pytest.raises(HotCloneRefusedError):
        await service.clone(
            server_id="srv1",
            source_root=src,
            template_id="tmpl60",
            rcon=rcon,
            container_state=container,
            save_off_store=store,
            clock=clock,
        )

    assert "save-on" in rcon.calls
    server_dir = layout.data_templates / "srv1"
    staging_left = (
        [p for p in server_dir.iterdir() if p.name.startswith(".onx-template-")]
        if server_dir.exists()
        else []
    )
    assert staging_left == []
    assert not (server_dir / "tmpl60").exists()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_two_pass_30s_flush_timeout_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: False)

    rcon = FakeRcon()
    store = FakeStore()
    container = FakeContainer(True)

    times = iter([0.0, 40.0])
    def clock() -> float:
        return next(times)

    service = DataTemplateService(layout=layout)
    from app.core.exceptions import HotCloneRefusedError

    with pytest.raises(HotCloneRefusedError):
        await service.clone(
            server_id="srv1",
            source_root=src,
            template_id="tmpl30",
            rcon=rcon,
            container_state=container,
            save_off_store=store,
            clock=clock,
        )

    assert "save-on" in rcon.calls
    server_dir = layout.data_templates / "srv1"
    staging_left = (
        [p for p in server_dir.iterdir() if p.name.startswith(".onx-template-")]
        if server_dir.exists()
        else []
    )
    assert staging_left == []


@POSIX_ONLY
@pytest.mark.asyncio
async def test_two_pass_delta_mutated_and_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host-state"
    root.mkdir()
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
        data_templates=root / "data-templates",
    )
    for d in (layout.locks, layout.data_templates):
        d.mkdir(parents=True, exist_ok=True)

    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    (src / "world" / "level.dat").write_bytes(b"level")
    (src / "world" / "region").mkdir(parents=True)
    (src / "world" / "region" / "r.0.0.mca").write_bytes(b"region")

    import app.modules.versioning.infrastructure.data_templates as dt

    monkeypatch.setattr(dt, "_probe_reflink_support", lambda *_a, **_k: False)

    class DeltaRcon(FakeRcon):
        def __init__(self, source: Path) -> None:
            super().__init__()
            self.source = source

        async def save_all_flush(self, timeout: float = 30.0) -> str:  # noqa: ARG002
            self.calls.append("save-all")
            (self.source / "world" / "level.dat").write_bytes(b"level-mutated")
            region = self.source / "world" / "region" / "r.0.0.mca"
            if region.exists():
                region.unlink()
            return "Saved the game"

    rcon = DeltaRcon(src)
    store = FakeStore()
    container = FakeContainer(True)

    service = DataTemplateService(layout=layout)
    out = await service.clone(
        server_id="srv1",
        source_root=src,
        template_id="tmplDelta",
        rcon=rcon,
        container_state=container,
        save_off_store=store,
        clock=lambda: 0.0,
    )

    assert (out / "world" / "level.dat").read_bytes() == b"level-mutated"
    assert not (out / "world" / "region" / "r.0.0.mca").exists()
