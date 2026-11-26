from __future__ import annotations

import io
import json
import zipfile

from app.modules.plugin.application.services.version_selector import (
    _mc_distance,
    select_best_version,
)
from app.modules.plugin.domain.aggregate import Plugin, PluginRegistry, PluginStatus
from app.modules.plugin.infrastructure.jar_metadata_parser import validate_addon_jar
from app.modules.plugin.infrastructure.providers.base import PluginVersionInfo
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


def _v(
    ver: str,
    *,
    loaders: list[str],
    game_versions: list[str],
    version_type: str = "release",
    date_published: str = "2026-01-01T00:00:00Z",
) -> PluginVersionInfo:
    return PluginVersionInfo(
        version_id=f"vid-{ver}-{'-'.join(loaders)}",
        project_id="proj-1",
        name=ver,
        version_number=ver,
        loaders=loaders,
        game_versions=game_versions,
        version_type=version_type,
        date_published=date_published,
    )


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_fallback_prefers_paper_over_bukkit_and_weighted_mc_distance() -> None:
    versions = [
        _v("1.4.40", loaders=["bukkit"], game_versions=["1.21.4"], date_published="2026-02-02T00:00:00Z"),
        _v("paper-1.5.66", loaders=["paper"], game_versions=["1.21.4"], date_published="2026-02-01T00:00:00Z"),
        _v("1.0.0", loaders=["paper"], game_versions=[]),  # must not crash on empty game_versions
    ]
    res = select_best_version("purpur", "1.21.11", versions)
    assert res.selected is not None
    assert res.selected.version_number == "paper-1.5.66"
    assert res.notice_kind == "version_mismatch"

    # Weighted MC distance: 1.21.4 must beat 1.20.1 for 1.21.1
    assert _mc_distance("1.21.1", "1.21.4") < _mc_distance("1.21.1", "1.20.1")


def test_release_beats_alpha_and_prefixed_version_beats_older_plain() -> None:
    versions = [
        _v("2.6.7", loaders=["bukkit"], game_versions=["1.21.11"]),
        _v("bukkit-2.6.21", loaders=["bukkit"], game_versions=["1.21.11"]),
        _v("3.0.0-alpha.1", loaders=["bukkit"], game_versions=["1.21.11"], version_type="alpha"),
    ]
    res = select_best_version("paper", "1.21.11", versions)
    assert res.selected is not None
    assert res.selected.version_number == "bukkit-2.6.21"


def test_universal_jar_validation_and_quilt_and_paper_deps() -> None:
    universal_proxy = _zip_bytes(
        {
            "plugin.yml": "name: UniversalPlugin\nversion: 1.0.0\n",
            "velocity-plugin.json": json.dumps({"id": "universal", "name": "UniversalPlugin", "version": "1.0.0"}),
        }
    )
    meta_vel = validate_addon_jar("Universal.jar", universal_proxy, server_type="velocity")
    assert meta_vel.loader == "velocity"

    universal_mod = _zip_bytes(
        {
            "fabric.mod.json": json.dumps({"id": "mymod", "name": "MyMod", "version": "1.0.0"}),
            "META-INF/neoforge.mods.toml": '[[mods]]\nmodId="mymod"\nversion="1.0.0"\ndisplayName="MyMod"\n',
        }
    )
    meta_neo = validate_addon_jar("MyMod.jar", universal_mod, server_type="neoforge")
    assert meta_neo.loader == "neoforge"

    quilt_jar = _zip_bytes(
        {
            "quilt.mod.json": json.dumps(
                {
                    "schema_version": 1,
                    "quilt_loader": {
                        "id": "qmod",
                        "version": "2.0.0",
                        "metadata": {"name": "QuiltMod"},
                    },
                }
            )
        }
    )
    meta_q = validate_addon_jar("QuiltMod.jar", quilt_jar, server_type="quilt")
    assert meta_q.loader == "quilt"
    assert meta_q.mod_id == "qmod"

    paper_jar = _zip_bytes(
        {
            "paper-plugin.yml": (
                "name: PaperPlugin\nversion: 1.0.0\n"
                "dependencies:\n  server:\n    Vault:\n      required: true\n    OptDep:\n      required: false\n"
            )
        }
    )
    meta_p = validate_addon_jar("PaperPlugin.jar", paper_jar, server_type="paper")
    assert meta_p.dependencies == ["Vault"]


def test_registry_ignores_platform_runtime_deps_and_matches_mod_id() -> None:
    sid = ServerId()
    reg = PluginRegistry(sid)
    dep = Plugin.install(
        plugin_id=PluginId(),
        server_id=sid,
        name="Fabric API",
        version=PluginVersion(1, 0, 0),
        mod_id="fabric-api",
    )
    dep._status = PluginStatus.ENABLED
    mod = Plugin.install(
        plugin_id=PluginId(),
        server_id=sid,
        name="CoolMod",
        version=PluginVersion(1, 0, 0),
        dependencies=["minecraft", "java", "fabricloader", "fabric-api"],
    )
    reg.add_plugin(dep)
    reg.add_plugin(mod)
    assert reg.can_enable(mod) is True
