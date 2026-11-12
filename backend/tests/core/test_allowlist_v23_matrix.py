"""Red tests for Allow-list v2.3 (SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02 v8.7).

Production code does not exist yet. The matrix rows are parsed from the spec's
normative ``tsv`` block at test time, never retyped. Only the literal two-character
sequences ``\\n`` and ``\\x00`` are decoded; every other character (real backslashes,
trailing spaces) stays literal.

Until ``app.core.allowlist`` lands, the classification, Step-0 and dir_fd tests fail
with ImportError -- the expected red state.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "docs" / "design" / "SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md"

EXPECTED_ROW_COUNT = 110

# Copied verbatim from the spec (Tests & Verification, Cross-loader Health Gate).
HEALTH_GATE_DONE_REGEX = re.compile(
    r"^.*?\bINFO\b.*?: Done \([0-9.,]+s\)! For help, type [\"']help[\"']"
)


def _decode_literal(text: str) -> str:
    """Decode only the spec's two literal escapes; leave everything else untouched."""
    return text.replace("\\n", "\n").replace("\\x00", "\x00")


def _parse_matrix_block(source: Path) -> list[tuple[str, str]]:
    """Return ``(path, expected)`` rows from the spec's ```tsv block.

    Lines are deliberately not stripped: a trailing space can be part of a path.
    """
    lines = source.read_text(encoding="utf-8").split("\n")
    start = lines.index("```tsv")
    end = lines.index("```", start + 1)
    block = lines[start + 1 : end]
    if not block or block[0] != "path\texpected":
        raise ValueError(f"unexpected TSV header: {block[:1]!r}")
    rows: list[tuple[str, str]] = []
    for line in block[1:]:
        fields = line.split("\t")
        if len(fields) != 2:
            raise ValueError(f"malformed TSV row: {line!r}")
        rows.append((_decode_literal(fields[0]), fields[1]))
    return rows


MATRIX_ROWS = _parse_matrix_block(SPEC_PATH)
EXPECTED_CLASS_COUNTS = Counter(expected for _, expected in MATRIX_ROWS)

_IMPORT_ERROR: str | None = None
_MISMATCHES: int | None = None


@dataclass
class MatrixEvaluation:
    mismatches: list[tuple[int, str, str, str]]
    actual_class_counts: Counter


def _allowlist_module():
    from app.core import allowlist

    return allowlist


def _emit_summary(config) -> None:
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    reporter.write_line(f"MATRIX ROWS: {len(MATRIX_ROWS)}")
    reporter.write_line(f"EXPECTED CLASS COUNTS: {dict(sorted(EXPECTED_CLASS_COUNTS.items()))}")
    if _IMPORT_ERROR is not None:
        reporter.write_line(f"ALLOWLIST IMPORT FAILED: {_IMPORT_ERROR}")
    reporter.write_line(f"MISMATCHES: {_MISMATCHES}")


@pytest.fixture(scope="session")
def evaluation(request: pytest.FixtureRequest) -> Iterator[MatrixEvaluation | None]:
    global _IMPORT_ERROR, _MISMATCHES
    result: MatrixEvaluation | None = None
    try:
        allowlist = _allowlist_module()
    except ImportError as exc:  # expected red state until the module exists
        _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        _MISMATCHES = len(MATRIX_ROWS)
    else:
        mismatches: list[tuple[int, str, str, str]] = []
        actual_counts: Counter = Counter()
        for index, (path, expected) in enumerate(MATRIX_ROWS):
            actual = allowlist.classify(path)  # empty dynamic-class-c registry
            actual_counts[actual] += 1
            if actual != expected:
                mismatches.append((index, path, expected, actual))
        _MISMATCHES = len(mismatches)
        result = MatrixEvaluation(mismatches=mismatches, actual_class_counts=actual_counts)
    yield result
    _emit_summary(request.config)


def test_tsv_block_has_110_data_rows() -> None:
    assert len(MATRIX_ROWS) == EXPECTED_ROW_COUNT


def test_classification_matrix(evaluation: MatrixEvaluation | None) -> None:
    if evaluation is None:
        pytest.fail(f"classification unavailable; production module missing ({_IMPORT_ERROR})")
    assert not evaluation.mismatches, "\n".join(
        f"row {index}: {path!r} expected {expected!r}, got {actual!r}"
        for index, path, expected, actual in evaluation.mismatches
    )


def test_reject_path_rows_raise_value_error() -> None:
    validate = _allowlist_module().validate_canonical_relpath
    for path, expected in MATRIX_ROWS:
        if expected != "REJECT-PATH":
            continue
        with pytest.raises(ValueError):
            validate(path)


def test_quarantine_rows_match_hostile_executable_regex() -> None:
    hostile = _allowlist_module().HOSTILE_EXECUTABLE_QUARANTINE_REGEX
    for path, expected in MATRIX_ROWS:
        if expected != "QUARANTINE":
            continue
        assert hostile.match(path) is not None


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_dir_fd_containment(tmp_path: Path) -> None:
    allowlist = _allowlist_module()
    root = tmp_path / "root"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("ok", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    fd = allowlist.open_safe_path_fd(root, "sub/file.txt")
    try:
        assert os.read(fd, 2) == b"ok"
    finally:
        os.close(fd)

    resolved = allowlist.resolve_safe_disk_path(root, "sub/file.txt")
    assert Path(resolved) == (nested / "file.txt").resolve()

    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(root, "link/secret.txt")
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.resolve_safe_disk_path(root, "link/secret.txt")

    (root / "final-link").symlink_to(outside / "secret.txt")
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(root, "final-link")


# Prose-only regression rows from the spec, not part of the 110-row TSV block.
# Source: docs/design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md:3144-3159.
V82_V85_REGRESSION_ROWS: tuple[tuple[str, str], ...] = (
    ("plugins/X/storage/cache.dat", "E"),
    ("version_history.json.bak", "E"),
    ("plugins/X/playerdata/abc.dat", "E"),
    ("mods/.connector/x.jar", "E"),
    ("versions/26.3/x.jar", "E"),
    ("world/players/steve.dat", "E"),
    ("config/mymod/cache/x.json", "E"),
    ("XaeroWaypoints/x.txt", "E"),
    ("logs/kubejs-server.log", "E"),
    ("crafttweaker.log", "E"),
    ("journeymap/x.json", "E"),
    ("local/x.txt", "E"),
    ("debug/x.json", "E"),
    ("config/x.toml.bak", "E"),
    ("forgottenrelics/defaultconfigs/x.toml", "E"),
    ("plugins/floodgate/key.pem", "C"),
    ("config/ssl/server.key", "C"),
    ("config/ssl/keystore.p12", "C"),
    ("plugins/Geyser-Skin/jks/client.jks", "C"),
    ("plugins/Essentials/config/key.pem", "C"),
    ("voicechat/voicechat-server.properties", "C"),
    ("voicechat/simple-voice-chat/voicechat-server.properties", "C"),
    ("shaderpacks/sub/Iris.jar", "A-CAS"),
    ("shaderpacks/sub/Iris.zip", "A-CAS"),
    ("resourcepacks/sub/deep/Pack.jar", "A-CAS"),
    ("resourcepacks/sub/deep/Pack.zip", "A-CAS"),
)

SECRET_AND_VOICECHAT_PATHS: tuple[str, ...] = (
    "plugins/floodgate/key.pem",
    "config/ssl/server.key",
    "config/ssl/keystore.p12",
    "plugins/Geyser-Skin/jks/client.jks",
    "plugins/Essentials/config/key.pem",
    "voicechat/voicechat-server.properties",
    "voicechat/simple-voice-chat/voicechat-server.properties",
)


@pytest.mark.parametrize(("path", "expected"), V82_V85_REGRESSION_ROWS)
def test_v82_v85_regression_rows(path: str, expected: str) -> None:
    assert _allowlist_module().classify(path) == expected


def test_class_regex_invariants() -> None:
    allowlist = _allowlist_module()
    e_deny = allowlist.CLASS_E_DENYLIST_REGEX
    b_allow = allowlist.CLASS_B_CONFIG_ALLOWLIST_REGEX
    c_live = allowlist.CLASS_C_LIVE_STATE_REGEX
    a_jar = allowlist.CLASS_A_JAR_REGEX

    for path in (
        "plugins/X.jar",
        "mods/X.jar",
        "server.jar",
        "schematics/a.nbt",
        "shaderpacks/sub/Iris.jar",
        "resourcepacks/sub/deep/Pack.jar",
    ):
        assert e_deny.match(path) is None, path

    for path in ("onx-jars.lock.json", "kubejs/probe/x.json", *SECRET_AND_VOICECHAT_PATHS):
        assert b_allow.match(path) is None, path

    for path in SECRET_AND_VOICECHAT_PATHS:
        assert c_live.match(path) is not None, path
    assert c_live.match("ops.json.bak") is None
    assert a_jar.match("config/evil.jar") is None


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_dir_fd_root_is_symlink(tmp_path: Path) -> None:
    allowlist = _allowlist_module()
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    (real_root / "file.txt").write_text("ok", encoding="utf-8")
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(root_link, "file.txt")
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.resolve_safe_disk_path(root_link, "file.txt")


def test_dir_fd_root_identity_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowlist = _allowlist_module()
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_text("ok", encoding="utf-8")
    real = os.stat(root)
    original_fstat = os.fstat

    raw = list(real)
    raw[1] = real.st_ino + 1
    altered_stat = os.stat_result(raw)

    class _OsProxy:
        def __init__(self, target: object) -> None:
            self._target = target

        def fstat(self, _fd: int) -> os.stat_result:
            return altered_stat

        def __getattr__(self, name: str) -> object:
            return getattr(self._target, name)

    proxy = _OsProxy(os)
    monkeypatch.setattr(allowlist, "os", proxy)
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(root, "file.txt")
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.resolve_safe_disk_path(root, "file.txt")
    assert os.fstat is original_fstat


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_dir_fd_casefold_swapped_escape(tmp_path: Path) -> None:
    allowlist = _allowlist_module()
    root = tmp_path / "Server"
    root.mkdir()
    (root / "file.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path / "server"  # casefold-equal to the root basename
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    assert root.name != outside.name and root.name.casefold() == outside.name.casefold()

    (root / "esc").symlink_to(outside, target_is_directory=True)
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(root, "esc/secret.txt")
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.resolve_safe_disk_path(root, "esc/secret.txt")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_dir_fd_allow_create_parents(tmp_path: Path) -> None:
    allowlist = _allowlist_module()
    root = tmp_path / "root"
    root.mkdir()
    created = root / "a" / "b" / "file.txt"

    fd = allowlist.open_safe_path_fd(
        root,
        "a/b/file.txt",
        flags=os.O_CREAT | os.O_WRONLY,
        mode=0o644,
        allow_create_parents=True,
    )
    os.close(fd)
    assert created.is_file()

    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(allowlist.SymlinkEscapeError):
        allowlist.open_safe_path_fd(
            root,
            "link/x/file.txt",
            flags=os.O_CREAT | os.O_WRONLY,
            mode=0o644,
            allow_create_parents=True,
        )


# spec literal only; production constant wiring is P5.5 (UNVERIFIED)
@pytest.mark.parametrize(
    "line",
    [
        '[12:00:00 INFO]: Done (5.123s)! For help, type "help"',
        '[12:00:00] [Server thread/INFO]: Done (5s)! For help, type "help"',
        "[12:00:00] [ServerMain/INFO] [minecraft/DedicatedServer]: "
        'Done (5,5s)! For help, type "help"',
        "[12:00:00] [Server thread/INFO] [minecraft/DedicatedServer]: "
        'Done (5.0s)! For help, type "help"',
    ],
    ids=["paper", "vanilla-fabric", "neoforge-comma", "legacy-forge"],
)
def test_health_gate_regex_accepts_done_lines(line: str) -> None:
    assert HEALTH_GATE_DONE_REGEX.match(line) is not None


# spec literal only; production constant wiring is P5.5 (UNVERIFIED)
@pytest.mark.parametrize(
    "line",
    [
        "[Server thread/INFO]: <Player> Done (1.0s)!",
        '[12:00:00]: Done (5s)! For help, type "help"',
    ],
    ids=["chat-player-done", "missing-info"],
)
def test_health_gate_regex_rejects_non_boot_lines(line: str) -> None:
    assert HEALTH_GATE_DONE_REGEX.match(line) is None
