from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.allowlist import classify, validate_canonical_relpath
from app.core.exceptions import (
    ConflictError,
    DirtyWorktreeError,
    GitCommandError,
    GitTimeoutError,
    MergeConflictError,
    NotFoundError,
    OversizedGitTrackedFileError,
)
from app.core.host_state import HostStateLayout
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    MAX_GIT_TRACKED_FILE_BYTES,
    PANEL_GITATTRIBUTES_CONTENT,
)
from app.modules.versioning.infrastructure.git_runner import GitRunner
from app.modules.versioning.infrastructure.git_save_commit import (
    _assert_no_case_collisions,
    _find_conflict_markers,
)
from app.modules.versioning.infrastructure.merge_engine import (
    SET_MERGEABLE_ARRAY_KEYS,
    merge_class_b_file,
    merge_lockfile_bytes,
)
from app.modules.versioning.infrastructure.secret_scanner import (
    assert_no_secrets,
    redact_conflict_value,
)


@dataclass(frozen=True)
class GitMergeResult:
    commit_id: str
    target_branch_name: str
    parent_commit_ids: tuple[str, str]
    base_commit_id: str | None
    changed_files: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class GitMergeService:
    def __init__(
        self, layout: HostStateLayout, *, git_executable: str = "git", timeout: float = 60.0
    ) -> None:
        self._layout = layout
        self._git_executable = git_executable
        self._timeout = timeout

    def _open_runner(self, server_id: str) -> GitRunner:
        segment = server_id
        repo_dir = self._layout.repo_dir(segment)
        repo_git = repo_dir / "repo.git"
        config_path = repo_dir / "gitconfig"
        return GitRunner(
            repo_path=repo_git,
            config_path=config_path,
            git_executable=self._git_executable,
            timeout=self._timeout,
        )

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: str | Path,
        env: dict[str, str] | None,
        input_bytes: bytes | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a Git subcommand with the service timeout and translate timeouts."""
        try:
            return subprocess.run(
                args,
                cwd=str(cwd),
                env=env,
                input=input_bytes,
                capture_output=True,
                timeout=self._timeout,
                check=check,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr
            if isinstance(stderr, bytes):
                stderr_text = stderr.decode("utf-8", "replace")
            else:
                stderr_text = stderr or ""
            raise GitTimeoutError(
                f"Git command timed out after {self._timeout:g}s",
                command=" ".join(args[:2]),
                timeout_seconds=self._timeout,
                stderr=stderr_text,
            ) from exc

    def merge(
        self,
        server_id,
        server_root,
        target_branch_name,
        parent_commit_ids,
        message,
        *,
        dynamic_class_c=None,
        set_mergeable_array_keys=SET_MERGEABLE_ARRAY_KEYS,
    ):
        server_root = Path(os.path.abspath(str(server_root)))
        runner = self._open_runner(server_id)
        branch_service = GitBranchService(
            self._layout, git_executable=self._git_executable, timeout=self._timeout
        )

        dynamic_class_c = set(dynamic_class_c or set())
        # load from service? caller passes; also merge with list_paths not available here (no session). Use passed.  # noqa: E501

        # Pre-merge clean worktree gate
        branches = branch_service.list_branches(server_id, server_root)
        worktrees_by_branch = {b.name: b for b in branches}
        target_wt = None
        if (
            target_branch_name in worktrees_by_branch
            and worktrees_by_branch[target_branch_name].worktree_path
        ):
            target_wt = worktrees_by_branch[target_branch_name].worktree_path
        # source worktree if branch

        # resolve parent refs
        def resolve_ref(ref):
            r = runner.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
            if r.returncode == 0:
                return r.stdout.strip()
            return None

        # parent_commit_ids[0] target, [1] source
        if len(parent_commit_ids) < 2:
            raise ConflictError("merge requires >=2 parents")
        # resolve ours_sha
        ours_sha = runner.run(
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{target_branch_name}^{{commit}}",
            check=False,
        )
        if ours_sha.returncode != 0:
            raise NotFoundError(f"Branch '{target_branch_name}' not found")
        ours_sha = ours_sha.stdout.strip()

        p0 = parent_commit_ids[0]
        # resolve p0 to commit
        p0_sha = None
        if p0 == target_branch_name:
            p0_sha = ours_sha
        else:
            # try as branch
            br = runner.run(
                "rev-parse", "--verify", "--quiet", f"refs/heads/{p0}^{{commit}}", check=False
            )
            if br.returncode == 0:  # noqa: SIM108
                p0_sha = br.stdout.strip()
            else:
                p0_sha = resolve_ref(p0)
        if p0_sha is None:
            raise NotFoundError(f"Parent commit '{p0}' not found on server '{server_id}'")
        if p0_sha != ours_sha:  # noqa: SIM102
            # maybe p0 is prefix
            if not ours_sha.startswith(p0_sha) and p0_sha != ours_sha:
                raise ConflictError(
                    f"Target branch '{target_branch_name}' head moved from '{p0}' to '{ours_sha}'"
                )

        p1 = parent_commit_ids[1]
        theirs_sha = None
        br = runner.run(
            "rev-parse", "--verify", "--quiet", f"refs/heads/{p1}^{{commit}}", check=False
        )
        if br.returncode == 0:  # noqa: SIM108
            theirs_sha = br.stdout.strip()
        else:
            theirs_sha = resolve_ref(p1)
        if theirs_sha is None:
            raise NotFoundError(f"Parent commit '{p1}' not found on server '{server_id}'")

        # source worktree if branch with worktree
        source_wt = None
        # check if p1 is a branch name
        if (  # noqa: SIM102
            runner.run(
                "rev-parse", "--verify", "--quiet", f"refs/heads/{p1}", check=False
            ).returncode
            == 0
        ):
            if p1 in worktrees_by_branch and worktrees_by_branch[p1].worktree_path:
                source_wt = worktrees_by_branch[p1].worktree_path

        # clean worktree gate
        def dirty_paths_in(wt):
            if wt is None:
                return []
            r = runner.run(
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--no-renames",
                cwd=wt,
            )
            out = []
            # parse NUL-separated entries
            entries = r.stdout.split("\x00")
            for e in entries:
                if not e:
                    continue
                # format: XY path
                if len(e) < 4:
                    continue
                status = e[:2]
                path = e[3:]
                from app.core.allowlist import classify as _cls

                cls = _cls(path, dynamic_class_c=frozenset(dynamic_class_c))
                tracked_dirty = status.strip() != "" and status != "??"
                untracked = status == "??"
                if tracked_dirty:
                    out.append(path)
                    continue
                if untracked:
                    if cls in ("C", "E"):
                        continue
                    out.append(path)
            return out

        for branch_name, wt in [
            (target_branch_name, target_wt),
            (p1 if source_wt else None, source_wt),
        ]:
            if wt is None:
                continue
            dp = dirty_paths_in(wt)
            if dp:
                raise DirtyWorktreeError(
                    branch=branch_name or "",
                    details={"branch": branch_name or "", "dirty_paths": dp[:20]},
                )

        # merge base
        mb = runner.run("merge-base", ours_sha, theirs_sha, check=False)
        base_sha = mb.stdout.strip() if mb.returncode == 0 else None

        # read trees
        def read_tree(sha):
            if sha is None:
                return {}
            r = runner.run("ls-tree", "-r", "-z", sha, check=False)
            result = {}
            for entry in r.stdout.split("\x00"):
                if not entry:
                    continue
                # format: <mode> SP <type> SP <oid>\t<file>
                meta, _, path = entry.partition("\t")
                parts = meta.split()
                if len(parts) < 3:
                    continue
                mode, oid = parts[0], parts[2]
                result[path] = (mode, oid)
            return result

        base_tree = read_tree(base_sha)
        ours_tree = read_tree(ours_sha)
        theirs_tree = read_tree(theirs_sha)

        all_paths = set(base_tree) | set(ours_tree) | set(theirs_tree)

        def _hardened_env(extra=None):
            env = runner._build_env() if hasattr(runner, "_build_env") else {}
            env = dict(env)
            if extra:
                env.update(extra)
            return env

        def cat_blob(oid):
            if oid is None:
                return None
            env = _hardened_env()
            proc = self._run_git(
                [self._git_executable, "cat-file", "blob", oid],
                cwd=self._layout.repo_dir(server_id) / "repo.git",
                env=env,
            )
            if proc.returncode != 0:
                raise GitCommandError("git cat-file failed", command="cat-file", returncode=proc.returncode, stderr=proc.stderr.decode("utf-8","replace"))  # noqa: E501
            return proc.stdout

        def oid_of(tree, path):
            return tree.get(path, (None, None))[1]

        conflicts = []
        warnings = []
        merged_blobs = {}  # path -> bytes or None
        # classify dynamic
        # We need dynamic_class_c set passed; also could load? no session. Use passed.

        for relpath in sorted(all_paths):
            validate_canonical_relpath(relpath)
            if relpath == ".gitattributes":
                merged_blobs[relpath] = PANEL_GITATTRIBUTES_CONTENT
                continue
            cls = classify(relpath, dynamic_class_c=frozenset(dynamic_class_c))
            if cls in ("C", "E", "QUARANTINE", "REJECT-PATH"):
                if cls == "C" or relpath in dynamic_class_c:
                    warnings.append(
                        f"'{relpath}' is classified as Class C and was excluded from the merged Git tree"  # noqa: E501
                    )
                continue

            base_oid = oid_of(base_tree, relpath)
            ours_oid = oid_of(ours_tree, relpath)
            theirs_oid = oid_of(theirs_tree, relpath)
            base_bytes = cat_blob(base_oid) if base_oid else (b"" if base_oid is not None else None)
            # if path absent, oid None -> None bytes
            if base_oid is None and relpath in base_tree:
                base_bytes = b""
            if relpath not in base_tree:
                base_bytes = None
            ours_bytes = (
                cat_blob(ours_oid) if ours_oid else (b"" if (ours_oid is not None) else None)
            )
            if ours_oid is None and relpath not in ours_tree:
                ours_bytes = None
            theirs_bytes = (
                cat_blob(theirs_oid) if theirs_oid else (b"" if (theirs_oid is not None) else None)
            )
            if theirs_oid is None and relpath not in theirs_tree:
                theirs_bytes = None

            if relpath == "onx-jars.lock.json":
                outcome = merge_lockfile_bytes(relpath, base_bytes, ours_bytes, theirs_bytes)
            elif cls == "B":
                outcome = merge_class_b_file(
                    relpath,
                    base_bytes,
                    ours_bytes,
                    theirs_bytes,
                    set_mergeable_array_keys=set_mergeable_array_keys,
                )
            else:
                # code-class / other tracked: use git merge-file fallback
                # fast paths
                if ours_bytes == theirs_bytes:
                    outcome_content = ours_bytes
                    outcome = None
                elif base_bytes is not None and ours_bytes == base_bytes:
                    outcome_content = theirs_bytes
                    outcome = None
                elif base_bytes is not None and theirs_bytes == base_bytes:
                    outcome_content = ours_bytes
                    outcome = None
                else:
                    # use git merge-file
                    outcome = None
                    # write temp files
                    with tempfile.TemporaryDirectory() as td:
                        base_p = Path(td) / "base"
                        ours_p = Path(td) / "ours"
                        theirs_p = Path(td) / "theirs"
                        base_p.write_bytes(base_bytes or b"")
                        ours_p.write_bytes(ours_bytes or b"")
                        theirs_p.write_bytes(theirs_bytes or b"")
                        r = runner.run(
                            "merge-file",
                            "-p",
                            "-L",
                            "ours",
                            "-L",
                            "base",
                            "-L",
                            "theirs",
                            str(ours_p),
                            str(base_p),
                            str(theirs_p),
                            check=False,
                        )
                        if r.returncode == 0:
                            outcome_content = r.stdout.encode("utf-8", errors="surrogateescape")
                            outcome = None
                        else:
                            # conflict
                            conflicts.append(
                                {
                                    "path": relpath,
                                    "key_path": "",
                                    "reason": "text-hunk-conflict",
                                    "base": redact_conflict_value(
                                        relpath,
                                        "",
                                        base_bytes.decode("utf-8", "replace")
                                        if base_bytes
                                        else None,
                                    ),
                                    "ours": redact_conflict_value(
                                        relpath,
                                        "",
                                        ours_bytes.decode("utf-8", "replace")
                                        if ours_bytes
                                        else None,
                                    ),
                                    "theirs": redact_conflict_value(
                                        relpath,
                                        "",
                                        theirs_bytes.decode("utf-8", "replace")
                                        if theirs_bytes
                                        else None,
                                    ),
                                }
                            )
                            outcome_content = None
                            outcome = "conflict"
                    if outcome == "conflict":
                        continue
                    if outcome is None and outcome_content is not None:
                        merged_blobs[relpath] = outcome_content
                        continue
                    continue
                if outcome is None:
                    # fast path handled; None means the path is deleted on both sides
                    if outcome_content is not None:
                        merged_blobs[relpath] = outcome_content
                    continue

            if outcome is not None:
                if outcome.conflicts:
                    for c in outcome.conflicts:
                        conflicts.append(c.to_dict() if hasattr(c, "to_dict") else c)
                    for w in getattr(outcome, "warnings", ()):
                        warnings.append(w)
                    continue
                # enforce checks for class B
                if cls == "B" or relpath == "onx-jars.lock.json":
                    content = outcome.content
                    if content is not None:
                        if len(content) > MAX_GIT_TRACKED_FILE_BYTES:
                            raise OversizedGitTrackedFileError(
                                relpath, len(content), MAX_GIT_TRACKED_FILE_BYTES
                            )
                        if _find_conflict_markers(content):
                            raise ConflictError("conflict markers found")
                        assert_no_secrets(relpath, content)
                if outcome.content is None:
                    # deleted
                    pass
                else:
                    if outcome.content is not None:
                        merged_blobs[relpath] = outcome.content
                for w in outcome.warnings:
                    warnings.append(w)

        if conflicts:
            raise MergeConflictError(conflicts=conflicts, warnings=warnings)

        # case collision gate
        _assert_no_case_collisions(set(merged_blobs.keys()), set(merged_blobs.keys()))  # noqa: E501

        # stage into temp index
        repo_git = self._layout.repo_dir(server_id) / "repo.git"
        index_path = repo_git / f".merge-index-{uuid.uuid4().hex}"
        env = runner._build_env()
        env["GIT_INDEX_FILE"] = str(index_path)
        try:
            # Seed the temporary index from the target tree, then apply the merged blobs.
            self._run_git(
                [self._git_executable, "read-tree", ours_sha],
                cwd=repo_git,
                env=env,
                check=True,
            )
            # Remove paths deleted in the merged tree.
            for path in list(ours_tree.keys()):
                if path not in merged_blobs and path != ".gitattributes":
                    self._run_git(
                        [self._git_executable, "rm", "--cached", "--ignore-unmatch", "--", path],
                        cwd=repo_git,
                        env=env,
                    )
            for path, content in merged_blobs.items():
                p = self._run_git(
                    [self._git_executable, "hash-object", "-w", "--no-filters", "--stdin"],
                    cwd=repo_git,
                    env=env,
                    input_bytes=content,
                )
                if p.returncode != 0:
                    raise GitCommandError(
                        "git hash-object failed",
                        command="hash-object",
                        returncode=p.returncode,
                        stderr=p.stderr.decode("utf-8", "replace"),
                    )
                oid = p.stdout.decode().strip()
                if path in ours_tree:
                    mode = ours_tree[path][0]
                elif path in theirs_tree:
                    mode = theirs_tree[path][0]
                else:
                    mode = "100644"
                self._run_git(
                    [
                        self._git_executable,
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"{mode},{oid},{path}",
                    ],
                    cwd=repo_git,
                    env=env,
                    check=True,
                )
            # write tree
            wt = self._run_git(
                [self._git_executable, "write-tree"],
                cwd=repo_git,
                env=env,
                check=True,
            )
            tree_oid = wt.stdout.decode().strip()

            # commit-tree
            ct = self._run_git(
                [
                    self._git_executable,
                    "commit-tree",
                    tree_oid,
                    "-p",
                    ours_sha,
                    "-p",
                    theirs_sha,
                    "-m",
                    message,
                ],
                cwd=repo_git,
                env={
                    **env,
                    "GIT_AUTHOR_NAME": "ONX Manager",
                    "GIT_AUTHOR_EMAIL": "onx-manager@localhost",
                    "GIT_COMMITTER_NAME": "ONX Manager",
                    "GIT_COMMITTER_EMAIL": "onx-manager@localhost",
                },
                check=True,
            )
            new_commit = ct.stdout.decode().strip()

            # update-ref CAS
            ur = self._run_git(
                [
                    self._git_executable,
                    "update-ref",
                    f"refs/heads/{target_branch_name}",
                    new_commit,
                    ours_sha,
                ],
                cwd=repo_git,
                env=env,
            )
            if ur.returncode != 0:
                raise ConflictError("Target branch head moved concurrently during merge")

            # sync worktree
            if target_wt is not None and target_wt.exists():
                self._run_git(
                    [self._git_executable, "reset", "--hard", new_commit],
                    cwd=target_wt,
                    env=runner._build_env(),
                    check=True,
                )
                # verify HEAD
                hv = self._run_git(
                    [self._git_executable, "rev-parse", "HEAD"],
                    cwd=target_wt,
                    env=runner._build_env(),
                )
                if hv.stdout.decode().strip() != new_commit:
                    raise ConflictError("Worktree sync failed")

            changed_paths = []
            for pth, content in merged_blobs.items():
                if pth not in ours_tree:
                    changed_paths.append(pth)
                else:
                    old_oid = ours_tree[pth][1]
                    old_bytes = cat_blob(old_oid) if old_oid else None
                    if old_bytes != content:
                        changed_paths.append(pth)
            # deletions
            for pth in ours_tree:
                if pth not in merged_blobs and pth != ".gitattributes":
                    changed_paths.append(pth)
            return GitMergeResult(
                commit_id=new_commit,
                target_branch_name=target_branch_name,
                parent_commit_ids=(ours_sha, theirs_sha),
                base_commit_id=base_sha,
                changed_files=tuple(sorted(set(changed_paths))),
                warnings=tuple(warnings),
            )
        finally:
            try:  # noqa: SIM105
                index_path.unlink(missing_ok=True)
            except Exception:
                pass
