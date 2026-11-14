"""Native Git branch and worktree lifecycle for Advanced servers (P2-2).

UI branches are real Git refs (``refs/heads/*``). Every active branch has one
worktree under ``<server_root>/.onx/worktrees/<branch>``; the bare repository
lives outside the server tree. ``main`` is created eagerly by
:class:`GitRepositoryService` and is never archivable or deletable here.

Branch names are validated both by ``git check-ref-format --branch`` and by a
stricter panel-owned path contract, because the name becomes a directory path
component beneath the worktree root.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import (
    BranchProtectedError,
    ConflictError,
    GitRefValidationError,
    GitRepositoryStateError,
    NotFoundError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.infrastructure.git_repository import (
    MAIN_BRANCH,
    ensure_private_dir,
    validate_server_root,
)
from app.modules.versioning.infrastructure.git_runner import GitRunner

MAX_BRANCH_NAME_LENGTH = 100
MAX_BRANCH_SEGMENT_LENGTH = 63

_SAFE_BRANCH_SEGMENT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,62}\Z")
_OID_RE = re.compile(r"\A[0-9a-f]{40,64}\Z")


@dataclass(frozen=True)
class GitBranchInfo:
    """One local branch and, when checked out, its worktree."""

    name: str
    sha: str
    worktree_path: Path | None = None
    worktree_locked: bool = False


@dataclass(frozen=True)
class GitBranchRemovalResult:
    """Outcome of archiving (ref kept) or deleting (ref removed) a branch."""

    name: str
    sha: str
    worktree_removed: bool
    ref_deleted: bool


@dataclass(frozen=True)
class _WorktreeRecord:
    path: Path
    branch_ref: str
    locked: bool


def _require_object_id(value: str, kind: str) -> str:
    oid = value.strip()
    if not _OID_RE.match(oid):
        raise GitRepositoryStateError(
            f"Git returned an invalid {kind} object id",
            details={"value": oid[:128]},
        )
    return oid


def _validate_branch_path_name(name: str) -> list[str]:
    """Reject names that cannot map to a safe worktree path.

    Git permits more characters than the panel should ever turn into a
    directory name. Components are restricted to a conservative ASCII set and
    the total length is bounded by the API schema.
    """
    if not isinstance(name, str):
        raise GitRefValidationError("Branch name must be a string", ref=str(name)[:128])
    if not name:
        raise GitRefValidationError("Branch name must not be empty")
    if len(name) > MAX_BRANCH_NAME_LENGTH:
        raise GitRefValidationError(
            f"Branch name must be at most {MAX_BRANCH_NAME_LENGTH} characters",
            ref=name[:128],
        )
    if name.startswith("/") or name.endswith("/"):
        raise GitRefValidationError("Branch name must not begin or end with '/'", ref=name[:128])

    segments = name.split("/")
    for segment in segments:
        if not segment:
            raise GitRefValidationError("Branch name contains an empty path segment", ref=name)
        if len(segment) > MAX_BRANCH_SEGMENT_LENGTH:
            raise GitRefValidationError("Branch name path segment is too long", ref=name)
        if not _SAFE_BRANCH_SEGMENT_RE.fullmatch(segment):
            raise GitRefValidationError(
                "Branch name cannot be mapped to a safe worktree path", ref=name
            )
        if segment.endswith(".lock"):
            raise GitRefValidationError("Branch name segment must not end with .lock", ref=name)
    return segments


def _normalized(path: str | os.PathLike[str]) -> str:
    return os.path.normpath(os.path.abspath(os.fspath(path)))


def _same_path(left: Path, right: Path) -> bool:
    return _normalized(left) == _normalized(right)


def _assert_no_overlap(server_root: Path, repo_dir: Path) -> None:
    try:
        common = os.path.commonpath([_normalized(server_root), _normalized(repo_dir)])
    except ValueError as exc:
        raise GitRepositoryStateError(
            "Repository path is not comparable with the server root",
            details={"path": str(repo_dir)[:256], "root": str(server_root)[:256]},
        ) from exc
    if common in (_normalized(server_root), _normalized(repo_dir)):
        raise GitRepositoryStateError(
            "Repository storage and server root must not overlap",
            details={"path": str(repo_dir)[:256], "root": str(server_root)[:256]},
        )


class GitBranchService:
    """Create, list, archive, and delete native Git branches and worktrees."""

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

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def list_branches(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
    ) -> list[GitBranchInfo]:
        """Read every local branch directly from Git, never from the DB."""
        root = validate_server_root(server_root)
        runner = self._open_repository(server_id, root)
        worktrees = self._worktrees_by_ref(runner)

        result = runner.run(
            "for-each-ref",
            "--sort=refname",
            "--format=%(refname)%09%(objectname)",
            "refs/heads",
        )
        branches: list[GitBranchInfo] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            ref, separator, oid = line.partition("\t")
            if not separator or not ref.startswith("refs/heads/"):
                raise GitRepositoryStateError(
                    "Git returned an unexpected branch reference",
                    details={"line": line[:256]},
                )
            name = ref[len("refs/heads/") :]
            worktree = worktrees.get(ref)
            branches.append(
                GitBranchInfo(
                    name=name,
                    sha=_require_object_id(oid, "commit"),
                    worktree_path=worktree.path if worktree else None,
                    worktree_locked=worktree.locked if worktree else False,
                )
            )
        return branches

    def get_branch(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        name: str,
    ) -> GitBranchInfo | None:
        """Return one local branch and validate its panel-owned worktree.

        Git remains authoritative for ref existence. A worktree registered
        outside ``<server_root>/.onx/worktrees/<branch>`` fails closed so the
        Files API can never serve an arbitrary host directory.
        """
        segments = _validate_branch_path_name(name)
        root = validate_server_root(server_root)
        branch = next(
            (info for info in self.list_branches(server_id, root) if info.name == name),
            None,
        )
        if branch is None or branch.worktree_path is None:
            return branch

        expected = self._worktree_path(root, segments)
        if not _same_path(branch.worktree_path, expected):
            raise GitRepositoryStateError(
                "Branch worktree is outside the panel worktree root",
                details={
                    "branch": name[:128],
                    "path": str(branch.worktree_path)[:256],
                },
            )
        if branch.worktree_path.is_symlink() or not branch.worktree_path.is_dir():
            raise GitRepositoryStateError(
                "Branch worktree is missing or is a symlink",
                details={
                    "branch": name[:128],
                    "path": str(branch.worktree_path)[:256],
                },
            )
        return branch

    def create_branch(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        name: str,
        start_point: str = MAIN_BRANCH,
        *,
        fencing_verifier: Callable[[], None] | None = None,
    ) -> GitBranchInfo:
        """Create a branch from an existing local branch and check it out."""
        segments = _validate_branch_path_name(name)
        _validate_branch_path_name(start_point)
        root = validate_server_root(server_root)
        if name == MAIN_BRANCH:
            raise ConflictError(
                "Branch 'main' already exists; it is created eagerly with the repository"
            )

        runner = self._open_repository(server_id, root)
        runner.validate_branch_name(name)
        runner.validate_branch_name(start_point)
        if fencing_verifier is not None:
            fencing_verifier()

        start_sha = self._resolve_branch(runner, start_point)
        if start_sha is None:
            raise NotFoundError(f"Start branch '{start_point}' not found")

        ref = f"refs/heads/{name}"
        if self._resolve_ref(runner, ref) is not None:
            raise ConflictError(f"Branch '{name}' already exists")

        worktrees = self._worktrees_by_ref(runner)
        target = self._worktree_path(root, segments)
        for worktree in worktrees.values():
            if _same_path(worktree.path, target):
                raise GitRepositoryStateError(
                    "A Git worktree already exists at the branch path",
                    details={"path": str(target)[:256]},
                )

        self._prepare_worktree_parents(root, segments, worktrees)
        if target.exists() or target.is_symlink():
            raise GitRepositoryStateError(
                "Branch worktree path already exists",
                details={"path": str(target)[:256]},
            )

        worktree_root = root / ".onx" / "worktrees"
        try:
            runner.run("worktree", "add", "-b", name, str(target), start_point)
        except Exception:
            self._rollback_created_branch(runner, ref, start_sha, target, worktree_root)
            raise

        try:
            sha = self._resolve_ref(runner, ref)
            if sha is None:
                raise GitRepositoryStateError(
                    "Git did not create the branch reference",
                    details={"branch": name[:128]},
                )
            worktree = self._worktrees_by_ref(runner).get(ref)
            if worktree is None or not _same_path(worktree.path, target):
                raise GitRepositoryStateError(
                    "Git did not register the branch worktree",
                    details={"path": str(target)[:256]},
                )
        except Exception:
            self._rollback_created_branch(runner, ref, start_sha, target, worktree_root)
            raise

        return GitBranchInfo(
            name=name,
            sha=sha,
            worktree_path=target,
            worktree_locked=worktree.locked,
        )

    def archive_branch(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        name: str,
        *,
        fencing_verifier: Callable[[], None] | None = None,
    ) -> GitBranchRemovalResult:
        """Retire a branch: remove its worktree, keep the ref and history."""
        _validate_branch_path_name(name)
        root = validate_server_root(server_root)
        if name == MAIN_BRANCH:
            raise BranchProtectedError("Branch 'main' is protected and cannot be archived")

        runner = self._open_repository(server_id, root)
        runner.validate_branch_name(name)
        if fencing_verifier is not None:
            fencing_verifier()
        ref = f"refs/heads/{name}"
        sha = self._resolve_ref(runner, ref)
        if sha is None:
            raise NotFoundError(f"Branch '{name}' not found")

        target = self._worktree_path(root, _validate_branch_path_name(name))
        worktrees = self._worktrees_by_ref(runner)
        worktree = worktrees.get(ref)
        removed = False
        if worktree is not None:
            if not _same_path(worktree.path, target):
                raise GitRepositoryStateError(
                    "Branch is checked out in an unexpected worktree",
                    details={"path": str(worktree.path)[:256]},
                )
            removed = self._remove_worktree(
                runner, ref, worktree, target, root / ".onx" / "worktrees"
            )

        if self._resolve_ref(runner, ref) != sha:
            raise GitRepositoryStateError(
                "Branch moved while it was being archived",
                details={"branch": name[:128]},
            )
        return GitBranchRemovalResult(
            name=name,
            sha=sha,
            worktree_removed=removed,
            ref_deleted=False,
        )

    def delete_branch(
        self,
        server_id: str,
        server_root: str | os.PathLike[str],
        name: str,
        *,
        fencing_verifier: Callable[[], None] | None = None,
    ) -> GitBranchRemovalResult:
        """Delete a fully merged branch after removing its clean worktree."""
        _validate_branch_path_name(name)
        root = validate_server_root(server_root)
        if name == MAIN_BRANCH:
            raise BranchProtectedError("Branch 'main' is protected and cannot be deleted")

        runner = self._open_repository(server_id, root)
        runner.validate_branch_name(name)
        if fencing_verifier is not None:
            fencing_verifier()
        ref = f"refs/heads/{name}"
        sha = self._resolve_ref(runner, ref)
        if sha is None:
            raise NotFoundError(f"Branch '{name}' not found")

        merged = runner.run(
            "merge-base",
            "--is-ancestor",
            ref,
            f"refs/heads/{MAIN_BRANCH}",
            check=False,
        )
        if merged.returncode == 1:
            raise GitRepositoryStateError(
                f"Branch '{name}' has commits that are not merged into main",
                details={"branch": name[:128]},
            )
        if merged.returncode != 0:
            raise GitRepositoryStateError(
                f"Unable to verify that branch '{name}' is merged into main",
                details={"branch": name[:128], "stderr": merged.stderr[:500]},
            )

        target = self._worktree_path(root, _validate_branch_path_name(name))
        worktrees = self._worktrees_by_ref(runner)
        worktree = worktrees.get(ref)
        removed = False
        if worktree is not None:
            if not _same_path(worktree.path, target):
                raise GitRepositoryStateError(
                    "Branch is checked out in an unexpected worktree",
                    details={"path": str(worktree.path)[:256]},
                )
            removed = self._remove_worktree(
                runner, ref, worktree, target, root / ".onx" / "worktrees"
            )

        if self._resolve_ref(runner, ref) != sha:
            raise GitRepositoryStateError(
                "Branch moved while it was being deleted",
                details={"branch": name[:128]},
            )

        deleted = runner.run("update-ref", "-d", ref, sha, check=False)
        if deleted.returncode != 0:
            raise GitRepositoryStateError(
                f"Git refused to delete branch '{name}'",
                details={"branch": name[:128], "stderr": deleted.stderr[:500]},
            )
        if self._resolve_ref(runner, ref) is not None:
            raise GitRepositoryStateError(
                "Branch reference still exists after deletion",
                details={"branch": name[:128]},
            )
        return GitBranchRemovalResult(
            name=name,
            sha=sha,
            worktree_removed=removed,
            ref_deleted=True,
        )

    # ------------------------------------------------------------------
    # Repository and branch helpers
    # ------------------------------------------------------------------

    def open_runner(self, server_id: str, server_root: str | os.PathLike[str]) -> GitRunner:
        """Return a hardened runner for an existing native repository."""
        root = validate_server_root(server_root)
        return self._open_repository(server_id, root)

    def _open_repository(self, server_id: str, server_root: Path) -> GitRunner:
        segment = validate_server_segment(server_id)
        repo_dir = self._layout.repo_dir(segment)
        _assert_no_overlap(server_root, repo_dir)

        repo_git = repo_dir / "repo.git"
        config_path = repo_dir / "gitconfig"
        if repo_git.is_symlink() or not repo_git.is_dir():
            raise GitRepositoryStateError(
                "Native Git repository does not exist for this server",
                details={"path": str(repo_git)[:256]},
            )
        if not repo_dir.is_dir() or repo_dir.is_symlink():
            raise GitRepositoryStateError(
                "Repository storage directory is invalid",
                details={"path": str(repo_dir)[:256]},
            )

        runner = GitRunner(
            repo_path=repo_git,
            config_path=config_path,
            git_executable=self._git_executable,
            timeout=self._timeout,
        )

        bare = runner.run("rev-parse", "--is-bare-repository", check=False)
        if bare.returncode != 0 or bare.stdout.strip() != "true":
            raise GitRepositoryStateError(
                "Repository is not a bare Git repository",
                details={"path": str(repo_git)[:256]},
            )
        if self._resolve_branch(runner, MAIN_BRANCH) is None:
            raise GitRepositoryStateError(
                "Repository has no main branch",
                details={"path": str(repo_git)[:256]},
            )
        return runner

    @staticmethod
    def _resolve_ref(runner: GitRunner, ref: str) -> str | None:
        result = runner.run(
            "rev-parse",
            "--verify",
            "--quiet",
            f"{ref}^{{commit}}",
            check=False,
        )
        if result.returncode == 0:
            return _require_object_id(result.stdout, "commit")
        if result.returncode == 1:
            return None
        raise GitRepositoryStateError(
            "Unable to resolve Git reference",
            details={"ref": ref[:256], "stderr": result.stderr[:500]},
        )

    def _resolve_branch(self, runner: GitRunner, name: str) -> str | None:
        return self._resolve_ref(runner, f"refs/heads/{name}")

    @staticmethod
    def _parse_worktrees(runner: GitRunner) -> list[dict[str, str | bool]]:
        result = runner.run("worktree", "list", "--porcelain", "-z")
        records: list[dict[str, str | bool]] = []
        current: dict[str, str | bool] = {}
        for token in result.stdout.split("\x00"):
            if token == "":
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = token.partition(" ")
            if key == "worktree":
                current["path"] = value
            elif key == "branch":
                current["branch"] = value
            elif key == "locked":
                current["locked"] = True
        if current:
            records.append(current)
        return records

    def _worktrees_by_ref(self, runner: GitRunner) -> dict[str, _WorktreeRecord]:
        worktrees: dict[str, _WorktreeRecord] = {}
        for record in self._parse_worktrees(runner):
            branch_ref = record.get("branch")
            if not isinstance(branch_ref, str) or not branch_ref:
                continue
            path_value = record.get("path")
            if not isinstance(path_value, str) or not path_value:
                raise GitRepositoryStateError("Git returned a worktree without a path")
            if not os.path.isabs(path_value):
                raise GitRepositoryStateError(
                    "Git returned a non-absolute worktree path",
                    details={"path": path_value[:256]},
                )
            if branch_ref in worktrees:
                raise GitRepositoryStateError(
                    "Git reported the same branch in multiple worktrees",
                    details={"branch": branch_ref[:128]},
                )
            worktrees[branch_ref] = _WorktreeRecord(
                path=Path(path_value),
                branch_ref=branch_ref,
                locked=bool(record.get("locked")),
            )
        return worktrees

    @staticmethod
    def _worktree_path(server_root: Path, segments: list[str]) -> Path:
        base = server_root / ".onx" / "worktrees"
        target = base.joinpath(*segments)
        base_norm = _normalized(base)
        target_norm = _normalized(target)
        try:
            common = os.path.commonpath([base_norm, target_norm])
        except ValueError as exc:
            raise GitRepositoryStateError(
                "Branch worktree path is not comparable with the worktree root",
                details={"path": str(target)[:256]},
            ) from exc
        if common != base_norm or target_norm == base_norm:
            raise GitRepositoryStateError(
                "Branch worktree path escapes the worktree root",
                details={"path": str(target)[:256]},
            )
        return target

    def _prepare_worktree_parents(
        self,
        server_root: Path,
        segments: list[str],
        worktrees: dict[str, _WorktreeRecord],
    ) -> None:
        base = server_root / ".onx" / "worktrees"
        ensure_private_dir(server_root / ".onx")
        ensure_private_dir(base)

        registered = {_normalized(worktree.path) for worktree in worktrees.values()}
        current = base
        for segment in segments[:-1]:
            current = current / segment
            if _normalized(current) in registered:
                raise GitRepositoryStateError(
                    "Branch name collides with an existing worktree",
                    details={"path": str(current)[:256]},
                )
            ensure_private_dir(current)
            try:
                non_empty = any(current.iterdir())
            except OSError as exc:
                raise GitRepositoryStateError(
                    "Unable to inspect the branch worktree parent",
                    details={"path": str(current)[:256], "reason": str(exc)[:256]},
                ) from exc
            if non_empty:
                raise GitRepositoryStateError(
                    "Branch name collides with a non-empty worktree directory",
                    details={"path": str(current)[:256]},
                )

    def _remove_worktree(
        self,
        runner: GitRunner,
        ref: str,
        worktree: _WorktreeRecord,
        target: Path,
        worktree_root: Path,
    ) -> bool:
        if worktree.locked:
            raise GitRepositoryStateError(
                "Branch worktree is locked and cannot be removed",
                details={"path": str(target)[:256]},
            )
        if target.is_symlink():
            raise GitRepositoryStateError(
                "Branch worktree path must not be a symlink",
                details={"path": str(target)[:256]},
            )
        if not target.exists():
            runner.run("worktree", "prune")
            if self._worktrees_by_ref(runner).get(ref) is not None:
                raise GitRepositoryStateError(
                    "Git still registers a missing branch worktree",
                    details={"path": str(target)[:256]},
                )
            return False
        if not target.is_dir():
            raise GitRepositoryStateError(
                "Branch worktree path is not a directory",
                details={"path": str(target)[:256]},
            )
        if not _same_path(worktree.path, target):
            raise GitRepositoryStateError(
                "Branch worktree path does not match the branch name",
                details={"path": str(worktree.path)[:256]},
            )

        status = runner.run(
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--ignored=matching",
            cwd=target,
            check=False,
        )
        if status.returncode != 0:
            raise GitRepositoryStateError(
                "Unable to inspect the branch worktree",
                details={"path": str(target)[:256], "stderr": status.stderr[:500]},
            )
        if status.stdout.strip():
            raise GitRepositoryStateError(
                "Branch worktree has uncommitted changes; commit or discard them first",
                details={"path": str(target)[:256], "status": status.stdout[:500]},
            )

        runner.run("worktree", "remove", str(target))
        if target.exists() or target.is_symlink():
            raise GitRepositoryStateError(
                "Git did not remove the branch worktree",
                details={"path": str(target)[:256]},
            )
        self._prune_empty_parents(target.parent, worktree_root)
        return True

    @staticmethod
    def _prune_empty_parents(start: Path, stop: Path) -> None:
        current = start
        stop_norm = _normalized(stop)
        while _normalized(current) != stop_norm:
            parent = current.parent
            if parent == current:
                return
            try:
                os.rmdir(current)
            except OSError:
                return
            current = parent

    def _rollback_created_branch(
        self,
        runner: GitRunner,
        ref: str,
        expected_sha: str,
        target: Path,
        worktree_root: Path,
    ) -> None:
        """Best-effort cleanup after a failed create; never touch other refs."""
        with suppress(Exception):
            runner.run("worktree", "remove", str(target), check=False)
        with suppress(Exception):
            runner.run("update-ref", "-d", ref, expected_sha, check=False)
        with suppress(Exception):
            self._prune_empty_parents(target.parent, worktree_root)


__all__ = [
    "GitBranchInfo",
    "GitBranchRemovalResult",
    "GitBranchService",
    "MAX_BRANCH_NAME_LENGTH",
    "MAX_BRANCH_SEGMENT_LENGTH",
]
