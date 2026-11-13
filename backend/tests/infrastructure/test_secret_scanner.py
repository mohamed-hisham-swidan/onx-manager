"""Tests for the Structured & Pattern Secret Scanner (P2-2/P2-5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import SecretFileInGitForbiddenError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    GitRepositoryService,
)
from app.modules.versioning.infrastructure.secret_scanner import (
    assert_no_secrets,
    scan_bytes,
)

DISCORD_BOT_TOKEN = "M" + ("A" * 24) + "." + ("B" * 6) + "." + ("C" * 27)
GITHUB_PAT = "ghp_" + ("A" * 36)
GITHUB_FINE_GRAINED_PAT = "github_pat_" + ("B" * 30)
AWS_ACCESS_KEY = "AKIA" + ("A" * 16)
DISCORD_WEBHOOK = (
    "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyzABCDEF"
)
SLACK_WEBHOOK = "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEexample\n-----END RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("path", "text", "kind"),
    [
        ("config/key.pem", PRIVATE_KEY, "forbidden-extension"),
        ("config/app.yml", PRIVATE_KEY, "private-key"),
        ("config/app.yml", DISCORD_BOT_TOKEN, "discord-bot-token"),
        ("config/app.yml", DISCORD_WEBHOOK, "discord-webhook"),
        ("config/app.yml", SLACK_WEBHOOK, "slack-webhook"),
        ("config/app.yml", GITHUB_PAT, "github-pat"),
        ("config/app.yml", GITHUB_FINE_GRAINED_PAT, "github-pat"),
        ("config/app.yml", AWS_ACCESS_KEY, "aws-access-key"),
    ],
)
def test_pattern_findings(path: str, text: str, kind: str) -> None:
    findings = scan_bytes(path, text.encode("utf-8"))
    assert kind in {finding.kind for finding in findings}


def test_forbidden_extensions_are_case_insensitive() -> None:
    for suffix in (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".KEY"):
        findings = scan_bytes(f"config/server{suffix}", b"not necessarily a secret")
        assert findings[0].kind == "forbidden-extension"


def test_findings_never_include_the_secret_value() -> None:
    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        assert_no_secrets("config/app.yml", f"token: {GITHUB_PAT}\n".encode())

    rendered = str(exc_info.value)
    assert GITHUB_PAT not in rendered
    assert GITHUB_PAT not in json.dumps(exc_info.value.details)
    assert exc_info.value.code == "SECRET_FILE_IN_GIT_FORBIDDEN"
    assert exc_info.value.http_status == 422
    assert exc_info.value.details["findings"][0]["kind"] == "github-pat"


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("config/app.yml", "rcon:\n  password: secret-value\n"),
        ("config/app.json", '{"rcon": {"password": "secret-value"}}'),
        ("config/app.toml", '[rcon]\npassword = "secret-value"\n'),
        ("config/app.properties", "rcon.password=secret-value\n"),
        ("config/app.yml", "bot-token: secret-value\n"),
        ("config/app.yml", "database:\n  password: secret-value\n"),
        ("config/app.json", '{"api_key": "secret-value"}'),
    ],
)
def test_sensitive_structured_keys_are_detected(path: str, text: str) -> None:
    findings = scan_bytes(path, text.encode("utf-8"))
    assert any(finding.kind == "sensitive-key" for finding in findings)


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("config/app.yml", "rcon:\n  password: ${ONX_SECRET_RCON_PASSWORD}\n"),
        ("config/app.json", '{"rcon": {"password": ""}}'),
        ("config/app.toml", '[rcon]\npassword = "none"\n'),
        ("config/app.properties", "rcon.password=changeme\n"),
        ("config/app.yml", "bot-token: password\n"),
        ("config/app.yml", "motd: Hello\nmax-players: 20\n"),
        ("config/app.json", '{"motd": "Hello", "view-distance": 10}'),
    ],
)
def test_placeholders_and_non_sensitive_values_are_allowed(path: str, text: str) -> None:
    assert scan_bytes(path, text.encode("utf-8")) == ()


def test_malformed_structured_file_still_gets_pattern_scanning() -> None:
    assert any(
        finding.kind == "github-pat"
        for finding in scan_bytes("config/broken.json", f'{{"token": "{GITHUB_PAT}"'.encode())
    )
    assert scan_bytes("config/broken.json", b'{"token": ') == ()


def test_binary_files_are_not_decoded() -> None:
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"payload"
    assert scan_bytes("server-icon.png", png) == ()
    assert scan_bytes("config/key.pem", png)[0].kind == "forbidden-extension"


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


@pytest.fixture
def layout_and_root(tmp_path: Path) -> tuple[HostStateLayout, Path]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-1"
    root.mkdir(parents=True)
    return layout, root


def _write(root: Path, relpath: str, data: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def test_initial_commit_blocks_secret_before_creating_repo(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _write(root, "server.properties", "motd=Hello\n")
    _write(root, "config/app.yml", f"bot-token: {DISCORD_BOT_TOKEN}\n")

    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    assert DISCORD_BOT_TOKEN not in str(exc_info.value)
    assert not (layout.repos / "srv-1" / "repo.git").exists()
    assert not (root / ".onx" / "worktrees" / "main").exists()


def test_initial_commit_allows_secret_placeholders(
    layout_and_root: tuple[HostStateLayout, Path],
) -> None:
    layout, root = layout_and_root
    _write(root, "server.properties", "motd=Hello\n")
    _write(root, "config/app.yml", "bot-token: ${ONX_SECRET_BOT_TOKEN}\n")

    result = GitRepositoryService(layout).initialize("srv-1", root, _lockfile())

    assert result.status == "created"
    committed = (root / ".onx" / "worktrees" / "main" / "config" / "app.yml").read_text(
        encoding="utf-8"
    )
    assert committed == "bot-token: ${ONX_SECRET_BOT_TOKEN}\n"
    assert (result.worktree_path / GITATTRIBUTES_RELPATH).is_file()
