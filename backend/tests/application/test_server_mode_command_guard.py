from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import exceptions as core_exceptions
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel

SERVER_ID = "srv-mode-gate-cmd"
COMMANDS = "app.modules.versioning.application.commands"

# (module, handler class, command factory) — every versioning command that has a route.
CASES = [
    (
        "archive_branch",
        "ArchiveBranchHandler",
        lambda: _cmd("archive_branch", "ArchiveBranchCommand", name="main"),
    ),
    (
        "auto_commit_live_changes",
        "AutoCommitLiveChangesHandler",
        lambda: _cmd("auto_commit_live_changes", "AutoCommitLiveChangesCommand", branch="main"),
    ),
    (
        "branch_protection",
        "SetBranchProtectionHandler",
        lambda: _cmd("branch_protection", "SetBranchProtectionCommand", branch_name="main"),
    ),
    (
        "branch_protection",
        "RemoveBranchProtectionHandler",
        lambda: _cmd("branch_protection", "RemoveBranchProtectionCommand", branch_name="main"),
    ),
    (
        "confirm_import_review",
        "ConfirmImportReviewHandler",
        lambda: _cmd("confirm_import_review", "ConfirmImportReviewCommand", review_id="rev-1"),
    ),
    (
        "create_branch",
        "CreateBranchHandler",
        lambda: _cmd("create_branch", "CreateBranchCommand", name="feature"),
    ),
    (
        "create_commit",
        "CreateCommitHandler",
        lambda: _cmd("create_commit", "CreateCommitCommand", message="m"),
    ),
    (
        "create_materialization",
        "CreateMaterializationHandler",
        lambda: _cmd(
            "create_materialization",
            "CreateMaterializationCommand",
            revision_type="commit",
            ref="c1",
        ),
    ),
    (
        "create_tag",
        "CreateTagHandler",
        lambda: _cmd("create_tag", "CreateTagCommand", name="v1", commit_id="c1"),
    ),
    (
        "discard_test",
        "DiscardTestHandler",
        lambda: _cmd("discard_test", "DiscardTestCommand", test_id="test-1"),
    ),
    (
        "dismiss_import_review",
        "DismissImportReviewHandler",
        lambda: _cmd("dismiss_import_review", "DismissImportReviewCommand", review_id="rev-1"),
    ),
    (
        "merge_commits",
        "MergeCommitsHandler",
        lambda: _cmd(
            "merge_commits",
            "MergeCommitsCommand",
            target_branch_name="main",
            parent_commit_ids=["c1"],
            message="m",
        ),
    ),
    (
        "remove_materialization",
        "RemoveMaterializationHandler",
        lambda: _cmd(
            "remove_materialization",
            "RemoveMaterializationCommand",
            materialization_id="mat-1",
        ),
    ),
    (
        "revert_import_review",
        "RevertImportReviewHandler",
        lambda: _cmd("revert_import_review", "RevertImportReviewCommand", review_id="rev-1"),
    ),
    (
        "run_isolated_test",
        "RunIsolatedTestHandler",
        lambda: _cmd("run_isolated_test", "RunIsolatedTestCommand"),
    ),
    (
        "set_materialization_edit_mode",
        "SetMaterializationEditModeHandler",
        lambda: _cmd(
            "set_materialization_edit_mode",
            "SetMaterializationEditModeCommand",
            materialization_id="mat-1",
            enabled=True,
        ),
    ),
    (
        "test_definitions",
        "CreateTestDefinitionHandler",
        lambda: _cmd("test_definitions", "CreateTestDefinitionCommand", name="def"),
    ),
    (
        "test_definitions",
        "UpdateTestDefinitionHandler",
        lambda: _cmd("test_definitions", "UpdateTestDefinitionCommand", definition_id="def-1"),
    ),
    (
        "test_definitions",
        "DeleteTestDefinitionHandler",
        lambda: _cmd("test_definitions", "DeleteTestDefinitionCommand", definition_id="def-1"),
    ),
    (
        "write_materialized_file",
        "WriteMaterializedFileHandler",
        lambda: _cmd(
            "write_materialized_file",
            "WriteMaterializedFileCommand",
            materialization_id="mat-1",
            path="a.txt",
            content="x",
        ),
    ),
]

CASE_IDS = [f"{handler}" for _, handler, _ in CASES]


def _cmd(module_name: str, class_name: str, **fields):
    module = importlib.import_module(f"{COMMANDS}.{module_name}")
    command_type = getattr(module, class_name)
    return command_type(server_id=SERVER_ID, **fields)


class _SimpleRepo:
    async def get(self, id: Any) -> SimpleNamespace:
        return SimpleNamespace(id=str(id), mode="simple")


def _handler(module_name: str, handler_name: str):
    module = importlib.import_module(f"{COMMANDS}.{module_name}")
    return getattr(module, handler_name)(server_repo=_SimpleRepo())


async def _seed_simple_server() -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="simple-cmd",
                server_type="vanilla",
                minecraft_version="1.20.4",
                status="STOPPED",
                port=25565,
            )
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "handler_name", "command_factory"), CASES, ids=CASE_IDS)
async def test_simple_server_command_raises_mode_disabled(
    module_name: str, handler_name: str, command_factory
) -> None:
    error_type = core_exceptions.ServerModeVersioningDisabledError
    await _seed_simple_server()

    handler = _handler(module_name, handler_name)
    with pytest.raises(error_type):
        await handler.handle(command_factory())
