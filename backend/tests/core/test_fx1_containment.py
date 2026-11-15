import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import PathContainmentError
from app.modules.server.application.services.filesystem_reconciliation import (
    FilesystemReconciliationService,
)
from app.modules.server.infrastructure.fs import LocalFileSystem
from app.modules.versioning.application.commands.remove_materialization import (
    RemoveMaterializationCommand,
    RemoveMaterializationHandler,
)
from app.modules.versioning.domain.entities import Materialization
from app.modules.versioning.domain.value_objects import PathClassification


def test_delete_dir_refuses_root_itself(tmp_path):
    root = tmp_path / "servers"
    root.mkdir()
    (root / "keep.txt").write_text("x")
    with pytest.raises(PathContainmentError):
        LocalFileSystem().delete_dir(str(root), root=str(root))
    assert (root / "keep.txt").exists()


def test_delete_dir_refuses_sibling_prefix(tmp_path):
    root = tmp_path / "server"
    sibling = tmp_path / "server2"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(PathContainmentError):
        LocalFileSystem().delete_dir(str(sibling), root=str(root))
    assert sibling.exists()


def test_delete_dir_refuses_symlink_escaping_root(tmp_path):
    root = tmp_path / "servers"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "data.txt").write_text("x")
    link = root / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathContainmentError):
        LocalFileSystem().delete_dir(str(link), root=str(root))
    assert (outside / "data.txt").exists()


def test_delete_dir_removes_valid_child(tmp_path):
    root = tmp_path / "servers"
    child = root / "a"
    child.mkdir(parents=True)
    (child / "f.txt").write_text("x")
    LocalFileSystem().delete_dir(str(child), root=str(root))
    assert not child.exists()


def _materialization(root_path: str) -> Materialization:
    return Materialization(id="m1", commit_id="c1", root_path=root_path, server_id="s1")


def _handler(mat: Materialization) -> RemoveMaterializationHandler:
    repo = MagicMock()
    repo.get_materialization = AsyncMock(return_value=mat)
    repo.save_materialization = AsyncMock()
    server_repo = MagicMock()
    server_repo.get = AsyncMock(return_value=SimpleNamespace(mode="advanced"))
    return RemoveMaterializationHandler(server_repo=server_repo, versioning_repo=repo)


@pytest.mark.asyncio
async def test_remove_materialization_deletes_valid_child(tmp_path):
    target = tmp_path / "srv" / ".onx" / "tests" / "t1"
    target.mkdir(parents=True)
    (target / "f.txt").write_text("x")
    result = await _handler(_materialization(str(target))).handle(
        RemoveMaterializationCommand(materialization_id="m1", server_id="s1")
    )
    assert result.success is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_remove_materialization_refuses_symlink_escape(tmp_path):
    container = tmp_path / "srv" / ".onx" / "tests"
    container.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("x")
    link = container / "t1"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathContainmentError):
        await _handler(_materialization(str(link))).handle(
            RemoveMaterializationCommand(materialization_id="m1", server_id="s1")
        )
    assert (outside / "data.txt").exists()


@pytest.mark.asyncio
async def test_remove_materialization_refuses_container_itself(tmp_path):
    container = tmp_path / "srv" / ".onx" / "tests"
    container.mkdir(parents=True)
    with pytest.raises(PathContainmentError):
        await _handler(_materialization(str(container))).handle(
            RemoveMaterializationCommand(materialization_id="m1", server_id="s1")
        )
    assert container.exists()


def test_is_outside_data_dir_rejects_sibling_prefix(tmp_path):
    data_dir = tmp_path / "servers"
    sibling = tmp_path / "servers2" / "x"
    data_dir.mkdir()
    sibling.mkdir(parents=True)
    server = SimpleNamespace(deployment=SimpleNamespace(root_path=str(sibling)))
    assert FilesystemReconciliationService._is_outside_data_dir(
        None, server, str(data_dir)
    )


def test_is_outside_data_dir_accepts_child(tmp_path):
    data_dir = tmp_path / "servers"
    child = data_dir / "x"
    child.mkdir(parents=True)
    server = SimpleNamespace(deployment=SimpleNamespace(root_path=str(child)))
    assert not FilesystemReconciliationService._is_outside_data_dir(
        None, server, str(data_dir)
    )


def test_stage_path_stays_inside_root(tmp_path):
    root = tmp_path / "srv" / ".onx" / "tests" / "t1"
    mat = _materialization(str(root))
    target = mat.stage_path("sub/file.txt", PathClassification.TRACKED)
    assert target == os.path.normpath(root / "sub" / "file.txt")


def test_stage_path_prefix_trick(tmp_path):
    root = tmp_path / "srv" / ".onx" / "tests" / "t1"
    mat = _materialization(str(root))
    # Sibling with same prefix (e.g. t1 vs t12)
    with pytest.raises(ValueError, match="escapes materialization root"):
        mat.stage_path("../t12/file.txt", PathClassification.TRACKED)
