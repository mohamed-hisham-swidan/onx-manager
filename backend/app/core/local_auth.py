"""Local zero-login provisioning and strict fail-closed loopback enforcement."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config as config_mod
from app.core.config import AppSettings, ConfigFactory, get_panel_bind
from app.core.exceptions import NotFoundError, PasswordRequiredForExposureError
from app.modules.auth.domain.aggregate import AccessMode, Role, User
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import (
    SQLSystemStateRepository,
    SQLUserRepository,
)
from app.modules.shared.value_objects import Permission, RoleId, UserId

logger = logging.getLogger(__name__)

LOCAL_ADMIN_USER_ID = "local-admin"
LOCAL_ADMIN_USERNAME = "local-admin"
LOCAL_ADMIN_DISPLAY_NAME = "Local Admin"
PASSWORDLESS_HASH_SENTINEL = "!PASSWORDLESS_LOCAL_ONLY!"

PROXY_FORWARD_HEADERS: tuple[str, ...] = (
    "x-forwarded-for",
    "forwarded",
    "x-real-ip",
    "cf-connecting-ip",
    "true-client-ip",
    "x-client-ip",
)


def is_loopback_bind_host(host: str | None) -> bool:
    """Return True only when *host* designates a loopback-only bind target."""
    if not host:
        return False
    cleaned = host.strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    if cleaned == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped.is_loopback
    return addr.is_loopback


def is_loopback_client_ip(host: str | None) -> bool:
    """Return True strictly when *host* is a loopback IP literal (127.0.0.0/8 or ::1)."""
    if not host:
        return False
    cleaned = host.strip()
    if not cleaned:
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped.is_loopback
    return addr.is_loopback


def has_proxy_forwarding_headers(headers: Mapping[str, str]) -> bool:
    """Return True if any reverse-proxy forwarding header is present."""
    return any(key.lower() in PROXY_FORWARD_HEADERS for key in headers)


def is_loopback_host_header(headers: Mapping[str, str]) -> bool:
    """Return True when the HTTP Host header targets loopback (blocks DNS rebinding)."""
    host_val = next((v for k, v in headers.items() if k.lower() == "host"), None)
    if not host_val or not host_val.strip():
        return True
    cleaned = host_val.strip()
    if cleaned.startswith("["):
        end_bracket = cleaned.find("]")
        if end_bracket == -1:
            return False
        parsed_host = cleaned[1:end_bracket]
        remainder = cleaned[end_bracket + 1 :]
        if remainder and not remainder.startswith(":"):
            return False
    elif ":" in cleaned:
        host_part, port_part = cleaned.rsplit(":", 1)
        parsed_host = host_part if port_part.isdigit() else cleaned
    else:
        parsed_host = cleaned
    return is_loopback_bind_host(parsed_host)


def is_strict_loopback_request(client_host: str | None, headers: Mapping[str, str]) -> bool:
    """Fail-closed check: client socket must be loopback, no proxy headers, loopback Host."""
    return (
        is_loopback_client_ip(client_host)
        and not has_proxy_forwarding_headers(headers)
        and is_loopback_host_header(headers)
    )


def is_local_profile_and_loopback_bound(settings: AppSettings | None = None) -> bool:
    """Return True only when deployment_profile=='local' and panel bind is strictly loopback."""
    cfg = settings or ConfigFactory.global_settings()
    if cfg.deployment_profile != "local":
        return False
    configured_host, _ = get_panel_bind()
    if not is_loopback_bind_host(configured_host):
        return False
    active_host = config_mod._ACTIVE_PANEL_BIND_HOST
    return active_host is None or is_loopback_bind_host(active_host)


def compute_auth_mode(
    password_configured: bool,
    settings: AppSettings | None = None,
) -> Literal["local_zero_login", "jwt"]:
    """Compute effective authentication mode exposed to UI/Desktop clients."""
    if is_local_profile_and_loopback_bound(settings) and not password_configured:
        return "local_zero_login"
    return "jwt"


async def ensure_local_admin_provisioned(
    session: AsyncSession,
    settings: AppSettings | None = None,
) -> bool:
    """Auto-provision passwordless `local-admin` owner in local loopback mode when unconfigured.

    Returns True when changes were flushed to *session* (caller should commit).
    """
    if not is_local_profile_and_loopback_bound(settings):
        return False

    sys_repo = SQLSystemStateRepository(session)
    state = await sys_repo.get_with_lock("default")
    if state.initialized and state.password_configured:
        return False

    user_repo = SQLUserRepository(session)
    user_count = await user_repo.count_users()
    if not state.initialized and user_count > 0:
        return False

    owner_role = await user_repo.get_role_by_name("owner")
    if owner_role is None:
        owner_role = Role(
            role_id=RoleId(LOCAL_ADMIN_USER_ID + "-owner-role"),
            name="owner",
            permissions=[Permission("admin", "full"), Permission("global", "*")],
            description="Instance Owner",
        )
        await user_repo.save_role(owner_role)

    existing_user: User | None = None
    try:
        existing_user = await user_repo.get(UserId(LOCAL_ADMIN_USER_ID))
    except NotFoundError:
        existing_user = await user_repo.get_by_username(LOCAL_ADMIN_USERNAME)

    changed = False
    if existing_user is None and user_count == 0:
        local_user = User.create(
            user_id=UserId(LOCAL_ADMIN_USER_ID),
            username=LOCAL_ADMIN_USERNAME,
            email=None,
            password_hash=PASSWORDLESS_HASH_SENTINEL,
            display_name=LOCAL_ADMIN_DISPLAY_NAME,
        )
        local_user.add_role(owner_role)
        await user_repo.save(local_user)
        changed = True
    elif existing_user is not None and not any(r.name == "owner" for r in existing_user.roles):
        existing_user.add_role(owner_role)
        await user_repo.save(existing_user)
        changed = True

    if not state.initialized:
        state.mark_initialized(access_mode=AccessMode.LOCAL, password_configured=False)
        await sys_repo.save(state)
        changed = True

    return changed


async def resolve_local_auto_auth(
    client_host: str | None,
    headers: Mapping[str, str],
    session: AsyncSession,
    settings: AppSettings | None = None,
) -> dict[str, Any] | None:
    """Resolve `local-admin` security context for strictly loopback local-mode requests.

    Fail-closed: returns None unless all local-mode, loopback-bind, strict-loopback-client,
    and passwordless-state conditions hold.
    """
    if not is_local_profile_and_loopback_bound(settings):
        return None
    if not is_strict_loopback_request(client_host, headers):
        return None

    sys_repo = SQLSystemStateRepository(session)
    state = await sys_repo.get("default")
    if state.password_configured:
        return None

    if not state.initialized:
        provisioned = await ensure_local_admin_provisioned(session, settings)
        if provisioned:
            await session.commit()
        state = await sys_repo.get("default")
        if not state.initialized or state.password_configured:
            return None

    user_repo = SQLUserRepository(session)
    user: User | None = None
    try:
        user = await user_repo.get(UserId(LOCAL_ADMIN_USER_ID))
    except NotFoundError:
        user = await user_repo.get_by_username(LOCAL_ADMIN_USERNAME)

    if user is None or not user.is_active:
        return None

    roles = [r.name for r in user.roles]
    permissions = await PermissionEvaluator().get_effective_permissions(user)
    return {
        "user_id": str(user.user_id),
        "roles": roles,
        "permissions": permissions,
        "scope": ",".join(permissions),
        "auth_mode": "local_zero_login",
    }


async def require_password_configured_for_exposure(
    session: AsyncSession,
    *,
    action: str = "external_exposure",
    settings: AppSettings | None = None,
) -> None:
    """Block tunnels, remote exposure, or non-loopback bind when in passwordless local mode."""
    cfg = settings or ConfigFactory.global_settings()
    if cfg.deployment_profile != "local":
        return

    state = await SQLSystemStateRepository(session).get("default")
    if not state.password_configured:
        raise PasswordRequiredForExposureError(
            details={
                "reason": "passwordless_local_mode",
                "action": action,
            }
        )
