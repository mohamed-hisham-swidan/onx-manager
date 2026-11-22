"""P5.5-3 tests for hash-only compatibility matrix, BFS, and 3-way config merge."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.exceptions import ConflictError, MergeConflictError, UpgradeBlockerError
from app.modules.plugin.infrastructure.providers.base import (
    PluginFile,
    PluginVersionInfo,
    PluginVersionsPage,
)
from app.modules.plugin.infrastructure.providers.modrinth import (
    ModrinthDependency,
    ModrinthProjectMeta,
    ModrinthVersionRecord,
)
from app.modules.versioning.application.modpack_lockfile_builder import (
    store_base_overrides_in_cas,
)
from app.modules.versioning.application.upgrade_merge import (
    assert_tree_ready_for_upgrade_export,
    merge_upgrade_configs,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.modpack_parser import (
    InstallPlan,
    InstallPlanFile,
    ManualDownloadBlocker,
)
from app.modules.versioning.infrastructure.upgrade_matrix import (
    MatrixStatus,
    build_compatibility_matrix,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="Uses ArtifactCas (POSIX-only); Windows = Simple-only",
)


def _hashes(payload: bytes) -> tuple[str, str, str]:
    return (
        hashlib.sha256(payload).hexdigest(),
        hashlib.sha512(payload).hexdigest(),
        hashlib.sha1(payload).hexdigest(),
    )


class FakeModrinthClient:
    """Strict hash-only fake ModrinthProvider that fails if search() is ever called."""

    def __init__(
        self,
        *,
        version_files: dict[str, ModrinthVersionRecord] | None = None,
        updates: dict[str, ModrinthVersionRecord] | None = None,
        versions_by_id: dict[str, ModrinthVersionRecord] | None = None,
        projects_by_id: dict[str, ModrinthProjectMeta] | None = None,
        project_versions: dict[str, list[ModrinthVersionRecord | PluginVersionInfo]] | None = None,
    ) -> None:
        self.version_files = version_files or {}
        self.updates = updates or {}
        self.versions_by_id = versions_by_id or {}
        self.projects_by_id = projects_by_id or {}
        self.project_versions = project_versions or {}
        self.lookup_files_calls: list[list[str]] = []
        self.lookup_updates_calls: list[list[str]] = []
        self.get_versions_calls: list[list[str]] = []

    async def search(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        del args, kwargs
        raise AssertionError("ModrinthProvider.search() must NEVER be called by upgrade matrix")

    async def lookup_version_files_by_hashes(
        self, hashes: list[str], *, algorithm: str = "sha512"
    ) -> dict[str, ModrinthVersionRecord]:
        assert algorithm == "sha512"
        self.lookup_files_calls.append(list(hashes))
        return {h: self.version_files[h] for h in hashes if h in self.version_files}

    async def lookup_version_updates_by_hashes(
        self,
        hashes: list[str],
        *,
        loaders: list[str],
        game_versions: list[str],
        algorithm: str = "sha512",
        version_types: tuple[str, ...] = ("release",),
    ) -> dict[str, ModrinthVersionRecord]:
        del loaders, game_versions, version_types
        assert algorithm == "sha512"
        self.lookup_updates_calls.append(list(hashes))
        return {h: self.updates[h] for h in hashes if h in self.updates}

    async def get_versions_by_ids(
        self, version_ids: list[str]
    ) -> dict[str, ModrinthVersionRecord]:
        self.get_versions_calls.append(list(version_ids))
        return {vid: self.versions_by_id[vid] for vid in version_ids if vid in self.versions_by_id}

    async def get_projects_by_ids(
        self, project_ids: list[str]
    ) -> dict[str, ModrinthProjectMeta]:
        return {pid: self.projects_by_id[pid] for pid in project_ids if pid in self.projects_by_id}

    async def get_project_versions(
        self, project_id: str, *, limit: int | None = None, offset: int = 0
    ) -> PluginVersionsPage:
        del limit, offset
        items = self.project_versions.get(project_id, [])
        converted = [
            PluginVersionInfo(
                version_id=it.version_id,
                project_id=it.project_id,
                name=it.name,
                version_number=it.version_number,
                game_versions=list(it.game_versions),
                loaders=list(it.loaders),
                files=list(it.files),
                dependencies=[d.project_id for d in it.dependencies if d.project_id],
                date_published=it.date_published,
            )
            if isinstance(it, ModrinthVersionRecord)
            else it
            for it in items
        ]
        for it in items:
            if isinstance(it, ModrinthVersionRecord):
                self.versions_by_id.setdefault(it.version_id, it)
        return PluginVersionsPage(items=converted, total=len(converted))


def _ver(
    vid: str,
    pid: str,
    *,
    filename: str = "mod.jar",
    url: str = "https://cdn.modrinth.com/data/x/mod.jar",
    sha512: str = "",
    sha1: str = "",
    environment: str | None = "client_and_server",
    game_versions: tuple[str, ...] = ("1.21.1",),
    loaders: tuple[str, ...] = ("fabric",),
    deps: tuple[ModrinthDependency, ...] = (),
    version_type: str = "release",
) -> ModrinthVersionRecord:
    return ModrinthVersionRecord(
        version_id=vid,
        project_id=pid,
        name=vid,
        version_number="1.0.0",
        version_type=version_type,
        game_versions=game_versions,
        loaders=loaders,
        environment=environment,
        files=(
            PluginFile(
                url=url,
                filename=filename,
                size_bytes=123,
                sha1=sha1 or ("1" * 40),
                sha512=sha512 or ("2" * 128),
                primary=True,
            ),
        ),
        dependencies=deps,
        date_published="2026-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_hash_only_lookup_client_only_filter_and_unresolved_carried(
    tmp_path: Path,
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    mod_a = b"mod-a-bytes"
    sha256_a, sha512_a, _ = _hashes(mod_a)
    cas.put_bytes(mod_a)

    mod_client = b"mod-client-bytes"
    sha256_c, sha512_c, _ = _hashes(mod_client)
    cas.put_bytes(mod_client)

    custom_jar = b"spigot-custom-plugin"
    sha256_u, sha512_u, _ = _hashes(custom_jar)
    cas.put_bytes(custom_jar)

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/a.jar",
                sha256=sha256_a,
                sha512=None,  # Computed from CAS!
                size=len(mod_a),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
            LockfileFile(
                path="mods/clientish.jar",
                sha256=sha256_c,
                sha512=sha512_c,
                size=len(mod_client),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-c",
                version_id="ver-c-old",
            ),
            LockfileFile(
                path="plugins/custom-spigot.jar",
                sha256=sha256_u,
                sha512=sha512_u,
                size=len(custom_jar),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
    )

    client = FakeModrinthClient(
        version_files={
            sha512_a: _ver("ver-a-1", "proj-a", game_versions=("1.20.4",)),
            sha512_c: _ver("ver-c-1", "proj-c", game_versions=("1.20.4",)),
        },
        updates={
            sha512_a: _ver(
                "ver-a-2",
                "proj-a",
                filename="a-new.jar",
                environment="server_only",
                deps=(
                    ModrinthDependency(
                        version_id=None,
                        project_id="opt-proj",
                        file_name=None,
                        dependency_type="optional",
                    ),
                ),
            ),
            # Returned update is client_only on Version.environment -> must be rejected!
            sha512_c: _ver("ver-c-2", "proj-c", environment="client_only"),
        },
    )

    matrix = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=client,  # type: ignore[arg-type]
        cas=cas,
    )

    assert len(client.lookup_files_calls) == 1
    assert set(client.lookup_files_calls[0]) == {sha512_a, sha512_c, sha512_u}

    by_path = {e.path: e for e in matrix.entries}
    assert by_path["mods/a.jar"].status == MatrixStatus.CARRIED
    assert by_path["mods/clientish.jar"].status == MatrixStatus.BLOCKER_NO_TARGET_BUILD
    assert by_path["plugins/custom-spigot.jar"].status == MatrixStatus.WARNING_UNRESOLVED_CARRIED
    assert not by_path["plugins/custom-spigot.jar"].is_blocker
    assert by_path["mods/a.jar#optional:opt-proj"].status == MatrixStatus.WARNING
    assert not by_path["mods/a.jar#optional:opt-proj"].is_blocker

    with pytest.raises(UpgradeBlockerError):
        matrix.assert_no_blockers()

    # Operator excludes the client_only blocker -> matrix clears!
    matrix_excluded = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=client,  # type: ignore[arg-type]
        cas=cas,
        excluded_paths=["mods/clientish.jar"],
    )
    assert not matrix_excluded.has_blockers
    matrix_excluded.assert_no_blockers()


@pytest.mark.asyncio
async def test_transitive_bfs_concrete_version_depth_and_project_caps(
    tmp_path: Path,
) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    root_bytes = b"root-mod"
    sha256_r, sha512_r, _ = _hashes(root_bytes)
    cas.put_bytes(root_bytes)

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/root.jar",
                sha256=sha256_r,
                sha512=sha512_r,
                size=len(root_bytes),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-root",
                version_id="v-root-old",
            ),
        ),
    )

    # 1. Valid 2-hop transitive BFS with concrete version_id at depth 2
    client = FakeModrinthClient(
        version_files={sha512_r: _ver("v-root-old", "proj-root", game_versions=("1.20.4",))},
        updates={
            sha512_r: _ver(
                "v-root-new",
                "proj-root",
                deps=(
                    ModrinthDependency(
                        version_id=None,
                        project_id="proj-d1",
                        file_name=None,
                        dependency_type="required",
                    ),
                ),
            )
        },
        project_versions={
            "proj-d1": [
                _ver(
                    "v-d1",
                    "proj-d1",
                    filename="dep1.jar",
                    deps=(
                        ModrinthDependency(
                            version_id="v-d2-concrete",
                            project_id="proj-d2",
                            file_name=None,
                            dependency_type="required",
                        ),
                    ),
                )
            ]
        },
        versions_by_id={
            "v-d2-concrete": _ver("v-d2-concrete", "proj-d2", filename="dep2.jar")
        },
    )

    matrix = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=client,  # type: ignore[arg-type]
        cas=cas,
    )
    assert not matrix.has_blockers
    assert matrix.bfs_depth_reached == 2
    assert matrix.bfs_projects_resolved == 2
    by_path = {e.path: e for e in matrix.entries}
    assert by_path["mods/dep1.jar"].status == MatrixStatus.ADD
    assert by_path["mods/dep2.jar"].status == MatrixStatus.ADD
    assert by_path["mods/dep2.jar"].required_by == ("mods/root.jar",)

    # 2. Concrete version_id incompatible with target_mc -> BLOCKER_MISSING_TRANSITIVE_DEPENDENCY
    bad_concrete_client = FakeModrinthClient(
        version_files={sha512_r: _ver("v-root-old", "proj-root", game_versions=("1.20.4",))},
        updates={
            sha512_r: _ver(
                "v-root-new",
                "proj-root",
                deps=(
                    ModrinthDependency(
                        version_id="v-wrong-mc",
                        project_id="proj-d1",
                        file_name=None,
                        dependency_type="required",
                    ),
                ),
            )
        },
        versions_by_id={
            "v-wrong-mc": _ver("v-wrong-mc", "proj-d1", game_versions=("1.20.1",))
        },
    )
    bad_matrix = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=bad_concrete_client,  # type: ignore[arg-type]
        cas=cas,
    )
    assert bad_matrix.blockers[0].status == MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY

    # 3. auto_include_dependencies=False -> BLOCKER_MISSING_DEPENDENCY
    no_auto = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=client,  # type: ignore[arg-type]
        cas=cas,
        auto_include_dependencies=False,
    )
    assert no_auto.blockers[0].status == MatrixStatus.BLOCKER_MISSING_DEPENDENCY

    # 4. Depth > 8 -> BLOCKER_MISSING_TRANSITIVE_DEPENDENCY
    chain_versions = {}
    for i in range(1, 10):
        pid = f"chain-{i}"
        next_deps = (
            (
                ModrinthDependency(
                    version_id=f"v-chain-{i + 1}",
                    project_id=f"chain-{i + 1}",
                    file_name=None,
                    dependency_type="required",
                ),
            )
            if i < 10
            else ()
        )
        chain_versions[f"v-chain-{i}"] = _ver(
            f"v-chain-{i}", pid, filename=f"c{i}.jar", deps=next_deps
        )
    deep_client = FakeModrinthClient(
        version_files={sha512_r: _ver("v-root-old", "proj-root", game_versions=("1.20.4",))},
        updates={
            sha512_r: _ver(
                "v-root-new",
                "proj-root",
                deps=(
                    ModrinthDependency(
                        version_id="v-chain-1",
                        project_id="chain-1",
                        file_name=None,
                        dependency_type="required",
                    ),
                ),
            )
        },
        versions_by_id=chain_versions,
    )
    deep_matrix = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=deep_client,  # type: ignore[arg-type]
        cas=cas,
    )
    assert deep_matrix.blockers[0].status == MatrixStatus.BLOCKER_MISSING_TRANSITIVE_DEPENDENCY


@pytest.mark.asyncio
async def test_remaining_blockers_and_pack_short_circuit(tmp_path: Path) -> None:
    cas = ArtifactCas(tmp_path / "cas")
    pack_mod = b"pack-mod"
    sha256_p, sha512_p, sha1_p = _hashes(pack_mod)
    cas.put_bytes(pack_mod)

    user_mod = b"user-loose-mod"
    sha256_u, sha512_u, _ = _hashes(user_mod)
    cas.put_bytes(user_mod)

    incompat_mod = b"incompat-mod"
    sha256_inc, sha512_inc, _ = _hashes(incompat_mod)
    cas.put_bytes(incompat_mod)

    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="fabric", version="0.15.11"),
        base_overrides={},
        files=(
            LockfileFile(
                path="mods/kept.jar",
                sha256=sha256_p,
                sha512=sha512_p,
                sha1=sha1_p,
                size=len(pack_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-kept",
                version_id="v-kept",
            ),
            LockfileFile(
                path="mods/removed.jar",
                sha256=sha256_inc,
                sha512=sha512_inc,
                size=len(incompat_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
                project_id="proj-removed",
                version_id="v-rem",
            ),
            LockfileFile(
                path="mods/loose.jar",
                sha256=sha256_u,
                sha512=sha512_u,
                size=len(user_mod),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.USER,
            ),
        ),
    )

    plan = InstallPlan(
        source="curseforge",
        project_id="100",
        version_id="200",
        version_label="v2",
        index_sha256="a" * 64,
        mc_version="1.21.1",
        loader_id="fabric",
        loader_version="0.16.0",
        files=(
            InstallPlanFile(
                path="mods/kept.jar",
                sha1=sha1_p,
                sha512=sha512_p,
                sha256=sha256_p,
                size=len(pack_mod),
                downloads=("https://cdn.modrinth.com/data/kept.jar",),
                origin=Origin.MODRINTH,
                project_id="proj-kept",
                version_id="v-kept",
            ),
            InstallPlanFile(
                path="mods/evil.jar",
                sha1="b" * 40,
                sha512="c" * 128,
                size=50,
                downloads=("https://evil.example.com/evil.jar",),
                origin=Origin.MODRINTH,
                project_id="proj-evil",
                version_id="v-evil",
            ),
            InstallPlanFile(
                path="mods/new.jar",
                sha1="d" * 40,
                sha512="e" * 128,
                size=60,
                downloads=("https://cdn.modrinth.com/data/new.jar",),
                origin=Origin.MODRINTH,
                project_id="proj-new",
                version_id="v-new",
            ),
        ),
        overrides=(),
        manual_blockers=(
            ManualDownloadBlocker(
                path="mods/manual.jar",
                filename="manual.jar",
                project_id=99,
                file_id=101,
                webpage_url="https://www.curseforge.com/minecraft/mc-mods/manual",
            ),
        ),
    )

    # Loose user jar declares incompatibility with proj-new -> BLOCKER_INCOMPATIBLE
    client = FakeModrinthClient(
        version_files={sha512_u: _ver("v-u-old", "proj-u", game_versions=("1.20.4",))},
        updates={
            sha512_u: _ver(
                "v-u-new",
                "proj-u",
                filename="loose.jar",
                deps=(
                    ModrinthDependency(
                        version_id=None,
                        project_id="proj-new",
                        file_name=None,
                        dependency_type="incompatible",
                    ),
                ),
            )
        },
    )

    matrix = await build_compatibility_matrix(
        lockfile,
        target_mc="1.21.1",
        target_loader=LoaderRef(id="fabric", version="0.16.0"),
        modrinth_client=client,  # type: ignore[arg-type]
        cas=cas,
        target_install_plan=plan,
    )

    # Short-circuit: ONLY loose user jar queried on /version_files/update!
    assert client.lookup_updates_calls == [[sha512_u]]

    by_path = {e.path: e for e in matrix.entries}
    assert by_path["mods/kept.jar"].status == MatrixStatus.UNCHANGED
    assert by_path["mods/removed.jar"].status == MatrixStatus.REMOVE
    assert by_path["mods/new.jar"].status == MatrixStatus.ADD
    assert by_path["mods/evil.jar"].status == MatrixStatus.BLOCKER_UNTRUSTED_HOST
    assert by_path["mods/manual.jar"].status == MatrixStatus.BLOCKER_MANUAL_DOWNLOAD_REQUIRED
    assert by_path["mods/loose.jar"].status == MatrixStatus.BLOCKER_INCOMPATIBLE


def test_upgrade_merge_rules_conflicts_and_per_file_base_advancement(
    tmp_path: Path,
) -> None:
    cas = ArtifactCas(tmp_path / "cas")

    base_blobs = {
        # Ordered scalar array vs set-mergeable key in spigot.yml
        "spigot.yml": (
            b"commands:\n"
            b"  silent-commandblock-console-worlds:\n"
            b"    - world\n"
            b"  other-ordered:\n"
            b"    - a\n"
            b"    - b\n"
        ),
        # Object-array primary key merge (id)
        "config/items.json": json.dumps(
            {"entries": [{"id": "sword", "dmg": 5}]}
        ).encode("utf-8"),
        # Textual diff3 (.json5)
        "config/custom.json5": b"{\n  a: 1,\n  b: 2,\n  c: 3,\n}\n",
        # Structured parse fallback -> ours-fallback must keep previous B
        "config/bad.yml": b"good: true\n",
    }
    base_overrides = store_base_overrides_in_cas(cas, base_blobs)
    lockfile = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="100"),
        base_overrides=base_overrides,
        files=(),
    )

    ours_files = {
        "spigot.yml": (
            b"commands:\n"
            b"  silent-commandblock-console-worlds:\n"
            b"    - world\n"
            b"    - world_nether\n"
            b"  other-ordered:\n"
            b"    - a\n"
            b"    - b\n"
        ),
        "config/items.json": json.dumps(
            {"entries": [{"id": "sword", "dmg": 7}, {"id": "bow", "dmg": 4}]}
        ).encode("utf-8"),
        "config/custom.json5": b"{\n  a: 10,\n  b: 2,\n  c: 3,\n}\n",
        "config/bad.yml": b":::not-valid-yaml:::\n[",
    }
    theirs_overrides = {
        "spigot.yml": (
            b"commands:\n"
            b"  silent-commandblock-console-worlds:\n"
            b"    - world\n"
            b"    - world_the_end\n"
            b"  other-ordered:\n"
            b"    - a\n"
            b"    - b\n"
        ),
        "config/items.json": json.dumps(
            {"entries": [{"id": "sword", "dmg": 5}, {"id": "shield", "dmg": 1}]}
        ).encode("utf-8"),
        "config/custom.json5": b"{\n  a: 1,\n  b: 2,\n  c: 30,\n}\n",
        "config/bad.yml": b"good: false\n",
    }

    res = merge_upgrade_configs(
        cas=cas,
        current_lockfile=lockfile,
        ours_files=ours_files,
        theirs_overrides=theirs_overrides,
    )
    assert res.status == "clean"
    assert "config/bad.yml" in res.fallback_paths
    assert "config/bad.yml" not in res.cleanly_resolved_paths
    # OD-v8.7-9: cleanly merged files advance to T; ours-fallback keeps previous B!
    assert res.new_base_overrides["spigot.yml"] != base_overrides["spigot.yml"]
    assert res.new_base_overrides["config/items.json"] != base_overrides["config/items.json"]
    assert res.new_base_overrides["config/custom.json5"] != base_overrides["config/custom.json5"]
    assert res.new_base_overrides["config/bad.yml"] == base_overrides["config/bad.yml"]

    # Check object-array merge result & diff3 result
    merged_items = json.loads(res.merged_files["config/items.json"].decode("utf-8"))
    by_id = {x["id"]: x for x in merged_items["entries"]}
    assert by_id["sword"]["dmg"] == 7
    assert "bow" in by_id and "shield" in by_id
    assert b"a: 10" in res.merged_files["config/custom.json5"]
    assert b"c: 30" in res.merged_files["config/custom.json5"]

    # Conflict on ordered scalar array -> needs_resolution & export refused
    conflict_ours = {
        "spigot.yml": (
            b"commands:\n"
            b"  silent-commandblock-console-worlds:\n"
            b"    - world\n"
            b"  other-ordered:\n"
            b"    - x\n"
        ),
    }
    conflict_theirs = {
        "spigot.yml": (
            b"commands:\n"
            b"  silent-commandblock-console-worlds:\n"
            b"    - world\n"
            b"  other-ordered:\n"
            b"    - y\n"
        ),
    }
    res_conf = merge_upgrade_configs(
        cas=cas,
        current_lockfile=lockfile,
        ours_files=conflict_ours,
        theirs_overrides=conflict_theirs,
    )
    assert res_conf.status == "needs_resolution"
    tree = tmp_path / "tree"
    tree.mkdir()
    with pytest.raises(MergeConflictError):
        assert_tree_ready_for_upgrade_export(tree, res_conf)

    # Conflict markers on disk also rejected
    (tree / "config").mkdir()
    (tree / "config" / "note.txt").write_text("<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n")
    with pytest.raises(ConflictError):
        assert_tree_ready_for_upgrade_export(tree)

    # Operator resolution clears conflict and advances base_overrides to T
    res_fixed = merge_upgrade_configs(
        cas=cas,
        current_lockfile=lockfile,
        ours_files=conflict_ours,
        theirs_overrides=conflict_theirs,
        resolved_conflicts={
            "spigot.yml": (
                b"commands:\n"
                b"  silent-commandblock-console-worlds:\n"
                b"    - world\n"
                b"  other-ordered:\n"
                b"    - x\n"
                b"    - y\n"
            )
        },
    )
    assert res_fixed.status == "clean"
    assert "spigot.yml" in res_fixed.cleanly_resolved_paths
    assert res_fixed.new_base_overrides["spigot.yml"] == hashlib.sha256(
        conflict_theirs["spigot.yml"]
    ).hexdigest()
