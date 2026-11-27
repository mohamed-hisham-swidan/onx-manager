from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import (
    ROLE_ADMIN,
    ROLE_OWNER,
    ROLE_SERVER_ADMIN,
    ROLE_VIEWER,
    database_has_users,
    load_user_auth_context,
    load_user_model_with_roles,
    normalize_server_action,
)
from app.core.security import hash_api_key
from app.modules.auth.infrastructure.jwt import verify_access_token
from app.modules.auth.infrastructure.models import ApiKeyModel

_SERVER_ADMIN_API_KEY_SCOPES: frozenset[str] = frozenset(
    {
        "server:read",
        "server:write",
        "server:start",
        "server:stop",
        "server:restart",
        "backup:read",
        "backup:create",
        "backup:restore",
        "backup:delete",
        "plugin:read",
        "plugin:install",
        "plugin:manage",
        "server:version:read",
        "server:version:commit",
        "server.versioning.manage",
        "exposure:read",
        "exposure:manage",
        "exposure:write",
    }
)
_VIEWER_API_KEY_SCOPES: frozenset[str] = frozenset(
    {
        "server:read",
        "backup:read",
        "plugin:read",
        "server:version:read",
        "exposure:read",
    }
)


def _permission_capability(perm: str) -> str:
    lower = perm.lower()
    if lower.startswith("backup:") or ".backup" in lower:
        return "backups"
    if lower.startswith("plugin:") or ".plugin" in lower:
        return "plugins"
    if lower.startswith("exposure:") or ".exposure" in lower:
        return "exposure"
    if "version" in lower:
        return "versioning"
    if lower in ("server:start", "server:stop", "server:restart") or lower.endswith(".power"):
        return "power"
    if ".console" in lower:
        return "console"
    if ".files" in lower:
        return "files"
    if lower == "server:write" or lower.endswith((".settings", ".write")):
        return "settings"
    return ""


def _intersect_api_key_permissions(
    raw_permissions: list[str],
    *,
    live_role: str,
    live_denied: set[str],
    live_effective_perms: set[str],
) -> list[str]:
    """Intersect API key stored permissions with the user's current live DB role & denies."""
    from app.core.authorization import _SERVER_ADMIN_ALLOWED_ACTIONS, _VIEWER_ALLOWED_ACTIONS

    if live_role == ROLE_OWNER:
        return list(raw_permissions)

    if live_role == ROLE_ADMIN:
        return [
            p
            for p in raw_permissions
            if p not in ("global:*", "global.*") and not p.startswith(("global.", "panel."))
        ]

    allowed_out: list[str] = []
    for p in raw_permissions:
        if p in (
            "admin:full",
            "global:*",
            "global.*",
            "server:*",
            "server:create",
            "server:delete",
            "user:read",
            "user:write",
            "user:delete",
            "settings:read",
            "settings:write",
        ) or p.startswith(("global.", "panel.", "user:", "settings:")):
            continue

        cap = _permission_capability(p)
        if cap and cap in live_denied:
            continue

        if live_role == ROLE_VIEWER:
            if p in live_effective_perms or p in _VIEWER_API_KEY_SCOPES:
                allowed_out.append(p)
            elif p.startswith("server."):
                action = normalize_server_action(p)
                if action in _VIEWER_ALLOWED_ACTIONS:
                    allowed_out.append(p)
        elif live_role == ROLE_SERVER_ADMIN:
            if p in live_effective_perms or p in _SERVER_ADMIN_API_KEY_SCOPES:
                allowed_out.append(p)
            elif p.startswith("server."):
                action = normalize_server_action(p)
                if action in _SERVER_ADMIN_ALLOWED_ACTIONS:
                    allowed_out.append(p)

    return allowed_out


def _is_api_key(token: str) -> bool:
    return token.startswith("onx_") or token.startswith("mcs_")


def _has_explicit_server_scope(user_perms: set[str]) -> bool:
    return any(
        p != "server:create"
        and p.startswith(("server.", "server:", "backup:", "plugin:", "exposure:"))
        for p in user_perms
    )


async def resolve_bearer_token(token: str, db: AsyncSession) -> dict:
    if _is_api_key(token):
        return await _resolve_api_key(token, db)
    claims = verify_access_token(token)
    user_id = str(claims.get("sub") or "")
    try:
        user_model = await load_user_model_with_roles(db, user_id)
    except OperationalError:
        # Pure middleware unit tests without initialized auth schema.
        return {
            "user_id": user_id,
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "scope": claims.get("scope", ""),
            "db_resolved": False,
        }

    if user_model is None:
        if await database_has_users(db):
            from app.core.exceptions import AuthenticationError

            raise AuthenticationError("User account not found")
        # Empty `users` table (e.g. stateless CI / unit tests with synthetic JWTs).
        return {
            "user_id": user_id,
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "scope": claims.get("scope", ""),
            "db_resolved": False,
        }

    if not user_model.is_active:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("Account is deactivated")

    ctx = await load_user_auth_context(db, user_model)
    ctx["auth_type"] = "jwt"
    return ctx


async def _resolve_api_key(token: str, db: AsyncSession) -> dict:
    key_hash = hash_api_key(token)
    stmt = select(ApiKeyModel).where(ApiKeyModel.key_hash == key_hash)
    result = await db.execute(stmt)
    api_key_model = result.scalar_one_or_none()
    if api_key_model is None:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("Invalid API key")
    if api_key_model.is_revoked:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("API key is revoked")
    if api_key_model.expires_at is not None:
        expires_at = (
            api_key_model.expires_at.replace(tzinfo=UTC)
            if api_key_model.expires_at.tzinfo is None
            else api_key_model.expires_at.astimezone(UTC)
        )
        if expires_at < datetime.now(UTC):
            from app.core.exceptions import AuthenticationError

            raise AuthenticationError("API key has expired")

    user_model = await load_user_model_with_roles(db, api_key_model.user_id)
    if user_model is None:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("API key owner not found")
    if not user_model.is_active:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("Account is deactivated")

    live_ctx = await load_user_auth_context(db, user_model)

    perms_str = api_key_model.permissions or ""
    raw_permissions = [p.strip() for p in perms_str.split(",") if p.strip()]
    live_role = live_ctx["global_role"]
    is_db_owner = live_role == ROLE_OWNER
    is_db_admin_or_owner = live_role in (ROLE_OWNER, ROLE_ADMIN)
    live_denied = set(live_ctx["denied_permissions"])
    live_effective = set(live_ctx["permissions"])

    filtered_permissions = _intersect_api_key_permissions(
        raw_permissions,
        live_role=live_role,
        live_denied=live_denied,
        live_effective_perms=live_effective,
    )
    perm_set = set(filtered_permissions)
    # Only honor Owner capability for API keys held by a live DB Owner AND explicitly scoped
    # with global:* / global.* (so an Owner's read-only API key cannot access Owner host routes).
    is_owner_key = is_db_owner and bool(perm_set & {"global:*", "global.*"})
    had_explicit_scope = bool(raw_permissions)

    return {
        "user_id": user_model.id,
        "username": user_model.username,
        "display_name": user_model.display_name,
        "email": user_model.email,
        "is_active": True,
        "roles": [],
        "global_role": live_role,
        "permissions": filtered_permissions,
        "denied_permissions": [] if is_db_admin_or_owner else live_ctx["denied_permissions"],
        "all_servers_access": (
            False
            if (_has_explicit_server_scope(perm_set) or (had_explicit_scope and not perm_set))
            else live_ctx["all_servers_access"]
        ),
        "server_memberships": live_ctx["server_memberships"],
        "owned_server_ids": live_ctx["owned_server_ids"],
        "is_owner_db": is_owner_key,
        "api_key_had_explicit_scope": had_explicit_scope and (
            _has_explicit_server_scope(set(raw_permissions)) or not perm_set
        ),
        "scope": ",".join(filtered_permissions),
        "auth_type": "api_key",
        "db_resolved": True,
    }
