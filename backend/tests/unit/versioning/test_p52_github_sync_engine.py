"""P5-2 GitHub sync engine integration tests (Brief §6.2).

Every scenario uses a real bare Git repository, a real local Smart HTTP server
on ``127.0.0.1:0`` backed by ``/usr/lib/git-core/git-http-backend``, real
``GIT_ASKPASS`` execution, and the production ``GitRunner`` hardening contract.
The only test-only addition is a loopback ``url.*.insteadOf`` rewrite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

import app.modules.operations.infrastructure.models  # noqa: F401
from app.core.config import AppSettings
from app.core.event_bus import EventBus, EventHandler
from app.core.exceptions import (
    DirtyWorktreeError,
    GitHubAuthFailedError,
    GitHubPushRejectedError,
    NonFastForwardMainError,
    WebhookSignatureError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.operations.application.services.operation_service import (
    OperationService,
)
from app.modules.operations.domain.enums import OperationStatus
from app.modules.operations.infrastructure.models import OperationModel
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.github_sync_service import (
    GitHubSyncService,
)
from app.modules.versioning.domain.events import (
    GitHubConnectedEvent,
    GitHubPushedEvent,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    GitRepositoryService,
)
from app.modules.versioning.infrastructure.git_runner import (
    GIT_HARDENING_OVERRIDES,
    GitRunner,
)
from app.modules.versioning.infrastructure.github_sync_repository import (
    SQLGitHubSyncRepository,
)
from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerBranchModel,
    ServerCommitModel,
)

pytestmark = pytest.mark.no_isolated_db

SERVER_ID = "srv-gh"
REMOTE_URL = "https://github.com/octo/mc-server.git"
BRANCH_MAIN = "main"
KEK_HEX = "a5" * 32
WEBHOOK_SECRET = "integration-webhook-secret-" + "c" * 32
HTTP_BACKEND = Path("/usr/lib/git-core/git-http-backend")
_GIT_IDENTITY = (
    "-c",
    "user.name=ONX Test",
    "-c",
    "user.email=onx-test@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
)


def _git(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        check=check,
        capture_output=True,
        text=True,
    )


def _ref_sha(repo: Path, ref: str) -> str | None:
    result = _git(
        ["-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
        check=False,
    )
    return result.stdout.strip() or None


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _webhook_body(ref: str, before: str, after: str) -> bytes:
    return json.dumps(
        {
            "ref": ref,
            "before": before,
            "after": after,
            "repository": {"full_name": "octo/mc-server"},
        }
    ).encode("utf-8")


class _LoopbackGitRunner(GitRunner):
    """Production runner plus exactly one loopback URL rewrite."""

    def __init__(self, *args: object, rewrite_port: int, **kwargs: object) -> None:
        self._rewrite_port = rewrite_port
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _override_args(self) -> list[str]:
        args = list(super()._override_args())
        args.extend(
            (
                "-c",
                "url.http://127.0.0.1:"
                f"{self._rewrite_port}/.insteadOf=https://github.com/",
            )
        )
        return args


@dataclass
class _SmartHTTPState:
    project_root: Path
    valid_tokens: set[str] = field(default_factory=set)
    read_only_tokens: set[str] = field(default_factory=set)
    revoked_tokens: set[str] = field(default_factory=set)
    request_log: list[tuple[str, str, bool]] = field(default_factory=list)
    missing_auth: int = 0
    receive_pack_denied: int = 0


def _make_handler(
    state: _SmartHTTPState,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "GitHubTest/1.0"

        def log_message(self, *args: object) -> None:
            del args

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._handle()

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._handle()

        def _token(self) -> str | None:
            header = self.headers.get("Authorization") or ""
            if not header.startswith("Basic "):
                return None
            try:
                decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
            _username, separator, password = decoded.partition(":")
            if not separator:
                return None
            return password or None

        def _empty(self, status: int, *, authenticate: bool = False) -> None:
            self.send_response(status)
            if authenticate:
                self.send_header(
                    "WWW-Authenticate", 'Basic realm="GitHubTest"'
                )
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            token = self._token()
            is_receive_pack = "/git-receive-pack" in self.path
            state.request_log.append((self.command, self.path, token is not None))
            if token is None:
                state.missing_auth += 1
                self._empty(401, authenticate=True)
                return
            if token in state.revoked_tokens or token not in state.valid_tokens:
                self._empty(401, authenticate=True)
                return
            if is_receive_pack and token in state.read_only_tokens:
                state.receive_pack_denied += 1
                self._empty(403)
                return

            split = urlsplit(self.path)
            env = os.environ.copy()
            env.update(
                {
                    "GIT_PROJECT_ROOT": str(state.project_root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                    "PATH_INFO": unquote(split.path),
                    "QUERY_STRING": split.query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(len(body)),
                    "REMOTE_ADDR": self.client_address[0],
                    "REMOTE_USER": "x-access-token",
                    "AUTH_TYPE": "Basic",
                    "SERVER_NAME": "127.0.0.1",
                    "SERVER_PORT": str(self.server.server_port),
                    "SERVER_PROTOCOL": "HTTP/1.1",
                    "SERVER_SOFTWARE": "ONX-GitHub-Test",
                    "GATEWAY_INTERFACE": "CGI/1.1",
                }
            )
            completed = subprocess.run(
                [str(HTTP_BACKEND)],
                input=body,
                capture_output=True,
                env=env,
                check=False,
            )
            header_blob, separator, payload = completed.stdout.partition(
                b"\r\n\r\n"
            )
            status = 200
            headers: list[tuple[str, str]] = []
            if separator:
                lines = header_blob.split(b"\r\n")
                if lines and lines[0].lower().startswith(b"status:"):
                    status = int(lines[0].split()[1])
                    lines = lines[1:]
                for line in lines:
                    name, colon, value = line.partition(b":")
                    if colon:
                        headers.append(
                            (
                                name.decode("latin-1").strip(),
                                value.decode("latin-1").strip(),
                            )
                        )
            else:
                payload = completed.stdout

            self.send_response(status)
            for name, value in headers:
                if name.lower() in ("content-length", "connection", "status"):
                    continue
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if payload:
                self.wfile.write(payload)

    return Handler


class _SmartHTTPServer:
    def __init__(self, project_root: Path) -> None:
        assert HTTP_BACKEND.is_file(), f"missing {HTTP_BACKEND}"
        self.state = _SmartHTTPState(project_root=project_root)
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0), _make_handler(self.state)
        )
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    def __enter__(self) -> _SmartHTTPServer:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


class _RemoteRepo:
    """Helper that advances the bare remote through a real clone."""

    def __init__(self, bare: Path, workdir: Path) -> None:
        self.bare = bare
        self.workdir = workdir

    def _ensure_clone(self) -> None:
        if not (self.workdir / ".git").exists():
            _git(["clone", str(self.bare), str(self.workdir)])
        _git(["fetch", "origin", "--prune"], cwd=self.workdir)

    def _commit(self, relpath: str, content: bytes, message: str) -> str:
        target = self.workdir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        _git(["add", "--", relpath], cwd=self.workdir)
        _git([*_GIT_IDENTITY, "commit", "-m", message], cwd=self.workdir)
        return _git(["rev-parse", "HEAD"], cwd=self.workdir).stdout.strip()

    def advance_main(self, relpath: str, content: bytes, message: str) -> str:
        self._ensure_clone()
        _git(["checkout", "-B", "main", "origin/main"], cwd=self.workdir)
        sha = self._commit(relpath, content, message)
        _git(["push", "origin", "main"], cwd=self.workdir)
        return sha

    def advance_branch(
        self, branch: str, relpath: str, content: bytes, message: str
    ) -> str:
        self._ensure_clone()
        _git(
            ["checkout", "-B", branch, f"origin/{branch}"],
            cwd=self.workdir,
        )
        sha = self._commit(relpath, content, message)
        _git(["push", "origin", branch], cwd=self.workdir)
        return sha

    def create_branch(
        self,
        branch: str,
        start: str,
        relpath: str,
        content: bytes,
        message: str,
    ) -> str:
        self._ensure_clone()
        _git(
            ["checkout", "-B", branch, f"origin/{start}"],
            cwd=self.workdir,
        )
        sha = self._commit(relpath, content, message)
        _git(["push", "origin", branch], cwd=self.workdir)
        return sha


class _Recorder(EventHandler):
    def __init__(self) -> None:
        self.events: list[object] = []

    async def handle(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _EngineHarness:
    layout: HostStateLayout
    server_root: Path
    repo_git: Path
    repo_config: Path
    main_worktree: Path
    remote_bare: Path
    remote: _RemoteRepo
    factory: async_sessionmaker[AsyncSession]
    sync_factory: sessionmaker
    service: GitHubSyncService
    event_bus: EventBus
    recorder: _Recorder
    smart: _SmartHTTPServer
    token: str = "ghp_integration_valid_token_0001"
    runner_overrides: list[list[str]] = field(default_factory=list)
    async_engine: object | None = None
    sync_engine: object | None = None


def _commit_worktree(
    worktree: Path, relpath: str, content: bytes, message: str
) -> str:
    target = worktree / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(["add", "--", relpath], cwd=worktree)
    _git([*_GIT_IDENTITY, "commit", "-m", message], cwd=worktree)
    return _git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()


async def _connect(
    h: _EngineHarness, *, webhook_secret: str | None = None
) -> None:
    h.smart.state.valid_tokens.add(h.token)
    status = await h.service.connect(
        SERVER_ID,
        remote_url=REMOTE_URL,
        auth_method="pat",
        credential_secret=h.token,
        webhook_secret=webhook_secret,
        server_root=h.server_root,
    )
    assert status.connected is True
    assert status.sync_status == "idle"


def _local_main_sha(h: _EngineHarness) -> str:
    sha = _ref_sha(h.repo_git, "refs/heads/main")
    assert sha is not None
    return sha


@pytest_asyncio.fixture
async def engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _EngineHarness:
    monkeypatch.setenv("ONX_MASTER_KEK", KEK_HEX)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    server_root = tmp_path / "server"
    server_root.mkdir()

    remote_root = tmp_path / "remote-root"
    remote_bare = remote_root / "octo" / "mc-server.git"
    remote_bare.parent.mkdir(parents=True)
    _git(
        ["init", "--bare", "--initial-branch=main", str(remote_bare)]
    )
    _git(["-C", str(remote_bare), "config", "http.receivepack", "true"])

    smart = _SmartHTTPServer(remote_root)
    smart.__enter__()

    db_path = tmp_path / "p52_engine.db"
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": 30.0},
    )
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    GitRepositoryService(layout).initialize(SERVER_ID, server_root, lockfile)
    repo_git = layout.repo_dir(SERVER_ID) / "repo.git"
    repo_config = layout.repo_dir(SERVER_ID) / "gitconfig"
    main_worktree = server_root / ".onx" / "worktrees" / "main"
    initial_main = _local_main_sha_from(repo_git)

    async with factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="gh",
                server_type="vanilla",
                minecraft_version="1.20.4",
                mode="advanced",
                provider="docker",
                root_path=str(server_root),
            )
        )
        session.add(
            ServerBranchModel(
                id="branch-main",
                server_id=SERVER_ID,
                name="main",
                head_commit_id=initial_main,
                status="active",
            )
        )
        await session.commit()

    event_bus = EventBus()
    recorder = _Recorder()
    for event_name in (
        "GitHubConnectedEvent",
        "GitHubDisconnectedEvent",
        "GitHubCredentialsRotatedEvent",
        "GitHubSyncedEvent",
        "GitHubPushedEvent",
        "push",
        "ping",
    ):
        event_bus.subscribe(event_name, recorder)
    runner_overrides: list[list[str]] = []

    def runner_factory(path: Path, config_path: Path) -> GitRunner:
        runner = _LoopbackGitRunner(
            repo_path=path,
            config_path=config_path,
            git_executable="git",
            timeout=60.0,
            rewrite_port=smart.port,
        )
        runner_overrides.append(runner._override_args())
        return runner

    service = GitHubSyncService(
        layout,
        session_factory=factory,
        sync_session_factory=sync_factory,
        event_bus=event_bus,
        operation_service=OperationService(event_bus=event_bus),
        git_runner_factory=runner_factory,
        git_timeout=60.0,
    )
    harness = _EngineHarness(
        layout=layout,
        server_root=server_root,
        repo_git=repo_git,
        repo_config=repo_config,
        main_worktree=main_worktree,
        remote_bare=remote_bare,
        remote=_RemoteRepo(remote_bare, tmp_path / "remote-work"),
        factory=factory,
        sync_factory=sync_factory,
        service=service,
        event_bus=event_bus,
        recorder=recorder,
        smart=smart,
        runner_overrides=runner_overrides,
        async_engine=async_engine,
        sync_engine=sync_engine,
    )
    try:
        yield harness
    finally:
        await async_engine.dispose()
        sync_engine.dispose()
        smart.__exit__()


def _local_main_sha_from(repo_git: Path) -> str:
    sha = _ref_sha(repo_git, "refs/heads/main")
    assert sha is not None
    return sha


def _assert_repo_config_has_no_secrets(
    h: _EngineHarness, *secrets: str
) -> None:
    contents = [
        (h.repo_git / "config").read_text(encoding="utf-8"),
        h.repo_config.read_text(encoding="utf-8"),
    ]
    for content in contents:
        assert "://" not in content or "@" not in content.split("://", 1)[1].split("/", 1)[0]
        for secret in secrets:
            assert secret not in content


# ----------------------------------------------------------------------
# 1. Connect + empty remote + push main + credential-free config
# ----------------------------------------------------------------------


async def test_connect_empty_remote_push_main_and_credential_free_config(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    assert engine.smart.state.missing_auth >= 1
    assert any(authorized for _, _, authorized in engine.smart.state.request_log)

    config_text = (engine.repo_git / "config").read_text(encoding="utf-8")
    assert f"url = {REMOTE_URL}" in config_text
    assert "filemode = true" in config_text
    _assert_repo_config_has_no_secrets(engine, engine.token)

    assert any(
        isinstance(event, GitHubConnectedEvent)
        for event in engine.recorder.events
    )
    assert engine.runner_overrides
    for overrides in engine.runner_overrides:
        for key, value in GIT_HARDENING_OVERRIDES:
            assert f"{key}={value}" in overrides
        assert any(
            arg.startswith(f"url.http://127.0.0.1:{engine.smart.port}/")
            for arg in overrides
        )

    synced = await engine.service.fetch_first_sync(
        SERVER_ID, server_root=engine.server_root
    )
    assert synced.sync_status == "ahead"
    main_state = next(state for state in synced.branches if state.branch == "main")
    assert main_state.status == "local_only"
    assert main_state.remote_sha is None

    local_sha = _local_main_sha(engine)
    pushed = await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    assert pushed.sync_status == "synced"
    assert pushed.commit_sha == local_sha
    assert _ref_sha(engine.remote_bare, "refs/heads/main") == local_sha
    assert any(
        isinstance(event, GitHubPushedEvent) for event in engine.recorder.events
    )
    _assert_repo_config_has_no_secrets(engine, engine.token)


# ----------------------------------------------------------------------
# 2. Fetch-first fast-forward + worktree sync + DB ledger projection
# ----------------------------------------------------------------------


async def test_fetch_first_fast_forwards_main_worktree_and_ledger(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    previous = _local_main_sha(engine)
    remote_sha = engine.remote.advance_main(
        "remote.txt", b"from github\n", "Remote GitHub commit"
    )
    assert remote_sha != previous

    result = await engine.service.fetch_first_sync(
        SERVER_ID, server_root=engine.server_root
    )
    assert result.main_fast_forwarded is True
    assert result.previous_main_sha == previous
    assert result.main_sha == remote_sha
    assert result.sync_status == "synced"
    assert _local_main_sha(engine) == remote_sha
    assert (engine.main_worktree / "remote.txt").read_text() == "from github\n"
    assert (
        _git(["rev-parse", "HEAD"], cwd=engine.main_worktree).stdout.strip()
        == remote_sha
    )

    async with engine.factory() as session:
        branch = await session.get(ServerBranchModel, "branch-main")
        commit = await session.get(ServerCommitModel, remote_sha)
        connection = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
    assert branch is not None
    assert branch.head_commit_id == remote_sha
    assert commit is not None
    assert commit.message == "Remote GitHub commit"
    assert connection is not None
    assert connection.sync_status == "synced"
    assert connection.last_error_code is None


# ----------------------------------------------------------------------
# 3. Dirty main worktree protection on fast-forward
# ----------------------------------------------------------------------


async def test_dirty_main_worktree_blocks_fast_forward(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    previous = _local_main_sha(engine)
    engine.remote.advance_main("remote.txt", b"remote\n", "Advance remote main")

    tracked = engine.main_worktree / "onx-jars.lock.json"
    dirty_content = tracked.read_text(encoding="utf-8") + "\n// local edit\n"
    tracked.write_text(dirty_content, encoding="utf-8")

    with pytest.raises(DirtyWorktreeError):
        await engine.service.fetch_first_sync(
            SERVER_ID, server_root=engine.server_root
        )

    assert tracked.read_text(encoding="utf-8") == dirty_content
    assert _local_main_sha(engine) == previous
    async with engine.factory() as session:
        connection = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
    assert connection is not None
    assert connection.sync_status == "behind"


# ----------------------------------------------------------------------
# 4. Non-fast-forward main divergence rejection (D-K)
# ----------------------------------------------------------------------


async def test_non_fast_forward_main_is_rejected_without_mutation(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    local_sha = _commit_worktree(
        engine.main_worktree, "local.txt", b"local\n", "Local main commit"
    )
    remote_sha = engine.remote.advance_main(
        "remote.txt", b"remote\n", "Remote main commit"
    )
    assert local_sha != remote_sha

    with pytest.raises(NonFastForwardMainError) as exc_info:
        await engine.service.fetch_first_sync(
            SERVER_ID, server_root=engine.server_root
        )
    assert exc_info.value.http_status == 409
    assert _local_main_sha(engine) == local_sha
    assert (
        _git(["rev-parse", "HEAD"], cwd=engine.main_worktree).stdout.strip()
        == local_sha
    )
    assert _ref_sha(engine.remote_bare, "refs/heads/main") == remote_sha

    async with engine.factory() as session:
        connection = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
    assert connection is not None
    assert connection.sync_status == "conflict"
    assert connection.last_error_code == "GITHUB_NON_FAST_FORWARD_MAIN"
    assert connection.branch_sync_json is not None
    main_state = next(
        item
        for item in connection.branch_sync_json
        if item["branch"] == "main"
    )
    assert main_state["status"] == "diverged"
    assert main_state["ahead_count"] >= 1
    assert main_state["behind_count"] >= 1

    with pytest.raises(NonFastForwardMainError):
        await engine.service.push_branch(
            SERVER_ID, "main", server_root=engine.server_root
        )
    assert _ref_sha(engine.remote_bare, "refs/heads/main") == remote_sha


# ----------------------------------------------------------------------
# 5. 1:1 multi-branch telemetry
# ----------------------------------------------------------------------


async def test_multi_branch_sync_states_and_feature_push(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    branches = GitBranchService(engine.layout)

    branches.create_branch(SERVER_ID, engine.server_root, "synced")
    await engine.service.push_branch(
        SERVER_ID, "synced", server_root=engine.server_root
    )

    branches.create_branch(SERVER_ID, engine.server_root, "ahead")
    await engine.service.push_branch(
        SERVER_ID, "ahead", server_root=engine.server_root
    )
    _commit_worktree(
        engine.server_root / ".onx" / "worktrees" / "ahead",
        "ahead.txt",
        b"ahead\n",
        "Local ahead commit",
    )

    branches.create_branch(SERVER_ID, engine.server_root, "behind")
    await engine.service.push_branch(
        SERVER_ID, "behind", server_root=engine.server_root
    )
    engine.remote.advance_branch(
        "behind", "behind.txt", b"behind\n", "Remote behind commit"
    )

    branches.create_branch(SERVER_ID, engine.server_root, "diverged")
    await engine.service.push_branch(
        SERVER_ID, "diverged", server_root=engine.server_root
    )
    _commit_worktree(
        engine.server_root / ".onx" / "worktrees" / "diverged",
        "local.txt",
        b"local\n",
        "Local divergent commit",
    )
    engine.remote.advance_branch(
        "diverged", "remote.txt", b"remote\n", "Remote divergent commit"
    )

    branches.create_branch(SERVER_ID, engine.server_root, "local-only")
    engine.remote.create_branch(
        "remote-only", "main", "remote-only.txt", b"remote\n", "Remote only"
    )
    branches.create_branch(SERVER_ID, engine.server_root, "feat/spawn")

    result = await engine.service.fetch_first_sync(
        SERVER_ID, server_root=engine.server_root
    )
    states = {state.branch: state for state in result.branches}

    assert states["synced"].status == "synced"
    assert states["synced"].local_sha == states["synced"].remote_sha
    assert states["ahead"].status == "ahead"
    assert states["ahead"].ahead_count == 1
    assert states["ahead"].behind_count == 0
    assert states["behind"].status == "behind"
    assert states["behind"].ahead_count == 0
    assert states["behind"].behind_count == 1
    assert states["diverged"].status == "diverged"
    assert states["diverged"].ahead_count >= 1
    assert states["diverged"].behind_count >= 1
    assert states["local-only"].status == "local_only"
    assert states["local-only"].local_sha is not None
    assert states["local-only"].remote_sha is None
    assert states["remote-only"].status == "remote_only"
    assert states["remote-only"].local_sha is None
    assert states["remote-only"].remote_sha is not None
    assert states["feat/spawn"].status == "local_only"

    feature_sha = _ref_sha(engine.repo_git, "refs/heads/feat/spawn")
    assert feature_sha is not None
    pushed = await engine.service.push_branch(
        SERVER_ID, "feat/spawn", server_root=engine.server_root
    )
    feature_state = next(
        state for state in pushed.branches if state.branch == "feat/spawn"
    )
    assert feature_state.status == "synced"
    assert _ref_sha(engine.remote_bare, "refs/heads/feat/spawn") == feature_sha


# ----------------------------------------------------------------------
# 6. Plain-.jar blob rejection before push (D-A)
# ----------------------------------------------------------------------


async def test_plain_jar_blobs_are_rejected_before_remote_mutation(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    branches = GitBranchService(engine.layout)

    branches.create_branch(SERVER_ID, engine.server_root, "bad-tip")
    worktree = engine.server_root / ".onx" / "worktrees" / "bad-tip"
    _commit_worktree(
        worktree, "plugins/bad.jar", b"PK\x03\x04tip", "Add jar at tip"
    )
    with pytest.raises(GitHubPushRejectedError) as tip_exc:
        await engine.service.push_branch(
            SERVER_ID, "bad-tip", server_root=engine.server_root
        )
    assert tip_exc.value.http_status == 409
    assert tip_exc.value.details["reason"] == "plain_jar_blob_forbidden"
    assert _ref_sha(engine.remote_bare, "refs/heads/bad-tip") is None

    branches.create_branch(SERVER_ID, engine.server_root, "bad-history")
    worktree = engine.server_root / ".onx" / "worktrees" / "bad-history"
    _commit_worktree(
        worktree, "plugins/old.jar", b"PK\x03\x04old", "Add historical jar"
    )
    _git(["rm", "--", "plugins/old.jar"], cwd=worktree)
    _git(
        [*_GIT_IDENTITY, "commit", "-m", "Delete historical jar"],
        cwd=worktree,
    )
    with pytest.raises(GitHubPushRejectedError) as history_exc:
        await engine.service.push_branch(
            SERVER_ID, "bad-history", server_root=engine.server_root
        )
    assert history_exc.value.details["reason"] == "plain_jar_blob_forbidden"
    assert _ref_sha(engine.remote_bare, "refs/heads/bad-history") is None

    branches.create_branch(SERVER_ID, engine.server_root, "jar-lock-clean")
    clean_sha = _ref_sha(engine.repo_git, "refs/heads/jar-lock-clean")
    clean_result = await engine.service.push_branch(
        SERVER_ID, "jar-lock-clean", server_root=engine.server_root
    )
    assert clean_result.commit_sha == clean_sha
    assert (
        _ref_sha(engine.remote_bare, "refs/heads/jar-lock-clean") == clean_sha
    )


# ----------------------------------------------------------------------
# 7. Revoked / under-scoped PAT classification + rotation recovery
# ----------------------------------------------------------------------


async def test_revoked_and_read_only_tokens_require_reauthentication_then_rotate(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )

    engine.smart.state.revoked_tokens.add(engine.token)
    with pytest.raises(GitHubAuthFailedError) as revoked:
        await engine.service.fetch_first_sync(
            SERVER_ID, server_root=engine.server_root
        )
    assert revoked.value.needs_reauth is True
    assert revoked.value.http_status == 409
    status = await engine.service.get_status(SERVER_ID)
    assert status.needs_reauth is True
    assert status.sync_status == "auth_failed"

    _commit_worktree(
        engine.main_worktree, "pending.txt", b"pending\n", "Local pending commit"
    )

    read_only = "ghp_integration_read_only_token_0002"
    engine.smart.state.valid_tokens.add(read_only)
    engine.smart.state.read_only_tokens.add(read_only)
    rotated = await engine.service.rotate_credentials(
        SERVER_ID,
        credential_secret=read_only,
        server_root=engine.server_root,
    )
    assert rotated.auth_method == "pat"
    assert rotated.sync_status == "idle"
    _assert_repo_config_has_no_secrets(engine, engine.token, read_only)

    with pytest.raises(GitHubAuthFailedError) as read_only_exc:
        await engine.service.push_branch(
            SERVER_ID, "main", server_root=engine.server_root
        )
    assert read_only_exc.value.needs_reauth is True
    assert engine.smart.state.receive_pack_denied >= 1

    async with engine.factory() as session:
        before = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
    assert before is not None
    ciphertext_before = bytes(before.credential_ciphertext)

    bad_token = "ghp_integration_revoked_bad_token_0003"
    engine.smart.state.revoked_tokens.add(bad_token)
    with pytest.raises(GitHubAuthFailedError):
        await engine.service.rotate_credentials(
            SERVER_ID,
            credential_secret=bad_token,
            server_root=engine.server_root,
        )
    async with engine.factory() as session:
        after_bad = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
    assert after_bad is not None
    assert bytes(after_bad.credential_ciphertext) == ciphertext_before

    replacement = "ghp_integration_replacement_token_0004"
    engine.smart.state.valid_tokens.add(replacement)
    recovered = await engine.service.rotate_credentials(
        SERVER_ID,
        credential_secret=replacement,
        server_root=engine.server_root,
    )
    assert recovered.sync_status == "idle"
    assert recovered.needs_reauth is False
    _assert_repo_config_has_no_secrets(engine, engine.token, replacement)

    synced = await engine.service.fetch_first_sync(
        SERVER_ID, server_root=engine.server_root
    )
    assert synced.sync_status == "ahead"
    status = await engine.service.get_status(SERVER_ID)
    assert status.needs_reauth is False


# ----------------------------------------------------------------------
# 8. Webhook enqueue -> run_queued_sync_operation
# ----------------------------------------------------------------------


async def test_webhook_enqueue_then_worker_processes_and_fails_operations(
    engine: _EngineHarness,
) -> None:
    await _connect(engine, webhook_secret=WEBHOOK_SECRET)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    previous = _local_main_sha(engine)
    remote_sha = engine.remote.advance_main(
        "remote.txt", b"remote\n", "Remote webhook commit"
    )

    body = _webhook_body("refs/heads/main", previous, remote_sha)
    queued = await engine.service.ingest_webhook(
        SERVER_ID,
        raw_body=body,
        signature_header=_signature(WEBHOOK_SECRET, body),
        delivery_id="delivery-success",
        event_type="push",
    )
    assert queued.status == "queued"
    assert queued.operation_id is not None
    assert _local_main_sha(engine) == previous

    result = await engine.service.run_queued_sync_operation(
        SERVER_ID,
        queued.operation_id,
        delivery_id="delivery-success",
        server_root=engine.server_root,
    )
    assert result.main_fast_forwarded is True
    assert _local_main_sha(engine) == remote_sha
    async with engine.factory() as session:
        operation = await session.get(OperationModel, queued.operation_id)
        delivery = (
            await session.execute(
                select(GitHubWebhookDeliveryModel).where(
                    GitHubWebhookDeliveryModel.delivery_id == "delivery-success"
                )
            )
        ).scalar_one()
    assert operation is not None
    assert operation.status == OperationStatus.COMPLETED.value
    assert delivery.status == "processed"
    assert delivery.processed_at is not None

    local_sha = _commit_worktree(
        engine.main_worktree, "local.txt", b"local\n", "Local divergent commit"
    )
    remote_diverged = engine.remote.advance_main(
        "remote-2.txt", b"remote\n", "Remote divergent commit"
    )
    failed_body = _webhook_body("refs/heads/main", remote_sha, remote_diverged)
    failed_queued = await engine.service.ingest_webhook(
        SERVER_ID,
        raw_body=failed_body,
        signature_header=_signature(WEBHOOK_SECRET, failed_body),
        delivery_id="delivery-conflict",
        event_type="push",
    )
    assert failed_queued.operation_id is not None
    with pytest.raises(NonFastForwardMainError):
        await engine.service.run_queued_sync_operation(
            SERVER_ID,
            failed_queued.operation_id,
            delivery_id="delivery-conflict",
            server_root=engine.server_root,
        )
    async with engine.factory() as session:
        failed_operation = await session.get(
            OperationModel, failed_queued.operation_id
        )
        failed_delivery = (
            await session.execute(
                select(GitHubWebhookDeliveryModel).where(
                    GitHubWebhookDeliveryModel.delivery_id == "delivery-conflict"
                )
            )
        ).scalar_one()
    assert failed_operation is not None
    assert failed_operation.status == OperationStatus.FAILED.value
    assert failed_operation.failure_code == "GITHUB_NON_FAST_FORWARD_MAIN"
    assert failed_delivery.status == "failed"
    assert failed_delivery.processed_at is not None
    assert _local_main_sha(engine) == local_sha


# ----------------------------------------------------------------------
# 9. Disconnect preserves local history and disables webhooks
# ----------------------------------------------------------------------


async def test_disconnect_preserves_history_and_disables_webhooks(
    engine: _EngineHarness,
) -> None:
    await _connect(engine)
    await engine.service.push_branch(
        SERVER_ID, "main", server_root=engine.server_root
    )
    GitBranchService(engine.layout).create_branch(
        SERVER_ID, engine.server_root, "feat/keep"
    )
    await engine.service.push_branch(
        SERVER_ID, "feat/keep", server_root=engine.server_root
    )
    main_sha = _local_main_sha(engine)
    feature_sha = _ref_sha(engine.repo_git, "refs/heads/feat/keep")
    commit_count = _git(
        ["-C", str(engine.repo_git), "rev-list", "--all", "--count"]
    ).stdout.strip()

    result = await engine.service.disconnect(
        SERVER_ID,
        purge_deliveries=True,
        server_root=engine.server_root,
    )
    assert result.disconnected is True
    assert result.local_history_preserved is True

    config_text = (engine.repo_git / "config").read_text(encoding="utf-8")
    assert '[remote "origin"]' not in config_text
    assert _local_main_sha(engine) == main_sha
    assert _ref_sha(engine.repo_git, "refs/heads/feat/keep") == feature_sha
    assert (
        _git(
            ["-C", str(engine.repo_git), "rev-list", "--all", "--count"]
        ).stdout.strip()
        == commit_count
    )
    assert (
        _git(["rev-parse", "HEAD"], cwd=engine.main_worktree).stdout.strip()
        == main_sha
    )

    status = await engine.service.get_status(SERVER_ID)
    assert status.connected is False
    async with engine.factory() as session:
        connection = await SQLGitHubSyncRepository(session).get_connection(
            SERVER_ID
        )
        deliveries = (
            await session.execute(
                select(func.count()).select_from(GitHubWebhookDeliveryModel)
            )
        ).scalar_one()
    assert connection is None
    assert deliveries == 0

    body = _webhook_body("refs/heads/main", main_sha, main_sha)
    with pytest.raises(WebhookSignatureError):
        await engine.service.ingest_webhook(
            SERVER_ID,
            raw_body=body,
            signature_header=_signature(engine.token, body),
            delivery_id="delivery-after-disconnect",
            event_type="push",
        )
