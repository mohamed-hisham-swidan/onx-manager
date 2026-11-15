"""Refresh staging, carry, swap, health gate, and triad rollback (P2-5d1/d2).

This module is the foundation of the seven-step live refresh:

* an upfront total free-space preflight (``1.10x`` headroom) that runs before
  the server is stopped;
* mountpoint and same-device preflight (``M-5`` / ``D-P25-5``);
* a fail-closed Git worktree lock guard (``D-P25-10``);
* complement carry: everything the A/B/D export manifest does not own is moved
  from the old live tree into the staged export (``C-1``);
* a thread-shielded, journaled ``swap_directories(..., keep_previous=True)``
  whose worker thread is always joined before cleanup (``H-6``);
* previous-tree retention policy parsing and journaled cleanup
  (``D-P25-11``);
* the 4-step Health Gate, automatic triad rollback (Class A+B fast rename or
  re-export, Class C snapshot restore, Class E backup restore), the
  ``LiveRefreshService`` seven-step refresh, and explicit confirm/unpin
  (P2-5d2).

Lock order is fixed: ``ServerLifecycleLeaseManager`` first, then
``RepoLeaseManager``. The service layer enforces it; the rollback service
assumes the caller already serializes the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import inspect
import logging
import math
import os
import re
import shutil
import threading
import uuid
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
)
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.exceptions import (
    ConflictError,
    FencingTokenMismatchError,
    InsufficientStorageError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.application.refresh_recovery import (
    RefreshStartupReconciler,
)
from app.modules.versioning.application.repo_lease import (
    RepoLeaseManager,
    RepoLeaseToken,
)
from app.modules.versioning.infrastructure.class_c_snapshot import (
    ClassCSnapshotResult,
    ClassCSnapshotService,
)
from app.modules.versioning.infrastructure.directory_swap import (
    DirectorySwapJournal,
    SwapResult,
    swap_directories,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    TERMINAL_PHASES,
    RefreshJournalRecord,
    RefreshJournalRepository,
)

DEFAULT_SPACE_HEADROOM = 1.10
STAGING_SUFFIX = ".staging"
PREVIOUS_SUFFIX = ".prev"
ROLLBACK_SUFFIX = ".rollback"
ROLLBACK_SOURCE_SUFFIX = ".rollback-prev"
SWAP_JOURNAL_FILENAME = "swap.json"
ROLLBACK_SWAP_JOURNAL_FILENAME = "swap-rollback.json"
SESSION_LOCK_FILENAME = "session.lock"

logger = logging.getLogger(__name__)

RETENTION_UNTIL_HEALTH_GATE = "until_health_gate"
RETENTION_UNTIL_CONFIRM = "until_confirm"

STEP_PROCESS_ALIVE = "process_alive"
STEP_BOOT_LOG = "boot_log"
STEP_READINESS = "readiness"
STEP_STABILITY = "stability"

CRASH_PATTERNS = (
    "exception in server tick loop",
    "encountered an unexpected exception",
    "failed to start the minecraft server",
    "could not find or load main class",
    "unsupportedclassversionerror",
    "outofmemoryerror",
    "java.lang.noclassdeffounderror",
    "address already in use",
)

_HOURS_RE = re.compile(r"\A([0-9]{1,3})h?\Z")
_SWAP_THREAD_NAME = "onx-refresh-swap"


# ----------------------------------------------------------------------
# Path helpers
# ----------------------------------------------------------------------


def _absolute_path(raw: str | os.PathLike[str], field: str) -> Path:
    try:
        text = os.fspath(raw)
    except TypeError as exc:
        raise ValidationError(f"{field} must be a filesystem path", field=field) from exc
    if not isinstance(text, str) or not text:
        raise ValidationError(f"{field} must be a non-empty path", field=field)
    if not os.path.isabs(text):
        raise ValidationError(f"{field} must be an absolute path", field=field)
    return Path(os.path.abspath(text))


def _existing_plain_directory(raw: str | os.PathLike[str], field: str) -> Path:
    path = _absolute_path(raw, field)
    if path.is_symlink():
        raise ValidationError(f"{field} must not be a symlink", field=field)
    if not path.is_dir():
        raise ValidationError(f"{field} must be an existing directory", field=field)
    if os.path.realpath(path) != str(path):
        raise ValidationError(f"{field} must not contain a symlinked component", field=field)
    return path


def _st_dev(path: Path) -> int:
    return int(os.stat(path).st_dev)


def _require_posix_live_refresh() -> None:
    if os.name != "posix":
        raise ServerModeVersioningDisabledError(
            "Live refresh is only supported on POSIX hosts in this release"
        )


def _free_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def previous_tree_path(live_dir: str | os.PathLike[str]) -> Path:
    """Return the sibling ``.prev`` path that a fallback swap retains."""
    live = _absolute_path(live_dir, "live_dir")
    return live.with_name(live.name + PREVIOUS_SUFFIX)


# ----------------------------------------------------------------------
# Disk-full policy
# ----------------------------------------------------------------------


def _non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{field} must be a non-negative integer", field=field)
    return value


def required_free_bytes(
    total_bytes: int,
    *,
    headroom: float = DEFAULT_SPACE_HEADROOM,
) -> int:
    """Return ``ceil(total_bytes * headroom)`` after validating the inputs."""
    total = _non_negative_int(total_bytes, "total_bytes")
    if not isinstance(headroom, (int, float)) or isinstance(headroom, bool):
        raise ValidationError("headroom must be a number", field="headroom")
    if float(headroom) < 1.0:
        raise ValidationError("headroom must be at least 1.0", field="headroom")
    return int(math.ceil(total * float(headroom)))


def check_refresh_free_space(
    live_dir: str | os.PathLike[str],
    *,
    export_bytes: int,
    backup_bytes: int = 0,
    class_c_snapshot_bytes: int = 0,
    retained_prev_tree_bytes: int = 0,
    rollback_headroom: int = 0,
    host_state_dir: str | os.PathLike[str] | None = None,
    headroom: float = DEFAULT_SPACE_HEADROOM,
) -> int:
    """Fail with HTTP 507 unless the refresh has its full ``1.10x`` budget.

    The live filesystem must hold the export, backup estimate, Class-C
    snapshot, retained previous tree, and rollback headroom with 10% slack. If
    ``host_state_dir`` lives on a different device it must separately hold the
    backup plus Class-C snapshot bytes.
    """
    live = _existing_plain_directory(live_dir, "live_dir")
    total = (
        _non_negative_int(export_bytes, "export_bytes")
        + _non_negative_int(backup_bytes, "backup_bytes")
        + _non_negative_int(class_c_snapshot_bytes, "class_c_snapshot_bytes")
        + _non_negative_int(retained_prev_tree_bytes, "retained_prev_tree_bytes")
        + _non_negative_int(rollback_headroom, "rollback_headroom")
    )
    required = required_free_bytes(total, headroom=headroom)
    parent = live.parent
    free = _free_bytes(parent)
    if free < required:
        raise InsufficientStorageError(
            details={
                "path": str(parent),
                "required_bytes": required,
                "free_bytes": free,
            }
        )

    if host_state_dir is not None:
        host_state = _existing_plain_directory(host_state_dir, "host_state_dir")
        if _st_dev(host_state) != _st_dev(parent):
            host_required = required_free_bytes(
                _non_negative_int(backup_bytes, "backup_bytes")
                + _non_negative_int(class_c_snapshot_bytes, "class_c_snapshot_bytes"),
                headroom=headroom,
            )
            host_free = _free_bytes(host_state)
            if host_free < host_required:
                raise InsufficientStorageError(
                    details={
                        "path": str(host_state),
                        "required_bytes": host_required,
                        "free_bytes": host_free,
                    }
                )
    return required


@contextlib.contextmanager
def staging_enospc_guard(
    staging_dir: str | os.PathLike[str],
    *,
    live_dir: str | os.PathLike[str] | None = None,
) -> Iterator[None]:
    """Remove a partially built staging tree on ``ENOSPC`` and raise HTTP 507.

    The live tree is never removed: staging must be a sibling, not the live
    path, and may not contain or be contained by it.
    """
    staging = _absolute_path(staging_dir, "staging_dir")
    if live_dir is not None:
        live = _absolute_path(live_dir, "live_dir")
        if staging == live:
            raise ValidationError(
                "staging_dir and live_dir must differ", field="staging_dir"
            )
        try:
            common = os.path.commonpath([str(staging), str(live)])
        except ValueError as exc:
            raise ValidationError(
                "staging_dir and live_dir are not comparable", field="staging_dir"
            ) from exc
        if common in (str(staging), str(live)):
            raise ValidationError(
                "staging_dir and live_dir must not contain each other",
                field="staging_dir",
            )
    try:
        yield
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            raise
        shutil.rmtree(staging, ignore_errors=True)
        raise InsufficientStorageError(details={"path": str(staging)}) from exc


# ----------------------------------------------------------------------
# Mountpoint / device and worktree guards
# ----------------------------------------------------------------------


def check_swap_preconditions(
    live_dir: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
) -> None:
    """Reject a mountpoint live tree and cross-device staging before stopping."""
    live = _existing_plain_directory(live_dir, "live_dir")
    staging = _absolute_path(staging_dir, "staging_dir")
    if os.path.ismount(live):
        raise ConflictError(
            f"Refusing to refresh: live directory is a mountpoint: {live}"
        )
    parent = staging.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValidationError(
            "staging_dir parent must be an existing plain directory",
            field="staging_dir",
        )
    if os.path.realpath(parent) != str(parent):
        raise ValidationError(
            "staging_dir parent must not contain a symlinked component",
            field="staging_dir",
        )
    if os.path.lexists(staging) and (staging.is_symlink() or not staging.is_dir()):
        raise ValidationError(
            "staging_dir must be a plain directory when it exists",
            field="staging_dir",
        )
    staging_device_source = staging if os.path.lexists(staging) else parent
    if _st_dev(live) != _st_dev(staging_device_source):
        raise ValidationError(
            "live_dir and staging_dir must share one filesystem",
            field="staging_dir",
            details={"live": str(live), "staging": str(staging)},
        )


def _worktree_gitdir(worktree: Path) -> Path | None:
    gitfile = worktree / ".git"
    if gitfile.is_symlink() or not gitfile.is_file():
        return None
    try:
        first_line = gitfile.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, IndexError):
        return None
    prefix = "gitdir:"
    if not first_line.startswith(prefix):
        return None
    raw = first_line[len(prefix) :].strip()
    if not raw:
        return None
    target = Path(raw)
    if not target.is_absolute():
        target = worktree / target
    return Path(os.path.abspath(target))


def _has_locked_marker(directory: Path) -> bool:
    marker = directory / "locked"
    return os.path.lexists(marker) and not marker.is_symlink()


def check_worktree_locks(
    live_dir: str | os.PathLike[str],
    *,
    repo_git_dir: str | os.PathLike[str] | None = None,
) -> None:
    """Fail closed when any linked Git worktree is locked (HTTP 409).

    Both the linked worktree's own ``locked`` marker and the marker inside its
    gitdir (where ``git worktree lock`` writes it) are inspected. When the
    repository location is known, ``<repo_git>/worktrees/*/locked`` is checked
    directly as well.
    """
    live = _absolute_path(live_dir, "live_dir")
    locked: set[str] = set()

    worktrees_root = live / ".onx" / "worktrees"
    if worktrees_root.is_dir() and not worktrees_root.is_symlink():
        for entry in sorted(os.scandir(worktrees_root), key=lambda item: item.name):
            if not entry.is_dir(follow_symlinks=False):
                continue
            worktree = Path(entry.path)
            if _has_locked_marker(worktree):
                locked.add(entry.name)
            gitdir = _worktree_gitdir(worktree)
            if gitdir is not None and _has_locked_marker(gitdir):
                locked.add(entry.name)

    candidates: list[Path] = []
    if repo_git_dir is not None:
        candidates.append(_absolute_path(repo_git_dir, "repo_git_dir"))
    legacy = live / ".onx" / "repo.git"
    if legacy not in candidates:
        candidates.append(legacy)
    for candidate in candidates:
        worktree_meta = candidate / "worktrees"
        if not worktree_meta.is_dir() or worktree_meta.is_symlink():
            continue
        for entry in sorted(os.scandir(worktree_meta), key=lambda item: item.name):
            if entry.is_dir(follow_symlinks=False) and _has_locked_marker(
                Path(entry.path)
            ):
                locked.add(entry.name)

    if locked:
        raise ConflictError(
            "A locked Git worktree blocks refresh; unlock it first: "
            + ", ".join(sorted(locked))
        )


# ----------------------------------------------------------------------
# Retention policy
# ----------------------------------------------------------------------


def parse_retention_policy(raw: str | int) -> tuple[str, timedelta | None]:
    """Validate a previous-tree retention policy.

    Accepts ``"until_health_gate"`` (default), ``"until_confirm"``, or bounded
    hours ``1..168`` in either integer or ``"<N>h"`` form. Returns the
    normalized policy and, for hour policies, its retention window.
    """
    if isinstance(raw, bool):
        raise ValidationError(
            "retention_policy must be a name or an hour count", field="retention_policy"
        )
    hours: int | None = None
    if isinstance(raw, int):
        hours = raw
    elif isinstance(raw, str):
        text = raw.strip().lower()
        if text == RETENTION_UNTIL_HEALTH_GATE:
            return RETENTION_UNTIL_HEALTH_GATE, None
        if text == RETENTION_UNTIL_CONFIRM:
            return RETENTION_UNTIL_CONFIRM, None
        match = _HOURS_RE.match(text)
        if match is None:
            raise ValidationError(
                "retention_policy must be 'until_health_gate', 'until_confirm', "
                "or 1..168 hours",
                field="retention_policy",
                details={"value": str(raw)[:64]},
            )
        hours = int(match.group(1))
    else:
        raise ValidationError(
            "retention_policy must be a string or an integer",
            field="retention_policy",
        )
    if hours < 1 or hours > 168:
        raise ValidationError(
            "retention hours must be between 1 and 168",
            field="retention_policy",
            details={"hours": hours},
        )
    return f"{hours}h", timedelta(hours=hours)


# ----------------------------------------------------------------------
# Complement carry
# ----------------------------------------------------------------------


def _validate_relative_entry(relpath: str) -> str:
    from app.core.allowlist import validate_canonical_relpath

    try:
        return validate_canonical_relpath(relpath)
    except ValueError as exc:
        raise ValidationError(
            "Carried entry is not a canonical relative path",
            field="carried_entries",
            details={"relpath": relpath[:128]},
        ) from exc


def discover_complement_entries(
    live_dir: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
) -> list[str]:
    """Return live entries that the staged export does not own.

    A directory owned by the export is descended into so its unowned children
    are carried; an unowned directory is carried whole and not descended.
    Symlinks are rejected (fail closed).
    """
    live = _existing_plain_directory(live_dir, "live_dir")
    staging = _existing_plain_directory(staging_dir, "staging_dir")

    carried: list[str] = []
    for dirpath, dirnames, filenames in os.walk(live, topdown=True, followlinks=False):
        dirnames.sort()
        filenames.sort()
        directory = Path(dirpath)
        for name in list(dirnames):
            candidate = directory / name
            if candidate.is_symlink():
                raise ValidationError(
                    "Live tree contains a symlink that cannot be carried",
                    field="live_dir",
                    details={"relpath": candidate.relative_to(live).as_posix()[:128]},
                )
            relpath = candidate.relative_to(live).as_posix()
            if not os.path.lexists(staging / relpath):
                carried.append(relpath)
                dirnames.remove(name)
        for name in filenames:
            candidate = directory / name
            if candidate.is_symlink() or not candidate.is_file():
                raise ValidationError(
                    "Live tree contains a non-regular entry that cannot be carried",
                    field="live_dir",
                    details={"relpath": candidate.relative_to(live).as_posix()[:128]},
                )
            relpath = candidate.relative_to(live).as_posix()
            if not os.path.lexists(staging / relpath):
                carried.append(relpath)
    return sorted(carried)


def _move_entry(source: Path, target: Path) -> None:
    if os.path.lexists(target):
        raise ConflictError(f"Carry target already exists in staging: {target}")
    os.rename(source, target)


def restore_carried_entries(
    live_dir: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
    entries: Iterable[str],
) -> list[str]:
    """Move carried entries from staging back into the live tree (inverse carry).

    Missing sources are skipped so the inverse is safe after a partial failure.
    An existing live target fails closed rather than overwriting live data.
    """
    live = _existing_plain_directory(live_dir, "live_dir")
    staging = _existing_plain_directory(staging_dir, "staging_dir")
    restored: list[str] = []
    for raw in reversed(list(entries)):
        relpath = _validate_relative_entry(raw)
        source = staging / relpath
        target = live / relpath
        if not os.path.lexists(source):
            continue
        if os.path.lexists(target):
            raise ConflictError(
                f"Cannot restore carried entry '{relpath}' over existing live data"
            )
        os.rename(source, target)
        restored.append(relpath)
    return sorted(restored)


def carry_complement_entries(
    live_dir: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
    entries: Iterable[str] | None = None,
) -> list[str]:
    """Move every non-export-owned live entry into staging, atomically per entry.

    ``entries`` may be a pre-persisted carry plan; when omitted the complement
    is discovered here. On any failure the already-moved entries are returned
    to live before the error propagates; ``ENOSPC`` becomes
    :class:`InsufficientStorageError`.
    """
    live = _existing_plain_directory(live_dir, "live_dir")
    staging = _existing_plain_directory(staging_dir, "staging_dir")
    if entries is None:
        entries = discover_complement_entries(live, staging)
    else:
        entries = sorted(_validate_relative_entry(raw) for raw in entries)
    moved: list[str] = []
    try:
        for relpath in entries:
            _move_entry(live / relpath, staging / relpath)
            moved.append(relpath)
    except OSError as exc:
        with contextlib.suppress(Exception):
            restore_carried_entries(live, staging, moved)
        if exc.errno == errno.ENOSPC:
            raise InsufficientStorageError(details={"path": str(staging)}) from exc
        raise
    except BaseException:
        with contextlib.suppress(Exception):
            restore_carried_entries(live, staging, moved)
        raise
    return entries


def assert_carried_entries_present(
    live_dir: str | os.PathLike[str],
    entries: Iterable[str],
) -> None:
    """Assert that every journaled carried entry exists in the new live tree."""
    live = _existing_plain_directory(live_dir, "live_dir")
    missing = [
        relpath
        for relpath in (_validate_relative_entry(raw) for raw in entries)
        if not os.path.lexists(live / relpath)
    ]
    if missing:
        raise ValidationError(
            "Carried entries are missing after the swap",
            field="carried_entries",
            details={"missing": sorted(missing)[:16]},
        )


# ----------------------------------------------------------------------
# Thread-shielded execution
# ----------------------------------------------------------------------


async def run_thread_shielded[T](target: Callable[[], T]) -> T:
    """Run ``target`` in an OS thread and always join it before returning.

    The await is shielded so task cancellation cannot strand the worker: the
    cancellation is re-raised only after the worker thread has finished (H-6).
    """
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = target()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the loop
            result["error"] = exc

    thread = threading.Thread(target=runner, name=_SWAP_THREAD_NAME, daemon=False)
    thread.start()
    join_task = asyncio.ensure_future(asyncio.to_thread(thread.join))
    try:
        await asyncio.shield(join_task)
    except asyncio.CancelledError:
        while not join_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(join_task)
        raise
    finally:
        if thread.is_alive():  # pragma: no cover - defensive
            thread.join()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    return result["value"]


# ----------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class CarrySwapResult:
    """Outcome of a journaled complement carry plus previous-retaining swap."""

    journal: RefreshJournalRecord
    swap: SwapResult
    carried_entries: tuple[str, ...]


class RefreshOrchestrator:
    """Preflight, carry, swap, and previous-tree retention for one host state."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        repository: RefreshJournalRepository | None = None,
        servers_data_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._layout = layout
        self._repository = repository or RefreshJournalRepository(layout)
        self._path_guard = RefreshStartupReconciler(
            layout,
            repository=self._repository,
            servers_data_dir=servers_data_dir,
        )

    @property
    def repository(self) -> RefreshJournalRepository:
        return self._repository

    # ------------------------------------------------------------------
    # Preflight (before the server is stopped)
    # ------------------------------------------------------------------

    def preflight(
        self,
        server_id: str,
        *,
        live_dir: str | os.PathLike[str],
        staging_dir: str | os.PathLike[str],
        export_bytes: int,
        backup_bytes: int = 0,
        class_c_snapshot_bytes: int = 0,
        retained_prev_tree_bytes: int = 0,
        rollback_headroom: int = 0,
    ) -> int:
        """Run the mountpoint, locked-worktree, and total free-space preflight."""
        segment = validate_server_segment(server_id)
        live = _existing_plain_directory(live_dir, "live_dir")
        staging = _absolute_path(staging_dir, "staging_dir")
        check_swap_preconditions(live, staging)
        check_worktree_locks(
            live,
            repo_git_dir=self._layout.repo_dir(segment) / "repo.git",
        )
        return check_refresh_free_space(
            live,
            export_bytes=export_bytes,
            backup_bytes=backup_bytes,
            class_c_snapshot_bytes=class_c_snapshot_bytes,
            retained_prev_tree_bytes=retained_prev_tree_bytes,
            rollback_headroom=rollback_headroom,
            host_state_dir=self._layout.root,
        )

    # ------------------------------------------------------------------
    # Previous-tree retention (before a new refresh starts)
    # ------------------------------------------------------------------

    async def prepare_prior_previous_tree(
        self,
        server_id: str,
        *,
        retention_policy: str | int = RETENTION_UNTIL_HEALTH_GATE,
    ) -> tuple[str, ...]:
        """Refuse an unconfirmed ``until_confirm`` tree, else clean prior ``.prev``.

        Returns the removed previous-tree paths. A retained tree from a prior
        ``until_confirm`` refresh blocks the next refresh with HTTP 409 until
        the journal reaches ``UPGRADE_CONFIRMED``.
        """
        segment = validate_server_segment(server_id)
        requested, _ = parse_retention_policy(retention_policy)
        retained = [
            record
            for record in await self._repository.list_retained_previous_trees()
            if record.server_id == segment
        ]
        for record in retained:
            if (
                record.retention_policy == RETENTION_UNTIL_CONFIRM
                and record.phase != "UPGRADE_CONFIRMED"
            ):
                raise ConflictError(
                    "A previous tree retained until confirmation blocks this refresh: "
                    f"journal {record.journal_id}, path "
                    f"{record.previous_path or record.staging_path}, "
                    f"requested policy {requested}"
                )

        # A non-terminal journal still owns its previous tree as the operator's
        # rollback artifact. Deleting it here (then failing on the one-active
        # journal index) would degrade rollback to a re-export that may not even
        # be possible (F1).
        for record in retained:
            if not record.terminal:
                raise ConflictError(
                    f"A non-terminal refresh journal {record.journal_id} "
                    f"({record.phase}) owns a retained previous tree; roll back "
                    "or resolve it before refreshing"
                )

        removed: list[str] = []
        for record in retained:
            candidate = record.staging_path if record.used_exchange else record.previous_path
            if candidate:
                path = self._path_guard.validate_swap_path(
                    record.server_id, candidate, field="previous_path"
                )
                if os.path.lexists(path):
                    if path.is_symlink() or not path.is_dir():
                        raise ValidationError(
                            "Retained previous tree is not a plain directory",
                            field="previous_path",
                            details={"path": str(path)[:256]},
                        )
                    shutil.rmtree(path)
                    removed.append(str(path))
            await self._repository.mark_previous_tree_cleaned(record.journal_id)
        return tuple(sorted(removed))

    def previous_tree_for(self, journal: RefreshJournalRecord) -> Path:
        """Resolve the retained previous tree path for a journal (path-validated)."""
        candidate = journal.staging_path if journal.used_exchange else journal.previous_path
        if not candidate:
            candidate = str(previous_tree_path(journal.live_path))
        return self._path_guard.validate_swap_path(
            journal.server_id, candidate, field="previous_path"
        )

    def clean_previous_tree(self, journal: RefreshJournalRecord) -> bool:
        """Remove a retained previous tree after the health gate passes.

        The DB flags are updated separately through
        :meth:`RefreshJournalRepository.mark_previous_tree_cleaned`.
        """
        path = self.previous_tree_for(journal)
        if not os.path.lexists(path):
            return False
        if path.is_symlink() or not path.is_dir():
            raise ValidationError(
                "Retained previous tree is not a plain directory",
                field="previous_path",
                details={"path": str(path)[:256]},
            )
        shutil.rmtree(path)
        return True

    # ------------------------------------------------------------------
    # Carry + thread-shielded swap
    # ------------------------------------------------------------------

    async def carry_and_swap(
        self,
        journal: RefreshJournalRecord,
        *,
        fencing_token: int | None = None,
        retention_policy: str | int | None = None,
        exchange_supported: bool | None = None,
        now: datetime | None = None,
        guard: FencingGuard | None = None,
    ) -> CarrySwapResult:
        """Journal CARRYING, carry the complement, swap, then journal CARRIED.

        The carry plan is discovered and persisted **before** the first rename,
        so recovery can always return a partially carried tree to live. The
        carry and swap run in a worker thread awaited through
        :func:`run_thread_shielded`; the thread is joined before any
        cancellation or exception escapes. The previous tree is retained and
        its expiry recorded for hour-based policies.
        """
        token = journal.fencing_token if fencing_token is None else fencing_token
        policy, delta = parse_retention_policy(
            journal.retention_policy if retention_policy is None else retention_policy
        )
        live = _existing_plain_directory(journal.live_path, "live_path")
        staging = _existing_plain_directory(journal.staging_path, "staging_path")
        previous = previous_tree_path(live)
        if os.path.lexists(previous):
            raise ConflictError(
                f"A previous tree already exists; clean it before refreshing: {previous}"
            )

        carrying = await self._repository.transition(
            journal.journal_id,
            fencing_token=token,
            phase="CARRYING",
        )
        planned = await asyncio.to_thread(discover_complement_entries, live, staging)
        carrying = await self._repository.transition(
            journal.journal_id,
            fencing_token=token,
            phase="CARRYING",
            carried_entries=planned,
        )
        swap_journal = DirectorySwapJournal(
            self._layout.journal / carrying.server_id / SWAP_JOURNAL_FILENAME
        )

        def worker() -> tuple[list[str], SwapResult]:
            if guard is not None:
                guard.check()
            carried = carry_complement_entries(live, staging, entries=planned)
            try:
                if guard is not None:
                    guard.check()
                swap = swap_directories(
                    live,
                    staging,
                    swap_journal,
                    server_id=carrying.server_id,
                    previous_main_sha=carrying.previous_main_sha,
                    target_main_sha=carrying.target_main_sha,
                    pre_upgrade_backup_id=carrying.pre_upgrade_backup_id,
                    class_c_snapshot_id=carrying.class_c_snapshot_id,
                    export_id=carrying.export_id,
                    keep_previous=True,
                    exchange_supported=exchange_supported,
                )
            except BaseException:
                with contextlib.suppress(Exception):
                    restore_carried_entries(live, staging, carried)
                raise
            assert_carried_entries_present(live, carried)
            return carried, swap

        carried_entries, swap = await run_thread_shielded(worker)
        expires_at = None if delta is None else (now or datetime.now(UTC)) + delta
        final = await self._repository.transition(
            journal.journal_id,
            fencing_token=token,
            phase="CARRIED",
            carried_entries=carried_entries,
            previous_tree_retained=True,
            previous_tree_expires_at=expires_at,
            used_exchange=swap.used_exchange,
            retention_policy=policy,
        )
        return CarrySwapResult(
            journal=final,
            swap=swap,
            carried_entries=tuple(carried_entries),
        )


# ----------------------------------------------------------------------
# Health Gate (4 steps)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HealthGateResult:
    """Outcome of the four-step health gate."""

    passed: bool
    failed_step: str | None = None
    reason: str | None = None


def _crash_reason(boot_log: str) -> str | None:
    lowered = boot_log.lower()
    for pattern in CRASH_PATTERNS:
        if pattern in lowered:
            return f"boot log contains fatal pattern '{pattern}'"
    return None


class HealthGateEvaluator:
    """Process, boot-log, readiness, and stability checks in that order."""

    def __init__(
        self,
        *,
        process_alive: Callable[[], bool],
        boot_log: Callable[[], str] | None = None,
        ready: Callable[[], bool] | None = None,
        stability_window: float = 0.0,
        timeout: float | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        if not callable(process_alive):
            raise ValidationError(
                "process_alive probe must be callable", field="process_alive"
            )
        if not isinstance(stability_window, (int, float)) or isinstance(
            stability_window, bool
        ):
            raise ValidationError(
                "stability_window must be a number", field="stability_window"
            )
        if float(stability_window) < 0:
            raise ValidationError(
                "stability_window must be non-negative", field="stability_window"
            )
        if timeout is not None:
            if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
                raise ValidationError(
                    "timeout must be a number", field="timeout"
                )
            if float(timeout) <= 0:
                raise ValidationError(
                    "timeout must be positive", field="timeout"
                )
        self._process_alive = process_alive
        self._boot_log = boot_log
        self._ready = ready
        self._stability_window = float(stability_window)
        self._timeout = None if timeout is None else float(timeout)
        self._sleep = sleep or asyncio.sleep

    @property
    def timeout(self) -> float | None:
        """Configured readiness timeout in seconds, when bounded."""
        return self._timeout

    async def evaluate(self) -> HealthGateResult:
        """Run all four steps, stopping at the first failure."""
        if not await asyncio.to_thread(self._process_alive):
            return HealthGateResult(
                passed=False,
                failed_step=STEP_PROCESS_ALIVE,
                reason="server process is not running",
            )
        if self._boot_log is not None:
            log = await asyncio.to_thread(self._boot_log)
            if not isinstance(log, str):
                raise ValidationError(
                    "boot_log probe must return a string", field="boot_log"
                )
            reason = _crash_reason(log)
            if reason is not None:
                return HealthGateResult(
                    passed=False, failed_step=STEP_BOOT_LOG, reason=reason
                )
        if self._ready is not None:
            timeout = self._timeout
            try:
                ready_call = asyncio.to_thread(self._ready)
                if timeout is None:
                    ready = await ready_call
                else:
                    ready = await asyncio.wait_for(ready_call, timeout=timeout)
            except TimeoutError:
                return HealthGateResult(
                    passed=False,
                    failed_step=STEP_READINESS,
                    reason=(
                        "server did not report ready within "
                        f"{(timeout or 0.0):.0f}s"
                    ),
                )
            if not ready:
                return HealthGateResult(
                    passed=False,
                    failed_step=STEP_READINESS,
                    reason="server did not report ready",
                )
        if self._stability_window > 0:
            await self._sleep(self._stability_window)
        if not await asyncio.to_thread(self._process_alive):
            return HealthGateResult(
                passed=False,
                failed_step=STEP_STABILITY,
                reason="server process exited during the stability window",
            )
        if self._boot_log is not None:
            log = await asyncio.to_thread(self._boot_log)
            if isinstance(log, str):
                reason = _crash_reason(log)
                if reason is not None:
                    return HealthGateResult(
                        passed=False, failed_step=STEP_STABILITY, reason=reason
                    )
        return HealthGateResult(passed=True)


async def run_health_gate(
    *,
    process_alive: Callable[[], bool],
    boot_log: Callable[[], str] | None = None,
    ready: Callable[[], bool] | None = None,
    stability_window: float = 0.0,
    timeout: float | None = None,
    sleep: Callable[[float], Any] | None = None,
) -> HealthGateResult:
    """Convenience wrapper around :class:`HealthGateEvaluator`."""
    evaluator = HealthGateEvaluator(
        process_alive=process_alive,
        boot_log=boot_log,
        ready=ready,
        stability_window=stability_window,
        timeout=timeout,
        sleep=sleep,
    )
    return await evaluator.evaluate()


# ----------------------------------------------------------------------
# Injected ports
# ----------------------------------------------------------------------


class ServerRuntimePort(Protocol):
    """Minimal runtime surface the refresh/rollback services drive."""

    def is_running(self) -> bool: ...

    def stop(self) -> bool: ...

    def start(self) -> bool: ...

    def process_alive(self) -> bool: ...

    def boot_log(self) -> str: ...

    def ready(self) -> bool: ...


class BackupServicePort(Protocol):
    """Pinned Tier-1/Class-E backup surface used by refresh and rollback."""

    async def create_pinned_backup(self, server_id: str, live_dir: Path) -> str: ...

    async def restore_backup(
        self, server_id: str, backup_id: str, live_dir: Path
    ) -> None: ...

    async def set_pinned(
        self, server_id: str, backup_id: str, pinned: bool
    ) -> None: ...


class StageExportPort(Protocol):
    """Clean-export surface; adapters run the blocking work off the loop."""

    def __call__(
        self,
        staging: Path,
        commit_sha: str,
        *,
        export_id: str,
        fencing_verifier: Callable[[], None],
    ) -> Awaitable[Any] | Any: ...


def _noop_fencing_verifier() -> None:
    """Fencing check used only when the caller holds no repo lease token."""
    return None


class Tier1BackupServiceAdapter:
    """Default :class:`BackupServicePort` backed by the SQL backup saga.

    The runtime/export adapters stay injected at call time because the server
    module owns provider lifecycle; this adapter covers the Class-E tier that
    the versioning module can construct without crossing module boundaries.
    """

    async def create_pinned_backup(self, server_id: str, live_dir: Path) -> str:
        del live_dir  # The backup saga resolves the tree via the server provider.
        from app.api.deps import build_backup_encryption, build_storage_backend
        from app.core.config import ConfigFactory
        from app.core.persistence.db import database
        from app.core.saga import SagaOrchestrator
        from app.modules.backup.domain.aggregate import BackupJob, BackupType
        from app.modules.backup.infrastructure.repository import SQLBackupRepository
        from app.modules.shared.value_objects import BackupJobId, ServerId
        from app.services.backup_orchestrator import BackupSaga

        backup_id = BackupJobId()
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=backup_id,
                server_id=ServerId(server_id),
                backup_type=BackupType.FULL,
                pinned=True,
            )
            await repo.save_job(job)
            await session.commit()
        settings = ConfigFactory.global_settings()
        try:
            await BackupSaga(SagaOrchestrator()).execute(
                backup_id=backup_id,
                server_id=ServerId(server_id),
                storage=build_storage_backend(settings),
                encryption=build_backup_encryption(
                    settings.backup_encryption_key_path
                ),
                backup_type=BackupType.FULL,
            )
        except Exception:
            async with database.session_factory() as session:
                repo = SQLBackupRepository(session)
                failed = await repo.get_job(backup_id)
                failed.mark_failed("Tier-1 refresh backup failed")
                await repo.save_job(failed)
                await session.commit()
            raise
        return str(backup_id)

    async def restore_backup(
        self, server_id: str, backup_id: str, live_dir: Path
    ) -> None:
        from app.modules.backup.application.restore_service import perform_safe_restore
        from app.modules.shared.value_objects import BackupJobId

        del server_id  # The artifact itself is the authority for restore.
        await perform_safe_restore(BackupJobId(backup_id), str(live_dir))

    async def set_pinned(
        self, server_id: str, backup_id: str, pinned: bool
    ) -> None:
        from app.core.persistence.db import database
        from app.modules.backup.infrastructure.repository import SQLBackupRepository
        from app.modules.shared.value_objects import BackupJobId

        del server_id
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await repo.set_pinned(BackupJobId(backup_id), pinned)
            await session.commit()


def _assert_no_session_lock(live: Path) -> None:
    lock = live / SESSION_LOCK_FILENAME
    if os.path.lexists(lock):
        raise ConflictError(
            f"{SESSION_LOCK_FILENAME} is still present in {live}; "
            "the server is not fully stopped"
        )


def _as_awaitable(result: Any) -> Any:
    return result if inspect.isawaitable(result) else None


@dataclass
class FencingGuard:
    """Fail-closed liveness/fencing check for one refresh or rollback mutation."""

    server_id: str
    token: RepoLeaseToken
    repo_lease: RepoLeaseManager | None

    def _lost(self) -> bool:
        return bool(getattr(self.token, "is_lost", False))

    def check(self) -> None:
        """Synchronous check for use inside the swap/carry worker thread."""
        if self._lost():
            raise FencingTokenMismatchError(
                server_id=self.server_id,
                expected_token=self.token.fencing_token,
                actual_token=None,
            )
        if self.repo_lease is not None:
            self.repo_lease.assert_fencing_token_sync(
                self.server_id, self.token.fencing_token
            )

    async def assert_live(self) -> None:
        if self._lost():
            raise FencingTokenMismatchError(
                server_id=self.server_id,
                expected_token=self.token.fencing_token,
                actual_token=None,
            )
        if self.repo_lease is not None:
            await self.repo_lease.assert_fencing_token(
                self.server_id, self.token.fencing_token
            )


# ----------------------------------------------------------------------
# Triad rollback
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RollbackResult:
    """Outcome of a triad rollback."""

    journal: RefreshJournalRecord
    used_previous_tree: bool
    restored_class_c: bool
    restored_backup: bool


class TriadRollbackService:
    """Class A+B, Class C, and Class E rollback for one refresh journal.

    The caller is responsible for holding the lifecycle and repo leases; this
    service never acquires them so it can run inside an in-flight refresh.
    """

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        repository: RefreshJournalRepository | None = None,
        orchestrator: RefreshOrchestrator | None = None,
        class_c_service: ClassCSnapshotService | None = None,
        backup_service: BackupServicePort | None = None,
        runtime: ServerRuntimePort | None = None,
        stage_export: StageExportPort | None = None,
        reset_main_ref: Callable[[str, str], None] | None = None,
        repo_lease: RepoLeaseManager | None = None,
        servers_data_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._layout = layout
        self._repository = repository or RefreshJournalRepository(layout)
        self._orchestrator = orchestrator or RefreshOrchestrator(
            layout,
            repository=self._repository,
            servers_data_dir=servers_data_dir,
        )
        self._class_c = class_c_service or ClassCSnapshotService(layout)
        self._backup = backup_service
        self._runtime = runtime
        self._stage_export = stage_export
        self._reset_main_ref = reset_main_ref
        self._repo_lease = repo_lease

    def _assert_fence(self, server_id: str, token: int) -> None:
        """Abort before a mutation if this writer no longer owns the lease."""
        if self._repo_lease is not None:
            self._repo_lease.assert_fencing_token_sync(server_id, token)

    async def rollback(
        self,
        server_id: str,
        journal_id: str | None = None,
        *,
        reason: str = "",
        fencing_token: int | None = None,
    ) -> RollbackResult:
        """Restore Class A+B, Class C, and Class E, then journal ``ROLLED_BACK``."""
        segment = validate_server_segment(server_id)
        record = await self._load(segment, journal_id)
        if record.phase == "ROLLED_BACK":
            return RollbackResult(
                journal=record,
                used_previous_tree=False,
                restored_class_c=False,
                restored_backup=False,
            )
        if record.phase in TERMINAL_PHASES:
            raise ConflictError(
                f"Refresh journal {record.journal_id} is terminal ({record.phase}) "
                "and cannot be rolled back"
            )
        # B-A1: the newly acquired lease token proves this writer is live, but
        # journal CAS transitions must use the *journal row's* token. A crash
        # recovery rollback holds lease token 2 while the journal still records
        # the crashed refresh's token 1.
        lease_token = record.fencing_token if fencing_token is None else fencing_token
        journal_token = record.fencing_token
        self._assert_fence(segment, lease_token)
        journal = await self._repository.transition(
            record.journal_id,
            fencing_token=journal_token,
            phase="ROLLING_BACK",
            error=reason or None,
        )
        live = self._orchestrator._path_guard.validate_swap_path(
            segment, journal.live_path, field="live_path"
        )
        if live.is_symlink() or not live.is_dir():
            raise ValidationError(
                "live_path is not a plain directory", field="live_path"
            )
        self._assert_fence(segment, lease_token)
        await self._stop_runtime()
        _assert_no_session_lock(live)

        used_previous = await self._restore_class_ab(
            segment, journal, live, lease_token
        )
        restored_class_c = False
        if journal.class_c_snapshot_id:
            self._assert_fence(segment, lease_token)
            await asyncio.to_thread(
                self._class_c.restore_snapshot,
                segment,
                journal.class_c_snapshot_id,
                live,
            )
            restored_class_c = True
        restored_backup = False
        if journal.pre_upgrade_backup_id:
            if self._backup is None:
                raise ValidationError(
                    "Class-E restore requires a backup service",
                    field="pre_upgrade_backup_id",
                )
            self._assert_fence(segment, lease_token)
            await self._backup.restore_backup(
                segment, journal.pre_upgrade_backup_id, live
            )
            restored_backup = True
        if self._reset_main_ref is not None and journal.previous_main_sha:
            self._assert_fence(segment, lease_token)
            await asyncio.to_thread(
                self._reset_main_ref, segment, journal.previous_main_sha
            )

        self._assert_fence(segment, lease_token)
        await self._repository.mark_previous_tree_cleaned(journal.journal_id)
        self._assert_fence(segment, lease_token)
        final = await self._repository.transition(
            journal.journal_id,
            fencing_token=journal.fencing_token,
            phase="ROLLED_BACK",
            error=reason or "refresh rolled back",
        )
        return RollbackResult(
            journal=final,
            used_previous_tree=used_previous,
            restored_class_c=restored_class_c,
            restored_backup=restored_backup,
        )

    async def _restore_class_ab(
        self,
        segment: str,
        journal: RefreshJournalRecord,
        live: Path,
        token: int,
    ) -> bool:
        try:
            previous = self._orchestrator.previous_tree_for(journal)
        except ValidationError:
            previous = None
        if previous is not None and os.path.lexists(previous):
            await asyncio.to_thread(
                self._swap_previous_tree, segment, journal, live, previous, token
            )
            return True
        await self._reexport_previous_tree(segment, journal, live, token)
        return False

    def _swap_previous_tree(
        self,
        segment: str,
        journal: RefreshJournalRecord,
        live: Path,
        previous: Path,
        token: int,
    ) -> None:
        if previous.is_symlink() or not previous.is_dir():
            raise ValidationError(
                "Retained previous tree is not a plain directory",
                field="previous_path",
            )
        self._assert_fence(segment, token)
        rollback_source = live.with_name(live.name + ROLLBACK_SOURCE_SUFFIX)
        if os.path.lexists(rollback_source):
            raise ConflictError(
                f"A stale rollback source blocks rollback: {rollback_source}"
            )
        os.rename(previous, rollback_source)
        swap_journal = DirectorySwapJournal(
            self._layout.journal / segment / ROLLBACK_SWAP_JOURNAL_FILENAME
        )
        try:
            self._assert_fence(segment, token)
            swap = swap_directories(
                live,
                rollback_source,
                swap_journal,
                server_id=segment,
                previous_main_sha=journal.previous_main_sha,
                target_main_sha=journal.target_main_sha,
                keep_previous=False,
            )
        except BaseException:
            with contextlib.suppress(OSError):
                if os.path.lexists(rollback_source) and not os.path.lexists(previous):
                    os.rename(rollback_source, previous)
            raise
        broken = swap.previous_tree_path
        if os.path.lexists(broken):
            if broken.is_symlink() or not broken.is_dir():
                raise ValidationError(
                    "Broken tree is not a plain directory", field="previous_path"
                )
            self._assert_fence(segment, token)
            carry_complement_entries(broken, live)
            shutil.rmtree(broken)

    async def _reexport_previous_tree(
        self,
        segment: str,
        journal: RefreshJournalRecord,
        live: Path,
        token: int,
    ) -> None:
        if self._stage_export is None:
            raise ValidationError(
                "No previous tree is retained and no export runner is available",
                field="previous_path",
            )
        if not journal.previous_main_sha:
            raise ValidationError(
                "Cannot re-export the previous release without previous_main_sha",
                field="previous_main_sha",
            )
        staging = live.with_name(live.name + ROLLBACK_SUFFIX)
        if os.path.lexists(staging):
            raise ConflictError(f"A stale rollback tree blocks rollback: {staging}")
        try:
            result = self._stage_export(
                staging,
                journal.previous_main_sha,
                export_id=journal.export_id or journal.journal_id,
                fencing_verifier=lambda: self._assert_fence(segment, token),
            )
            awaitable = _as_awaitable(result)
            if awaitable is not None:
                await awaitable
        except BaseException:
            with contextlib.suppress(OSError):
                if os.path.lexists(staging) and not staging.is_symlink():
                    shutil.rmtree(staging)
            raise
        if staging.is_symlink() or not staging.is_dir():
            raise ValidationError(
                "Re-export did not produce a staging directory", field="staging_path"
            )
        self._assert_fence(segment, token)
        carried = discover_complement_entries(live, staging)
        # Persist the inverse-carry plan before the first rename so a crash is
        # recoverable even when the swap never reaches its journal.
        await self._repository.transition(
            journal.journal_id,
            fencing_token=journal.fencing_token,
            phase="ROLLING_BACK",
            carried_entries=carried,
        )
        try:
            carry_complement_entries(live, staging, entries=carried)
            self._assert_fence(segment, token)
            swap_journal = DirectorySwapJournal(
                self._layout.journal / segment / ROLLBACK_SWAP_JOURNAL_FILENAME
            )
            swap = swap_directories(
                live,
                staging,
                swap_journal,
                server_id=segment,
                previous_main_sha=journal.previous_main_sha,
                target_main_sha=journal.target_main_sha,
                keep_previous=False,
            )
        except BaseException:
            # Match carry_and_swap: return every moved entry to live before the
            # error escapes, otherwise the only copy would be stranded in the
            # .rollback tree.
            if os.path.lexists(staging):
                with contextlib.suppress(Exception):
                    restore_carried_entries(live, staging, carried)
            raise
        broken = swap.previous_tree_path
        if os.path.lexists(broken):
            if broken.is_symlink() or not broken.is_dir():
                raise ValidationError(
                    "Broken tree is not a plain directory", field="previous_path"
                )
            shutil.rmtree(broken)

    async def _stop_runtime(self) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        if await asyncio.to_thread(runtime.is_running):
            confirmed = await asyncio.to_thread(runtime.stop)
            if not confirmed:
                raise ConflictError(
                    "Server runtime did not confirm stop during rollback"
                )
        # B-2: never swap the live tree under a container that a fresh inspect
        # still reports running. The journal stays ROLLING_BACK and the caller
        # fails closed for operator reconciliation.
        if await asyncio.to_thread(runtime.is_running):
            raise ConflictError(
                "Server runtime is still running after stop during rollback; "
                "refusing to touch the live tree"
            )

    async def _load(
        self, server_id: str, journal_id: str | None
    ) -> RefreshJournalRecord:
        if journal_id is None:
            record = await self._repository.get_active_for_server(server_id)
            if record is None:
                raise NotFoundError(
                    f"No active refresh journal for server '{server_id}'"
                )
        else:
            if not isinstance(journal_id, str) or not journal_id:
                raise ValidationError(
                    "journal_id must be a non-empty string", field="journal_id"
                )
            record = await self._repository.get(journal_id)
            if record is None:
                raise NotFoundError(f"Refresh journal '{journal_id}' not found")
        if record.server_id != server_id:
            raise ValidationError(
                "Refresh journal belongs to a different server", field="server_id"
            )
        return record


# ----------------------------------------------------------------------
# Live refresh (seven steps)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LiveRefreshRequest:
    """Inputs for one atomic live refresh."""

    server_id: str
    live_dir: str | os.PathLike[str]
    staging_dir: str | os.PathLike[str]
    export_bytes: int
    backup_bytes: int = 0
    class_c_snapshot_bytes: int = 0
    retained_prev_tree_bytes: int = 0
    rollback_headroom: int = 0
    retention_policy: str | int = RETENTION_UNTIL_HEALTH_GATE
    previous_main_sha: str = ""
    target_main_sha: str = ""
    export_id: str = ""

    def __post_init__(self) -> None:
        validate_server_segment(self.server_id)
        parse_retention_policy(self.retention_policy)
        # An empty export id disables already-swapped exchange recovery, so
        # every request always gets a durable, non-empty identity.
        if not self.export_id:
            object.__setattr__(self, "export_id", uuid.uuid4().hex)


@dataclass(frozen=True)
class LiveRefreshResult:
    """Outcome of one seven-step live refresh."""

    journal: RefreshJournalRecord
    health: HealthGateResult
    class_c_snapshot_id: str
    pre_upgrade_backup_id: str
    rolled_back: bool = False


@dataclass(frozen=True)
class _LeaseHandle:
    """The live lease token plus the fencing guard bound to it."""

    fencing_token: int
    guard: FencingGuard | None


class LiveRefreshService:
    """Seven-step atomic live refresh with an automatic triad rollback."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        repository: RefreshJournalRepository | None = None,
        orchestrator: RefreshOrchestrator | None = None,
        rollback_service: TriadRollbackService | None = None,
        class_c_service: ClassCSnapshotService | None = None,
        backup_service: BackupServicePort | None = None,
        runtime: ServerRuntimePort | None = None,
        health_gate: HealthGateEvaluator | None = None,
        stage_export: StageExportPort | None = None,
        reset_main_ref: Callable[[str, str], None] | None = None,
        lifecycle_lease: Any | None = None,
        repo_lease: RepoLeaseManager,
        servers_data_dir: str | os.PathLike[str] | None = None,
        stability_window: float = 0.0,
        fencing_token: int = 1,
        lease_wait_timeout: float = 60.0,
        holder: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if repo_lease is None:
            raise ValidationError(
                "A repo lease manager is required for live refresh",
                field="repo_lease",
            )
        self._layout = layout
        self._repository = repository or RefreshJournalRepository(layout)
        dialect = getattr(self._repository, "dialect_name", None)
        if isinstance(dialect, str) and dialect.lower() != "sqlite":
            raise ServerModeVersioningDisabledError(
                "Live refresh is SQLite-only until the Postgres sync driver "
                f"and CI job are approved; this database uses '{dialect or 'unknown'}'"
            )
        self._orchestrator = orchestrator or RefreshOrchestrator(
            layout,
            repository=self._repository,
            servers_data_dir=servers_data_dir,
        )
        self._class_c = class_c_service or ClassCSnapshotService(layout)
        self._backup = backup_service
        self._runtime = runtime
        self._health_gate = health_gate
        self._stage_export = stage_export
        self._lifecycle_lease = lifecycle_lease
        self._repo_lease = repo_lease
        self._stability_window = stability_window
        self._fencing_token = fencing_token
        self._lease_wait_timeout = lease_wait_timeout
        self._holder = holder or f"LiveRefreshService:{os.getpid()}"
        self._now = now or (lambda: datetime.now(UTC))
        self._rollback = rollback_service or TriadRollbackService(
            layout,
            repository=self._repository,
            orchestrator=self._orchestrator,
            class_c_service=self._class_c,
            backup_service=backup_service,
            runtime=runtime,
            stage_export=stage_export,
            reset_main_ref=reset_main_ref,
            repo_lease=repo_lease,
            servers_data_dir=servers_data_dir,
        )

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def _lease_context(self, server_id: str) -> AsyncIterator[_LeaseHandle]:
        lifecycle = self._lifecycle_lease
        repo = self._repo_lease
        timeout = self._lease_wait_timeout
        holder = self._holder

        def handle(token: RepoLeaseToken) -> _LeaseHandle:
            fencing_token = int(getattr(token, "fencing_token", self._fencing_token))
            return _LeaseHandle(
                fencing_token=fencing_token,
                guard=FencingGuard(server_id, token, repo),
            )

        if lifecycle is None:
            async with repo.acquire(
                server_id, holder=holder, wait_timeout=timeout
            ) as token:
                yield handle(token)
            return
        async with (
            lifecycle.acquire(
                server_id, holder=holder, wait_timeout=timeout
            ) as _lifecycle_token,
            repo.acquire(
                server_id, holder=holder, wait_timeout=timeout
            ) as token,
        ):
            yield handle(token)

    async def _transition(
        self,
        journal_id: str,
        *,
        guard: FencingGuard | None,
        token: int,
        phase: str,
        **kwargs: Any,
    ) -> RefreshJournalRecord:
        if guard is not None:
            await guard.assert_live()
        return await self._repository.transition(
            journal_id, fencing_token=token, phase=phase, **kwargs
        )

    def _require_runtime(self) -> ServerRuntimePort:
        if self._runtime is None:
            raise ValidationError(
                "A server runtime is required for live refresh", field="runtime"
            )
        return self._runtime

    def _require_backup(self) -> BackupServicePort:
        if self._backup is None:
            raise ValidationError(
                "A backup service is required for live refresh", field="backup_service"
            )
        return self._backup

    def _require_stage_export(self) -> StageExportPort:
        if self._stage_export is None:
            raise ValidationError(
                "An export runner is required for live refresh", field="stage_export"
            )
        return self._stage_export

    def _evaluator(self, runtime: ServerRuntimePort) -> HealthGateEvaluator:
        if self._health_gate is not None:
            return self._health_gate
        raw_timeout = getattr(runtime, "startup_timeout_seconds", None)
        timeout = (
            float(raw_timeout)
            if isinstance(raw_timeout, (int, float))
            and not isinstance(raw_timeout, bool)
            and raw_timeout > 0
            else None
        )
        return HealthGateEvaluator(
            process_alive=runtime.process_alive,
            boot_log=getattr(runtime, "boot_log", None),
            ready=getattr(runtime, "ready", None),
            stability_window=self._stability_window,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def refresh(self, request: LiveRefreshRequest) -> LiveRefreshResult:
        """Run the seven-step refresh; roll back automatically on failure."""
        _require_posix_live_refresh()
        segment = validate_server_segment(request.server_id)
        policy, delta = parse_retention_policy(request.retention_policy)
        live = _existing_plain_directory(request.live_dir, "live_dir")
        staging = _absolute_path(request.staging_dir, "staging_dir")
        async with self._lease_context(segment) as lease:
            token = lease.fencing_token
            guard = lease.guard
            self._orchestrator.preflight(
                segment,
                live_dir=live,
                staging_dir=staging,
                export_bytes=request.export_bytes,
                backup_bytes=request.backup_bytes,
                class_c_snapshot_bytes=request.class_c_snapshot_bytes,
                retained_prev_tree_bytes=request.retained_prev_tree_bytes,
                rollback_headroom=request.rollback_headroom,
            )
            # M-5: scan the committed tree before _quiesce stops the server.
            # An unresolved ${ONX_SECRET_*} would otherwise fail at STAGING,
            # after downtime has already begun.
            preflight_secrets = getattr(
                self._stage_export, "assert_no_unresolved_secrets", None
            )
            if callable(preflight_secrets):
                await asyncio.to_thread(
                    preflight_secrets, segment, live, request.target_main_sha
                )
            await self._orchestrator.prepare_prior_previous_tree(
                segment, retention_policy=policy
            )
            journal = await self._quiesce(
                segment, request, live, staging, policy, token, guard
            )
            try:
                return await self._refresh_locked(
                    segment,
                    request,
                    live,
                    staging,
                    journal,
                    policy,
                    delta,
                    token,
                    guard,
                )
            except BaseException as exc:
                await self._compensate(journal, token, exc, guard)
                raise

    async def _quiesce(
        self,
        segment: str,
        request: LiveRefreshRequest,
        live: Path,
        staging: Path,
        policy: str,
        token: int,
        guard: FencingGuard | None = None,
    ) -> RefreshJournalRecord:
        if guard is not None:
            await guard.assert_live()
        runtime = self._require_runtime()
        if await asyncio.to_thread(runtime.is_running):
            confirmed = await asyncio.to_thread(runtime.stop)
            if not confirmed:
                raise ConflictError(
                    f"Server '{segment}' did not confirm stop; refresh aborted"
                )
        _assert_no_session_lock(live)
        if guard is not None:
            await guard.assert_live()
        return await self._repository.create(
            server_id=segment,
            fencing_token=token,
            live_path=live,
            staging_path=staging,
            previous_path=previous_tree_path(live),
            export_id=request.export_id or None,
            phase="QUIESCED",
            previous_main_sha=request.previous_main_sha,
            target_main_sha=request.target_main_sha,
            retention_policy=policy,
        )

    async def _refresh_locked(
        self,
        segment: str,
        request: LiveRefreshRequest,
        live: Path,
        staging: Path,
        journal: RefreshJournalRecord,
        policy: str,
        delta: timedelta | None,
        token: int,
        guard: FencingGuard | None = None,
    ) -> LiveRefreshResult:
        backup = self._require_backup()
        stage_export = self._require_stage_export()
        runtime = self._require_runtime()

        if guard is not None:
            await guard.assert_live()
        snapshot: ClassCSnapshotResult = await asyncio.to_thread(
            self._class_c.create_snapshot, segment, live, pinned=True
        )
        if guard is not None:
            await guard.assert_live()
        backup_id = await backup.create_pinned_backup(segment, live)
        journal = await self._transition(
            journal.journal_id,
            guard=guard,
            token=token,
            phase="BACKED_UP",
            pre_upgrade_backup_id=backup_id,
            class_c_snapshot_id=snapshot.snapshot_id,
        )

        journal = await self._transition(
            journal.journal_id, guard=guard, token=token, phase="STAGING"
        )
        if guard is not None:
            await guard.assert_live()
        with staging_enospc_guard(staging, live_dir=live):
            staged = stage_export(
                staging,
                request.target_main_sha,
                export_id=journal.export_id or request.export_id,
                fencing_verifier=(
                    guard.check if guard is not None else _noop_fencing_verifier
                ),
            )
            awaitable = _as_awaitable(staged)
            if awaitable is not None:
                await awaitable

        carried = await self._orchestrator.carry_and_swap(
            journal,
            fencing_token=token,
            retention_policy=policy,
            now=self._now(),
            guard=guard,
        )
        journal = carried.journal

        journal = await self._transition(
            journal.journal_id, guard=guard, token=token, phase="STARTING"
        )
        mark_refresh_start = getattr(runtime, "mark_refresh_start", None)
        if callable(mark_refresh_start):
            mark_refresh_start(self._now())
        prepare_start = getattr(runtime, "prepare_start", None)
        if callable(prepare_start):
            prepare_start(journal.journal_id)
        if not await asyncio.to_thread(runtime.start):
            raise ConflictError(f"Server '{segment}' failed to start after the swap")
        journal = await self._transition(
            journal.journal_id, guard=guard, token=token, phase="VERIFYING_HEALTH"
        )
        health = await self._evaluator(runtime).evaluate()
        if not health.passed:
            rolled = await self._rollback.rollback(
                segment,
                journal.journal_id,
                reason=health.reason or f"health gate failed at {health.failed_step}",
                fencing_token=token,
            )
            return LiveRefreshResult(
                journal=rolled.journal,
                health=health,
                class_c_snapshot_id=journal.class_c_snapshot_id,
                pre_upgrade_backup_id=journal.pre_upgrade_backup_id,
                rolled_back=True,
            )

        if policy == RETENTION_UNTIL_HEALTH_GATE:
            # Record COMPLETED (terminal) before deleting the previous tree so a
            # crash can never leave a terminal-less VERIFYING_HEALTH journal
            # pointing at a tree that no longer exists.
            journal = await self._transition(
                journal.journal_id,
                guard=guard,
                token=token,
                phase="COMPLETED",
                previous_tree_retained=True,
            )
            await self._clean_previous(journal, guard)
            journal = await self._repository.get(journal.journal_id) or journal
        elif policy == RETENTION_UNTIL_CONFIRM:
            journal = await self._transition(
                journal.journal_id,
                guard=guard,
                token=token,
                phase="COMPLETED",
                previous_tree_retained=True,
            )
        else:
            expires_at = self._now() + (delta or timedelta(0))
            journal = await self._transition(
                journal.journal_id,
                guard=guard,
                token=token,
                phase="COMPLETED",
                previous_tree_retained=True,
                previous_tree_expires_at=expires_at,
            )
        return LiveRefreshResult(
            journal=journal,
            health=health,
            class_c_snapshot_id=journal.class_c_snapshot_id,
            pre_upgrade_backup_id=journal.pre_upgrade_backup_id,
        )

    async def _compensate(
        self,
        journal: RefreshJournalRecord,
        token: int,
        exc: BaseException,
        guard: FencingGuard | None = None,
    ) -> None:
        current = await self._repository.get(journal.journal_id)
        if current is None or current.terminal:
            return
        if guard is not None:
            # Never mutate a tree for a lease this writer no longer owns.
            await guard.assert_live()
        if current.phase in ("CARRIED", "STARTING", "HEALTH_CHECK", "VERIFYING_HEALTH"):
            with contextlib.suppress(Exception):
                await self._rollback.rollback(
                    journal.server_id,
                    journal.journal_id,
                    reason=f"refresh failed: {exc}"[:200],
                    fencing_token=token,
                )
            return
        if current.phase == "CARRYING":
            # The swap journal proves whether a swap may have happened; only
            # the no-swap-journal case is safe to fail clean after restoring
            # every journaled carried entry.
            swap_path = (
                self._layout.journal
                / current.server_id
                / SWAP_JOURNAL_FILENAME
            )
            if os.path.lexists(swap_path):
                with contextlib.suppress(Exception):
                    await self._rollback.rollback(
                        journal.server_id,
                        journal.journal_id,
                        reason=f"refresh failed during carry/swap: {exc}"[:200],
                        fencing_token=token,
                    )
                return
            try:
                if current.carried_entries and os.path.lexists(current.staging_path):
                    live = self._orchestrator._path_guard.validate_swap_path(
                        current.server_id, current.live_path, field="live_path"
                    )
                    staging = self._orchestrator._path_guard.validate_swap_path(
                        current.server_id, current.staging_path, field="staging_path"
                    )
                    await asyncio.to_thread(
                        restore_carried_entries,
                        live,
                        staging,
                        current.carried_entries,
                    )
                    await asyncio.to_thread(
                        assert_carried_entries_present,
                        live,
                        current.carried_entries,
                    )
                await self._repository.transition(
                    journal.journal_id,
                    fencing_token=token,
                    phase="FAILED_CLEAN",
                    error=f"refresh aborted during complement carry: {exc}"[:200],
                )
            except Exception:
                logger.exception(
                    "Failed to clean interrupted CARRYING journal %s",
                    journal.journal_id,
                )
            return
        if current.phase in ("QUIESCED", "BACKED_UP", "STAGING", "ROLLBACK_REQUIRED"):
            with contextlib.suppress(Exception):
                await self._repository.transition(
                    journal.journal_id,
                    fencing_token=token,
                    phase="FAILED_CLEAN",
                    error=f"refresh aborted before the swap: {exc}"[:200],
                )

    async def _clean_previous(
        self, journal: RefreshJournalRecord, guard: FencingGuard | None = None
    ) -> bool:
        if guard is not None:
            await guard.assert_live()
        removed = await asyncio.to_thread(
            self._orchestrator.clean_previous_tree, journal
        )
        await self._repository.mark_previous_tree_cleaned(journal.journal_id)
        return removed

    # ------------------------------------------------------------------
    # Explicit confirm/unpin and manual rollback
    # ------------------------------------------------------------------

    async def confirm_upgrade_unpin(
        self, server_id: str, journal_id: str | None = None
    ) -> RefreshJournalRecord:
        """Unpin the backup and Class-C snapshot and mark ``UPGRADE_CONFIRMED``."""
        _require_posix_live_refresh()
        segment = validate_server_segment(server_id)
        async with self._lease_context(segment) as lease:
            guard = lease.guard
            if guard is not None:
                await guard.assert_live()
            record = await self._load(segment, journal_id)
            if record.phase == "UPGRADE_CONFIRMED":
                return record
            if record.phase != "COMPLETED":
                raise ConflictError(
                    f"Refresh journal {record.journal_id} is {record.phase}; "
                    "only a COMPLETED upgrade can be confirmed"
                )
            if record.pre_upgrade_backup_id:
                backup = self._require_backup()
                if guard is not None:
                    await guard.assert_live()
                await backup.set_pinned(
                    segment, record.pre_upgrade_backup_id, False
                )
            if record.class_c_snapshot_id:
                if guard is not None:
                    await guard.assert_live()
                await asyncio.to_thread(
                    self._class_c.unpin_snapshot,
                    segment,
                    record.class_c_snapshot_id,
                )
            if record.retention_policy == RETENTION_UNTIL_CONFIRM:
                await self._clean_previous(record, guard)
            if guard is not None:
                await guard.assert_live()
            return await self._repository.mark_upgrade_confirmed(
                record.journal_id, fencing_token=record.fencing_token
            )

    async def release_pins(
        self, server_id: str, journal_id: str | None = None
    ) -> RefreshJournalRecord:
        """Explicitly unpin a rolled-back/failed journal's backup and snapshot.

        ``ROLLED_BACK`` and ``FAILED_CLEAN`` journals deliberately keep their
        recovery artifacts pinned; an operator releases them only after
        deciding not to retry the refresh.
        """
        _require_posix_live_refresh()
        segment = validate_server_segment(server_id)
        async with self._lease_context(segment) as lease:
            guard = lease.guard
            if guard is not None:
                await guard.assert_live()
            record = await self._load(segment, journal_id)
            if record.phase not in ("ROLLED_BACK", "FAILED_CLEAN"):
                raise ConflictError(
                    f"Refresh journal {record.journal_id} is {record.phase}; "
                    "pins can only be released for ROLLED_BACK or FAILED_CLEAN"
                )
            if record.pre_upgrade_backup_id:
                backup = self._require_backup()
                if guard is not None:
                    await guard.assert_live()
                await backup.set_pinned(
                    segment, record.pre_upgrade_backup_id, False
                )
            if record.class_c_snapshot_id:
                if guard is not None:
                    await guard.assert_live()
                await asyncio.to_thread(
                    self._class_c.unpin_snapshot,
                    segment,
                    record.class_c_snapshot_id,
                )
            return record

    async def rollback(
        self,
        server_id: str,
        journal_id: str | None = None,
        *,
        reason: str = "",
    ) -> RollbackResult:
        """Roll back while holding the lifecycle then repo lease."""
        _require_posix_live_refresh()
        segment = validate_server_segment(server_id)
        async with self._lease_context(segment) as lease:
            return await self._rollback.rollback(
                segment,
                journal_id,
                reason=reason,
                fencing_token=lease.fencing_token,
            )

    async def _load(
        self, server_id: str, journal_id: str | None
    ) -> RefreshJournalRecord:
        if journal_id is None:
            record = await self._repository.get_active_for_server(server_id)
            if record is None:
                record = await self._repository.get_latest_for_server(server_id)
            if record is None:
                raise NotFoundError(
                    f"No refresh journal for server '{server_id}'"
                )
        else:
            record = await self._repository.get(journal_id)
            if record is None:
                raise NotFoundError(f"Refresh journal '{journal_id}' not found")
        if record.server_id != server_id:
            raise ValidationError(
                "Refresh journal belongs to a different server", field="server_id"
            )
        return record


# ----------------------------------------------------------------------
# Application / bus commands (no HTTP routes)
# ----------------------------------------------------------------------


class RefreshServerCommand(Command):
    """Command wrapper for a seven-step live refresh."""

    server_id: str
    request: LiveRefreshRequest


class ConfirmUpgradeCommand(Command):
    """Command wrapper for the explicit confirm/unpin step."""

    server_id: str
    journal_id: str | None = None


class RollbackRefreshCommand(Command):
    """Command wrapper for a manual triad rollback."""

    server_id: str
    journal_id: str | None = None
    reason: str = ""


class ReleaseRefreshPinsCommand(Command):
    """Command wrapper for explicitly unpinning a rolled-back journal."""

    server_id: str
    journal_id: str | None = None


RefreshServiceFactory = (
    LiveRefreshService
    | Callable[[str], Awaitable[LiveRefreshService] | LiveRefreshService]
)


async def _resolve_refresh_service(
    service: RefreshServiceFactory, server_id: str
) -> LiveRefreshService:
    """Resolve a per-request service, awaiting an async factory when supplied."""
    if isinstance(service, LiveRefreshService):
        return service
    result = service(server_id)
    if inspect.isawaitable(result):
        return await cast(Awaitable[LiveRefreshService], result)
    return cast(LiveRefreshService, result)


class RefreshServerCommandHandler(CommandHandler[RefreshServerCommand]):
    def __init__(self, service: RefreshServiceFactory) -> None:
        self._service = service

    async def handle(self, command: RefreshServerCommand) -> CommandResult:
        return CommandResult(success=True, data=await self(command))

    async def __call__(self, command: RefreshServerCommand) -> LiveRefreshResult:
        if command.request.server_id != command.server_id:
            raise ValidationError(
                "command server_id does not match the refresh request",
                field="server_id",
            )
        service = await _resolve_refresh_service(self._service, command.server_id)
        return await service.refresh(command.request)


class ConfirmUpgradeCommandHandler(CommandHandler[ConfirmUpgradeCommand]):
    def __init__(self, service: RefreshServiceFactory) -> None:
        self._service = service

    async def handle(self, command: ConfirmUpgradeCommand) -> CommandResult:
        return CommandResult(success=True, data=await self(command))

    async def __call__(self, command: ConfirmUpgradeCommand) -> RefreshJournalRecord:
        service = await _resolve_refresh_service(self._service, command.server_id)
        return await service.confirm_upgrade_unpin(
            command.server_id, command.journal_id
        )


class RollbackRefreshCommandHandler(CommandHandler[RollbackRefreshCommand]):
    def __init__(self, service: RefreshServiceFactory) -> None:
        self._service = service

    async def handle(self, command: RollbackRefreshCommand) -> CommandResult:
        return CommandResult(success=True, data=await self(command))

    async def __call__(self, command: RollbackRefreshCommand) -> RollbackResult:
        service = await _resolve_refresh_service(self._service, command.server_id)
        return await service.rollback(
            command.server_id, command.journal_id, reason=command.reason
        )


class ReleaseRefreshPinsCommandHandler(CommandHandler[ReleaseRefreshPinsCommand]):
    def __init__(self, service: RefreshServiceFactory) -> None:
        self._service = service

    async def handle(self, command: ReleaseRefreshPinsCommand) -> CommandResult:
        return CommandResult(success=True, data=await self(command))

    async def __call__(self, command: ReleaseRefreshPinsCommand) -> RefreshJournalRecord:
        service = await _resolve_refresh_service(self._service, command.server_id)
        return await service.release_pins(command.server_id, command.journal_id)


__all__ = [
    "CRASH_PATTERNS",
    "DEFAULT_SPACE_HEADROOM",
    "PREVIOUS_SUFFIX",
    "RETENTION_UNTIL_CONFIRM",
    "RETENTION_UNTIL_HEALTH_GATE",
    "ROLLBACK_SUFFIX",
    "SESSION_LOCK_FILENAME",
    "STAGING_SUFFIX",
    "STEP_BOOT_LOG",
    "STEP_PROCESS_ALIVE",
    "STEP_READINESS",
    "STEP_STABILITY",
    "BackupServicePort",
    "CarrySwapResult",
    "ConfirmUpgradeCommand",
    "ConfirmUpgradeCommandHandler",
    "FencingGuard",
    "HealthGateEvaluator",
    "HealthGateResult",
    "LiveRefreshRequest",
    "LiveRefreshResult",
    "LiveRefreshService",
    "RefreshOrchestrator",
    "RefreshServerCommand",
    "RefreshServerCommandHandler",
    "RefreshServiceFactory",
    "ReleaseRefreshPinsCommand",
    "ReleaseRefreshPinsCommandHandler",
    "RollbackRefreshCommand",
    "RollbackRefreshCommandHandler",
    "RollbackResult",
    "ServerRuntimePort",
    "StageExportPort",
    "Tier1BackupServiceAdapter",
    "TriadRollbackService",
    "assert_carried_entries_present",
    "carry_complement_entries",
    "check_refresh_free_space",
    "check_swap_preconditions",
    "check_worktree_locks",
    "discover_complement_entries",
    "parse_retention_policy",
    "previous_tree_path",
    "required_free_bytes",
    "restore_carried_entries",
    "run_health_gate",
    "run_thread_shielded",
    "staging_enospc_guard",
]
