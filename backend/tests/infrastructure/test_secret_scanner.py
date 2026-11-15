"""Tests for the Structured & Pattern Secret Scanner (P2-2/P2-5)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.exceptions import SecretFileInGitForbiddenError, ValidationError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_repository import (
    GITATTRIBUTES_RELPATH,
    GitRepositoryService,
)
from app.modules.versioning.infrastructure.git_save_commit import (
    _validate_structured,
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


LUCKPERMS_SECRET = "S3cr3t-LuckPerms-Pass-2026"
LUCKPERMS_CONFIG = (
    "storage-method: MySQL\n"
    "data:\n"
    '  address: "localhost:3306"\n'
    '  database: "luckperms"\n'
    '  username: "luckperms"\n'
    f'  password: "{LUCKPERMS_SECRET}"\n'
)


@pytest.mark.parametrize(
    ("path", "text", "expected_key"),
    [
        ("plugins/LuckPerms/config.yml", LUCKPERMS_CONFIG, "data.password"),
        (
            "config/app.yml",
            "data:\n  mongo:\n    password: nested-secret\n",
            "data.mongo.password",
        ),
        (
            "config/app.yml",
            "settings:\n  database:\n    password: nested-secret\n",
            "settings.database.password",
        ),
        ("config/app.yml", "rabbitmq:\n  password: broker-secret\n", "rabbitmq.password"),
        ("config/app.yml", "nats:\n  password: broker-secret\n", "nats.password"),
        (
            "config/app.yml",
            "accounts:\n  - name: one\n    password: list-secret\n",
            "accounts[0].password",
        ),
        ("config/app.yml", "rcon:\n  - pass: rcon-secret\n", "rcon[0].pass"),
        (
            "config/app.json",
            '[{"password": "top-level-array-secret"}]',
            "[0].password",
        ),
        (
            "config/app.json",
            '{"items": [{"password": "nested-array-secret"}]}',
            "items[0].password",
        ),
        ("config/app.toml", '[data]\npassword = "toml-secret"\n', "data.password"),
        (
            "config/app.toml",
            '[[databases]]\npassword = "toml-array-secret"\n',
            "databases[0].password",
        ),
        ("config/app.properties", "db.password=properties-secret\n", "db.password"),
        (
            "config/app.properties",
            "storage.password=properties-secret\n",
            "storage.password",
        ),
        ("config/app.yml", "data:\n  passwd: passwd-secret\n", "data.passwd"),
        ("config/app.yml", "data:\n  pwd: pwd-secret\n", "data.pwd"),
    ],
)
def test_od_v8_7_16_sensitive_key_vectors(
    path: str, text: str, expected_key: str
) -> None:
    findings = scan_bytes(path, text.encode("utf-8"))
    assert any(
        finding.kind == "sensitive-key" and finding.key == expected_key
        for finding in findings
    ), findings


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (
            "plugins/LuckPerms/config.yml",
            LUCKPERMS_CONFIG.replace(
                f'"{LUCKPERMS_SECRET}"', '"${ONX_SECRET_LUCKPERMS_DB_PASSWORD}"'
            ),
        ),
        ("config/app.yml", "password-required: true\n"),
        ("config/app.yml", 'password-policy: "min length 8"\n'),
        ("config/app.yml", 'password: ""\n'),
        ("config/app.yml", "password: false\n"),
        ("config/app.yml", "password: true\n"),
        ("config/app.yml", "password: changeme\n"),
        ("config/app.yml", 'password: "   "\n'),
        ("config/app.yml", 'password: "null"\n'),
        ("config/app.yml", 'password: "~"\n'),
        ("config/app.yml", 'password: "NONE"\n'),
        (
            "config/app.yml",
            "password: ${onx_secret_luckperms_db_password}\n",
        ),
        ("config/app.json", '{"password": true}'),
        ("config/app.properties", "password=false\n"),
        ("config/app.properties", "password-required true\n"),
        ("config/app.properties", "password=   \n"),
        ("config/app.properties", "password=${ONX_SECRET_DB_PASSWORD}\n"),
        ("config/app.properties", 'password="none"\n'),
    ],
)
def test_od_v8_7_16_placeholders_and_booleans_do_not_raise(
    path: str, text: str
) -> None:
    assert scan_bytes(path, text.encode("utf-8")) == ()


@pytest.mark.parametrize(
    ("path", "text", "expected_keys"),
    [
        (
            "config/case.yml",
            "Password: Case-Secret\nPASSWORD: Upper-Secret\nBot_Token: Case-Token\n",
            {"Password", "PASSWORD", "Bot_Token"},
        ),
        (
            "config/quoted.yml",
            '"password": Quoted-Secret\n\'data.password\': Quoted-Dot-Secret\n',
            {"password", "data.password"},
        ),
        (
            "config/app.properties",
            '"db.password"=Quoted-Prop-Secret\n'
            "'storage.password'=Quoted-Storage-Secret\n",
            {"db.password", "storage.password"},
        ),
        (
            "config/anchors.yml",
            "defaults:\n  password: &pw Anchored-Secret\n"
            "data:\n  password: *pw\n",
            {"defaults.password", "data.password"},
        ),
        (
            "config/merge.yml",
            "defaults: &pw\n  password: Merged-Secret\n"
            "data:\n  <<: *pw\n",
            {"defaults.password", "data.password"},
        ),
        (
            "config/whitespace.yml",
            'password: "  padded secret  "\n',
            {"password"},
        ),
        (
            "config/app.properties",
            "password=  padded secret  \n",
            {"password"},
        ),
        (
            "config/app.properties",
            "password space-separated-secret\n",
            {"password"},
        ),
        (
            "config/quoted.toml",
            '"password" = "toml-quoted-secret"\n',
            {"password"},
        ),
    ],
)
def test_od_v8_7_16_bypass_attempts_are_detected(
    path: str, text: str, expected_keys: set[str]
) -> None:
    findings = scan_bytes(path, text.encode("utf-8"))
    found = {finding.key for finding in findings if finding.kind == "sensitive-key"}
    assert expected_keys <= found, (expected_keys, findings)


def test_od_v8_7_16_redaction_keeps_only_kind_and_key_metadata() -> None:
    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        assert_no_secrets("plugins/LuckPerms/config.yml", LUCKPERMS_CONFIG.encode())

    assert LUCKPERMS_SECRET not in str(exc_info.value)
    assert LUCKPERMS_SECRET not in json.dumps(exc_info.value.details)
    assert exc_info.value.details["findings"] == [
        {"kind": "sensitive-key", "key": "data.password"}
    ]
    assert all(
        set(finding) == {"kind", "key"}
        for finding in exc_info.value.details["findings"]
    )


def test_malformed_structured_file_still_gets_pattern_scanning() -> None:
    assert any(
        finding.kind == "github-pat"
        for finding in scan_bytes("config/broken.json", f'{{"token": "{GITHUB_PAT}"'.encode())
    )
    assert scan_bytes("config/broken.json", b'{"token": ') == ()


MULTI_DOC_SECRET = "S3cr3t-Multi-Doc-Pass-2026"


@pytest.mark.parametrize(
    ("text", "expected_key"),
    [
        (
            f"---\ndata:\n  password: {MULTI_DOC_SECRET}\n---\nother: 1\n",
            "data.password",
        ),
        (
            f"---\nfoo: bar\n---\ndata:\n  password: {MULTI_DOC_SECRET}\n",
            "data.password",
        ),
        (f"---\n---\npassword: {MULTI_DOC_SECRET}\n", "password"),
        (
            f"---\npassword: {MULTI_DOC_SECRET}\n---\n: [unclosed\n",
            "password",
        ),
    ],
)
def test_multi_document_yaml_secrets_are_detected(
    text: str, expected_key: str
) -> None:
    findings = scan_bytes("config/multi.yml", text.encode("utf-8"))
    assert any(
        finding.kind == "sensitive-key" and finding.key == expected_key
        for finding in findings
    ), findings


def test_multi_document_yaml_placeholders_are_allowed() -> None:
    text = (
        "---\n"
        "data:\n"
        "  password: ${ONX_SECRET_DB_PASSWORD}\n"
        "---\n"
        "bot-token: changeme\n"
        "---\n"
        "enabled: false\n"
    )
    assert scan_bytes("config/multi.yml", text.encode("utf-8")) == ()


def test_multi_document_yaml_redaction_keeps_only_kind_and_key_metadata() -> None:
    text = f"---\nfoo: bar\n---\ndata:\n  password: {MULTI_DOC_SECRET}\n"
    with pytest.raises(SecretFileInGitForbiddenError) as exc_info:
        assert_no_secrets("config/multi.yml", text.encode("utf-8"))

    assert MULTI_DOC_SECRET not in str(exc_info.value)
    assert MULTI_DOC_SECRET not in json.dumps(exc_info.value.details)
    assert exc_info.value.details["findings"] == [
        {"kind": "sensitive-key", "key": "data.password"}
    ]


def test_validate_structured_accepts_multi_document_yaml() -> None:
    _validate_structured(
        "config/multi.yml",
        b"---\nenabled: true\n---\nmotd: Hello\n",
    )


def test_validate_structured_rejects_malformed_multi_document_yaml() -> None:
    with pytest.raises(ValidationError):
        _validate_structured(
            "config/multi.yml",
            b"---\nkey: value\n---\n: [unclosed\n",
        )


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


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only GitRepositoryService.initialize integration; Windows = Simple-only",
)
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


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only GitRepositoryService.initialize integration; Windows = Simple-only",
)
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
