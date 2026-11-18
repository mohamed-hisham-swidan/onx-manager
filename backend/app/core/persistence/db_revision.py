"""Per-release database revision compatibility floor.

onx-manager refuses to start against a database whose schema revision is older
than the minimum required by the release. Migrations are NEVER run automatically
from this module — the operator is responsible for ``alembic upgrade head``
before starting the application (see ``backend/Dockerfile``).

Compatibility is decided from the Alembic revision *graph* (migration ancestry),
never by lexicographic comparison of revision ids: a database revision is
compatible when the release-minimum revision is reachable by walking
``down_revision`` from the database's current revision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script.base import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.identity import IDENTITY

logger = logging.getLogger(__name__)

#: Single authoritative declaration of the DB schema floor for onx-manager 0.1.0.
RELEASE_MINIMUM_DB_REVISION = "b1e2100000029"
EXPECTED_ALEMBIC_HEAD = "b1e2100000029"


@dataclass(frozen=True)
class RevisionStatus:
    ok: bool
    message: str


def _migrations_dir() -> Path:
    # app/core/persistence/<module> -> backend/
    return Path(__file__).resolve().parents[3] / "alembic"


def load_revision_parents(scripts_dir: Path | None = None) -> dict[str, str | None]:
    """Map each revision id to its down_revision id (migration ancestry edges)."""
    cfg = AlembicConfig()
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(scripts_dir or _migrations_dir()))
    script = ScriptDirectory.from_config(cfg)
    parents: dict[str, str | None] = {}
    for rev in script.walk_revisions():
        parents[rev.revision] = rev.down_revision
    return parents


def _ancestors(revision: str, parents: dict[str, str | None]) -> set[str]:
    """All revision ids reachable by walking down_revision from `revision` (incl. itself)."""
    seen: set[str] = set()
    node: str | None = revision
    while node is not None and node not in seen:
        seen.add(node)
        node = parents.get(node)
    return seen


def evaluate_revision(
    current_revisions: list[str] | None,
    minimum_revision: str = RELEASE_MINIMUM_DB_REVISION,
    parents: dict[str, str | None] | None = None,
) -> RevisionStatus:
    """Decide whether a database's revision(s) satisfy the release minimum.

    Returns an actionable ``RevisionStatus`` without raising. Parameterized with
    the migration graph so the pure logic is testable against synthetic graphs.
    An empty/absent ``alembic_version`` fails closed.
    """
    graph = parents if parents is not None else load_revision_parents()

    if not current_revisions:
        return RevisionStatus(
            ok=False,
            message=(
                f"The database has no schema revision recorded (missing or empty "
                f"alembic_version). {IDENTITY.project_name} requires at least revision "
                f"'{minimum_revision}'. Run the migrations before starting: "
                f"alembic upgrade head"
            ),
        )

    unique = list(dict.fromkeys(current_revisions))
    if len(unique) > 1:
        heads = ", ".join(sorted(unique))
        return RevisionStatus(
            ok=False,
            message=(
                f"The database reports multiple schema revisions ({heads}). "
                f"{IDENTITY.project_name} requires a single revision >= "
                f"'{minimum_revision}'. Resolve the migration heads before "
                f"starting: alembic upgrade head"
            ),
        )

    current = unique[0]
    if current not in graph:
        return RevisionStatus(
            ok=False,
            message=(
                f"The database has an unknown schema revision '{current}'. "
                f"{IDENTITY.project_name} requires revision '{minimum_revision}' or a "
                f"compatible descendant. Run the migrations before starting: "
                f"alembic upgrade head"
            ),
        )

    if minimum_revision not in graph:
        # Minimum itself is not a known node (misconfigured graph) — fail closed.
        return RevisionStatus(
            ok=False,
            message=(
                f"Release minimum revision '{minimum_revision}' is not present "
                f"in the migration history. Check the release configuration."
            ),
        )

    current_ancestors = _ancestors(current, graph)
    if minimum_revision in current_ancestors:
        return RevisionStatus(
            ok=True,
            message=f"Database schema revision '{current}' is compatible.",
        )

    return RevisionStatus(
        ok=False,
        message=(
            f"The database is at schema revision '{current}', which is behind the "
            f"minimum required by {IDENTITY.project_name} ('{minimum_revision}'). Run the "
            f"migrations before starting: alembic upgrade head"
        ),
    )


async def check_database_compatibility(
    minimum_revision: str = RELEASE_MINIMUM_DB_REVISION,
) -> RevisionStatus:
    """Read ``alembic_version`` from the live database and enforce the floor.

    Fails closed: a missing table/revision aborts startup with an actionable
    error. No automatic migration is ever performed.
    """
    from app.core.persistence.db import database

    async with database.session_factory() as session:
        try:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            current = [row[0] for row in result.fetchall()]
        except DBAPIError:
            current = []  # table absent -> record nothing -> fail closed below

    status = evaluate_revision(current, minimum_revision)
    if not status.ok:
        logger.error("Database compatibility check FAILED: %s", status.message)
    else:
        logger.info("Database compatibility check OK: %s", status.message)
    return status
