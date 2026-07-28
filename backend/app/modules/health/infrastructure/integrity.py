from __future__ import annotations

import hashlib
import logging
import stat
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.modules.health.domain.services import IntegrityChecker
from app.modules.health.domain.value_objects import IntegrityCheck, IntegrityReport
from app.modules.health.domain.events import IntegrityCheckPassedEvent, IntegrityCheckFailedEvent
from app.modules.health.domain.repository import IntegrityRepository
from app.modules.server.application.services.jar_service import resolve_server_dir

logger = logging.getLogger("mcs.health.integrity")


def _hash_file(filepath: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _default_data_dir() -> Path:
    return Path(AppSettings().servers_data_dir)


def _resolve_path(server_id: str) -> Path | None:
    raw = resolve_server_dir(server_id)
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    short_id = server_id[:8]
    if short_id:
        data_dir = _default_data_dir()
        for candidate in data_dir.glob(f"*-{short_id}"):
            if candidate.is_dir():
                return candidate
    return None


class FilesystemIntegrityChecker(IntegrityChecker):
    def __init__(
        self,
        event_bus: EventBus | None = None,
        integrity_repo: IntegrityRepository | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._integrity_repo = integrity_repo

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
            report = IntegrityReport(server_id=server_id, checks=checks, overall_status="fail")
            await self._emit_events(report)
            return report

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
        _check_permissions(srvd, checks)
        _check_symlinks(srvd, checks)
        _check_plugins_dir(srvd, checks)
        _check_db_path_mismatch(srvd, checks)

        baselines: list[dict] = []
        if self._integrity_repo:
            baselines = await self._integrity_repo.get_baselines(server_id)
        _check_file_hashes(srvd, checks, baselines)

        if scope == "full":
            _check_disk_space(srvd, checks)

        overall = _compute_overall(checks)
        report = IntegrityReport(
            server_id=server_id,
            checks=checks,
            overall_status=overall,
            scope=scope,
        )
        await self._emit_events(report)
        return report

    async def capture_baseline(
        self,
        server_id: str,
    ) -> IntegrityReport:
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

        now = datetime.now(timezone.utc)
        target_files = _get_baseline_targets(srvd)

        if not target_files:
            checks.append(IntegrityCheck(
                check_name="baseline_capture",
                severity="warning",
                status="warn",
                detail="No files found to baseline",
            ))
            return IntegrityReport(server_id=server_id, checks=checks, overall_status="warn")

        captured = 0
        for rel_path, full_path in target_files:
            file_hash = _hash_file(full_path)
            if file_hash is None:
                checks.append(IntegrityCheck(
                    check_name="baseline_capture",
                    severity="warning",
                    status="warn",
                    detail=f"Cannot hash {rel_path}",
                    file_path=rel_path,
                ))
                continue
            if self._integrity_repo:
                await self._integrity_repo.save_baseline(
                    server_id=server_id,
                    file_path=str(rel_path),
                    file_name=full_path.name,
                    file_hash=file_hash,
                    hash_algorithm="sha256",
                )
            checks.append(IntegrityCheck(
                check_name="baseline_capture",
                severity="info",
                status="pass",
                detail=f"Baseline captured: {rel_path} → {file_hash[:16]}...",
                file_path=rel_path,
                actual_hash=file_hash,
            ))
            captured += 1

        overall = "pass" if captured > 0 else "warn"
        return IntegrityReport(
            server_id=server_id,
            checks=checks,
            overall_status=overall,
            scope="baseline",
        )

    async def _emit_events(self, report: IntegrityReport) -> None:
        if self._event_bus is None:
            return
        for c in report.checks:
            if c.status == "pass":
                event = IntegrityCheckPassedEvent(
                    server_id=report.server_id,
                    check_name=c.check_name,
                    scope=report.scope,
                )
            elif c.status in ("fail", "error"):
                event = IntegrityCheckFailedEvent(
                    server_id=report.server_id,
                    check_name=c.check_name,
                    severity=c.severity,
                    detail=c.detail,
                    scope=report.scope,
                )
            else:
                continue
            await self._event_bus.publish(event)


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


def _check_permissions(srvd: Path, checks: list[IntegrityCheck]) -> None:
    world_writable: list[str] = []
    for entry in srvd.rglob("*"):
        if entry.is_file():
            try:
                mode = entry.stat().st_mode
                if mode & stat.S_IWOTH:
                    rel = entry.relative_to(srvd)
                    world_writable.append(str(rel))
            except (FileNotFoundError, PermissionError, OSError):
                pass
    if world_writable:
        checks.append(IntegrityCheck(
            check_name="permissions",
            severity="warning",
            status="warn",
            detail=f"World-writable files: {', '.join(world_writable[:5])}",
            file_path=",".join(world_writable[:5]),
        ))
    else:
        checks.append(IntegrityCheck(
            check_name="permissions",
            severity="info",
            status="pass",
            detail="No world-writable files detected",
        ))


def _check_symlinks(srvd: Path, checks: list[IntegrityCheck]) -> None:
    for entry in srvd.rglob("*"):
        if entry.is_symlink():
            try:
                target = entry.readlink()
                if not target.is_absolute():
                    target = (entry.parent / target).resolve()
                srvd_resolved = srvd.resolve()
                if not str(target).startswith(str(srvd_resolved)):
                    rel = entry.relative_to(srvd)
                    checks.append(IntegrityCheck(
                        check_name="symlinks",
                        severity="critical",
                        status="fail",
                        detail=f"Symlink escapes server dir: {rel} → {target}",
                        file_path=str(rel),
                    ))
                    return
            except (FileNotFoundError, PermissionError, OSError):
                continue
    checks.append(IntegrityCheck(
        check_name="symlinks",
        severity="info",
        status="pass",
        detail="No dangerous symlinks detected",
    ))


def _check_plugins_dir(srvd: Path, checks: list[IntegrityCheck]) -> None:
    plugins_dir = srvd / "plugins"
    if not plugins_dir.is_dir():
        checks.append(IntegrityCheck(
            check_name="plugins_directory",
            severity="info",
            status="pass",
            detail="No plugins directory yet",
        ))
        return
    jar_count = len(list(plugins_dir.glob("*.jar")))
    if jar_count == 0:
        checks.append(IntegrityCheck(
            check_name="plugins_directory",
            severity="warning",
            status="warn",
            detail="Plugins directory exists but is empty",
        ))
    else:
        checks.append(IntegrityCheck(
            check_name="plugins_directory",
            severity="info",
            status="pass",
            detail=f"Plugins directory contains {jar_count} plugin(s)",
        ))


def _check_db_path_mismatch(srvd: Path, checks: list[IntegrityCheck]) -> None:
    props_path = srvd / "server.properties"
    if not props_path.is_file():
        return
    try:
        level_name = "world"
        for line in props_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("level-name="):
                level_name = line.strip().split("=", 1)[1].strip()
                break
        world_dir = srvd / level_name
        if world_dir.is_dir():
            checks.append(IntegrityCheck(
                check_name="db_path_mismatch",
                severity="info",
                status="pass",
                detail=f"World directory '{level_name}' matches level-name in properties",
            ))
        else:
            checks.append(IntegrityCheck(
                check_name="db_path_mismatch",
                severity="warning",
                status="warn",
                detail=f"level-name='{level_name}' but no '{level_name}' directory exists",
            ))
    except (FileNotFoundError, PermissionError, OSError):
        pass


def _get_baseline_targets(srvd: Path) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    important = ["server.jar", "server.properties", "eula.txt", "bukkit.yml", "spigot.yml", "paper.yml"]
    for name in important:
        p = srvd / name
        if p.is_file():
            targets.append((name, p))
    for jar in sorted(srvd.glob("*.jar")):
        rel = str(jar.relative_to(srvd))
        if rel not in [t[0] for t in targets]:
            targets.append((rel, jar))
    return targets


def _check_file_hashes(srvd: Path, checks: list[IntegrityCheck], baselines: list[dict]) -> None:
    if not baselines:
        checks.append(IntegrityCheck(
            check_name="file_hashes",
            severity="info",
            status="pass",
            detail="No baselines recorded yet — run baseline capture first",
        ))
        return

    baseline_map: dict[str, str] = {}
    for b in baselines:
        fp = b.get("file_path", "")
        fh = b.get("file_hash", "")
        if fp and fh:
            baseline_map[fp] = fh

    tampered: list[str] = []
    new_files: list[str] = []
    ok_count = 0

    for rel_path, full_path in _get_baseline_targets(srvd):
        if rel_path in baseline_map:
            current_hash = _hash_file(full_path)
            if current_hash is None:
                tampered.append(f"{rel_path} (unreadable)")
            elif current_hash != baseline_map[rel_path]:
                tampered.append(rel_path)
                checks.append(IntegrityCheck(
                    check_name="file_hashes",
                    severity="critical",
                    status="fail",
                    detail=f"{rel_path} hash mismatch (was {baseline_map[rel_path][:16]}…, now {current_hash[:16]}…)",
                    file_path=rel_path,
                    expected_hash=baseline_map[rel_path],
                    actual_hash=current_hash,
                ))
            else:
                ok_count += 1
        else:
            new_files.append(rel_path)

    for rel_path in baseline_map:
        if rel_path not in [t[0] for t in _get_baseline_targets(srvd)]:
            new_files.append(f"{rel_path} (baseline exists but file missing)")

    if ok_count > 0:
        checks.append(IntegrityCheck(
            check_name="file_hashes",
            severity="info",
            status="pass",
            detail=f"{ok_count} file(s) match baseline",
        ))
    if new_files and not tampered:
        checks.append(IntegrityCheck(
            check_name="file_hashes",
            severity="warning",
            status="warn",
            detail=f"New/changed files without baseline: {', '.join(new_files[:5])}",
        ))


def _check_orphans(
    known_server_ids: set[str],
    checks: list[IntegrityCheck],
) -> None:
    data_dir = _default_data_dir()
    if not data_dir.is_dir():
        return
    orphans: list[str] = []
    for candidate in sorted(data_dir.iterdir()):
        if not candidate.is_dir():
            continue
        dir_name = candidate.name
        parts = dir_name.rsplit("-", 1)
        if len(parts) != 2:
            continue
        slug, short_id = parts
        if len(short_id) != 8:
            continue
        if short_id not in known_server_ids:
            orphans.append(dir_name)
    if orphans:
        checks.append(IntegrityCheck(
            check_name="orphan_directories",
            severity="warning",
            status="warn",
            detail=f"Orphan directories: {', '.join(orphans[:10])}",
        ))
    else:
        checks.append(IntegrityCheck(
            check_name="orphan_directories",
            severity="info",
            status="pass",
            detail="No orphan directories detected",
        ))


def _compute_overall(checks: list[IntegrityCheck]) -> str:
    for c in checks:
        if c.severity == "critical" and c.status in ("fail", "error"):
            return "fail"
    for c in checks:
        if c.status in ("warn", "error"):
            return "warn"
    return "pass"
