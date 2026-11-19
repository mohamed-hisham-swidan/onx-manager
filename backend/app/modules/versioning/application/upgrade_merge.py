"""Three-way Class-B config merge and per-file ``base_overrides`` advancement (P5.5).

Uses ``LockfileV21.base_overrides`` in CAS as the merge ancestor ``B``, live/branch
Class-B files as ``O``, and the target pack's overrides as ``T``. Implements
OD-v8.7-9: ``base_overrides`` advances per file only for cleanly merged or
operator-resolved files, while ``ours-fallback`` files retain their previous ``B``
hash so future upgrades never silently drop operator edits.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from app.core.allowlist import (
    SymlinkEscapeError,
    classify,
    open_safe_path_fd,
    validate_canonical_relpath,
)
from app.core.exceptions import ConflictError, MergeConflictError, ValidationError
from app.modules.versioning.application.modpack_lockfile_builder import (
    advance_base_overrides_per_file,
    store_base_overrides_in_cas,
)
from app.modules.versioning.domain.lockfile import LockfileV21
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.git_save_commit import _find_conflict_markers
from app.modules.versioning.infrastructure.merge_engine import (
    SET_MERGEABLE_ARRAY_KEYS,
    STRUCTURED_EXTENSIONS,
    MergeConflictItem,
    _parse_structured,
    merge_class_b_file,
)
from app.modules.versioning.infrastructure.secret_scanner import assert_no_secrets

_SKIP_TREE_DIRS = frozenset({".git", ".onx", ".onx-manager", ".mcsmanager"})


@dataclass(frozen=True)
class UpgradeMergeResult:
    """Outcome of a 3-way Class-B upgrade config merge."""

    merged_files: dict[str, bytes]
    deleted_files: tuple[str, ...]
    conflicts: tuple[MergeConflictItem, ...]
    warnings: tuple[str, ...]
    new_base_overrides: dict[str, str]
    cleanly_resolved_paths: tuple[str, ...]
    fallback_paths: tuple[str, ...]

    @property
    def status(self) -> Literal["clean", "needs_resolution"]:
        return "needs_resolution" if self.conflicts else "clean"


def _validate_resolved_content(relpath: str, resolved_bytes: bytes) -> None:
    if _find_conflict_markers(resolved_bytes):
        raise ConflictError(f"Unresolved conflict markers remain in '{relpath}'")

    lowered = relpath.lower()
    ext = "." + lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if ext in STRUCTURED_EXTENSIONS:
        if ext in (".yml", ".yaml"):
            try:
                text = resolved_bytes.decode("utf-8")
                list(yaml.safe_load_all(text))
            except (UnicodeDecodeError, yaml.YAMLError) as exc:
                raise ValidationError(
                    f"Resolved config '{relpath}' failed YAML validation: {exc}",
                    field="resolved_conflicts",
                ) from exc
        elif _parse_structured(relpath, resolved_bytes) is None:
            raise ValidationError(
                f"Resolved config '{relpath}' failed structured parse validation",
                field="resolved_conflicts",
            )

    assert_no_secrets(relpath, resolved_bytes)


def merge_upgrade_configs(
    *,
    cas: ArtifactCas,
    current_lockfile: LockfileV21,
    ours_files: Mapping[str, bytes],
    theirs_overrides: Mapping[str, bytes],
    set_mergeable_array_keys: frozenset[tuple[str, str]] = SET_MERGEABLE_ARRAY_KEYS,
    resolved_conflicts: Mapping[str, bytes] = {},
) -> UpgradeMergeResult:
    """Perform 3-way Class-B merge and per-file ``base_overrides`` advancement."""
    all_paths = sorted(
        set(current_lockfile.base_overrides)
        | set(ours_files)
        | set(theirs_overrides)
        | set(resolved_conflicts)
    )

    merged_files: dict[str, bytes] = {}
    deleted_files: list[str] = []
    conflicts: list[MergeConflictItem] = []
    warnings: list[str] = []
    cleanly_resolved_paths: set[str] = set()
    removed_paths: set[str] = set()
    fallback_paths: list[str] = []

    for raw_path in all_paths:
        relpath = validate_canonical_relpath(raw_path)
        if classify(relpath) != "B":
            raise ValidationError(
                f"Upgrade config merge only accepts Class-B paths, got '{relpath}'",
                field="path",
            )

        if relpath in resolved_conflicts:
            resolved_bytes = bytes(resolved_conflicts[relpath])
            _validate_resolved_content(relpath, resolved_bytes)
            merged_files[relpath] = resolved_bytes
            cleanly_resolved_paths.add(relpath)
            continue

        base_sha = current_lockfile.base_overrides.get(relpath)
        if base_sha is not None:
            with cas.open_blob(base_sha) as fh:
                base_bytes: bytes | None = fh.read()
        else:
            base_bytes = None
        ours_bytes = ours_files.get(relpath)
        theirs_bytes = theirs_overrides.get(relpath)

        outcome = merge_class_b_file(
            relpath,
            base_bytes,
            ours_bytes,
            theirs_bytes,
            set_mergeable_array_keys=set_mergeable_array_keys,
        )
        warnings.extend(outcome.warnings)

        if outcome.conflicts:
            conflicts.extend(outcome.conflicts)
            if outcome.content is not None:
                merged_files[relpath] = outcome.content
            continue

        if outcome.used_strategy == "ours-fallback":
            fallback_paths.append(relpath)
            if outcome.content is not None:
                merged_files[relpath] = outcome.content
            continue

        cleanly_resolved_paths.add(relpath)
        if outcome.content is None:
            deleted_files.append(relpath)
            if relpath in current_lockfile.base_overrides and relpath not in theirs_overrides:
                removed_paths.add(relpath)
        else:
            merged_files[relpath] = outcome.content

    target_base_overrides = store_base_overrides_in_cas(cas, theirs_overrides)
    new_base_overrides = advance_base_overrides_per_file(
        current_lockfile.base_overrides,
        target_base_overrides,
        resolved_paths=cleanly_resolved_paths,
        removed_paths=removed_paths,
    )

    return UpgradeMergeResult(
        merged_files=merged_files,
        deleted_files=tuple(sorted(deleted_files)),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        new_base_overrides=new_base_overrides,
        cleanly_resolved_paths=tuple(sorted(cleanly_resolved_paths)),
        fallback_paths=tuple(sorted(fallback_paths)),
    )


def assert_tree_ready_for_upgrade_export(
    root_dir: Path,
    merge_result: UpgradeMergeResult | None = None,
) -> None:
    """Fail closed if merge conflicts or conflict markers exist in *root_dir*."""
    if merge_result is not None and merge_result.conflicts:
        raise MergeConflictError(
            conflicts=[c.to_dict() for c in merge_result.conflicts],
            warnings=list(merge_result.warnings),
        )

    root = Path(os.path.abspath(str(root_dir)))
    if not root.is_dir() or root.is_symlink():
        raise ValidationError(f"Upgrade tree '{root}' is not a valid directory", field="root_dir")

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_TREE_DIRS)
        for filename in sorted(filenames):
            full = Path(dirpath) / filename
            if full.is_symlink():
                raise ValidationError(
                    f"Upgrade tree contains a symlink: '{full.relative_to(root).as_posix()}'",
                    field="path",
                )
            relpath = full.relative_to(root).as_posix()
            if classify(relpath) != "B":
                continue
            try:
                fd = open_safe_path_fd(str(root), relpath, flags=os.O_RDONLY)
            except (OSError, SymlinkEscapeError) as exc:
                raise ValidationError(
                    f"Unable to read Class-B file '{relpath}' during export check",
                    field="path",
                ) from exc
            try:
                data = os.read(fd, 1024 * 1024 + 1)
            finally:
                os.close(fd)
            if _find_conflict_markers(data):
                raise ConflictError(f"Unresolved conflict markers remain in '{relpath}'")


__all__ = [
    "UpgradeMergeResult",
    "assert_tree_ready_for_upgrade_export",
    "merge_upgrade_configs",
]
