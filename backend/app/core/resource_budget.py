"""Host RAM and CPU budgeting with profile-aware OS reserve and atomic admission checks."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import AppSettings, ConfigFactory
from app.core.exceptions import InsufficientHostResourcesError
from app.core.settings_store import get_live_settings

logger = logging.getLogger(__name__)

_ACTIVE_SERVER_STATES = ("starting", "running")
_ADMISSION_LOCK: asyncio.Lock | None = None
_ADMISSION_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True)
class ServerAllocationItem:
    id: str
    name: str
    kind: str  # "server" | "branch_runtime" | "test_run"
    status: str
    ram_mb: int
    cpu_cores: float


@dataclass(frozen=True)
class HostResourceBudget:
    total_ram_mb: int
    os_reserve_ram_mb: int
    allocatable_ram_mb: int
    allocated_ram_mb: int
    available_ram_mb: int
    total_cpus: float
    reserved_cpus: float
    allocatable_cpus: float
    allocated_cpus: float
    available_cpus: float
    profile: str
    ram_reserve_override_mb: int = 0
    cpu_reserve_override: float = 0.0
    allocations: list[ServerAllocationItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_ram_mb": self.total_ram_mb,
            "os_reserve_ram_mb": self.os_reserve_ram_mb,
            "allocatable_ram_mb": self.allocatable_ram_mb,
            "allocated_ram_mb": self.allocated_ram_mb,
            "available_ram_mb": self.available_ram_mb,
            "total_cpus": self.total_cpus,
            "reserved_cpus": self.reserved_cpus,
            "allocatable_cpus": self.allocatable_cpus,
            "allocated_cpus": self.allocated_cpus,
            "available_cpus": self.available_cpus,
            "profile": self.profile,
            "ram_reserve_override_mb": self.ram_reserve_override_mb,
            "cpu_reserve_override": self.cpu_reserve_override,
            "allocations": [asdict(item) for item in self.allocations],
        }


def _read_cgroup_memory_limit_mb() -> int | None:
    """Return Linux cgroup memory cap in MB when constrained inside a container."""
    candidates = (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for path in candidates:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw or raw == "max":
            continue
        try:
            limit_bytes = int(raw)
        except ValueError:
            continue
        # Kernel uses ~2^63-4096 when unlimited in cgroup v1.
        if 0 < limit_bytes < (1 << 50):
            return max(128, limit_bytes // (1024 * 1024))
    return None


def _read_cgroup_cpu_limit() -> float | None:
    """Return Linux cgroup CPU quota in cores when constrained inside a container."""
    v2_path = Path("/sys/fs/cgroup/cpu.max")
    try:
        raw = v2_path.read_text(encoding="utf-8").strip()
        parts = raw.split()
        if len(parts) == 2 and parts[0] != "max":
            quota = int(parts[0])
            period = int(parts[1])
            if quota > 0 and period > 0:
                return round(quota / period, 2)
    except (OSError, ValueError):
        pass

    quota_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    try:
        quota = int(quota_path.read_text(encoding="utf-8").strip())
        period = int(period_path.read_text(encoding="utf-8").strip())
        if quota > 0 and period > 0:
            return round(quota / period, 2)
    except (OSError, ValueError):
        pass
    return None


def _resolve_reserve_overrides(settings: AppSettings) -> tuple[int, float]:
    """Combine live settings overrides with env-backed AppSettings overrides."""
    ram_override = int(getattr(settings, "host_ram_reserve_mb", 0) or 0)
    cpu_override = float(getattr(settings, "host_cpu_reserve", 0.0) or 0.0)
    try:
        live = get_live_settings()
        live_ram = int(getattr(live, "host_ram_reserve_mb", 0) or 0)
        live_cpu = float(getattr(live, "host_cpu_reserve", 0.0) or 0.0)
        if live_ram > 0:
            ram_override = live_ram
        if live_cpu > 0:
            cpu_override = live_cpu
    except Exception:
        pass
    return max(0, ram_override), max(0.0, cpu_override)


class ResourceBudgetService:
    """Tracks host RAM/CPU capacity, profile-based OS reserve, and live server allocations."""

    @staticmethod
    def admission_lock() -> asyncio.Lock:
        """Return an asyncio Lock bound to the active running event loop."""
        global _ADMISSION_LOCK, _ADMISSION_LOCK_LOOP
        loop = asyncio.get_running_loop()
        if _ADMISSION_LOCK is None or _ADMISSION_LOCK_LOOP is not loop:
            _ADMISSION_LOCK = asyncio.Lock()
            _ADMISSION_LOCK_LOOP = loop
        return _ADMISSION_LOCK

    @staticmethod
    def detect_host_capacity() -> tuple[int, float]:
        """Return `(total_ram_mb, total_cpus)` honoring container cgroup limits on Linux."""
        vm = psutil.virtual_memory()
        raw_bytes = getattr(vm, "total", None)
        if raw_bytes is None:
            raw_bytes = getattr(vm, "available", 0)
        host_ram_mb = max(256, int(raw_bytes) // (1024 * 1024))

        raw_cpus = os.cpu_count() or psutil.cpu_count(logical=True) or 1
        host_cpus = float(max(1, int(raw_cpus)))

        if os.name == "posix":
            cg_mem = _read_cgroup_memory_limit_mb()
            if cg_mem is not None and cg_mem < host_ram_mb:
                host_ram_mb = cg_mem
            cg_cpu = _read_cgroup_cpu_limit()
            if cg_cpu is not None and cg_cpu < host_cpus:
                host_cpus = max(1.0, cg_cpu)

        return host_ram_mb, round(host_cpus, 2)

    @staticmethod
    def compute_os_reserve(
        total_ram_mb: int,
        total_cpus: float,
        profile: str,
        ram_override_mb: int = 0,
        cpu_override: float = 0.0,
    ) -> tuple[int, float]:
        """Compute protected OS/panel reserve for `local` desktop vs `vps` server profiles."""
        if ram_override_mb > 0:
            ram_reserve = min(int(ram_override_mb), int(total_ram_mb))
        elif profile == "local":
            ram_reserve = min(
                max(4096, int(total_ram_mb * 0.25)),
                max(512, int(total_ram_mb * 0.60)),
            )
        else:
            ram_reserve = min(
                max(1024, int(total_ram_mb * 0.15)),
                max(512, int(total_ram_mb * 0.50)),
            )

        if cpu_override > 0:
            cpu_reserve = round(min(float(cpu_override), float(total_cpus)), 2)
        elif total_cpus <= 1.0:
            cpu_reserve = 0.0
        elif profile == "local":
            cpu_reserve = round(min(max(1.0, round(total_cpus * 0.25, 2)), total_cpus - 1.0), 2)
        else:
            cpu_reserve = round(min(max(0.5, round(total_cpus * 0.10, 2)), total_cpus - 1.0), 2)

        return ram_reserve, cpu_reserve

    @classmethod
    async def get_budget(
        cls,
        db: AsyncSession | AsyncConnection,
        *,
        exclude_server_id: str | None = None,
        exclude_runtime_id: str | None = None,
        settings: AppSettings | None = None,
    ) -> HostResourceBudget:
        """Compute current host RAM/CPU budget across active servers, branch runtimes, & tests."""
        cfg = settings or ConfigFactory.global_settings()
        profile = cfg.deployment_profile
        total_ram_mb, total_cpus = cls.detect_host_capacity()
        ram_override_mb, cpu_override = _resolve_reserve_overrides(cfg)
        os_reserve_ram_mb, reserved_cpus = cls.compute_os_reserve(
            total_ram_mb,
            total_cpus,
            profile,
            ram_override_mb=ram_override_mb,
            cpu_override=cpu_override,
        )
        allocatable_ram_mb = max(0, total_ram_mb - os_reserve_ram_mb)
        allocatable_cpus = round(max(0.0, total_cpus - reserved_cpus), 2)

        allocations: list[ServerAllocationItem] = []
        server_specs: dict[str, tuple[str, int, float]] = {}

        from app.modules.server.infrastructure.models import ServerModel

        srv_tbl = ServerModel.__table__
        try:
            all_srv_rows = (
                await db.execute(
                    select(
                        srv_tbl.c.id,
                        srv_tbl.c.name,
                        srv_tbl.c.status,
                        srv_tbl.c.memory_max_mb,
                        srv_tbl.c.cpu_cores,
                    )
                )
            ).mappings().all()
        except SQLAlchemyError:
            all_srv_rows = []

        for row in all_srv_rows:
            sid = str(row["id"])
            ram_mb = int(row.get("memory_max_mb") or 2048)
            cpus = float(row.get("cpu_cores") or 0)
            name = str(row.get("name") or sid)
            server_specs[sid] = (name, ram_mb, cpus)
            status = str(row.get("status") or "").lower()
            if status in _ACTIVE_SERVER_STATES and sid != exclude_server_id:
                allocations.append(
                    ServerAllocationItem(
                        id=sid,
                        name=name,
                        kind="server",
                        status=status,
                        ram_mb=ram_mb,
                        cpu_cores=cpus,
                    )
                )

        try:
            from app.modules.versioning.infrastructure.models import (
                ServerRuntimeModel,
                ServerTestRunModel,
            )

            rt_tbl = ServerRuntimeModel.__table__
            rt_rows = (
                await db.execute(
                    select(
                        rt_tbl.c.id,
                        rt_tbl.c.server_id,
                        rt_tbl.c.branch_name,
                        rt_tbl.c.status,
                    ).where(
                        rt_tbl.c.status.in_(_ACTIVE_SERVER_STATES),
                        rt_tbl.c.branch_name.is_not(None),
                        rt_tbl.c.branch_name != "main",
                    )
                )
            ).mappings().all()
            for rt in rt_rows:
                rid = str(rt["id"])
                if rid == exclude_runtime_id:
                    continue
                sid = str(rt["server_id"])
                srv_name, srv_ram, srv_cpus = server_specs.get(sid, (sid, 2048, 0.0))
                branch_label = f"{srv_name} ({rt.get('branch_name')})"
                allocations.append(
                    ServerAllocationItem(
                        id=rid,
                        name=branch_label,
                        kind="branch_runtime",
                        status=str(rt.get("status") or "running").lower(),
                        ram_mb=srv_ram,
                        cpu_cores=srv_cpus if srv_cpus > 0 else 2.0,
                    )
                )

            run_tbl = ServerTestRunModel.__table__
            test_rows = (
                await db.execute(
                    select(
                        run_tbl.c.id,
                        run_tbl.c.server_id,
                        run_tbl.c.status,
                        run_tbl.c.reserved_ram_mb,
                        run_tbl.c.reserved_cores,
                    ).where(run_tbl.c.status.in_(("PENDING", "BOOTING", "RUNNING")))
                )
            ).mappings().all()
            for tr in test_rows:
                tr_ram = int(tr.get("reserved_ram_mb") or 0)
                tr_cpus = float(tr.get("reserved_cores") or 0)
                if tr_ram <= 0 and tr_cpus <= 0:
                    continue
                sid = str(tr["server_id"])
                srv_name = server_specs.get(sid, (sid, 0, 0.0))[0]
                allocations.append(
                    ServerAllocationItem(
                        id=str(tr["id"]),
                        name=f"{srv_name} (test run)",
                        kind="test_run",
                        status=str(tr.get("status") or "RUNNING").lower(),
                        ram_mb=tr_ram,
                        cpu_cores=tr_cpus,
                    )
                )
        except SQLAlchemyError:
            pass

        allocated_ram_mb = sum(item.ram_mb for item in allocations)
        allocated_cpus = round(sum(item.cpu_cores for item in allocations), 2)
        available_ram_mb = max(0, allocatable_ram_mb - allocated_ram_mb)
        available_cpus = round(max(0.0, allocatable_cpus - allocated_cpus), 2)

        return HostResourceBudget(
            total_ram_mb=total_ram_mb,
            os_reserve_ram_mb=os_reserve_ram_mb,
            allocatable_ram_mb=allocatable_ram_mb,
            allocated_ram_mb=allocated_ram_mb,
            available_ram_mb=available_ram_mb,
            total_cpus=total_cpus,
            reserved_cpus=reserved_cpus,
            allocatable_cpus=allocatable_cpus,
            allocated_cpus=allocated_cpus,
            available_cpus=available_cpus,
            profile=profile,
            ram_reserve_override_mb=ram_override_mb,
            cpu_reserve_override=cpu_override,
            allocations=allocations,
        )

    @classmethod
    def check_config_ceiling(
        cls,
        *,
        requested_ram_mb: int,
        requested_cpu_cores: float = 0.0,
        settings: AppSettings | None = None,
    ) -> HostResourceBudget:
        """Validate a single server configuration against host allocatable capacity."""
        cfg = settings or ConfigFactory.global_settings()
        total_ram_mb, total_cpus = cls.detect_host_capacity()
        ram_override_mb, cpu_override = _resolve_reserve_overrides(cfg)
        os_reserve_ram_mb, reserved_cpus = cls.compute_os_reserve(
            total_ram_mb,
            total_cpus,
            cfg.deployment_profile,
            ram_override_mb=ram_override_mb,
            cpu_override=cpu_override,
        )
        allocatable_ram_mb = max(0, total_ram_mb - os_reserve_ram_mb)
        allocatable_cpus = round(max(0.0, total_cpus - reserved_cpus), 2)

        if requested_ram_mb > allocatable_ram_mb or (
            requested_cpu_cores > 0 and requested_cpu_cores > allocatable_cpus
        ):
            raise InsufficientHostResourcesError(
                message=(
                    f"Server allocation ({requested_ram_mb} MB RAM"
                    + (f", {requested_cpu_cores:g} CPU cores" if requested_cpu_cores > 0 else "")
                    + f") exceeds host allocatable capacity ({allocatable_ram_mb} MB RAM, "
                    + f"{allocatable_cpus:g} CPU cores) after {os_reserve_ram_mb} MB OS reserve."
                ),
                requested_ram_mb=requested_ram_mb,
                available_ram_mb=allocatable_ram_mb,
                requested_cpu_cores=requested_cpu_cores,
                available_cpus=allocatable_cpus,
                details={
                    "profile": cfg.deployment_profile,
                    "total_ram_mb": total_ram_mb,
                    "os_reserve_ram_mb": os_reserve_ram_mb,
                    "allocatable_ram_mb": allocatable_ram_mb,
                },
            )

        return HostResourceBudget(
            total_ram_mb=total_ram_mb,
            os_reserve_ram_mb=os_reserve_ram_mb,
            allocatable_ram_mb=allocatable_ram_mb,
            allocated_ram_mb=0,
            available_ram_mb=allocatable_ram_mb,
            total_cpus=total_cpus,
            reserved_cpus=reserved_cpus,
            allocatable_cpus=allocatable_cpus,
            allocated_cpus=0.0,
            available_cpus=allocatable_cpus,
            profile=cfg.deployment_profile,
            ram_reserve_override_mb=ram_override_mb,
            cpu_reserve_override=cpu_override,
            allocations=[],
        )

    @classmethod
    async def check_admission(
        cls,
        db: AsyncSession | AsyncConnection,
        *,
        requested_ram_mb: int,
        requested_cpu_cores: float = 0.0,
        exclude_server_id: str | None = None,
        exclude_runtime_id: str | None = None,
        settings: AppSettings | None = None,
    ) -> HostResourceBudget:
        """Fail closed when starting a runtime would breach host RAM or CPU budget."""
        budget = await cls.get_budget(
            db,
            exclude_server_id=exclude_server_id,
            exclude_runtime_id=exclude_runtime_id,
            settings=settings,
        )
        ram_exhausted = requested_ram_mb > budget.available_ram_mb
        cpu_exhausted = requested_cpu_cores > 0 and requested_cpu_cores > budget.available_cpus
        if ram_exhausted or cpu_exhausted:
            raise InsufficientHostResourcesError(
                requested_ram_mb=requested_ram_mb,
                available_ram_mb=budget.available_ram_mb,
                requested_cpu_cores=requested_cpu_cores,
                available_cpus=budget.available_cpus,
                details={
                    "profile": budget.profile,
                    "total_ram_mb": budget.total_ram_mb,
                    "os_reserve_ram_mb": budget.os_reserve_ram_mb,
                    "allocated_ram_mb": budget.allocated_ram_mb,
                    "total_cpus": budget.total_cpus,
                    "reserved_cpus": budget.reserved_cpus,
                    "allocated_cpus": budget.allocated_cpus,
                },
            )
        return budget
