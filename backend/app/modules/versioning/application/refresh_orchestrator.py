"""Refresh staging, complement carry, swap, and retention orchestration (P2-5d1).

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
  (``D-P25-11``).

The full Health Gate, triad rollback, and confirm/unpin service land in P2-5d2.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import math
import os
import re
import shutil
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.exceptions import (
    ConflictError,
    InsufficientStorageError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.application.refresh_recovery import (
    RefreshStartupReconciler,
)
from app.modules.versioning.infrastructure.directory_swap import (
    DirectorySwapJournal,
    SwapResult,
    swap_directories,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    RefreshJournalRecord,
    RefreshJournalRepository,
)

DEFAULT_SPACE_HEADROOM = 1.10
STAGING_SUFFIX = ".staging"
PREVIOUS_SUFFIX = ".prev"
SWAP_JOURNAL_FILENAME = "swap.json"

RETENTION_UNTIL_HEALTH_GATE = "until_health_gate"
RETENTION_UNTIL_CONFIRM = "until_confirm"

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


def _free_bytes(path: Path) -> int:
    vfs = os.statvfs(path)
    return int(vfs.f_bavail) * int(vfs.f_frsize)


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
) -> list[str]:
    """Move every non-export-owned live entry into staging, atomically per entry.

    On any failure the already-moved entries are returned to live before the
    error propagates; ``ENOSPC`` becomes :class:`InsufficientStorageError`.
    """
    live = _existing_plain_directory(live_dir, "live_dir")
    staging = _existing_plain_directory(staging_dir, "staging_dir")
    entries = discover_complement_entries(live, staging)
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
    ) -> CarrySwapResult:
        """Journal CARRYING, carry the complement, swap, then journal CARRIED.

        The carry and swap run in a worker thread awaited through
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
        swap_journal = DirectorySwapJournal(
            self._layout.journal / carrying.server_id / SWAP_JOURNAL_FILENAME
        )

        def worker() -> tuple[list[str], SwapResult]:
            carried = carry_complement_entries(live, staging)
            try:
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
        )
        return CarrySwapResult(
            journal=final,
            swap=swap,
            carried_entries=tuple(carried_entries),
        )


__all__ = [
    "DEFAULT_SPACE_HEADROOM",
    "PREVIOUS_SUFFIX",
    "RETENTION_UNTIL_CONFIRM",
    "RETENTION_UNTIL_HEALTH_GATE",
    "STAGING_SUFFIX",
    "CarrySwapResult",
    "RefreshOrchestrator",
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
    "run_thread_shielded",
    "staging_enospc_guard",
]
