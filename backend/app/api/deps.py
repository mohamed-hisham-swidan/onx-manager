import logging

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_utils import resolve_bearer_token
from app.core.authorization import (
    authorize_server_action,
    is_admin_or_owner_context,
    is_owner_context,
    normalize_denied_permissions,
)
from app.core.command_bus import CommandBus
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
from app.core.exceptions import PermissionDenied
from app.core.persistence.db import get_db
from app.core.query_bus import QueryBus
from app.modules.storage.base import StorageBackend
from app.modules.storage.encryption import BackupEncryption, build_backup_encryption
from app.modules.storage.local import LocalStorage
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

_command_bus: CommandBus | None = None
_query_bus: QueryBus | None = None
_event_bus: EventBus | None = None
_storage_backend: StorageBackend | None = None
_backup_encryption: BackupEncryption | None = None


def build_storage_backend(settings: AppSettings) -> StorageBackend:
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        return LocalStorage(settings.backup_storage_path)
    if backend == "s3":
        return S3Storage(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix or "",
            endpoint_url=settings.s3_endpoint_url or None,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id or None,
            secret_access_key=settings.s3_secret_access_key or None,
        )
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")


def init_storage(settings: AppSettings | None = None) -> None:
    global _storage_backend, _backup_encryption
    settings = settings or ConfigFactory.global_settings()
    _storage_backend = build_storage_backend(settings)
    _backup_encryption = build_backup_encryption(settings.backup_encryption_key_path)


def init_buses(command_bus: CommandBus, query_bus: QueryBus, event_bus: EventBus) -> None:
    global _command_bus, _query_bus, _event_bus
    _command_bus = command_bus
    _query_bus = query_bus
    _event_bus = event_bus


async def get_command_bus() -> CommandBus:
    if _command_bus is None:
        raise RuntimeError("CommandBus not initialized")
    return _command_bus


async def get_query_bus() -> QueryBus:
    if _query_bus is None:
        raise RuntimeError("QueryBus not initialized")
    return _query_bus


async def get_event_bus() -> EventBus:
    if _event_bus is None:
        raise RuntimeError("EventBus not initialized")
    return _event_bus


def get_optional_event_bus() -> EventBus | None:
    return _event_bus


async def get_current_user(
    request: Request = None,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    authorization: str = Header(default=""),
) -> dict:
    if not authorization:
        if request is not None:
            from app.core.local_auth import resolve_local_auto_auth

            client_host = request.client.host if request.client else None
            local_claims = await resolve_local_auto_auth(client_host, request.headers, db)
            if local_claims is not None:
                return local_claims
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    try:
        return await resolve_bearer_token(token, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error resolving bearer token: %s", e, exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed") from e


def require_permission(permission: str):
    """FastAPI dependency factory: require a permission from the caller's token claims.

    `admin:full` always satisfies the check. Missing or expired tokens are
    rejected by the underlying `get_current_user` (401); an authenticated
    caller without the required permission gets a `PermissionDenied` (403).
    """

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
        permissions = current_user.get("permissions", [])
        if "admin:full" not in permissions and permission not in permissions:
            raise PermissionDenied(f"missing required permission: {permission}")
        return current_user

    return _check


def require_marketplace_access(permission: str = "plugin:manage"):
    """FastAPI dependency factory: allow plugin admins OR assigned server_admins without plugins denied."""

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
        permissions = current_user.get("permissions", [])
        if "admin:full" in permissions or permission in permissions:
            return current_user
        global_role = str(current_user.get("global_role") or "").lower()
        denied = set(normalize_denied_permissions(current_user.get("denied_permissions", [])))
        has_scope = (
            bool(current_user.get("all_servers_access"))
            or bool(current_user.get("server_memberships"))
            or bool(current_user.get("owned_server_ids"))
        )
        if global_role == "server_admin" and "plugins" not in denied and has_scope:
            return current_user
        raise PermissionDenied(f"missing required permission: {permission}")

    return _check


def require_admin_or_owner(permission: str = "admin:full"):
    """FastAPI dependency factory: require Owner or Admin role."""

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
        if is_admin_or_owner_context(current_user):
            return current_user
        perms = current_user.get("permissions", [])
        if (
            permission != "admin:full"
            and permission in perms
            and (
                not current_user.get("db_resolved")
                or current_user.get("auth_type") == "api_key"
            )
        ):
            return current_user
        raise PermissionDenied(f"missing required permission: {permission}")

    return _check


def _has_global_wildcard(permissions: set[str] | list[str]) -> bool:
    return "global.*" in permissions or "global:*" in permissions


def _api_key_has_explicit_server_scope(user_perms: set[str]) -> bool:
    """Return True when an API key explicitly declares server-action scopes.

    Keys with no server-action scopes (e.g. unscoped personal keys or keys carrying
    only fleet-level permissions like ``settings:read`` / ``server:create``) defer to
    the user's live server ownership and membership roles. Keys that explicitly declare
    server-action scopes (e.g. ``server:read`` or ``server.{id}.view``) are strictly
    capped to those declared actions even when the caller owns the server.
    """
    return any(
        p != "server:create"
        and p.startswith(("server.", "server:", "backup:", "plugin:", "exposure:"))
        for p in user_perms
    )


def _api_key_satisfies_server_actions(
    user_perms: set[str], server_id: str, required_permissions: tuple[str, ...]
) -> bool:
    """Ensure an API key explicitly holds at least one required server scope."""
    if not user_perms:
        return False
    if (
        "admin:full" in user_perms
        or _has_global_wildcard(user_perms)
        or "global.servers.manage" in user_perms
        or "server:*" in user_perms
        or f"server.{server_id}.*" in user_perms
        or "server.{id}.*" in user_perms
    ):
        return True

    action_aliases: dict[str, set[str]] = {
        "view": {"server:read", "server:write"},
        "write": {"server:write"},
        "power": {"server:write", "server:start", "server:stop", "server:restart"},
        "console": {"server:write"},
        "console.view": {"server:read", "server:write"},
        "files": {"server:write"},
        "files.read": {"server:read", "server:write"},
        "files.logs": {"server:read", "server:write"},
        "players": {"server:read", "server:write"},
        "settings": {"server:write"},
        "backup": {
            "backup:read",
            "backup:create",
            "backup:restore",
            "backup:delete",
            "server:write",
        },
        "backups": {
            "backup:read",
            "backup:create",
            "backup:restore",
            "backup:delete",
            "server:write",
        },
        "backups.view": {"backup:read", "server:read"},
        "plugins": {"plugin:read", "plugin:install", "plugin:manage", "server:write"},
        "plugins.view": {"plugin:read", "plugin:manage", "server:read"},
        "versioning": {"server:version:commit", "server.versioning.manage", "server:write"},
        "versioning.view": {"server:version:read", "server.versioning.manage", "server:read"},
        "delete": {"server:delete"},
        "exposure.view": {"exposure:read", "server:read"},
        "exposure": {"exposure:manage", "exposure:write", "server:write"},
    }
    for perm in required_permissions:
        if perm in user_perms:
            return True
        norm_action = (
            perm.replace("server.{id}.", "")
            .replace("server.", "")
            .replace("server:", "")
            .strip()
        )
        candidates = {
            f"server.{{id}}.{norm_action}",
            f"server.{server_id}.{norm_action}",
            f"server:{norm_action}",
            *action_aliases.get(norm_action, set()),
        }
        if user_perms & candidates:
            return True
    return False


def require_owner():
    """FastAPI dependency factory: require live instance Owner authority."""

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
        if not is_owner_context(current_user):
            raise PermissionDenied("Only the instance Owner can perform this action")
        return current_user

    return _check


SERVER_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "server.{id}.*",
        "server.{id}.view",
        "server.{id}.write",
        "server.{id}.power",
        "server.{id}.console",
        "server.{id}.console.view",
        "server.{id}.files",
        "server.{id}.files.read",
        "server.{id}.files.logs",
        "server.{id}.backup",
        "server.{id}.backups",
        "server.{id}.backups.view",
        "server.{id}.players",
        "server.{id}.settings",
        "server.{id}.plugins",
        "server.{id}.plugins.view",
        "server.{id}.exposure",
        "server.{id}.exposure.view",
        "server.{id}.versioning",
        "server.{id}.versioning.view",
    },
    "server_admin": {
        "server.{id}.view",
        "server.{id}.write",
        "server.{id}.power",
        "server.{id}.console",
        "server.{id}.console.view",
        "server.{id}.files",
        "server.{id}.files.read",
        "server.{id}.files.logs",
        "server.{id}.backup",
        "server.{id}.backups",
        "server.{id}.backups.view",
        "server.{id}.players",
        "server.{id}.settings",
        "server.{id}.plugins",
        "server.{id}.plugins.view",
        "server.{id}.exposure",
        "server.{id}.exposure.view",
        "server.{id}.versioning",
        "server.{id}.versioning.view",
    },
    "dev": {
        "server.{id}.view",
        "server.{id}.write",
        "server.{id}.power",
        "server.{id}.console",
        "server.{id}.console.view",
        "server.{id}.files",
        "server.{id}.files.read",
        "server.{id}.files.logs",
        "server.{id}.backup",
        "server.{id}.backups",
        "server.{id}.backups.view",
        "server.{id}.players",
        "server.{id}.settings",
        "server.{id}.plugins",
        "server.{id}.plugins.view",
        "server.{id}.exposure.view",
        "server.{id}.versioning",
        "server.{id}.versioning.view",
    },
    "viewer": {
        "server.{id}.view",
        "server.{id}.players",
        "server.{id}.console.view",
        "server.{id}.files.logs",
        "server.{id}.backups.view",
        "server.{id}.plugins.view",
        "server.{id}.exposure.view",
        "server.{id}.versioning.view",
    },
}


def require_server_permission(*permissions: str):
    """FastAPI dependency factory: enforce RBAC v2 server-scoped permission."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        user_perms = set(current_user.get("permissions", []))

        path_id = request.path_params.get("server_id")
        query_id = request.query_params.get("server_id")
        body_id = None
        headers = getattr(request, "headers", None) or {}
        content_type = str(headers.get("content-type", "")).lower()
        if "application/json" in content_type and "multipart/form-data" not in content_type:
            try:
                body_json = await request.json()
                if isinstance(body_json, dict):
                    body_id = body_json.get("server_id")
            except Exception:
                pass

        found_ids = {i for i in (path_id, query_id, body_id) if i is not None}
        if len(found_ids) > 1:
            raise HTTPException(status_code=400, detail="Conflicting server_id parameters")

        server_id = found_ids.pop() if found_ids else None

        if not server_id:
            raise HTTPException(status_code=400, detail="Missing server_id parameter")

        if (
            current_user.get("auth_type") == "api_key"
            and (
                current_user.get("api_key_had_explicit_scope")
                or _api_key_has_explicit_server_scope(user_perms)
            )
            and not _api_key_satisfies_server_actions(user_perms, str(server_id), permissions)
        ):
            raise PermissionDenied("API key lacks required permission")

        from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel

        stmt = select(ServerModel).where(ServerModel.id == server_id)
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid user authentication")

        auth_ctx = current_user
        if not current_user.get("db_resolved"):
            mem_stmt = select(ServerMembershipModel).where(
                ServerMembershipModel.server_id == server_id,
                ServerMembershipModel.user_id == user_id,
            )
            mem_row = (await db.execute(mem_stmt)).scalar_one_or_none()
            auth_ctx = {
                **current_user,
                "server_memberships": {str(server_id): mem_row.role} if mem_row else {},
                "owned_server_ids": (
                    [str(server_id)] if server.owner_id == user_id else []
                ),
            }

        for perm in permissions:
            if authorize_server_action(
                auth_ctx,
                str(server_id),
                perm,
                server_owner_id=server.owner_id,
            ):
                return current_user

        raise PermissionDenied("Permission denied")

    return _check


def require_exposure_grant(permission: str):
    """FastAPI dependency factory: unified server-scoped exposure permission check."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        user_perms = set(current_user.get("permissions", []))

        path_id = request.path_params.get("server_id")
        if not path_id:
            raise HTTPException(status_code=400, detail="Missing server_id parameter")

        if (
            current_user.get("auth_type") == "api_key"
            and (
                current_user.get("api_key_had_explicit_scope")
                or _api_key_has_explicit_server_scope(user_perms)
            )
            and not _api_key_satisfies_server_actions(user_perms, str(path_id), (permission,))
        ):
            raise PermissionDenied("API key lacks required exposure permission")

        from app.modules.server.infrastructure.models import ServerModel

        stmt = select(ServerModel).where(ServerModel.id == path_id)
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid user authentication")

        denied = set(normalize_denied_permissions(current_user.get("denied_permissions", [])))
        if "exposure" in denied:
            raise PermissionDenied("Exposure capability permission is disabled")

        manage = permission.endswith(".exposure") and not permission.endswith(".exposure.view")
        primary_role = str(current_user.get("global_role") or "").lower()
        if primary_role == "viewer" and manage:
            raise PermissionDenied("Viewers lack permission to modify server exposure")

        if authorize_server_action(
            current_user,
            str(path_id),
            permission,
            server_owner_id=server.owner_id,
        ):
            return current_user

        from app.modules.exposure.infrastructure.models import ServerExposureGrantModel

        grant_stmt = select(ServerExposureGrantModel).where(
            ServerExposureGrantModel.server_id == path_id,
            ServerExposureGrantModel.user_id == user_id,
        )
        grant_result = await db.execute(grant_stmt)
        grant = grant_result.scalar_one_or_none()
        if grant is None:
            raise PermissionDenied("No exposure permission for this server")

        if manage and not grant.can_manage:
            raise PermissionDenied("Exposure manage permission denied")
        if not manage and not (grant.can_manage or grant.can_view):
            raise PermissionDenied("Exposure view permission denied")

        return current_user

    return _check


_BACKUP_PERM_ACTIONS: dict[str, str] = {
    "backup:read": "backups.view",
    "backup:create": "backups",
    "backup:restore": "backups",
    "backup:delete": "backups",
}


async def _load_auth_ctx_for_server(
    db: AsyncSession, current_user: dict, server_id: str
) -> tuple[dict, str | None]:
    """Ensure server exists (404) and enrich non-DB-resolved contexts with live membership."""
    from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel

    stmt = select(ServerModel).where(ServerModel.id == server_id)
    server = (await db.execute(stmt)).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    if current_user.get("db_resolved"):
        return current_user, server.owner_id

    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user authentication")
    mem_stmt = select(ServerMembershipModel).where(
        ServerMembershipModel.server_id == server_id,
        ServerMembershipModel.user_id == user_id,
    )
    mem_row = (await db.execute(mem_stmt)).scalar_one_or_none()
    enriched = {
        **current_user,
        "server_memberships": {server_id: mem_row.role} if mem_row else {},
        "owned_server_ids": [server_id] if server.owner_id == user_id else [],
    }
    return enriched, server.owner_id


def require_backup_permission(permission: str):
    """FastAPI dependency factory: enforce RBAC v2 backup authorization via backup_id."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        action = _BACKUP_PERM_ACTIONS.get(permission, "backups")
        backup_id = request.path_params.get("backup_id")
        if not backup_id:
            if is_admin_or_owner_context(current_user):
                return current_user
            raise HTTPException(status_code=400, detail="Missing backup_id parameter")

        from app.modules.backup.infrastructure.models import BackupJobModel

        backup_row = (
            await db.execute(select(BackupJobModel).where(BackupJobModel.id == backup_id))
        ).scalar_one_or_none()
        if backup_row is None:
            raise HTTPException(status_code=404, detail="Backup not found")

        user_perms = set(current_user.get("permissions", []))
        if (
            current_user.get("auth_type") == "api_key"
            and (
                current_user.get("api_key_had_explicit_scope")
                or _api_key_has_explicit_server_scope(user_perms)
            )
            and not _api_key_satisfies_server_actions(
                user_perms, str(backup_row.server_id), (action,)
            )
            and permission not in user_perms
        ):
            raise PermissionDenied("API key lacks required backup permission")

        if is_admin_or_owner_context(current_user):
            return current_user

        auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
            db, current_user, str(backup_row.server_id)
        )
        if not authorize_server_action(
            auth_ctx,
            str(backup_row.server_id),
            action,
            server_owner_id=server_owner_id,
        ):
            raise PermissionDenied("Permission denied")
        return current_user

    return _check


def require_files_read_permission(permission: str = "server.{id}.files.read"):
    """FastAPI dependency factory: allow ?scope=logs via files.logs, else require files.read."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        server_id = request.path_params.get("server_id")
        if not server_id:
            raise HTTPException(status_code=400, detail="Missing server_id parameter")

        scope = str(request.query_params.get("scope", "") or "").strip().lower()
        target_action = "files.logs" if scope == "logs" else "files.read"
        user_perms = set(current_user.get("permissions", []))
        if (
            current_user.get("auth_type") == "api_key"
            and (
                current_user.get("api_key_had_explicit_scope")
                or _api_key_has_explicit_server_scope(user_perms)
            )
            and not _api_key_satisfies_server_actions(
                user_perms, str(server_id), (target_action, permission)
            )
        ):
            raise PermissionDenied("API key lacks required file permission")

        auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
            db, current_user, str(server_id)
        )
        if not authorize_server_action(
            auth_ctx,
            str(server_id),
            target_action,
            server_owner_id=server_owner_id,
        ):
            raise PermissionDenied("Permission denied")
        return current_user

    return _check


def require_versioning_permission(permission: str):
    """FastAPI dependency factory: enforce RBAC v2 server-scoped versioning/conversion checks."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        action = "versioning.view" if permission == "server:version:read" else "versioning"
        server_id = request.path_params.get("server_id")
        if not server_id:
            if is_admin_or_owner_context(current_user):
                return current_user
            perms = set(current_user.get("permissions", []))
            if permission in perms:
                return current_user
            raise PermissionDenied(f"missing required permission: {permission}")

        user_perms = set(current_user.get("permissions", []))
        if (
            current_user.get("auth_type") == "api_key"
            and (
                current_user.get("api_key_had_explicit_scope")
                or _api_key_has_explicit_server_scope(user_perms)
            )
            and permission not in user_perms
            and not _api_key_satisfies_server_actions(user_perms, str(server_id), (action,))
        ):
            raise PermissionDenied(f"missing required permission: {permission}")

        if is_admin_or_owner_context(current_user):
            return current_user

        auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
            db, current_user, str(server_id)
        )
        if authorize_server_action(
            auth_ctx,
            str(server_id),
            action,
            server_owner_id=server_owner_id,
        ):
            return current_user

        raise PermissionDenied("Permission denied")

    return _check


def require_alert_rule_permission(permission: str = "settings:write"):
    """FastAPI dependency factory: server-scoped or admin alert rule management."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        rule_id = request.path_params.get("alert_rule_id")
        if rule_id:
            from app.modules.monitoring.infrastructure.models import AlertRuleModel

            row = (
                await db.execute(select(AlertRuleModel).where(AlertRuleModel.id == rule_id))
            ).scalar_one_or_none()
            if row is not None and row.server_id:
                auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
                    db, current_user, str(row.server_id)
                )
                if authorize_server_action(
                    auth_ctx,
                    str(row.server_id),
                    "settings",
                    server_owner_id=server_owner_id,
                ):
                    return current_user
        raise PermissionDenied(f"missing required permission: {permission}")

    return _check


def require_schedule_permission(permission: str = "settings:write"):
    """FastAPI dependency factory: server-scoped backup schedule mutation or admin/owner."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        schedule_id = request.path_params.get("schedule_id")
        target_server_id: str | None = None
        if schedule_id:
            import json as _json

            from app.tasks.scheduler import CronJobModel

            row = await db.get(CronJobModel, schedule_id)
            if row is not None and row.params_json:
                try:
                    parsed = _json.loads(row.params_json)
                    if isinstance(parsed, dict) and parsed.get("server_id"):
                        target_server_id = str(parsed["server_id"])
                except Exception:
                    target_server_id = None
        else:
            try:
                body = await request.json()
                if isinstance(body, dict) and isinstance(body.get("params"), dict):
                    sid = body["params"].get("server_id")
                    if sid:
                        target_server_id = str(sid)
            except Exception:
                target_server_id = None

        if target_server_id:
            auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
                db, current_user, target_server_id
            )
            if authorize_server_action(
                auth_ctx,
                target_server_id,
                "backups",
                server_owner_id=server_owner_id,
            ):
                return current_user
        raise PermissionDenied(f"missing required permission: {permission}")

    return _check


def require_operation_permission(permission: str):
    """FastAPI dependency factory: server-scoped or admin operation access."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: dict = Depends(get_current_user),  # noqa: B008
    ) -> dict:
        if is_admin_or_owner_context(current_user):
            return current_user

        is_read = permission == "server:read"
        action = "view" if is_read else "settings"
        op_id = request.path_params.get("operation_id")
        target_type: str | None = None
        target_id: str | None = None

        if op_id:
            from app.modules.operations.infrastructure.models import OperationModel

            row = await db.get(OperationModel, op_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Operation not found")
            target_type = str(row.target_type or "")
            target_id = str(row.target_id or "")
        elif request.method == "POST":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target_type = str(body.get("target_type") or "")
                    target_id = str(body.get("target_id") or "")
            except Exception:
                pass
        else:
            # Collection GET /operations uses router filtering after query
            return current_user

        if target_type == "server" and target_id:
            auth_ctx, server_owner_id = await _load_auth_ctx_for_server(
                db, current_user, target_id
            )
            if authorize_server_action(
                auth_ctx,
                target_id,
                action,
                server_owner_id=server_owner_id,
            ):
                return current_user

        raise PermissionDenied(f"missing required permission: {permission}")

    return _check


async def get_storage_backend() -> StorageBackend:
    if _storage_backend is None:
        raise RuntimeError("StorageBackend not initialized")
    return _storage_backend


async def get_backup_encryption() -> BackupEncryption:
    if _backup_encryption is None:
        raise RuntimeError("BackupEncryption not initialized")
    return _backup_encryption


async def get_settings() -> AppSettings:
    return ConfigFactory.global_settings()
