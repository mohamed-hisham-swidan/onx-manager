import zipfile

import pytest

from app.core.exceptions import InvalidJarError
from app.modules.plugin.infrastructure.jar_metadata_parser import (
    parse_jar_metadata,
    parse_jar_version,
)


def _create_jar(path, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for fname, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(fname, content)


def test_parse_plugin_yml(tmp_path) -> None:
    jar = tmp_path / "test-plugin.jar"
    _create_jar(jar, {"plugin.yml": "name: TestPlugin\nversion: 1.4.2\n"})
    assert parse_jar_version(str(jar)) == "1.4.2"


def test_parse_paper_plugin_yml(tmp_path) -> None:
    jar = tmp_path / "test-paper-plugin.jar"
    _create_jar(jar, {"paper-plugin.yml": "name: PaperPlugin\nversion: 2.0.0-rc1\n"})
    assert parse_jar_version(str(jar)) == "2.0.0-rc1"


def test_parse_fabric_mod_json(tmp_path) -> None:
    jar = tmp_path / "test-fabric.jar"
    _create_jar(jar, {"fabric.mod.json": '{"id": "test", "version": "0.15.0+1.20"}'})
    assert parse_jar_version(str(jar)) == "0.15.0+1.20"


def test_parse_quilt_mod_json(tmp_path) -> None:
    jar = tmp_path / "test-quilt.jar"
    _create_jar(jar, {"quilt.mod.json": '{"id": "quilt_test", "version": "1.0.1"}'})
    assert parse_jar_version(str(jar)) == "1.0.1"


def test_parse_mods_toml(tmp_path) -> None:
    jar = tmp_path / "test-forge.jar"
    toml_content = """
[[mods]]
modId = "testmod"
version = "2.1.0"
"""
    _create_jar(jar, {"META-INF/mods.toml": toml_content})
    assert parse_jar_version(str(jar)) == "2.1.0"


def test_parse_forge_placeholder_fallthrough_to_manifest(tmp_path) -> None:
    jar = tmp_path / "test-forge-placeholder.jar"
    toml_content = """
[[mods]]
modId = "testmod"
version = "${file.jarVersion}"
"""
    manifest_content = "Manifest-Version: 1.0\nImplementation-Version: 3.4.5\n"
    _create_jar(
        jar,
        {
            "META-INF/mods.toml": toml_content,
            "META-INF/MANIFEST.MF": manifest_content,
        },
    )
    assert parse_jar_version(str(jar)) == "3.4.5"


def test_parse_manifest_mf(tmp_path) -> None:
    jar = tmp_path / "test-manifest.jar"
    manifest_content = "Manifest-Version: 1.0\nImplementation-Version: 5.6.7\n"
    _create_jar(jar, {"META-INF/MANIFEST.MF": manifest_content})
    assert parse_jar_version(str(jar)) == "5.6.7"


def test_parse_mcmod_info(tmp_path) -> None:
    jar = tmp_path / "test-legacy.jar"
    _create_jar(jar, {"mcmod.info": '[{"modid": "legacy", "version": "1.7.10-1.0"}]'})
    assert parse_jar_version(str(jar)) == "1.7.10-1.0"


def test_corrupted_jar_returns_none(tmp_path) -> None:
    jar = tmp_path / "corrupt.jar"
    jar.write_bytes(b"not a real zip file")
    assert parse_jar_version(str(jar)) is None


def test_no_descriptor_returns_none(tmp_path) -> None:
    jar = tmp_path / "empty.jar"
    _create_jar(jar, {"some_other_file.txt": "hello"})
    assert parse_jar_version(str(jar)) is None


def test_parse_jar_metadata_invalid_jar_raises(tmp_path) -> None:
    bad_jar = tmp_path / "corrupt.jar"
    bad_jar.write_bytes(b"not a zip file at all")
    with pytest.raises(InvalidJarError):
        parse_jar_metadata(str(bad_jar))

    with pytest.raises(InvalidJarError):
        parse_jar_metadata(b"raw non-zip bytes")


def test_parse_jar_metadata_fabric_client_only(tmp_path) -> None:
    jar = tmp_path / "sodium-fabric.jar"
    content = {
        "fabric.mod.json": (
            '{"id": "sodium", "name": "Sodium", "version": "0.5.8", '
            '"environment": "client", "authors": ["jellysquid3"], '
            '"contact": {"homepage": "https://modrinth.com/mod/sodium"}, '
            '"depends": {"fabricloader": ">=0.15.0", "minecraft": "~1.20.4"}}'
        )
    }
    _create_jar(jar, content)
    meta = parse_jar_metadata(str(jar))
    assert meta.mod_id == "sodium"
    assert meta.name == "Sodium"
    assert meta.version == "0.5.8"
    assert meta.loader == "fabric"
    assert meta.is_client_only is True
    assert meta.warning is not None
    assert "Client-only mod detected" in meta.warning
    assert "fabricloader" in meta.dependencies
    assert "minecraft" in meta.dependencies
    assert meta.authors == ["jellysquid3"]
    assert meta.website == "https://modrinth.com/mod/sodium"


def test_parse_jar_metadata_forge_mods_toml(tmp_path) -> None:
    jar = tmp_path / "jei-forge.jar"
    toml_content = """
[[mods]]
modId = "jei"
displayName = "Just Enough Items"
version = "15.3.0.4"
description = "JEI item viewer"
authors = "mezz"
displayURL = "https://curseforge.com/minecraft/mc-mods/jei"

[[dependencies.jei]]
modId = "forge"
mandatory = true
versionRange = "[47.0.0,)"
"""
    _create_jar(jar, {"META-INF/mods.toml": toml_content})
    meta = parse_jar_metadata(str(jar))
    assert meta.mod_id == "jei"
    assert meta.name == "Just Enough Items"
    assert meta.version == "15.3.0.4"
    assert meta.loader == "forge"
    assert "forge" in meta.dependencies
    assert meta.authors == ["mezz"]
    assert meta.website == "https://curseforge.com/minecraft/mc-mods/jei"


def test_parse_jar_metadata_neoforge(tmp_path) -> None:
    jar = tmp_path / "test-neoforge.jar"
    toml_content = """
[[mods]]
modId = "neomod"
displayName = "Neo Mod"
version = "1.0.0"
clientSideOnly = true
"""
    _create_jar(jar, {"META-INF/neoforge.mods.toml": toml_content})
    meta = parse_jar_metadata(str(jar))
    assert meta.mod_id == "neomod"
    assert meta.loader == "neoforge"
    assert meta.is_client_only is True
    assert meta.warning is not None


def test_parse_universal_multiloader_jar_prefers_plugin_on_paper(tmp_path) -> None:
    jar = tmp_path / "universal-addon.jar"
    _create_jar(
        jar,
        {
            "fabric.mod.json": '{"id": "chunky", "name": "Chunky", "version": "1.4.0"}',
            "plugin.yml": "name: Chunky\nversion: 1.4.0\nmain: org.popcraft.chunky.ChunkyBukkit\n",
        },
    )
    # Default keeps historical Fabric-first behavior
    default_meta = parse_jar_metadata(str(jar))
    assert default_meta.loader == "fabric"

    # Paper/plugin servers prefer Bukkit/Paper descriptor over bundled Fabric metadata
    paper_meta = parse_jar_metadata(str(jar), preferred_server_type="paper")
    assert paper_meta.loader == "bukkit"
    assert paper_meta.name == "Chunky"

    # With paper-plugin.yml + fabric.mod.json on Purpur -> resolves to paper
    jar_paper = tmp_path / "universal-paper.jar"
    _create_jar(
        jar_paper,
        {
            "fabric.mod.json": '{"id": "bluemap", "name": "BlueMap", "version": "5.0"}',
            "paper-plugin.yml": (
                "name: BlueMap\nversion: '5.0'\nmain: de.bluecolored.bluemap.Paper\n"
            ),
        },
    )
    purpur_meta = parse_jar_metadata(str(jar_paper), preferred_server_type="purpur")
    assert purpur_meta.loader == "paper"

