#!/usr/bin/env python3
"""
Migration script: move legacy servers into the managed directory.

The Create flow used to accept an arbitrary ``install_dir``, storing it as
``root_path`` verbatim — allowing servers to live outside ``data/servers/``.

This script discovers every server whose ``root_path`` is OUTSIDE
``servers_data_dir``, copies its files into
``data/servers/{slug}-{uuid[:8]}/``, and updates the database.

Usage:
    python scripts/migrate_legacy_servers.py          # real run
    python scripts/migrate_legacy_servers.py --dry-run # preview only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
logger = logging.getLogger("migrate_legacy_servers")


def _slugify(text: str) -> str:
    import re

    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace("_", "-")
    text = re.sub(r"[\s-]+", "-", text)
    text = text.strip("-")
    return text or "server"


def server_dir_name(name: str, server_id: str) -> str:
    return f"{_slugify(name)}-{server_id[:8]}"


async def migrate(dry_run: bool = False) -> int:
    from app.core.config import AppSettings
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.fs import local_fs
    from app.modules.server.infrastructure.repository import SQLServerRepository

    settings = AppSettings()
    database.init(settings)
    data_dir = Path(settings.servers_data_dir).resolve()

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        servers = await repo.list()

    moved = 0
    skipped = 0

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)

        for server in servers:
            if server.deployment is None or not server.deployment.root_path:
                skipped += 1
                continue

            old_path = Path(server.deployment.root_path).resolve()

            try:
                old_path.relative_to(data_dir)
                logger.debug("Skip %s — already under %s", server.name, data_dir)
                skipped += 1
                continue
            except ValueError:
                pass

            sid = str(server.id)
            new_name = server_dir_name(server.name, sid)
            new_path = (data_dir / new_name).resolve()

            logger.info(
                "Server  %-30s  id=%s",
                server.name,
                sid,
            )
            logger.info("  Old:  %s", old_path)
            logger.info("  New:  %s", new_path)

            if new_path.exists():
                logger.warning("  SKIP — target already exists: %s", new_path)
                skipped += 1
                continue

            if not old_path.exists():
                logger.warning("  SKIP — old path does not exist: %s", old_path)
                skipped += 1
                continue

            if not dry_run:
                local_fs.ensure_dir(str(new_path.parent))
                local_fs.copy_dir(str(old_path), str(new_path))
                server.deployment.root_path = str(new_path)
                await repo.save(server)
                await session.commit()
                logger.info("  MOVED ✅")
            else:
                logger.info("  WOULD MOVE (dry-run)")

            moved += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("Done: %d moved, %d skipped", moved, skipped)
    if dry_run and moved > 0:
        logger.info("Re-run without --dry-run to apply.")
    return 0 if dry_run or moved > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy servers into managed directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    import asyncio

    return asyncio.run(migrate(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
