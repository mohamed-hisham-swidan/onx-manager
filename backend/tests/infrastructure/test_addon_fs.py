from __future__ import annotations

import pytest

from app.core.exceptions import InvalidValueError
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    is_mod_server,
    sanitize_addon_filename,
    toggle_addon_file,
)


def test_get_addon_dir_name() -> None:
    assert get_addon_dir_name("fabric") == "mods"
    assert get_addon_dir_name("forge") == "mods"
    assert get_addon_dir_name("neoforge") == "mods"
    assert get_addon_dir_name("quilt") == "mods"
    assert get_addon_dir_name("paper") == "plugins"
    assert get_addon_dir_name("purpur") == "plugins"
    assert get_addon_dir_name("spigot") == "plugins"
    assert get_addon_dir_name("bukkit") == "plugins"
    assert get_addon_dir_name("vanilla") == "plugins"
    assert get_addon_dir_name(None) == "plugins"


def test_is_mod_server() -> None:
    assert is_mod_server("fabric") is True
    assert is_mod_server("forge") is True
    assert is_mod_server("neoforge") is True
    assert is_mod_server("quilt") is True
    assert is_mod_server("paper") is False
    assert is_mod_server("vanilla") is False
    assert is_mod_server(None) is False


def test_sanitize_addon_filename_valid(tmp_path) -> None:
    target = sanitize_addon_filename("test-mod-1.0.jar", tmp_path)
    assert target == tmp_path / "test-mod-1.0.jar"


def test_sanitize_addon_filename_path_traversal(tmp_path) -> None:
    # Basename strips ../../ so "../../test.jar" becomes "test.jar" inside tmp_path
    target = sanitize_addon_filename("../../test.jar", tmp_path)
    assert target == tmp_path / "test.jar"


def test_sanitize_addon_filename_invalid_extension(tmp_path) -> None:
    with pytest.raises(InvalidValueError) as exc:
        sanitize_addon_filename("malicious.sh", tmp_path)
    assert exc.value.details["field"] == "filename"

    with pytest.raises(InvalidValueError):
        sanitize_addon_filename("", tmp_path)

    with pytest.raises(InvalidValueError):
        sanitize_addon_filename("evil.jar\x00.exe", tmp_path)


def test_toggle_addon_file_disable_and_enable(tmp_path) -> None:
    mod_file = tmp_path / "my-mod.jar"
    mod_file.write_bytes(b"dummy")

    # 1. Disable active file
    disabled_path, renamed = toggle_addon_file(tmp_path, "my-mod.jar", enabled=False)
    assert renamed is True
    assert disabled_path == tmp_path / "my-mod.jar.disabled"
    assert not mod_file.exists()
    assert disabled_path.exists()

    # 2. Disable again (drift / idempotent)
    disabled_path2, renamed2 = toggle_addon_file(tmp_path, "my-mod.jar", enabled=False)
    assert renamed2 is False
    assert disabled_path2 == disabled_path

    # 3. Enable disabled file
    active_path, renamed3 = toggle_addon_file(tmp_path, "my-mod.jar.disabled", enabled=True)
    assert renamed3 is True
    assert active_path == mod_file
    assert mod_file.exists()
    assert not disabled_path.exists()

    # 4. Enable again (drift / idempotent)
    active_path2, renamed4 = toggle_addon_file(tmp_path, "my-mod.jar", enabled=True)
    assert renamed4 is False
    assert active_path2 == mod_file


def test_toggle_addon_file_missing_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        toggle_addon_file(tmp_path, "nonexistent.jar", enabled=False)

    with pytest.raises(FileNotFoundError):
        toggle_addon_file(tmp_path, "nonexistent.jar", enabled=True)
