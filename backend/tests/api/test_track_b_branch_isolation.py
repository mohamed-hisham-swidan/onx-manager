"""Track B Multi-Tab Branch Isolation & Lifecycle Integration Tests (B.1 – B.4)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.main import app
from app.modules.server.application.branch_settings import auto_merge_pending_settings_on_restart
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.create_branch import (
    CreateBranchCommand,
    CreateBranchHandler,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.branch_runtime_service import BranchRuntimeService
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import ServerBranchModel
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Track B Advanced-mode routes require a POSIX host"
)

SERVER_ID = "srv-trackb"
SIMPLE_ID = "srv-trackb-simple"
VERSIONING = f"/api/v1/servers/{SERVER_ID}/versioning"


class FakeDockerRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.running = True
        self.logs = (
            "[Server thread/INFO]: Branch log line 1\n"
            "[Server thread/INFO]: Branch log line 2"
        )

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        if not args:
            return 0, ""
        if args[0] == "inspect":
            if "-f" in args:
                return 0, "true" if self.running else "false"
            return 0, json.dumps([{"State": {"ExitCode": 0, "OOMKilled": False}}])
        if args[0] == "logs":
            return 0, self.logs
        if args[0] == "create":
            return 0, "container-id-trackb"
        return 0, ""


class FakeRconClient:
    sent: list[tuple[str, str, int]] = []

    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password

    async def connect(self) -> None:
        type(self).sent.append(("connect", self.host, self.port))

    async def close(self) -> None:
        pass

    async def send_command(self, command: str) -> str:
        type(self).sent.append(("command", command, self.port))
        return f"branch-rcon:{command}"


def _make_jar_bytes(plugin_name: str = "BranchSpark", version: str = "1.0.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "plugin.yml",
            f"name: {plugin_name}\nversion: {version}\nmain: com.example.Main\n",
        )
    return buf.getvalue()


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(
    server_id: str, root: Path, *, mode: str = "advanced", port: int = 29970
) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=server_id,
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=port,
                java_args="-Xmx1G",
                memory_max_mb=4096,
                cpu_cores=2,
                mode=mode,
                provider="docker",
                max_concurrent_branch_runs=3,
                external_id=f"onx-{server_id}",
            )
        )
        await session.commit()


def _write_server_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text(
        "motd=MainWorld\nmax-players=20\nserver-port=25565\nrcon.password=super-secret\nrcon.port=25600\n",
        encoding="utf-8",
    )
    (root / "server.jar").write_bytes(b"jar")
    (root / "plugins").mkdir(exist_ok=True)
    (root / "world").mkdir(exist_ok=True)
    (root / "world" / "level.dat").write_bytes(b"level")
    (root / "ops.json").write_text("[]", encoding="utf-8")


@pytest.fixture
def trackb_host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_MASTER_KEK", "22" * 32)
    (tmp_path / "servers").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
async def trackb_api(
    client: AsyncClient,
    created_user: dict,
    trackb_host_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    import psutil

    from app.api.v1.routers import versioning as versioning_router
    from app.modules.versioning.application.lockfile_service import LockfileService

    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(available=64 * 1024 * 1024 * 1024),
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 32)
    FakeRconClient.sent.clear()

    layout = ensure_host_state_layout()
    root = trackb_host_state / "servers" / SERVER_ID
    _write_server_tree(root)
    await _seed_server(SERVER_ID, root, mode="advanced", port=29970)
    lockfile = _empty_lockfile()
    GitRepositoryService(layout).initialize(SERVER_ID, root, lockfile)
    LockfileService(layout).write(SERVER_ID, lockfile)
    await CreateBranchHandler().handle(CreateBranchCommand(server_id=SERVER_ID, name="feat-a"))

    simple_root = trackb_host_state / "servers" / SIMPLE_ID
    _write_server_tree(simple_root)
    await _seed_server(SIMPLE_ID, simple_root, mode="simple", port=29971)

    header = await _seed_api_key_header(client, created_user["user_id"], ["admin:full"])
    runner = FakeDockerRunner()
    service = BranchRuntimeService(
        layout,
        session_factory=database.session_factory,
        engine=database._engine,
        docker_runner=runner,
        rcon_client_factory=FakeRconClient,
    )
    orig_get_svc = versioning_router.get_branch_runtime_service
    app.dependency_overrides[orig_get_svc] = lambda: service
    try:
        yield SimpleNamespace(
            client=client,
            header=header,
            root=root,
            simple_root=simple_root,
            runner=runner,
            service=service,
            layout=layout,
        )
    finally:
        app.dependency_overrides.pop(orig_get_svc, None)


# ---------------------------------------------------------------------------
# B.1: Persistent-Stop / Explicit-Destroy & Branch-Scoped Console Routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_branch_container_lifecycle_and_console_routing(trackb_api: Any) -> None:
    api = trackb_api

    # Unprovisioned branch -> console 404, runtime container_provisioned=False
    rt_res = await api.client.get(f"{VERSIONING}/branches/feat-a/runtime", headers=api.header)
    assert rt_res.status_code == 200, rt_res.text
    assert rt_res.json()["container_provisioned"] is False

    c_res = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/console?branch=feat-a", headers=api.header
    )
    assert c_res.status_code == 404, c_res.text

    # Start branch run -> provisioned & running, console + command route to branch
    start_res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )
    assert start_res.status_code == 201, start_res.text
    rcon_port = start_res.json()["port_set"]["rcon_port"]
    export_dir = api.root / ".onx" / "branch-exports" / start_res.json()["runtime_id"]
    assert export_dir.is_dir()

    c_res = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/console?branch=feat-a", headers=api.header
    )
    assert c_res.status_code == 200, c_res.text
    assert any("Branch log line 1" in line for line in c_res.json()["lines"])

    cmd_res = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/command?branch=feat-a",
        json={"command": "list"},
        headers=api.header,
    )
    assert cmd_res.status_code == 200, cmd_res.text
    assert cmd_res.json()["output"] == "branch-rcon:list"
    assert ("command", "list", rcon_port) in FakeRconClient.sent

    # Stop -> container & export dir persist; historical logs remain readable
    stop_res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/stop", json={}, headers=api.header
    )
    assert stop_res.status_code == 200, stop_res.text
    assert export_dir.exists()

    rt_stopped = await api.client.get(f"{VERSIONING}/branches/feat-a/runtime", headers=api.header)
    assert rt_stopped.status_code == 200
    assert rt_stopped.json()["container_provisioned"] is True
    assert rt_stopped.json()["runtime_status"] == "stopped"

    hist_res = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/console?branch=feat-a", headers=api.header
    )
    assert hist_res.status_code == 200, hist_res.text

    # Resume existing container on start without re-provisioning
    resumed = await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["port_set"]["rcon_port"] == rcon_port

    # Stop again then Destroy -> wipes export & releases ports
    await api.client.post(f"{VERSIONING}/branches/feat-a/stop", json={}, headers=api.header)
    destroy_res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/destroy",
        json={},
        headers=api.header,
    )
    assert destroy_res.status_code == 200, destroy_res.text
    assert destroy_res.json()["container_provisioned"] is False
    assert not export_dir.exists()

    c_after = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/console?branch=feat-a", headers=api.header
    )
    assert c_after.status_code == 404


# ---------------------------------------------------------------------------
# B.2: Branch-Aware Plugins (CAS + Lockfile), main protection, Simple intact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b2_branch_plugins_isolation_and_simple_mode_intact(trackb_api: Any) -> None:
    api = trackb_api
    jar_bytes = _make_jar_bytes("BranchSpark", "1.2.3")

    # Direct mutation on main is forbidden
    main_up = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/upload?branch=main",
        files={"file": ("BranchSpark-1.2.3.jar", jar_bytes, "application/java-archive")},
        headers=api.header,
    )
    assert main_up.status_code in (403, 409), main_up.text

    # Upload on working branch feat-a -> writes CAS + feat-a lockfile, main untouched
    up = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/upload?branch=feat-a",
        files={"file": ("BranchSpark-1.2.3.jar", jar_bytes, "application/java-archive")},
        headers=api.header,
    )
    assert up.status_code == 201, up.text
    plugin_id = up.json()["plugin_id"]
    assert not (api.root / "plugins" / "BranchSpark-1.2.3.jar").exists()

    feat_list = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/plugins?branch=feat-a", headers=api.header
    )
    assert feat_list.status_code == 200, feat_list.text
    items = feat_list.json()
    assert len(items) == 1
    assert items[0]["name"] == "BranchSpark"
    assert items[0]["status"] == "enabled"
    assert items[0]["is_disabled_on_disk"] is False
    assert items[0]["is_committed"] is False

    main_list = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/plugins?branch=main", headers=api.header
    )
    assert main_list.status_code == 200
    assert main_list.json() == []

    # Toggle and delete on feat-a
    tog = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/toggle?branch=feat-a",
        json={"plugin_id": plugin_id, "enabled": False},
        headers=api.header,
    )
    assert tog.status_code == 200, tog.text
    assert tog.json()["enabled"] is False
    toggled_plugin_id = tog.json()["plugin_id"]

    rem = await api.client.delete(
        f"/api/v1/servers/{SERVER_ID}/plugins/{toggled_plugin_id}?branch=feat-a",
        headers=api.header,
    )
    assert rem.status_code == 204, rem.text

    # Simple mode remains Git-free and manages live plugins normally
    s_ver = await api.client.get(
        f"/api/v1/servers/{SIMPLE_ID}/versioning/branches", headers=api.header
    )
    assert s_ver.status_code == 409

    s_up = await api.client.post(
        f"/api/v1/servers/{SIMPLE_ID}/plugins/upload",
        files={
            "file": (
                "SimplePlugin-1.0.0.jar",
                _make_jar_bytes("SimplePlugin"),
                "application/java-archive",
            )
        },
        headers=api.header,
    )
    assert s_up.status_code == 201, s_up.text
    assert (api.simple_root / "plugins" / "SimplePlugin-1.0.0.jar").exists()


# ---------------------------------------------------------------------------
# B.3: Branch vs Main Settings + Pending settings/... Auto-Merge & Conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b3_settings_branch_isolation_pending_merge_and_discard(trackb_api: Any) -> None:
    api = trackb_api

    # 1. Edit on working branch feat-a -> auto-commits on feat-a, leaves main untouched
    patch_feat = await api.client.patch(
        f"/api/v1/servers/{SERVER_ID}?branch=feat-a",
        json={"min_memory_mb": 1536, "properties": {"motd": "FeatAMotd", "max-players": 42}},
        headers=api.header,
    )
    assert patch_feat.status_code == 200, patch_feat.text

    get_feat = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}?branch=feat-a", headers=api.header
    )
    assert get_feat.status_code == 200
    assert get_feat.json()["motd"] == "FeatAMotd"
    assert get_feat.json()["max_players"] == 42
    assert get_feat.json()["min_memory_mb"] == 1536

    get_main = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}?branch=main", headers=api.header
    )
    assert get_main.status_code == 200
    assert get_main.json()["motd"] == "MainWorld"
    assert "motd=MainWorld" in (api.root / "server.properties").read_text(encoding="utf-8")

    # 2. Edit on main -> queues settings/... branch + discard
    patch_main = await api.client.patch(
        f"/api/v1/servers/{SERVER_ID}?branch=main",
        json={"properties": {"motd": "QueuedMainMotd"}},
        headers=api.header,
    )
    assert patch_main.status_code == 200, patch_main.text

    get_main2 = await api.client.get(f"/api/v1/servers/{SERVER_ID}", headers=api.header)
    pending = get_main2.json()["pending_settings_branch"]
    assert pending is not None
    assert pending["branch_name"].startswith("settings/")
    assert pending["status"] == "pending"

    del_res = await api.client.delete(
        f"/api/v1/servers/{SERVER_ID}/settings/pending", headers=api.header
    )
    assert del_res.status_code == 200
    assert del_res.json()["discarded"] is True

    get_main3 = await api.client.get(f"/api/v1/servers/{SERVER_ID}", headers=api.header)
    assert get_main3.json()["pending_settings_branch"] is None

    # 3. Re-queue on main and auto-merge on restart
    await api.client.patch(
        f"/api/v1/servers/{SERVER_ID}?branch=main",
        json={"properties": {"motd": "MergedOnRestart"}},
        headers=api.header,
    )
    applied = await auto_merge_pending_settings_on_restart(SERVER_ID, layout=api.layout)
    assert len(applied) == 1

    get_main4 = await api.client.get(f"/api/v1/servers/{SERVER_ID}", headers=api.header)
    assert get_main4.json()["pending_settings_branch"] is None
    assert get_main4.json()["motd"] == "MergedOnRestart"


@pytest.mark.asyncio
async def test_b3_pending_settings_conflict_is_non_fatal(trackb_api: Any) -> None:
    api = trackb_api
    # Queue change to max-players on settings/...
    await api.client.patch(
        f"/api/v1/servers/{SERVER_ID}?branch=main",
        json={"properties": {"max-players": 55}},
        headers=api.header,
    )
    # Create conflicting commit on main worktree directly
    info = GitBranchService(api.layout).get_branch(SERVER_ID, api.root, "main")
    assert info is not None and info.worktree_path is not None
    main_wt = Path(info.worktree_path)
    props_path = main_wt / "server.properties"
    props_path.write_text(
        props_path.read_text(encoding="utf-8").replace("max-players=20", "max-players=99"),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(main_wt), "add", "server.properties"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main_wt),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "conflicting main change",
        ],
        check=True,
    )

    with pytest.raises(Exception, match="."):
        await auto_merge_pending_settings_on_restart(SERVER_ID, layout=api.layout)

    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(ServerBranchModel).where(
                    ServerBranchModel.server_id == SERVER_ID,
                    ServerBranchModel.pending_merge_on_restart.is_(True),
                )
            )
        ).scalars().first()
        assert row is not None
        assert row.pending_merge_status == "needs_resolution"


# ---------------------------------------------------------------------------
# B.4: Per-Branch Network Exposure, CGNAT Detection & Teardown on Stop/Destroy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b4_per_branch_exposure_cgnat_and_stop_teardown(
    trackb_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = trackb_api

    start_res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )
    assert start_res.status_code == 201
    game_port = start_res.json()["port_set"]["game_port"]

    # Configure Cloudflare Quick Preview on branch feat-a (mocks CloudflaredSupervisor.start_quick)
    from app.modules.exposure.application import commands as exp_cmds

    async def fake_start_quick(
        _self: Any,
        local_url: str,
        *,
        on_status: Any = None,
        on_url: Any = None,
    ) -> bool:
        port_part = local_url.rsplit(":", 1)[-1]
        if on_url is not None:
            await on_url(f"https://branch-{port_part}.trycloudflare.com")
        if on_status is not None:
            await on_status("ACTIVE")
        return True

    async def fake_stop(_self: Any) -> None:
        return None

    monkeypatch.setattr(exp_cmds.CloudflaredSupervisor, "start_quick", fake_start_quick)
    monkeypatch.setattr(exp_cmds.CloudflaredSupervisor, "stop", fake_stop)

    put_res = await api.client.put(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=feat-a",
        json={
            "method": "cloudflare_tcp",
            "desired_state": "ENABLED",
            "cloudflare_mode": "quick",
            "acknowledged_warning": True,
        },
        headers=api.header,
    )
    assert put_res.status_code == 200, put_res.text
    get_res = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=feat-a", headers=api.header
    )
    assert get_res.status_code == 200, get_res.text
    body = get_res.json()
    assert body["branch_name"] == "feat-a"
    assert body["allocated_game_port"] == game_port
    assert body["ephemeral"] is True
    assert f"branch-{game_port}.trycloudflare.com" in (body["targets"][0]["public_address"] or "")

    # Main exposure remains independent/disabled
    main_exp = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=main", headers=api.header
    )
    assert main_exp.status_code == 200
    assert main_exp.json()["method"] == "none"

    # Stop branch container automatically tears down branch exposure
    await api.client.post(f"{VERSIONING}/branches/feat-a/stop", json={}, headers=api.header)
    after_stop = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=feat-a", headers=api.header
    )
    assert after_stop.status_code == 200
    assert after_stop.json()["desired_state"] == "DISABLED"

    # CGNAT detection on UPnP port_forward on branch
    await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )

    async def fake_cgnat_map(_self: Any, *_args: Any, **_kwargs: Any) -> Any:
        from app.modules.exposure.infrastructure.upnp import UPnPResult

        return UPnPResult(
            success=False,
            external_ip="100.64.5.9",
            error_code="CGNAT_DETECTED",
            error_message="Router reported CGNAT WAN IP 100.64.5.9",
        )

    monkeypatch.setattr(exp_cmds.AsyncUPnPService, "attempt_mapping", fake_cgnat_map)
    upnp_res = await api.client.put(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=feat-a",
        json={
            "method": "port_forward",
            "desired_state": "ENABLED",
            "subdomain_prefix": "play",
            "base_domain": "example.com",
            "srv_record_enabled": True,
        },
        headers=api.header,
    )
    assert upnp_res.status_code == 200, upnp_res.text
    upnp_get = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/exposure?branch=feat-a", headers=api.header
    )
    assert upnp_get.status_code == 200, upnp_get.text
    upnp_body = upnp_get.json()
    assert upnp_body["upnp_status"] == "CGNAT_DETECTED"
    assert upnp_body["detected_wan_ip"] == "100.64.5.9"
    assert upnp_body["srv_record_hint"] is not None


@pytest.mark.asyncio
async def test_b5_staging_branch_plugin_install_and_auto_merge_into_main(
    trackb_api: Any,
) -> None:
    api = trackb_api
    jar_bytes = _make_jar_bytes("InitialAddon", "1.0.0")
    branch_name = "setup-initial-addons"

    br = await api.client.post(
        f"{VERSIONING}/branches",
        json={"name": branch_name},
        headers=api.header,
    )
    assert br.status_code == 201, br.text

    up = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/upload?branch={branch_name}",
        files={"file": ("InitialAddon-1.0.0.jar", jar_bytes, "application/java-archive")},
        headers=api.header,
    )
    assert up.status_code == 201, up.text

    cm = await api.client.post(
        f"{VERSIONING}/commits",
        json={"branch_name": branch_name, "message": "Install initial addons"},
        headers=api.header,
    )
    assert cm.status_code == 201, cm.text

    mg = await api.client.post(
        f"{VERSIONING}/commits/merge",
        json={
            "target_branch_name": "main",
            "source_branch_name": branch_name,
            "message": "Auto-merge initial addons into main",
            "force": True,
            "force_bypass_protection": True,
            "force_reason": "Initial server creation add-on setup",
        },
        headers=api.header,
    )
    assert mg.status_code == 201, mg.text

    dl = await api.client.delete(f"{VERSIONING}/branches/{branch_name}", headers=api.header)
    assert dl.status_code == 200, dl.text

    main_list = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/plugins?branch=main", headers=api.header
    )
    assert main_list.status_code == 200, main_list.text
    items = main_list.json()
    assert len(items) == 1
    assert items[0]["name"] == "InitialAddon"
    assert items[0]["status"] == "enabled"
    assert items[0]["is_disabled_on_disk"] is False
    assert items[0]["is_committed"] is True
    assert (api.root / "plugins" / "InitialAddon-1.0.0.jar").is_file()


@pytest.mark.asyncio
async def test_b6_disabling_plugin_prunes_active_jar_across_branch_resume_and_main_merge(
    trackb_api: Any,
) -> None:
    api = trackb_api
    jar_bytes = _make_jar_bytes("DisableMe", "1.0.0")

    # 1. Install plugin on feat-a -> default status "enabled", start -> active jar exported
    up = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/upload?branch=feat-a",
        files={"file": ("DisableMe-1.0.0.jar", jar_bytes, "application/java-archive")},
        headers=api.header,
    )
    assert up.status_code == 201, up.text
    plugin_id = up.json()["plugin_id"]

    start1 = await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )
    assert start1.status_code == 201, start1.text
    export_dir = api.root / ".onx" / "branch-exports" / start1.json()["runtime_id"]
    assert (export_dir / "plugins" / "DisableMe-1.0.0.jar").is_file()

    # 2. Stop branch container, disable plugin on feat-a, resume -> active jar pruned!
    stop1 = await api.client.post(
        f"{VERSIONING}/branches/feat-a/stop", json={}, headers=api.header
    )
    assert stop1.status_code == 200, stop1.text

    dis = await api.client.post(
        f"/api/v1/servers/{SERVER_ID}/plugins/{plugin_id}/disable?branch=feat-a",
        headers=api.header,
    )
    assert dis.status_code == 200, dis.text

    feat_list = await api.client.get(
        f"/api/v1/servers/{SERVER_ID}/plugins?branch=feat-a", headers=api.header
    )
    assert feat_list.status_code == 200
    assert feat_list.json()[0]["status"] == "disabled"
    assert feat_list.json()[0]["is_disabled_on_disk"] is True

    start2 = await api.client.post(
        f"{VERSIONING}/branches/feat-a/run",
        json={"check_os_ports": False},
        headers=api.header,
    )
    assert start2.status_code == 201, start2.text
    assert not (export_dir / "plugins" / "DisableMe-1.0.0.jar").exists()
    assert (export_dir / "plugins" / "DisableMe-1.0.0.jar.disabled").is_file()

    # 3. Stop, commit, merge into main when main already had active jar -> active jar pruned!
    await api.client.post(f"{VERSIONING}/branches/feat-a/stop", json={}, headers=api.header)
    await api.client.post(
        f"{VERSIONING}/commits",
        json={"branch_name": "feat-a", "message": "Disable DisableMe plugin"},
        headers=api.header,
    )
    # Simulate active jar sitting on live main root before merge
    (api.root / "plugins" / "DisableMe-1.0.0.jar").write_bytes(jar_bytes)

    mg = await api.client.post(
        f"{VERSIONING}/commits/merge",
        json={
            "target_branch_name": "main",
            "source_branch_name": "feat-a",
            "message": "Merge disabled plugin into main",
            "force": True,
            "force_bypass_protection": True,
            "force_reason": "Test disabled plugin sync",
        },
        headers=api.header,
    )
    assert mg.status_code == 201, mg.text
    assert not (api.root / "plugins" / "DisableMe-1.0.0.jar").exists()
    assert (api.root / "plugins" / "DisableMe-1.0.0.jar.disabled").is_file()
