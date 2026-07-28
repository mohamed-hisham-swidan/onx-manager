from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.modules.health.domain.value_objects import EvidenceBundle
from app.modules.health.infrastructure.environment import HostEnvironmentScanner

logger = logging.getLogger("mcs.health.evidence")


class LogBasedEvidenceCollector:
    MAX_LOG_LINES: int = 200
    MAX_CRASH_REPORTS: int = 5

    def __init__(self, server_dir: str | None = None) -> None:
        self._server_dir = Path(server_dir) if server_dir else None

    async def collect(self, server_id: str, server_dir: str | None = None) -> EvidenceBundle:
        resolved_dir = Path(server_dir) if server_dir else self._server_dir
        if not resolved_dir or not resolved_dir.is_dir():
            return EvidenceBundle(
                server_id=server_id,
                evidence_id=uuid.uuid4().hex,
                collection_errors=[f"Server directory not found: {resolved_dir}"],
            )

        log_tail = self._read_log_tail(resolved_dir)
        crash_reports = self._read_crash_reports(resolved_dir)
        snapshot = await self._capture_system_snapshot()
        provider_diag = self._read_provider_diagnostics(resolved_dir)
        errors: list[str] = []

        return EvidenceBundle(
            server_id=server_id,
            evidence_id=uuid.uuid4().hex,
            latest_log_tail=log_tail,
            crash_reports=crash_reports,
            provider_diagnostics=provider_diag,
            system_snapshot=snapshot,
            collection_errors=errors,
            timestamp=datetime.now(timezone.utc),
        )

    def _read_log_tail(self, server_dir: Path) -> list[str]:
        log_dir = server_dir / "logs"
        latest_log = log_dir / "latest.log"
        if not latest_log.is_file():
            return []
        try:
            lines: list[str] = []
            with open(latest_log, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [l.rstrip("\n\r") for l in lines[-self.MAX_LOG_LINES:]]
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.warning("Cannot read log %s: %s", latest_log, exc)
            return []

    def _read_crash_reports(self, server_dir: Path) -> list[dict]:
        crash_dir = server_dir / "crash-reports"
        if not crash_dir.is_dir():
            return []
        try:
            reports: list[dict] = []
            files = sorted(crash_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:self.MAX_CRASH_REPORTS]:
                if f.is_file() and f.suffix == ".txt":
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        reports.append({
                            "filename": f.name,
                            "size_bytes": f.stat().st_size,
                            "content": content,
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        })
                    except (FileNotFoundError, PermissionError, OSError) as exc:
                        reports.append({
                            "filename": f.name,
                            "error": str(exc),
                        })
            return reports
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.warning("Cannot read crash-reports directory %s: %s", crash_dir, exc)
            return []

    async def _capture_system_snapshot(self) -> dict:
        snapshot: dict = {}
        try:
            total, used, free = shutil.disk_usage("/")
            snapshot["disk_total_gb"] = round(total / (1024**3), 1)
            snapshot["disk_used_gb"] = round(used / (1024**3), 1)
            snapshot["disk_free_gb"] = round(free / (1024**3), 1)
        except Exception:
            pass

        try:
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        meminfo[parts[0].strip()] = parts[1].strip()
            snapshot["mem_total_kb"] = meminfo.get("MemTotal")
            snapshot["mem_available_kb"] = meminfo.get("MemAvailable")
        except Exception:
            pass

        try:
            load = os.getloadavg()
            snapshot["load_1m"] = round(load[0], 2)
            snapshot["load_5m"] = round(load[1], 2)
            snapshot["load_15m"] = round(load[2], 2)
        except Exception:
            pass

        try:
            scanner = HostEnvironmentScanner()
            env_report = await scanner.scan()
            snapshot["java_versions"] = env_report.java_versions
            snapshot["host_environment"] = {
                "provider_ready": env_report.provider_ready,
                "prerequisites": env_report.prerequisites,
            }
        except Exception:
            pass

        snapshot["captured_at"] = datetime.now(timezone.utc).isoformat()
        return snapshot

    def _read_provider_diagnostics(self, server_dir: Path) -> dict | None:
        diag_file = server_dir / ".provider-diagnostics.json"
        if not diag_file.is_file():
            return None
        try:
            return json.loads(diag_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as exc:
            logger.warning("Cannot read provider diagnostics %s: %s", diag_file, exc)
            return None
