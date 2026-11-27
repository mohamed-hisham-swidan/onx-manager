"""Shared RBAC v2 user access policy helpers for create/update/invite workflows."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import (
    CANONICAL_ROLE_PERMISSIONS,
    CANONICAL_ROLES,
    ROLE_ADMIN,
    ROLE_OWNER,
    ROLE_SERVER_ADMIN,
    ROLE_VIEWER,
    load_user_auth_context,
    load_user_model_with_roles,
    normalize_capability_key,
)
from app.core.exceptions import ConflictError, InvalidValueError, PermissionDenied
from app.modules.auth.domain.aggregate import Role, User
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerMembershipRepository
from app.modules.shared.value_objects import Permission, RoleId


def canonical_role_permissions_objects(role_name: str) -> list[Permission]:
    """Build Permission value objects for a canonical role name."""
    perms: list[Permission] = []
    for raw in CANONICAL_ROLE_PERMISSIONS.get(role_name, []):
        if ":" in raw:
            res, act = raw.split(":", 1)
            perms.append(Permission(res, act))
    return perms


async def ensure_canonical_role(user_repo: SQLUserRepository, role_name: str) -> Role:
    """Fetch canonical role row, seeding or updating its permissions to RBAC v2 defaults."""
    norm = role_name.strip().lower()
    if norm not in CANONICAL_ROLES:
        raise InvalidValueError(
            "role",
            role_name,
            "Role must be owner, admin, server_admin, or viewer",
        )
    existing = await user_repo.get_role_by_name(norm)
    expected_perms = canonical_role_permissions_objects(norm)
    expected_strs = sorted(str(p) for p in expected_perms)
    if existing is None:
        role = Role(
            role_id=RoleId(uuid.uuid4().hex),
            name=norm,
            permissions=expected_perms,
            description=f"Canonical {norm} role",
        )
        await user_repo.save_role(role)
        return role

    current_strs = sorted(str(p) for p in existing.permissions)
    if current_strs != expected_strs:
        updated = Role(
            role_id=existing.role_id,
            name=norm,
            permissions=expected_perms,
            description=existing.description or f"Canonical {norm} role",
        )
        await user_repo.save_role(updated)
        return updated
    return existing


def validate_denied_capabilities(raw_keys: Iterable[str] | None) -> list[str]:
    """Validate and canonicalize UI capability deny toggle keys."""
    if not raw_keys:
        return []
    validated: list[str] = []
    for raw in raw_keys:
        cap = normalize_capability_key(str(raw))
        if cap is None:
            raise InvalidValueError(
                "denied_permissions",
                raw,
                f"Unsupported capability permission toggle: {raw}",
            )
        if cap not in validated:
            validated.append(cap)
    return validated


def resolve_invite_policy(
    *,
    role: str | None = None,
    global_role: str | None = None,
    server_role: str | None = None,
    server_id: str | None = None,
    server_ids: Iterable[str] | None = None,
    all_servers_access: bool = False,
    denied_permissions: Iterable[str] | None = None,
) -> tuple[str, list[str], bool, list[str]]:
    """Normalize canonical + legacy invite fields into `(role, server_ids, all_servers, denied)`."""
    if role is not None and role.strip():
        target_role = role.strip().lower()
        if target_role not in CANONICAL_ROLES:
            raise InvalidValueError(
                "role",
                role,
                "Role must be owner, admin, server_admin, or viewer",
            )
    else:
        raw_global = (global_role or ROLE_VIEWER).strip().lower()
        if raw_global not in ("owner", "admin", "server_admin", "member", "viewer"):
            raise InvalidValueError(
                "global_role",
                global_role,
                "Global role must be owner, admin, server_admin, member, or viewer",
            )
        if server_role and server_role.strip():
            raw_srv = server_role.strip().lower()
            if raw_srv not in ("admin", "server_admin", "dev", "viewer"):
                raise InvalidValueError(
                    "server_role",
                    server_role,
                    "Server role must be admin, server_admin, dev, or viewer",
                )
        else:
            raw_srv = ""

        if raw_global in (ROLE_OWNER, ROLE_ADMIN, ROLE_SERVER_ADMIN):
            target_role = raw_global
        elif raw_global == ROLE_VIEWER:
            target_role = ROLE_VIEWER
        elif raw_srv in ("admin", "server_admin", "dev"):
            target_role = ROLE_SERVER_ADMIN
        else:
            target_role = ROLE_VIEWER

    merged_servers: list[str] = []
    for candidate in list(server_ids or ()) + ([server_id] if server_id else []):
        cleaned = str(candidate).strip()
        if cleaned and cleaned not in merged_servers:
            merged_servers.append(cleaned)

    normalized_denied = validate_denied_capabilities(denied_permissions)
    if target_role in (ROLE_OWNER, ROLE_ADMIN):
        return target_role, [], True, []
    return target_role, merged_servers, bool(all_servers_access), normalized_denied


async def apply_user_access_policy(
    session: AsyncSession,
    user_repo: SQLUserRepository,
    user: User,
    *,
    target_role: str,
    server_ids: Iterable[str] = (),
    all_servers_access: bool = False,
    denied_permissions: Iterable[str] = (),
    requester_roles: Iterable[str] | None = None,
    validate_servers_exist: bool = True,
) -> None:
    """Apply canonical RBAC v2 role, server memberships, and capability overrides atomically."""
    norm_role = (target_role or ROLE_VIEWER).strip().lower()
    if norm_role not in CANONICAL_ROLES:
        raise InvalidValueError(
            "role", target_role, "Role must be owner, admin, server_admin, or viewer"
        )

    currently_owner = any(r.name.lower() == ROLE_OWNER for r in user.roles)
    if requester_roles is not None:
        req_lower = {str(r).strip().lower() for r in requester_roles}
        if currently_owner and ROLE_OWNER not in req_lower:
            raise PermissionDenied("Only an instance Owner can modify an Owner account")
        if norm_role == ROLE_OWNER and ROLE_OWNER not in req_lower:
            raise PermissionDenied("Only an instance Owner can assign the Owner role")

    if currently_owner and norm_role != ROLE_OWNER:
        all_users = await user_repo.list()
        other_active_owners = [
            u
            for u in all_users
            if str(u.user_id) != str(user.user_id)
            and u.is_active
            and any(r.name.lower() == ROLE_OWNER for r in u.roles)
        ]
        if not other_active_owners:
            raise ConflictError("Cannot demote the last active instance owner")

    clean_denied = validate_denied_capabilities(denied_permissions)
    clean_servers = list(dict.fromkeys([str(s).strip() for s in server_ids if str(s).strip()]))
    if validate_servers_exist and clean_servers:
        rows = (
            await session.execute(
                select(ServerModel.id).where(ServerModel.id.in_(clean_servers))
            )
        ).scalars().all()
        existing_set = {str(sid) for sid in rows}
        missing = [sid for sid in clean_servers if sid not in existing_set]
        if missing:
            raise InvalidValueError("server_ids", missing[0], f"Server '{missing[0]}' not found")

    role_obj = await ensure_canonical_role(user_repo, norm_role)
    user.set_roles([role_obj])

    if norm_role in (ROLE_OWNER, ROLE_ADMIN):
        user.set_all_servers_access(True)
        user.set_denied_permissions([])
        effective_servers: list[str] = []
    else:
        user.set_all_servers_access(bool(all_servers_access))
        user.set_denied_permissions(clean_denied)
        effective_servers = clean_servers

    await user_repo.save(user)

    mem_repo = SQLServerMembershipRepository(session)
    mem_role = ROLE_SERVER_ADMIN if norm_role == ROLE_SERVER_ADMIN else ROLE_VIEWER
    await mem_repo.replace_memberships_for_user(
        str(user.user_id),
        effective_servers,
        mem_role,
    )

    if norm_role in (ROLE_SERVER_ADMIN, ROLE_VIEWER):
        owned_rows = (
            await session.execute(
                select(ServerModel).where(ServerModel.owner_id == str(user.user_id))
            )
        ).scalars().all()
        allowed_set = set(effective_servers)
        for srv in owned_rows:
            if not all_servers_access and str(srv.id) not in allowed_set:
                srv.owner_id = None
        await session.flush()


async def build_user_profile_dict(
    session: AsyncSession,
    user_id: str,
) -> dict[str, Any] | None:
    """Build complete user profile + live RBAC v2 access structure from DB."""
    model = await load_user_model_with_roles(session, user_id)
    if model is None:
        return None
    ctx = await load_user_auth_context(session, model)
    return {
        "user_id": ctx["user_id"],
        "username": ctx["username"],
        "email": ctx["email"],
        "display_name": ctx["display_name"],
        "is_active": ctx["is_active"],
        "roles": ctx["roles"],
        "global_role": ctx["global_role"],
        "permissions": ctx["permissions"],
        "denied_permissions": ctx["denied_permissions"],
        "all_servers_access": ctx["all_servers_access"],
        "assigned_server_ids": list(ctx["server_memberships"].keys()),
        "server_memberships": [
            {"server_id": sid, "role": role}
            for sid, role in ctx["server_memberships"].items()
        ],
        "owned_server_ids": ctx["owned_server_ids"],
        "created_at": model.created_at,
        "last_login_at": model.last_login_at,
    }
