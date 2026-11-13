"""Hardened native Git invocation for the Advanced-mode repository engine.

Normative contract: ``SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02`` P2 / D-G,
amended by OD-v8.4-7. Git is never invoked through a shell, every command
receives the exact hardening overrides, and the global/system Git configuration
is replaced by a panel-owned minimal file containing one ``safe.directory``.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.allowlist import SymlinkEscapeError
from app.core.exceptions import (
    GitCommandError,
    GitConfigurationError,
    GitError,
    GitRefValidationError,
    GitRemoteUrlError,
    GitTimeoutError,
    GitUnavailableError,
    GitUnsupportedPlatformError,
)
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_private

# Exact per-command overrides required before every Git subcommand by OD-v8.4-7.
GIT_HARDENING_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("protocol.allow", "user"),
    ("protocol.file.allow", "never"),
    ("protocol.ext.allow", "never"),
    ("core.symlinks", "false"),
    ("core.attributesFile", "/dev/null"),
    ("filter.lfs.smudge", ""),
    ("filter.lfs.process", ""),
    ("filter.lfs.clean", ""),
)

_GITHUB_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_GITHUB_REPO = r"[A-Za-z0-9._-]{1,100}"
_HTTPS_REMOTE_RE = re.compile(rf"\Ahttps://github\.com/{_GITHUB_OWNER}/{_GITHUB_REPO}(?:\.git)?\Z")
_SSH_REMOTE_RE = re.compile(rf"\Assh://git@github\.com/{_GITHUB_OWNER}/{_GITHUB_REPO}(?:\.git)?\Z")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_REMOTE_TOKENS = ("ext::", "fd::", "file::")

_CONFIG_HEADER = "# ONX Manager isolated Git configuration (generated; do not edit).\n"


@dataclass(frozen=True)
class GitResult:
    """Captured result of one hardened Git invocation."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _quote_config_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _validate_absolute_path(
    value: str | os.PathLike[str],
    *,
    field: str,
    error_type: type[GitError],
) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw:
        raise error_type(f"{field} must be a non-empty path")
    if _CONTROL_RE.search(raw):
        raise error_type(f"{field} must not contain control characters")
    path = Path(raw)
    if not path.is_absolute():
        raise error_type(f"{field} must be an absolute path")
    return Path(os.path.abspath(raw))


def validate_remote_url(url: str) -> str:
    """Validate a GitHub remote URL against the exact D-G approved forms.

    Only ``https://github.com/<owner>/<repo>(.git)?`` and
    ``ssh://git@github.com/<owner>/<repo>(.git)?`` are accepted. Protocol
    tokens, userinfo, whitespace, control characters, and extra path segments
    are rejected.
    """
    if not isinstance(url, str):
        raise GitRemoteUrlError("Remote URL must be a string", url=str(url)[:256])
    if not url:
        raise GitRemoteUrlError("Remote URL must not be empty")
    if len(url) > 2048:
        raise GitRemoteUrlError("Remote URL is too long", url=url[:256])
    if _CONTROL_RE.search(url) or any(ch.isspace() for ch in url):
        raise GitRemoteUrlError(
            "Remote URL must not contain whitespace or control characters", url=url
        )

    lowered = url.lower()
    for token in _FORBIDDEN_REMOTE_TOKENS:
        if token in lowered:
            raise GitRemoteUrlError(
                f"Remote URL must not contain the {token!r} protocol token", url=url
            )

    if not (_HTTPS_REMOTE_RE.match(url) or _SSH_REMOTE_RE.match(url)):
        raise GitRemoteUrlError(
            "Remote URL must be https://github.com/<owner>/<repo> or "
            "ssh://git@github.com/<owner>/<repo>",
            url=url,
        )

    repo = url.rsplit("/", 1)[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo in ("", ".", ".."):
        raise GitRemoteUrlError("Remote URL repository name is invalid", url=url)
    return url


class GitRunner:
    """Run Git with the D-G hardening contract and an isolated configuration."""

    def __init__(
        self,
        *,
        repo_path: str | os.PathLike[str],
        config_path: str | os.PathLike[str],
        git_executable: str = "git",
        timeout: float = 60.0,
        env: Mapping[str, str] | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._platform_name = platform_name or os.name
        if self._platform_name != "posix":
            raise GitUnsupportedPlatformError(
                "Native Git repository operations require a POSIX host",
                details={"platform": self._platform_name},
            )
        if not isinstance(git_executable, str) or not git_executable or "\x00" in git_executable:
            raise GitConfigurationError("git_executable must be a non-empty string")
        if timeout <= 0:
            raise GitConfigurationError("Git timeout must be positive")

        self._repo_path = _validate_absolute_path(
            repo_path, field="repo_path", error_type=GitConfigurationError
        )
        self._config_path = _validate_absolute_path(
            config_path, field="config_path", error_type=GitConfigurationError
        )
        if self._repo_path == self._config_path:
            raise GitConfigurationError("repo_path and config_path must differ")
        if not self._config_path.parent.is_dir():
            raise GitConfigurationError(
                "Git config parent directory does not exist",
                details={"config_path": str(self._config_path)[:256]},
            )

        self._git_executable = git_executable
        self._timeout = float(timeout)
        self._base_env = dict(os.environ if env is None else env)

    @property
    def repo_path(self) -> Path:
        return self._repo_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def git_executable(self) -> str:
        return self._git_executable

    def _render_config(self) -> str:
        return (
            _CONFIG_HEADER
            + "[user]\n"
            + "\tname = ONX Manager\n"
            + "\temail = onx-manager@localhost\n"
            + "[init]\n"
            + "\tdefaultBranch = main\n"
            + "[core]\n"
            + "\tfilemode = true\n"
            + "[commit]\n"
            + "\tgpgsign = false\n"
            + "[tag]\n"
            + "\tgpgsign = false\n"
            + "[safe]\n"
            + f"\tdirectory = {_quote_config_value(str(self._repo_path))}\n"
        )

    def _ensure_config(self) -> None:
        if self._config_path.is_symlink():
            raise GitConfigurationError(
                "Git config path must not be a symlink",
                details={"config_path": str(self._config_path)[:256]},
            )

        expected = self._render_config()
        try:
            current = self._config_path.read_text(encoding="utf-8")
            current_mode = stat.S_IMODE(self._config_path.stat().st_mode)
        except FileNotFoundError:
            current = None
            current_mode = None
        except OSError as exc:
            raise GitConfigurationError(
                f"Failed to read isolated Git config: {exc}",
                details={"config_path": str(self._config_path)[:256]},
            ) from exc

        if current == expected and current_mode == 0o600:
            return

        try:
            atomic_write_private(self._config_path, expected, mode=0o600)
        except (OSError, SymlinkEscapeError) as exc:
            raise GitConfigurationError(
                f"Failed to write isolated Git config: {exc}",
                details={"config_path": str(self._config_path)[:256]},
            ) from exc

    def _build_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in self._base_env.items()
            if not key.startswith("GIT_") and key != "SSH_ASKPASS"
        }
        env.update(
            {
                "GIT_CONFIG_GLOBAL": str(self._config_path),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_PAGER": "cat",
                "GIT_EDITOR": "true",
                "LC_ALL": "C",
            }
        )
        return env

    @staticmethod
    def _override_args() -> list[str]:
        args: list[str] = []
        for key, value in GIT_HARDENING_OVERRIDES:
            args.extend(("-c", f"{key}={value}"))
        return args

    def run(
        self,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
        input_text: str | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> GitResult:
        """Run one Git subcommand with the hardened contract.

        ``args`` must start with the subcommand (for example ``"status"``),
        never a leading-dash option. The caller's ``cwd`` defaults to the
        repository path. Standard input is closed unless ``input_text`` is
        supplied, so an accidental interactive prompt fails instead of hanging.
        """
        if not args:
            raise GitError("At least one Git subcommand is required")
        for arg in args:
            if not isinstance(arg, str):
                raise GitError("Git arguments must be strings")
            if "\x00" in arg:
                raise GitError("Git arguments must not contain NUL bytes")
        if args[0].startswith("-"):
            raise GitError("Git subcommand must not begin with '-'")
        if input_text is not None and not isinstance(input_text, str):
            raise GitError("input_text must be a string")

        run_timeout = self._timeout if timeout is None else float(timeout)
        if run_timeout <= 0:
            raise GitError("Git timeout must be positive")

        self._ensure_config()

        if cwd is None:
            workdir = self._repo_path
        else:
            workdir = _validate_absolute_path(cwd, field="cwd", error_type=GitCommandError)
        if not workdir.is_dir():
            raise GitCommandError(
                "Git working directory does not exist",
                details={"cwd": str(workdir)[:256]},
            )

        argv = [self._git_executable, *self._override_args(), *args]
        kwargs: dict[str, Any] = {
            "cwd": str(workdir),
            "env": self._build_env(),
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": run_timeout,
            "shell": False,
            "check": False,
        }

        try:
            if input_text is None:
                completed = subprocess.run(argv, stdin=subprocess.DEVNULL, **kwargs)
            else:
                completed = subprocess.run(argv, input=input_text, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise GitTimeoutError(
                f"Git command timed out after {run_timeout:g}s",
                command=" ".join(args[:2]),
                timeout_seconds=run_timeout,
                stderr=_coerce_output(exc.stderr),
            ) from exc
        except FileNotFoundError as exc:
            raise GitUnavailableError(
                "Git executable could not be executed",
                details={
                    "executable": self._git_executable[:128],
                    "reason": str(exc)[:256],
                },
            ) from exc
        except OSError as exc:
            raise GitCommandError(
                f"Git invocation failed: {exc}",
                command=" ".join(args[:2]),
                details={"errno": getattr(exc, "errno", None)},
            ) from exc

        result = GitResult(
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if check and completed.returncode != 0:
            raise GitCommandError(
                f"Git command failed with exit code {completed.returncode}",
                command=" ".join(args[:2]),
                returncode=completed.returncode,
                stderr=result.stderr,
            )
        return result

    def validate_branch_name(self, name: str) -> str:
        """Validate a short branch name through ``git check-ref-format --branch``."""
        if not isinstance(name, str):
            raise GitRefValidationError("Branch name must be a string", ref=str(name)[:128])
        if not name:
            raise GitRefValidationError("Branch name must not be empty")
        if name.startswith("-"):
            raise GitRefValidationError("Branch name must not begin with '-'", ref=name)
        if name.startswith("@") or "@{" in name:
            raise GitRefValidationError("Reflog expressions are not valid branch names", ref=name)
        if name.startswith("refs/"):
            raise GitRefValidationError(
                "Branch name must be a short name, not a full ref", ref=name
            )
        if _CONTROL_RE.search(name) or any(ch.isspace() for ch in name):
            raise GitRefValidationError(
                "Branch name must not contain whitespace or control characters", ref=name
            )

        result = self.run(
            "check-ref-format",
            "--branch",
            name,
            check=False,
            cwd=self._config_path.parent,
        )
        if result.returncode != 0:
            raise GitRefValidationError(
                "Branch name failed git check-ref-format --branch",
                ref=name,
                details={"stderr": result.stderr[:500]},
            )
        return name


__all__ = [
    "GIT_HARDENING_OVERRIDES",
    "GitResult",
    "GitRunner",
    "validate_remote_url",
]
