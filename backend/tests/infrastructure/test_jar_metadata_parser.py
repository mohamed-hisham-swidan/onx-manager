import zipfile

from app.modules.plugin.infrastructure.jar_metadata_parser import parse_jar_version


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
