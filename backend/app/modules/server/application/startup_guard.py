from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.startup.guard")


@dataclass
class StartupGuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def check_startup_readiness(
    server_id: str,
    root_path: str | None = None,
) -> StartupGuardResult:
    from app.modules.health.infrastructure.environment import HostEnvironmentScanner
    from app.modules.health.infrastructure.integrity import FilesystemIntegrityChecker

    reasons: list[str] = []
    warnings: list[str] = []

    checker = FilesystemIntegrityChecker()
    try:
        report = await checker.check(server_id, scope="quick", root_path=root_path)
        if report.has_failures:
            for c in report.checks:
                if c.status in ("fail", "error") and c.severity == "critical":
                    if c.check_name == "server_directory":
                        warnings.append(f"Integrity: {c.check_name} — {c.detail or c.status}")
                    else:
                        reasons.append(f"Integrity: {c.check_name} — {c.detail or c.status}")
            for c in report.checks:
                if c.status == "warn":
                    warnings.append(f"Integrity: {c.check_name} — {c.detail or c.status}")
    except Exception as exc:
        reasons.append(f"Integrity check failed: {exc}")
        logger.exception("Integrity check error for %s", server_id)

    env_scanner = HostEnvironmentScanner()
    try:
        env_report = await env_scanner.scan(server_id)
        if not env_report.is_capable and env_report.errors:
            for err in env_report.errors:
                reasons.append(f"Environment: {err}")
        if env_report.available_disk_mb < 1024:
            reasons.append(
                f"Environment: low disk space ({env_report.available_disk_mb:.0f} MB free)"
            )
        elif env_report.available_disk_mb < 5120:
            warnings.append(
                f"Environment: disk space warning ({env_report.available_disk_mb:.0f} MB free)"
            )
        if not env_report.java_versions and not env_report.prerequisites.get("docker"):
            reasons.append("Environment: no Java runtime detected")
    except Exception as exc:
        reasons.append(f"Environment scan failed: {exc}")
        logger.exception("Environment scan error for %s", server_id)

    return StartupGuardResult(
        allowed=len(reasons) == 0,
        reasons=reasons,
        warnings=warnings,
    )
