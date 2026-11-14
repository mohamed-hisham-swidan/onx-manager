"""Startup recovery for interrupted refresh/swap journals (P2-5c).

The reconciler runs before DB and filesystem reconciliation so the rest of the
boot sees consistent trees:

1. every ``<host_state>/journal/<server>/swap.json`` is path-checked and
   reconciled through :func:`recover_interrupted_swap`;
2. matching active ``refresh_journals`` rows advance to ``SWAP_COMPLETED`` or
   ``SWAP_ROLLED_BACK``;
3. unfinalized ``*.staging`` directories without a completion marker are
   removed, unless an active journal still references them as the old live
   tree after a successful exchange;
4. expired retained previous trees are pruned and marked cleaned.

Path safety (M-4) is enforced before every rename or ``rmtree``: paths must be
strictly below ``servers_data_dir``, belong to the journal's ``server_id``, and
must not traverse symlinks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import AppSettings
from app.core.exceptions import ValidationError
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.infrastructure.directory_swap import (
    PHASE_SWAP_COMPLETED,
    PHASE_SWAP_ROLLED_BACK,
    DirectorySwapJournal,
    SwapRecoveryResult,
    recover_interrupted_swap,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    RefreshJournalRecord,
    RefreshJournalRepository,
)

logger = logging.getLogger(__name__)

EXPORT_MARKER_NAME = ".onx-complete.json"
STAGING_SUFFIX = ".staging"


@dataclass(frozen=True)
class RefreshRecoverySummary:
    recovered_swaps: tuple[str, ...] = ()
    transitioned_journals: tuple[str, ...] = ()
    removed_staging: tuple[str, ...] = ()
    pruned_previous_trees: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(
            self.recovered_swaps
            or self.transitioned_journals
            or self.removed_staging
            or self.pruned_previous_trees
        )


def _resolved_root(raw: str | os.PathLike[str]) -> Path:
    path = Path(os.fspath(raw)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.realpath(path))


def _server_owned_component(component: str, server_id: str) -> bool:
    return (
        component == server_id
        or component == f"{server_id}{STAGING_SUFFIX}"
        or component == f"{server_id}.prev"
        or component.startswith(f"{server_id}{STAGING_SUFFIX}.")
        or component.startswith(f"{server_id}.prev.")
        or component.startswith(f".{server_id}{STAGING_SUFFIX}_")
    )


def _same_declared_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return os.path.normpath(os.path.abspath(left)) == os.path.normpath(
        os.path.abspath(right)
    )


def _read_marker_export_id(directory: Path) -> str | None:
    marker = directory / EXPORT_MARKER_NAME
    if not os.path.lexists(marker) or marker.is_symlink() or not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    export_id = payload.get("export_id")
    return export_id if isinstance(export_id, str) and export_id else None


class RefreshStartupReconciler:
    """Reconcile interrupted refresh journals before normal startup work."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        repository: RefreshJournalRepository | None = None,
        servers_data_dir: str | os.PathLike[str] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._layout = layout
        self._repository = repository or RefreshJournalRepository(layout)
        self._servers_root = _resolved_root(
            servers_data_dir or AppSettings().servers_data_dir
        )
        self._now = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(self) -> RefreshRecoverySummary:
        return await self._reconcile_async()

    def reconcile_sync(self) -> RefreshRecoverySummary:
        return asyncio.run(self._reconcile_async())

    async def _reconcile_async(self) -> RefreshRecoverySummary:
        now = self._now or datetime.now(UTC)
        errors: list[str] = []

        swaps, changed_swaps = self._recover_swap_journals(errors)
        records = await self._repository.list_incomplete()
        transitioned = await self._advance_refresh_phases(records, swaps, errors)
        records = await self._repository.list_incomplete()
        retained = await self._repository.list_retained_previous_trees()
        removed = self._remove_unfinalized_staging(records, retained, errors)
        pruned = await self._prune_previous_trees(now, errors)

        summary = RefreshRecoverySummary(
            recovered_swaps=tuple(sorted(changed_swaps)),
            transitioned_journals=tuple(sorted(transitioned)),
            removed_staging=tuple(sorted(removed)),
            pruned_previous_trees=tuple(sorted(pruned)),
            errors=tuple(errors),
        )
        if summary.changed or summary.errors:
            logger.warning("Refresh startup recovery: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Path safety (M-4)
    # ------------------------------------------------------------------

    def validate_swap_path(
        self, server_id: str, raw_path: str | os.PathLike[str], *, field: str
    ) -> Path:
        """Return a path only when it is safely owned by ``server_id``.

        Rejects relative paths, paths outside ``servers_data_dir``, paths whose
        first component does not belong to the server, and paths that traverse
        a symlink. Raises :class:`ValidationError` before any caller can rename
        or remove the target.
        """
        segment = validate_server_segment(server_id)
        try:
            raw = os.fspath(raw_path)
        except TypeError as exc:
            raise ValidationError(f"{field} must be a filesystem path", field=field) from exc
        if not isinstance(raw, str) or not raw:
            raise ValidationError(f"{field} must be a non-empty path", field=field)
        if not os.path.isabs(raw):
            raise ValidationError(f"{field} must be an absolute path", field=field)
        lexical = Path(os.path.abspath(raw))
        try:
            relative = lexical.relative_to(self._servers_root)
        except ValueError as exc:
            raise ValidationError(
                f"{field} must be strictly below servers_data_dir",
                field=field,
                details={"path": str(lexical)[:256]},
            ) from exc
        if not relative.parts or not _server_owned_component(relative.parts[0], segment):
            raise ValidationError(
                f"{field} does not belong to server '{segment}'",
                field=field,
                details={"path": str(lexical)[:256]},
            )
        if lexical.is_symlink():
            raise ValidationError(f"{field} must not be a symlink", field=field)
        real = Path(os.path.realpath(lexical))
        if real != lexical:
            raise ValidationError(
                f"{field} must not traverse a symlink", field=field
            )
        try:
            real.relative_to(self._servers_root)
        except ValueError as exc:
            raise ValidationError(
                f"{field} resolves outside servers_data_dir", field=field
            ) from exc
        return lexical

    # ------------------------------------------------------------------
    # Swap journals
    # ------------------------------------------------------------------

    def _recover_swap_journals(
        self, errors: list[str]
    ) -> tuple[dict[str, SwapRecoveryResult], set[str]]:
        recovered: dict[str, SwapRecoveryResult] = {}
        changed: set[str] = set()
        journal_root = self._layout.journal
        try:
            if journal_root.is_symlink() or not journal_root.is_dir():
                return recovered, changed
            entries = sorted(journal_root.iterdir())
        except OSError as exc:
            errors.append(f"journal root unreadable: {exc}")
            return recovered, changed

        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            try:
                server_id = validate_server_segment(entry.name)
            except Exception:
                logger.warning("Ignoring unexpected journal directory %s", entry.name)
                continue
            swap_path = entry / "swap.json"
            if not os.path.lexists(swap_path):
                continue
            if swap_path.is_symlink():
                errors.append(f"{server_id}: swap journal is a symlink")
                continue
            try:
                journal = DirectorySwapJournal(swap_path)
                record = journal.read()
                if record is None:
                    continue
                if record.server_id != server_id:
                    raise ValidationError(
                        "swap journal server_id does not match its directory",
                        field="journal_path",
                    )
                for field in ("live_path", "staging_path", "previous_path"):
                    self.validate_swap_path(
                        server_id, getattr(record, field), field=field
                    )
                result = recover_interrupted_swap(journal)
            except Exception as exc:
                logger.exception("Swap recovery failed for server %s", server_id)
                errors.append(f"{server_id}: swap recovery failed: {exc}")
                continue
            if result.record is not None:
                recovered[server_id] = result
                if (
                    result.status in ("completed", "rolled_back")
                    and record.phase
                    not in (PHASE_SWAP_COMPLETED, PHASE_SWAP_ROLLED_BACK)
                ):
                    changed.add(server_id)
        return recovered, changed

    async def _advance_refresh_phases(
        self,
        records: list[RefreshJournalRecord],
        swaps: dict[str, SwapRecoveryResult],
        errors: list[str],
    ) -> list[str]:
        transitioned: list[str] = []
        for record in records:
            if record.phase not in ("QUIESCED", "STAGING", "SWAPPING"):
                continue
            result = swaps.get(record.server_id)
            if result is None or result.record is None:
                continue
            swap = result.record
            if not _same_declared_path(record.live_path, swap.live_path) or not (
                _same_declared_path(record.staging_path, swap.staging_path)
            ):
                continue
            if result.status not in ("completed", "rolled_back"):
                continue
            phase = "SWAP_COMPLETED" if result.status == "completed" else "SWAP_ROLLED_BACK"
            try:
                await self._repository.transition(
                    record.journal_id,
                    fencing_token=record.fencing_token,
                    phase=phase,
                    error=(
                        None
                        if result.status == "completed"
                        else (swap.error or "swap rolled back")
                    ),
                    used_exchange=swap.used_exchange,
                    export_id=swap.export_id or None,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to record swap recovery for journal %s", record.journal_id
                )
                errors.append(f"{record.journal_id}: transition failed: {exc}")
                continue
            transitioned.append(record.journal_id)
        return transitioned

    # ------------------------------------------------------------------
    # Staging and previous-tree cleanup
    # ------------------------------------------------------------------

    def _protected_staging(
        self,
        records: list[RefreshJournalRecord],
        retained: list[RefreshJournalRecord],
    ) -> set[str]:
        protected: set[str] = set()
        for record in [*records, *retained]:
            try:
                staging = self.validate_swap_path(
                    record.server_id, record.staging_path, field="staging_path"
                )
            except ValidationError:
                continue
            if (record.previous_tree_retained and record.used_exchange) or (
                not record.terminal
                and (record.used_exchange or self._live_marker_matches(record))
            ):
                protected.add(os.path.realpath(staging))
        return protected

    def _live_marker_matches(self, record: RefreshJournalRecord) -> bool:
        if not record.export_id:
            return False
        try:
            live = self.validate_swap_path(
                record.server_id, record.live_path, field="live_path"
            )
        except ValidationError:
            return False
        return _read_marker_export_id(live) == record.export_id

    def _remove_unfinalized_staging(
        self,
        records: list[RefreshJournalRecord],
        retained: list[RefreshJournalRecord],
        errors: list[str],
    ) -> list[str]:
        removed: list[str] = []
        try:
            if self._servers_root.is_symlink() or not self._servers_root.is_dir():
                return removed
            entries = sorted(self._servers_root.iterdir())
        except OSError as exc:
            errors.append(f"servers_data_dir unreadable: {exc}")
            return removed
        protected = self._protected_staging(records, retained)

        for entry in entries:
            name = entry.name
            if not name.endswith(STAGING_SUFFIX):
                continue
            if entry.is_symlink() or not entry.is_dir():
                continue
            server_id = name[: -len(STAGING_SUFFIX)]
            try:
                validate_server_segment(server_id)
            except Exception:
                continue
            try:
                staging = self.validate_swap_path(
                    server_id, entry, field="staging_path"
                )
            except ValidationError as exc:
                errors.append(f"unsafe staging directory {entry}: {exc}")
                continue
            if os.path.realpath(staging) in protected:
                continue
            if os.path.lexists(staging / EXPORT_MARKER_NAME):
                continue
            try:
                shutil.rmtree(staging)
            except OSError as exc:
                logger.exception("Failed to remove unfinalized staging %s", staging)
                errors.append(f"failed to remove staging {staging}: {exc}")
                continue
            removed.append(str(staging))
        return removed

    async def _prune_previous_trees(
        self, now: datetime, errors: list[str]
    ) -> list[str]:
        pruned: list[str] = []
        try:
            expired = await self._repository.list_expired_previous_trees(now)
        except Exception as exc:
            logger.exception("Failed to list expired previous trees")
            errors.append(f"expired previous-tree query failed: {exc}")
            return pruned

        for record in expired:
            candidate = record.staging_path if record.used_exchange else record.previous_path
            if not candidate:
                await self._mark_cleaned(record, errors)
                continue
            try:
                path = self.validate_swap_path(
                    record.server_id, candidate, field="previous_path"
                )
            except ValidationError as exc:
                errors.append(f"{record.journal_id}: unsafe previous_path: {exc}")
                continue
            if os.path.lexists(path):
                if path.is_symlink() or not path.is_dir():
                    errors.append(
                        f"{record.journal_id}: previous tree is not a plain directory"
                    )
                    continue
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    logger.exception("Failed to prune previous tree %s", path)
                    errors.append(f"failed to prune previous tree {path}: {exc}")
                    continue
                pruned.append(str(path))
            await self._mark_cleaned(record, errors)
        return pruned

    async def _mark_cleaned(
        self, record: RefreshJournalRecord, errors: list[str]
    ) -> None:
        try:
            await self._repository.mark_previous_tree_cleaned(record.journal_id)
        except Exception as exc:
            logger.exception("Failed to mark previous tree cleaned for %s", record.journal_id)
            errors.append(f"{record.journal_id}: mark cleaned failed: {exc}")


__all__ = [
    "EXPORT_MARKER_NAME",
    "RefreshRecoverySummary",
    "RefreshStartupReconciler",
]
