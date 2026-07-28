from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

from app.modules.health.domain.services import EnvironmentScanner
from app.modules.health.domain.value_objects import EnvironmentReport
from app.modules.server.infrastructure.providers import provider_factory

logger = logging.getLogger("mcs.health.environment")


class HostEnvironmentScanner(EnvironmentScanner):
    async def scan(self, server_id: str | None = None) -> EnvironmentReport:
        java_versions = _detect_java_versions()
        disk = _check_disk_space()
        memory = _check_memory()
        provider_ready, prereqs, errors = _check_provider_prerequisites(server_id)
        load_avg = _get_load_average()

        report = EnvironmentReport(
            java_versions=java_versions,
            available_disk_mb=disk,
            available_memory_mb=memory,
            provider_ready=provider_ready,
            prerequisites=prereqs,
            errors=errors,
        )

        if not report.is_capable:
            logger.warning("Environment scan: not fully capable (%d errors)", len(errors))

        return report


def _detect_java_versions() -> list[str]:
    versions: list[str] = []
    candidates = ["java", "/usr/lib/jvm/*/bin/java"]
    for cmd in ["java", "java17", "java21", "java8"]:
        try:
            result = subprocess.run(
                [cmd, "-version"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stderr or result.stdout
            match = re.search(r'(?:openjdk|java)\s+version\s+"([^"]+)"', output, re.IGNORECASE)
            if match:
                versions.append(f"{cmd}={match.group(1)}")
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            continue
    return versions


def _check_disk_space() -> float:
    try:
        usage = shutil.disk_usage("/")
        return usage.free / (1024 * 1024)
    except (FileNotFoundError, PermissionError, OSError):
        return 0.0


def _check_memory() -> float:
    try:
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                if len(parts) >= 4:
                    return float(parts[3])
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        pass
    return 0.0


def _check_provider_prerequisites(server_id: str | None) -> tuple[bool, dict[str, bool], list[str]]:
    prereqs: dict[str, bool] = {}
    errors: list[str] = []

    tmux_ok = shutil.which("tmux") is not None
    prereqs["tmux"] = tmux_ok
    if not tmux_ok:
        errors.append("tmux not found in PATH")

    if server_id:
        try:
            provider = provider_factory.get("local")
            ping_ok = False
            try:
                ping_ok = True
            except Exception:
                pass
            prereqs["provider_local"] = ping_ok
        except (ValueError, KeyError):
            prereqs["provider_local"] = False
            errors.append("local provider not registered")

    provider_ready = tmux_ok
    return provider_ready, prereqs, errors


def _get_load_average() -> float:
    try:
        if os.path.exists("/proc/loadavg"):
            with open("/proc/loadavg") as f:
                return float(f.read().split()[0])
    except (FileNotFoundError, PermissionError, OSError, IndexError, ValueError):
        pass
    return 0.0
