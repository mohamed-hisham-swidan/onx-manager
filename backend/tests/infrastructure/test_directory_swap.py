"""Journaled directory swap tests for P2-3 (OD-v8.7-2)."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.modules.versioning.infrastructure.directory_swap import (
    PHASE_PREPARED,
    PHASE_SWAP_COMPLETED,
    PHASE_SWAP_ROLLED_BACK,
    PHASE_SWAPPING_IN_STAGING,
    PHASE_SWAPPING_OUT_LIVE,
    DirectorySwapJournal,
    SwapJournalRecord,
    recover_interrupted_swap,
    rename_exchange,
    swap_directories,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode directory swap is POSIX-only",
)

SERVER_ID = "srv-directory-swap"


class RecordingJournal(DirectorySwapJournal):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.phases: list[str] = []

    def write(self, record: SwapJournalRecord) -> None:
        self.phases.append(record.phase)
        super().write(record)


def _tree(path: Path, name: str, value: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(value, encoding="utf-8")


def _latest_phase(journal: DirectorySwapJournal) -> str:
    record = journal.read()
    assert record is not None
    return record.phase


def _journal(tmp_path: Path, name: str = "swap.json") -> DirectorySwapJournal:
    return DirectorySwapJournal(tmp_path / "journal" / name)


def _record(
    live: Path,
    staging: Path,
    phase: str,
    **overrides: object,
) -> SwapJournalRecord:
    values: dict[str, object] = {
        "journal_id": "journal-1",
        "server_id": SERVER_ID,
        "phase": phase,
        "live_path": str(live),
        "staging_path": str(staging),
        "previous_path": str(live.with_name(live.name + ".prev")),
    }
    values.update(overrides)
    return SwapJournalRecord(**values)  # type: ignore[arg-type]


def test_fallback_swap_moves_staging_into_live_and_keeps_previous(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = RecordingJournal(tmp_path / "journal" / "swap.json")

    result = swap_directories(
        live,
        staging,
        journal,
        server_id=SERVER_ID,
        exchange_supported=False,
    )

    assert result.used_exchange is False
    assert result.live_path == live
    assert result.previous_tree_path == tmp_path / "live.prev"
    assert (live / "new.txt").read_text() == "new"
    assert not (live / "old.txt").exists()
    assert (tmp_path / "live.prev" / "old.txt").read_text() == "old"
    assert not staging.exists()
    assert journal.phases == [
        PHASE_PREPARED,
        PHASE_SWAPPING_OUT_LIVE,
        PHASE_SWAPPING_IN_STAGING,
        PHASE_SWAP_COMPLETED,
    ]
    latest = journal.read()
    assert latest is not None
    assert latest.phase == PHASE_SWAP_COMPLETED
    assert latest.used_exchange is False


def test_exchange_swap_when_supported(tmp_path: Path) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)

    try:
        result = swap_directories(
            live,
            staging,
            journal,
            server_id=SERVER_ID,
            exchange_supported=True,
        )
    except ValidationError as exc:
        if exc.details.get("field") == "exchange_supported":
            pytest.skip("filesystem does not support RENAME_EXCHANGE")
        raise

    assert result.used_exchange is True
    assert (live / "new.txt").read_text() == "new"
    assert (staging / "old.txt").read_text() == "old"
    assert _latest_phase(journal) == PHASE_SWAP_COMPLETED


def test_rename_exchange_swaps_two_directories(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _tree(left, "left.txt", "left")
    _tree(right, "right.txt", "right")

    if not rename_exchange(left, right):
        pytest.skip("filesystem does not support RENAME_EXCHANGE")

    assert (left / "right.txt").read_text() == "right"
    assert (right / "left.txt").read_text() == "left"


def test_forced_exchange_on_unsupported_filesystem_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)
    monkeypatch.setattr(
        "app.modules.versioning.infrastructure.directory_swap.rename_exchange",
        lambda *_args: False,
    )

    with pytest.raises(ValidationError, match="RENAME_EXCHANGE"):
        swap_directories(
            live,
            staging,
            journal,
            server_id=SERVER_ID,
            exchange_supported=True,
        )

    assert (live / "old.txt").read_text() == "old"
    assert (staging / "new.txt").read_text() == "new"
    record = journal.read()
    assert record is not None
    assert record.phase == PHASE_SWAP_ROLLED_BACK


def test_failed_swap_in_restores_live_and_marks_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)
    real_rename = os.rename
    calls = {"count": 0}

    def flaky_rename(source: str, destination: str) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError(errno.EIO, "injected rename failure")
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", flaky_rename)

    with pytest.raises(OSError, match="injected"):
        swap_directories(
            live,
            staging,
            journal,
            server_id=SERVER_ID,
            exchange_supported=False,
        )

    assert (live / "old.txt").read_text() == "old"
    assert not (tmp_path / "live.prev").exists()
    record = journal.read()
    assert record is not None
    assert record.phase == PHASE_SWAP_ROLLED_BACK


def test_recover_swapping_out_live_restores_previous_tree(tmp_path: Path) -> None:
    live = tmp_path / "live"
    previous = tmp_path / "live.prev"
    staging = tmp_path / "staging"
    _tree(previous, "old.txt", "old")
    staging.mkdir()
    journal = _journal(tmp_path)
    journal.write(_record(live, staging, PHASE_SWAPPING_OUT_LIVE))

    result = recover_interrupted_swap(journal)

    assert result.status == "rolled_back"
    assert (live / "old.txt").read_text() == "old"
    assert not previous.exists()
    assert _latest_phase(journal) == PHASE_SWAP_ROLLED_BACK


def test_recover_swapping_in_staging_restores_when_live_is_missing(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    previous = tmp_path / "live.prev"
    staging = tmp_path / "staging"
    _tree(previous, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)
    journal.write(_record(live, staging, PHASE_SWAPPING_IN_STAGING))

    result = recover_interrupted_swap(journal)

    assert result.status == "rolled_back"
    assert (live / "old.txt").read_text() == "old"
    assert (staging / "new.txt").read_text() == "new"
    assert _latest_phase(journal) == PHASE_SWAP_ROLLED_BACK


def test_recover_swapping_in_staging_marks_completed_when_live_exists(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    previous = tmp_path / "live.prev"
    staging = tmp_path / "staging"
    _tree(live, "new.txt", "new")
    _tree(previous, "old.txt", "old")
    journal = _journal(tmp_path)
    journal.write(_record(live, staging, PHASE_SWAPPING_IN_STAGING))

    result = recover_interrupted_swap(journal)

    assert result.status == "completed"
    assert (live / "new.txt").read_text() == "new"
    assert (previous / "old.txt").read_text() == "old"
    assert _latest_phase(journal) == PHASE_SWAP_COMPLETED


def test_recover_failed_rollback_write_classifies_as_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-1: live restored + staging still present + no .prev is a rollback."""
    live = tmp_path / "live"
    previous = tmp_path / "live.prev"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)

    real_write = journal.write
    real_rename = os.rename

    def flaky_write(record: SwapJournalRecord) -> None:
        if record.phase == PHASE_SWAP_ROLLED_BACK:
            raise OSError(errno.EIO, "injected SWAP_ROLLED_BACK journal write failure")
        real_write(record)

    def flaky_rename(src: object, dst: object) -> None:
        if Path(str(src)) == staging and Path(str(dst)) == live:
            raise OSError(errno.EIO, "injected staging -> live rename failure")
        real_rename(src, dst)

    monkeypatch.setattr(journal, "write", flaky_write)
    monkeypatch.setattr(os, "rename", flaky_rename)

    with pytest.raises(OSError, match="staging -> live"):
        swap_directories(
            live,
            staging,
            journal,
            server_id=SERVER_ID,
            exchange_supported=False,
        )

    # Crash image: live holds the old tree again, staging still holds the new
    # tree, .prev is gone, and the journal never received SWAP_ROLLED_BACK.
    assert _latest_phase(journal) == PHASE_SWAPPING_IN_STAGING
    assert (live / "old.txt").read_text() == "old"
    assert (staging / "new.txt").read_text() == "new"
    assert not previous.exists()

    monkeypatch.setattr(journal, "write", real_write)
    monkeypatch.setattr(os, "rename", real_rename)

    result = recover_interrupted_swap(journal)

    assert result.status == "rolled_back"
    assert _latest_phase(journal) == PHASE_SWAP_ROLLED_BACK
    assert result.record is not None
    assert result.record.phase == PHASE_SWAP_ROLLED_BACK


def test_recover_prepared_swap_leaves_live_untouched(tmp_path: Path) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    journal = _journal(tmp_path)
    journal.write(_record(live, staging, PHASE_PREPARED))

    result = recover_interrupted_swap(journal)

    assert result.status == "unchanged"
    assert (live / "old.txt").read_text() == "old"
    assert _latest_phase(journal) == PHASE_PREPARED


def test_missing_journal_returns_none(tmp_path: Path) -> None:
    result = recover_interrupted_swap(_journal(tmp_path))
    assert result.status == "none"
    assert result.record is None


def test_invalid_journal_is_rejected(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.path.parent.mkdir(parents=True, exist_ok=True)
    journal.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationError, match="not valid JSON"):
        journal.read()


def test_previous_path_must_not_exist(tmp_path: Path) -> None:
    live = tmp_path / "live"
    staging = tmp_path / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    _tree(tmp_path / "live.prev", "stale.txt", "stale")
    with pytest.raises(ConflictError, match="previous path"):
        swap_directories(
            live,
            staging,
            _journal(tmp_path),
            server_id=SERVER_ID,
            exchange_supported=False,
        )


def test_symlinked_live_tree_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _tree(real, "old.txt", "old")
    live = tmp_path / "live"
    live.symlink_to(real)
    staging = tmp_path / "staging"
    _tree(staging, "new.txt", "new")
    with pytest.raises(ValidationError, match="symlink"):
        swap_directories(
            live,
            staging,
            _journal(tmp_path),
            server_id=SERVER_ID,
            exchange_supported=False,
        )


def test_nested_live_and_staging_are_rejected(tmp_path: Path) -> None:
    live = tmp_path / "live"
    staging = live / "staging"
    _tree(live, "old.txt", "old")
    _tree(staging, "new.txt", "new")
    with pytest.raises(ValidationError, match="contain each other"):
        swap_directories(
            live,
            staging,
            _journal(tmp_path),
            server_id=SERVER_ID,
            exchange_supported=False,
        )


def test_journal_is_valid_json_and_fsynced(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.write(
        SwapJournalRecord(
            journal_id="journal-2",
            server_id=SERVER_ID,
            phase=PHASE_PREPARED,
            live_path=str(tmp_path / "live"),
            staging_path=str(tmp_path / "staging"),
            previous_path=str(tmp_path / "live.prev"),
            previous_main_sha="a" * 40,
            target_main_sha="b" * 40,
        )
    )
    payload = json.loads(journal.path.read_text())
    assert payload["journal_id"] == "journal-2"
    assert payload["phase"] == PHASE_PREPARED
    assert payload["previous_main_sha"] == "a" * 40
    assert journal.path.stat().st_mode & 0o777 == 0o600
