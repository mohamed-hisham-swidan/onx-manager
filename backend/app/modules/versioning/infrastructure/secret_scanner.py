"""Structured & Pattern Secret Scanner for Class-B Git content (P2-2/P2-5).

Normative contract: ``SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02`` OD-v8.5-1,
OD-v8.7-3, and OD-v8.7-16. The scanner runs before every Git write (repo
initialization, Save & Commit, merge, conversion, push, and export). It reports only
finding metadata; detected secret values are never included in errors or logs.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any

import yaml

from app.core.exceptions import SecretFileInGitForbiddenError

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*KEY-----", re.ASCII)
_DISCORD_BOT_TOKEN_RE = re.compile(
    r"[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}",
    re.ASCII,
)
_DISCORD_WEBHOOK_RE = re.compile(
    r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+",
    re.ASCII,
)
_SLACK_WEBHOOK_RE = re.compile(
    r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+",
    re.ASCII,
)
_GITHUB_PAT_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{22,})",
    re.ASCII,
)
_AWS_ACCESS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}", re.ASCII)

_PATTERN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", _PRIVATE_KEY_RE),
    ("discord-bot-token", _DISCORD_BOT_TOKEN_RE),
    ("discord-webhook", _DISCORD_WEBHOOK_RE),
    ("slack-webhook", _SLACK_WEBHOOK_RE),
    ("github-pat", _GITHUB_PAT_RE),
    ("aws-access-key", _AWS_ACCESS_KEY_RE),
)

_TOKEN_KEY_RE = re.compile(
    r"^(?:"
    r"bot_?token|auth_?token|access_?token|refresh_?token|"
    r"client_?secret|api_?key|secret_?key|private_?key|webhook_?url"
    r")$"
)
_PREFIXED_DB_KEY_RE = re.compile(
    r"^(?:mysql|mariadb|postgres|database|db|redis|rcon|smtp)[._]?(?:password|pass|pwd)$"
)
_SECRET_PLACEHOLDER_RE = re.compile(r"\A\$\{ONX_SECRET_[A-Za-z0-9_]+\}\Z", re.IGNORECASE)

_BARE_PASSWORD_LEAVES = frozenset({"password", "passwd", "pwd"})
_LIST_INDEX_SUFFIX_RE = re.compile(r"(?:\[\d+\])+$")
_FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")
_PLACEHOLDER_VALUES = frozenset({"", "none", "changeme", "password", "null", "~"})
_BOOLEAN_STRING_VALUES = frozenset({"true", "false"})


@dataclass(frozen=True)
class SecretFinding:
    """A single secret hit; never contains the matched value."""

    kind: str
    key: str = ""

    def to_details(self) -> dict[str, str]:
        return {"kind": self.kind, "key": self.key}


def _add(findings: list[SecretFinding], kind: str, key: str = "") -> None:
    finding = SecretFinding(kind=kind, key=key[:256])
    if finding not in findings:
        findings.append(finding)


def _scan_patterns(text: str, findings: list[SecretFinding]) -> None:
    for kind, pattern in _PATTERN_RULES:
        if pattern.search(text):
            _add(findings, kind)


def _flatten(value: Any, path: tuple[str, ...]) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        leaves: list[tuple[str, Any]] = []
        for key, child in value.items():
            leaves.extend(_flatten(child, (*path, str(key))))
        return leaves
    if isinstance(value, (list, tuple)):
        leaves = []
        for index, child in enumerate(value):
            indexed_path = (
                (*path[:-1], f"{path[-1]}[{index}]") if path else (f"[{index}]",)
            )
            leaves.extend(_flatten(child, indexed_path))
        return leaves
    return [(".".join(path), value)] if path else []


def _is_placeholder(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (dict, list, tuple, bytes)):
        return True
    text = str(value).strip()
    lowered = text.lower()
    if lowered in _PLACEHOLDER_VALUES or lowered in _BOOLEAN_STRING_VALUES:
        return True
    return bool(_SECRET_PLACEHOLDER_RE.fullmatch(text))


def _normalize_key_segment(segment: str, *, strip_list_index: bool = False) -> str:
    if strip_list_index:
        segment = _LIST_INDEX_SUFFIX_RE.sub("", segment)
    return segment.lower().replace("-", "_")


def _is_sensitive_key(key_path: str) -> bool:
    segments = key_path.split(".") if key_path else []
    if not segments:
        return False
    leaf = _normalize_key_segment(segments[-1])
    if _TOKEN_KEY_RE.fullmatch(leaf) or leaf in _BARE_PASSWORD_LEAVES:
        return True
    if _PREFIXED_DB_KEY_RE.fullmatch(leaf):
        return True
    if len(segments) < 2:
        return False
    parent = _normalize_key_segment(segments[-2], strip_list_index=True)
    if not parent:
        return False
    return any(
        _PREFIXED_DB_KEY_RE.fullmatch(f"{parent}{separator}{leaf}")
        for separator in (".", "_")
    )


def _scan_structured_leaves(
    leaves: list[tuple[str, Any]],
    findings: list[SecretFinding],
) -> None:
    for key_path, value in leaves:
        if not _is_sensitive_key(key_path):
            continue
        if value is None or isinstance(value, (dict, list, tuple, bytes)):
            continue
        if _is_placeholder(value):
            continue
        _add(findings, "sensitive-key", key_path)


def _strip_matching_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _split_properties_line(line: str) -> tuple[str, str]:
    index = 0
    key_end = len(line)
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char in "=:" or char.isspace():
            key_end = index
            break
        index += 1
    key = line[:key_end]
    index = key_end
    while index < len(line) and line[index].isspace():
        index += 1
    if index < len(line) and line[index] in "=:":
        index += 1
        while index < len(line) and line[index].isspace():
            index += 1
    return key, line[index:]


def _parse_properties(text: str) -> list[tuple[str, Any]]:
    leaves: list[tuple[str, Any]] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        key, value = _split_properties_line(line)
        key = _strip_matching_quotes(key.strip()).strip()
        if key:
            leaves.append((key, _strip_matching_quotes(value.strip()).strip()))
    return leaves


def _parse_structured(path: str, text: str) -> list[tuple[str, Any]]:
    lowered = path.lower()
    try:
        if lowered.endswith(".json"):
            return _flatten(json.loads(text), ())
        if lowered.endswith((".yml", ".yaml")):
            return _flatten(yaml.safe_load(text), ())
        if lowered.endswith(".toml"):
            return _flatten(tomllib.loads(text), ())
        if lowered.endswith(".properties"):
            return _parse_properties(text)
    except (ValueError, TypeError, yaml.YAMLError):
        # Parse failures belong to the Save & Commit config validator. The
        # pattern scanner above still protects malformed files.
        return []
    return []


def scan_bytes(path: str, data: bytes) -> tuple[SecretFinding, ...]:
    """Return every finding for one file without ever returning secret values."""
    findings: list[SecretFinding] = []
    lowered = path.lower()
    if lowered.endswith(_FORBIDDEN_SUFFIXES):
        _add(findings, "forbidden-extension")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return tuple(findings)

    _scan_patterns(text, findings)
    _scan_structured_leaves(_parse_structured(path, text), findings)
    return tuple(findings)


def assert_no_secrets(path: str, data: bytes) -> None:
    """Raise :class:`SecretFileInGitForbiddenError` when *data* contains secrets."""
    findings = scan_bytes(path, data)
    if findings:
        raise SecretFileInGitForbiddenError(
            path,
            findings=[finding.to_details() for finding in findings],
        )


__all__ = [
    "SecretFinding",
    "assert_no_secrets",
    "scan_bytes",
]
