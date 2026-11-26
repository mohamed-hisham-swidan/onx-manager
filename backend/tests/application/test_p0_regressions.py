from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.plugin.application.commands.enable_plugin import (
    EnablePluginCommand,
    EnablePluginHandler,
)
from app.modules.plugin.application.commands.install_modrinth_plugin import (
    InstallModrinthPluginCommand,
    InstallModrinthPluginHandler,
)
from app.modules.plugin.application.commands.toggle_mod_state import (
    ToggleModStateCommand,
    ToggleModStateHandler,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.jar_metadata_parser import parse_jar_metadata
from app.modules.plugin.infrastructure.providers.base import (
    PluginFile,
    PluginSearchResult,
    PluginVersionInfo,
)
from app.modules.plugin.infrastructure.providers.modrinth import (
    _PLUGIN_LOADER_FACETS,
    ModrinthProvider,
)
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import (
    MinecraftVersion,
    PluginId,
    PluginVersion,
    ServerId,
)
from app.modules.versioning.application.queries.diff_commits import (
    DiffCommitsHandler,
    DiffCommitsQuery,
)
from app.modules.versioning.infrastructure.mc_slp import SlpProbeResult

pytestmark = pytest.mark.usefixtures("init_test_db")


def _make_jar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


async def _seed_server(server_id: str, server_type: str, root: Path) -> Server:
    srv = Server.create(
        server_id=ServerId(server_id),
        name=f"Srv {server_id}",
        server_type=ServerType(server_type),
        minecraft_version=MinecraftVersion.parse("1.21.11"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=str(root),
            working_directory=".",
        ),
    )
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        await repo.save(srv)
        await session.commit()
    return srv


@pytest.mark.asyncio
async def test_toggle_mod_state_rejects_cross_server_idor(tmp_path: Path) -> None:
    eb = EventBus()
    srv_a = await _seed_server("srv-idor-a", "fabric", tmp_path / "a")
    srv_b = await _seed_server("srv-idor-b", "fabric", tmp_path / "b")

    pid = PluginId()
    plugin = Plugin.install(
        plugin_id=pid,
        server_id=srv_a.id,
        name="SecretMod",
        version=PluginVersion(1, 0, 0),
        filename="secret.jar",
        project_type="mod",
        loader="fabric",
    )
    async with UnitOfWork(eb) as uow:
        await SQLPluginRepository(uow.session).save(plugin)
        await uow.commit()

    handler = ToggleModStateHandler(eb)
    res = await handler.handle(
        ToggleModStateCommand(
            server_id=str(srv_b.id),
            plugin_id=str(pid),
            enabled=False,
        )
    )
    assert res.success is False
    assert res.error_code == "PLUGIN_NOT_FOUND"


@pytest.mark.asyncio
async def test_install_modrinth_persists_metadata_and_safe_filename(tmp_path: Path) -> None:
    eb = EventBus()
    srv_dir = tmp_path / "paper-meta"
    srv_dir.mkdir(parents=True)
    srv = await _seed_server("srv-mr-meta", "paper", srv_dir)

    jar_bytes = _make_jar({"plugin.yml": "name: ViaVersion\nversion: 5.0.0\nmain: com.vv.Main\n"})
    sha1 = hashlib.sha1(jar_bytes).hexdigest()

    class _StubProvider:
        name = "modrinth"

        async def get_version(self, version_id: str) -> PluginVersionInfo:
            return PluginVersionInfo(
                version_id=version_id,
                project_id="viaversion",
                name="5.0.0",
                version_number="5.0.0",
                game_versions=["1.21.11"],
                loaders=["paper", "spigot"],
                files=[
                    PluginFile(
                        filename="ViaVersion 5.0.0.jar",
                        url="https://cdn.modrinth.com/data/viaversion/ViaVersion.jar",
                        size_bytes=len(jar_bytes),
                        primary=True,
                        sha1=sha1,
                    )
                ],
                dependencies=[],
            )

        async def get_project(self, project_id: str) -> PluginSearchResult:
            return PluginSearchResult(
                project_id=project_id,
                slug="viaversion",
                title="ViaVersion",
                description="Allow newer clients on older servers",
                author="MylesIsCool",
                icon_url="https://cdn.modrinth.com/icon.png",
            )

        async def download(self, _url: str, **_kwargs) -> bytes:
            return jar_bytes

    handler = InstallModrinthPluginHandler(eb, provider=_StubProvider())
    res = await handler.handle(
        InstallModrinthPluginCommand(
            server_id=str(srv.id),
            project_id="viaversion",
            version_id="ver-1",
            minecraft_version="1.21.11",
        )
    )
    assert res.success is True, res.error

    async with database.session_factory() as session:
        saved = await SQLPluginRepository(session).get(PluginId(res.data["plugin_id"]))
        assert saved.name == "ViaVersion"
        assert saved.author == "MylesIsCool"
        assert saved.description == "Allow newer clients on older servers"
        assert saved.icon_url == "https://cdn.modrinth.com/icon.png"
        assert saved.filename == res.data["filename"]
        assert ".." not in (saved.filename or "")


@pytest.mark.asyncio
async def test_modrinth_purpur_or_facet_and_proxy_plugin_facets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for proxy in ("velocity", "bungeecord", "waterfall", "minestom"):
        assert f"categories:{proxy}" in _PLUGIN_LOADER_FACETS

    provider = ModrinthProvider()
    captured: dict = {}

    async def fake_get_json(_path: str, params: dict | None = None) -> dict:
        captured.update(params or {})
        return {"hits": [], "total_hits": 0}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    await provider.search("luckperms", project_type="plugin", loader="purpur")
    facets = json.loads(captured["facets"])
    assert [
        "categories:purpur",
        "categories:paper",
        "categories:spigot",
        "categories:bukkit",
    ] in facets


@pytest.mark.asyncio
async def test_enable_plugin_ignores_softdepend_and_accepts_installed_dependency(
    tmp_path: Path,
) -> None:
    jar = _make_jar(
        {
            "plugin.yml": (
                "name: MyPlugin\n"
                "version: 1.0.0\n"
                "main: com.example.MyPlugin\n"
                "depend: [Vault]\n"
                "softdepend: [PlaceholderAPI, MissingOptional]\n"
            )
        }
    )
    meta = parse_jar_metadata(jar)
    assert meta.dependencies == ["Vault"]
    assert "PlaceholderAPI" not in meta.dependencies
    assert "MissingOptional" not in meta.dependencies

    eb = EventBus()
    srv = await _seed_server("srv-dep-check", "paper", tmp_path / "dep")

    dep_plugin = Plugin.install(
        plugin_id=PluginId(),
        server_id=srv.id,
        name="Vault",
        version=PluginVersion(1, 7, 3),
        filename="Vault.jar",
    )
    # Note: Plugin.install leaves status == INSTALLED (not ENABLED)
    target_pid = PluginId()
    target_plugin = Plugin.install(
        plugin_id=target_pid,
        server_id=srv.id,
        name="MyPlugin",
        version=PluginVersion(1, 0, 0),
        dependencies=["Vault"],
        filename="MyPlugin.jar",
    )
    target_plugin.disable()

    async with UnitOfWork(eb) as uow:
        repo = SQLPluginRepository(uow.session)
        await repo.save(dep_plugin)
        await repo.save(target_plugin)
        await uow.commit()

    res = await EnablePluginHandler(eb).handle(EnablePluginCommand(plugin_id=str(target_pid)))
    assert res.success is True, res.error


@pytest.mark.asyncio
async def test_activity_repo_main_includes_null_branch_and_prefix_filter() -> None:
    repo = SQLActivityRepository()
    now = time.time()
    logs = [
        ServerActivityLog(
            id="act-null-1",
            server_id="srv-act-repo",
            timestamp=now - 30,
            event_type="server.started",
            actor_type="system",
            actor_id=None,
            summary="Server started",
            branch_name=None,
        ),
        ServerActivityLog(
            id="act-main-1",
            server_id="srv-act-repo",
            timestamp=now - 20,
            event_type="plugin.installed",
            actor_type="user",
            actor_id="u1",
            summary="Installed Essentials",
            branch_name="main",
        ),
        ServerActivityLog(
            id="act-main-2",
            server_id="srv-act-repo",
            timestamp=now - 10,
            event_type="plugin.disabled",
            actor_type="user",
            actor_id="u1",
            summary="Disabled Essentials",
            branch_name=None,
        ),
        ServerActivityLog(
            id="act-feat-1",
            server_id="srv-act-repo",
            timestamp=now - 5,
            event_type="plugin.installed",
            actor_type="user",
            actor_id="u1",
            summary="Branch plugin",
            branch_name="feat-x",
        ),
    ]
    for entry in logs:
        await repo.save(entry)

    main_items, main_total = await repo.list_by_server("srv-act-repo", branch_name="main")
    main_ids = {i.id for i in main_items}
    assert main_total == 3
    assert {"act-null-1", "act-main-1", "act-main-2"} == main_ids
    assert "act-feat-1" not in main_ids

    plugin_items, plugin_total = await repo.list_by_server(
        "srv-act-repo",
        event_type="plugin.",
        branch_name="main",
    )
    assert plugin_total == 2
    assert {i.id for i in plugin_items} == {"act-main-1", "act-main-2"}


@pytest.mark.asyncio
async def test_diff_commits_parses_null_delimited_paths_and_omits_unchanged_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lockfile_json = json.dumps(
        {"mc": "1.21.11", "loader": {"id": "purpur"}, "files": []}
    )

    class _FakeRunner:
        def run(self, *args: str, **_kwargs) -> SimpleNamespace:
            if args[0] == "rev-parse":
                return SimpleNamespace(returncode=0, stdout=args[-1].split("^")[0] + "\n")
            if args[0] == "show":
                return SimpleNamespace(returncode=0, stdout=lockfile_json)
            if args[0] == "diff-tree":
                return SimpleNamespace(
                    returncode=0,
                    stdout="A\x00config/new.yml\x00M\x00server.properties\x00R100\x00old.yml\x00renamed.yml\x00",
                )
            return SimpleNamespace(returncode=1, stdout="")

    fake_ctx = SimpleNamespace(
        service=SimpleNamespace(open_runner=lambda _sid, _root: _FakeRunner()),
        server_root=Path("/tmp/fake"),
    )
    monkeypatch.setattr(
        "app.modules.versioning.application.queries.diff_commits.git_branch_context",
        lambda _srv: fake_ctx,
    )

    server_repo = MagicMock()
    server_repo.get = AsyncMock(return_value=SimpleNamespace(id=ServerId("srv-diff-1")))
    versioning_repo = MagicMock()

    handler = DiffCommitsHandler(server_repo=server_repo, versioning_repo=versioning_repo)
    diff = await handler.handle(
        DiffCommitsQuery(
            server_id="srv-diff-1",
            from_commit_id="aaa1111",
            to_commit_id="bbb2222",
        )
    )

    assert diff["configs"]["added"] == ["config/new.yml", "renamed.yml"]
    assert diff["configs"]["modified"] == ["server.properties"]
    assert diff["configs"]["removed"] == ["old.yml"]
    assert diff["server_type"] is None
    assert diff["minecraft_version"] is None
    assert diff["has_changes"] is True


@pytest.mark.asyncio
async def test_get_server_exposure_probe_true_returns_slp_reachability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.routers.exposure import get_server_exposure

    fake_query_bus = MagicMock()
    fake_query_bus.ask = AsyncMock(
        return_value={
            "server_id": "srv-probe-1",
            "branch_name": "main",
            "allocated_game_port": 25565,
            "method": "playit",
            "desired_state": "ENABLED",
            "aggregate_status": "ACTIVE",
            "targets": [
                {
                    "id": "tgt-1",
                    "protocol": "tcp",
                    "service_type": "java",
                    "local_port": 25565,
                    "public_address": "play.example.com:25565",
                    "status": "ACTIVE",
                }
            ],
        }
    )

    async def fake_probe(host: str, port: int, **_kwargs) -> SlpProbeResult:
        assert host == "play.example.com"
        assert port == 25565
        return SlpProbeResult(
            reachable=True,
            latency_ms=42,
            version_name="Purpur 1.21.11",
            protocol_version=769,
            players_online=3,
            players_max=20,
            motd="Welcome",
        )

    monkeypatch.setattr(
        "app.modules.versioning.infrastructure.mc_slp.probe_minecraft_slp",
        fake_probe,
    )

    resp = await get_server_exposure(
        server_id="srv-probe-1",
        branch=None,
        probe=True,
        query_bus=fake_query_bus,
        _current_user={"user_id": "u1"},
    )
    assert resp.reachability is not None
    assert resp.reachability.reachable is True
    assert resp.reachability.latency_ms == 42
    assert resp.reachability.version_name == "Purpur 1.21.11"
    assert resp.reachability.players_online == 3
    assert resp.reachability.players_max == 20
