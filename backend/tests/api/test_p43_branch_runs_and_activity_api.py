"""P4-3 API tests: data templates, port sets, branch runs, console, activity, RBAC."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.main import app
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.create_branch import (
    CreateBranchCommand,
    CreateBranchHandler,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.branch_runtime_service import (
    BranchRuntimeService,
    BranchStartRequest,
)
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerDataTemplateModel,
    ServerRuntimeModel,
)
from tests.api.test_api_endpoints import _seed_api_key_header

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="P4-3 Advanced-mode routes require a POSIX host"
)

SERVER_ID = "srv-p43"
OTHER_SERVER_ID = "srv-p43-other"
VERSIONING = f"/api/v1/servers/{SERVER_ID}/versioning"
ACTIVITY = f"/api/v1/servers/{SERVER_ID}/activity"


class FakeDockerRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.running = True
        self.logs = "line-one\nline-two"

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
            return 0, "container-id-p43"
        return 0, ""


class FakeRconClient:
    sent: list[tuple[str, str, int, str]] = []

    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password

    async def connect(self) -> None:
        type(self).sent.append(("connect", self.host, self.port, self.password))

    async def close(self) -> None:
        pass

    async def send_command(self, command: str) -> str:
        type(self).sent.append(("command", command, self.port, self.password))
        if command == "save-all flush":
            return "Saved the game"
        return f"result:{command}"


class RefusingRconClient(FakeRconClient):
    async def connect(self) -> None:
        raise ConnectionError("rcon unavailable (password=super-secret)")


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(
    server_id: str,
    root: Path,
    *,
    mode: str = "advanced",
    provider: str = "docker",
    pass_status: str = "STOPPED",
) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=server_id,
                name=server_id,
                server_type="paper",
                minecraft_version="1.20.4",
                status=pass_status,
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=29965 if server_id == SERVER_ID else 29966,
                java_args="-Xmx1G",
                memory_max_mb=4096,
                cpu_cores=2,
                mode=mode,
                provider=provider,
                max_concurrent_branch_runs=3,
                external_id=f"onx-{server_id}",
            )
        )
        await session.commit()


def _write_server_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text(
        "motd=P43\nrcon.password=super-secret\nrcon.port=25600\n", encoding="utf-8"
    )
    (root / "server.jar").write_bytes(b"jar")
    (root / "world").mkdir(exist_ok=True)
    (root / "world" / "level.dat").write_bytes(b"level-data")
    (root / "ops.json").write_text("[]", encoding="utf-8")


def _init_repository(server_id: str, root: Path) -> None:
    from app.modules.versioning.application.lockfile_service import LockfileService

    layout = ensure_host_state_layout()
    lockfile = _empty_lockfile()
    GitRepositoryService(layout).initialize(server_id, root, lockfile)
    LockfileService(layout).write(server_id, lockfile)


async def _create_branch(server_id: str, name: str) -> None:
    await CreateBranchHandler().handle(
        CreateBranchCommand(server_id=server_id, name=name)
    )


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_MASTER_KEK", "11" * 32)
    (tmp_path / "servers").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
async def p43_api(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    import psutil

    from app.api.v1.routers import versioning as versioning_router

    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(available=64 * 1024 * 1024 * 1024),
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 32)
    FakeRconClient.sent.clear()

    root = host_state / "servers" / SERVER_ID
    _write_server_tree(root)
    await _seed_server(SERVER_ID, root)
    _init_repository(SERVER_ID, root)
    await _create_branch(SERVER_ID, "feat-a")
    await _create_branch(SERVER_ID, "feat-b")

    header = await _seed_api_key_header(
        client, created_user["user_id"], ["admin:full"]
    )
    runner = FakeDockerRunner()
    service = BranchRuntimeService(
        ensure_host_state_layout(),
        session_factory=database.session_factory,
        engine=database._engine,
        docker_runner=runner,
        rcon_client_factory=FakeRconClient,
    )
    app.dependency_overrides[versioning_router.get_branch_runtime_service] = (
        lambda: service
    )
    try:
        yield SimpleNamespace(
            client=client,
            root=root,
            header=header,
            user=created_user,
            runner=runner,
            service=service,
            layout=ensure_host_state_layout(),
        )
    finally:
        app.dependency_overrides.pop(versioning_router.get_branch_runtime_service, None)


async def _start(api: Any, branch: str = "feat-a", **overrides: Any) -> dict:
    body = {"check_os_ports": False}
    body.update(overrides)
    res = await api.client.post(
        f"{VERSIONING}/branches/{branch}/run", json=body, headers=api.header
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _stop(api: Any, branch: str = "feat-a", **overrides: Any) -> dict:
    body: dict[str, Any] = {}
    body.update(overrides)
    res = await api.client.post(
        f"{VERSIONING}/branches/{branch}/stop", json=body, headers=api.header
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# 1. Data Template CRUD & quiescent hot clone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_template_crud_and_live_clone(p43_api: Any) -> None:
    api = p43_api
    res = await api.client.get(f"{VERSIONING}/data-templates", headers=api.header)
    assert res.status_code == 200
    assert res.json() == []

    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-live", "description": "live clone"},
        headers=api.header,
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["status"] == "ready"
    assert payload["operation_id"]
    template_id = payload["id"]
    template_root = api.layout.data_templates_dir(SERVER_ID) / template_id
    assert (template_root / ".onx-complete.json").is_file()
    assert (template_root / "world" / "level.dat").is_file()

    from app.modules.operations.infrastructure.models import OperationModel

    async with database.session_factory() as session:
        op = await session.get(OperationModel, payload["operation_id"])
        assert op is not None and op.status == "COMPLETED"

    res = await api.client.get(f"{VERSIONING}/data-templates", headers=api.header)
    assert res.status_code == 200
    assert [item["id"] for item in res.json()] == [template_id]

    # async mode returns 202 with a durable operation id
    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-async", "async_mode": True},
        headers=api.header,
    )
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "cloning"
    async_id = res.json()["id"]
    async_op_id = res.json()["operation_id"]
    assert async_op_id

    # The background clone finishes without leaving a pending task behind.
    from app.modules.operations.infrastructure.models import OperationModel

    async_op = None
    for _ in range(200):
        async with database.session_factory() as session:
            async_op = await session.get(OperationModel, async_op_id)
        if async_op is not None and async_op.status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
    assert async_op is not None and async_op.status == "COMPLETED"
    async with database.session_factory() as session:
        row = await session.get(ServerDataTemplateModel, async_id)
        assert row is not None and row.status == "ready"

    # duplicate name
    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-live"},
        headers=api.header,
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_running_rcon_refusal_marks_template_and_operation_failed(
    p43_api: Any,
) -> None:
    api = p43_api
    api.runner.running = True
    api.service.rcon_client_factory = RefusingRconClient
    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-refused"},
        headers=api.header,
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "HOT_CLONE_REFUSED"

    async with database.session_factory() as session:
        from sqlalchemy import select

        row = (
            (
                await session.execute(
                    select(ServerDataTemplateModel).where(
                        ServerDataTemplateModel.name == "tmpl-refused"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert row is not None and row.status == "failed"
        from app.modules.operations.infrastructure.models import OperationModel

        op = await session.get(OperationModel, row.operation_id)
        assert op is not None and op.status == "FAILED"


@pytest.mark.asyncio
async def test_delete_data_template_guards_and_cross_server_404(p43_api: Any) -> None:
    api = p43_api
    other_root = api.root.parent / OTHER_SERVER_ID
    other_root.mkdir(parents=True, exist_ok=True)
    await _seed_server(OTHER_SERVER_ID, other_root)
    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-delete"},
        headers=api.header,
    )
    assert res.status_code == 201, res.text
    template_id = res.json()["id"]
    template_root = api.layout.data_templates_dir(SERVER_ID) / template_id

    # mount by an active runtime -> 409
    async with database.session_factory() as session:
        session.add(
            ServerRuntimeModel(
                id="rt-mounted",
                server_id=SERVER_ID,
                commit_id="commit-mounted",
                status="running",
                branch_name="feat-a",
                data_template_id=template_id,
            )
        )
        await session.commit()
    res = await api.client.delete(
        f"{VERSIONING}/data-templates/{template_id}", headers=api.header
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "CONFLICT"

    async with database.session_factory() as session:
        rt = await session.get(ServerRuntimeModel, "rt-mounted")
        assert rt is not None
        rt.status = "terminated"
        await session.commit()

    # cross-server template id -> 404
    res = await api.client.delete(
        f"/api/v1/servers/{OTHER_SERVER_ID}/versioning/data-templates/{template_id}",
        headers=api.header,
    )
    assert res.status_code == 404, res.text

    res = await api.client.delete(
        f"{VERSIONING}/data-templates/{template_id}", headers=api.header
    )
    assert res.status_code == 200, res.text
    assert not template_root.exists()
    async with database.session_factory() as session:
        assert await session.get(ServerDataTemplateModel, template_id) is None


# ---------------------------------------------------------------------------
# 2. Port set allocation & manual assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_port_set_allocate_and_put(p43_api: Any) -> None:
    api = p43_api
    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/port-set/allocate",
        json={
            "include_query": True,
            "plugin_port_names": ["geyser"],
            "check_os_ports": False,
        },
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    allocated = res.json()["port_set"]
    assert allocated["game_port"] != allocated["rcon_port"]
    assert allocated["query_port"]
    assert allocated["plugin_ports"]["geyser"]

    async with database.session_factory() as session:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(ServerBranchModel).where(
                    ServerBranchModel.server_id == SERVER_ID,
                    ServerBranchModel.name == "feat-a",
                )
            )
        ).scalars().first()
        assert row is not None and row.port_set_json["game_port"] == allocated["game_port"]

    # conflicting ports on another branch -> 409
    res = await api.client.put(
        f"{VERSIONING}/branches/feat-b/port-set",
        json={
            "game_port": allocated["game_port"],
            "rcon_port": allocated["rcon_port"],
            "check_os_ports": False,
        },
        headers=api.header,
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "DUPLICATE_PORT_SET"

    # main -> 422
    res = await api.client.put(
        f"{VERSIONING}/branches/main/port-set",
        json={"game_port": 25700, "rcon_port": 25701},
        headers=api.header,
    )
    assert res.status_code == 422, res.text

    # explicit unique assignment works
    res = await api.client.put(
        f"{VERSIONING}/branches/feat-b/port-set",
        json={
            "game_port": 25800,
            "rcon_port": 25801,
            "query_port": 25802,
            "plugin_ports": {"voice": 25803},
            "check_os_ports": False,
        },
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    assert res.json()["port_set"]["game_port"] == 25800

    # active runtime refuses re-allocation -> 409 BRANCH_RUNTIME_ACTIVE
    await _start(api)
    res = await api.client.put(
        f"{VERSIONING}/branches/feat-a/port-set",
        json={"game_port": 25900, "rcon_port": 25901, "check_os_ports": False},
        headers=api.header,
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "BRANCH_RUNTIME_ACTIVE"
    await _stop(api)


# ---------------------------------------------------------------------------
# 3. Branch run, runtime status, save-template, stop, uncommitted warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_run_status_save_stop_and_uncommitted_warning(
    p43_api: Any,
) -> None:
    api = p43_api
    started = await _start(api)
    assert started["commit_sha"]
    assert started["runtime_id"]
    assert started["port_set"]["game_port"] >= 1024
    assert started["uncommitted_changes_warning"] is False
    runtime_id = started["runtime_id"]

    res = await api.client.get(
        f"{VERSIONING}/branches/feat-a/runtime", headers=api.header
    )
    assert res.status_code == 200, res.text
    status = res.json()
    assert status["runtime_status"] == "running"
    assert status["runtime_id"] == runtime_id
    assert status["active_commit_sha"] == started["commit_sha"]
    assert status["port_set"]["rcon_port"] == started["port_set"]["rcon_port"]
    assert status["container_liveness"] is True
    assert status["worktree_locked"] is True
    assert status["worktree_lock_reason"] == f"runtime:{runtime_id}"

    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/save-data-template",
        json={"name": "tmpl-branch", "description": "from run"},
        headers=api.header,
    )
    assert res.status_code == 201, res.text
    assert res.json()["source_branch_name"] == "feat-a"

    stopped = await _stop(
        api,
        save_template_name="tmpl-on-stop",
        keep_port_assignment=True,
    )
    assert stopped["status"] == "stopped"
    assert stopped["saved_template_id"]
    assert stopped["saved_template_name"] == "tmpl-on-stop"

    res = await api.client.get(
        f"{VERSIONING}/branches/feat-a/runtime", headers=api.header
    )
    assert res.status_code == 200
    assert res.json()["runtime_status"] == "stopped"
    assert res.json()["worktree_locked"] is False
    # keep_port_assignment preserved the branch port set
    assert res.json()["port_set"] is not None

    worktree = api.root / ".onx" / "worktrees" / "feat-a"
    (worktree / "dirty-file.txt").write_text("uncommitted", encoding="utf-8")
    dirty = await _start(api)
    assert dirty["uncommitted_changes_warning"] is True
    await _stop(api)


# ---------------------------------------------------------------------------
# 4. Branch console & loopback RCON commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_console_and_loopback_rcon(p43_api: Any) -> None:
    api = p43_api
    started = await _start(api)
    rcon_port = started["port_set"]["rcon_port"]

    api.runner.logs = "boot-line\nready-line"
    res = await api.client.get(
        f"{VERSIONING}/branches/feat-a/console?tail=50", headers=api.header
    )
    assert res.status_code == 200, res.text
    assert res.json()["lines"] == ["boot-line", "ready-line"]
    assert any(
        call[:2] == ["logs", "--tail"] and call[-2:] == ["50", res.json()["container_name"]]
        for call in api.runner.calls
    )

    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/console/command",
        json={"command": "list"},
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    assert res.json()["output"] == "result:list"
    assert any(
        entry[0] == "command" and entry[1] == "list" and entry[2] == rcon_port
        for entry in FakeRconClient.sent
    )
    assert all(entry[1] == "127.0.0.1" for entry in FakeRconClient.sent if entry[0] == "connect")

    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/console/command",
        json={"command": "say hi\nop someone"},
        headers=api.header,
    )
    assert res.status_code == 422, res.text

    # RCON failures must not leak the password
    class LeakyFailure(FakeRconClient):
        async def send_command(self, _command: str) -> str:
            raise RuntimeError("boom super-secret")

    api.service.rcon_client_factory = LeakyFailure
    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/console/command",
        json={"command": "list"},
        headers=api.header,
    )
    assert res.status_code == 503, res.text
    assert "super-secret" not in res.text

    await _stop(api)
    res = await api.client.get(
        f"{VERSIONING}/branches/feat-a/console", headers=api.header
    )
    assert res.status_code == 404, res.text
    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/console/command",
        json={"command": "list"},
        headers=api.header,
    )
    assert res.status_code == 404, res.text


# ---------------------------------------------------------------------------
# 5. Branch-scoped activity filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_scoped_activity_filtering(p43_api: Any) -> None:
    api = p43_api
    for branch in ("feat-a", "feat-b"):
        await _start(api, branch)
        res = await api.client.post(
            f"{VERSIONING}/branches/{branch}/save-data-template",
            json={"name": f"tmpl-{branch}"},
            headers=api.header,
        )
        assert res.status_code == 201, res.text
        await _stop(api, branch)

    res = await api.client.get(
        f"{ACTIVITY}?branch=feat-a&limit=200", headers=api.header
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"]
    assert all(item["branch_name"] == "feat-a" for item in payload["items"])
    event_types = {item["event_type"] for item in payload["items"]}
    assert "versioning.branch_started" in event_types
    assert "versioning.data_template_saved" in event_types
    assert "versioning.branch_stopped" in event_types

    res = await api.client.get(f"{ACTIVITY}?limit=200", headers=api.header)
    assert res.status_code == 200
    unfiltered = res.json()["items"]
    assert {item["branch_name"] for item in unfiltered} >= {"feat-a", "feat-b"}


# ---------------------------------------------------------------------------
# 6. RBAC + P4-2 hardening regressions (M4, L4, M1, L1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_read_vs_mutate(p43_api: Any) -> None:
    api = p43_api
    viewer = await _seed_api_key_header(
        api.client, api.user["user_id"], ["server:version:read"]
    )
    for path in (
        "/data-templates",
        "/branches/feat-a/runtime",
        "/branches/feat-a/console",
    ):
        res = await api.client.get(f"{VERSIONING}{path}", headers=viewer)
        assert res.status_code != 403, (path, res.text)

    mutations = [
        ("POST", "/data-templates", {"name": "rbac"}),
        ("DELETE", "/data-templates/missing", None),
        ("POST", "/branches/feat-a/port-set/allocate", {}),
        ("PUT", "/branches/feat-a/port-set", {"game_port": 26000, "rcon_port": 26001}),
        ("POST", "/branches/feat-a/run", {}),
        ("POST", "/branches/feat-a/stop", {}),
        ("POST", "/branches/feat-a/save-data-template", {"name": "rbac"}),
        ("POST", "/branches/feat-a/console/command", {"command": "list"}),
    ]
    for method, path, body in mutations:
        res = await api.client.request(
            method,
            f"{VERSIONING}{path}",
            json=body,
            headers=viewer,
        )
        assert res.status_code == 403, (method, path, res.text)


@pytest.mark.asyncio
async def test_m4_data_template_ownership_and_containment(p43_api: Any) -> None:
    api = p43_api
    other_root = api.root.parent / OTHER_SERVER_ID
    _write_server_tree(other_root)
    await _seed_server(OTHER_SERVER_ID, other_root)
    _init_repository(OTHER_SERVER_ID, other_root)
    await _create_branch(OTHER_SERVER_ID, "feat-a")

    # template owned by SERVER_ID
    res = await api.client.post(
        f"{VERSIONING}/data-templates",
        json={"name": "tmpl-owned"},
        headers=api.header,
    )
    assert res.status_code == 201, res.text
    foreign_id = res.json()["id"]

    res = await api.client.post(
        f"/api/v1/servers/{OTHER_SERVER_ID}/versioning/branches/feat-a/run",
        json={"data_template_id": foreign_id, "check_os_ports": False},
        headers=api.header,
    )
    assert res.status_code == 404, res.text

    # DB row pointing outside the server template root fails closed (422)
    outside = api.root.parent / "outside-template"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / ".onx-complete.json").write_text("{}", encoding="utf-8")
    bad_id = uuid.uuid4().hex
    async with database.session_factory() as session:
        session.add(
            ServerDataTemplateModel(
                id=bad_id,
                server_id=OTHER_SERVER_ID,
                name="tmpl-outside",
                storage_path=str(outside),
                status="ready",
            )
        )
        await session.commit()
    res = await api.client.post(
        f"/api/v1/servers/{OTHER_SERVER_ID}/versioning/branches/feat-a/run",
        json={"data_template_id": bad_id, "check_os_ports": False},
        headers=api.header,
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_l4_runtime_ownership_on_stop(p43_api: Any) -> None:
    api = p43_api
    a = await _start(api, "feat-a")
    b = await _start(api, "feat-b")
    res = await api.client.post(
        f"{VERSIONING}/branches/feat-a/stop",
        json={"runtime_id": b["runtime_id"]},
        headers=api.header,
    )
    assert res.status_code == 404, res.text
    async with database.session_factory() as session:
        runtime = await session.get(ServerRuntimeModel, b["runtime_id"])
        assert runtime is not None and runtime.status == "running"
    await _stop(api, "feat-b", runtime_id=b["runtime_id"])
    await _stop(api, "feat-a", runtime_id=a["runtime_id"])


@pytest.mark.asyncio
async def test_m1_service_mode_guard_fails_closed(p43_api: Any) -> None:
    from app.core.exceptions import ServerModeVersioningDisabledError

    api = p43_api
    await _seed_server(OTHER_SERVER_ID, api.root, mode="simple")
    request = BranchStartRequest(
        server_id=OTHER_SERVER_ID,
        server_root=api.root,
        branch_name="feat-a",
        server_mode="advanced",
        server_provider="docker",
        check_os_ports=False,
    )
    with pytest.raises(ServerModeVersioningDisabledError):
        await api.service.start_branch_runtime(request)


@pytest.mark.asyncio
async def test_l1_cancelled_export_joins_worker_and_cleans_export_root(
    p43_api: Any,
) -> None:
    api = p43_api
    started = threading.Event()
    finished = threading.Event()

    class SlowExport:
        def assert_no_unresolved_secrets(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def export(self, request: Any, **_kwargs: Any) -> Any:
            destination = Path(request.destination)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "secret.txt").write_text("very-secret", encoding="utf-8")
            started.set()
            time.sleep(0.4)
            finished.set()
            return SimpleNamespace(export_id=request.export_id)

    api.service.clean_export_service = SlowExport()
    task = asyncio.create_task(
        api.service.start_branch_runtime(
            BranchStartRequest(
                server_id=SERVER_ID,
                server_root=api.root,
                branch_name="feat-a",
                server_mode="advanced",
                server_provider="docker",
                check_os_ports=False,
            )
        )
    )
    assert await asyncio.to_thread(started.wait, 5.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set(), "worker thread was not joined before cancellation returned"
    exports_root = api.root / ".onx" / "branch-exports"
    assert not exports_root.exists() or list(exports_root.iterdir()) == []
