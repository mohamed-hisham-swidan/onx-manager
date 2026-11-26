from __future__ import annotations

import asyncio
import contextlib
import contextvars
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from app.core.event_bus import EventBus
from app.modules.server.domain.events import ForgeProvisionProgressEvent
from app.modules.shared.value_objects import ServerId

PROVISIONING_STEPS: tuple[tuple[str, str], ...] = (
    ("prepare_workspace", "Prepare Workspace"),
    ("download_core", "Download Server Core"),
    ("verify_and_install", "Verify & Install"),
    ("prepare_runtime", "Prepare Runtime"),
    ("finalize", "Finalize"),
)

_STEP_PROGRESS_RANGES: dict[str, tuple[int, int]] = {
    "prepare_workspace": (0, 15),
    "download_core": (15, 55),
    "verify_and_install": (55, 85),
    "prepare_runtime": (85, 95),
    "finalize": (95, 100),
}

_INSTALLER_STAGE_LABELS: dict[str, str] = {
    "downloading_libraries": "Downloading loader libraries...",
    "downloading_forge": "Downloading loader artifacts...",
    "installing_profile": "Installing loader profile...",
    "installing_minecraft": "Patching and installing Minecraft server...",
    "installing": "Running loader installer...",
}

_MAX_SNAPSHOTS = 200
_MAX_ACTIVITY_ITEMS = 60
_WS_THROTTLE_SECONDS = 0.2


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_bytes_human(num_bytes: int | float | None) -> str:
    if num_bytes is None or num_bytes < 0:
        return "0 B"
    val = float(num_bytes)
    if val >= 1024 * 1024 * 1024:
        return f"{val / (1024 * 1024 * 1024):.2f} GB"
    if val >= 1024 * 1024:
        return f"{val / (1024 * 1024):.1f} MB"
    if val >= 1024:
        return f"{val / 1024:.0f} KB"
    return f"{int(val)} B"


class ProvisioningTelemetryStore:
    """In-memory bounded store of latest server provisioning snapshots."""

    _snapshots: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @classmethod
    def set_snapshot(cls, server_id: str, snapshot: dict[str, Any]) -> None:
        sid = str(server_id)
        if sid in cls._snapshots:
            cls._snapshots.move_to_end(sid)
        cls._snapshots[sid] = snapshot
        while len(cls._snapshots) > _MAX_SNAPSHOTS:
            # Prefer evicting oldest terminal snapshot first
            evict_key: str | None = None
            for k, v in cls._snapshots.items():
                if v.get("status") in ("completed", "failed"):
                    evict_key = k
                    break
            if evict_key is None:
                cls._snapshots.popitem(last=False)
            else:
                cls._snapshots.pop(evict_key, None)

    @classmethod
    def get_snapshot(cls, server_id: str) -> dict[str, Any] | None:
        snap = cls._snapshots.get(str(server_id))
        if snap is None:
            return None
        # Return a shallow copy with live elapsed_ms if still running
        copy_snap = dict(snap)
        if copy_snap.get("status") == "running":
            started_mono = copy_snap.get("_started_mono")
            if isinstance(started_mono, (int, float)):
                copy_snap["elapsed_ms"] = max(
                    int(copy_snap.get("elapsed_ms") or 0),
                    int((time.monotonic() - started_mono) * 1000),
                )
        copy_snap.pop("_started_mono", None)
        return copy_snap

    @classmethod
    def clear_snapshot(cls, server_id: str) -> None:
        cls._snapshots.pop(str(server_id), None)

    @classmethod
    def clear_all(cls) -> None:
        cls._snapshots.clear()


class ProvisioningProgressTracker:
    """Tracks structured 5-stage provisioning telemetry and emits WS events."""

    def __init__(
        self,
        server_id: str,
        server_name: str,
        server_type: str,
        minecraft_version: str,
        mode: str = "simple",
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_id = str(server_id)
        self._server_name = server_name
        self._server_type = server_type
        self._minecraft_version = minecraft_version
        self._mode = mode
        self._event_bus = event_bus

        self._started_mono = time.monotonic()
        self._started_at = _utc_now_iso()
        self._finished_at: str | None = None
        self._elapsed_ms = 0
        self._status = "running"
        self._current_step_id: str | None = None
        self._percent = 0
        self._message = "Starting server provisioning..."
        self._error: str | None = None
        self._failed_step_id: str | None = None
        self._active_transfer: dict[str, Any] | None = None
        self._activity: list[dict[str, str]] = []
        self._artifacts: list[dict[str, str]] = []
        self._last_ws_emit_mono = 0.0
        self._last_installer_stage: str | None = None
        self._step_started_mono: dict[str, float] = {}

        self._steps: list[dict[str, Any]] = [
            {
                "id": step_id,
                "label": label,
                "status": "pending",
                "detail": None,
                "started_at": None,
                "completed_at": None,
                "elapsed_ms": 0,
            }
            for step_id, label in PROVISIONING_STEPS
        ]
        self._persist_snapshot()

    def _find_step(self, step_id: str) -> dict[str, Any] | None:
        for step in self._steps:
            if step["id"] == step_id:
                return step
        return None

    def _elapsed_now_ms(self) -> int:
        return max(0, int((time.monotonic() - self._started_mono) * 1000))

    def _build_snapshot(self, *, include_internal: bool = False) -> dict[str, Any]:
        if self._status == "running":
            self._elapsed_ms = self._elapsed_now_ms()
        snap: dict[str, Any] = {
            "server_id": self._server_id,
            "server_name": self._server_name,
            "server_type": self._server_type,
            "minecraft_version": self._minecraft_version,
            "mode": self._mode,
            "status": self._status,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "elapsed_ms": self._elapsed_ms,
            "current_step_id": self._current_step_id,
            "percent": self._percent,
            "message": self._message,
            "error": self._error,
            "failed_step_id": self._failed_step_id,
            "steps": [dict(s) for s in self._steps],
            "active_transfer": dict(self._active_transfer) if self._active_transfer else None,
            "activity": [dict(a) for a in self._activity],
            "artifacts": [dict(a) for a in self._artifacts],
        }
        if include_internal:
            snap["_started_mono"] = self._started_mono
        return snap

    def _persist_snapshot(self) -> dict[str, Any]:
        internal = self._build_snapshot(include_internal=True)
        ProvisioningTelemetryStore.set_snapshot(self._server_id, internal)
        public = dict(internal)
        public.pop("_started_mono", None)
        return public

    def snapshot(self) -> dict[str, Any]:
        return self._persist_snapshot()

    async def _publish_ws(
        self,
        stage: str,
        percent: int | None,
        message: str,
        *,
        force: bool = False,
    ) -> None:
        snap = self._persist_snapshot()
        if self._event_bus is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_ws_emit_mono) < _WS_THROTTLE_SECONDS:
            return
        self._last_ws_emit_mono = now
        with contextlib.suppress(Exception):
            await self._event_bus.publish(
                ForgeProvisionProgressEvent(
                    server_id=ServerId(self._server_id),
                    stage=stage,
                    percent=percent,
                    message=message,
                    snapshot=snap,
                )
            )

    def add_activity(self, message: str, level: str = "info") -> None:
        clean = message.strip()
        if not clean:
            return
        if self._activity and self._activity[-1]["message"] == clean:
            return
        self._activity.append(
            {
                "timestamp": _utc_now_iso(),
                "message": clean,
                "level": level,
            }
        )
        if len(self._activity) > _MAX_ACTIVITY_ITEMS:
            self._activity = self._activity[-_MAX_ACTIVITY_ITEMS:]
        self._persist_snapshot()

    def set_artifacts(self, artifacts: list[dict[str, str]]) -> None:
        self._artifacts = [dict(item) for item in artifacts]
        self._persist_snapshot()

    async def start_step(
        self,
        step_id: str,
        message: str,
        *,
        detail: str | None = None,
        activity_message: str | None = None,
    ) -> None:
        now_iso = _utc_now_iso()
        now_mono = time.monotonic()
        # Complete any earlier running step cleanly
        for step in self._steps:
            if step["id"] == step_id:
                break
            if step["status"] == "running":
                step["status"] = "completed"
                step["completed_at"] = now_iso
                started_m = self._step_started_mono.get(step["id"], now_mono)
                step["elapsed_ms"] = max(0, int((now_mono - started_m) * 1000))

        target = self._find_step(step_id)
        if target is not None:
            if target["status"] != "running":
                target["started_at"] = target["started_at"] or now_iso
                self._step_started_mono.setdefault(step_id, now_mono)
            target["status"] = "running"
            if detail is not None:
                target["detail"] = detail

        self._current_step_id = step_id
        self._message = message
        low, _high = _STEP_PROGRESS_RANGES.get(step_id, (0, 100))
        self._percent = max(self._percent, low)
        if activity_message:
            self.add_activity(activity_message, level="info")
        await self._publish_ws(step_id, self._percent, message, force=True)

    async def complete_step(
        self,
        step_id: str,
        *,
        detail: str | None = None,
        activity_message: str | None = None,
        level: str = "success",
    ) -> None:
        now_iso = _utc_now_iso()
        now_mono = time.monotonic()
        target = self._find_step(step_id)
        if target is not None:
            if target["started_at"] is None:
                target["started_at"] = now_iso
                self._step_started_mono.setdefault(step_id, now_mono)
            target["status"] = "completed"
            target["completed_at"] = now_iso
            started_m = self._step_started_mono.get(step_id, now_mono)
            target["elapsed_ms"] = max(1, int((now_mono - started_m) * 1000))
            if detail is not None:
                target["detail"] = detail

        if step_id in ("download_core", "verify_and_install"):
            self._active_transfer = None
        _low, high = _STEP_PROGRESS_RANGES.get(step_id, (0, 100))
        self._percent = max(self._percent, high)
        if activity_message:
            self.add_activity(activity_message, level=level)
        await self._publish_ws(step_id, self._percent, detail or self._message, force=True)

    async def skip_step(self, step_id: str, *, detail: str | None = None) -> None:
        target = self._find_step(step_id)
        if target is not None:
            target["status"] = "skipped"
            target["completed_at"] = _utc_now_iso()
            if detail is not None:
                target["detail"] = detail
        _low, high = _STEP_PROGRESS_RANGES.get(step_id, (0, 100))
        self._percent = max(self._percent, high)
        self._persist_snapshot()

    async def record_download_progress(
        self,
        filename: str,
        bytes_downloaded: int,
        total_bytes: int | None,
        speed_bps: float | None,
        eta_seconds: float | None,
        file_index: int = 1,
        file_total: int = 1,
    ) -> None:
        pct: float | None = None
        if total_bytes is not None and total_bytes > 0:
            pct = round(min(100.0, max(0.0, (bytes_downloaded / total_bytes) * 100.0)), 1)

        self._active_transfer = {
            "filename": filename,
            "bytes_downloaded": int(bytes_downloaded),
            "total_bytes": int(total_bytes) if total_bytes is not None else None,
            "percent": pct,
            "speed_bps": round(speed_bps, 1) if speed_bps is not None else None,
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
            "file_index": file_index,
            "file_total": file_total,
            "phase": "downloading",
        }

        if pct is not None:
            low, high = _STEP_PROGRESS_RANGES["download_core"]
            self._percent = int(low + ((high - low) * (pct / 100.0)))
            done_str = format_bytes_human(bytes_downloaded)
            total_str = format_bytes_human(total_bytes)
            detail = f"{filename} · {int(pct)}% ({done_str} / {total_str})"
        else:
            detail = f"{filename} · {format_bytes_human(bytes_downloaded)} downloaded"

        step = self._find_step("download_core")
        if step is not None and step["status"] == "running":
            step["detail"] = detail
        self._message = f"Downloading {filename}..."

        is_complete = total_bytes is not None and bytes_downloaded >= total_bytes
        await self._publish_ws(
            "download_core",
            self._percent,
            detail,
            force=is_complete or bytes_downloaded == 0,
        )

    async def update_installer_progress(
        self,
        stage: str,
        percent: int | None,
        message: str,
        *,
        installer_filename: str = "installer.jar",
    ) -> None:
        step = self._find_step("verify_and_install")
        friendly = _INSTALLER_STAGE_LABELS.get(stage) or message or "Installing loader libraries..."
        if step is not None:
            if step["status"] == "pending":
                await self.start_step("verify_and_install", friendly, detail=friendly)
            else:
                step["detail"] = friendly

        self._active_transfer = {
            "filename": installer_filename,
            "bytes_downloaded": 0,
            "total_bytes": None,
            "percent": float(percent) if percent is not None else None,
            "speed_bps": None,
            "eta_seconds": None,
            "file_index": 1,
            "file_total": 1,
            "phase": "installing",
        }
        self._message = friendly
        if percent is not None:
            low, high = _STEP_PROGRESS_RANGES["verify_and_install"]
            clamped = max(0, min(100, int(percent)))
            self._percent = max(self._percent, int(low + ((high - low) * (clamped / 100.0))))

        if stage and stage != "unknown" and stage != self._last_installer_stage:
            self._last_installer_stage = stage
            if stage in _INSTALLER_STAGE_LABELS:
                self.add_activity(_INSTALLER_STAGE_LABELS[stage], level="info")

        await self._publish_ws(stage or "verify_and_install", self._percent, friendly)

    async def complete(
        self,
        message: str = "Server created and ready to start",
        artifacts: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        now_iso = _utc_now_iso()
        now_mono = time.monotonic()
        for step in self._steps:
            if step["status"] in ("pending", "running"):
                if step["started_at"] is None:
                    step["started_at"] = now_iso
                started_m = self._step_started_mono.get(step["id"], now_mono)
                step["elapsed_ms"] = max(
                    int(step.get("elapsed_ms") or 0),
                    int((now_mono - started_m) * 1000),
                )
                step["status"] = "completed"
                step["completed_at"] = now_iso
        if artifacts is not None:
            self._artifacts = [dict(item) for item in artifacts]
        self._status = "completed"
        self._finished_at = now_iso
        self._elapsed_ms = self._elapsed_now_ms()
        self._current_step_id = "finalize"
        self._percent = 100
        self._message = message
        self._active_transfer = None
        self.add_activity(message, level="success")
        await self._publish_ws("success", 100, message, force=True)
        return self._persist_snapshot()

    async def fail(self, error: str, *, step_id: str | None = None) -> dict[str, Any]:
        now_iso = _utc_now_iso()
        now_mono = time.monotonic()
        target_id = step_id or self._current_step_id or "download_core"
        target = self._find_step(target_id)
        if target is not None:
            if target["started_at"] is None:
                target["started_at"] = now_iso
            started_m = self._step_started_mono.get(target["id"], now_mono)
            target["elapsed_ms"] = max(1, int((now_mono - started_m) * 1000))
            target["status"] = "failed"
            target["completed_at"] = now_iso
            target["detail"] = error

        self._status = "failed"
        self._finished_at = now_iso
        self._elapsed_ms = self._elapsed_now_ms()
        self._failed_step_id = target_id
        self._current_step_id = target_id
        self._error = error
        self._message = error
        self._active_transfer = None
        self.add_activity(error, level="error")
        await self._publish_ws("failed", None, error, force=True)
        return self._persist_snapshot()


def make_sync_or_async_progress_adapter(
    tracker: ProvisioningProgressTracker,
) -> Any:
    """Return an async progress callback compatible with jar_service.on_progress."""

    async def _on_progress(
        filename: str,
        bytes_downloaded: int,
        total_bytes: int | None,
        speed_bps: float | None,
        eta_seconds: float | None,
        file_index: int,
        file_total: int,
    ) -> None:
        await tracker.record_download_progress(
            filename=filename,
            bytes_downloaded=bytes_downloaded,
            total_bytes=total_bytes,
            speed_bps=speed_bps,
            eta_seconds=eta_seconds,
            file_index=file_index,
            file_total=file_total,
        )

    return _on_progress


_ACTIVE_PROVISIONING_TRACKER: contextvars.ContextVar[ProvisioningProgressTracker | None] = (
    contextvars.ContextVar("active_provisioning_tracker", default=None)
)


@contextlib.contextmanager
def provisioning_tracker_context(tracker: ProvisioningProgressTracker | None):
    """Bind a ProvisioningProgressTracker for the current async task."""
    token = _ACTIVE_PROVISIONING_TRACKER.set(tracker)
    try:
        yield
    finally:
        _ACTIVE_PROVISIONING_TRACKER.reset(token)


def get_active_provisioning_tracker() -> ProvisioningProgressTracker | None:
    return _ACTIVE_PROVISIONING_TRACKER.get()


def schedule_progress_emit(coro: Any) -> None:
    """Safely schedule an async telemetry call if a loop is running."""
    with contextlib.suppress(RuntimeError):
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
