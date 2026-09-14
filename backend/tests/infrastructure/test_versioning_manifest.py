import tempfile
from pathlib import Path

from app.modules.versioning.domain.value_objects import CommitManifest
from app.modules.versioning.infrastructure.manifest_builder import ManifestBuilder


def test_manifest_builder_captures_configs_and_mods() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv = Path(tmpdir)

        # 1. Root configs
        (srv / "server.properties").write_text(
            "motd=Hello World\nonline-mode=true\n", encoding="utf-8"
        )
        (srv / "spigot.yml").write_text(
            "settings:\n  save-user-cache-on-stop-only: false\n", encoding="utf-8"
        )

        # 2. config/ directory
        cfg_sub = srv / "config" / "subfolder"
        cfg_sub.mkdir(parents=True)
        (cfg_sub / "plugin_cfg.json").write_text('{"key": "value"}', encoding="utf-8")

        # 3. mods/ directory
        mods_dir = srv / "mods"
        mods_dir.mkdir()
        mod_jar = mods_dir / "fabric-api-0.90.0.jar"
        mod_jar.write_bytes(b"PK\x03\x04mockjarcontent")

        # Build manifest
        manifest = ManifestBuilder.build_manifest(
            srv,
            server_type="fabric",
            minecraft_version="1.21.1",
            env_vars={"JAVA_HOME": "/opt/java"},
            java_args="-Xmx4G",
        )

        assert isinstance(manifest, CommitManifest)
        assert manifest.server_type == "fabric"
        assert manifest.minecraft_version == "1.21.1"
        assert manifest.java_args == "-Xmx4G"
        assert manifest.env_vars == {"JAVA_HOME": "/opt/java"}

        # Configs check
        assert "server.properties" in manifest.configs
        assert "online-mode=true" in manifest.configs["server.properties"]
        assert "spigot.yml" in manifest.configs
        assert "config/subfolder/plugin_cfg.json" in manifest.configs

        # Mods check
        assert len(manifest.mods) == 1
        assert manifest.mods[0]["filename"] == "mods/fabric-api-0.90.0.jar"
        assert len(manifest.mods[0]["sha256"]) == 64

        # Serialization round-trip
        data = manifest.to_dict()
        restored = CommitManifest.from_dict(data)
        assert restored.server_type == manifest.server_type
        assert restored.configs == manifest.configs
        assert restored.mods == manifest.mods
