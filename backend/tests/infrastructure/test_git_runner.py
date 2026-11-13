"""Tests for the hardened native Git runner (P2-2)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

import app.modules.versioning.infrastructure.git_runner as git_runner
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
from app.modules.versioning.infrastructure.git_runner import (
    GIT_HARDENING_OVERRIDES,
    GitResult,
    GitRunner,
    validate_remote_url,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only; Windows remains Simple-only",
)


def _runner(tmp_path: Path, **kwargs: object) -> GitRunner:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return GitRunner(
        repo_path=repo,
        config_path=tmp_path / "gitconfig",
        **kwargs,
    )


def _capture_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> list[tuple[list[str], dict[str, object]]]:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(git_runner.subprocess, "run", fake_run)
    return calls


def test_hardening_overrides_are_exact_and_precede_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    calls = _capture_run(monkeypatch)

    runner.run("status", "--porcelain")

    expected = ["git"]
    for key, value in GIT_HARDENING_OVERRIDES:
        expected.extend(["-c", f"{key}={value}"])
    expected.extend(["status", "--porcelain"])
    argv, kwargs = calls[0]
    assert argv == expected
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(runner.repo_path)


def test_stdin_is_closed_unless_input_is_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    calls = _capture_run(monkeypatch)

    runner.run("status")
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert "input" not in calls[0][1]

    runner.run("commit", "-F", "-", input_text="message\n")
    assert calls[1][1]["input"] == "message\n"
    assert "stdin" not in calls[1][1]


def test_environment_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(
        tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
            "GIT_DIR": "/tmp/poison",
            "GIT_WORK_TREE": "/tmp/poison",
            "GIT_CONFIG_GLOBAL": "/tmp/poison",
            "GIT_ASKPASS": "/tmp/poison",
            "SSH_ASKPASS": "/tmp/poison",
        },
    )
    calls = _capture_run(monkeypatch)

    runner.run("status")

    env = calls[0][1]["env"]
    assert isinstance(env, dict)
    assert env["GIT_CONFIG_GLOBAL"] == str(runner.config_path)
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ATTR_NOSYSTEM"] == "1"
    assert env["GIT_PAGER"] == "cat"
    assert env["GIT_EDITOR"] == "true"
    assert env["LC_ALL"] == "C"
    assert "GIT_DIR" not in env
    assert "GIT_WORK_TREE" not in env
    assert "GIT_ASKPASS" not in env
    assert "SSH_ASKPASS" not in env


def test_isolated_config_is_private_and_minimal(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    runner.run("status", check=False)

    content = runner.config_path.read_text(encoding="utf-8")
    assert content.count("directory =") == 1
    assert f'directory = "{runner.repo_path}"' in content
    assert "defaultBranch = main" in content
    assert "filemode = true" in content
    assert "gpgsign = false" in content
    assert "name = ONX Manager" in content
    assert "email = onx-manager@localhost" in content
    assert stat.S_IMODE(runner.config_path.stat().st_mode) == 0o600


def test_isolated_config_is_reused_without_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    _capture_run(monkeypatch)
    writes: list[Path] = []
    original = git_runner.atomic_write_private

    def counting_write(dst: str | Path, content: str | bytes, **kwargs: object) -> int:
        writes.append(Path(dst))
        return original(dst, content, **kwargs)

    monkeypatch.setattr(git_runner, "atomic_write_private", counting_write)

    runner.run("status")
    runner.run("status")

    assert writes == [runner.config_path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_config_symlink_is_rejected(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    target = tmp_path / "target"
    target.write_text("not a config", encoding="utf-8")
    runner.config_path.symlink_to(target)

    with pytest.raises(GitConfigurationError, match="symlink"):
        runner.run("status", check=False)


def test_config_parent_must_exist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(GitConfigurationError, match="parent"):
        GitRunner(
            repo_path=repo,
            config_path=tmp_path / "missing" / "gitconfig",
        )


def test_non_zero_exit_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(tmp_path)
    _capture_run(monkeypatch, returncode=128, stderr="fatal: bad revision")

    with pytest.raises(GitCommandError) as exc_info:
        runner.run("rev-parse", "HEAD")

    error = exc_info.value
    assert error.code == "GIT_COMMAND_FAILED"
    assert error.http_status == 500
    assert error.returncode == 128
    assert "fatal: bad revision" in error.stderr
    assert error.details["returncode"] == 128
    assert "rev-parse" in error.details["command"]


def test_check_false_returns_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(tmp_path)
    _capture_run(monkeypatch, returncode=1, stdout="out", stderr="err")

    result = runner.run("status", check=False)

    assert result == GitResult(
        argv=result.argv,
        returncode=1,
        stdout="out",
        stderr="err",
    )
    assert result.ok is False


def test_timeout_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(tmp_path)

    def timeout_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr=b"partial")

    monkeypatch.setattr(git_runner.subprocess, "run", timeout_run)

    with pytest.raises(GitTimeoutError) as exc_info:
        runner.run("status", timeout=1.5)

    error = exc_info.value
    assert error.code == "GIT_TIMEOUT"
    assert error.http_status == 504
    assert error.retryable is True
    assert error.timeout_seconds == 1.5
    assert error.stderr == "partial"


def test_missing_executable_raises_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)

    def missing_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(git_runner.subprocess, "run", missing_run)

    with pytest.raises(GitUnavailableError) as exc_info:
        runner.run("status")

    assert exc_info.value.code == "GIT_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert exc_info.value.retryable is True


def test_missing_working_directory_is_rejected_before_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    called = False

    def unexpected_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(git_runner.subprocess, "run", unexpected_run)

    with pytest.raises(GitCommandError, match="working directory"):
        runner.run("status", cwd=tmp_path / "missing")
    assert called is False


def test_relative_working_directory_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    _capture_run(monkeypatch)

    with pytest.raises(GitCommandError, match="absolute"):
        runner.run("status", cwd="relative")


def test_subcommand_must_not_begin_with_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    called = False

    def unexpected_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(git_runner.subprocess, "run", unexpected_run)

    with pytest.raises(GitError, match="subcommand"):
        runner.run("--version")
    assert called is False


def test_nul_argument_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(tmp_path)
    _capture_run(monkeypatch)

    with pytest.raises(GitError, match="NUL"):
        runner.run("status", "bad\x00arg")


def test_platform_guard_rejects_non_posix(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(GitUnsupportedPlatformError) as exc_info:
        GitRunner(
            repo_path=repo,
            config_path=tmp_path / "gitconfig",
            platform_name="nt",
        )
    assert exc_info.value.code == "GIT_UNSUPPORTED_PLATFORM"
    assert exc_info.value.http_status == 501


def test_real_git_init_commit_and_panel_identity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = GitRunner(repo_path=repo, config_path=tmp_path / "gitconfig")

    runner.run("init", "-q")
    assert runner.run("symbolic-ref", "--short", "HEAD").stdout.strip() == "main"

    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    runner.run("add", "hello.txt")
    runner.run("commit", "-q", "-m", "initial")

    log = runner.run("log", "-1", "--format=%an <%ae>|%s").stdout.strip()
    assert log == "ONX Manager <onx-manager@localhost>|initial"


@pytest.mark.parametrize(
    "name",
    ["main", "feature/x", "release-1.0", "a.b_c-d"],
)
def test_validate_branch_name_accepts_valid_names(tmp_path: Path, name: str) -> None:
    runner = _runner(tmp_path)
    assert runner.validate_branch_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-evil",
        "bad name",
        "a..b",
        "a~1",
        "a^",
        "a:",
        "a\\b",
        "a.lock",
        ".hidden",
        "a/",
        "/a",
        "a//b",
        "a.",
        "HEAD",
        "@{-1}",
        "a@{b",
        "refs/heads/x",
    ],
)
def test_validate_branch_name_rejects_invalid_names(tmp_path: Path, name: str) -> None:
    runner = _runner(tmp_path)
    with pytest.raises(GitRefValidationError) as exc_info:
        runner.validate_branch_name(name)
    assert exc_info.value.code == "GIT_REF_INVALID"
    assert exc_info.value.http_status == 422


def test_validate_branch_name_rejects_leading_dash_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    called = False

    def unexpected_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(git_runner.subprocess, "run", unexpected_run)

    with pytest.raises(GitRefValidationError, match="begin"):
        runner.validate_branch_name("-evil")
    assert called is False


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner-name/repo_name.js",
        "ssh://git@github.com/owner/repo",
        "ssh://git@github.com/owner/repo.git",
    ],
)
def test_validate_remote_url_accepts_approved_forms(url: str) -> None:
    assert validate_remote_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/extra",
        "https://user:pass@github.com/owner/repo",
        "https://github.com/owner/repo\n",
        "https://github.com/owner/repo ",
        "ssh://git@github.com:22/owner/repo",
        "file:///tmp/repo",
        "ext::sh -c whoami",
        "fd::3",
        "ssh://git@github.com/owner/..",
        "https://github.com/-owner/repo",
    ],
)
def test_validate_remote_url_rejects_invalid_forms(url: str) -> None:
    with pytest.raises(GitRemoteUrlError) as exc_info:
        validate_remote_url(url)
    assert exc_info.value.code == "GIT_REMOTE_URL_INVALID"
    assert exc_info.value.http_status == 422


@pytest.mark.parametrize("token", ["ext::", "fd::", "file::"])
def test_validate_remote_url_rejects_forbidden_protocol_tokens(token: str) -> None:
    with pytest.raises(GitRemoteUrlError, match="protocol token"):
        validate_remote_url(f"https://github.com/owner/repo{token}x")


def test_git_error_types_expose_expected_http_statuses() -> None:
    assert GitConfigurationError().http_status == 500
    assert GitUnsupportedPlatformError().http_status == 501
    assert GitUnavailableError().http_status == 503
    assert GitCommandError().http_status == 500
    assert GitTimeoutError().http_status == 504
    assert GitRefValidationError().http_status == 422
    assert GitRemoteUrlError().http_status == 422
