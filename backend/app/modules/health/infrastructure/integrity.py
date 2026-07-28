from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import AppSettings
from app.modules.health.domain.services import IntegrityChecker
from app.modules.health.domain.value_objects import IntegrityCheck, IntegrityReport
from app.modules.server.application.services.jar_service import resolve_server_dir

logger = logging.getLogger("mcs.health.integrity")


def _default_data_dir() -> Path:
    return Path(AppSettings().servers_data_dir)


def _resolve_path(server_id: str) -> Path | None:
    raw = resolve_server_dir(server_id)
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    fallback = _default_data_dir() / server_id
    if fallback.exists():
        return fallback
    return None


class FilesystemIntegrityChecker(IntegrityChecker):
    async def check(self, server_id: str, scope: str = "full") -> IntegrityReport:
        checks: list[IntegrityCheck] = []
        srvd = _resolve_path(server_id)

        if srvd is None:
            checks.append(IntegrityCheck(
                check_name="server_directory",
                severity="critical",
                status="error",
                detail=f"Server directory not found for {server_id}",
            ))
            return IntegrityReport(server_id=server_id, checks=checks, overall_status="fail")

        checks.append(IntegrityCheck(
            check_name="server_directory",
            severity="critical",
            status="pass",
            detail=str(srvd),
        ))

        _check_jar(srvd, checks)
        _check_properties(srvd, checks)
        _check_eula(srvd, checks)
        _check_world(srvd, checks)

        if scope == "full":
            _check_disk_space(srvd, checks)

        overall = _compute_overall(checks)
        return IntegrityReport(
            server_id=server_id,
            checks=checks,
            overall_status=overall,
            scope=scope,
        )


def _check_jar(srvd: Path, checks: list[IntegrityCheck]) -> None:
    jar_files = list(srvd.glob("*.jar"))
    if not jar_files:
        checks.append(IntegrityCheck(
            check_name="server_jar",
            severity="critical",
            status="fail",
            detail="No .jar files found in server directory",
        ))
        return
    server_jars = [f for f in jar_files if "server" in f.name.lower()]
    if server_jars:
        checks.append(IntegrityCheck(
            check_name="server_jar",
            severity="critical",
            status="pass",
            detail=f"Found server jar: {server_jars[0].name}",
        ))
    else:
        checks.append(IntegrityCheck(
            check_name="server_jar",
            severity="warning",
            status="warn",
            detail=f"Found jar(s): {', '.join(f.name for f in jar_files[:3])} — none named 'server'",
        ))


def _check_properties(srvd: Path, checks: list[IntegrityCheck]) -> None:
    props_path = srvd / "server.properties"
    if not props_path.is_file():
        checks.append(IntegrityCheck(
            check_name="server_properties",
            severity="critical",
            status="fail",
            detail="server.properties not found",
        ))
        return

    try:
        content = props_path.read_text(encoding="utf-8", errors="replace")
        required_keys = ["server-port", "level-name", "gamemode"]
        missing = [k for k in required_keys if f"{k}=" not in content]
        if missing:
            checks.append(IntegrityCheck(
                check_name="server_properties",
                severity="warning",
                status="warn",
                detail=f"Missing keys: {', '.join(missing)}",
            ))
        else:
            checks.append(IntegrityCheck(
                check_name="server_properties",
                severity="critical",
                status="pass",
            ))
    except (FileNotFoundError, PermissionError) as exc:
        checks.append(IntegrityCheck(
            check_name="server_properties",
            severity="critical",
            status="error",
            detail=str(exc),
        ))


def _check_eula(srvd: Path, checks: list[IntegrityCheck]) -> None:
    eula_path = srvd / "eula.txt"
    if not eula_path.is_file():
        checks.append(IntegrityCheck(
            check_name="eula",
            severity="warning",
            status="warn",
            detail="eula.txt not found — server may prompt on first start",
        ))
        return
    try:
        content = eula_path.read_text(encoding="utf-8", errors="replace")
        if "eula=true" in content:
            checks.append(IntegrityCheck(
                check_name="eula",
                severity="warning",
                status="pass",
                detail="EULA accepted",
            ))
        else:
            checks.append(IntegrityCheck(
                check_name="eula",
                severity="warning",
                status="warn",
                detail="EULA not accepted (eula=false or not set)",
            ))
    except (FileNotFoundError, PermissionError) as exc:
        checks.append(IntegrityCheck(
            check_name="eula",
            severity="warning",
            status="error",
            detail=str(exc),
        ))


def _check_world(srvd: Path, checks: list[IntegrityCheck]) -> None:
    props_path = srvd / "server.properties"
    level_name = "world"
    if props_path.is_file():
        try:
            for line in props_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("level-name="):
                    level_name = line.strip().split("=", 1)[1].strip()
                    break
        except (FileNotFoundError, PermissionError):
            pass

    world_dir = srvd / level_name
    if world_dir.is_dir():
        level_dat = world_dir / "level.dat"
        if level_dat.is_file():
            checks.append(IntegrityCheck(
                check_name="world_data",
                severity="warning",
                status="pass",
                detail=f"World '{level_name}' found with level.dat",
            ))
        else:
            checks.append(IntegrityCheck(
                check_name="world_data",
                severity="warning",
                status="warn",
                detail=f"World directory '{level_name}' exists but missing level.dat",
            ))
    else:
        checks.append(IntegrityCheck(
            check_name="world_data",
            severity="info",
            status="pass",
            detail="No world directory yet (first start pending)",
        ))


def _check_disk_space(srvd: Path, checks: list[IntegrityCheck]) -> None:
    try:
        stat = srvd.stat()
        import shutil
        usage = shutil.disk_usage(srvd.anchor if srvd.anchor else srvd.root)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1:
            checks.append(IntegrityCheck(
                check_name="disk_space",
                severity="critical",
                status="fail",
                detail=f"Only {free_gb:.1f} GB free on {srvd.anchor}",
            ))
        elif free_gb < 5:
            checks.append(IntegrityCheck(
                check_name="disk_space",
                severity="warning",
                status="warn",
                detail=f"Low disk space: {free_gb:.1f} GB free on {srvd.anchor}",
            ))
        else:
            checks.append(IntegrityCheck(
                check_name="disk_space",
                severity="info",
                status="pass",
                detail=f"{free_gb:.1f} GB free on disk",
            ))
    except (FileNotFoundError, PermissionError, OSError) as exc:
        checks.append(IntegrityCheck(
            check_name="disk_space",
            severity="warning",
            status="error",
            detail=str(exc),
        ))


def _compute_overall(checks: list[IntegrityCheck]) -> str:
    for c in checks:
        if c.severity == "critical" and c.status in ("fail", "error"):
            return "fail"
    for c in checks:
        if c.status in ("warn", "error"):
            return "warn"
    return "pass"
