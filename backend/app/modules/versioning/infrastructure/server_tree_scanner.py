"""Server tree scanner for deterministic, allow-list-driven filesystem inventories.

P2-1 Core Substrate — B4c
"""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from app.core.allowlist import SymlinkEscapeError, classify, validate_canonical_relpath
from app.core.exceptions import CaseCollisionError

PRUNED_DIR_NAMES = frozenset({
    "libraries",
    "versions",
    ".fabric",
    ".git",
    "logs",
    "crash-reports",
    "cache",
    ".cache",
})

ALL_CLASSES = (
    "A-JAR",
    "A-CAS",
    "A-LOCKFILE",
    "B",
    "C",
    "E",
    "QUARANTINE",
)


@dataclass(frozen=True)
class ScannedFile:
    path: str  # canonical POSIX relpath
    classification: str  # A-JAR | A-CAS | A-LOCKFILE | B | C | E | QUARANTINE
    size: int


@dataclass(frozen=True)
class ScanReport:
    root: Path
    files: tuple[ScannedFile, ...]  # sorted by path
    by_class: Mapping[str, int]
    quarantined: tuple[str, ...]
    skipped_symlinks: tuple[str, ...]
    skipped_dirs: tuple[str, ...]
    case_collisions: tuple[tuple[str, str], ...]
    total_bytes: int
    truncated: bool


def _is_symlink_or_reparse(entry: os.DirEntry[str]) -> bool:
    """Return True if entry is a POSIX symlink or Windows reparse point."""
    if entry.is_symlink():
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        st = entry.stat(follow_symlinks=False)
        if getattr(st, "st_file_attributes", 0) & reparse:
            return True
    except OSError:
        pass
    return False


class _TruncationLimitReachedError(Exception):
    """Internal sentinel indicating max_files or max_total_bytes limit was hit."""


def scan_server_tree(
    root: str | Path,
    *,
    max_files: int = 200_000,
    max_total_bytes: int = 20 * 1024**3,
    dynamic_class_c: Set[str] = frozenset(),
) -> ScanReport:
    """Scan a server tree deterministically according to allow-list classification rules."""
    root_str = str(root)
    if not os.path.isabs(root_str):
        raise ValueError(f"Root must be an absolute path: {root_str!r}")
    if os.path.islink(root_str):
        raise SymlinkEscapeError(f"Root itself is a symlink: {root_str!r}")

    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        st = os.lstat(root_str)
    except OSError as e:
        raise ValueError(f"Root does not exist: {root_str!r}") from e

    if getattr(st, "st_file_attributes", 0) & reparse:
        raise SymlinkEscapeError(f"Root is a reparse point: {root_str!r}")

    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"Root is not an existing directory: {root_str!r}")

    c_set = frozenset(dynamic_class_c) if dynamic_class_c else frozenset()

    files: list[ScannedFile] = []
    quarantined: list[str] = []
    skipped_symlinks: list[str] = []
    skipped_dirs: list[str] = []
    case_collisions: list[tuple[str, str]] = []
    seen_casefold: dict[str, str] = {}
    by_class: dict[str, int] = {c: 0 for c in ALL_CLASSES}
    total_bytes = 0
    truncated = False

    def _walk(current_dir: str, current_relpath: str) -> None:
        nonlocal total_bytes, truncated

        try:
            with os.scandir(current_dir) as it:
                entries = sorted(list(it), key=lambda e: e.name)
        except OSError as e:
            raise ValueError(f"Cannot read directory {current_dir}: {e}") from e

        for entry in entries:
            rel_path = f"{current_relpath}/{entry.name}" if current_relpath else entry.name
            validate_canonical_relpath(rel_path)

            if _is_symlink_or_reparse(entry):
                skipped_symlinks.append(rel_path)
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as e:
                raise ValueError(f"Cannot stat entry {rel_path}: {e}") from e

            if is_dir:
                if entry.name in PRUNED_DIR_NAMES:
                    skipped_dirs.append(rel_path)
                else:
                    _walk(entry.path, rel_path)
                continue

            if is_file:
                if len(files) >= max_files:
                    truncated = True
                    raise _TruncationLimitReachedError()

                try:
                    f_st = entry.stat(follow_symlinks=False)
                    size = max(0, f_st.st_size)
                except OSError as e:
                    raise ValueError(f"Cannot stat file {rel_path}: {e}") from e

                if total_bytes + size > max_total_bytes:
                    truncated = True
                    raise _TruncationLimitReachedError()

                folded = rel_path.casefold()
                if folded in seen_casefold:
                    prev = seen_casefold[folded]
                    if prev != rel_path:
                        pair = (min(prev, rel_path), max(prev, rel_path))
                        if pair not in case_collisions:
                            case_collisions.append(pair)
                else:
                    seen_casefold[folded] = rel_path

                classification = classify(rel_path, dynamic_class_c=c_set)
                if classification == "QUARANTINE":
                    quarantined.append(rel_path)

                by_class[classification] = by_class.get(classification, 0) + 1
                files.append(
                    ScannedFile(path=rel_path, classification=classification, size=size)
                )
                total_bytes += size

    with contextlib.suppress(_TruncationLimitReachedError):
        _walk(root_str, "")

    case_collisions.sort()
    if case_collisions:
        first_a, first_b = case_collisions[0]
        raise CaseCollisionError(
            f"Casefold collision: {first_a!r} vs {first_b!r}",
            path_a=first_a,
            path_b=first_b,
        )

    files.sort(key=lambda f: f.path)
    quarantined.sort()
    skipped_symlinks.sort()
    skipped_dirs.sort()

    return ScanReport(
        root=Path(root_str),
        files=tuple(files),
        by_class=dict(by_class),
        quarantined=tuple(quarantined),
        skipped_symlinks=tuple(skipped_symlinks),
        skipped_dirs=tuple(skipped_dirs),
        case_collisions=tuple(case_collisions),
        total_bytes=total_bytes,
        truncated=truncated,
    )
