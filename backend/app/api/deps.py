from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_utils import resolve_bearer_token
from app.core.command_bus import CommandBus
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
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
