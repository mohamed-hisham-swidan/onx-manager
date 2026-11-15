"""Native Git "Save & Commit" for Advanced branch worktrees (P2-4).

Normative contract: ``SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02`` P2 / D-C, D-E,
OD-v8.5-1, OD-v8.6-5, OD-v8.7-3/12/15.

The service never commits raw working-tree bytes. Every changed allow-listed
Class-B path is normalized, validated, secret-scanned, and only then staged with
native ``git add``. Class-A binaries are routed to the host CAS and recorded in
``onx-jars.lock.json``; hostile executables under config roots are quarantined
and never staged. Class-C/Class-E changes are intentionally left untracked.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from app.core.allowlist import classify as classify_path
from app.core.allowlist import open_safe_path_fd, validate_canonical_relpath
from app.core.exceptions import (
    CaseCollisionError,
    ConflictError,
    GitRepositoryStateError,
    OversizedGitTrackedFileError,
    ValidationError,
)
from app.core.host_state import HostStateLayout
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    LOCKFILE_RELPATH,
    PANEL_GITATTRIBUTES_CONTENT,
    _normalize_server_properties,
    _normalize_text,
    validate_server_root,
)
from app.modules.versioning.infrastructure.secret_scanner import assert_no_secrets

MAX_CLASS_B_FILE_BYTES = 1024 * 1024
MAX_CLASS_B_ROUTED_BYTES = 16 * 1024 * 1024
MAX_LOCKFILE_BYTES = 16 * 1024 * 1024
MAX_QUARANTINE_BYTES = 16 * 1024 * 1024
MAX_MESSAGE_LENGTH = 500

_SHA_RE = re.compile(r"\A[0-9a-f]{40,64}\Z")
_READ_CHUNK = 65536


@dataclass(frozen=True)
class GitSaveCommitResult:
    """Outcome of one native Save & Commit."""

    commit_id: str
    parent_commit_id: str | None
    branch_name: str
    message: str
    files: tuple[str, ...]
    routed_to_cas: tuple[str, ...] = ()
    quarantined: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _StatusEntry:
    code: str
    path: str

    @property
    def deleted(self) -> bool:
        return "D" in self.code


def _require_sha(value: str, kind: str) -> str:
    sha = value.strip()
    if not _SHA_RE.match(sha):
        raise GitRepositoryStateError(
            f"Git returned an invalid {kind} object id",
            details={"value": sha[:128]},
        )
    return sha


def _parse_status(output: str) -> list[_StatusEntry]:
    entries: list[_StatusEntry] = []
    for record in output.split("\x00"):
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise GitRepositoryStateError(
                "Git returned an unexpected status record",
                details={"record": record[:128]},
            )
        entries.append(_StatusEntry(code=record[:2], path=record[3:]))
    return entries


def _status_size(path: Path, relpath: str) -> int:
    try:
        st = path.lstat()
    except OSError as exc:
        raise GitRepositoryStateError(
            "Unable to inspect a changed file",
            details={"path": relpath[:128], "reason": str(exc)[:128]},
        ) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValidationError(
            f"Changed path '{relpath}' is not a regular file",
            field="path",
            details={"path": relpath[:128]},
        )
    return st.st_size


def _read_regular_file(
    root: Path,
    relpath: str,
    *,
    max_bytes: int,
) -> tuple[bytes, int]:
    try:
        fd = open_safe_path_fd(
            str(root),
            relpath,
            flags=os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except (OSError, ValueError) as exc:
        raise GitRepositoryStateError(
            "Unable to open a changed file safely",
            details={"path": relpath[:128]},
        ) from exc

    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValidationError(
                f"Changed path '{relpath}' is not a regular file",
                field="path",
                details={"path": relpath[:128]},
            )
        if before.st_size > max_bytes:
            raise OversizedGitTrackedFileError(relpath, before.st_size, max_bytes)
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(fd, min(_READ_CHUNK, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(data) != after.st_size
        ):
            raise GitRepositoryStateError(
                "Changed file changed while it was being read",
                details={"path": relpath[:128]},
            )
        if len(data) > max_bytes:
            raise OversizedGitTrackedFileError(relpath, len(data), max_bytes)
        return data, after.st_size
    finally:
        os.close(fd)


def _ensure_parent_dirs(worktree: Path, relpath: str) -> Path:
    validate_canonical_relpath(relpath)
    current = worktree
    for segment in relpath.split("/")[:-1]:
        current = current / segment
        if current.is_symlink():
            raise GitRepositoryStateError(
                "Changed path contains a symlinked directory",
                details={"path": relpath[:128]},
            )
        if not current.exists():
            current.mkdir(mode=0o755)
        if not current.is_dir():
            raise GitRepositoryStateError(
                "Changed path parent is not a directory",
                details={"path": relpath[:128]},
            )
    return worktree.joinpath(*relpath.split("/"))


def _write_worktree_file(worktree: Path, relpath: str, data: bytes) -> None:
    target = _ensure_parent_dirs(worktree, relpath)
    atomic_write_private(target, data, mode=0o600, fsync_parent=False)


def _unlink_worktree_file(worktree: Path, relpath: str) -> None:
    target = worktree.joinpath(*relpath.split("/"))
    if target.is_symlink():
        raise GitRepositoryStateError(
            "Refusing to remove a symlink",
            details={"path": relpath[:128]},
        )
    try:
        target.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise GitRepositoryStateError(
            "Unable to remove a CAS-routed file from the worktree",
            details={"path": relpath[:128], "reason": str(exc)[:128]},
        ) from exc


def _find_conflict_markers(data: bytes) -> bool:
    text = data.decode("utf-8", errors="replace")
    return any(
        line.startswith(("<<<<<<<", "=======", ">>>>>>>"))
        for line in text.split("\n")
    )


def _parse_properties_strict(text: str) -> None:
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line and ":" not in line:
            raise ValueError("properties line is not key=value")


def _validate_structured(path: str, data: bytes) -> None:
    """Reject conflict markers and unparseable structured config files."""
    if _find_conflict_markers(data):
        raise ValidationError(
            f"Config file '{path}' contains conflict markers",
            field="path",
            details={"path": path[:128], "reason": "conflict-marker"},
        )

    text = data.decode("utf-8")
    lowered = path.lower()
    try:
        if lowered.endswith(".json"):
            json.loads(text)
        elif lowered.endswith((".yml", ".yaml")):
            # A YAML stream may hold several documents; consume all of them so
            # valid multi-document files save while malformed ones fail closed.
            for _doc in yaml.safe_load_all(text):
                pass
        elif lowered.endswith(".toml"):
            tomllib.loads(text)
        elif lowered.endswith(".properties"):
            _parse_properties_strict(text)
    except (ValueError, TypeError, yaml.YAMLError) as exc:
        raise ValidationError(
            f"Config file '{path}' failed to parse",
            field="path",
            details={"path": path[:128], "reason": str(exc)[:128]},
        ) from exc


def _read_lockfile(worktree: Path) -> LockfileV21:
    data, _ = _read_regular_file(
        worktree,
        LOCKFILE_RELPATH,
        max_bytes=MAX_LOCKFILE_BYTES,
    )
    return parse_lockfile(data)


def _ingest_to_cas(
    layout: HostStateLayout,
    worktree: Path,
    relpath: str,
) -> LockfileFile:
    target = worktree.joinpath(*relpath.split("/"))
    try:
        before = target.lstat()
    except OSError as exc:
        raise GitRepositoryStateError(
            "Unable to stat a Class-A file before CAS ingest",
            details={"path": relpath[:128]},
        ) from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValidationError(
            f"Class-A path '{relpath}' is not a regular file",
            field="path",
            details={"path": relpath[:128]},
        )

    digest = ArtifactCas(layout.cas).put_file(target)
    after = target.lstat()
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise GitRepositoryStateError(
            "Class-A file changed while it was being ingested",
            details={"path": relpath[:128]},
        )
    return LockfileFile(
        path=relpath,
        sha256=digest,
        size=after.st_size,
        optional=False,
        env_server=EnvServer.REQUIRED,
        origin=Origin.USER,
    )


def _quarantine_hostile(
    layout: HostStateLayout,
    server_id: str,
    worktree: Path,
    relpath: str,
) -> None:
    data, _ = _read_regular_file(worktree, relpath, max_bytes=MAX_QUARANTINE_BYTES)
    destination = layout.quarantine_dir(server_id).joinpath(*relpath.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_private(destination, data, mode=0o400, fsync_parent=True)
    _unlink_worktree_file(worktree, relpath)


def _assert_no_case_collisions(
    tracked_paths: set[str],
    changed_paths: set[str],
) -> None:
    candidates = tracked_paths | changed_paths
    folded: dict[str, str] = {}
    for path in sorted(candidates):
        key = path.casefold()
        previous = folded.get(key)
        if previous is not None and previous != path:
            raise CaseCollisionError(
                f"Casefold collision: {previous!r} vs {path!r}",
                path_a=previous,
                path_b=path,
            )
        folded[key] = path


class GitSaveCommitService:
    """Validate, normalize, stage, and commit one branch worktree."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        git_executable: str = "git",
        timeout: float = 60.0,
    ) -> None:
        self._layout = layout
        self._git_executable = git_executable
        self._timeout = timeout
        self._branches = GitBranchService(
            layout,
            git_executable=git_executable,
            timeout=timeout,
        )

    def save(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        branch_name: str,
        message: str,
    ) -> GitSaveCommitResult:
        if not isinstance(message, str) or not message.strip():
            raise ValidationError("Commit message must not be empty", field="message")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValidationError(
                f"Commit message must be at most {MAX_MESSAGE_LENGTH} characters",
                field="message",
            )

        root = validate_server_root(server_root)
        branch = self._branches.get_branch(server_id, root, branch_name)
        if branch is None:
            raise ConflictError(f"Branch '{branch_name}' not found")
        if branch.worktree_path is None:
            raise ConflictError(
                f"Branch '{branch_name}' has no active worktree; restore or recreate it first"
            )

        worktree = branch.worktree_path
        runner = self._branches.open_runner(server_id, root)

        # The panel owns staging. Drop any user-staged paths so an ignored
        # Class-C/Class-E blob can never ride along into the commit.
        runner.run("reset", "-q", cwd=worktree)
        status = runner.run(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
            cwd=worktree,
        )
        entries = _parse_status(status.stdout)

        if any(
            entry.path == LOCKFILE_RELPATH and entry.deleted for entry in entries
        ):
            raise ValidationError(
                "The authoritative lockfile cannot be deleted",
                field="path",
                details={"path": LOCKFILE_RELPATH},
            )

        lockfile = _read_lockfile(worktree)
        files_by_path = {entry.path: entry for entry in lockfile.files}
        tracked_paths = {
            path
            for path in runner.run("ls-files", "-z", cwd=worktree).stdout.split("\x00")
            if path
        }
        changed: list[str] = []
        routed: list[str] = []
        removed_tracked: list[str] = []
        quarantined: list[str] = []
        warnings: list[str] = []
        changed_paths = {entry.path for entry in entries}

        for entry in entries:
            relpath = entry.path
            try:
                validate_canonical_relpath(relpath)
            except ValueError as exc:
                raise ValidationError(
                    "Changed path is not a canonical relative path",
                    field="path",
                    details={"path": relpath[:128], "reason": str(exc)[:128]},
                ) from exc

            classification = classify_path(relpath)
            target = worktree.joinpath(*relpath.split("/"))

            if classification == "QUARANTINE":
                if not entry.deleted:
                    try:
                        _quarantine_hostile(self._layout, server_id, worktree, relpath)
                        quarantined.append(relpath)
                    except Exception as exc:  # noqa: BLE001 - non-blocking by spec
                        warnings.append(
                            f"Unable to quarantine '{relpath}': {type(exc).__name__}"
                        )
                continue

            if classification in ("A-JAR", "A-CAS"):
                if entry.deleted:
                    if files_by_path.pop(relpath, None) is not None:
                        warnings.append(f"Removed lockfile entry for deleted '{relpath}'")
                    continue
                entry_file = _ingest_to_cas(self._layout, worktree, relpath)
                files_by_path[relpath] = entry_file
                _unlink_worktree_file(worktree, relpath)
                if relpath in tracked_paths:
                    removed_tracked.append(relpath)
                routed.append(relpath)
                continue

            if classification == "A-LOCKFILE":
                if entry.deleted:
                    raise ValidationError(
                        "The authoritative lockfile cannot be deleted",
                        field="path",
                        details={"path": relpath[:128]},
                    )
                continue

            if classification != "B":
                # Class C, Class E, and rejected paths are never staged.
                continue

            if entry.deleted:
                changed.append(relpath)
                continue

            size = _status_size(target, relpath)
            if relpath == "server-icon.png" and size > MAX_CLASS_B_FILE_BYTES:
                raise OversizedGitTrackedFileError(
                    relpath, size, MAX_CLASS_B_FILE_BYTES
                )
            if size > MAX_CLASS_B_ROUTED_BYTES:
                raise OversizedGitTrackedFileError(
                    relpath, size, MAX_CLASS_B_ROUTED_BYTES
                )
            if size > MAX_CLASS_B_FILE_BYTES:
                entry_file = _ingest_to_cas(self._layout, worktree, relpath)
                files_by_path[relpath] = entry_file
                _unlink_worktree_file(worktree, relpath)
                if relpath in tracked_paths:
                    removed_tracked.append(relpath)
                routed.append(relpath)
                warnings.append(
                    f"'{relpath}' is larger than 1 MiB and was routed to A-CAS"
                )
                continue

            data, _ = _read_regular_file(
                worktree,
                relpath,
                max_bytes=MAX_CLASS_B_FILE_BYTES,
            )
            if relpath == "server.properties":
                data = _normalize_server_properties(data)
            elif not relpath.lower().endswith(".png"):
                data = _normalize_text(relpath, data)

            _validate_structured(relpath, data)
            assert_no_secrets(relpath, data)
            _write_worktree_file(worktree, relpath, data)
            changed.append(relpath)

        _assert_no_case_collisions(tracked_paths, changed_paths)

        lockfile = replace(
            lockfile,
            files=tuple(sorted(files_by_path.values(), key=lambda item: item.path)),
        )
        _write_worktree_file(worktree, LOCKFILE_RELPATH, dump_lockfile(lockfile))
        _write_worktree_file(
            worktree,
            GITATTRIBUTES_RELPATH,
            PANEL_GITATTRIBUTES_CONTENT,
        )

        staged_paths = sorted(
            set(changed)
            | set(removed_tracked)
            | {LOCKFILE_RELPATH, GITATTRIBUTES_RELPATH}
        )
        pathspec = "\x00".join(staged_paths) + "\x00"
        runner.run(
            "add",
            "-A",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            cwd=worktree,
            input_text=pathspec,
        )

        quiet = runner.run("diff", "--cached", "--quiet", cwd=worktree, check=False)
        if quiet.returncode == 0:
            raise ConflictError("No changes to commit")
        if quiet.returncode != 1:
            raise GitRepositoryStateError(
                "Unable to inspect the staged Git index",
                details={"stderr": quiet.stderr[:500]},
            )

        runner.run("commit", "-m", message, cwd=worktree)
        commit_id = _require_sha(
            runner.run("rev-parse", "HEAD", cwd=worktree).stdout,
            "commit",
        )
        parent_result = runner.run(
            "rev-parse", "--verify", "HEAD^", cwd=worktree, check=False
        )
        parent_commit_id = (
            _require_sha(parent_result.stdout, "parent commit")
            if parent_result.returncode == 0
            else None
        )

        committed = runner.run(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            "HEAD",
            cwd=worktree,
        ).stdout.split("\x00")

        return GitSaveCommitResult(
            commit_id=commit_id,
            parent_commit_id=parent_commit_id,
            branch_name=branch.name,
            message=message,
            files=tuple(path for path in committed if path),
            routed_to_cas=tuple(sorted(routed)),
            quarantined=tuple(sorted(quarantined)),
            warnings=tuple(warnings),
        )


__all__ = ["GitSaveCommitResult", "GitSaveCommitService"]
