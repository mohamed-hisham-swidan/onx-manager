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
import os
import shutil
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.exceptions import (
    BotRunInsufficientResourcesError,
    BranchConcurrencyLimitError,
    BranchRuntimeActiveError,
    ConflictError,
    DuplicatePortSetError,
    NotFoundError,
    PortAllocationExhaustedError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
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

_ACTIVE_STATUSES = (
    TestRunStatus.PENDING.value,
    TestRunStatus.BOOTING.value,
    TestRunStatus.RUNNING.value,
)


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


async def reap_stale_reservations(
    conn: Any,
    *,
    at: datetime | None = None,
    stale_hours: float | None = None,
    artifact_retention_hours: float | None = None,
) -> int:
    """Reaps phantom active reservations and prunes expired test artifacts.

    Invoked inside the admission transaction under global lock; can also be called
    directly by test maintenance commands or tests.
    """
    now = at or datetime.now(UTC)
    stale = stale_hours if stale_hours is not None else STALE_TIMEOUT_HOURS_DEFAULT
    run_tbl = ServerTestRunModel.__table__

    # 1. Stale reservations -> CANCELLED
    cutoff = now - timedelta(hours=stale)
    res = await conn.execute(
        run_tbl.update()
        .where(run_tbl.c.status.in_(_ACTIVE_STATUSES), run_tbl.c.created_at < cutoff)
        .values(status=TestRunStatus.CANCELLED.value, failure_reason=STALE_REAP_REASON)
    )
    reaped = res.rowcount

    # 2. Expired test artifacts -> delete directory + mark artifacts_purged = True
    try:
        from app.core.config import AppSettings

        settings = AppSettings()
        hours = (
            artifact_retention_hours
            if artifact_retention_hours is not None
            else getattr(settings, "test_artifact_retention_hours", 24)
        )
        art_cutoff = now - timedelta(hours=hours)

        art_stmt = (
            run_tbl.select()
            .where(
                run_tbl.c.status.in_([TestRunStatus.FAILED.value, TestRunStatus.CANCELLED.value]),
                run_tbl.c.artifacts_purged.is_(False),
                run_tbl.c.created_at < art_cutoff,
            )
        )
        expired_rows = (await conn.execute(art_stmt)).mappings().all()
        if expired_rows:
            from app.modules.server.infrastructure.models import ServerModel
            from app.modules.versioning.domain.cleanup import TestCleanupPlan
            from app.modules.versioning.domain.paths import resolve_test_dir

            srv_tbl = ServerModel.__table__
            server_ids = {row["server_id"] for row in expired_rows}
            srv_stmt = srv_tbl.select().where(srv_tbl.c.id.in_(server_ids))
            srv_rows = {r["id"]: r for r in (await conn.execute(srv_stmt)).mappings().all()}

            expired_ids = []
            for row in expired_rows:
                s_id = row["server_id"]
                t_id = row["id"]
                srv = srv_rows.get(s_id)
                if not srv or not srv.get("root_path"):
                    logger.warning(
                        "Skipping artifact cleanup for test %s: "
                        "server %s missing or root_path is NULL; refusing to guess path",
                        t_id,
                        s_id,
                    )
                    expired_ids.append(t_id)
                    continue

                root_path = srv["root_path"]
                working_dir = srv.get("working_directory") or "."
                server_dir = (
                    os.path.join(root_path, working_dir)
                    if working_dir != "."
                    else root_path
                )

                try:
                    t_dir = resolve_test_dir(server_dir, t_id)
                    plan = TestCleanupPlan.create(
                        server_id=s_id,
                        test_id=t_id,
                        container_name=f"onx-test-{t_id}",
                        test_dir=t_dir,
                        server_dir=server_dir,
                        passed=False,
                        retention_hours=0.0,
                    )
                    if plan.purge_artifacts and t_dir.exists():
                        shutil.rmtree(t_dir, ignore_errors=True)
                except Exception as exc:
                    logger.warning("Failed pruning test artifact directory for %s: %s", t_id, exc)
                expired_ids.append(t_id)

            if expired_ids:
                await conn.execute(
                    run_tbl.update()
                    .where(run_tbl.c.id.in_(expired_ids))
                    .values(artifacts_purged=True)
                )
    except Exception as exc:
        logger.warning("Artifact pruning during lazy reap encountered error: %s", exc)

    return reaped


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
            # 1. Lazy reap of phantom reservations and expired test artifacts
            # (zero standalone background polling loops).
            await reap_stale_reservations(conn, at=at, stale_hours=stale)

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


# ---------------------------------------------------------------------------
# P4-2 Branch Runtime admission
# ---------------------------------------------------------------------------

DEFAULT_MAX_CONCURRENT_BRANCH_RUNS = 1
MAX_CONCURRENT_BRANCH_RUNS_LIMIT = 3
BRANCH_MEMORY_FLOOR_MB = 2048
LIGHTWEIGHT_BRANCH_MEMORY_FLOOR_MB = 1024
BRANCH_DEFAULT_MEMORY_MB = 4096
BRANCH_DEFAULT_CPU_CORES = 2
LIGHTWEIGHT_BRANCH_SERVER_TYPES = frozenset(
    {"vanilla", "velocity", "bungeecord", "waterfall", "proxy"}
)
_ACTIVE_RUNTIME_STATUSES = ("starting", "running")

STALE_TIMEOUT_HOURS_DEFAULT = 6.0



@dataclass(frozen=True)
class BranchAdmissionDecision:
    runtime_id: str
    server_id: str
    branch_name: str
    commit_sha: str
    memory_max_mb: int
    memory_min_mb: int
    cpu_cores: int
    pids_limit: int
    port_set: Any = None
    server_active_branch_count: int = 0
    server_branch_cap: int = 1


@dataclass
class BranchAdmissionRequest:
    server_id: str
    branch_name: str
    commit_sha: str
    server_type: str = "vanilla"
    runtime_id: str | None = None
    requested_memory_mb: int | None = None
    requested_cpu_cores: int | None = None
    max_concurrent_branch_runs: int | None = None
    port_set: Any = None
    allocate_ports: bool = False
    include_query: bool = False
    plugin_port_names: Sequence[str] = ()
    check_os_ports: bool = True
    data_template_id: str | None = None
    allow_public_test_join: bool = False
    export_path: str | None = None
    persist_runtime: bool = True
    now: Any = None


class RuntimeAdmissionScheduler:
    def __init__(
        self,
        engine: Any | None = None,
        *,
        headroom_probe: Callable[[int, str], Any] | None = None,
    ) -> None:
        self._engine = engine
        self._headroom_probe = headroom_probe

    @staticmethod
    def resolve_branch_resources(
        *,
        server_type: str,
        server_memory_max_mb: int | None,
        requested_memory_mb: int | None = None,
        server_cpu_cores: int | None = None,
        requested_cpu_cores: int | None = None,
    ) -> tuple[int, int, int]:
        floor_mb = (
            LIGHTWEIGHT_BRANCH_MEMORY_FLOOR_MB
            if str(server_type).lower() in LIGHTWEIGHT_BRANCH_SERVER_TYPES
            else BRANCH_MEMORY_FLOOR_MB
        )
        if requested_memory_mb is not None:
            if requested_memory_mb < floor_mb:
                raise ValidationError(
                    f"Branch runtime requires at least {floor_mb} MB RAM "
                    f"for server type '{server_type}'",
                    field="memory_max_mb",
                    details={"floor_mb": floor_mb, "requested_mb": requested_memory_mb},
                )
            mem_max = requested_memory_mb
        else:
            if server_memory_max_mb is not None and int(server_memory_max_mb) > 0:
                mem_max = max(int(server_memory_max_mb), floor_mb)
            else:
                mem_max = BRANCH_DEFAULT_MEMORY_MB
        mem_min = min(1024, mem_max)
        if requested_cpu_cores is not None and int(requested_cpu_cores) > 0:
            cpu_cores = int(requested_cpu_cores)
        elif server_cpu_cores is not None and int(server_cpu_cores) > 0:
            cpu_cores = int(server_cpu_cores)
        else:
            cpu_cores = BRANCH_DEFAULT_CPU_CORES
        return mem_min, mem_max, cpu_cores

    async def admit_branch_runtime(
        self,
        *,
        server_id: str,
        branch_name: str,
        commit_sha: str,
        server_type: str = "vanilla",
        runtime_id: str | None = None,
        requested_memory_mb: int | None = None,
        requested_cpu_cores: int | None = None,
        max_concurrent_branch_runs: int | None = None,
        port_set: Any = None,
        allocate_ports: bool = False,
        include_query: bool = False,
        plugin_port_names: Sequence[str] = (),
        check_os_ports: bool = True,
        data_template_id: str | None = None,
        allow_public_test_join: bool = False,
        export_path: str | None = None,
        persist_runtime: bool = True,
        now: Any = None,
    ) -> BranchAdmissionDecision:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()
        if branch_name == "main":
            raise ValidationError(
                "Branch runtime engine only launches non-main branches",
                field="branch_name",
            )
        if max_concurrent_branch_runs is not None and not (
            1 <= int(max_concurrent_branch_runs) <= 3
        ):
            raise ValidationError(
                "max_concurrent_branch_runs must be between 1 and 3",
                field="max_concurrent_branch_runs",
            )

        from app.core.container_hardening import PIDS_LIMIT
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.models import ServerModel
        from app.modules.versioning.infrastructure.models import (
            ServerBranchModel,
            ServerCommitModel,
            ServerRuntimeModel,
        )
        from app.modules.versioning.infrastructure.port_allocator import (
            allocate_port_set,
            validate_port_set_atomic,
        )
        from app.modules.versioning.infrastructure.resource_probe import (
            ResourcePreflightProbe,
        )

        eng = self._engine
        if eng is None:
            eng = database._engine
        if eng is None:
            raise RuntimeError("Database not initialized; cannot admit branch runtime")

        at = now
        if at is None:
            at = datetime.now(UTC)

        async with eng.connect() as conn:
            await _claim_global_lock(conn, holder=f"branch-admit:{server_id}:{branch_name}")
            try:
                await reap_stale_reservations(conn, at=at, stale_hours=STALE_TIMEOUT_HOURS_DEFAULT)

                srv_tbl = ServerModel.__table__
                srv_row = (
                    await conn.execute(srv_tbl.select().where(srv_tbl.c.id == server_id))
                ).mappings().first()
                if srv_row is None:
                    raise NotFoundError(f"Server '{server_id}' not found")
                srv = dict(srv_row)
                srv_type = srv.get("server_type") or server_type or "vanilla"
                override_cap = max_concurrent_branch_runs
                if override_cap is None:
                    override_cap = srv.get("max_concurrent_branch_runs")
                server_cap = min(
                    max(int(override_cap if override_cap is not None else 1), 1),
                    MAX_CONCURRENT_BRANCH_RUNS_LIMIT,
                )

                mem_min, mem_max, req_cores = self.resolve_branch_resources(
                    server_type=srv_type,
                    server_memory_max_mb=srv.get("memory_max_mb"),
                    requested_memory_mb=requested_memory_mb,
                    server_cpu_cores=srv.get("cpu_cores"),
                    requested_cpu_cores=requested_cpu_cores,
                )

                rt_tbl = ServerRuntimeModel.__table__
                active_runtimes = [
                    dict(r)
                    for r in (
                        await conn.execute(
                            rt_tbl.select().where(
                                rt_tbl.c.status.in_(_ACTIVE_RUNTIME_STATUSES),
                                rt_tbl.c.branch_name.is_not(None),
                                rt_tbl.c.branch_name != "main",
                            )
                        )
                    ).mappings().all()
                ]
                server_branch_rows = [
                    r for r in active_runtimes if r["server_id"] == server_id
                ]

                # Same branch already active
                for r in server_branch_rows:
                    if r.get("branch_name") == branch_name:
                        raise BranchRuntimeActiveError(
                            f"Branch '{branch_name}' already has an active runtime",
                            details={
                                "server_id": server_id,
                                "branch_name": branch_name,
                                "active_runtime_id": r["id"],
                            },
                        )

                if len(server_branch_rows) >= server_cap:
                    raise BranchConcurrencyLimitError(
                        f"Server '{server_id}' reached active branch run limit "
                        f"({len(server_branch_rows)}/{server_cap}); "
                        "stop an active branch run before starting another.",
                        details={
                            "server_id": server_id,
                            "active_count": len(server_branch_rows),
                            "limit": server_cap,
                            "active_branches": [r["branch_name"] for r in server_branch_rows],
                        },
                    )

                # Earmarked RAM/cores
                run_tbl = ServerTestRunModel.__table__
                test_runs = [
                    dict(r)
                    for r in (
                        await conn.execute(
                            run_tbl.select().where(
                                run_tbl.c.status.in_(("PENDING", "BOOTING", "RUNNING"))
                            )
                        )
                    ).mappings().all()
                ]
                earmarked_ram = 0
                earmarked_cores = 0
                for row in test_runs:
                    ram = row.get("reserved_ram_mb")
                    cores = row.get("reserved_cores")
                    if ram is None or cores is None:
                        legacy_ram, legacy_cores = (
                            ResourcePreflightProbe.calculate_required_resources(
                                row.get("bot_count") or 0, srv_type
                            )
                        )
                        ram = legacy_ram if ram is None else ram
                        cores = legacy_cores if cores is None else cores
                        await conn.execute(
                            run_tbl.update()
                            .where(run_tbl.c.id == row["id"])
                            .values(reserved_ram_mb=ram, reserved_cores=cores)
                        )
                    earmarked_ram += int(ram or 0)
                    earmarked_cores += int(cores or 0)

                # starting branch runtimes earmark
                starting_branch_runtimes = [
                    r for r in active_runtimes if r.get("status") == "starting"
                ]
                server_ids_sb = {r["server_id"] for r in starting_branch_runtimes}
                srv_rows_sb: dict[str, Any] = {}
                if server_ids_sb:
                    srv_rows_sb = {
                        r["id"]: r
                        for r in (
                            await conn.execute(
                                srv_tbl.select().where(srv_tbl.c.id.in_(server_ids_sb))
                            )
                        ).mappings().all()
                    }
                for r in starting_branch_runtimes:
                    s = srv_rows_sb.get(r["server_id"])
                    mem = 4096
                    cores = 2
                    if s is not None:
                        if s.get("memory_max_mb"):
                            mem = int(s["memory_max_mb"])
                        if s.get("cpu_cores"):
                            cores = int(s["cpu_cores"])
                    earmarked_ram += mem
                    earmarked_cores += cores

                headroom = ResourcePreflightProbe.check_headroom(
                    0, srv_type, custom_floor_mb=mem_max, custom_floor_cores=req_cores
                )
                if (
                    earmarked_ram + mem_max > getattr(headroom, "available_ram_mb", 0)
                    or earmarked_cores + req_cores > getattr(headroom, "available_cores", 0)
                ):
                    raise BotRunInsufficientResourcesError(
                        message="Insufficient resources for branch runtime",
                        details={
                            "earmarked_ram_mb": earmarked_ram,
                            "required_ram_mb": mem_max,
                            "available_ram_mb": getattr(headroom, "available_ram_mb", 0),
                            "earmarked_cores": earmarked_cores,
                            "required_cores": req_cores,
                            "available_cores": getattr(headroom, "available_cores", 0),
                        },
                    )

                if self._headroom_probe is None:
                    from app.core.resource_budget import ResourceBudgetService

                    await ResourceBudgetService.check_admission(
                        conn,
                        requested_ram_mb=mem_max,
                        requested_cpu_cores=float(req_cores),
                    )

                # Ports
                resolved_port_set = port_set
                if port_set is not None or allocate_ports:
                    from sqlalchemy.ext.asyncio import AsyncSession

                    async with AsyncSession(bind=conn) as p_session:
                        if allocate_ports:
                            resolved_port_set = await allocate_port_set(
                                p_session,
                                include_query=include_query,
                                plugin_port_names=plugin_port_names,
                                check_os_ports=check_os_ports,
                            )
                        else:
                            branch_tbl_ports = ServerBranchModel.__table__
                            own_branch = (
                                await p_session.execute(
                                    branch_tbl_ports.select()
                                    .where(
                                        branch_tbl_ports.c.server_id == server_id,
                                        branch_tbl_ports.c.name == branch_name,
                                    )
                                    .limit(1)
                                )
                            ).mappings().first()
                            await validate_port_set_atomic(
                                p_session,
                                port_set,
                                exclude_branch_id=(
                                    own_branch["id"] if own_branch is not None else None
                                ),
                                exclude_runtime_id=runtime_id,
                                check_os_ports=check_os_ports,
                            )
                            resolved_port_set = port_set

                rt_id = runtime_id or str(uuid.uuid4())

                if persist_runtime:
                    commit_tbl = ServerCommitModel.__table__
                    existing_commit = await conn.execute(
                        commit_tbl.select().where(commit_tbl.c.id == commit_sha)
                    )
                    if existing_commit.scalar_one_or_none() is None:
                        await conn.execute(
                            commit_tbl.insert().values(
                                id=commit_sha,
                                server_id=server_id,
                                message=f"Git commit {commit_sha[:12]}",
                                manifest_json={},
                                created_at=at,
                            )
                        )
                    port_val = resolved_port_set.game_port if resolved_port_set else None
                    port_set_json = (
                        resolved_port_set.to_dict() if resolved_port_set else None
                    )
                    await conn.execute(
                        rt_tbl.insert().values(
                            id=rt_id,
                            server_id=server_id,
                            commit_id=commit_sha,
                            materialization_id=None,
                            provider_type="docker",
                            port=port_val,
                            status="starting",
                            started_at=at,
                            created_at=at,
                            branch_name=branch_name,
                            data_template_id=data_template_id,
                            port_set_json=port_set_json,
                            allow_public_test_join=allow_public_test_join,
                            export_path=export_path,
                        )
                    )
                    branch_tbl = ServerBranchModel.__table__
                    await conn.execute(
                        branch_tbl.update()
                        .where(
                            branch_tbl.c.server_id == server_id,
                            branch_tbl.c.name == branch_name,
                        )
                        .values(
                            runtime_status="starting",
                            active_runtime_id=rt_id,
                            active_commit_sha=commit_sha,
                            active_data_template_id=data_template_id,
                            port_set_json=port_set_json,
                        )
                    )

                await conn.commit()
            except (
                BranchRuntimeActiveError,
                BranchConcurrencyLimitError,
                DuplicatePortSetError,
                PortAllocationExhaustedError,
                BotRunInsufficientResourcesError,
                ValidationError,
            ):
                try:
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                raise
            except Exception:
                await conn.rollback()
                raise

        return BranchAdmissionDecision(
            runtime_id=rt_id,
            server_id=server_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            memory_max_mb=mem_max,
            memory_min_mb=mem_min,
            cpu_cores=req_cores,
            pids_limit=PIDS_LIMIT,
            port_set=resolved_port_set,
            server_active_branch_count=len(server_branch_rows),
            server_branch_cap=server_cap,
        )


async def admit_branch_runtime(*args: Any, **kwargs: Any) -> BranchAdmissionDecision:
    engine = kwargs.pop("engine", None)
    headroom_probe = kwargs.pop("headroom_probe", None)
    scheduler = RuntimeAdmissionScheduler(engine=engine, headroom_probe=headroom_probe)
    return await scheduler.admit_branch_runtime(*args, **kwargs)
