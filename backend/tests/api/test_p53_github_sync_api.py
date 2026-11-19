"""P5-3 API tests: GitHub sync, public webhooks, activity, and RBAC.

The suite exercises the production FastAPI routes, the production webhook
dispatcher, real Git subprocesses, and a real local Smart HTTP server backed by
``/usr/lib/git-core/git-http-backend``. Only the loopback ``url.*.insteadOf``
rewrite from the P5-2 engine suite is test-local.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.main import app
from app.modules.operations.application.services.operation_service import (
    get_operation_service,
    reset_operation_service,
)
from app.modules.operations.infrastructure.models import OperationModel
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerBranchModel,
)
from tests.api.test_api_endpoints import _seed_api_key_header
from tests.unit.versioning.test_p52_github_sync_engine import (
    _GIT_IDENTITY,
    _git,
    _LoopbackGitRunner,
    _ref_sha,
    _RemoteRepo,
    _SmartHTTPServer,
)

pytest_plugins = ["tests.api.test_api_endpoints"]

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="P5-3 Advanced-mode routes require a POSIX host"
)

SERVER_ID = "srv-p53"
VERSIONING = f"/api/v1/servers/{SERVER_ID}/versioning"
ACTIVITY = f"/api/v1/servers/{SERVER_ID}/activity"
WEBHOOK_PATH = f"/api/v1/webhooks/github/{SERVER_ID}"
REMOTE_URL = "https://github.com/octo/mc-server.git"
TOKEN = "ghp_p53_valid_token_0001"
REPLACEMENT_TOKEN = "ghp_p53_replacement_token_0002"
WEBHOOK_SECRET = "p53-initial-webhook-secret-" + "a" * 24


class _FetchGate:
    def __init__(self) -> None:
        self.enabled = False
        self.started = threading.Event()
        self.release = threading.Event()


class _GatedLoopbackRunner(_LoopbackGitRunner):
    """Production runner with a test-only fetch gate for async dispatch proof."""

    def __init__(self, *args: Any, gate: _FetchGate, **kwargs: Any) -> None:
        self._gate = gate
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def run(self, *args: Any, **kwargs: Any) -> Any:
        if self._gate.enabled and args and args[0] == "fetch":
            self._gate.started.set()
            self._gate.release.wait(timeout=30.0)
        return super().run(*args, **kwargs)


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


def _write_server_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.properties").write_text(
        "motd=P53\nrcon.password=super-secret\nrcon.port=25600\n", encoding="utf-8"
    )
    (root / "server.jar").write_bytes(b"jar")
    (root / "world").mkdir(exist_ok=True)
    (root / "world" / "level.dat").write_bytes(b"level-data")
    (root / "ops.json").write_text("[]", encoding="utf-8")


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _webhook_body(ref: str, before: str, after: str) -> bytes:
    # Deliberately non-canonical raw JSON: whitespace and unsorted keys prove
    # HMAC verification covers the exact bytes GitHub sent.
    return (
        b"{\n"
        b'  "repository": {"full_name": "octo/mc-server"},\n'
        b'  "after":"' + after.encode("utf-8") + b'",\n'
        b'  "before" : "' + before.encode("utf-8") + b'",\n'
        b'  "ref":"' + ref.encode("utf-8") + b'"\n'
        b"}\n"
    )


def _commit_worktree(worktree: Path, relpath: str, content: bytes, message: str) -> str:
    target = worktree / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(["add", "--", relpath], cwd=worktree)
    _git([*_GIT_IDENTITY, "commit", "-m", message], cwd=worktree)
    return _git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()


async def _wait_for_operation(operation_id: str, timeout: float = 20.0) -> OperationModel:
    deadline = time.monotonic() + timeout
    row: OperationModel | None = None
    while time.monotonic() < deadline:
        async with database.session_factory() as session:
            row = await session.get(OperationModel, operation_id)
        if row is not None and row.status in ("COMPLETED", "FAILED"):
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"operation {operation_id} did not finish: {row!r}")


async def _delivery_row(delivery_id: str) -> GitHubWebhookDeliveryModel | None:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(GitHubWebhookDeliveryModel).where(
                    GitHubWebhookDeliveryModel.server_id == SERVER_ID,
                    GitHubWebhookDeliveryModel.delivery_id == delivery_id,
                )
            )
        ).scalar_one_or_none()


async def _wait_for_delivery(
    delivery_id: str, expected: str, timeout: float = 20.0
) -> GitHubWebhookDeliveryModel:
    deadline = time.monotonic() + timeout
    row: GitHubWebhookDeliveryModel | None = None
    while time.monotonic() < deadline:
        row = await _delivery_row(delivery_id)
        if row is not None and row.status == expected:
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"delivery {delivery_id} did not reach {expected}: {row!r}")


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(tmp_path / "host-state"))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    monkeypatch.setenv("ONX_MASTER_KEK", "11" * 32)
    (tmp_path / "servers").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
async def p53_api(
    client: AsyncClient,
    created_user: dict,
    host_state: Path,
    buses: tuple[Any, Any, Any],
) -> Any:
    from app.api.v1.routers import versioning as versioning_router

    gate = _FetchGate()
    reset_operation_service()

    layout = ensure_host_state_layout()
    root = host_state / "servers" / SERVER_ID
    _write_server_tree(root)
    GitRepositoryService(layout).initialize(SERVER_ID, root, _empty_lockfile())
    LockfileService(layout).write(SERVER_ID, _empty_lockfile())
    repo_git = layout.repo_dir(SERVER_ID) / "repo.git"
    main_sha = _ref_sha(repo_git, "refs/heads/main")
    assert main_sha is not None

    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name=SERVER_ID,
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=29965,
                java_args="-Xmx1G",
                memory_max_mb=4096,
                cpu_cores=2,
                mode="advanced",
                provider="docker",
                max_concurrent_branch_runs=3,
                external_id=f"onx-{SERVER_ID}",
            )
        )
        session.add(
            ServerBranchModel(
                id="branch-main",
                server_id=SERVER_ID,
                name="main",
                head_commit_id=main_sha,
                status="active",
            )
        )
        await session.commit()

    remote_root = host_state / "remote-root"
    remote_bare = remote_root / "octo" / "mc-server.git"
    remote_bare.parent.mkdir(parents=True)
    _git(["init", "--bare", "--initial-branch=main", str(remote_bare)])
    _git(["-C", str(remote_bare), "config", "http.receivepack", "true"])

    smart = _SmartHTTPServer(remote_root)
    smart.__enter__()

    event_bus = buses[2]

    def runner_factory(path: Path, config_path: Path) -> _GatedLoopbackRunner:
        return _GatedLoopbackRunner(
            repo_path=path,
            config_path=config_path,
            git_executable="git",
            timeout=60.0,
            rewrite_port=smart.port,
            gate=gate,
        )

    service = versioning_router.create_github_sync_service(
        event_bus, git_runner_factory=runner_factory
    )
    app.dependency_overrides[versioning_router.get_github_sync_service] = lambda: service
    header = await _seed_api_key_header(
        client, created_user["user_id"], ["admin:full"]
    )

    try:
        yield SimpleNamespace(
            client=client,
            header=header,
            user=created_user,
            root=root,
            layout=layout,
            repo_git=repo_git,
            main_worktree=root / ".onx" / "worktrees" / "main",
            remote_bare=remote_bare,
            remote=_RemoteRepo(remote_bare, host_state / "remote-work"),
            smart=smart,
            gate=gate,
            service=service,
        )
    finally:
        gate.enabled = False
        gate.release.set()
        executor = get_operation_service(event_bus).executor
        tasks = list(executor._running_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for watcher in list(executor._timeout_watchers.values()):
            if not watcher.done():
                watcher.cancel()
        executor._running_tasks.clear()
        executor._timeout_watchers.clear()
        with suppress(Exception):
            service._get_repo_write_lock().close()
        app.dependency_overrides.pop(versioning_router.get_github_sync_service, None)
        reset_operation_service()
        smart.__exit__()


def _connect_body(
    *,
    token: str = TOKEN,
    enable_webhook: bool = True,
    webhook_secret: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "remote_url": REMOTE_URL,
        "auth_method": "pat",
        "credential_secret": token,
        "enable_webhook": enable_webhook,
    }
    if webhook_secret is not None:
        body["webhook_secret"] = webhook_secret
    return body


async def _connect(api: Any, **kwargs: Any) -> dict:
    api.smart.state.valid_tokens.add(kwargs.get("token", TOKEN))
    res = await api.client.post(
        f"{VERSIONING}/github/connect",
        json=_connect_body(**kwargs),
        headers=api.header,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _push_main(api: Any) -> dict:
    res = await api.client.post(
        f"{VERSIONING}/github/push",
        json={"branch_name": "main"},
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# 1. Unconnected status, deploy-key generation, schema extra="forbid"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconnected_status_deploy_key_and_schema_rejects_extra(p53_api: Any) -> None:
    api = p53_api

    res = await api.client.get(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200, res.text
    status = res.json()
    assert status["connected"] is False
    assert status["sync_status"] == "disconnected"
    assert status["webhook_path"] is None
    assert status["generated_webhook_secret"] is None

    for body in ({}, {"comment": "ci-key"}):
        res = await api.client.post(
            f"{VERSIONING}/github/deploy-key/generate", json=body, headers=api.header
        )
        assert res.status_code == 201, res.text
        key = res.json()
        assert key["server_id"] == SERVER_ID
        assert key["public_key_openssh"].startswith("ssh-ed25519 ")
        assert "BEGIN OPENSSH PRIVATE KEY" in key["private_key_pem"]
        assert key["fingerprint_sha256"].startswith("SHA256:")

    schema_cases = [
        ("POST", "/github/deploy-key/generate", {"comment": "x", "extra": True}),
        ("POST", "/github/connect", {**_connect_body(), "extra": True}),
        ("POST", "/github/credentials/rotate", {"enable_webhook": False, "extra": True}),
        ("POST", "/github/push", {"branch_name": "main", "extra": True}),
    ]
    for method, path, body in schema_cases:
        res = await api.client.request(
            method, f"{VERSIONING}{path}", json=body, headers=api.header
        )
        assert res.status_code == 422, (path, res.text)


# ---------------------------------------------------------------------------
# 2. Connect, one-time webhook secret, secret hygiene, auth classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_one_time_secret_and_secret_hygiene(p53_api: Any) -> None:
    api = p53_api

    res = await api.client.post(
        f"{VERSIONING}/github/connect",
        json=_connect_body(token="ghp_p53_bad_token"),
        headers=api.header,
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "GITHUB_AUTH_FAILED"
    assert res.json()["details"]["needs_reauth"] is True

    connected = await _connect(api, enable_webhook=True)
    assert connected["connected"] is True
    assert connected["webhook_enabled"] is True
    assert connected["webhook_path"] == WEBHOOK_PATH
    secret = connected["generated_webhook_secret"]
    assert secret
    assert TOKEN not in str(connected)
    assert secret not in str(connected).replace(secret, "", 1)

    config_text = (api.repo_git / "config").read_text(encoding="utf-8")
    gitconfig_text = (
        api.layout.repo_dir(SERVER_ID) / "gitconfig"
    ).read_text(encoding="utf-8")
    for content in (config_text, gitconfig_text):
        assert TOKEN not in content
        remote_section = content.split('[remote "origin"]', 1)
        if len(remote_section) == 2:
            assert "@" not in remote_section[1].split("[", 1)[0]

    res = await api.client.get(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200, res.text
    status = res.json()
    assert status["connected"] is True
    assert status["generated_webhook_secret"] is None
    assert TOKEN not in res.text
    assert secret not in res.text

    res = await api.client.post(
        f"{VERSIONING}/github/connect",
        json=_connect_body(token=TOKEN),
        headers=api.header,
    )
    assert res.status_code == 409, res.text


# ---------------------------------------------------------------------------
# 3. Push/fetch: force forbidden, clean FF, non-FF conflict, jar, reauth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_fetch_conflicts_jar_rejection_and_revoked_pat(p53_api: Any) -> None:
    api = p53_api
    await _connect(api, enable_webhook=False)

    res = await api.client.post(
        f"{VERSIONING}/github/push",
        json={"branch_name": "main", "force": True},
        headers=api.header,
    )
    assert res.status_code == 422, res.text

    pushed = await _push_main(api)
    assert pushed["sync_status"] == "synced"
    local_main = _ref_sha(api.repo_git, "refs/heads/main")
    assert local_main is not None
    assert _ref_sha(api.remote_bare, "refs/heads/main") == local_main

    GitBranchService(api.layout).create_branch(SERVER_ID, api.root, "bad-jar")
    _commit_worktree(
        api.root / ".onx" / "worktrees" / "bad-jar",
        "plugins/plain.jar",
        b"PK\x03\x04plain",
        "Add plain jar to feature branch",
    )
    res = await api.client.post(
        f"{VERSIONING}/github/push",
        json={"branch_name": "bad-jar"},
        headers=api.header,
    )
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "GITHUB_PUSH_REJECTED"
    assert res.json()["details"]["reason"] == "plain_jar_blob_forbidden"
    assert _ref_sha(api.remote_bare, "refs/heads/bad-jar") is None

    remote_sha = api.remote.advance_main(
        "remote.txt", b"from github\n", "Advance remote main"
    )
    res = await api.client.post(f"{VERSIONING}/github/fetch", json={}, headers=api.header)
    assert res.status_code == 200, res.text
    fetched = res.json()
    assert fetched["main_fast_forwarded"] is True
    assert fetched["main_sha"] == remote_sha
    assert _ref_sha(api.repo_git, "refs/heads/main") == remote_sha
    assert (api.main_worktree / "remote.txt").read_text(encoding="utf-8") == "from github\n"

    _commit_worktree(
        api.main_worktree, "local.txt", b"local\n", "Local divergent commit"
    )
    api.remote.advance_main("remote-2.txt", b"remote\n", "Remote divergent commit")
    res = await api.client.post(f"{VERSIONING}/github/fetch", json={}, headers=api.header)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "GITHUB_NON_FAST_FORWARD_MAIN"

    res = await api.client.get(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200
    assert res.json()["sync_status"] == "conflict"

    api.smart.state.revoked_tokens.add(TOKEN)
    res = await api.client.post(f"{VERSIONING}/github/fetch", json={}, headers=api.header)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "GITHUB_AUTH_FAILED"
    assert res.json()["details"]["needs_reauth"] is True

    res = await api.client.get(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200
    status = res.json()
    assert status["needs_reauth"] is True
    assert status["sync_status"] == "auth_failed"


# ---------------------------------------------------------------------------
# 4. Credential and webhook secret rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotation_rejects_invalid_combinations_and_recovers_reauth(p53_api: Any) -> None:
    api = p53_api
    await _connect(
        api, enable_webhook=True, webhook_secret=WEBHOOK_SECRET
    )

    for body in (
        {},
        {"disable_webhook": True, "enable_webhook": True},
    ):
        res = await api.client.post(
            f"{VERSIONING}/github/credentials/rotate", json=body, headers=api.header
        )
        assert res.status_code == 422, res.text

    api.smart.state.revoked_tokens.add(TOKEN)
    res = await api.client.post(f"{VERSIONING}/github/fetch", json={}, headers=api.header)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "GITHUB_AUTH_FAILED"

    api.smart.state.valid_tokens.add(REPLACEMENT_TOKEN)
    res = await api.client.post(
        f"{VERSIONING}/github/credentials/rotate",
        json={"credential_secret": REPLACEMENT_TOKEN},
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    rotated = res.json()
    assert rotated["needs_reauth"] is False
    assert rotated["sync_status"] == "idle"
    assert rotated["generated_webhook_secret"] is None

    res = await api.client.post(
        f"{VERSIONING}/github/credentials/rotate",
        json={"regenerate_webhook_secret": True},
        headers=api.header,
    )
    assert res.status_code == 200, res.text
    new_secret = res.json()["generated_webhook_secret"]
    assert new_secret and new_secret != WEBHOOK_SECRET

    ping_body = b'{"zen":"keep it simple"}\n'
    old_res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(WEBHOOK_SECRET, ping_body),
            "X-GitHub-Delivery": "rotate-old-secret",
            "X-GitHub-Event": "ping",
        },
    )
    assert old_res.status_code == 401, old_res.text
    assert old_res.json()["code"] == "GITHUB_WEBHOOK_SIGNATURE_INVALID"

    new_res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(new_secret, ping_body),
            "X-GitHub-Delivery": "rotate-new-secret",
            "X-GitHub-Event": "ping",
        },
    )
    assert new_res.status_code == 200, new_res.text
    assert new_res.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# 5. Public webhook: HMAC, scoping, 202 async dispatch, dedupe, redelivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_webhook_hmac_async_dedupe_deliveries_and_redelivery(
    p53_api: Any,
) -> None:
    api = p53_api
    connected = await _connect(api, enable_webhook=True)
    secret = connected["generated_webhook_secret"]
    assert secret
    await _push_main(api)
    previous = _ref_sha(api.repo_git, "refs/heads/main")
    assert previous is not None
    remote_sha = api.remote.advance_main(
        "webhook.txt", b"from webhook\n", "Remote webhook commit"
    )
    body = _webhook_body("refs/heads/main", previous, remote_sha)
    delivery_id = "p53-delivery-push-1"
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _signature(secret, body),
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
    }

    res = await api.client.post(WEBHOOK_PATH, content=body)
    assert res.status_code == 401, res.text
    assert res.json()["code"] == "GITHUB_WEBHOOK_SIGNATURE_INVALID"

    res = await api.client.post(
        WEBHOOK_PATH,
        content=body,
        headers={**headers, "X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert res.status_code == 401, res.text

    res = await api.client.post(
        WEBHOOK_PATH,
        content=body + b" ",
        headers=headers,
    )
    assert res.status_code == 401, res.text

    res = await api.client.post(
        WEBHOOK_PATH,
        content=b"not json",
        headers={"Content-Type": "text/plain", "X-Hub-Signature-256": "ignored"},
    )
    assert res.status_code == 415, res.text

    for method in ("GET", "DELETE"):
        res = await api.client.request(method, WEBHOOK_PATH)
        assert res.status_code == 401, res.text
        assert res.json()["error_code"] == "AUTHENTICATION_ERROR"

    res = await api.client.post(
        f"{WEBHOOK_PATH}/extra",
        json={"ref": "refs/heads/main"},
    )
    assert res.status_code == 401, res.text
    assert res.json()["error_code"] == "AUTHENTICATION_ERROR"

    api.gate.enabled = True
    res = await api.client.post(WEBHOOK_PATH, content=body, headers=headers)
    assert res.status_code == 202, res.text
    queued = res.json()
    assert queued["status"] == "queued"
    assert queued["deduplicated"] is False
    operation_id = queued["operation_id"]
    assert operation_id

    assert await asyncio.to_thread(api.gate.started.wait, 5.0)
    async with database.session_factory() as session:
        running = await session.get(OperationModel, operation_id)
    assert running is not None and running.status != "COMPLETED"
    delivery = await _delivery_row(delivery_id)
    assert delivery is not None and delivery.status == "queued"

    api.gate.enabled = False
    api.gate.release.set()
    operation = await _wait_for_operation(operation_id)
    assert operation.status == "COMPLETED"
    await _wait_for_delivery(delivery_id, "processed")
    assert _ref_sha(api.repo_git, "refs/heads/main") == remote_sha

    res = await api.client.post(WEBHOOK_PATH, content=body, headers=headers)
    assert res.status_code == 200, res.text
    deduped = res.json()
    assert deduped["status"] == "deduplicated"
    assert deduped["deduplicated"] is True
    assert deduped["operation_id"] == operation_id

    ping_body = b'{"zen":"ping"}\n'
    res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(secret, ping_body),
            "X-GitHub-Delivery": "p53-delivery-ping-1",
            "X-GitHub-Event": "ping",
        },
    )
    assert res.status_code == 200, res.text
    ignored = res.json()
    assert ignored["status"] == "ignored"
    assert ignored["operation_id"] is None

    res = await api.client.get(
        f"{VERSIONING}/github/webhooks/deliveries", headers=api.header
    )
    assert res.status_code == 200, res.text
    deliveries = res.json()
    assert {item["delivery_id"] for item in deliveries} >= {
        delivery_id,
        "p53-delivery-ping-1",
    }
    assert "raw_payload" not in res.text
    timestamps = [item["received_at"] for item in deliveries]
    assert timestamps == sorted(timestamps, reverse=True)
    assert secret not in res.text
    assert TOKEN not in res.text

    res = await api.client.post(
        f"{VERSIONING}/github/webhooks/deliveries/{delivery_id}/redeliver",
        json={},
        headers=api.header,
    )
    assert res.status_code == 202, res.text
    redelivered = res.json()
    assert redelivered["status"] == "queued"
    assert redelivered["redelivered"] is True
    assert redelivered["redelivery_count"] == 1
    assert redelivered["operation_id"]
    assert redelivered["operation_id"] != operation_id

    redelivery_op = await _wait_for_operation(redelivered["operation_id"])
    assert redelivery_op.status == "COMPLETED"
    redelivery_row = await _wait_for_delivery(delivery_id, "processed")
    assert redelivery_row.redelivery_count == 1


# ---------------------------------------------------------------------------
# 6. Disconnect keeps local history and disables the old webhook secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_preserves_local_history_and_purges_deliveries(p53_api: Any) -> None:
    api = p53_api
    connected = await _connect(api, enable_webhook=True)
    secret = connected["generated_webhook_secret"]
    assert secret
    await _push_main(api)
    main_sha = _ref_sha(api.repo_git, "refs/heads/main")
    assert main_sha is not None
    worktree_head = _git(["rev-parse", "HEAD"], cwd=api.main_worktree).stdout.strip()
    commit_count = _git(
        ["-C", str(api.repo_git), "rev-list", "--all", "--count"]
    ).stdout.strip()

    ping_body = b'{"zen":"disconnect"}\n'
    res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(secret, ping_body),
            "X-GitHub-Delivery": "p53-delivery-disconnect",
            "X-GitHub-Event": "ping",
        },
    )
    assert res.status_code == 200, res.text

    res = await api.client.delete(
        f"{VERSIONING}/github?purge_deliveries=true", headers=api.header
    )
    assert res.status_code == 200, res.text
    disconnected = res.json()
    assert disconnected["disconnected"] is True
    assert disconnected["local_history_preserved"] is True
    assert disconnected["purged_deliveries"] >= 1

    config_text = (api.repo_git / "config").read_text(encoding="utf-8")
    assert '[remote "origin"]' not in config_text
    assert _ref_sha(api.repo_git, "refs/heads/main") == main_sha
    assert _git(["rev-parse", "HEAD"], cwd=api.main_worktree).stdout.strip() == worktree_head
    assert (
        _git(["rev-list", "--all", "--count"], cwd=api.repo_git).stdout.strip()
        == commit_count
    )

    res = await api.client.get(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200
    status = res.json()
    assert status["connected"] is False
    assert status["webhook_path"] is None

    res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(secret, ping_body),
            "X-GitHub-Delivery": "p53-delivery-after-disconnect",
            "X-GitHub-Event": "ping",
        },
    )
    assert res.status_code == 401, res.text
    assert res.json()["code"] == "GITHUB_WEBHOOK_SIGNATURE_INVALID"


# ---------------------------------------------------------------------------
# 7. Activity log persistence for all six GitHub events, secret-free
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_log_contains_all_six_github_events_without_secrets(
    p53_api: Any,
) -> None:
    api = p53_api
    connected = await _connect(api, enable_webhook=True)
    secret = connected["generated_webhook_secret"]
    assert secret
    await _push_main(api)

    res = await api.client.post(f"{VERSIONING}/github/fetch", json={}, headers=api.header)
    assert res.status_code == 200, res.text

    ping_body = b'{"zen":"activity"}\n'
    res = await api.client.post(
        WEBHOOK_PATH,
        content=ping_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(secret, ping_body),
            "X-GitHub-Delivery": "p53-delivery-activity",
            "X-GitHub-Event": "ping",
        },
    )
    assert res.status_code == 200, res.text

    res = await api.client.post(
        f"{VERSIONING}/github/credentials/rotate",
        json={"enable_webhook": False},
        headers=api.header,
    )
    assert res.status_code == 200, res.text

    res = await api.client.delete(f"{VERSIONING}/github", headers=api.header)
    assert res.status_code == 200, res.text

    res = await api.client.get(f"{ACTIVITY}?limit=200", headers=api.header)
    assert res.status_code == 200, res.text
    payload = res.json()
    event_types = {item["event_type"] for item in payload["items"]}
    assert {
        "versioning.github_connected",
        "versioning.github_pushed",
        "versioning.github_synced",
        "versioning.github_webhook_received",
        "versioning.github_credentials_rotated",
        "versioning.github_disconnected",
    } <= event_types

    res = await api.client.get(f"{ACTIVITY}?branch=main&limit=200", headers=api.header)
    assert res.status_code == 200, res.text
    branch_types = {item["event_type"] for item in res.json()["items"]}
    assert "versioning.github_pushed" in branch_types

    res = await api.client.get(f"{ACTIVITY}?limit=200", headers=api.header)
    assert TOKEN not in res.text
    assert secret not in res.text
    assert REPLACEMENT_TOKEN not in res.text


# ---------------------------------------------------------------------------
# 8. RBAC: read-only key mutates nothing, unauthenticated gets 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_read_only_and_unauthenticated_routes(p53_api: Any) -> None:
    api = p53_api
    viewer = await _seed_api_key_header(
        api.client, api.user["user_id"], ["server:version:read"]
    )

    for path in ("/github", "/github/webhooks/deliveries"):
        res = await api.client.get(f"{VERSIONING}{path}", headers=viewer)
        assert res.status_code != 403, (path, res.text)

    mutations = [
        ("POST", "/github/deploy-key/generate", {}),
        ("POST", "/github/connect", _connect_body()),
        ("POST", "/github/credentials/rotate", {"enable_webhook": False}),
        ("DELETE", "/github", None),
        ("POST", "/github/fetch", {}),
        ("POST", "/github/push", {"branch_name": "main"}),
        (
            "POST",
            "/github/webhooks/deliveries/del-1/redeliver",
            {},
        ),
    ]
    for method, path, body in mutations:
        if body is None:
            res = await api.client.request(
                method, f"{VERSIONING}{path}", headers=viewer
            )
        else:
            res = await api.client.request(
                method, f"{VERSIONING}{path}", json=body, headers=viewer
            )
        assert res.status_code == 403, (method, path, res.text)

    unauthenticated = [
        ("GET", "/github", None),
        ("POST", "/github/deploy-key/generate", {}),
        ("POST", "/github/connect", _connect_body()),
        ("POST", "/github/credentials/rotate", {"enable_webhook": False}),
        ("DELETE", "/github", None),
        ("POST", "/github/fetch", {}),
        ("POST", "/github/push", {"branch_name": "main"}),
        ("GET", "/github/webhooks/deliveries", None),
        (
            "POST",
            "/github/webhooks/deliveries/del-1/redeliver",
            {},
        ),
    ]
    for method, path, body in unauthenticated:
        if body is None:
            res = await api.client.request(method, f"{VERSIONING}{path}")
        else:
            res = await api.client.request(
                method, f"{VERSIONING}{path}", json=body
            )
        assert res.status_code == 401, (method, path, res.text)
        assert res.json()["error_code"] == "AUTHENTICATION_ERROR"
