from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import psutil

from app.core.exceptions import BotRunInsufficientResourcesError
from app.core.settings_store import get_live_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceCheckResult:
    passed: bool
    required_ram_mb: int
    available_ram_mb: int
    required_cores: int
    available_cores: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "required_ram_mb": self.required_ram_mb,
            "available_ram_mb": self.available_ram_mb,
            "required_cores": self.required_cores,
            "available_cores": self.available_cores,
            "message": self.message,
        }


class ResourcePreflightProbe:
    """Preflight check for system headroom before starting a test container and bot run.

    Enforces Design Spec §3.5.7:
    Serves as the SOLE guard against system overload — no artificial numeric ceilings
    are placed on bot_count or duration. The run proceeds if physical resources suffice.
    """

    MODDED_SERVER_TYPES: frozenset[str] = frozenset(
        {"forge", "neoforge", "fabric", "quilt", "mohist", "arclight", "catserver"}
    )

    @classmethod
    def calculate_required_resources(
        cls,
        bot_count: int,
        server_type: str = "vanilla",
        custom_floor_mb: int | None = None,
        custom_floor_cores: int | None = None,
    ) -> tuple[int, int]:
        """Calculates (required_ram_mb, required_cores) based on bot count and server type."""
        try:
            live = get_live_settings()
            base_floor_mb = custom_floor_mb or getattr(live, "bot_resource_floor_mb", 4096)
            base_floor_cores = custom_floor_cores or getattr(live, "bot_resource_floor_cores", 2)
        except Exception:
            base_floor_mb = custom_floor_mb or 4096
            base_floor_cores = custom_floor_cores or 2

        # Modded servers require higher memory floor for Forge/Fabric JVM + modpacks
        modded_overhead_mb = 2048 if server_type.lower() in cls.MODDED_SERVER_TYPES else 0

        # Scale proportionally: 50MB per bot beyond the baseline 10 bots
        additional_bots = max(0, bot_count - 10)
        bot_ram_mb = additional_bots * 50

        # Total RAM requirement
        required_ram_mb = base_floor_mb + modded_overhead_mb + bot_ram_mb

        # Core requirement: 1 additional core for every 50 bots beyond 10
        additional_cores = additional_bots // 50
        required_cores = base_floor_cores + additional_cores

        return required_ram_mb, required_cores

    @classmethod
    def check_headroom(
        cls,
        bot_count: int,
        server_type: str = "vanilla",
        custom_floor_mb: int | None = None,
        custom_floor_cores: int | None = None,
    ) -> ResourceCheckResult:
        """Inspects physical system headroom and returns a ResourceCheckResult."""
        req_ram_mb, req_cores = cls.calculate_required_resources(
            bot_count,
            server_type=server_type,
            custom_floor_mb=custom_floor_mb,
            custom_floor_cores=custom_floor_cores,
        )

        vm = psutil.virtual_memory()
        avail_ram_mb = int(vm.available / (1024 * 1024))
        avail_cores = os.cpu_count() or psutil.cpu_count(logical=True) or 1

        passed = (avail_ram_mb >= req_ram_mb) and (avail_cores >= req_cores)

        if passed:
            msg = (
                f"Sufficient headroom: {avail_ram_mb}MB RAM available (required: {req_ram_mb}MB), "
                f"{avail_cores} CPU cores (required: {req_cores})."
            )
        else:
            reasons = []
            if avail_ram_mb < req_ram_mb:
                reasons.append(f"RAM {avail_ram_mb}MB < required {req_ram_mb}MB")
            if avail_cores < req_cores:
                reasons.append(f"Cores {avail_cores} < required {req_cores}")
            msg = f"Insufficient headroom for {bot_count}-bot run ({server_type}): " + ", ".join(
                reasons
            )

        return ResourceCheckResult(
            passed=passed,
            required_ram_mb=req_ram_mb,
            available_ram_mb=avail_ram_mb,
            required_cores=req_cores,
            available_cores=avail_cores,
            message=msg,
        )

    @classmethod
    def assert_sufficient_resources(
        cls,
        bot_count: int,
        server_type: str = "vanilla",
        custom_floor_mb: int | None = None,
        custom_floor_cores: int | None = None,
    ) -> ResourceCheckResult:
        """Validates headroom and raises BotRunInsufficientResourcesError if insufficient."""
        res = cls.check_headroom(
            bot_count,
            server_type=server_type,
            custom_floor_mb=custom_floor_mb,
            custom_floor_cores=custom_floor_cores,
        )
        if not res.passed:
            raise BotRunInsufficientResourcesError(
                message=res.message,
                details=res.to_dict(),
            )
        return res
