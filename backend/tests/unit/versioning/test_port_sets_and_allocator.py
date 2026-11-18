from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.modules.versioning.domain.port_sets import HostPortSet
from app.modules.versioning.infrastructure.port_allocator import (
    allocate_port_set,
    is_host_port_free,
    validate_port_set_atomic,
)


def test_host_port_set_validation() -> None:
    ps = HostPortSet(
        game_port=25600,
        rcon_port=25601,
        query_port=25602,
        plugin_ports={"voice": 25603},
    )
    assert ps.all_host_ports() == {25600, 25601, 25602, 25603}
    assert ps.container_game_port == 25565
    assert ps.container_rcon_port == 25575

    with pytest.raises(ValidationError):
        HostPortSet(game_port=25600, rcon_port=25600)

    with pytest.raises(ValidationError):
        HostPortSet(game_port=80, rcon_port=25601)

    props = HostPortSet(
        game_port=25600, rcon_port=25601, query_port=25602
    ).to_panel_properties("secret")
    assert props["server-port"] == "25565"
    assert props["rcon.port"] == "25575"
    assert props["rcon.password"] == "secret"
    assert props["query.port"] == "25602"

    bindings = HostPortSet(game_port=25600, rcon_port=25601).to_docker_port_bindings()
    assert "25600:25565" in bindings
    assert "127.0.0.1:25601:25575" in bindings


@pytest.mark.asyncio
async def test_validate_and_allocate(tmp_path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        candidate = HostPortSet(game_port=25600, rcon_port=25601)
        await validate_port_set_atomic(session, candidate, check_os_ports=False)
        # allocate two disjoint
        a = await allocate_port_set(session, check_os_ports=False)
        b = await allocate_port_set(session, check_os_ports=False)
        assert a.all_host_ports().isdisjoint(b.all_host_ports())
    await engine.dispose()


def test_is_host_port_free() -> None:
    # bind a port then ensure not free
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        assert is_host_port_free(port) is False


def test_plugin_key_regex() -> None:
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        HostPortSet(game_port=25600, rcon_port=25601, plugin_ports={"Bad": 25602})
    ok = HostPortSet(game_port=25600, rcon_port=25601, plugin_ports={"voice_chat": 25602})
    assert "voice_chat" in ok.plugin_ports


@pytest.mark.asyncio
async def test_duplicate_vs_servers_port(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import DuplicatePortSetError
    from app.core.persistence.base import Base
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        srv = ServerModel(
            id="s1",
            name="s1",
            minecraft_version="1.20",
            root_path="/tmp",
            working_directory="/tmp",
            startup_jar="x.jar",
            port=25600,
        )
        session.add(srv)
        await session.commit()
        candidate = HostPortSet(game_port=25600, rcon_port=25601)
        with pytest.raises(DuplicatePortSetError):
            await validate_port_set_atomic(session, candidate, check_os_ports=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_vs_branch_port_set(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import DuplicatePortSetError
    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.models import ServerBranchModel
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        branch = ServerBranchModel(
            id="b1",
            server_id="s1",
            name="main",
            head_commit_id="c1",
            port_set_json={"game_port": 25600, "rcon_port": 25601},
        )
        session.add(branch)
        await session.commit()
        candidate = HostPortSet(game_port=25600, rcon_port=25602)
        with pytest.raises(DuplicatePortSetError):
            await validate_port_set_atomic(session, candidate, check_os_ports=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_vs_runtime(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import DuplicatePortSetError
    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.models import ServerRuntimeModel
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        runtime = ServerRuntimeModel(
            id="rt1",
            server_id="s1",
            commit_id="c1",
            status="running",
            port_set_json={"game_port": 25600, "rcon_port": 25601},
        )
        session.add(runtime)
        await session.commit()
        candidate = HostPortSet(game_port=25600, rcon_port=25602)
        with pytest.raises(DuplicatePortSetError):
            await validate_port_set_atomic(session, candidate, check_os_ports=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_vs_test_run(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import DuplicatePortSetError
    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.models import ServerTestRunModel
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        run = ServerTestRunModel(
            id="run1",
            server_id="s1",
            commit_id="c1",
            status="PENDING",
            port_set_json={"game_port": 25600, "rcon_port": 25601},
        )
        session.add(run)
        await session.commit()
        candidate = HostPortSet(game_port=25600, rcon_port=25602)
        with pytest.raises(DuplicatePortSetError):
            await validate_port_set_atomic(session, candidate, check_os_ports=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_live_socket(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import DuplicatePortSetError
    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 25600))
            s.listen(1)
            candidate = HostPortSet(game_port=25600, rcon_port=25601)
            with pytest.raises(DuplicatePortSetError):
                await validate_port_set_atomic(session, candidate, check_os_ports=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_exclude_ids(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.models import ServerBranchModel, ServerRuntimeModel
    from app.modules.versioning.infrastructure.port_allocator import validate_port_set_atomic

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        branch = ServerBranchModel(
            id="b1",
            server_id="s1",
            name="main",
            head_commit_id="c1",
            port_set_json={"game_port": 25600, "rcon_port": 25601},
        )
        runtime = ServerRuntimeModel(
            id="rt1",
            server_id="s1",
            commit_id="c1",
            status="running",
            port_set_json={"game_port": 25600, "rcon_port": 25601},
        )
        session.add_all([branch, runtime])
        await session.commit()
        candidate = HostPortSet(game_port=25600, rcon_port=25601)
        # excluded -> no conflict
        await validate_port_set_atomic(
            session,
            candidate,
            exclude_branch_id="b1",
            exclude_runtime_id="rt1",
            check_os_ports=False,
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_port_allocation_exhausted(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import PortAllocationExhaustedError
    from app.core.persistence.base import Base
    from app.modules.versioning.infrastructure.port_allocator import allocate_port_set

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        # reserve the only port in range
        from app.modules.server.infrastructure.models import ServerModel

        srv = ServerModel(
            id="s1",
            name="s1",
            minecraft_version="1.20",
            root_path="/tmp",
            working_directory="/tmp",
            startup_jar="x.jar",
            port=25600,
        )
        session.add(srv)
        await session.commit()
        with pytest.raises(PortAllocationExhaustedError):
            await allocate_port_set(
                session, start_port=25600, end_port=25600, check_os_ports=False
            )
    await engine.dispose()
