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
from app.modules.versioning.application.repo_lease import RepoLeaseManager
from app.modules.versioning.infrastructure.class_c_snapshot import (
    ClassCSnapshotService,
)
from app.modules.versioning.infrastructure.directory_swap import (
    PHASE_SWAP_COMPLETED,
    PHASE_SWAP_ROLLED_BACK,
    DirectorySwapJournal,
    SwapRecoveryResult,
    recover_interrupted_swap,
)
from app.modules.versioning.infrastructure.refresh_journal import (
    TERMINAL_PHASES,
    RefreshJournalRecord,
    RefreshJournalRepository,
)

logger = logging.getLogger(__name__)

EXPORT_MARKER_NAME = ".onx-complete.json"
STAGING_SUFFIX = ".staging"

# Phases that can be failed clean: the live tree was never replaced (or the
# swap itself rolled back), so only the orphaned journal needs closing.
_FAILED_CLEAN_PHASES = frozenset(
    {"QUIESCED", "BACKED_UP", "STAGING", "SWAP_ROLLED_BACK"}
)
# Phases where the new tree may be live or a rollback may be half-applied.
# They are never auto-failed: an operator must roll back or confirm first.
_ROLLBACK_REQUIRED_PHASES = frozenset(
    {
        "CARRIED",
        "SWAPPING",
        "SWAP_COMPLETED",
        "STARTING",
        "HEALTH_CHECK",
        "VERIFYING_HEALTH",
        "ROLLING_BACK",
    }
)
_PRUNE_SAFE_PHASES = frozenset({"COMPLETED", "UPGRADE_CONFIRMED"})


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


def _strip_swap_suffixes(component: str) -> str:
    if component.startswith(".") and f"{STAGING_SUFFIX}_" in component:
        return component[1 : component.index(f"{STAGING_SUFFIX}_")]
    for marker in (STAGING_SUFFIX, ".prev"):
        if component.endswith(marker):
            return component[: -len(marker)]
        marker_dot = f"{marker}."
        if marker_dot in component:
            return component[: component.index(marker_dot)]
    return component


def _is_server_id_dir_match(base_name: str, server_id: str) -> bool:
    """Return True when ``base_name`` represents ``server_id`` (full ID or ONX short-UUID dir)."""
    if base_name == server_id:
        return True
    hex_id = server_id.replace("-", "").lower()
    if len(hex_id) >= 8 and all(ch in "0123456789abcdef" for ch in hex_id):
        if base_name.replace("-", "").lower() == hex_id:
            return True
        parts = base_name.split("-")
        if (
            len(parts) > 1
            and len(parts[-1]) == 8
            and all(ch in "0123456789abcdef" for ch in parts[-1].lower())
            and parts[-1].lower() == hex_id[:8]
        ):
            return True
    return False


def _owned_component_for_base(component: str, base_name: str, *, field: str = "") -> bool:
    is_live = component == base_name
    is_staging = (
        component == f"{base_name}{STAGING_SUFFIX}"
        or component.startswith(f"{base_name}{STAGING_SUFFIX}.")
        or component.startswith(f".{base_name}{STAGING_SUFFIX}_")
    )
    is_prev = component == f"{base_name}.prev" or component.startswith(f"{base_name}.prev.")
    if field in ("live_path", "live_dir"):
        return is_live
    if field == "staging_path":
        return is_staging
    if field == "previous_path":
        # Note: RENAME_EXCHANGE leaves the previous tree at ``staging_path`` and
        # callers pass it with ``field="previous_path"``.
        return is_prev or is_staging
    return is_live or is_staging or is_prev


def _server_owned_component(component: str, server_id: str) -> bool:
    if _owned_component_for_base(component, server_id):
        return True
    base_name = _strip_swap_suffixes(component)
    return _is_server_id_dir_match(base_name, server_id) and _owned_component_for_base(
        component, base_name
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
        live_root: str | os.PathLike[str] | None = None,
        repo_lease: RepoLeaseManager | None = None,
        now: datetime | None = None,
    ) -> None:
        self._layout = layout
        self._repository = repository or RefreshJournalRepository(layout)
        self._servers_root = _resolved_root(
            servers_data_dir or AppSettings().servers_data_dir
        )
        self._live_root = (
            Path(os.path.abspath(os.fspath(live_root))) if live_root is not None else None
        )
        self._repo_lease = repo_lease
        self._now = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(self) -> RefreshRecoverySummary:
        return await self._reconcile_async()

    def reconcile_sync(self) -> RefreshRecoverySummary:
        return asyncio.run(self._reconcile_async())

    def _reconcile_class_c_vault(self, errors: list[str]) -> None:
        """Remove orphan Class-C dirs and mark missing active ledger rows."""
        service = ClassCSnapshotService(
            self._layout,
            session_factory=getattr(self._repository, "_session_factory", None),
            sync_session_factory=getattr(
                self._repository, "_sync_session_factory", None
            ),
        )
        try:
            summary = service.reconcile_snapshots()
        except Exception as exc:  # noqa: BLE001 - startup reports, never crashes
            errors.append(f"class-c: {exc}")
            logger.warning("Class-C startup reconciliation failed: %s", exc)
            return
        finally:
            service.close()
        if summary.removed_directories or summary.marked_missing:
            logger.warning("Class-C startup reconciliation: %s", summary)

    async def _reconcile_data_templates(self, errors: list[str]) -> None:
        try:
            from app.modules.versioning.infrastructure.data_templates import (
                reconcile_data_templates_and_save_off_async,
            )

            layout = self._layout
            factory = getattr(self._repository, "_session_factory", None)
            if factory is not None:
                async with factory() as session:
                    await reconcile_data_templates_and_save_off_async(
                        layout, db_session=session
                    )
            else:
                await reconcile_data_templates_and_save_off_async(layout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"data-templates: {exc}")
            logger.warning("Data template startup reconciliation failed: %s", exc)

    async def _reconcile_async(self) -> RefreshRecoverySummary:
        now = self._now or datetime.now(UTC)
        errors: list[str] = []

        swaps, changed_swaps = self._recover_swap_journals(errors)
        await self._reconcile_disk_only_journals(errors)
        records = await self._repository.list_incomplete()
        transitioned = await self._advance_refresh_phases(records, swaps, errors)
        records = await self._repository.list_incomplete()
        retained = await self._repository.list_retained_previous_trees()
        removed = self._remove_unfinalized_staging(records, retained, errors)
        pruned = await self._prune_previous_trees(now, errors)
        self._reconcile_class_c_vault(errors)
        await self._reconcile_data_templates(errors)

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
        self,
        server_id: str,
        raw_path: str | os.PathLike[str],
        *,
        field: str,
        live_root: str | os.PathLike[str] | None = None,
    ) -> Path:
        """Return a path only when it is safely owned by ``server_id``.

        Rejects relative paths, paths outside ``servers_data_dir``, paths that
        do not belong to ``server_id`` (or its resolved ``live_root`` sibling
        ``.staging`` / ``.prev`` names), and paths that traverse a symlink.
        Raises :class:`ValidationError` before any caller can rename or remove
        the target.
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

        effective_live_root: Path | None = self._live_root
        authoritative_from_host = self._live_root is not None
        if effective_live_root is None and live_root is not None:
            try:
                raw_lr = os.fspath(live_root)
            except TypeError:
                raw_lr = ""
            if isinstance(raw_lr, str) and raw_lr and os.path.isabs(raw_lr):
                effective_live_root = Path(os.path.abspath(raw_lr))

        if effective_live_root is not None:
            try:
                lr_rel = effective_live_root.relative_to(self._servers_root)
            except ValueError as exc:
                raise ValidationError(
                    f"{field} does not belong to server '{segment}'",
                    field=field,
                    details={"path": str(lexical)[:256]},
                ) from exc
            if (
                not lr_rel.parts
                or effective_live_root.is_symlink()
                or Path(os.path.realpath(effective_live_root)) != effective_live_root
            ):
                raise ValidationError(
                    f"{field} does not belong to server '{segment}'",
                    field=field,
                    details={"path": str(lexical)[:256]},
                )
            if not authoritative_from_host and not _is_server_id_dir_match(
                effective_live_root.name, segment
            ):
                raise ValidationError(
                    f"{field} does not belong to server '{segment}'",
                    field=field,
                    details={"path": str(lexical)[:256]},
                )
            if field in ("live_path", "live_dir"):
                owned = lexical == effective_live_root
            else:
                owned = lexical.parent == effective_live_root.parent and _owned_component_for_base(
                    lexical.name, effective_live_root.name, field=field
                )
            if not owned:
                raise ValidationError(
                    f"{field} does not belong to server '{segment}'",
                    field=field,
                    details={"path": str(lexical)[:256]},
                )
        elif not relative.parts or not _server_owned_component(relative.parts[0], segment):
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
            for journal_filename in ("swap.json", "swap-rollback.json"):
                swap_path = entry / journal_filename
                if not os.path.lexists(swap_path):
                    continue
                if swap_path.is_symlink():
                    errors.append(f"{server_id}: {journal_filename} is a symlink")
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
                    if journal_filename == "swap.json":
                        for field in ("live_path", "staging_path", "previous_path"):
                            self.validate_swap_path(
                                server_id,
                                getattr(record, field),
                                field=field,
                                live_root=record.live_path,
                            )
                    result = recover_interrupted_swap(journal)
                except Exception as exc:
                    logger.exception(
                        "Swap recovery failed for server %s (%s)", server_id, journal_filename
                    )
                    errors.append(
                        f"{server_id}: swap recovery failed ({journal_filename}): {exc}"
                    )
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

    async def _reconcile_disk_only_journals(self, errors: list[str]) -> None:
        """Re-create DB rows for active journals that exist only on disk.

        The JSON mirror is fsynced before the first mutation, so a crash that
        loses the DB row must never silently orphan the journal: an unblocked
        ``StartServerCommand`` would then boot a half-refreshed tree.
        """
        try:
            disk_records = await asyncio.to_thread(self._repository.iter_disk_journals)
        except Exception as exc:
            logger.exception("Failed to enumerate on-disk refresh journals")
            errors.append(f"on-disk journal scan failed: {exc}")
            return
        for disk in disk_records:
            if disk.phase in TERMINAL_PHASES:
                continue
            try:
                existing = await self._repository.get(disk.journal_id)
            except Exception as exc:
                logger.exception("Failed to read refresh journal %s", disk.journal_id)
                errors.append(f"{disk.journal_id}: lookup failed: {exc}")
                continue
            if existing is not None:
                continue
            try:
                await self._repository.create(
                    server_id=disk.server_id,
                    fencing_token=disk.fencing_token,
                    live_path=disk.live_path,
                    staging_path=disk.staging_path,
                    previous_path=disk.previous_path or None,
                    export_id=disk.export_id or None,
                    phase=disk.phase,
                    journal_id=disk.journal_id,
                    carried_entries=disk.carried_entries,
                    previous_tree_expires_at=disk.previous_tree_expires_at,
                    previous_main_sha=disk.previous_main_sha,
                    target_main_sha=disk.target_main_sha,
                    pre_upgrade_backup_id=disk.pre_upgrade_backup_id,
                    class_c_snapshot_id=disk.class_c_snapshot_id,
                    used_exchange=disk.used_exchange,
                    retention_policy=disk.retention_policy,
                    previous_tree_retained=disk.previous_tree_retained,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to re-create disk-only refresh journal %s", disk.journal_id
                )
                errors.append(
                    f"{disk.journal_id}: disk-only journal could not be restored: {exc}"
                )

    async def _advance_refresh_phases(
        self,
        records: list[RefreshJournalRecord],
        swaps: dict[str, SwapRecoveryResult],
        errors: list[str],
    ) -> list[str]:
        transitioned: list[str] = []
        for record in records:
            if record.phase not in ("QUIESCED", "STAGING", "CARRYING", "SWAPPING"):
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

        # A crash during the complement carry happens before any swap journal
        # exists. The live tree was never replaced, but the orphaned journal
        # would otherwise wedge the one-active-journal partial unique index and
        # a later start would boot the new (incomplete) tree.
        for record in records:
            if record.phase != "CARRYING" or record.journal_id in transitioned:
                continue
            if os.path.lexists(
                self._layout.journal / record.server_id / "swap.json"
            ):
                # An unresolved swap journal needs operator reconciliation.
                continue
            await self._recover_interrupted_carrying(record, errors, transitioned)

        # Every remaining non-terminal phase gets an explicit disposition. A
        # phase left non-terminal without a planned action would wedge the
        # server forever (B-7).
        for record in records:
            if record.journal_id in transitioned:
                continue
            if record.phase in _FAILED_CLEAN_PHASES:
                await self._fail_clean_if_live_intact(record, errors, transitioned)
                continue
            if record.phase in _ROLLBACK_REQUIRED_PHASES:
                try:
                    await self._repository.transition(
                        record.journal_id,
                        fencing_token=record.fencing_token,
                        phase="ROLLBACK_REQUIRED",
                        error=(
                            f"startup recovery found phase {record.phase}; "
                            "roll back or confirm before starting the server"
                        ),
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to mark journal %s as ROLLBACK_REQUIRED",
                        record.journal_id,
                    )
                    errors.append(f"{record.journal_id}: transition failed: {exc}")
                    continue
                transitioned.append(record.journal_id)
        return transitioned

    async def _recover_interrupted_carrying(
        self,
        record: RefreshJournalRecord,
        errors: list[str],
        transitioned: list[str],
    ) -> None:
        """Restore the journaled carry plan before marking CARRYING clean.

        The carry list is persisted before the first rename, so recovery can
        always return a partially carried tree to live. If any entry cannot be
        restored, the journal stays unresolved as ``ROLLBACK_REQUIRED``.
        """
        from app.modules.versioning.application.refresh_orchestrator import (
            assert_carried_entries_present,
            restore_carried_entries,
        )

        try:
            live = self.validate_swap_path(
                record.server_id,
                record.live_path,
                field="live_path",
                live_root=record.live_path,
            )
        except ValidationError as exc:
            errors.append(f"{record.journal_id}: unsafe live_path: {exc}")
            return
        if not os.path.lexists(live) or live.is_symlink() or not live.is_dir():
            errors.append(
                f"{record.journal_id}: interrupted CARRYING has no swap journal "
                "and the live tree is unavailable"
            )
            return

        carried = tuple(record.carried_entries)
        try:
            staging = self.validate_swap_path(
                record.server_id,
                record.staging_path,
                field="staging_path",
                live_root=record.live_path,
            )
        except ValidationError as exc:
            errors.append(f"{record.journal_id}: unsafe staging_path: {exc}")
            return

        if carried and os.path.lexists(staging):
            if staging.is_symlink() or not staging.is_dir():
                errors.append(
                    f"{record.journal_id}: staging tree is not a plain directory"
                )
                return
            try:
                await asyncio.to_thread(
                    restore_carried_entries, live, staging, carried
                )
            except Exception as exc:
                logger.exception(
                    "Failed to restore carried entries for journal %s",
                    record.journal_id,
                )
                errors.append(
                    f"{record.journal_id}: carried entries could not be restored: {exc}"
                )
                await self._mark_rollback_required(record, errors, transitioned)
                return
        if carried:
            try:
                await asyncio.to_thread(
                    assert_carried_entries_present, live, carried
                )
            except Exception as exc:
                errors.append(
                    f"{record.journal_id}: carried entries are missing from live: {exc}"
                )
                await self._mark_rollback_required(record, errors, transitioned)
                return

        try:
            await self._repository.transition(
                record.journal_id,
                fencing_token=record.fencing_token,
                phase="FAILED_CLEAN",
                error=(
                    "refresh interrupted during complement carry before the "
                    "swap; live tree left intact"
                ),
            )
        except Exception as exc:
            logger.exception(
                "Failed to mark interrupted CARRYING journal %s as FAILED_CLEAN",
                record.journal_id,
            )
            errors.append(f"{record.journal_id}: transition failed: {exc}")
            return
        transitioned.append(record.journal_id)

    async def _fail_clean_if_live_intact(
        self,
        record: RefreshJournalRecord,
        errors: list[str],
        transitioned: list[str],
    ) -> None:
        try:
            live = self.validate_swap_path(
                record.server_id,
                record.live_path,
                field="live_path",
                live_root=record.live_path,
            )
        except ValidationError as exc:
            errors.append(f"{record.journal_id}: unsafe live_path: {exc}")
            return
        if not os.path.lexists(live) or live.is_symlink() or not live.is_dir():
            errors.append(
                f"{record.journal_id}: phase {record.phase} has no intact live tree"
            )
            await self._mark_rollback_required(record, errors, transitioned)
            return
        try:
            await self._repository.transition(
                record.journal_id,
                fencing_token=record.fencing_token,
                phase="FAILED_CLEAN",
                error=(
                    f"startup recovery closed interrupted {record.phase} before "
                    "the live tree was replaced"
                ),
            )
        except Exception as exc:
            logger.exception(
                "Failed to mark journal %s as FAILED_CLEAN", record.journal_id
            )
            errors.append(f"{record.journal_id}: transition failed: {exc}")
            return
        transitioned.append(record.journal_id)

    async def _mark_rollback_required(
        self,
        record: RefreshJournalRecord,
        errors: list[str],
        transitioned: list[str],
    ) -> None:
        try:
            await self._repository.transition(
                record.journal_id,
                fencing_token=record.fencing_token,
                phase="ROLLBACK_REQUIRED",
                error=(
                    f"startup recovery could not safely clean phase {record.phase}; "
                    "operator rollback required"
                ),
            )
        except Exception as exc:
            logger.exception(
                "Failed to mark journal %s as ROLLBACK_REQUIRED", record.journal_id
            )
            errors.append(f"{record.journal_id}: transition failed: {exc}")
            return
        transitioned.append(record.journal_id)

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
                    record.server_id,
                    record.staging_path,
                    field="staging_path",
                    live_root=record.live_path,
                )
            except ValidationError:
                continue
            # Any non-terminal journal owns its staging tree: it may hold the
            # journaled carry plan or the only copy of the old live tree after
            # an exchange swap. Never sweep it out from under recovery.
            if (
                not record.terminal
                or (record.previous_tree_retained and record.used_exchange)
                or self._live_marker_matches(record)
            ):
                protected.add(os.path.realpath(staging))
        return protected

    def _live_marker_matches(self, record: RefreshJournalRecord) -> bool:
        if not record.export_id:
            return False
        try:
            live = self.validate_swap_path(
                record.server_id,
                record.live_path,
                field="live_path",
                live_root=record.live_path,
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

        known_export_ids: set[str] = {
            record.export_id for record in [*records, *retained] if record.export_id
        }
        try:
            known_export_ids.update(
                disk.export_id for disk in self._repository.iter_disk_journals()
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unable to read disk journals for marker validation: %s", exc)
        known_export_ids.discard("")

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
            marker_export_id = _read_marker_export_id(staging)
            if marker_export_id is not None and marker_export_id in known_export_ids:
                # A completed export owned by a known journal: never delete it
                # on marker presence alone, only when its id is recognized.
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
            try:
                fresh = await self._repository.get(record.journal_id)
            except Exception as exc:
                logger.exception("Failed to re-read refresh journal %s", record.journal_id)
                errors.append(f"{record.journal_id}: re-read failed: {exc}")
                continue
            if fresh is None:
                errors.append(
                    f"{record.journal_id}: journal vanished before previous-tree prune"
                )
                continue
            if fresh.phase not in _PRUNE_SAFE_PHASES:
                # Never race an active refresh/rollback that still owns the
                # retained tree.
                logger.warning(
                    "Skipping previous-tree prune for %s: phase is %s",
                    fresh.journal_id,
                    fresh.phase,
                )
                continue
            if self._repo_lease is not None:
                try:
                    # A newer lease acquisition bumps the fencing token, which
                    # proves another writer may already own this server.
                    await self._repo_lease.assert_fencing_token(
                        fresh.server_id, fresh.fencing_token
                    )
                except Exception as exc:
                    logger.warning(
                        "Skipping previous-tree prune for %s: %s",
                        fresh.journal_id,
                        exc,
                    )
                    errors.append(
                        f"{fresh.journal_id}: previous-tree prune skipped: {exc}"
                    )
                    continue
            record = fresh
            candidate = record.staging_path if record.used_exchange else record.previous_path
            if not candidate:
                await self._mark_cleaned(record, errors)
                continue
            try:
                path = self.validate_swap_path(
                    record.server_id,
                    candidate,
                    field="previous_path",
                    live_root=record.live_path,
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
