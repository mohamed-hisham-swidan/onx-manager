"""P3-2 merge engine, dynamic Class-C, and native Git merge tests."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    DirtyWorktreeError,
    MergeConflictError,
)
from app.core.host_state import ensure_host_state_layout
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.dynamic_class_c import (
    DynamicClassCService,
)
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_merge import GitMergeService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.merge_engine import (
    merge_class_b_file,
    merge_lockfile_bytes,
    merge_text_diff3,
)
from app.modules.versioning.infrastructure.secret_scanner import (
    REDACTED_LITERAL,
    redact_conflict_value,
)

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode native Git is POSIX-only",
)


def _yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(value, sort_keys=False).encode("utf-8")


def _lockfile(mc: str = "1.20.4", version: str = "499") -> LockfileV21:
    return LockfileV21(
        format=2,
        mc=mc,
        loader=LoaderRef(id="paper", version=version),
        base_overrides={},
        files=(
            LockfileFile(
                path="plugins/sample.jar",
                sha256="a" * 64,
                size=3,
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
    )


def _lockfile_bytes(mc: str = "1.20.4", version: str = "499") -> bytes:
    return dump_lockfile(_lockfile(mc=mc, version=version))


# ---------------------------------------------------------------------------
# Pure merge engine
# ---------------------------------------------------------------------------


def test_yaml_diff3_first_preserves_comments_when_ast_matches():
    base = b"a: 1\n# keep me\nb: 2\n"
    ours = b"a: 10\n# keep me\nb: 2\n"
    theirs = b"a: 1\n# keep me\nb: 2\nc: 3\n"
    outcome = merge_class_b_file("config/app.yml", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.warnings == ()
    assert outcome.used_strategy == "diff3-preserved"
    assert outcome.content == b"a: 10\n# keep me\nb: 2\nc: 3\n"


def test_toml_diff3_first_preserves_comments_when_ast_matches():
    base = b"a = 1\n# keep me\nb = 2\n"
    ours = b"a = 10\n# keep me\nb = 2\n"
    theirs = b"a = 1\n# keep me\nb = 2\nc = 3\n"
    outcome = merge_class_b_file("config/app.toml", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.warnings == ()
    assert outcome.used_strategy == "diff3-preserved"
    assert b"# keep me" in (outcome.content or b"")
    assert b"c = 3" in (outcome.content or b"")


def test_diff3_clean_ast_but_textual_conflict_falls_back_with_exact_warning():
    base = b"a: 1\nb: 2\n"
    ours = b"a: 1\nx: 10\nb: 2\n"
    theirs = b"a: 1\ny: 20\nb: 2\n"
    outcome = merge_class_b_file("config/app.yml", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.used_strategy == "ast-canonical"
    assert outcome.warnings == (
        "'config/app.yml': textual diff3 could not preserve formatting cleanly; "
        "fell back to canonical yaml rewrite (comments may have been stripped)",
    )
    data = yaml.safe_load(outcome.content)
    assert data["x"] == 10
    assert data["y"] == 20

    tbase = b"a = 1\nb = 2\n"
    tours = b"a = 1\nx = 10\nb = 2\n"
    ttheirs = b"a = 1\ny = 20\nb = 2\n"
    toutcome = merge_class_b_file("config/app.toml", tbase, tours, ttheirs)
    assert toutcome.conflicts == ()
    assert toutcome.used_strategy == "ast-canonical"
    assert toutcome.warnings == (
        "'config/app.toml': textual diff3 could not preserve formatting cleanly; "
        "fell back to canonical toml rewrite (comments may have been stripped)",
    )


def test_textual_diff3_all_extensions_clean_and_conflict():
    for ext in [
        ".json5",
        ".snbt",
        ".cfg",
        ".conf",
        ".js",
        ".zs",
        ".sk",
        ".dsc",
        ".mcfunction",
        ".txt",
    ]:
        base = b"x=1\ny=2\n"
        ours = b"x=9\ny=2\n"
        theirs = b"x=1\ny=8\n"
        outcome = merge_text_diff3(f"f{ext}", base, ours, theirs)
        assert outcome.conflicts == ()
        content = outcome.content.decode()
        assert "x=9" in content and "y=8" in content
    base = b"x=1\n"
    ours = b"x=2\n"
    theirs = b"x=3\n"
    outcome = merge_text_diff3("f.txt", base, ours, theirs)
    assert len(outcome.conflicts) == 1
    assert outcome.conflicts[0].reason == "text-hunk-conflict"
    assert b"<<<<<<<" not in (outcome.content or b"")


def test_textual_diff3_boundary_insertion_is_clean():
    base = b"a\nb\nc\n"
    ours = b"A\nb\nc\n"
    theirs = b"a\nX\nb\nc\n"
    outcome = merge_text_diff3("f.txt", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.content == b"A\nX\nb\nc\n"

    mirrored = merge_text_diff3("f.txt", base, b"a\nX\nb\nc\n", b"A\nb\nc\n")
    assert mirrored.conflicts == ()
    assert mirrored.content == b"A\nX\nb\nc\n"

    same_slice = merge_text_diff3("f.txt", base, b"a\nO\nb\nc\n", b"a\nT\nb\nc\n")
    assert len(same_slice.conflicts) == 1


def test_textual_diff3_start_boundary_insertion_conflicts_without_data_loss():
    base = b"l1\nl2\n"

    outcome = merge_text_diff3("f.txt", base, b"L1\nl2\n", b"NEW\nl1\nl2\n")
    assert len(outcome.conflicts) == 1
    assert outcome.conflicts[0].reason == "text-hunk-conflict"
    assert outcome.conflicts[0].ours == "L1\n"
    assert "NEW" in outcome.conflicts[0].theirs
    assert b"<<<<<<<" not in (outcome.content or b"")

    mirrored = merge_text_diff3("f.txt", base, b"NEW\nl1\nl2\n", b"L1\nl2\n")
    assert len(mirrored.conflicts) == 1
    assert "NEW" in mirrored.conflicts[0].ours
    assert mirrored.conflicts[0].theirs == "L1\n"

    base2 = b"a\nb\n"
    mid = merge_text_diff3("f.txt", base2, b"a\nB\n", b"a\nX\nb\n")
    assert len(mid.conflicts) == 1
    assert mid.conflicts[0].ours == "B\n"
    assert "X" in mid.conflicts[0].theirs

    mirrored_mid = merge_text_diff3("f.txt", base2, b"a\nX\nb\n", b"a\nB\n")
    assert len(mirrored_mid.conflicts) == 1
    assert "X" in mirrored_mid.conflicts[0].ours
    assert mirrored_mid.conflicts[0].theirs == "B\n"


def test_scalar_array_atomic_by_default():
    base = {"arr": [1, 2]}
    ours = {"arr": [1, 2, 3]}
    theirs = {"arr": [1, 2, 4]}
    outcome = merge_class_b_file(
        "x.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts
    assert outcome.conflicts[0].reason == "scalar-array-conflict"


def test_set_mergeable_array_keys_spigot_and_type_aware_dedup():
    base = {"commands": {"silent-commandblock-console-worlds": [1, True, "a"]}}
    ours = {"commands": {"silent-commandblock-console-worlds": [1, True, "a", 2]}}
    theirs = {"commands": {"silent-commandblock-console-worlds": [1, "a", "b"]}}
    outcome = merge_class_b_file(
        "spigot.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts == ()
    worlds = yaml.safe_load(outcome.content)["commands"][
        "silent-commandblock-console-worlds"
    ]
    assert worlds == [1, "a", 2, "b"]
    assert not any(isinstance(w, bool) for w in worlds)

    base = {"MidTickChunkTasks": {"worlds": ["a", "b"]}}
    ours = {"MidTickChunkTasks": {"worlds": ["a", "b", "c"]}}
    theirs = {"MidTickChunkTasks": {"worlds": ["a", "d"]}}
    outcome = merge_class_b_file(
        "config/paper-global.yml",
        _yaml_bytes(base),
        _yaml_bytes(ours),
        _yaml_bytes(theirs),
    )
    assert outcome.conflicts == ()
    worlds = yaml.safe_load(outcome.content)["MidTickChunkTasks"]["worlds"]
    assert "c" in worlds and "d" in worlds


@pytest.mark.parametrize("pk", ["id", "name", "modid", "Id"])
def test_object_array_merges_by_primary_key(pk: str):
    base = {"items": [{pk: "k1", "v": "b"}, {pk: "k2", "v": "x"}]}
    ours = {"items": [{pk: "k1", "v": "ours"}, {pk: "k2", "v": "x"}]}
    theirs = {"items": [{pk: "k1", "v": "b"}, {pk: "k2", "v": "theirs"}]}
    outcome = merge_class_b_file(
        "x.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts == ()
    rows = {row[pk]: row for row in yaml.safe_load(outcome.content)["items"]}
    assert rows["k1"]["v"] == "ours"
    assert rows["k2"]["v"] == "theirs"


def test_object_array_recursion_and_delete_modify_conflict():
    base = {"items": [{"id": 1, "nested": {"a": 1, "b": 2}}]}
    ours = {"items": [{"id": 1, "nested": {"a": 10, "b": 2}}]}
    theirs = {"items": [{"id": 1, "nested": {"a": 1, "b": 20}}]}
    outcome = merge_class_b_file(
        "x.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts == ()
    nested = yaml.safe_load(outcome.content)["items"][0]["nested"]
    assert nested == {"a": 10, "b": 20}

    base = {"items": [{"id": 1, "v": "b"}, {"id": 2, "v": "keep"}]}
    ours = {"items": [{"id": 2, "v": "keep"}]}
    theirs = {"items": [{"id": 1, "v": "changed"}, {"id": 2, "v": "keep"}]}
    outcome = merge_class_b_file(
        "x.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts
    assert outcome.conflicts[0].key_path == "items[id=1]"
    assert outcome.conflicts[0].reason == "object-array-conflict"


def test_object_array_with_empty_dict_element_conflicts_without_crashing():
    base = {"items": [{"id": 1, "v": 1}]}
    ours = {"items": [{"id": 1, "v": 2}, {}]}
    theirs = {"items": [{"id": 1, "v": 3}, {}]}
    outcome = merge_class_b_file(
        "x.yml", _yaml_bytes(base), _yaml_bytes(ours), _yaml_bytes(theirs)
    )
    assert outcome.conflicts
    assert outcome.conflicts[0].reason in {
        "scalar-array-conflict",
        "object-array-conflict",
    }


def test_add_only_class_b_and_lockfile_take_changed_side():
    payload = b"a: 1\n"
    outcome = merge_class_b_file("config/app.yml", None, None, payload)
    assert outcome.content == payload
    assert outcome.conflicts == ()
    assert outcome.used_strategy == "fast-forward"

    outcome = merge_class_b_file("config/app.yml", None, payload, None)
    assert outcome.content == payload
    assert outcome.conflicts == ()
    assert outcome.used_strategy == "fast-forward"

    lockbytes = _lockfile_bytes()
    outcome = merge_lockfile_bytes("onx-jars.lock.json", None, None, lockbytes)
    assert outcome.conflicts == ()
    assert outcome.used_strategy == "fast-forward"
    assert outcome.content == lockbytes

    outcome = merge_lockfile_bytes("onx-jars.lock.json", None, lockbytes, None)
    assert outcome.conflicts == ()
    assert outcome.used_strategy == "fast-forward"
    assert outcome.content == lockbytes


def test_lockfile_single_side_validation_warns_on_corrupt_bytes():
    valid = _lockfile_bytes()
    corrupt = b"not-a-lockfile\n"
    outcome = merge_lockfile_bytes(
        "onx-jars.lock.json", valid, corrupt, valid
    )
    assert outcome.conflicts == ()
    assert outcome.content == corrupt
    assert outcome.used_strategy == "ours-fallback"
    assert outcome.warnings == (
        "'onx-jars.lock.json': structured parse failed during merge; "
        "kept target ('ours') bytes untouched",
    )


def test_lockfile_three_way_merges_scalar_fields():
    base = _lockfile_bytes()
    ours = _lockfile_bytes(mc="1.20.5")
    theirs = _lockfile_bytes(version="500")
    outcome = merge_lockfile_bytes("onx-jars.lock.json", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.warnings == ()
    assert outcome.used_strategy == "lockfile"
    merged = parse_lockfile(outcome.content)
    assert merged.mc == "1.20.5"
    assert merged.loader.version == "500"


def test_lockfile_three_way_field_conflict():
    base = _lockfile_bytes()
    ours = _lockfile_bytes(mc="1.20.5")
    theirs = _lockfile_bytes(mc="1.20.6")
    outcome = merge_lockfile_bytes("onx-jars.lock.json", base, ours, theirs)
    assert len(outcome.conflicts) == 1
    assert outcome.conflicts[0].key_path == "mc"
    assert outcome.conflicts[0].reason == "lockfile-conflict"


def test_multi_document_yaml_merges_each_document():
    base = b"a: 1\n---\nb: 2\n"
    ours = b"a: 10\n---\nb: 2\n"
    theirs = b"a: 1\n---\nb: 20\n"
    outcome = merge_class_b_file("config/multi.yml", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.warnings == ()
    assert outcome.used_strategy == "diff3-preserved"
    docs = list(yaml.safe_load_all(outcome.content))
    assert docs[0]["a"] == 10
    assert docs[1]["b"] == 20


def test_multi_document_yaml_count_mismatch_falls_back():
    base = b"a: 1\n---\nb: 2\n"
    ours = b"a: 10\n---\nb: 2\n"
    theirs = b"a: 1\n"
    outcome = merge_class_b_file("config/multi.yml", base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.content == ours
    assert any("structured parse failed" in w for w in outcome.warnings)


@pytest.mark.parametrize(
    ("relpath", "base", "ours", "theirs"),
    [
        ("x.yml", b"a: 1\n", b"a: 2\n:::bad\n", b"a: 3\n"),
        ("x.toml", b"a = 1\n", b"a = [\n", b"a = 3\n"),
        ("x.json", b'{"a": 1}\n', b"{bad", b'{"a": 3}\n'),
        ("x.properties", b"a=1\n", b"no-separator\n", b"a=3\n"),
    ],
)
def test_unparseable_structured_file_live_wins_with_warning(
    relpath: str, base: bytes, ours: bytes, theirs: bytes
):
    outcome = merge_class_b_file(relpath, base, ours, theirs)
    assert outcome.conflicts == ()
    assert outcome.content == ours
    assert any("structured parse failed" in w for w in outcome.warnings)


def test_conflict_payload_redacts_secrets_and_preserves_placeholders():
    val = redact_conflict_value("config.yml", "password", "secret123")
    assert val == REDACTED_LITERAL
    val2 = redact_conflict_value("config.yml", "password", "${ONX_SECRET_FOO}")
    assert val2 == "${ONX_SECRET_FOO}"
    val3 = redact_conflict_value("config.yml", "password", "none")
    assert val3 == "none"
    v = redact_conflict_value("x.txt", "lines:1-1", "token=AKIAIOSFODNN7EXAMPLE")
    assert REDACTED_LITERAL in v
    longstr = "a" * 3000
    r = redact_conflict_value("x.txt", "", longstr)
    assert len(r) == 2048


def test_merged_file_secret_scan_blocks_commit():
    from app.core.exceptions import SecretFileInGitForbiddenError
    from app.modules.versioning.infrastructure.secret_scanner import assert_no_secrets

    data = b"password: supersecretvalue\n"
    with pytest.raises(SecretFileInGitForbiddenError):
        assert_no_secrets("config.yml", data)


def test_http_409_error_contract_round_trips_details():
    from starlette.requests import Request

    from app.api.errors import conflict_error_handler

    conflicts = [
        {
            "path": "config/app.yml",
            "key_path": "a",
            "reason": "scalar-conflict",
            "base": 1,
            "ours": 2,
            "theirs": 3,
        }
    ]
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/servers/srv-1/versioning/merge",
            "headers": [(b"x-request-id", b"req-1")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "root_path": "",
        }
    )
    response = asyncio.run(
        conflict_error_handler(
            request, MergeConflictError(conflicts=conflicts, warnings=["w"])
        )
    )
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["code"] == "MERGE_CONFLICT"
    assert body["details"]["conflicts"] == conflicts
    assert body["details"]["warnings"] == ["w"]

    dirty = DirtyWorktreeError(branch="main", details={"dirty_paths": ["a.txt"]})
    response = asyncio.run(conflict_error_handler(request, dirty))
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["code"] == "DIRTY_WORKTREE"
    assert body["details"]["branch"] == "main"
    assert body["details"]["dirty_paths"] == ["a.txt"]


def _native_handler_context():
    from app.modules.versioning.application.commands.merge_commits import (
        MergeCommitsCommand,
        MergeCommitsHandler,
    )
    from app.modules.versioning.domain.entities import (
        BranchProtectionPolicy,
        ServerBranch,
    )
    from app.modules.versioning.domain.value_objects import BranchStatus

    branch = ServerBranch(
        id="branch-1",
        server_id="srv-1",
        name="release",
        head_commit_id="a" * 40,
        status=BranchStatus.ACTIVE,
        is_protected=True,
        protection_policy=BranchProtectionPolicy(allow_direct_commit=False, allow_force_bypass=True),
    )
    versioning_repo = AsyncMock()
    versioning_repo.get_branch_by_name.return_value = branch
    versioning_repo.get_commit.return_value = None
    versioning_repo.advance_branch_head_optimistic.return_value = True
    command = MergeCommitsCommand(
        server_id="srv-1",
        target_branch_name="release",
        parent_commit_ids=["a" * 40, "b" * 40],
        message="merge",
        author_id="user-1",
        force=True,
        force_reason="hotfix",
        caller_permissions=["admin:full"],
    )
    server = SimpleNamespace(server_type="paper", minecraft_version="1.20.4")
    context = SimpleNamespace(layout=object(), server_root=Path("/tmp"))
    return MergeCommitsHandler(), command, server, context, versioning_repo, branch


def _merge_result():
    from app.modules.versioning.infrastructure.git_merge import GitMergeResult

    return GitMergeResult(
        commit_id="c" * 40,
        target_branch_name="main",
        parent_commit_ids=("a" * 40, "b" * 40),
        base_commit_id=None,
        changed_files=(),
        warnings=(),
    )


def test_native_merge_force_bypass_writes_audit_log():
    handler, command, server, context, versioning_repo, _ = _native_handler_context()
    activity_repo = AsyncMock()
    with (
        patch(
            "app.modules.versioning.application.commands.merge_commits.DynamicClassCService"
        ) as dyn_cls,
        patch(
            "app.modules.versioning.application.commands.merge_commits.GitMergeService"
        ) as merge_cls,
    ):
        dyn_cls.return_value.list_paths.return_value = frozenset()
        merge_cls.return_value.merge.return_value = _merge_result()
        result = asyncio.run(
            handler._execute_native_git(
                command, server, context, versioning_repo, activity_repo, []
            )
        )
    assert result.success is True
    activity_repo.save.assert_awaited_once()
    log = activity_repo.save.await_args.args[0]
    assert log.event_type == "versioning.branch_protection_bypassed"
    assert log.details == {"branch": "release", "reason": "hotfix"}
    assert log.actor_id == "user-1"


def test_native_merge_db_cas_failure_raises_conflict():
    handler, command, server, context, versioning_repo, _ = _native_handler_context()
    versioning_repo.advance_branch_head_optimistic.return_value = False
    with (
        patch(
            "app.modules.versioning.application.commands.merge_commits.DynamicClassCService"
        ) as dyn_cls,
        patch(
            "app.modules.versioning.application.commands.merge_commits.GitMergeService"
        ) as merge_cls,
    ):
        dyn_cls.return_value.list_paths.return_value = frozenset()
        merge_cls.return_value.merge.return_value = _merge_result()
        with pytest.raises(ConflictError, match="Concurrent merge detected"):
            asyncio.run(
                handler._execute_native_git(
                    command, server, context, versioning_repo, AsyncMock(), []
                )
            )


# ---------------------------------------------------------------------------
# Dynamic Class-C service
# ---------------------------------------------------------------------------


def test_dynamic_class_c_promotion_exemption_auto_demote_and_reset(tmp_path):
    from app.core.host_state import HostStateLayout

    root = tmp_path / "host-state"
    for sub in (
        "server-meta",
        "class-c-vault",
        "quarantine",
        "lec",
        "cas",
        "repos",
        "locks",
        "journal",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    layout = HostStateLayout(
        root=root,
        server_meta=root / "server-meta",
        class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine",
        lec=root / "lec",
        cas=root / "cas",
        repos=root / "repos",
        locks=root / "locks",
        journal=root / "journal",
    )
    from sqlalchemy import create_engine

    from app.core.persistence.base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'dcc.db'}")
    Base.metadata.create_all(engine)
    engine.dispose()
    from sqlalchemy.orm import sessionmaker

    sf = sessionmaker(
        bind=create_engine(
            f"sqlite:///{tmp_path / 'dcc.db'}", connect_args={"check_same_thread": False}
        ),
        expire_on_commit=False,
    )
    svc = DynamicClassCService(layout, sync_session_factory=sf)
    server_id = "srv1"
    base = b"a: 1\n"
    live = b"a: 2\n"
    evalr = svc.evaluate_file(
        server_id, "config/foo.yml", live_bytes=live, baseline_bytes=base
    )
    assert evalr.action == "promoted_to_class_c"
    assert "config/foo.yml" in svc.list_paths(server_id)
    evalr2 = svc.evaluate_file(
        server_id, "server.properties", live_bytes=live, baseline_bytes=base
    )
    assert evalr2.action == "exempt"
    assert "server.properties" not in svc.list_paths(server_id)
    evalr3 = svc.evaluate_file(
        server_id, "config/foo.yml", live_bytes=base, baseline_bytes=base
    )
    assert evalr3.action == "auto_returned_to_class_b"
    assert "config/foo.yml" not in svc.list_paths(server_id)
    svc.evaluate_file(
        server_id, "config/foo.yml", live_bytes=live, baseline_bytes=base
    )
    assert svc.reset_to_class_b(server_id, "config/foo.yml") is True
    assert svc.reset_to_class_b(server_id, "config/foo.yml") is False
    svc.close()


def test_dynamic_class_c_service_requires_layout():
    with pytest.raises(ValueError, match="HostStateLayout is required"):
        DynamicClassCService(None)


# ---------------------------------------------------------------------------
# Real Git integration for GitMergeService
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_AUTHOR_NAME"] = "P32 Test"
    env["GIT_AUTHOR_EMAIL"] = "p32@example.com"
    env["GIT_COMMITTER_NAME"] = "P32 Test"
    env["GIT_COMMITTER_EMAIL"] = "p32@example.com"
    return env


def _git(repo_git: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--git-dir", str(repo_git), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
        text=True,
    )


def _wt_git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
        text=True,
    )


def _commit_file(worktree: Path, relpath: str, content: str, message: str) -> str:
    path = worktree / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _wt_git(worktree, "add", "--", relpath)
    _wt_git(worktree, "commit", "-m", message)
    return _wt_git(worktree, "rev-parse", "HEAD").stdout.strip()


def _refs(repo_git: Path) -> str:
    return _git(repo_git, "for-each-ref", "--format=%(refname) %(objectname)").stdout


@pytest.fixture
def git_env(tmp_path: Path):
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-1"
    (root / "config").mkdir(parents=True)
    (root / "config" / "app.yml").write_text("a: 1\nb: 2\n", encoding="utf-8")
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(
            LockfileFile(
                path="plugins/sample.jar",
                sha256="a" * 64,
                size=3,
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
    )
    init = GitRepositoryService(layout).initialize("srv-1", root, lockfile)
    branch = GitBranchService(layout).create_branch("srv-1", root, "feature", "main")
    return layout, root, init.repo_path, init.main_sha, branch.sha, branch.worktree_path


@POSIX_ONLY
def test_git_merge_dirty_target_and_source_worktree_refused(git_env):
    layout, root, repo_git, main_sha, feature_sha, feature_wt = git_env  # noqa: ARG001
    main_wt = root / ".onx" / "worktrees" / "main"
    before = _refs(repo_git)

    (main_wt / "config" / "app.yml").write_text("a: 99\nb: 2\n", encoding="utf-8")
    with pytest.raises(DirtyWorktreeError) as excinfo:
        GitMergeService(layout).merge(
            server_id="srv-1",
            server_root=root,
            target_branch_name="main",
            parent_commit_ids=[main_sha, feature_sha],
            message="merge",
        )
    assert excinfo.value.details["branch"] == "main"
    assert excinfo.value.details["dirty_paths"]
    assert _refs(repo_git) == before

    _wt_git(main_wt, "checkout", "--", "config/app.yml")
    (feature_wt / "config" / "app.yml").write_text("a: 98\nb: 2\n", encoding="utf-8")
    with pytest.raises(DirtyWorktreeError) as excinfo:
        GitMergeService(layout).merge(
            server_id="srv-1",
            server_root=root,
            target_branch_name="main",
            parent_commit_ids=[main_sha, "feature"],
            message="merge",
        )
    assert excinfo.value.details["branch"] == "feature"
    assert _refs(repo_git) == before


@POSIX_ONLY
def test_git_merge_conflict_makes_zero_writes(git_env):
    layout, root, repo_git, main_sha, feature_sha, feature_wt = git_env  # noqa: ARG001
    main_wt = root / ".onx" / "worktrees" / "main"
    main_head = _commit_file(main_wt, "config/app.yml", "a: 100\nb: 2\n", "main edit")
    feature_head = _commit_file(
        feature_wt, "config/app.yml", "a: 200\nb: 2\n", "feature edit"
    )
    before_refs = _refs(repo_git)
    before_head = _wt_git(main_wt, "rev-parse", "HEAD").stdout.strip()
    before_bytes = (main_wt / "config" / "app.yml").read_bytes()

    with pytest.raises(MergeConflictError) as excinfo:
        GitMergeService(layout).merge(
            server_id="srv-1",
            server_root=root,
            target_branch_name="main",
            parent_commit_ids=[main_head, feature_head],
            message="conflicting merge",
        )
    assert excinfo.value.details["conflicts"]
    assert _refs(repo_git) == before_refs
    assert _wt_git(main_wt, "rev-parse", "HEAD").stdout.strip() == before_head
    assert (main_wt / "config" / "app.yml").read_bytes() == before_bytes
    markers = subprocess.run(
        ["grep", "-r", "<<<<<<<", str(main_wt)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert markers.returncode != 0


@POSIX_ONLY
def test_git_merge_clean_creates_two_parent_commit_and_syncs_worktree(git_env):
    layout, root, repo_git, main_sha, feature_sha, feature_wt = git_env  # noqa: ARG001
    main_wt = root / ".onx" / "worktrees" / "main"
    main_head = _commit_file(main_wt, "config/app.yml", "a: 5\nb: 2\n", "main edit")
    feature_head = _commit_file(
        feature_wt, "config/app.yml", "a: 1\nb: 20\n", "feature edit"
    )

    result = GitMergeService(layout).merge(
        server_id="srv-1",
        server_root=root,
        target_branch_name="main",
        parent_commit_ids=[main_head, feature_head],
        message="clean merge",
    )
    assert len(result.commit_id) == 40
    assert result.parent_commit_ids == (main_head, feature_head)
    assert "config/app.yml" in result.changed_files
    assert _git(repo_git, "rev-parse", "refs/heads/main").stdout.strip() == result.commit_id
    parents = _git(repo_git, "cat-file", "-p", result.commit_id).stdout.splitlines()
    parent_lines = [line for line in parents if line.startswith("parent ")]
    assert parent_lines == [f"parent {main_head}", f"parent {feature_head}"]
    assert _wt_git(main_wt, "rev-parse", "HEAD").stdout.strip() == result.commit_id
    assert (main_wt / "config" / "app.yml").read_text(encoding="utf-8") == "a: 5\nb: 20\n"


@POSIX_ONLY
def test_git_merge_deletion_is_not_resurrected_as_empty_blob(git_env):
    layout, root, repo_git, main_sha, feature_sha, feature_wt = git_env  # noqa: ARG001
    main_wt = root / ".onx" / "worktrees" / "main"
    (main_wt / "mods").mkdir(exist_ok=True)
    (main_wt / "mods" / "old.jar").write_bytes(b"jar-bytes")
    _wt_git(main_wt, "add", "--", "mods/old.jar")
    _wt_git(main_wt, "commit", "-m", "track legacy jar")
    legacy = GitBranchService(layout).create_branch(
        "srv-1", root, "legacy", start_point="main"
    )
    _wt_git(main_wt, "rm", "mods/old.jar")
    _wt_git(main_wt, "commit", "-m", "delete jar on main")
    _wt_git(legacy.worktree_path, "rm", "mods/old.jar")
    _wt_git(legacy.worktree_path, "commit", "-m", "delete jar on feature")
    main_head = _wt_git(main_wt, "rev-parse", "HEAD").stdout.strip()
    legacy_head = _wt_git(legacy.worktree_path, "rev-parse", "HEAD").stdout.strip()

    result = GitMergeService(layout).merge(
        server_id="srv-1",
        server_root=root,
        target_branch_name="main",
        parent_commit_ids=[main_head, legacy_head],
        message="delete both",
    )
    tree = _git(repo_git, "ls-tree", "-r", "--name-only", result.commit_id).stdout
    assert "mods/old.jar" not in tree.splitlines()
    assert not (main_wt / "mods" / "old.jar").exists()


@POSIX_ONLY
def test_git_merge_skips_dynamic_class_c_paths_with_warning(git_env):
    layout, root, repo_git, main_sha, feature_sha, feature_wt = git_env  # noqa: ARG001
    feature_head = _commit_file(
        feature_wt,
        "plugins/dyn/config.yml",
        "runtime: true\n",
        "add runtime path",
    )
    result = GitMergeService(layout).merge(
        server_id="srv-1",
        server_root=root,
        target_branch_name="main",
        parent_commit_ids=[main_sha, feature_head],
        message="skip class c",
        dynamic_class_c={"plugins/dyn/config.yml"},
    )
    tree = _git(repo_git, "ls-tree", "-r", "--name-only", result.commit_id).stdout
    assert "plugins/dyn/config.yml" not in tree.splitlines()
    assert (
        "'plugins/dyn/config.yml' is classified as Class C and was excluded "
        "from the merged Git tree"
    ) in result.warnings


def test_redteam_dynamic_c_standalone_and_async(tmp_path):
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.host_state import HostStateLayout
    from app.core.persistence.base import Base

    root = tmp_path / "hs"
    for sub in ("server-meta", "class-c-vault", "quarantine", "lec", "cas", "repos", "locks", "journal"):  # noqa: E501
        (root / sub).mkdir(parents=True, exist_ok=True)
    layout = HostStateLayout(
        root=root, server_meta=root / "server-meta", class_c_vault=root / "class-c-vault",
        quarantine=root / "quarantine", lec=root / "lec", cas=root / "cas",
        repos=root / "repos", locks=root / "locks", journal=root / "journal",
    )
    base = b"a: 1\n"
    live = b"a: 2\n"

    # Standalone fallback (no factories/global DB): own file-backed SQLite vault.
    from app.core.persistence.db import database

    saved_engine, saved_factory = database._engine, database._session_factory
    database._engine = None
    database._session_factory = None
    try:
        standalone = DynamicClassCService(layout)
        assert standalone._is_async is False
        assert standalone.list_paths("s-standalone") == frozenset()
        assert (
            standalone.evaluate_file(
                "s-standalone", "config/foo.yml", live_bytes=live, baseline_bytes=base
            ).action
            == "promoted_to_class_c"
        )
        assert "config/foo.yml" in standalone.list_paths("s-standalone")
        standalone.close()
    finally:
        database._engine, database._session_factory = saved_engine, saved_factory

    # Explicit sync factory.
    db_path = tmp_path / "dcc.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    sf = sessionmaker(bind=create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}), expire_on_commit=False)  # noqa: E501
    svc = DynamicClassCService(layout, sync_session_factory=sf)
    assert svc.list_paths("s1") == frozenset()
    svc.close()

    # Async in-memory session factory.
    async def run_async_mode():
        async_engine = create_async_engine("sqlite+aiosqlite://")
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async_sf = async_sessionmaker(bind=async_engine, expire_on_commit=False)
        asvc = DynamicClassCService(layout, session_factory=async_sf)
        assert asvc._is_async is True
        assert asvc.list_paths("s-async") == frozenset()
        assert (
            asvc.evaluate_file(
                "s-async", "config/foo.yml", live_bytes=live, baseline_bytes=base
            ).action
            == "promoted_to_class_c"
        )
        assert "config/foo.yml" in asvc.list_paths("s-async")
        asvc.close()
        await async_engine.dispose()

    asyncio.run(run_async_mode())

    from app.modules.versioning.infrastructure.dynamic_class_c import canonical_config_ast_sha256
    # multi-doc canonical AST
    data = b"a: 1\n---\nb: 2\n"
    ok, sha = canonical_config_ast_sha256("x.yml", data)
    assert ok is True and sha is not None


def test_redteam_redact_json_and_sensitive_containers():
    v = redact_conflict_value("config/app.json", "", '{\n  "password": "supersecret123"\n}')
    assert "supersecret123" not in v
    v2 = redact_conflict_value("config/app.yml", "auth_token", {"raw": "ghp_123456789012345678901234567890123456", "password": "hunter2"})  # noqa: E501
    assert v2 == REDACTED_LITERAL
    v3 = redact_conflict_value("x.txt", "", "webhook_url: https://example.com/hook?token=abc")
    assert "https://example.com/hook?token=abc" not in v3 or REDACTED_LITERAL in v3
    v4 = redact_conflict_value("x.txt", "redis[id=1].pass", "secret")
    # normalize
    assert v4 == REDACTED_LITERAL or v4 == "secret"  # placeholder? no, redacted
    assert v4 == REDACTED_LITERAL


def test_redteam_conflict_handler_json_serializable():
    import asyncio
    from datetime import date

    from fastapi import Request

    from app.api.errors import conflict_error_handler
    from app.core.exceptions import MergeConflictError

    async def run():
        scope = {"type": "http", "headers": [], "path": "/"}
        req = Request(scope)
        exc = MergeConflictError(conflicts=[{"path": "a.yml", "key_path": "d", "reason": "scalar-conflict", "base": date(2026,1,2), "ours": date(2026,1,3), "theirs": date(2026,1,4)}], warnings=[])  # noqa: E501
        resp = await conflict_error_handler(req, exc)
        assert resp.status_code == 409
        body = resp.body.decode()
        assert "date" not in body or "2026" in body
    asyncio.get_event_loop().run_until_complete(run())


def test_redteam_multidoc_and_invalid_utf8():
    outcome = merge_class_b_file("a.yml", None, b"a: 1\n---\nb: 2\n", b"a: 1\n---\nc: 3\n")
    assert outcome.conflicts == ()
    assert list(yaml.safe_load_all(outcome.content)) == [{"a": 1}, {"b": 2, "c": 3}]

    base = b"a: 1\n---\nb: 2\n"
    ours = b"a: 1\ny: 9\n---\nb: 2\n"
    theirs = b"a: 1\nz: 8\n---\nb: 2\n"
    outcome3 = merge_class_b_file("m.yml", base, ours, theirs)
    assert outcome3.conflicts == ()
    assert outcome3.used_strategy == "ast-canonical"
    assert list(yaml.safe_load_all(outcome3.content)) == [
        {"a": 1, "y": 9, "z": 8},
        {"b": 2},
    ]

    outcome2 = merge_class_b_file("a.yml", b"a: 1\n", b"\xff\xfe", b"a: 2\n")
    assert outcome2.conflicts == ()
    assert outcome2.content == b"\xff\xfe" or outcome2.warnings


def _native_merge_mocks():
    from unittest.mock import AsyncMock, MagicMock

    server_repo = MagicMock()
    server = MagicMock()
    server.server_type = "vanilla"
    server.minecraft_version = "1.20"
    server_repo.get = AsyncMock(return_value=server)
    versioning_repo = MagicMock()
    versioning_repo.get_branch_by_name = AsyncMock(return_value=None)
    ctx = MagicMock()
    ctx.layout = MagicMock()
    ctx.server_root = "/tmp"
    merge_result = MagicMock(
        commit_id="c1",
        target_branch_name="main",
        parent_commit_ids=("a", "b"),
        changed_files=(),
        warnings=(),
    )
    mock_merge = MagicMock()
    mock_merge.merge = MagicMock(return_value=merge_result)
    return server, versioning_repo, ctx, mock_merge


def test_native_merge_into_main_allowed_without_force():
    import asyncio
    from unittest.mock import MagicMock, patch

    from app.modules.versioning.application.commands import merge_commits as mc
    from app.modules.versioning.application.commands.merge_commits import (
        MergeCommitsCommand,
        MergeCommitsHandler,
    )

    server, versioning_repo, ctx, mock_merge = _native_merge_mocks()

    async def run():
        handler = MergeCommitsHandler(server_repo=MagicMock(), versioning_repo=versioning_repo)
        cmd = MergeCommitsCommand(
            server_id="s1",
            target_branch_name="main",
            parent_commit_ids=["a", "b"],
            message="m",
        )
        with (
            patch.object(mc, "git_branch_context", lambda _s: ctx),
            patch.object(
                mc,
                "DynamicClassCService",
                lambda _layout: MagicMock(list_paths=lambda _sid: frozenset()),
            ),
            patch.object(mc, "GitMergeService", lambda _layout: mock_merge),
        ):
            res = await handler._execute_native_git(
                cmd, server, ctx, versioning_repo, None, []
            )
            assert res.success is True

    asyncio.run(run())


def test_redteam_custom_protected_branch_force_bypass_audited():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.versioning.application.commands import merge_commits as mc
    from app.modules.versioning.application.commands.merge_commits import (
        MergeCommitsCommand,
        MergeCommitsHandler,
    )
    from app.modules.versioning.domain.entities import BranchProtectionPolicy, ServerBranch
    from app.modules.versioning.domain.value_objects import BranchStatus

    server, versioning_repo, ctx, mock_merge = _native_merge_mocks()
    versioning_repo.get_commit = AsyncMock(return_value=None)
    versioning_repo.save_commit = AsyncMock()
    versioning_repo.advance_branch_head_optimistic = AsyncMock(return_value=True)
    versioning_repo.get_branch_by_name.return_value = ServerBranch(
        id="b-rel",
        server_id="s1",
        name="release",
        head_commit_id="a",
        status=BranchStatus.ACTIVE,
        is_protected=True,
        protection_policy=BranchProtectionPolicy(allow_direct_commit=False, allow_force_bypass=True),
    )
    activity_repo = MagicMock()
    activity_repo.save = AsyncMock()

    async def run():
        handler = MergeCommitsHandler(server_repo=MagicMock(), versioning_repo=versioning_repo)
        cmd = MergeCommitsCommand(
            server_id="s1",
            target_branch_name="release",
            parent_commit_ids=["a", "b"],
            message="m",
            author_id="u1",
            force=True,
            force_reason="emergency",
            caller_permissions=["admin:full"],
        )
        with (
            patch.object(mc, "git_branch_context", lambda _s: ctx),
            patch.object(
                mc,
                "DynamicClassCService",
                lambda _layout: MagicMock(list_paths=lambda _sid: frozenset()),
            ),
            patch.object(mc, "GitMergeService", lambda _layout: mock_merge),
        ):
            result = await handler._execute_native_git(
                cmd, server, ctx, versioning_repo, activity_repo, []
            )
        assert result.success is True
        activity_repo.save.assert_awaited_once()
        audit = activity_repo.save.await_args.args[0]
        assert audit.event_type == "versioning.branch_protection_bypassed"
        assert audit.details == {"branch": "release", "reason": "emergency"}

    asyncio.run(run())
