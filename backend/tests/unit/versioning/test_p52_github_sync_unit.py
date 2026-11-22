"""P5-2 GitHub sync unit tests (Brief §6.1).

The suite uses a file-backed SQLite database with async and sync factories so
``RepoWriteLock`` can share the same durable store as the service. Every secret
assertion verifies that plaintext never appears in DTOs, events, errors, or
status snapshots.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
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
    GitCommandError,
    GitHubAuthFailedError,
    GitHubPushRejectedError,
    GitRemoteUrlError,
    GitTimeoutError,
    InvalidValueError,
    NonFastForwardMainError,
    ServerModeVersioningDisabledError,
    ValidationError,
    WebhookSignatureError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.operations.application.services.operation_service import (
    OperationService,
)
from app.modules.operations.domain.enums import OperationStatus, OperationType
from app.modules.operations.infrastructure.models import OperationModel
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.github_sync_service import (
    GeneratedDeployKeyResult,
    GitHubBranchSyncState,
    GitHubConnectionStatus,
    GitHubSyncService,
    classify_git_remote_error,
)
from app.modules.versioning.domain.events import (
    GitHubConnectedEvent,
    GitHubCredentialsRotatedEvent,
    GitHubDisconnectedEvent,
    GitHubPushedEvent,
    GitHubSyncedEvent,
    GitHubWebhookReceivedEvent,
)
from app.modules.versioning.infrastructure.github_sync_repository import (
    SQLGitHubSyncRepository,
)
from app.modules.versioning.infrastructure.github_vault import (
    apply_credential_to_connection,
    apply_webhook_secret_to_connection,
)
from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerGitHubConnectionModel,
)

pytestmark = pytest.mark.no_isolated_db

_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P5 GitHub sync / secret vault requires a POSIX host; Windows = Simple-only",
)

KEK_HEX = "a5" * 32
PAT = "ghp_unitsecret1234567890abcdef"
WEBHOOK_SECRET = "whsec_" + "b" * 40
ADVANCED_SERVER = "srv-advanced"
SIMPLE_SERVER = "srv-simple"
EVENT_TYPES = (
    GitHubConnectedEvent,
    GitHubDisconnectedEvent,
    GitHubCredentialsRotatedEvent,
    GitHubSyncedEvent,
    GitHubPushedEvent,
    GitHubWebhookReceivedEvent,
)


class _Recorder(EventHandler):
    def __init__(self) -> None:
        self.events: list[object] = []

    async def handle(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _Harness:
    layout: HostStateLayout
    server_root: Path
    factory: async_sessionmaker[AsyncSession]
    sync_factory: sessionmaker
    event_bus: EventBus
    recorder: _Recorder
    service: GitHubSyncService
    dispatcher_calls: list[tuple[str, str, str]] = field(default_factory=list)
    async_engine: object | None = None
    sync_engine: object | None = None


@pytest_asyncio.fixture
async def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    monkeypatch.setenv("ONX_MASTER_KEK", KEK_HEX)
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    server_root = tmp_path / "server"
    server_root.mkdir()

    db_path = tmp_path / "p52_unit.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    sync_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    async with factory() as session:
        session.add(
            ServerModel(
                id=ADVANCED_SERVER,
                name="advanced",
                server_type="vanilla",
                minecraft_version="1.20.4",
                mode="advanced",
                provider="docker",
                root_path=str(server_root),
            )
        )
        session.add(
            ServerModel(
                id=SIMPLE_SERVER,
                name="simple",
                server_type="vanilla",
                minecraft_version="1.20.4",
                mode="simple",
                provider="docker",
                root_path=str(server_root),
            )
        )
        session.add(
            ServerModel(
                id="srv-other",
                name="other",
                server_type="vanilla",
                minecraft_version="1.20.4",
                mode="advanced",
                provider="docker",
                root_path=str(server_root),
            )
        )
        await session.commit()

    event_bus = EventBus()
    recorder = _Recorder()
    for event_type in EVENT_TYPES:
        event_bus.subscribe(event_type.__name__, recorder)
    # GitHubWebhookReceivedEvent.event_type carries the GitHub event name, so
    # the bus dispatches it under "push"/"ping"/... rather than the class name.
    for github_event_type in ("push", "create", "delete", "ping"):
        event_bus.subscribe(github_event_type, recorder)
    dispatcher_calls: list[tuple[str, str, str]] = []

    async def dispatcher(server_id: str, operation_id: str, delivery_id: str) -> None:
        dispatcher_calls.append((server_id, operation_id, delivery_id))

    service = GitHubSyncService(
        layout,
        session_factory=factory,
        sync_session_factory=sync_factory,
        event_bus=event_bus,
        operation_service=OperationService(event_bus=event_bus),
        webhook_sync_dispatcher=dispatcher,
    )
    runner = _Harness(
        layout=layout,
        server_root=server_root,
        factory=factory,
        sync_factory=sync_factory,
        event_bus=event_bus,
        recorder=recorder,
        service=service,
        dispatcher_calls=dispatcher_calls,
        async_engine=async_engine,
        sync_engine=sync_engine,
    )
    try:
        yield runner
    finally:
        await async_engine.dispose()
        sync_engine.dispose()


async def _create_connection(
    harness: _Harness,
    *,
    server_id: str = ADVANCED_SERVER,
    webhook_secret: str | None = WEBHOOK_SECRET,
    webhook_enabled: bool = True,
    credential: str = PAT,
) -> ServerGitHubConnectionModel:
    conn = ServerGitHubConnectionModel(
        id=f"conn-{server_id}",
        server_id=server_id,
        remote_url="https://github.com/octo/mc-server.git",
        auth_method="pat",
        wrapped_credential_dek=b"",
        kek_version=1,
        credential_nonce=b"",
        credential_ciphertext=b"",
        sync_status="idle",
        webhook_enabled=False,
    )
    apply_credential_to_connection(
        conn,
        server_id=server_id,
        auth_method="pat",
        secret=credential,
    )
    if webhook_secret is not None:
        apply_webhook_secret_to_connection(
            conn,
            server_id=server_id,
            webhook_secret=webhook_secret,
        )
    conn.webhook_enabled = webhook_enabled
    async with harness.factory() as session:
        await SQLGitHubSyncRepository(session).save_connection(conn)
        await session.commit()
    return conn


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _push_payload(*, ref: str = "refs/heads/main", after: str = "a" * 40) -> bytes:
    return json.dumps(
        {
            "ref": ref,
            "before": "b" * 40,
            "after": after,
            "repository": {"full_name": "octo/mc-server"},
        }
    ).encode("utf-8")


def _command_error(stderr: str) -> GitCommandError:
    return GitCommandError("Git command failed", stderr=stderr)


# ----------------------------------------------------------------------
# 1. Mode guard enforcement
# ----------------------------------------------------------------------


async def test_simple_mode_guard_rejects_every_public_operation(
    harness: _Harness,
) -> None:
    service = harness.service
    calls = [
        lambda: service.generate_deploy_key(SIMPLE_SERVER),
        lambda: service.connect(
            SIMPLE_SERVER,
            remote_url="https://github.com/octo/mc-server.git",
            auth_method="pat",
            credential_secret=PAT,
        ),
        lambda: service.rotate_credentials(SIMPLE_SERVER, credential_secret=PAT),
        lambda: service.disconnect(SIMPLE_SERVER),
        lambda: service.fetch_first_sync(SIMPLE_SERVER),
        lambda: service.push_branch(SIMPLE_SERVER, "main"),
        lambda: service.get_status(SIMPLE_SERVER),
        lambda: service.list_deliveries(SIMPLE_SERVER),
        lambda: service.redeliver_webhook(SIMPLE_SERVER, "delivery-1"),
    ]
    for call in calls:
        with pytest.raises(ServerModeVersioningDisabledError) as exc_info:
            await call()
        assert exc_info.value.http_status == 409
        assert exc_info.value.code == "SERVER_MODE_VERSIONING_DISABLED"


@_POSIX_ONLY
async def test_invalid_server_segment_is_rejected(harness: _Harness) -> None:
    with pytest.raises(InvalidValueError):
        await harness.service.get_status("../escape")


# ----------------------------------------------------------------------
# 2. URL and auth-method validation
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c id",
        "fd::3",
        "file::/tmp/repo.git",
        "https://tok@github.com/octo/mc-server.git",
        "https://gitlab.com/octo/mc-server.git",
        "https://github.com/octo/mc-server.git\n",
        " https://github.com/octo/mc-server.git",
        "ssh://git@github.com:22/octo/mc-server.git",
        "https://github.com/octo/mc-server.git/extra",
        "git@github.com:octo/mc-server.git",
    ],
)
def test_remote_url_validation_rejects_hostile_forms(url: str) -> None:
    with pytest.raises(GitRemoteUrlError):
        GitHubSyncService._validate_remote_and_auth(url, "pat")


def test_remote_url_and_auth_method_must_agree() -> None:
    https = "https://github.com/octo/mc-server.git"
    ssh = "ssh://git@github.com/octo/mc-server.git"
    assert GitHubSyncService._validate_remote_and_auth(https, "pat") == https
    assert (
        GitHubSyncService._validate_remote_and_auth(ssh, "ssh_deploy_key") == ssh
    )
    with pytest.raises(ValidationError) as pat_mismatch:
        GitHubSyncService._validate_remote_and_auth(ssh, "pat")
    assert pat_mismatch.value.details["field"] == "remote_url"
    with pytest.raises(ValidationError) as ssh_mismatch:
        GitHubSyncService._validate_remote_and_auth(https, "ssh_deploy_key")
    assert ssh_mismatch.value.details["field"] == "remote_url"
    with pytest.raises(ValidationError):
        GitHubSyncService._validate_remote_and_auth(https, "oauth")
    with pytest.raises(ValidationError):
        GitHubSyncService._validate_remote_and_auth(https, "")  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 3. Deploy-key generation and redaction
# ----------------------------------------------------------------------


@_POSIX_ONLY
async def test_generate_deploy_key_redacts_private_material(
    harness: _Harness,
) -> None:
    result = await harness.service.generate_deploy_key(
        ADVANCED_SERVER, comment="unit-test"
    )
    assert isinstance(result, GeneratedDeployKeyResult)
    assert result.public_key_openssh.startswith("ssh-ed25519 ")
    assert result.fingerprint_sha256.startswith("SHA256:")
    assert result.public_key_openssh.endswith("unit-test")
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in result.private_key_pem
    for rendered in (repr(result), str(result)):
        assert "***REDACTED***" in rendered
        assert result.private_key_pem not in rendered
        assert "BEGIN OPENSSH PRIVATE KEY" not in rendered


# ----------------------------------------------------------------------
# 4. Git remote error classifier
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "fatal: Authentication failed for 'https://github.com/octo/mc-server.git/'",
        "remote: Invalid username or token.",
        "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
        "The requested URL returned error: 401",
        "The requested URL returned error: 403",
        "remote: Repository not found.",
        "git@github.com: Permission denied (publickey).",
        "remote: Write access to repository not granted.",
        "remote: Deploy key does not have write access.",
        "remote: Permission to octo/mc-server.git denied to deploy-key.",
        "remote: Bad credentials",
    ],
)
def test_classifier_maps_auth_failures_to_reauthentication(stderr: str) -> None:
    classified = classify_git_remote_error(
        _command_error(stderr), auth_method="pat", branch="main"
    )
    assert isinstance(classified, GitHubAuthFailedError)
    assert classified.needs_reauth is True
    assert classified.http_status == 409
    assert classified.code == "GITHUB_AUTH_FAILED"


def test_classifier_never_leaks_extra_secrets() -> None:
    secret = "ghp_supersecretvalue9876543210"
    classified = classify_git_remote_error(
        _command_error(
            f"remote: Invalid username or token {secret} for 'https://x@github.com'"
        ),
        auth_method="pat",
        extra_secrets=(secret,),
    )
    assert isinstance(classified, GitHubAuthFailedError)
    rendered = f"{classified.message}\n{classified.details!r}\n{classified!r}"
    assert secret not in rendered
    assert classified.details["needs_reauth"] is True


@pytest.mark.parametrize(
    "stderr",
    [
        "! [rejected]        main -> main (non-fast-forward)",
        "! [rejected]        main -> main (fetch first)",
        "! [rejected]        main -> main (cannot lock ref 'refs/heads/main')",
        "Updates were rejected because the tip of your current branch is behind",
        "Updates were rejected because the remote contains work that you do not have",
    ],
)
def test_classifier_rejects_non_fast_forward_main(stderr: str) -> None:
    classified = classify_git_remote_error(
        _command_error(stderr),
        auth_method="pat",
        branch="main",
        local_sha="a" * 40,
        remote_sha="b" * 40,
    )
    assert isinstance(classified, NonFastForwardMainError)
    assert classified.http_status == 409
    assert classified.code == "GITHUB_NON_FAST_FORWARD_MAIN"
    assert classified.details["local_sha"] == "a" * 40
    assert classified.details["remote_sha"] == "b" * 40


@pytest.mark.parametrize(
    "stderr",
    [
        "! [rejected]        feat -> feat (non-fast-forward)",
        "! [rejected]        feat -> feat (fetch first)",
        "remote: error: GH001: Large files detected.",
        "remote: error: Protected branch update failed",
        "remote rejected: pre-receive hook declined",
    ],
)
def test_classifier_rejects_feature_branch_pushes(stderr: str) -> None:
    classified = classify_git_remote_error(
        _command_error(stderr), auth_method="pat", branch="feat/spawn"
    )
    assert isinstance(classified, GitHubPushRejectedError)
    assert classified.http_status == 409
    assert classified.code == "GITHUB_PUSH_REJECTED"


def test_classifier_preserves_timeouts_and_transient_network_errors() -> None:
    timeout = GitTimeoutError("timed out", command="fetch", timeout_seconds=1.0)
    assert classify_git_remote_error(timeout, auth_method="pat") is timeout

    transient = _command_error("fatal: unable to access: Could not resolve host")
    result = classify_git_remote_error(transient, auth_method="pat")
    assert result is transient
    assert not isinstance(result, GitHubAuthFailedError)


# ----------------------------------------------------------------------
# 5. Force-push unconditional denial (before any Git invocation)
# ----------------------------------------------------------------------


@_POSIX_ONLY
async def test_force_push_is_denied_before_touching_git(harness: _Harness) -> None:
    with pytest.raises(NonFastForwardMainError) as main_exc:
        await harness.service.push_branch(ADVANCED_SERVER, "main", force=True)
    assert main_exc.value.code == "GITHUB_NON_FAST_FORWARD_MAIN"

    with pytest.raises(GitHubPushRejectedError) as feature_exc:
        await harness.service.push_branch(
            ADVANCED_SERVER, "feat/spawn", force=True
        )
    assert feature_exc.value.code == "GITHUB_PUSH_REJECTED"
    assert feature_exc.value.details["reason"] == "force_push_forbidden"


# ----------------------------------------------------------------------
# 6. Webhook ingestion, dedupe, enqueue-only, and redelivery
# ----------------------------------------------------------------------


@_POSIX_ONLY
async def test_webhook_fails_closed_without_leaking_secrets(
    harness: _Harness,
) -> None:
    service = harness.service
    body = _push_payload()

    # No connection at all.
    with pytest.raises(WebhookSignatureError) as missing:
        await service.ingest_webhook(
            ADVANCED_SERVER,
            raw_body=body,
            signature_header=_signature(WEBHOOK_SECRET, body),
            delivery_id="d-missing",
            event_type="push",
        )
    assert missing.value.http_status == 401

    # Simple-mode server is indistinguishable from a missing connection.
    with pytest.raises(WebhookSignatureError):
        await service.ingest_webhook(
            SIMPLE_SERVER,
            raw_body=body,
            signature_header=_signature(WEBHOOK_SECRET, body),
            delivery_id="d-simple",
            event_type="push",
        )

    # Connected but webhook disabled.
    disabled = await _create_connection(
        harness, webhook_enabled=False, webhook_secret=WEBHOOK_SECRET
    )
    assert disabled.webhook_enabled is False
    with pytest.raises(WebhookSignatureError):
        await service.ingest_webhook(
            ADVANCED_SERVER,
            raw_body=body,
            signature_header=_signature(WEBHOOK_SECRET, body),
            delivery_id="d-disabled",
            event_type="push",
        )

    # Enable the webhook again and exercise signature failures.
    async with harness.factory() as session:
        row = await SQLGitHubSyncRepository(session).get_connection(
            ADVANCED_SERVER
        )
        assert row is not None
        row.webhook_enabled = True
        await session.commit()

    for signature in (
        None,
        "",
        "sha256=" + "0" * 64,
        "sha1=" + "0" * 40,
        _signature(WEBHOOK_SECRET, body[::-1]),
    ):
        with pytest.raises(WebhookSignatureError) as exc_info:
            await service.ingest_webhook(
                ADVANCED_SERVER,
                raw_body=body,
                signature_header=signature,
                delivery_id="d-bad-signature",
                event_type="push",
            )
        rendered = f"{exc_info.value!r}\n{exc_info.value.details!r}"
        assert WEBHOOK_SECRET not in rendered
        assert hashlib.sha256(body).hexdigest() not in rendered


@_POSIX_ONLY
async def test_valid_push_webhook_enqueues_only_and_dedupes(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_connection(harness)
    service = harness.service

    async def _must_not_sync(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("ingest_webhook must never execute git fetch")

    monkeypatch.setattr(service, "fetch_first_sync", _must_not_sync)

    body = _push_payload()
    result = await service.ingest_webhook(
        ADVANCED_SERVER,
        raw_body=body,
        signature_header=_signature(WEBHOOK_SECRET, body),
        delivery_id="delivery-1",
        event_type="push",
    )
    assert result.status == "queued"
    assert result.deduplicated is False
    assert result.operation_id is not None
    assert harness.dispatcher_calls == [
        (ADVANCED_SERVER, result.operation_id, "delivery-1")
    ]

    async with harness.factory() as session:
        operations = (
            (await session.execute(select(OperationModel))).scalars().all()
        )
        deliveries = (
            (
                await session.execute(
                    select(GitHubWebhookDeliveryModel).where(
                        GitHubWebhookDeliveryModel.server_id == ADVANCED_SERVER
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(operations) == 1
    operation = operations[0]
    assert operation.type == OperationType.GITHUB_SYNC.value
    assert operation.status == OperationStatus.QUEUED.value
    assert operation.target_type == "server"
    assert operation.target_id == ADVANCED_SERVER
    assert len(deliveries) == 1
    assert deliveries[0].status == "queued"
    assert deliveries[0].operation_id == result.operation_id
    assert deliveries[0].signature_valid is True

    duplicate = await service.ingest_webhook(
        ADVANCED_SERVER,
        raw_body=body,
        signature_header=_signature(WEBHOOK_SECRET, body),
        delivery_id="delivery-1",
        event_type="push",
    )
    assert duplicate.status == "deduplicated"
    assert duplicate.deduplicated is True
    assert duplicate.operation_id == result.operation_id
    assert len(harness.dispatcher_calls) == 1

    async with harness.factory() as session:
        operations = (
            (await session.execute(select(OperationModel))).scalars().all()
        )
        deliveries = (
            await session.execute(select(GitHubWebhookDeliveryModel))
        ).scalars().all()
    assert len(operations) == 1
    assert len(deliveries) == 1

    dedupe_events = [
        event
        for event in harness.recorder.events
        if isinstance(event, GitHubWebhookReceivedEvent) and event.deduplicated
    ]
    assert len(dedupe_events) == 1
    assert dedupe_events[0].operation_id == result.operation_id


@_POSIX_ONLY
async def test_ping_webhook_is_ignored_without_an_operation(
    harness: _Harness,
) -> None:
    await _create_connection(harness)
    body = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")
    result = await harness.service.ingest_webhook(
        ADVANCED_SERVER,
        raw_body=body,
        signature_header=_signature(WEBHOOK_SECRET, body),
        delivery_id="delivery-ping",
        event_type="ping",
    )
    assert result.status == "ignored"
    assert result.operation_id is None
    assert harness.dispatcher_calls == []

    async with harness.factory() as session:
        operations = (
            (await session.execute(select(OperationModel))).scalars().all()
        )
        delivery = (
            await session.execute(
                select(GitHubWebhookDeliveryModel).where(
                    GitHubWebhookDeliveryModel.delivery_id == "delivery-ping"
                )
            )
        ).scalar_one()
    assert operations == []
    assert delivery.status == "ignored"
    assert delivery.processed_at is not None


@_POSIX_ONLY
async def test_redelivery_increments_count_and_creates_fresh_operations(
    harness: _Harness,
) -> None:
    await _create_connection(harness)
    body = _push_payload()
    first = await harness.service.ingest_webhook(
        ADVANCED_SERVER,
        raw_body=body,
        signature_header=_signature(WEBHOOK_SECRET, body),
        delivery_id="delivery-redeliver",
        event_type="push",
    )
    assert first.operation_id is not None

    for expected_count in (1, 2):
        result = await harness.service.redeliver_webhook(
            ADVANCED_SERVER, "delivery-redeliver", actor_id="operator-1"
        )
        assert result.status == "queued"
        assert result.redelivered is True
        assert result.redelivery_count == expected_count
        assert result.operation_id is not None
        assert result.operation_id != first.operation_id

    assert len(harness.dispatcher_calls) == 3
    async with harness.factory() as session:
        operations = (
            (await session.execute(select(OperationModel))).scalars().all()
        )
        delivery = (
            await session.execute(
                select(GitHubWebhookDeliveryModel).where(
                    GitHubWebhookDeliveryModel.delivery_id
                    == "delivery-redeliver"
                )
            )
        ).scalar_one()
    assert len(operations) == 3
    assert delivery.redelivery_count == 2
    redelivery_events = [
        event
        for event in harness.recorder.events
        if isinstance(event, GitHubWebhookReceivedEvent) and event.redelivered
    ]
    assert len(redelivery_events) == 2
    assert all(event.actor_id == "operator-1" for event in redelivery_events)


@_POSIX_ONLY
async def test_list_deliveries_is_reverse_chronological_and_secret_free(
    harness: _Harness,
) -> None:
    await _create_connection(harness)
    now = datetime.now(UTC)
    async with harness.factory() as session:
        repo = SQLGitHubSyncRepository(session)
        for delivery_id, received_at in (
            ("older", now - timedelta(minutes=5)),
            ("newer", now),
        ):
            await repo.create_webhook_delivery(
                GitHubWebhookDeliveryModel(
                    id=f"row-{delivery_id}",
                    server_id=ADVANCED_SERVER,
                    delivery_id=delivery_id,
                    event_type="push",
                    ref="refs/heads/main",
                    payload_sha256=hashlib.sha256(delivery_id.encode()).hexdigest(),
                    raw_payload='{"secret": "' + WEBHOOK_SECRET + '"}',
                    signature_valid=True,
                    status="queued",
                    redelivery_count=0,
                    received_at=received_at,
                )
            )
        await session.commit()

    records = await harness.service.list_deliveries(ADVANCED_SERVER, limit=10)
    assert [record.delivery_id for record in records] == ["newer", "older"]
    for record in records:
        rendered = repr(record)
        assert WEBHOOK_SECRET not in rendered
        assert PAT not in rendered
        assert not hasattr(record, "raw_payload")


@_POSIX_ONLY
async def test_oversized_webhook_payload_is_rejected(
    harness: _Harness,
) -> None:
    await _create_connection(harness)
    body = b"{" + b" " * (2 * 1024 * 1024) + b"}"
    with pytest.raises(ValidationError) as exc_info:
        await harness.service.ingest_webhook(
            ADVANCED_SERVER,
            raw_body=body,
            signature_header=_signature(WEBHOOK_SECRET, body),
            delivery_id="delivery-huge",
            event_type="push",
        )
    assert exc_info.value.details["field"] == "raw_body"


# ----------------------------------------------------------------------
# 7. Domain events and DTO secret hygiene
# ----------------------------------------------------------------------


async def test_domain_events_instantiate_and_publish(harness: _Harness) -> None:
    events = [
        GitHubConnectedEvent(
            server_id=ADVANCED_SERVER,
            remote_url="https://github.com/octo/mc-server.git",
            auth_method="pat",
        ),
        GitHubDisconnectedEvent(
            server_id=ADVANCED_SERVER,
            remote_url="https://github.com/octo/mc-server.git",
        ),
        GitHubCredentialsRotatedEvent(
            server_id=ADVANCED_SERVER, auth_method="pat"
        ),
        GitHubSyncedEvent(server_id=ADVANCED_SERVER, sync_status="synced"),
        GitHubPushedEvent(
            server_id=ADVANCED_SERVER,
            branch_name="main",
            commit_sha="a" * 40,
            remote_url="https://github.com/octo/mc-server.git",
        ),
        GitHubWebhookReceivedEvent(
            server_id=ADVANCED_SERVER,
            delivery_id="delivery-1",
            webhook_event="push",
        ),
    ]
    for event in events:
        await harness.event_bus.publish(event)

    published = [event for event in harness.recorder.events if event in events]
    assert published == events
    for event in events:
        assert event.event_type == type(event).__name__
        if isinstance(event, GitHubWebhookReceivedEvent):
            assert event.webhook_event == "push"
        rendered = repr(event.model_dump())
        assert PAT not in rendered
        assert WEBHOOK_SECRET not in rendered


@_POSIX_ONLY
async def test_status_and_dto_never_expose_secret_material(
    harness: _Harness,
) -> None:
    await _create_connection(harness)
    status = await harness.service.get_status(ADVANCED_SERVER)
    assert isinstance(status, GitHubConnectionStatus)
    assert status.connected is True
    assert status.webhook_enabled is True
    assert status.auth_method == "pat"
    assert status.generated_webhook_secret is None
    assert status.credential_hint is not None
    assert status.credential_hint != PAT

    async with harness.factory() as session:
        row = await SQLGitHubSyncRepository(session).get_connection(
            ADVANCED_SERVER
        )
    assert row is not None
    ciphertext = bytes(row.credential_ciphertext)
    webhook_ciphertext = bytes(row.webhook_ciphertext or b"")

    rendered = f"{status!r}\n{status!s}\n{status!r}"
    for value in (PAT, WEBHOOK_SECRET, ciphertext.hex(), webhook_ciphertext.hex()):
        assert value not in rendered

    generated = GitHubConnectionStatus(
        server_id=ADVANCED_SERVER,
        connected=True,
        generated_webhook_secret=WEBHOOK_SECRET,
    )
    assert WEBHOOK_SECRET not in repr(generated)
    assert WEBHOOK_SECRET not in str(generated)
    assert "***REDACTED***" in repr(generated)

    branch = GitHubBranchSyncState(
        branch="main",
        status="synced",
        local_sha="a" * 40,
        remote_sha="a" * 40,
    )
    round_trip = GitHubBranchSyncState.from_dict(branch.to_dict())
    assert round_trip == branch

    disconnected = await harness.service.get_status("srv-other")
    assert disconnected.connected is False
    assert disconnected.sync_status == "disconnected"
