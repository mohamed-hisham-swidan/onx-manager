from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import require_exposure_grant, require_server_permission
from app.api.v1.routers.exposure import _is_blocked_ssrf_probe_host, _parse_probe_host_port
from app.core.auth_utils import _resolve_api_key
from app.core.event_bus import EventBus
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    InvalidValueError,
    PermissionDenied,
    RateLimitExceeded,
)
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.security import hash_api_key
from app.modules.auth.application.commands.create_invite import (
    CreateInviteCommand,
    CreateInviteHandler,
)
from app.modules.auth.application.commands.delete_user import (
    DeleteUserCommand,
    DeleteUserHandler,
)
from app.modules.auth.application.commands.update_user import (
    UpdateUserCommand,
    UpdateUserHandler,
)
from app.modules.auth.infrastructure.models import ApiKeyModel, RoleModel, UserModel, UserRoleModel
from app.modules.exposure.domain.aggregate import ServerExposureTarget
from app.modules.exposure.domain.value_objects import (
    ExposureStatus,
    ServiceType,
    TargetProtocol,
)
from app.modules.health.application.event_handlers.server_crashed_handler import (
    HandleServerCrashHandler,
)
from app.modules.health.domain.value_objects import CrashClassification, EvidenceBundle
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider
from app.modules.server.domain.events import ServerCrashedEvent
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.infrastructure.mc_slp import slp_version_matches_mc
from app.tasks.scheduler import Scheduler
from app.websocket.authorization import ChannelAuthorizer


@pytest.fixture
async def mem_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = factory
    try:
        yield factory
    finally:
        database._engine = old_engine
        database._session_factory = old_factory
        await engine.dispose()


class _FakeRequest:
    def __init__(self, path_params: dict[str, str] | None = None):
        self.path_params = path_params or {}
        self.query_params: dict[str, str] = {}
        self.headers: dict[str, str] = {}


@pytest.mark.asyncio
async def test_sqlite_naive_api_key_expiry_handling(mem_db) -> None:
    """Expiring API keys loaded as naive datetimes from SQLite never crash with TypeError."""
    raw_expired = "onx_expired_key_test_123456"
    raw_valid = "onx_valid_key_test_123456"
    now_naive = datetime.now(UTC).replace(tzinfo=None)

    async with mem_db() as session:
        session.add(
            UserModel(
                id="u-owner",
                username="owner",
                display_name="Owner",
                email="owner@example.com",
                password_hash="hashed",
                is_active=True,
            )
        )
        session.add(
            ApiKeyModel(
                id="ak-exp",
                user_id="u-owner",
                name="expired",
                prefix="onx_exp",
                key_hash=hash_api_key(raw_expired),
                permissions="server:read",
                expires_at=now_naive - timedelta(hours=1),
                is_revoked=False,
            )
        )
        session.add(
            ApiKeyModel(
                id="ak-val",
                user_id="u-owner",
                name="valid",
                prefix="onx_val",
                key_hash=hash_api_key(raw_valid),
                permissions="server:read",
                expires_at=now_naive + timedelta(hours=2),
                is_revoked=False,
            )
        )
        await session.commit()

    async with mem_db() as session:
        with pytest.raises(AuthenticationError, match="expired"):
            await _resolve_api_key(raw_expired, session)
        claims = await _resolve_api_key(raw_valid, session)
        assert claims["user_id"] == "u-owner"
        assert claims["auth_type"] == "api_key"
        assert claims["permissions"] == ["server:read"]


@pytest.mark.asyncio
async def test_api_key_scope_isolation_blocks_owner_escalation(mem_db) -> None:
    """A scoped read-only API key cannot bypass scope checks via server ownership."""
    async with mem_db() as session:
        session.add(
            ServerModel(
                id="srv-1",
                name="Alpha",
                owner_id="u-owner",
                server_type="paper",
                minecraft_version="1.21.4",
                status="stopped",
            )
        )
        await session.commit()

    req = _FakeRequest(path_params={"server_id": "srv-1"})
    unscoped_key_user = {
        "user_id": "u-owner",
        "roles": [],
        "permissions": [],
        "auth_type": "api_key",
    }
    read_key_user = {
        "user_id": "u-owner",
        "roles": [],
        "permissions": ["server:read"],
        "auth_type": "api_key",
    }

    async with mem_db() as session:
        check_console = require_server_permission("server.{id}.console")
        # Unscoped personal API key inherits the owner's own server access
        allowed_personal = await check_console(
            request=req, db=session, current_user=unscoped_key_user
        )
        assert allowed_personal["user_id"] == "u-owner"

        # Explicitly scoped read-only API key is blocked from console & exposure
        with pytest.raises(PermissionDenied) as exc_read_console:
            await check_console(request=req, db=session, current_user=read_key_user)
        assert exc_read_console.value.http_status == 403

        check_view = require_server_permission("server.{id}.view")
        allowed = await check_view(request=req, db=session, current_user=read_key_user)
        assert allowed["user_id"] == "u-owner"

        check_exp = require_exposure_grant("server.{id}.exposure")
        with pytest.raises(PermissionDenied) as exc_exp:
            await check_exp(request=req, db=session, current_user=read_key_user)
        assert exc_exp.value.http_status == 403


@pytest.mark.asyncio
async def test_unprivileged_user_cannot_create_global_invite(mem_db) -> None:
    """Non-admin users cannot mint global invitations or arbitrary global_role strings."""
    async with mem_db() as session:
        session.add(RoleModel(id="role-member", name="member", permissions="server:read"))
        session.add(
            UserModel(
                id="u-member",
                username="member1",
                display_name="Member One",
                email="member1@example.com",
                password_hash="hashed",
                is_active=True,
            )
        )
        await session.flush()
        session.add(UserRoleModel(user_id="u-member", role_id="role-member"))
        await session.commit()

    handler = CreateInviteHandler(EventBus())
    with pytest.raises(PermissionDenied):
        await handler.handle(
            CreateInviteCommand(creator_id="u-member", global_role="member", server_id=None)
        )

    with pytest.raises(InvalidValueError):
        await handler.handle(
            CreateInviteCommand(creator_id="u-member", global_role="superadmin", server_id=None)
        )


@pytest.mark.asyncio
async def test_last_active_owner_cannot_be_deleted_or_deactivated(mem_db) -> None:
    """Deleting or deactivating the sole active owner raises ConflictError."""
    async with mem_db() as session:
        session.add(RoleModel(id="role-owner", name="owner", permissions="admin:full,global:*"))
        session.add(
            UserModel(
                id="u-sole-owner",
                username="rootowner",
                display_name="Root Owner",
                email="root@example.com",
                password_hash="hashed",
                is_active=True,
            )
        )
        await session.flush()
        session.add(UserRoleModel(user_id="u-sole-owner", role_id="role-owner"))
        await session.commit()

    bus = EventBus()
    with pytest.raises(ConflictError):
        await DeleteUserHandler(bus).handle(DeleteUserCommand(user_id="u-sole-owner"))

    with pytest.raises(ConflictError):
        await UpdateUserHandler(bus).handle(
            UpdateUserCommand(user_id="u-sole-owner", is_active=False)
        )


def test_rate_limit_exceeded_accepts_message_and_details() -> None:
    exc = RateLimitExceeded(
        message="Upstream marketplace rate limit exceeded",
        details={"retry_after": 30},
    )
    assert exc.http_status == 429
    assert exc.message == "Upstream marketplace rate limit exceeded"
    assert exc.details["retry_after"] == 30


def test_slp_version_matches_mc_rejects_minor_prefix_false_positive() -> None:
    assert slp_version_matches_mc("Paper 1.21.4", "1.21.4") is True
    assert slp_version_matches_mc("Purpur 1.21.11", "1.21.11") is True
    assert slp_version_matches_mc("Paper 1.21.4", "1.21") is False
    assert slp_version_matches_mc("Paper 1.21.1", "1.21.11") is False


def test_exposure_ssrf_probe_blocks_dns_internal_and_invalid_ports() -> None:
    fake_loopback = [(2, 1, 6, "", ("127.0.0.1", 0))]
    fake_metadata = [(2, 1, 6, "", ("169.254.169.254", 0))]
    fake_public = [(2, 1, 6, "", ("93.184.216.34", 0))]

    with patch("socket.getaddrinfo", return_value=fake_loopback):
        assert _is_blocked_ssrf_probe_host("127.0.0.1.nip.io") is True
    with patch("socket.getaddrinfo", return_value=fake_metadata):
        assert _is_blocked_ssrf_probe_host("metadata.nip.io") is True
    with patch("socket.getaddrinfo", return_value=fake_public):
        assert _is_blocked_ssrf_probe_host("play.example.com") is False

    bad_port_payload = {
        "desired_state": "ENABLED",
        "aggregate_status": "ACTIVE",
        "targets": [{"service_type": "java", "public_address": "play.example.com:70000"}],
    }
    assert _parse_probe_host_port(bad_port_payload) is None


def test_scheduler_validate_expression_rejects_bad_intervals() -> None:
    Scheduler._validate_expression("interval:60s")
    Scheduler._validate_expression("0 * * * *")
    for bad in ("interval:0s", "interval:-5s", "interval:nan", "interval:inf", "interval:abc"):
        with pytest.raises(ValueError):
            Scheduler._validate_expression(bad)


def test_ws_channel_authorizer_blocks_cross_user_subscription() -> None:
    authz = ChannelAuthorizer()
    authz.set_permissions("user-a", {"user:read", "server:read"})
    assert authz.can_subscribe("user-a", "user:user-a") is True
    assert authz.can_subscribe("user-a", "user:user-b") is False


def test_exposure_target_allows_claim_required_from_recovery_states() -> None:
    for start_status in (
        ExposureStatus.CLAIM_REQUIRED,
        ExposureStatus.ERROR,
        ExposureStatus.DEGRADED,
        ExposureStatus.RECLAIM_REQUIRED,
        ExposureStatus.STOPPED,
    ):
        target = ServerExposureTarget(
            exposure_id="exp-1",
            id="t1",
            service_type=ServiceType.JAVA,
            protocol=TargetProtocol.TCP,
            local_port=25565,
            status=start_status,
        )
        target._transition_to(ExposureStatus.CLAIM_REQUIRED)
        assert target.status == ExposureStatus.CLAIM_REQUIRED


@pytest.mark.asyncio
async def test_crash_handler_does_not_mutate_frozen_evidence_bundle(mem_db) -> None:
    """When latest.log is empty, HandleServerCrashHandler replaces frozen EvidenceBundle safely."""
    handler = HandleServerCrashHandler(EventBus())
    empty_bundle = EvidenceBundle(server_id="srv-crash-frozen", latest_log_tail=[])
    assert dataclasses.is_dataclass(empty_bundle)

    handler._collector.collect = AsyncMock(return_value=empty_bundle)  # type: ignore[method-assign]
    handler._classifier.classify = AsyncMock(
        return_value=CrashClassification(
            failure_code="UNKNOWN_CRASH",
            confidence=0.5,
            summary="crash",
            suggested_action="check logs",
            evidence_id=empty_bundle.evidence_id,
        )
    )  # type: ignore[method-assign]
    handler._recovery.trigger = AsyncMock(return_value=MagicMock(events=[]))  # type: ignore[method-assign]

    event = ServerCrashedEvent(
        server_id="srv-crash-frozen",
        exit_code=1,
        last_log_lines=["Error: UnsupportedClassVersionError"],
    )
    await handler.handle(event)
    called_bundle = handler._classifier.classify.call_args.args[0]
    assert called_bundle.latest_log_tail == ["Error: UnsupportedClassVersionError"]


@pytest.mark.asyncio
async def test_modrinth_search_infers_dual_plugin_and_mod_projects() -> None:
    provider = ModrinthProvider()
    fake_payload = {
        "hits": [
            {
                "project_id": "luckperms",
                "slug": "luckperms",
                "title": "LuckPerms",
                "description": "Permissions plugin & mod",
                "author": "Luck",
                "project_type": "mod",
                "categories": ["paper", "spigot", "fabric", "forge"],
                "downloads": 1000,
                "follows": 100,
            }
        ],
        "total_hits": 1,
    }
    with patch.object(ModrinthProvider, "_get_json", new=AsyncMock(return_value=fake_payload)):
        res = await provider.search(query="luckperms", project_type="plugin")
    assert len(res.items) == 1
    assert set(res.items[0].project_types) == {"plugin", "mod"}
