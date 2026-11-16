import asyncio
import os
import sys
from logging.config import fileConfig
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

import app.modules.auth.infrastructure.audit  # noqa
import app.modules.auth.infrastructure.models  # noqa
import app.modules.backup.infrastructure.models  # noqa
import app.modules.event_store.models  # noqa
import app.modules.exposure.infrastructure.models  # noqa
import app.modules.health.infrastructure.models  # noqa
import app.modules.monitoring.infrastructure.models  # noqa
import app.modules.plugin.infrastructure.models  # noqa
import app.modules.server.infrastructure.models  # noqa
import app.modules.versioning.infrastructure.models  # noqa
from alembic import context
from app.core.persistence.base import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Resolve database URL: ONX_DATABASE_URL / MCS_DATABASE_URL env var overrides alembic.ini
_raw_db_url = (
    os.environ.get("ONX_DATABASE_URL")
    or os.environ.get("MCS_DATABASE_URL")
    or config.get_main_option("sqlalchemy.url")
    or "sqlite+aiosqlite:///data/onx.db"
)

if "sqlite" in _raw_db_url.lower() and ":memory:" not in _raw_db_url:
    from pathlib import Path
    _prefix, _, _raw_path = _raw_db_url.partition(":///")
    if not _raw_path:
        _prefix, _, _raw_path = _raw_db_url.partition("://")
    _p = Path(_raw_path)
    if not _p.is_absolute():
        _backend_dir = Path(__file__).resolve().parents[1]
        _p = (_backend_dir / _p).resolve()
    _posix_path = _p.as_posix()
    _db_url = f"{_prefix}:///{_posix_path}"
else:
    _db_url = _raw_db_url

_db_label = _db_url.rsplit("/", 1)[-1] if "/" in _db_url else _db_url
print(f"Alembic target DB: {_db_url}  ({_db_label})", file=sys.stderr)


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(_db_url)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
