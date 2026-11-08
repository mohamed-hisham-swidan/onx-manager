import os

import pytest

from app.core.exceptions import PathContainmentError
from app.core.fs_utils import assert_inside_root


def test_valid_child(tmp_path):
    root = tmp_path / "server"
    child = root / "a" / "b"
    child.mkdir(parents=True)
    assert assert_inside_root(child, root) == child.resolve()


def test_root_itself_rejected(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        assert_inside_root(root, root)


def test_parent_rejected(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        assert_inside_root(tmp_path, root)


def test_sibling_prefix_rejected(tmp_path):
    root = tmp_path / "server"
    sibling = tmp_path / "server2"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(PathContainmentError):
        assert_inside_root(sibling, root)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlink_pointing_outside_rejected(tmp_path):
    root = tmp_path / "server"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(PathContainmentError):
        assert_inside_root(link, root)
