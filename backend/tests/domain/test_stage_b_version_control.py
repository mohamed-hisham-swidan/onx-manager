from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.versioning.domain.dag import check_cycle, traverse_history
from app.modules.versioning.domain.diff import diff_commits, diff_trees
from app.modules.versioning.domain.entities import ServerCommit, Tag
from app.modules.versioning.domain.value_objects import CommitManifest, Revision, Tree


def _now() -> datetime:
    return datetime.now(UTC)


def _make_manifest(
    configs: dict[str, str] | None = None,
    mods: list[dict] | None = None,
    env_vars: dict[str, str] | None = None,
    server_type: str = "vanilla",
    minecraft_version: str = "1.21.1",
    java_args: str = "",
) -> CommitManifest:
    return CommitManifest(
        server_type=server_type,
        minecraft_version=minecraft_version,
        configs=configs or {},
        mods=mods or [],
        env_vars=env_vars or {},
        java_args=java_args,
    )


def _make_commit(
    commit_id: str,
    server_id: str = "srv-1",
    parent_ids: list[str] | None = None,
    created_at: datetime | None = None,
    manifest: CommitManifest | None = None,
) -> ServerCommit:
    return ServerCommit(
        id=commit_id,
        server_id=server_id,
        message=f"Commit {commit_id}",
        manifest=manifest or _make_manifest(),
        parent_commit_ids=parent_ids or [],
        created_at=created_at or _now(),
    )


class TestCommitDAGInvariants:
    def test_single_parent_syncs_with_parent_commit_ids(self) -> None:
        c = ServerCommit(
            id="c1",
            server_id="srv-1",
            message="initial",
            manifest=_make_manifest(),
            parent_commit_id="p1",
        )
        assert c.parent_commit_id == "p1"
        assert c.parent_commit_ids == ["p1"]

    def test_parent_commit_ids_syncs_with_parent_commit_id(self) -> None:
        c = ServerCommit(
            id="c2",
            server_id="srv-1",
            message="merge",
            manifest=_make_manifest(),
            parent_commit_ids=["p1", "p2"],
        )
        assert c.parent_commit_id == "p1"
        assert c.parent_commit_ids == ["p1", "p2"]

    def test_rejects_empty_commit_id(self) -> None:
        with pytest.raises(ValueError, match="Commit id cannot be empty"):
            ServerCommit(
                id="",
                server_id="srv-1",
                message="msg",
                manifest=_make_manifest(),
            )

    def test_rejects_empty_server_id(self) -> None:
        with pytest.raises(ValueError, match="Commit server_id cannot be empty"):
            ServerCommit(
                id="c1",
                server_id="",
                message="msg",
                manifest=_make_manifest(),
            )

    def test_rejects_self_parenting(self) -> None:
        with pytest.raises(ValueError, match="Self-parenting rejected"):
            ServerCommit(
                id="c1",
                server_id="srv-1",
                message="msg",
                manifest=_make_manifest(),
                parent_commit_ids=["c1"],
            )

    def test_rejects_duplicate_parents(self) -> None:
        with pytest.raises(ValueError, match="Duplicate parent commit references"):
            ServerCommit(
                id="c1",
                server_id="srv-1",
                message="msg",
                manifest=_make_manifest(),
                parent_commit_ids=["p1", "p1"],
            )

    def test_validate_parents_rejects_dangling_parent(self) -> None:
        c = _make_commit("c1", parent_ids=["p1", "p2"])
        p1 = _make_commit("p1")
        with pytest.raises(ValueError, match="Dangling parent commit 'p2'"):
            c.validate_parents([p1])

    def test_validate_parents_rejects_cross_server_parent(self) -> None:
        c = _make_commit("c1", server_id="srv-1", parent_ids=["p1", "p2"])
        p1 = _make_commit("p1", server_id="srv-1")
        p2 = _make_commit("p2", server_id="srv-OTHER")
        with pytest.raises(ValueError, match="Cross-server parent rejected"):
            c.validate_parents([p1, p2])

    def test_validate_parents_accepts_valid_parents(self) -> None:
        c = _make_commit("c1", server_id="srv-1", parent_ids=["p1", "p2"])
        p1 = _make_commit("p1", server_id="srv-1")
        p2 = _make_commit("p2", server_id="srv-1")
        c.validate_parents([p1, p2])


class TestCycleDetectionAndDAGTraversal:
    @pytest.mark.asyncio
    async def test_cycle_detection_direct(self) -> None:
        # Commit candidate is in parent_ids
        parents_map = {"c1": []}

        async def get_parents(cid: str) -> list[str]:
            return parents_map.get(cid, [])

        assert await check_cycle("c1", ["c1"], get_parents) is True

    @pytest.mark.asyncio
    async def test_cycle_detection_transitive(self) -> None:
        # c1 -> c2 -> c3. Try adding candidate c1 with parent c3.
        parents_map = {
            "c3": ["c2"],
            "c2": ["c1"],
            "c1": [],
        }

        async def get_parents(cid: str) -> list[str]:
            return parents_map.get(cid, [])

        assert await check_cycle("c1", ["c3"], get_parents) is True

    @pytest.mark.asyncio
    async def test_cycle_detection_accepts_valid_diamond_dag(self) -> None:
        # Diamond: c0 is root. c1, c2 branch from c0. c3 merges c1, c2.
        # No cycle.
        parents_map = {
            "c1": ["c0"],
            "c2": ["c0"],
            "c0": [],
        }

        async def get_parents(cid: str) -> list[str]:
            return parents_map.get(cid, [])

        assert await check_cycle("c3", ["c1", "c2"], get_parents) is False

    @pytest.mark.asyncio
    async def test_traverse_history_deterministic_order(self) -> None:
        t0 = _now()
        t1 = t0 + timedelta(seconds=1)
        t2 = t0 + timedelta(seconds=2)
        t3 = t0 + timedelta(seconds=3)

        c0 = _make_commit("c0", created_at=t0)
        c1 = _make_commit("c1", parent_ids=["c0"], created_at=t1)
        c2 = _make_commit("c2", parent_ids=["c0"], created_at=t2)
        c3 = _make_commit("c3", parent_ids=["c1", "c2"], created_at=t3)

        commits_db = {"c0": c0, "c1": c1, "c2": c2, "c3": c3}

        async def get_commit(cid: str) -> ServerCommit | None:
            return commits_db.get(cid)

        async def get_parents(cid: str) -> list[str]:
            c = commits_db.get(cid)
            return c.parent_commit_ids if c else []

        history = await traverse_history("c3", get_commit, get_parents)
        history_ids = [c.id for c in history]

        assert history_ids == ["c3", "c2", "c1", "c0"]


class TestTagEntityAndRevision:
    def test_tag_invariants(self) -> None:
        with pytest.raises(ValueError, match="Tag id cannot be empty"):
            Tag(id="", server_id="srv-1", name="v1.0", commit_id="c1")

        with pytest.raises(ValueError, match="Tag server_id cannot be empty"):
            Tag(id="t1", server_id="", name="v1.0", commit_id="c1")

        with pytest.raises(ValueError, match="Tag name cannot be empty"):
            Tag(id="t1", server_id="srv-1", name="  ", commit_id="c1")

        with pytest.raises(ValueError, match="Tag commit_id cannot be empty"):
            Tag(id="t1", server_id="srv-1", name="v1.0", commit_id="")

        tag = Tag(id="t1", server_id="srv-1", name="v1.0", commit_id="c1")
        assert tag.name == "v1.0"
        assert tag.commit_id == "c1"

    def test_revision_from_tag(self) -> None:
        rev = Revision.from_tag(
            tag_name="v1.0",
            commit_id="commit-abc",
            tag_server_id="srv-1",
            target_server_id="srv-1",
        )
        assert rev.commit_id == "commit-abc"
        assert rev.server_id == "srv-1"
        assert rev.resolved_from == "tag:v1.0@commit-abc"

    def test_revision_from_tag_cross_server_rejected(self) -> None:
        with pytest.raises(ValueError, match="Cannot resolve tag 'v1.0' from server 'srv-OTHER'"):
            Revision.from_tag(
                tag_name="v1.0",
                commit_id="commit-abc",
                tag_server_id="srv-OTHER",
                target_server_id="srv-1",
            )

    def test_revision_from_tag_empty_commit_rejected(self) -> None:
        with pytest.raises(ValueError, match="Tag 'v1.0' has no target commit to resolve"):
            Revision.from_tag(
                tag_name="v1.0",
                commit_id="",
                tag_server_id="srv-1",
                target_server_id="srv-1",
            )


class TestDeterministicDiff:
    def test_identical_trees_have_no_changes(self) -> None:
        t1 = Tree.from_manifest(
            _make_manifest(
                configs={"server.properties": "motd=MCS"},
                mods=[{"filename": "modA.jar", "version": "1.0"}],
                env_vars={"JAVA_OPTS": "-Xmx2G"},
            )
        )
        t2 = Tree.from_manifest(
            _make_manifest(
                configs={"server.properties": "motd=MCS"},
                mods=[{"filename": "modA.jar", "version": "1.0"}],
                env_vars={"JAVA_OPTS": "-Xmx2G"},
            )
        )
        diff = diff_trees(t1, t2)
        assert diff.has_changes is False
        assert diff.configs.added == {}
        assert diff.configs.removed == {}
        assert diff.configs.modified == {}

    def test_config_diff_determinism_and_sorting(self) -> None:
        t1 = Tree.from_manifest(
            _make_manifest(
                configs={
                    "z.txt": "old_z",
                    "b.txt": "old_b",
                    "a.txt": "common",
                    "del.txt": "to_delete",
                }
            )
        )
        t2 = Tree.from_manifest(
            _make_manifest(
                configs={
                    "z.txt": "new_z",
                    "b.txt": "new_b",
                    "a.txt": "common",
                    "c_new.txt": "added_c",
                    "a_new.txt": "added_a",
                }
            )
        )
        diff = diff_trees(t1, t2)
        assert diff.has_changes is True

        # Deterministic sorting on added keys: ["a_new.txt", "c_new.txt"]
        assert list(diff.configs.added.keys()) == ["a_new.txt", "c_new.txt"]
        assert list(diff.configs.removed.keys()) == ["del.txt"]
        # Deterministic sorting on modified keys: ["b.txt", "z.txt"]
        assert list(diff.configs.modified.keys()) == ["b.txt", "z.txt"]
        assert diff.configs.modified["b.txt"] == {"old": "old_b", "new": "new_b"}

    def test_mods_diff_determinism_and_sorting(self) -> None:
        t1 = Tree.from_manifest(
            _make_manifest(
                mods=[
                    {"filename": "z_mod.jar", "version": "1.0"},
                    {"filename": "a_mod.jar", "version": "1.0"},
                    {"filename": "old_mod.jar", "version": "1.0"},
                ]
            )
        )
        t2 = Tree.from_manifest(
            _make_manifest(
                mods=[
                    {"filename": "z_mod.jar", "version": "2.0"},
                    {"filename": "a_mod.jar", "version": "1.0"},
                    {"filename": "new_mod.jar", "version": "1.0"},
                ]
            )
        )
        diff = diff_trees(t1, t2)
        assert diff.has_changes is True
        assert [m["filename"] for m in diff.mods.added] == ["new_mod.jar"]
        assert [m["filename"] for m in diff.mods.removed] == ["old_mod.jar"]
        assert [m["key"] for m in diff.mods.modified] == ["z_mod.jar"]

    def test_diff_commits_cross_server_rejected(self) -> None:
        c1 = _make_commit("c1", server_id="srv-1")
        c2 = _make_commit("c2", server_id="srv-2")
        with pytest.raises(ValueError, match="Cannot diff commits across different servers"):
            diff_commits(c1, c2)
