"""Two-tier refresh journal: fsynced JSON mirror plus DB authority (P2-5c).

The ``refresh_journals`` table is the authoritative record: it enforces one
active row per server and its ``fencing_token`` column provides compare-and-swap
transitions. Every write is mirrored to
``<host_state>/journal/<server_id>/refresh.json`` so a crash leaves a durable
high-level record next to the swap journal.

Transitions use ``UPDATE ... WHERE journal_id = :jid AND fencing_token = :token
AND terminal = false``. A stale token never overwrites a newer writer and fails
closed with :class:`FencingTokenMismatchError` (HTTP 409).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import (
    ConflictError,
    FencingTokenMismatchError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.models import RefreshJournalModel

logger = logging.getLogger(__name__)

TERMINAL_PHASES = frozenset(
    {"COMPLETED", "ROLLED_BACK", "FAILED_CLEAN", "UPGRADE_CONFIRMED"}
)
ACTIVE_PHASES = frozenset(
    {
        "QUIESCED",
        "STAGING",
        "SWAPPING",
        "STARTING",
        "HEALTH_CHECK",
        "ROLLING_BACK",
        "SWAP_ROLLED_BACK",
        "SWAP_COMPLETED",
    }
)
ALL_PHASES = TERMINAL_PHASES | ACTIVE_PHASES

JOURNAL_FILENAME = "refresh.json"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _to_utc(value)
    if isinstance(value, str):
        raw = value.replace("Z", "+00:00")
        try:
            return _to_utc(datetime.fromisoformat(raw))
        except ValueError as exc:
            raise ValidationError(
                "refresh journal has an invalid timestamp",
                field="refresh_journal",
            ) from exc
    raise ValidationError("refresh journal has an invalid timestamp", field="refresh_journal")


def _absolute_path(raw: str | os.PathLike[str] | None, field: str) -> str:
    if raw is None:
        return ""
    try:
        text = os.fspath(raw)
    except TypeError as exc:
        raise ValidationError(f"{field} must be a filesystem path", field=field) from exc
    if not isinstance(text, str) or not text:
        raise ValidationError(f"{field} must be a non-empty path", field=field)
    if not os.path.isabs(text):
        raise ValidationError(f"{field} must be an absolute path", field=field)
    return os.path.abspath(text)


def _validate_phase(phase: str) -> str:
    if phase not in ALL_PHASES:
        raise ValidationError("Unknown refresh journal phase", field="phase")
    return phase


def _normalise_carried(value: Sequence[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [value]
    return [str(item) for item in value]


@dataclass(frozen=True)
class RefreshJournalRecord:
    """High-level refresh/rollback journal shared by JSON and the DB."""

    journal_id: str
    server_id: str
    fencing_token: int
    phase: str
    live_path: str
    staging_path: str
    terminal: bool = False
    export_id: str = ""
    previous_main_sha: str = ""
    target_main_sha: str = ""
    pre_upgrade_backup_id: str = ""
    class_c_snapshot_id: str = ""
    previous_path: str = ""
    used_exchange: bool = False
    carried_entries: tuple[str, ...] = ()
    retention_policy: str = "until_health_gate"
    previous_tree_retained: bool = False
    previous_tree_expires_at: datetime | None = None
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.journal_id, str) or not self.journal_id:
            raise ValidationError("journal_id must be a non-empty string", field="journal_id")
        validate_server_segment(self.server_id)
        _validate_phase(self.phase)
        if type(self.fencing_token) is not int or self.fencing_token < 0:
            raise ValidationError(
                "fencing_token must be a non-negative integer", field="fencing_token"
            )
        expected_terminal = self.phase in TERMINAL_PHASES
        if self.terminal != expected_terminal:
            raise ValidationError(
                "terminal flag does not match phase", field="terminal"
            )
        if not isinstance(self.carried_entries, tuple):
            object.__setattr__(self, "carried_entries", tuple(self.carried_entries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": self.journal_id,
            "server_id": self.server_id,
            "export_id": self.export_id or None,
            "fencing_token": self.fencing_token,
            "phase": self.phase,
            "terminal": self.terminal,
            "previous_main_sha": self.previous_main_sha or None,
            "target_main_sha": self.target_main_sha or None,
            "pre_upgrade_backup_id": self.pre_upgrade_backup_id or None,
            "class_c_snapshot_id": self.class_c_snapshot_id or None,
            "live_path": self.live_path,
            "staging_path": self.staging_path,
            "previous_path": self.previous_path or None,
            "used_exchange": self.used_exchange,
            "carried_entries": list(self.carried_entries),
            "retention_policy": self.retention_policy,
            "previous_tree_retained": self.previous_tree_retained,
            "previous_tree_expires_at": (
                self.previous_tree_expires_at.isoformat()
                if self.previous_tree_expires_at is not None
                else None
            ),
            "error": self.error or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RefreshJournalRecord:
        if not isinstance(data, dict):
            raise ValidationError("refresh journal must be a JSON object", field="refresh_journal")
        carried = data.get("carried_entries", [])
        if isinstance(carried, str):
            try:
                carried = json.loads(carried)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    "refresh journal carried_entries is invalid JSON",
                    field="refresh_journal",
                ) from exc
        if not isinstance(carried, (list, tuple)):
            raise ValidationError(
                "refresh journal carried_entries must be a list",
                field="refresh_journal",
            )
        try:
            return cls(
                journal_id=str(data["journal_id"]),
                server_id=str(data["server_id"]),
                fencing_token=int(data["fencing_token"]),
                phase=str(data["phase"]),
                live_path=str(data.get("live_path", "")),
                staging_path=str(data.get("staging_path", "")),
                terminal=bool(data.get("terminal", data.get("phase") in TERMINAL_PHASES)),
                export_id=str(data.get("export_id") or ""),
                previous_main_sha=str(data.get("previous_main_sha") or ""),
                target_main_sha=str(data.get("target_main_sha") or ""),
                pre_upgrade_backup_id=str(data.get("pre_upgrade_backup_id") or ""),
                class_c_snapshot_id=str(data.get("class_c_snapshot_id") or ""),
                previous_path=str(data.get("previous_path") or ""),
                used_exchange=bool(data.get("used_exchange", False)),
                carried_entries=tuple(str(item) for item in carried),
                retention_policy=str(data.get("retention_policy") or "until_health_gate"),
                previous_tree_retained=bool(data.get("previous_tree_retained", False)),
                previous_tree_expires_at=_parse_datetime(data.get("previous_tree_expires_at")),
                error=str(data.get("error") or ""),
                created_at=_parse_datetime(data.get("created_at")),
                updated_at=_parse_datetime(data.get("updated_at")),
            )
        except KeyError as exc:
            raise ValidationError(
                "refresh journal is missing required fields",
                field="refresh_journal",
                details={"missing": [str(exc.args[0])]},
            ) from exc


def _values_from_model(model: RefreshJournalModel) -> dict[str, Any]:
    return {
        column.name: getattr(model, column.name)
        for column in RefreshJournalModel.__table__.columns
    }


def _record_from_values(values: dict[str, Any]) -> RefreshJournalRecord:
    carried_raw = values.get("carried_entries_json") or "[]"
    try:
        carried = json.loads(carried_raw) if isinstance(carried_raw, str) else carried_raw
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "refresh journal carried_entries_json is invalid", field="refresh_journal"
        ) from exc
    phase = str(values["phase"])
    return RefreshJournalRecord(
        journal_id=str(values["journal_id"]),
        server_id=str(values["server_id"]),
        fencing_token=int(values["fencing_token"]),
        phase=phase,
        terminal=phase in TERMINAL_PHASES,
        export_id=str(values.get("export_id") or ""),
        previous_main_sha=str(values.get("previous_main_sha") or ""),
        target_main_sha=str(values.get("target_main_sha") or ""),
        pre_upgrade_backup_id=str(values.get("pre_upgrade_backup_id") or ""),
        class_c_snapshot_id=str(values.get("class_c_snapshot_id") or ""),
        live_path=str(values.get("live_path") or ""),
        staging_path=str(values.get("staging_path") or ""),
        previous_path=str(values.get("previous_path") or ""),
        used_exchange=bool(values.get("used_exchange", False)),
        carried_entries=tuple(str(item) for item in (carried or ())),
        retention_policy=str(values.get("retention_policy") or "until_health_gate"),
        previous_tree_retained=bool(values.get("previous_tree_retained", False)),
        previous_tree_expires_at=_to_utc(values.get("previous_tree_expires_at")),
        error=str(values.get("error") or ""),
        created_at=_to_utc(values.get("created_at")),
        updated_at=_to_utc(values.get("updated_at")),
    )


class RefreshJournalRepository:
    """Persist refresh journals in the DB and mirror them to fsynced JSON."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._layout = layout
        self._session_factory = session_factory
        self._sync_session_factory = sync_session_factory
        self._owned_engine: Engine | None = None

    # ------------------------------------------------------------------
    # Session factories
    # ------------------------------------------------------------------

    def _get_async_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        from app.core.persistence.db import database

        return database.session_factory

    def _get_sync_factory(self) -> sessionmaker[Session]:
        if self._sync_session_factory is not None:
            return self._sync_session_factory
        url = None
        if self._session_factory is not None:
            bind = self._session_factory.kw.get("bind")
            if bind is not None:
                url = bind.url
        if url is None:
            from app.core.persistence.db import database

            url = database.engine.url
        if url.get_backend_name() != "sqlite":
            raise RuntimeError(
                "RefreshJournalRepository requires sync_session_factory for non-SQLite backends"
            )
        if (url.database or "") == ":memory:":
            raise RuntimeError(
                "RefreshJournalRepository cannot derive a sync SQLite engine for :memory:"
            )
        self._owned_engine = create_engine(
            url.set(drivername="sqlite"),
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        self._sync_session_factory = sessionmaker(bind=self._owned_engine, expire_on_commit=False)
        return self._sync_session_factory

    def close(self) -> None:
        if self._owned_engine is not None:
            self._owned_engine.dispose()
            self._owned_engine = None

    # ------------------------------------------------------------------
    # JSON mirror
    # ------------------------------------------------------------------

    def journal_path(self, server_id: str) -> Path:
        segment = validate_server_segment(server_id)
        return self._layout.journal / segment / JOURNAL_FILENAME

    def _write_json(self, record: RefreshJournalRecord) -> None:
        path = self.journal_path(record.server_id)
        parent = path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise ValidationError(
                f"Unable to create refresh journal directory: {exc}",
                field="refresh_journal",
            ) from exc
        if parent.is_symlink():
            raise ValidationError(
                "Refresh journal directory must not be a symlink",
                field="refresh_journal",
            )
        payload = (
            json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        atomic_write_private(path, payload, mode=0o600, fsync_parent=True)

    def _read_json(self, server_id: str) -> RefreshJournalRecord | None:
        path = self.journal_path(server_id)
        if path.is_symlink():
            raise ValidationError(
                "Refresh journal path must not be a symlink",
                field="refresh_journal",
            )
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValidationError(
                f"Unable to read refresh journal: {exc}",
                field="refresh_journal",
            ) from exc
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "Refresh journal is not valid JSON", field="refresh_journal"
            ) from exc
        if not isinstance(data, dict):
            raise ValidationError(
                "Refresh journal must be a JSON object", field="refresh_journal"
            )
        record = RefreshJournalRecord.from_dict(data)
        if record.server_id != validate_server_segment(server_id):
            raise ValidationError(
                "Refresh journal server_id does not match its directory",
                field="refresh_journal",
            )
        return record

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    @staticmethod
    def _create_values(
        *,
        journal_id: str,
        server_id: str,
        fencing_token: int,
        phase: str,
        live_path: str,
        staging_path: str,
        previous_path: str,
        export_id: str | None,
        previous_main_sha: str | None,
        target_main_sha: str | None,
        pre_upgrade_backup_id: str | None,
        class_c_snapshot_id: str | None,
        used_exchange: bool,
        carried_entries: Sequence[str] | None,
        retention_policy: str,
        previous_tree_retained: bool,
        previous_tree_expires_at: datetime | None,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "journal_id": journal_id,
            "server_id": server_id,
            "export_id": export_id or None,
            "fencing_token": fencing_token,
            "phase": phase,
            "terminal": False,
            "previous_main_sha": previous_main_sha or None,
            "target_main_sha": target_main_sha or None,
            "pre_upgrade_backup_id": pre_upgrade_backup_id or None,
            "class_c_snapshot_id": class_c_snapshot_id or None,
            "live_path": live_path,
            "staging_path": staging_path,
            "previous_path": previous_path or None,
            "used_exchange": used_exchange,
            "carried_entries_json": json.dumps(_normalise_carried(carried_entries)),
            "retention_policy": retention_policy,
            "previous_tree_retained": previous_tree_retained,
            "previous_tree_expires_at": previous_tree_expires_at,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

    def _prepare_create(
        self,
        *,
        server_id: str,
        fencing_token: int,
        live_path: str | os.PathLike[str],
        staging_path: str | os.PathLike[str],
        previous_path: str | os.PathLike[str] | None,
        phase: str,
        export_id: str | None,
        journal_id: str | None,
        carried_entries: Sequence[str] | None,
        previous_tree_expires_at: datetime | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        segment = validate_server_segment(server_id)
        _validate_phase(phase)
        if phase in TERMINAL_PHASES:
            raise ValidationError(
                "A refresh journal cannot be created in a terminal phase", field="phase"
            )
        if type(fencing_token) is not int or fencing_token < 0:
            raise ValidationError(
                "fencing_token must be a non-negative integer", field="fencing_token"
            )
        live = _absolute_path(live_path, "live_path")
        staging = _absolute_path(staging_path, "staging_path")
        previous = _absolute_path(previous_path, "previous_path")
        if live == staging:
            raise ValidationError(
                "live_path and staging_path must differ", field="staging_path"
            )
        jid = journal_id or uuid.uuid4().hex
        if not isinstance(jid, str) or not jid:
            raise ValidationError("journal_id must be a non-empty string", field="journal_id")
        return self._create_values(
            journal_id=jid,
            server_id=segment,
            fencing_token=fencing_token,
            phase=phase,
            live_path=live,
            staging_path=staging,
            previous_path=previous,
            export_id=export_id,
            previous_main_sha=extra.get("previous_main_sha"),
            target_main_sha=extra.get("target_main_sha"),
            pre_upgrade_backup_id=extra.get("pre_upgrade_backup_id"),
            class_c_snapshot_id=extra.get("class_c_snapshot_id"),
            used_exchange=bool(extra.get("used_exchange", False)),
            carried_entries=carried_entries,
            retention_policy=str(extra.get("retention_policy", "until_health_gate")),
            previous_tree_retained=bool(extra.get("previous_tree_retained", False)),
            previous_tree_expires_at=_to_utc(previous_tree_expires_at),
            now=_utcnow(),
        )

    @staticmethod
    def _create_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "previous_main_sha",
            "target_main_sha",
            "pre_upgrade_backup_id",
            "class_c_snapshot_id",
            "used_exchange",
            "retention_policy",
            "previous_tree_retained",
        }
        return {key: value for key, value in kwargs.items() if key in allowed}

    def create_sync(
        self,
        *,
        server_id: str,
        fencing_token: int,
        live_path: str | os.PathLike[str],
        staging_path: str | os.PathLike[str],
        previous_path: str | os.PathLike[str] | None = None,
        export_id: str | None = None,
        phase: str = "QUIESCED",
        journal_id: str | None = None,
        carried_entries: Sequence[str] | None = None,
        previous_tree_expires_at: datetime | None = None,
        **kwargs: Any,
    ) -> RefreshJournalRecord:
        values = self._prepare_create(
            server_id=server_id,
            fencing_token=fencing_token,
            live_path=live_path,
            staging_path=staging_path,
            previous_path=previous_path,
            phase=phase,
            export_id=export_id,
            journal_id=journal_id,
            carried_entries=carried_entries,
            previous_tree_expires_at=previous_tree_expires_at,
            extra=self._create_kwargs(kwargs),
        )
        factory = self._get_sync_factory()
        try:
            with factory() as session:
                session.add(RefreshJournalModel(**values))
                session.commit()
        except IntegrityError as exc:
            if "refresh_journals" not in str(exc.orig):
                raise
            raise ConflictError(
                f"An active refresh journal already exists for server '{server_id}'"
            ) from exc
        record = _record_from_values(values)
        try:
            self._write_json(record)
        except BaseException:
            try:
                with factory() as session:
                    session.execute(
                        delete(RefreshJournalModel).where(
                            RefreshJournalModel.journal_id == record.journal_id
                        )
                    )
                    session.commit()
            except Exception:
                logger.exception("Failed to compensate refresh journal create")
            raise
        return record

    async def create(
        self,
        *,
        server_id: str,
        fencing_token: int,
        live_path: str | os.PathLike[str],
        staging_path: str | os.PathLike[str],
        previous_path: str | os.PathLike[str] | None = None,
        export_id: str | None = None,
        phase: str = "QUIESCED",
        journal_id: str | None = None,
        carried_entries: Sequence[str] | None = None,
        previous_tree_expires_at: datetime | None = None,
        **kwargs: Any,
    ) -> RefreshJournalRecord:
        values = self._prepare_create(
            server_id=server_id,
            fencing_token=fencing_token,
            live_path=live_path,
            staging_path=staging_path,
            previous_path=previous_path,
            phase=phase,
            export_id=export_id,
            journal_id=journal_id,
            carried_entries=carried_entries,
            previous_tree_expires_at=previous_tree_expires_at,
            extra=self._create_kwargs(kwargs),
        )
        factory = self._get_async_factory()
        try:
            async with factory() as session:
                session.add(RefreshJournalModel(**values))
                await session.commit()
        except IntegrityError as exc:
            if "refresh_journals" not in str(exc.orig):
                raise
            raise ConflictError(
                f"An active refresh journal already exists for server '{server_id}'"
            ) from exc
        record = _record_from_values(values)
        try:
            self._write_json(record)
        except BaseException:
            try:
                async with factory() as session:
                    await session.execute(
                        delete(RefreshJournalModel).where(
                            RefreshJournalModel.journal_id == record.journal_id
                        )
                    )
                    await session.commit()
            except Exception:
                logger.exception("Failed to compensate refresh journal create")
            raise
        return record

    # ------------------------------------------------------------------
    # Transition (compare-and-swap on fencing_token)
    # ------------------------------------------------------------------

    @staticmethod
    def _transition_values(
        *,
        phase: str,
        error: str | None,
        previous_tree_retained: bool | None,
        previous_tree_expires_at: datetime | None,
        used_exchange: bool | None,
        carried_entries: Sequence[str] | None,
        export_id: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        _validate_phase(phase)
        values: dict[str, Any] = {
            "phase": phase,
            "terminal": phase in TERMINAL_PHASES,
            "updated_at": now,
        }
        if error is not None:
            values["error"] = error
        if previous_tree_retained is not None:
            values["previous_tree_retained"] = previous_tree_retained
        if previous_tree_expires_at is not None:
            values["previous_tree_expires_at"] = _to_utc(previous_tree_expires_at)
        if used_exchange is not None:
            values["used_exchange"] = used_exchange
        if carried_entries is not None:
            values["carried_entries_json"] = json.dumps(
                _normalise_carried(carried_entries)
            )
        if export_id is not None:
            values["export_id"] = export_id or None
        return values

    @staticmethod
    def _raise_mismatch(
        session_row: dict[str, Any] | None,
        fencing_token: int,
    ) -> None:
        raise FencingTokenMismatchError(
            server_id=None if session_row is None else str(session_row["server_id"]),
            expected_token=fencing_token,
            actual_token=None if session_row is None else int(session_row["fencing_token"]),
        )

    def transition_sync(
        self,
        journal_id: str,
        *,
        fencing_token: int,
        phase: str,
        error: str | None = None,
        previous_tree_retained: bool | None = None,
        previous_tree_expires_at: datetime | None = None,
        used_exchange: bool | None = None,
        carried_entries: Sequence[str] | None = None,
        export_id: str | None = None,
    ) -> RefreshJournalRecord:
        if not isinstance(journal_id, str) or not journal_id:
            raise ValidationError("journal_id must be a non-empty string", field="journal_id")
        values = self._transition_values(
            phase=phase,
            error=error,
            previous_tree_retained=previous_tree_retained,
            previous_tree_expires_at=previous_tree_expires_at,
            used_exchange=used_exchange,
            carried_entries=carried_entries,
            export_id=export_id,
            now=_utcnow(),
        )
        factory = self._get_sync_factory()
        with factory() as session:
            result = session.execute(
                update(RefreshJournalModel)
                .where(
                    RefreshJournalModel.journal_id == journal_id,
                    RefreshJournalModel.fencing_token == fencing_token,
                    RefreshJournalModel.terminal.is_(False),
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            row = session.execute(
                select(RefreshJournalModel).where(
                    RefreshJournalModel.journal_id == journal_id
                )
            ).scalar_one_or_none()
            if not result.rowcount or row is None:
                self._raise_mismatch(
                    None if row is None else _values_from_model(row), fencing_token
                )
            record = _record_from_values(_values_from_model(row))
            session.commit()
        self._write_json(record)
        return record

    async def transition(
        self,
        journal_id: str,
        *,
        fencing_token: int,
        phase: str,
        error: str | None = None,
        previous_tree_retained: bool | None = None,
        previous_tree_expires_at: datetime | None = None,
        used_exchange: bool | None = None,
        carried_entries: Sequence[str] | None = None,
        export_id: str | None = None,
    ) -> RefreshJournalRecord:
        if not isinstance(journal_id, str) or not journal_id:
            raise ValidationError("journal_id must be a non-empty string", field="journal_id")
        values = self._transition_values(
            phase=phase,
            error=error,
            previous_tree_retained=previous_tree_retained,
            previous_tree_expires_at=previous_tree_expires_at,
            used_exchange=used_exchange,
            carried_entries=carried_entries,
            export_id=export_id,
            now=_utcnow(),
        )
        factory = self._get_async_factory()
        async with factory() as session:
            result = await session.execute(
                update(RefreshJournalModel)
                .where(
                    RefreshJournalModel.journal_id == journal_id,
                    RefreshJournalModel.fencing_token == fencing_token,
                    RefreshJournalModel.terminal.is_(False),
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            row = (
                await session.execute(
                    select(RefreshJournalModel).where(
                        RefreshJournalModel.journal_id == journal_id
                    )
                )
            ).scalar_one_or_none()
            if not result.rowcount or row is None:
                self._raise_mismatch(
                    None if row is None else _values_from_model(row), fencing_token
                )
            record = _record_from_values(_values_from_model(row))
            await session.commit()
        self._write_json(record)
        return record

    # ------------------------------------------------------------------
    # Reads and previous-tree cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _select_record(session: Session, journal_id: str) -> RefreshJournalRecord | None:
        row = session.execute(
            select(RefreshJournalModel).where(RefreshJournalModel.journal_id == journal_id)
        ).scalar_one_or_none()
        return None if row is None else _record_from_values(_values_from_model(row))

    @staticmethod
    async def _aselect_record(
        session: AsyncSession, journal_id: str
    ) -> RefreshJournalRecord | None:
        row = (
            await session.execute(
                select(RefreshJournalModel).where(RefreshJournalModel.journal_id == journal_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _record_from_values(_values_from_model(row))

    def get_sync(self, journal_id: str) -> RefreshJournalRecord | None:
        factory = self._get_sync_factory()
        with factory() as session:
            return self._select_record(session, journal_id)

    async def get(self, journal_id: str) -> RefreshJournalRecord | None:
        factory = self._get_async_factory()
        async with factory() as session:
            return await self._aselect_record(session, journal_id)

    def get_active_for_server_sync(self, server_id: str) -> RefreshJournalRecord | None:
        segment = validate_server_segment(server_id)
        factory = self._get_sync_factory()
        with factory() as session:
            row = session.execute(
                select(RefreshJournalModel)
                .where(
                    RefreshJournalModel.server_id == segment,
                    RefreshJournalModel.terminal.is_(False),
                )
                .order_by(RefreshJournalModel.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        if row is not None:
            return _record_from_values(_values_from_model(row))
        return None

    async def get_active_for_server(self, server_id: str) -> RefreshJournalRecord | None:
        segment = validate_server_segment(server_id)
        factory = self._get_async_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(RefreshJournalModel)
                    .where(
                        RefreshJournalModel.server_id == segment,
                        RefreshJournalModel.terminal.is_(False),
                    )
                    .order_by(RefreshJournalModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is not None:
            return _record_from_values(_values_from_model(row))
        return None

    def list_incomplete_sync(self) -> list[RefreshJournalRecord]:
        factory = self._get_sync_factory()
        with factory() as session:
            rows = (
                session.execute(
                    select(RefreshJournalModel)
                    .where(RefreshJournalModel.terminal.is_(False))
                    .order_by(RefreshJournalModel.created_at)
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    async def list_incomplete(self) -> list[RefreshJournalRecord]:
        factory = self._get_async_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RefreshJournalModel)
                        .where(RefreshJournalModel.terminal.is_(False))
                        .order_by(RefreshJournalModel.created_at)
                    )
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    def list_retained_previous_trees_sync(self) -> list[RefreshJournalRecord]:
        factory = self._get_sync_factory()
        with factory() as session:
            rows = (
                session.execute(
                    select(RefreshJournalModel)
                    .where(RefreshJournalModel.previous_tree_retained.is_(True))
                    .order_by(RefreshJournalModel.previous_tree_expires_at)
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    async def list_retained_previous_trees(self) -> list[RefreshJournalRecord]:
        factory = self._get_async_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RefreshJournalModel)
                        .where(RefreshJournalModel.previous_tree_retained.is_(True))
                        .order_by(RefreshJournalModel.previous_tree_expires_at)
                    )
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    def list_expired_previous_trees_sync(
        self, now: datetime | None = None
    ) -> list[RefreshJournalRecord]:
        moment = _to_utc(now) or _utcnow()
        factory = self._get_sync_factory()
        with factory() as session:
            rows = (
                session.execute(
                    select(RefreshJournalModel)
                    .where(
                        RefreshJournalModel.previous_tree_retained.is_(True),
                        RefreshJournalModel.previous_tree_expires_at.is_not(None),
                        RefreshJournalModel.previous_tree_expires_at <= moment,
                    )
                    .order_by(RefreshJournalModel.previous_tree_expires_at)
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    async def list_expired_previous_trees(
        self, now: datetime | None = None
    ) -> list[RefreshJournalRecord]:
        moment = _to_utc(now) or _utcnow()
        factory = self._get_async_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RefreshJournalModel)
                        .where(
                            RefreshJournalModel.previous_tree_retained.is_(True),
                            RefreshJournalModel.previous_tree_expires_at.is_not(None),
                            RefreshJournalModel.previous_tree_expires_at <= moment,
                        )
                        .order_by(RefreshJournalModel.previous_tree_expires_at)
                    )
                )
                .scalars()
                .all()
            )
        return [_record_from_values(_values_from_model(row)) for row in rows]

    def mark_previous_tree_cleaned_sync(self, journal_id: str) -> bool:
        factory = self._get_sync_factory()
        with factory() as session:
            result = session.execute(
                update(RefreshJournalModel)
                .where(RefreshJournalModel.journal_id == journal_id)
                .values(
                    previous_tree_retained=False,
                    previous_tree_expires_at=None,
                    updated_at=_utcnow(),
                )
                .execution_options(synchronize_session=False)
            )
            record = self._select_record(session, journal_id)
            session.commit()
        if not result.rowcount or record is None:
            return False
        self._write_json(record)
        return True

    async def mark_previous_tree_cleaned(self, journal_id: str) -> bool:
        factory = self._get_async_factory()
        async with factory() as session:
            result = await session.execute(
                update(RefreshJournalModel)
                .where(RefreshJournalModel.journal_id == journal_id)
                .values(
                    previous_tree_retained=False,
                    previous_tree_expires_at=None,
                    updated_at=_utcnow(),
                )
                .execution_options(synchronize_session=False)
            )
            record = await self._aselect_record(session, journal_id)
            await session.commit()
        if not result.rowcount or record is None:
            return False
        self._write_json(record)
        return True


__all__ = [
    "ACTIVE_PHASES",
    "ALL_PHASES",
    "JOURNAL_FILENAME",
    "RefreshJournalRecord",
    "RefreshJournalRepository",
    "TERMINAL_PHASES",
]
