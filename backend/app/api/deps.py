from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_utils import resolve_bearer_token
from app.core.command_bus import CommandBus
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
from app.core.exceptions import PermissionDenied
from app.core.query_bus import QueryBus
from app.core.persistence.db import get_db
from app.modules.storage.base import StorageBackend
from app.modules.storage.encryption import BackupEncryption, build_backup_encryption
from app.modules.storage.local import LocalStorage
from app.modules.storage.s3 import S3Storage

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


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(default=""),
) -> dict:
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
        raise HTTPException(status_code=401, detail=str(e))


def require_permission(permission: str):
    """FastAPI dependency factory: require a permission from the caller's token claims.

    `admin:full` always satisfies the check. Missing or expired tokens are
    rejected by the underlying `get_current_user` (401); an authenticated
    caller without the required permission gets a `PermissionDenied` (403).
    """

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        permissions = current_user.get("permissions", [])
        if "admin:full" not in permissions and permission not in permissions:
            raise PermissionDenied(f"missing required permission: {permission}")
        return current_user

    return _check


def require_owner():
    """FastAPI dependency factory: require Owner role or global.* permission.

    `admin:full` alone is NOT sufficient — the access-mode operation is
    deliberately Owner-only. The call is satisfied only by the `owner` role
    or a `global.*` permission claim (the Owner receives both at bootstrap).
    """

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        roles = current_user.get("roles", [])
        permissions = current_user.get("permissions", [])
        if "owner" not in roles and "global.*" not in permissions:
            raise PermissionDenied("Only the instance Owner can perform this action")
        return current_user

    return _check


SERVER_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "server.{id}.*",
        "server.{id}.view",
        "server.{id}.power",
        "server.{id}.console",
        "server.{id}.files",
        "server.{id}.backup",
        "server.{id}.players",
        "server.{id}.settings",
    },
    "dev": {
        "server.{id}.view",
        "server.{id}.power",
        "server.{id}.console",
        "server.{id}.files",
        "server.{id}.backup",
        "server.{id}.players",
        "server.{id}.settings",
    },
    "viewer": {
        "server.{id}.view",
    },
}


def require_server_permission(*permissions: str):
    """FastAPI dependency factory: require a server-scoped permission for target server_id.

    Accepts one or more required permission nodes (e.g. 'server.{id}.files', 'server.{id}.view').
    Access is granted if the caller satisfies ANY of the specified permission nodes.
    Short-circuits if caller has global admin rights ('admin:full', 'global.*', 'global.servers.manage').
    Otherwise, extracts `server_id` from request path/query, verifies server existence (404),
    and checks live DB for server ownership or valid ServerMembership role (403).
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        user_perms = set(current_user.get("permissions", []))
        if "admin:full" in user_perms or "global.*" in user_perms or "global.servers.manage" in user_perms:
            return current_user

        path_id = request.path_params.get("server_id")
        query_id = request.query_params.get("server_id")
        body_id = None
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


        from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel

        stmt = select(ServerModel).where(ServerModel.id == server_id)
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid user authentication")

        if server.owner_id and server.owner_id == user_id:
            return current_user

        mem_stmt = select(ServerMembershipModel).where(
            ServerMembershipModel.server_id == server_id,
            ServerMembershipModel.user_id == user_id,
        )
        mem_result = await db.execute(mem_stmt)
        membership = mem_result.scalar_one_or_none()
        if membership is None:
            raise HTTPException(status_code=403, detail="Permission denied")

        role_perms = SERVER_ROLE_PERMISSIONS.get(membership.role, set())
        if "server.{id}.*" in role_perms:
            return current_user

        for perm in permissions:
            norm_action = perm.replace("server.{id}.", "").replace("server.", "").replace("server:", "").strip()
            required_node = f"server.{{id}}.{norm_action}"
            if required_node in role_perms:
                return current_user

        raise HTTPException(status_code=403, detail="Permission denied")

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
