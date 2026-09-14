from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import AppSettings


class DatabaseEngine:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._session_factory

    def init(self, settings: AppSettings | None = None) -> None:
        if settings:
            self._settings = settings

        kw: dict[str, Any] = {
            "echo": self._settings.database_echo,
        }
        if "sqlite" not in self._settings.database_url:
            kw["pool_size"] = 20
            kw["max_overflow"] = 10
            kw["pool_pre_ping"] = True
            self._engine = create_async_engine(self._settings.database_url, **kw)
        else:
            import shutil
            from pathlib import Path

            from sqlalchemy.engine.url import make_url

            from app.core.identity import IDENTITY

            kw["connect_args"] = {"timeout": 30.0, "check_same_thread": False}
            kw["pool_pre_ping"] = True
            effective_url = self._settings.database_url
            try:
                parsed_url = make_url(self._settings.database_url)
                if parsed_url.database and parsed_url.database != ":memory:":
                    target_path = Path(parsed_url.database)
                    if not target_path.is_absolute():
                        backend_dir = Path(__file__).resolve().parents[3]
                        target_path = (backend_dir / target_path).resolve()
                    db_dir = target_path.parent
                    db_dir.mkdir(parents=True, exist_ok=True)
                    if not target_path.is_file() or target_path.stat().st_size == 0:
                        legacy_candidates = [
                            db_dir / IDENTITY.db_filename_legacy,
                            db_dir.parent / IDENTITY.db_filename_legacy,
                        ]
                        for legacy_path in legacy_candidates:
                            if legacy_path.is_file() and legacy_path.stat().st_size > 0:
                                shutil.copy2(str(legacy_path), str(target_path))
                                break
                    posix_path = target_path.as_posix()
                    effective_url = f"{parsed_url.drivername}:///{posix_path}"
            except Exception:
                pass

            self._engine = create_async_engine(effective_url, **kw)

        if "sqlite" in self._settings.database_url:
            from sqlalchemy import event

            @event.listens_for(self._engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=30000")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                except Exception:
                    pass
                finally:
                    cursor.close()

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized")
        async with self._session_factory() as session:
            yield session


database = DatabaseEngine()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in database.get_session():
        yield session
