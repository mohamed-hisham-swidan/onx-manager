"""Crash-safe journaled directory swap (OD-v8.7-2).

A live tree is replaced by a staged tree with a single ``RENAME_EXCHANGE``
where the kernel and filesystem support it. Otherwise the swap uses the
journaled two-step rename:

1. ``SWAPPING_OUT_LIVE``: ``live`` -> ``live.prev``
2. ``SWAPPING_IN_STAGING``: ``staging`` -> ``live``
3. ``SWAP_COMPLETED``

Each journal phase is fsynced before the corresponding rename, so a crash can
be reconciled back to the pre-swap tree by :func:`recover_interrupted_swap`.
The old tree is left at ``staging`` (exchange) or ``live.prev`` (fallback) for
the caller to verify and remove; this module never deletes a tree.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import json
import os
import platform
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.exceptions import ConflictError, ValidationError
from app.core.host_state import validate_server_segment
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

AT_FDCWD = -100
RENAME_EXCHANGE = 2

PHASE_PREPARED = "PREPARED"
PHASE_SWAPPING_OUT_LIVE = "SWAPPING_OUT_LIVE"
PHASE_SWAPPING_IN_STAGING = "SWAPPING_IN_STAGING"
PHASE_SWAP_COMPLETED = "SWAP_COMPLETED"
PHASE_SWAP_ROLLED_BACK = "SWAP_ROLLED_BACK"

SwapPhase = Literal[
    "PREPARED",
    "SWAPPING_OUT_LIVE",
    "SWAPPING_IN_STAGING",
    "SWAP_COMPLETED",
    "SWAP_ROLLED_BACK",
]
SwapRecoveryStatus = Literal["none", "unchanged", "completed", "rolled_back"]
SwapClassificationState = Literal["unchanged", "already_swapped", "completed", "rolled_back"]

_EXPORT_MARKER_NAME = ".onx-complete.json"

_PHASES = frozenset(
    {
        PHASE_PREPARED,
        PHASE_SWAPPING_OUT_LIVE,
        PHASE_SWAPPING_IN_STAGING,
        PHASE_SWAP_COMPLETED,
        PHASE_SWAP_ROLLED_BACK,
    }
)
_SYS_RENAMEAT2 = {
    "x86_64": 316,
    "amd64": 316,
    "aarch64": 276,
    "arm64": 276,
    "i386": 353,
    "i686": 353,
    "armv7l": 382,
    "armv6l": 382,
    "ppc64le": 357,
    "ppc64": 357,
    "s390x": 347,
    "riscv64": 276,
}
_UNSUPPORTED_ERRNOS = frozenset(
    {
        errno.ENOSYS,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _absolute_path(raw: str | os.PathLike[str], field: str) -> Path:
    try:
        text = os.fspath(raw)
    except TypeError as exc:
        raise ValidationError(f"{field} must be a filesystem path", field=field) from exc
    if not isinstance(text, str) or not text:
        raise ValidationError(f"{field} must be a non-empty path", field=field)
    if not os.path.isabs(text):
        raise ValidationError(f"{field} must be an absolute path", field=field)
    path = Path(os.path.abspath(text))
    if path.name in ("", ".", ".."):
        raise ValidationError(f"{field} is not a usable directory", field=field)
    if path.is_symlink():
        raise ValidationError(f"{field} must not be a symlink", field=field)
    return path


def _existing_directory(raw: str | os.PathLike[str], field: str) -> Path:
    path = _absolute_path(raw, field)
    if os.path.realpath(path) != str(path):
        raise ValidationError(f"{field} must not contain a symlinked component", field=field)
    if not path.is_dir():
        raise ValidationError(f"{field} is not an existing directory", field=field)
    return path


def _declared_path(raw: str, field: str) -> Path:
    """Validate a path recorded in a journal, which may no longer exist."""
    path = _absolute_path(raw, field)
    if os.path.realpath(path.parent) != str(path.parent):
        raise ValidationError(f"{field} parent must not contain a symlinked component", field=field)
    return path


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path.parent, flags)
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def _validated_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or any(ch not in "0123456789abcdef" for ch in value):
        raise ValidationError(f"{field} must be a lowercase hexadecimal object id", field=field)
    if len(value) not in (40, 64):
        raise ValidationError(f"{field} must be 40 or 64 hexadecimal characters", field=field)
    return value


@dataclass(frozen=True)
class SwapJournalRecord:
    """One on-disk Refresh Journal row for a directory swap."""

    journal_id: str
    server_id: str
    phase: str
    live_path: str
    staging_path: str
    previous_path: str
    previous_main_sha: str = ""
    target_main_sha: str = ""
    pre_upgrade_backup_id: str = ""
    class_c_snapshot_id: str = ""
    export_id: str = ""
    keep_previous: bool = False
    used_exchange: bool = False
    error: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.journal_id, str) or not self.journal_id:
            raise ValidationError("journal_id must be a non-empty string", field="journal_id")
        validate_server_segment(self.server_id)
        if self.phase not in _PHASES:
            raise ValidationError("Unknown swap journal phase", field="phase")
        for name in ("live_path", "staging_path", "previous_path"):
            value = getattr(self, name)
            if not isinstance(value, str) or not os.path.isabs(value):
                raise ValidationError(f"{name} must be an absolute path", field=name)
        for name in ("previous_main_sha", "target_main_sha"):
            value = getattr(self, name)
            if value:
                _validated_digest(value, name)
        if type(self.used_exchange) is not bool:
            raise ValidationError("used_exchange must be a boolean", field="used_exchange")
        if type(self.keep_previous) is not bool:
            raise ValidationError("keep_previous must be a boolean", field="keep_previous")
        if not isinstance(self.export_id, str):
            raise ValidationError("export_id must be a string", field="export_id")


class DirectorySwapJournal:
    """Atomic, fsynced JSON journal for one server's directory swap."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = _absolute_path(path, "journal_path")
        if self._path.exists() and self._path.is_symlink():
            raise ValidationError("Journal path must not be a symlink", field="journal_path")

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: SwapJournalRecord) -> None:
        payload = (json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise ValidationError(
                f"Unable to create journal directory: {exc}", field="journal_path"
            ) from exc
        if self._path.parent.is_symlink():
            raise ValidationError("Journal directory must not be a symlink", field="journal_path")
        atomic_write_private(self._path, payload, mode=0o600, fsync_parent=True)

    def read(self) -> SwapJournalRecord | None:
        try:
            if self._path.is_symlink():
                raise ValidationError("Journal path must not be a symlink", field="journal_path")
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValidationError(
                f"Unable to read swap journal: {exc}", field="journal_path"
            ) from exc
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Swap journal is not valid JSON", field="journal_path") from exc
        if not isinstance(data, dict):
            raise ValidationError("Swap journal must be a JSON object", field="journal_path")
        required = {
            "journal_id",
            "server_id",
            "phase",
            "live_path",
            "staging_path",
            "previous_path",
        }
        missing = sorted(required.difference(data))
        if missing:
            raise ValidationError(
                "Swap journal is missing required fields",
                field="journal_path",
                details={"missing": missing},
            )
        try:
            return SwapJournalRecord(
                journal_id=str(data["journal_id"]),
                server_id=str(data["server_id"]),
                phase=str(data["phase"]),
                live_path=str(data["live_path"]),
                staging_path=str(data["staging_path"]),
                previous_path=str(data["previous_path"]),
                previous_main_sha=str(data.get("previous_main_sha", "")),
                target_main_sha=str(data.get("target_main_sha", "")),
                pre_upgrade_backup_id=str(data.get("pre_upgrade_backup_id", "")),
                class_c_snapshot_id=str(data.get("class_c_snapshot_id", "")),
                export_id=str(data.get("export_id", "")),
                keep_previous=bool(data.get("keep_previous", False)),
                used_exchange=bool(data.get("used_exchange", False)),
                error=str(data.get("error", "")),
                updated_at=str(data.get("updated_at", "")),
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Swap journal has invalid field types", field="journal_path"
            ) from exc


@dataclass(frozen=True)
class SwapResult:
    journal_id: str
    live_path: Path
    previous_tree_path: Path
    journal_path: Path
    used_exchange: bool


@dataclass(frozen=True)
class SwapRecoveryResult:
    status: SwapRecoveryStatus
    record: SwapJournalRecord | None = None


@dataclass(frozen=True)
class SwapClassification:
    """Disk-state classification for a possibly interrupted swap."""

    state: SwapClassificationState
    live_marker: dict[str, object] | None = None
    staging_marker: dict[str, object] | None = None


def _read_export_marker(directory: Path) -> dict[str, object] | None:
    marker = directory / _EXPORT_MARKER_NAME
    if not os.path.lexists(marker):
        return None
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def classify_swap_state(record: SwapJournalRecord) -> SwapClassification:
    """Classify disk state for a journal record without touching any tree.

    ``already_swapped`` is the critical post-``rename_exchange`` case: the live
    tree already carries the staged export's completion marker, but the journal
    may still say ``PREPARED`` because the process crashed before the
    ``SWAP_COMPLETED`` write. Callers must treat ``staging_path`` as the old
    live tree and never delete it as an unfinalized staging directory.
    """
    live = _declared_path(record.live_path, "live_path")
    staging = _declared_path(record.staging_path, "staging_path")
    live_marker = _read_export_marker(live)
    staging_marker = _read_export_marker(staging)

    if record.phase == PHASE_SWAP_COMPLETED:
        state: SwapClassificationState = "completed"
    elif record.phase == PHASE_SWAP_ROLLED_BACK:
        state = "rolled_back"
    elif (
        record.export_id
        and record.phase in (PHASE_PREPARED, PHASE_SWAPPING_IN_STAGING)
        and live_marker is not None
        and live_marker.get("export_id") == record.export_id
    ):
        state = "already_swapped"
    else:
        state = "unchanged"
    return SwapClassification(
        state=state, live_marker=live_marker, staging_marker=staging_marker
    )


def _validate_pair(live: Path, staging: Path) -> Path:
    if live == staging:
        raise ValidationError("Live and staging directories must differ", field="staging")
    previous = live.with_name(live.name + ".prev")
    if staging == previous:
        raise ValidationError("Staging directory must not be the .prev path", field="staging")
    if os.path.lexists(previous):
        raise ConflictError(f"Swap previous path already exists: {previous}")
    try:
        if os.path.commonpath([str(live), str(staging)]) in (str(live), str(staging)):
            raise ValidationError(
                "Live and staging directories must not contain each other", field="staging"
            )
    except ValueError as exc:
        raise ValidationError(
            "Live and staging directories are not comparable", field="staging"
        ) from exc
    if os.lstat(live).st_dev != os.lstat(staging).st_dev:
        raise ValidationError(
            "Live and staging directories must be on the same filesystem", field="staging"
        )
    return previous


def _load_libc() -> ctypes.CDLL | None:
    if sys.platform != "linux":
        return None
    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None


def rename_exchange(live: Path, staging: Path) -> bool:
    """Exchange two directories, returning ``False`` when unsupported.

    A supported exchange is a single atomic metadata operation. Unsupported
    kernels/filesystems return ``False`` so the caller uses the journaled
    two-step fallback; unexpected errors are raised.
    """
    libc = _load_libc()
    if libc is None:
        return False
    live_b = os.fsencode(str(live))
    staging_b = os.fsencode(str(staging))
    ctypes.set_errno(0)
    try:
        func = getattr(libc, "renameat2", None)
        if func is not None:
            func.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            func.restype = ctypes.c_int
            rc = func(AT_FDCWD, live_b, AT_FDCWD, staging_b, RENAME_EXCHANGE)
        else:
            syscall_number = _SYS_RENAMEAT2.get(platform.machine().lower())
            if syscall_number is None:
                return False
            libc.syscall.restype = ctypes.c_long
            rc = libc.syscall(
                ctypes.c_long(syscall_number),
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(live_b),
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(staging_b),
                ctypes.c_uint(RENAME_EXCHANGE),
            )
    except (AttributeError, OSError):
        return False

    if rc == 0:
        return True
    error = ctypes.get_errno()
    if error in _UNSUPPORTED_ERRNOS:
        return False
    if error == 0:
        error = errno.EIO
    raise OSError(error, os.strerror(error), str(live))


def swap_directories(
    live_dir: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
    journal: DirectorySwapJournal,
    *,
    server_id: str,
    previous_main_sha: str = "",
    target_main_sha: str = "",
    pre_upgrade_backup_id: str = "",
    class_c_snapshot_id: str = "",
    export_id: str = "",
    keep_previous: bool = False,
    exchange_supported: bool | None = None,
) -> SwapResult:
    """Atomically replace ``live_dir`` with ``staging_dir``.

    ``exchange_supported=False`` forces the journaled fallback. The caller
    owns the old tree afterwards: it is at ``staging_dir`` after an exchange
    and at ``<live_dir>.prev`` after a fallback. This module never deletes a
    tree. ``keep_previous`` records the caller's intent to retain the old tree
    so crash recovery cannot mistake it for an unfinalized staging directory.
    """
    segment = validate_server_segment(server_id)
    live = _existing_directory(live_dir, "live_dir")
    staging = _existing_directory(staging_dir, "staging_dir")
    previous = _validate_pair(live, staging)

    journal_id = uuid.uuid4().hex

    def record(
        phase: SwapPhase,
        *,
        used_exchange: bool = False,
        error: str = "",
    ) -> SwapJournalRecord:
        return SwapJournalRecord(
            journal_id=journal_id,
            server_id=segment,
            phase=phase,
            live_path=str(live),
            staging_path=str(staging),
            previous_path=str(previous),
            previous_main_sha=previous_main_sha,
            target_main_sha=target_main_sha,
            pre_upgrade_backup_id=pre_upgrade_backup_id,
            class_c_snapshot_id=class_c_snapshot_id,
            export_id=export_id,
            keep_previous=keep_previous,
            used_exchange=used_exchange,
            error=error[:256],
            updated_at=_utc_now(),
        )

    journal.write(record(PHASE_PREPARED))

    if exchange_supported is not False:
        try:
            exchanged = rename_exchange(live, staging)
        except OSError as exc:
            journal.write(record(PHASE_SWAP_ROLLED_BACK, error=str(exc)))
            raise
        if exchanged:
            _fsync_parent(live)
            if live.parent != staging.parent:
                _fsync_parent(staging)
            journal.write(record(PHASE_SWAP_COMPLETED, used_exchange=True))
            return SwapResult(
                journal_id=journal_id,
                live_path=live,
                previous_tree_path=staging,
                journal_path=journal.path,
                used_exchange=True,
            )
        if exchange_supported is True:
            journal.write(record(PHASE_SWAP_ROLLED_BACK, error="RENAME_EXCHANGE unsupported"))
            raise ValidationError(
                "RENAME_EXCHANGE is not supported by this filesystem",
                field="exchange_supported",
            )

    try:
        journal.write(record(PHASE_SWAPPING_OUT_LIVE))
        os.rename(live, previous)
        _fsync_parent(live)

        journal.write(record(PHASE_SWAPPING_IN_STAGING))
        os.rename(staging, live)
        _fsync_parent(live)
    except BaseException as exc:
        if not os.path.lexists(live) and os.path.lexists(previous):
            with contextlib.suppress(OSError):
                os.rename(previous, live)
                _fsync_parent(live)
        with contextlib.suppress(Exception):
            journal.write(record(PHASE_SWAP_ROLLED_BACK, error=str(exc)))
        raise

    journal.write(record(PHASE_SWAP_COMPLETED))
    return SwapResult(
        journal_id=journal_id,
        live_path=live,
        previous_tree_path=previous,
        journal_path=journal.path,
        used_exchange=False,
    )


def recover_interrupted_swap(
    journal: DirectorySwapJournal,
) -> SwapRecoveryResult:
    """Reconcile a swap interrupted by a crash, restoring a consistent tree.

    ``SWAPPING_OUT_LIVE`` and ``SWAPPING_IN_STAGING`` are rolled back to the
    pre-swap live tree when ``live`` is missing. A crash that happened after
    the staging tree was renamed into place is marked ``SWAP_COMPLETED``.
    """
    record = journal.read()
    if record is None:
        return SwapRecoveryResult(status="none")

    live = _declared_path(record.live_path, "live_path")
    staging = _declared_path(record.staging_path, "staging_path")
    previous = _declared_path(record.previous_path, "previous_path")
    live_exists = os.path.lexists(live)
    previous_exists = os.path.lexists(previous)

    def finish(
        phase: SwapPhase,
        status: SwapRecoveryStatus,
        *,
        error: str = "",
        used_exchange: bool | None = None,
    ) -> SwapRecoveryResult:
        updated = SwapJournalRecord(
            journal_id=record.journal_id,
            server_id=record.server_id,
            phase=phase,
            live_path=record.live_path,
            staging_path=record.staging_path,
            previous_path=record.previous_path,
            previous_main_sha=record.previous_main_sha,
            target_main_sha=record.target_main_sha,
            pre_upgrade_backup_id=record.pre_upgrade_backup_id,
            class_c_snapshot_id=record.class_c_snapshot_id,
            export_id=record.export_id,
            keep_previous=record.keep_previous,
            used_exchange=(
                record.used_exchange if used_exchange is None else used_exchange
            ),
            error=error[:256],
            updated_at=_utc_now(),
        )
        journal.write(updated)
        return SwapRecoveryResult(status=status, record=updated)

    if record.phase in (PHASE_SWAP_COMPLETED, PHASE_SWAP_ROLLED_BACK):
        return SwapRecoveryResult(
            status="completed" if record.phase == PHASE_SWAP_COMPLETED else "rolled_back",
            record=record,
        )

    if record.phase == PHASE_PREPARED:
        classification = classify_swap_state(record)
        if classification.state == "already_swapped":
            # The exchange happened but the process died before the journal
            # recorded SWAP_COMPLETED. The old live tree is now at staging.
            return finish(PHASE_SWAP_COMPLETED, "completed", used_exchange=True)
        if live_exists:
            return SwapRecoveryResult(status="unchanged", record=record)
        if previous_exists:
            os.rename(previous, live)
            _fsync_parent(live)
            return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
        raise ValidationError(
            "Prepared swap journal has neither a live nor a previous tree",
            field="journal_path",
        )

    if record.phase == PHASE_SWAPPING_OUT_LIVE:
        if previous_exists and live_exists:
            raise ConflictError("Swap journal found both live and .prev trees")
        if previous_exists:
            os.rename(previous, live)
            _fsync_parent(live)
            return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
        if live_exists:
            return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
        raise ValidationError(
            "Swap journal lost both the live and previous trees", field="journal_path"
        )

    if record.phase == PHASE_SWAPPING_IN_STAGING:
        staging_exists = os.path.lexists(staging)
        if live_exists and previous_exists:
            # Both the new live tree and .prev exist. A present staging tree
            # means the staging rename never consumed it (or rollback restored
            # live), so the swap did not complete; otherwise the swap finished
            # and only the .prev cleanup is outstanding.
            if staging_exists:
                return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
            return finish(PHASE_SWAP_COMPLETED, "completed")
        if previous_exists:
            os.rename(previous, live)
            _fsync_parent(live)
            return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
        if live_exists:
            # The staging rename completed before the crash (staging gone), or
            # the failure path renamed .prev back to live before the journal
            # write of SWAP_ROLLED_BACK failed. In the latter case the staging
            # tree is still present, proving the new tree was never installed.
            if staging_exists:
                return finish(PHASE_SWAP_ROLLED_BACK, "rolled_back")
            return finish(PHASE_SWAP_COMPLETED, "completed")
        raise ValidationError(
            "Swap journal lost both the live and previous trees", field="journal_path"
        )

    raise ValidationError("Unknown swap journal phase", field="phase")


__all__ = [
    "DirectorySwapJournal",
    "PHASE_PREPARED",
    "PHASE_SWAP_COMPLETED",
    "PHASE_SWAP_ROLLED_BACK",
    "PHASE_SWAPPING_IN_STAGING",
    "PHASE_SWAPPING_OUT_LIVE",
    "SwapClassification",
    "SwapJournalRecord",
    "SwapRecoveryResult",
    "SwapResult",
    "classify_swap_state",
    "recover_interrupted_swap",
    "rename_exchange",
    "swap_directories",
]
