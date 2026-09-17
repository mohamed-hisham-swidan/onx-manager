"""Global admission gate for isolated test runs (Stage D).

Replaces the removed per-server in-memory lock in ``DockerTestExecutionRunner``
with a reserving, cross-process-safe admission checkpoint:

* reap stale PENDING/RUNNING rows (lazy, no background jobs),
* read the global occupied set (PENDING/RUNNING across ALL servers),
* deny on global cap (409) or earmarked headroom exhaustion (422),
* earmark RAM/cores by writing them onto the admitted run's own row.

The whole reap-read-check-insert sequence runs inside ONE database transaction
holding a cross-process global lock (dialect-aware sentinel claim), so two
workers cannot both observe the same "available" headroom. The lock is held
for milliseconds: the admitted container starts only AFTER this transaction
commits. Runner invocation, verification, and terminal transitions happen
outside, exactly as before.

Admission vocabulary only — no new Runtime-named concepts (Stage D spec §a).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.exceptions import BotRunInsufficientResourcesError, ConflictError
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.value_objects import (
    BotTech,
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import (
    ServerAdmissionLeaseModel,
    ServerTestRunModel,
)

logger = logging.getLogger(__name__)

LEASE_ROW_ID = 1
GLOBAL_CAP_DEFAULT = 3
STALE_TIMEOUT_HOURS_DEFAULT = 6.0
STALE_REAP_REASON = "stale reservation reaped"

_ACTIVE_STATUSES = (TestRunStatus.PENDING.value, TestRunStatus.RUNNING.value)


@dataclass(frozen=True)
class AdmittedReservation:
    """Result of a successful admission: the persisted PENDING run + ledger context."""

    test_run: ServerTestRun
    occupied_count: int  # other active runs observed (excluding this admission)


def _admission_settings() -> tuple[int, float]:
    """Read (cap, stale-timeout-hours), tolerating missing settings in tests."""
    try:
        from app.core.settings_store import get_live_settings

        live = get_live_settings()
    except Exception:
        return GLOBAL_CAP_DEFAULT, STALE_TIMEOUT_HOURS_DEFAULT
    cap = getattr(live, "global_max_concurrent_runs", GLOBAL_CAP_DEFAULT)
    stale = getattr(live, "stale_run_timeout_hours", STALE_TIMEOUT_HOURS_DEFAULT)
    try:
        return int(cap), float(stale)
    except (TypeError, ValueError):
        return GLOBAL_CAP_DEFAULT, STALE_TIMEOUT_HOURS_DEFAULT


async def _claim_global_lock(conn: Any, holder: str = "") -> None:
    """Serialize admission across worker processes on one host.

    Postgres-family: SELECT ... FOR UPDATE on the singleton sentinel row
    (in-repo precedent: refresh_token + auth repository row locks).
    SQLite: BEGIN IMMEDIATE up front, so a second worker blocks BEFORE reading
    (a deferred BEGIN would let it read stale state, then deadlock on write).
    Backend selected via ``conn.dialect.name``. Multi-HOST is out of scope (Stage G).
    The holder heartbeat is observability only; correctness needs just the lock.
    """
    if conn.dialect.name == "sqlite":
        await conn.exec_driver_sql("BEGIN IMMEDIATE")
        present = await conn.execute(
            select(ServerAdmissionLeaseModel.id).where(
                ServerAdmissionLeaseModel.id == LEASE_ROW_ID
            )
        )
        missing = present.scalar_one_or_none() is None
    else:
        res = await conn.execute(
            select(ServerAdmissionLeaseModel).where(
                ServerAdmissionLeaseModel.id == LEASE_ROW_ID
            ).with_for_update()
        )
        missing = res.scalar_one_or_none() is None
    if missing:
        # Seed-if-absent: the migration seeds production databases; schemas
        # built via create_all (tests) start empty. Runs inside the claimed
        # lock, so concurrent seeders cannot duplicate the row.
        await conn.execute(
            ServerAdmissionLeaseModel.__table__.insert().values(
                id=LEASE_ROW_ID, holder=holder, acquired_at=datetime.now(UTC)
            )
        )
    else:
        await conn.execute(
            ServerAdmissionLeaseModel.__table__.update()
            .where(ServerAdmissionLeaseModel.__table__.c.id == LEASE_ROW_ID)
            .values(holder=holder, acquired_at=datetime.now(UTC))
        )


async def admit(
    *,
    server_id: str,
    commit_id: str,
    bot_count: int,
    server_type: str,
    duration_minutes: int = 15,
    placement_mode: str = "sidecar",
    bot_tech: str = "auto",
    node_id: str = "local",
    engine: Any | None = None,
    max_runs: int | None = None,
    stale_hours: float | None = None,
    now: datetime | None = None,
) -> AdmittedReservation:
    """Admit one test run: reap, check cap + earmarked headroom, persist PENDING earmark.

    Raises ConflictError (409) on global-cap denial and
    BotRunInsufficientResourcesError (422) on headroom denial — the same codes
    as the pre-Stage-D behavior. The returned run is PENDING; the caller marks
    it RUNNING and invokes the runner only after this transaction commits.
    """
    from app.core.persistence.db import database
    from app.modules.versioning.infrastructure.resource_probe import (
        ResourcePreflightProbe,
    )

    eng = engine if engine is not None else database._engine
    if eng is None:
        raise RuntimeError("Database not initialized; cannot admit test run")
    cap_default, stale_default = _admission_settings()
    cap = cap_default if max_runs is None else max_runs
    stale = stale_default if stale_hours is None else stale_hours
    at = now or datetime.now(UTC)
    if cap < 0:
        cap = cap_default

    run_tbl = ServerTestRunModel.__table__
    req_ram, req_cores = ResourcePreflightProbe.calculate_required_resources(
        bot_count, server_type
    )

    async with eng.connect() as conn:
        await _claim_global_lock(conn, holder=f"admit:{server_id}")
        try:
            # 1. Lazy reap of phantom reservations (crash-during-reservation self-heals
            # here; stored earmarks die with the terminal transition — nothing else to clean).
            cutoff = at - timedelta(hours=stale)
            await conn.execute(
                run_tbl.update()
                .where(run_tbl.c.status.in_(_ACTIVE_STATUSES), run_tbl.c.created_at < cutoff)
                .values(status=TestRunStatus.CANCELLED.value, failure_reason=STALE_REAP_REASON)
            )

            # 2. Global occupied set.
            rows = (
                (
                    await conn.execute(
                        run_tbl.select()
                        .where(run_tbl.c.status.in_(_ACTIVE_STATUSES))
                        .order_by(run_tbl.c.created_at)
                    )
                )
                .mappings()
                .all()
            )

            # 3. Resolve earmarks (stored values are truth; NULL legacy rows recompute
            # once via the unchanged formula and are backfilled in this transaction).
            earmarked_ram = 0
            earmarked_cores = 0
            for row in rows:
                ram = row["reserved_ram_mb"]
                cores = row["reserved_cores"]
                if ram is None or cores is None:
                    legacy_ram, legacy_cores = (
                        ResourcePreflightProbe.calculate_required_resources(
                            row["bot_count"] or 0, server_type
                        )
                    )
                    ram = legacy_ram if ram is None else ram
                    cores = legacy_cores if cores is None else cores
                    await conn.execute(
                        run_tbl.update()
                        .where(run_tbl.c.id == row["id"])
                        .values(reserved_ram_mb=ram, reserved_cores=cores)
                    )
                earmarked_ram += ram
                earmarked_cores += cores

            # 4a. Global-cap denial (409, existing code).
            if len(rows) >= cap:
                raise ConflictError(
                    f"Global concurrent test-run cap reached ({len(rows)}/{cap} active). "
                    "Wait for a run to finish and retry."
                )

            # 4b. Earmarked-headroom denial (422, existing code). Live psutil.available
            # already reflects live-server consumption (observed, never earmarked).
            headroom = ResourcePreflightProbe.check_headroom(bot_count, server_type)
            if (
                earmarked_ram + req_ram > headroom.available_ram_mb
                or earmarked_cores + req_cores > headroom.available_cores
            ):
                raise BotRunInsufficientResourcesError(
                    message=(
                        f"Insufficient earmarked headroom: {earmarked_ram}MB already "
                        f"reserved + {req_ram}MB requested > {headroom.available_ram_mb}MB "
                        f"available ({len(rows)}/{cap} runs active)"
                    ),
                    details={
                        "occupied": len(rows),
                        "cap": cap,
                        "earmarked_ram_mb": earmarked_ram,
                        "required_ram_mb": req_ram,
                        "available_ram_mb": headroom.available_ram_mb,
                    },
                )

            # 5. Earmark: the promise becomes durable BEFORE anyone else can check.
            run_id = str(uuid.uuid4())
            await conn.execute(
                run_tbl.insert().values(
                    id=run_id,
                    server_id=server_id,
                    commit_id=commit_id,
                    node_id=node_id,
                    status=TestRunStatus.PENDING.value,
                    created_at=at,
                    bot_count=bot_count,
                    duration_minutes=duration_minutes,
                    placement_mode=placement_mode,
                    bot_tech=bot_tech,
                    reserved_ram_mb=req_ram,
                    reserved_cores=req_cores,
                )
            )
            await conn.commit()
        except (ConflictError, BotRunInsufficientResourcesError):
            # Denial is not a failure: no reservation was written, but the
            # reap/backfill maintenance above must still commit — otherwise a
            # stale phantom would survive every denial and leak its slot until
            # the next success (denial-storm deadlock).
            try:
                await conn.commit()
            except Exception:
                await conn.rollback()
            raise
        except Exception:
            await conn.rollback()
            raise

    test_run = ServerTestRun(
        id=run_id,
        server_id=server_id,
        commit_id=commit_id,
        node_id=node_id,
        status=TestRunStatus.PENDING,
        bot_count=bot_count,
        duration_minutes=duration_minutes,
        placement_mode=(
            PlacementMode(placement_mode)
            if placement_mode in PlacementMode._value2member_map_
            else PlacementMode.SIDECAR
        ),
        bot_tech=(
            BotTech(bot_tech)
            if bot_tech in BotTech._value2member_map_
            else BotTech.AUTO
        ),
        created_at=at,
        reserved_ram_mb=req_ram,
        reserved_cores=req_cores,
    )
    logger.info(
        "Admitted test run %s on server %s (%s/%s active, earmark %sMB/%score)",
        run_id,
        server_id,
        len(rows) + 1,
        cap,
        req_ram,
        req_cores,
    )
    return AdmittedReservation(test_run=test_run, occupied_count=len(rows))
