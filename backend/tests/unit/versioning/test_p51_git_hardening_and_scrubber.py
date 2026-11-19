"""P5-1 Git hardening, credential injection, redaction, and scrubber tests."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import AppSettings
from app.core.exceptions import (
    GitCommandError,
    GitConfigurationError,
    GitTimeoutError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    PANEL_GITATTRIBUTES_CONTENT,
    GitRepositoryService,
    scrub_gitattributes,
)
from app.modules.versioning.infrastructure.git_runner import (
    GitCredentials,
    GitRunner,
    redact_secrets,
)
from app.modules.versioning.infrastructure.git_save_commit import GitSaveCommitService

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P5-1 native Git hardening is POSIX-only",
)


def _make_runner(tmp_path: Path) -> GitRunner:
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg_parent = tmp_path / "state"
    cfg_parent.mkdir()
    config = cfg_parent / "gitconfig"
    return GitRunner(repo_path=repo, config_path=config)


SERVER_ID = "srv-p51-git"


def _write(root: Path, relpath: str, data: str | bytes) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )


def _init_repo(tmp_path: Path) -> tuple[HostStateLayout, Path, Path, str]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / SERVER_ID
    root.mkdir(parents=True)
    _write(
        root,
        "server.properties",
        "#Minecraft server properties\r\n"
        "motd=Hello\r\n"
        "server-port=25565\r\n"
        "online-mode=true\r\n",
    )
    _write(root, "config/app.yml", "enabled: true\n")
    _write(root, "plugins/sample/config.yml", "key: value\n")
    _write(root, "server-icon.png", b"\x89PNG\r\n\x1a\npng")

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    result = GitRepositoryService(layout).initialize(SERVER_ID, root, lockfile)
    GitBranchService(layout).create_branch(SERVER_ID, root, "dev")
    worktree = root / ".onx" / "worktrees" / "dev"
    return layout, root, worktree, result.main_sha


def _assert_no_secret_bytes(data: bytes, secrets: tuple[str, ...]) -> None:
    for secret in secrets:
        assert secret.encode("utf-8") not in data


def _assert_no_secret_config_bytes(data: bytes, secrets: tuple[str, ...]) -> None:
    _assert_no_secret_bytes(data, secrets)
    assert b"credential.helper" not in data
    assert b"PRIVATE KEY" not in data


def test_git_credentials_validation() -> None:
    creds = GitCredentials(auth_method="pat", token="ghp_secret123", username="bot")
    assert creds.auth_method == "pat"
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="bad")
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="pat", token="")
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="pat", token="a\nb")
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="pat", token="tok", ssh_private_key="key")
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="pat", token="tok", username="")
    with pytest.raises(GitConfigurationError):
        GitCredentials(auth_method="ssh_deploy_key", ssh_private_key="no marker")
    with pytest.raises(GitConfigurationError):
        GitCredentials(
            auth_method="ssh_deploy_key", ssh_private_key="-----BEGIN PRIVATE KEY-----\x00"
        )
    with pytest.raises(GitConfigurationError):
        GitCredentials(
            auth_method="ssh_deploy_key",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----",
            token="t",
        )
    assert "REDACTED" in repr(creds)
    assert "secret" not in str(creds).lower() or "REDACTED" in str(creds)


def test_secret_values_and_redact() -> None:
    creds = GitCredentials(auth_method="pat", token="supersecret")
    assert creds.secret_values() == ("supersecret",)
    assert redact_secrets("out", ()) == "out"
    assert redact_secrets("err", ()) == "err"
    assert redact_secrets("fatal: bad revision", ()) == "fatal: bad revision"
    assert redact_secrets("partial", ()) == "partial"
    text = (
        "token supersecret https://user:pass@github.com/x "
        "github_pat_abcdefghij123456 ghp_abcdefghij123456 "
        "-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----"
    )
    redacted = redact_secrets(text, ("supersecret",))
    assert "supersecret" not in redacted
    assert "user:pass" not in redacted
    assert "github_pat_abcdefghij123456" not in redacted
    assert "ghp_abcdefghij123456" not in redacted
    assert "PRIVATE KEY" not in redacted
    assert "secret\n" not in redacted


def test_scrub_gitattributes() -> None:
    content = (
        b"# comment\n\n"
        b"*.txt text=auto filter=lfs eol=lf\n"
        b"*.jar -filter=evil diff=astextplain merge=ours textconv=cat "
        b"working-tree-encoding=UTF-16 export-subst -export-subst export-subst=true\n"
        b"* filter = cmd\n"
    )
    out = scrub_gitattributes(content)
    assert b"# comment" in out
    assert b"text=auto" in out
    assert b"filter" not in out
    assert b"diff" not in out
    assert b"merge" not in out
    assert b"textconv" not in out
    assert b"working-tree-encoding" not in out
    assert b"export-subst" not in out
    # A line whose attributes are entirely forbidden is dropped, not emitted
    # as a bare pattern.
    assert b"* filter = cmd" not in out
    assert b"\n*\n" not in out
    assert scrub_gitattributes(PANEL_GITATTRIBUTES_CONTENT) == PANEL_GITATTRIBUTES_CONTENT
    assert scrub_gitattributes(b"") == b""
    assert scrub_gitattributes("") == b""

    mixed = (
        b"*.upper FILTER=cmd Export-Subst text=auto\n"
        b"*.neg -FILTER=evil !Merge\n"
        b"*.bare Export-Subst\n"
        b"*.mixed Filter = lfs Diff=astextplain eol=crlf\n"
    )
    mixed_out = scrub_gitattributes(mixed)
    assert b"*.upper text=auto\n" in mixed_out
    assert b"*.mixed eol=crlf\n" in mixed_out
    assert b"FILTER" not in mixed_out
    assert b"Filter" not in mixed_out
    assert b"Export-Subst" not in mixed_out
    assert b"Diff" not in mixed_out
    assert b"*.neg" not in mixed_out
    assert b"*.bare" not in mixed_out


def test_pat_injection(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    token = "ghp_special -e %s $HOME spaces"
    creds = GitCredentials(auth_method="pat", token=token, username="bot user".replace(" ", "-"))
    from subprocess import run as real_subprocess_run

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = dict(kwargs["env"])
        captured["cwd"] = kwargs["cwd"]
        captured["askpass_mode"] = stat.S_IMODE(Path(kwargs["env"]["GIT_ASKPASS"]).stat().st_mode)
        captured["token_mode"] = stat.S_IMODE(
            Path(kwargs["env"]["ONX_GIT_TOKEN_FILE"]).stat().st_mode
        )
        captured["askpass_script"] = Path(kwargs["env"]["GIT_ASKPASS"]).read_text()
        env = kwargs["env"]
        token_file = env["ONX_GIT_TOKEN_FILE"]
        u = real_subprocess_run(
            [env["GIT_ASKPASS"], "Username for 'https://github.com': "],
            capture_output=True,
            text=True,
            env={"ONX_GIT_USERNAME": env["ONX_GIT_USERNAME"], "ONX_GIT_TOKEN_FILE": token_file},
        )
        captured["username_output"] = u.stdout.strip()
        p2 = real_subprocess_run(
            [env["GIT_ASKPASS"], "Password for 'https://github.com': "],
            capture_output=True,
            text=True,
            env={"ONX_GIT_USERNAME": env["ONX_GIT_USERNAME"], "ONX_GIT_TOKEN_FILE": token_file},
        )
        captured["password_output"] = p2.stdout.strip()
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        result = runner.run("status", credentials=creds)

    assert result.stdout == "ok"
    argv = captured["argv"]
    assert argv[0].endswith("git") or argv[0] == "git"
    assert "-c" in argv
    assert "credential.helper=" in argv
    assert token not in " ".join(argv)
    env = captured["env"]
    assert "GIT_ASKPASS" in env
    askpass = Path(env["GIT_ASKPASS"])
    assert askpass.parent.parent == tmp_path / "state"
    assert captured["askpass_mode"] == 0o700
    assert captured["token_mode"] == 0o600
    script = captured["askpass_script"]
    assert token not in script
    assert captured["username_output"] == env["ONX_GIT_USERNAME"]
    assert captured["password_output"] == token
    assert "SSH_AUTH_SOCK" not in env
    # temp dir cleaned
    cred_dirs = list((tmp_path / "state").glob(".onx-git-cred-*"))
    assert cred_dirs == []


def test_ssh_injection(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    creds = GitCredentials(auth_method="ssh_deploy_key", ssh_private_key=key)

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = dict(kwargs["env"])
        ssh_parts = shlex.split(kwargs["env"]["GIT_SSH_COMMAND"])
        key_path = Path(ssh_parts[ssh_parts.index("-i") + 1])
        captured["key_path"] = key_path
        captured["key_mode"] = stat.S_IMODE(key_path.stat().st_mode)
        captured["key_dir_mode"] = stat.S_IMODE(key_path.parent.stat().st_mode)
        captured["key_bytes"] = key_path.read_bytes()
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        runner.run("fetch", credentials=creds)

    env = captured["env"]
    assert "GIT_SSH_COMMAND" in env
    assert f"-i {captured['key_path']}" in env["GIT_SSH_COMMAND"]
    assert "IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "PasswordAuthentication=no" in env["GIT_SSH_COMMAND"]
    assert "KbdInteractiveAuthentication=no" in env["GIT_SSH_COMMAND"]
    assert "PubkeyAuthentication=yes" in env["GIT_SSH_COMMAND"]
    assert captured["key_mode"] == 0o600
    assert captured["key_dir_mode"] == 0o700
    assert captured["key_bytes"] == (key + "\n").encode("utf-8")
    assert "SSH_AUTH_SOCK" not in env
    assert "GIT_ASKPASS" not in env
    assert "SSH_ASKPASS" not in env
    cred_dirs = list((tmp_path / "state").glob(".onx-git-cred-*"))
    assert cred_dirs == []

    # known hosts
    kh = tmp_path / "known_hosts"
    kh.write_text("host ssh-ed25519 AAAA\n")
    creds2 = GitCredentials(
        auth_method="ssh_deploy_key", ssh_private_key=key, ssh_known_hosts_path=str(kh)
    )
    captured2 = {}

    def fake_run2(argv, **kwargs):
        captured2["env"] = dict(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=fake_run2):
        runner.run("fetch", credentials=creds2)
    assert "StrictHostKeyChecking=yes" in captured2["env"]["GIT_SSH_COMMAND"]
    assert str(kh) in captured2["env"]["GIT_SSH_COMMAND"]

    # SSH failures must still wipe and remove the transient credential dir.
    with (
        pytest.raises(GitTimeoutError),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=1),
        ),
    ):
        runner.run("fetch", credentials=creds)
    assert list((tmp_path / "state").glob(".onx-git-cred-*")) == []

    with (
        pytest.raises(GitCommandError),
        patch(
            "subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git"], 1, stdout="", stderr="denied")
            ],
        ),
    ):
        runner.run("fetch", credentials=creds)
    assert list((tmp_path / "state").glob(".onx-git-cred-*")) == []


def test_cleanup_on_error(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    creds = GitCredentials(auth_method="pat", token="secret-token")
    calls = {"n": 0}

    def fake_run(argv, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1, stderr=b"secret-token")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="secret-token")

    with pytest.raises(GitTimeoutError), patch("subprocess.run", side_effect=fake_run):
        runner.run("status", credentials=creds)
    cred_dirs = list((tmp_path / "state").glob(".onx-git-cred-*"))
    assert cred_dirs == []

    # GitCommandError path
    with (
        pytest.raises(GitCommandError),
        patch(
            "subprocess.run",
            side_effect=[subprocess.CompletedProcess(["git"], 1, stdout="", stderr="secret-token")],
        ),
    ):
        runner.run("status", credentials=creds, check=True)
    cred_dirs = list((tmp_path / "state").glob(".onx-git-cred-*"))
    assert cred_dirs == []


def test_runner_redacts_results_and_errors(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    runtime_pat = "ghp_runtimeSecretToken1234567890"
    creds = GitCredentials(auth_method="pat", token=runtime_pat)
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpemPrivateKeyBody\n"
        "-----END RSA PRIVATE KEY-----"
    )
    leaked = (
        f"token={runtime_pat} "
        "github_pat_abcdefghij123456 ghp_abcdefghij123456 "
        "https://user:pass@github.com/o/r\n"
        f"{pem}"
    )
    secrets = (
        runtime_pat,
        "github_pat_abcdefghij123456",
        "ghp_abcdefghij123456",
        "user:pass",
        "MIIEpemPrivateKeyBody",
        "BEGIN RSA PRIVATE KEY",
    )

    def fake_ok(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=leaked, stderr=leaked)

    with patch("subprocess.run", side_effect=fake_ok):
        result = runner.run("status", credentials=creds)
    for field in (result.stdout, result.stderr, " ".join(result.argv)):
        _assert_no_secret_bytes(field.encode("utf-8"), secrets)

    def fake_fail(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=leaked, stderr=leaked)

    with (
        patch("subprocess.run", side_effect=fake_fail),
        pytest.raises(GitCommandError) as command_exc,
    ):
        runner.run("status", credentials=creds)
    command_error = command_exc.value
    command_fields = (
        command_error.message,
        command_error.command,
        command_error.stderr,
        repr(command_error.details),
    )
    for field in command_fields:
        _assert_no_secret_bytes(field.encode("utf-8"), secrets)

    def fake_timeout(argv, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1, stderr=leaked.encode())

    with (
        patch("subprocess.run", side_effect=fake_timeout),
        pytest.raises(GitTimeoutError) as timeout_exc,
    ):
        runner.run("status", credentials=creds)
    timeout_error = timeout_exc.value
    timeout_fields = (
        timeout_error.message,
        timeout_error.command,
        timeout_error.stderr,
        repr(timeout_error.details),
    )
    for field in timeout_fields:
        _assert_no_secret_bytes(field.encode("utf-8"), secrets)


def test_gitconfig_and_repo_config_contain_no_secrets(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    runner.run("init", "-q")
    runner.run("remote", "add", "origin", "https://github.com/o/r")

    token = "ghp_zeroSecretToken1234567890"
    pat_creds = GitCredentials(auth_method="pat", token=token)
    runner.run("status", credentials=pat_creds)
    config_bytes = runner.config_path.read_bytes()
    repo_config_bytes = (runner.repo_path / ".git" / "config").read_bytes()
    for data in (config_bytes, repo_config_bytes):
        _assert_no_secret_config_bytes(data, (token,))

    key_body = "AAAAB3NzaC1lZDI1NTE5AAAAIZeroSecretDeployKeyBody"
    key = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        f"{key_body}\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    ssh_creds = GitCredentials(auth_method="ssh_deploy_key", ssh_private_key=key)
    runner.run("status", credentials=ssh_creds)
    for data in (runner.config_path.read_bytes(), repo_config_bytes):
        _assert_no_secret_config_bytes(data, (key_body,))
    assert list((tmp_path / "state").glob(".onx-git-cred-*")) == []


def test_git_save_commit_scrubs_gitattributes(tmp_path: Path) -> None:
    layout, root, worktree, _main_sha = _init_repo(tmp_path)
    malicious_root = b"* filter=pwn export-subst\n*.txt text=auto\n"
    _write(worktree, GITATTRIBUTES_RELPATH, malicious_root)
    _write(worktree, "plugins/sample/.gitattributes", "* filter=pwn export-subst\n")
    _write(worktree, "config/feature.yml", "feature: true\n")

    result = GitSaveCommitService(layout).save(
        SERVER_ID, root, "dev", "Harden git attributes"
    )

    # The nested server-tree file is removed before ``git add`` and never
    # reaches the commit.
    assert not (worktree / "plugins/sample/.gitattributes").exists()
    assert any(
        "plugins/sample/.gitattributes" in warning for warning in result.warnings
    )
    committed = _git(worktree, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines()
    assert GITATTRIBUTES_RELPATH in committed
    assert "plugins/sample/.gitattributes" not in committed
    assert "config/feature.yml" in committed

    # The malicious root file is overwritten with the panel-owned content.
    root_content = _git(worktree, "show", f"HEAD:{GITATTRIBUTES_RELPATH}").stdout.encode()
    assert root_content == PANEL_GITATTRIBUTES_CONTENT
    assert b"filter" not in root_content
    assert b"export-subst" not in root_content
    assert (worktree / GITATTRIBUTES_RELPATH).read_bytes() == PANEL_GITATTRIBUTES_CONTENT


def test_clean_export_archive_uses_no_worktree_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, root, _worktree, main_sha = _init_repo(tmp_path)
    calls: list[tuple[str, ...]] = []
    original_run = GitRunner.run

    def spy_run(self, *args, **kwargs):
        calls.append(args)
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(GitRunner, "run", spy_run)
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    request = CleanExportRequest(
        server_id=SERVER_ID,
        server_root=root,
        commit_sha=main_sha,
        destination=tmp_path / "export",
        lockfile=lockfile,
    )
    CleanExportService(layout).export(request)

    archive_calls = [args for args in calls if args and args[0] == "archive"]
    assert archive_calls
    for args in archive_calls:
        assert "--no-worktree-attributes" in args
        assert "--format=tar" in args
