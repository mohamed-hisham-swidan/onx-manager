from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.versioning.domain.entities import (
    ImportReview,
    Materialization,
    PersistentDataset,
)
from app.modules.versioning.domain.value_objects import (
    ALLOWED_MATERIALIZATION_ROOTS,
    MATERIALIZATION_ROOT_TESTS,
    MATERIALIZATION_ROOT_WORKTREES,
    CommitManifest,
    ImportReviewStatus,
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
    Tree,
)
from app.modules.versioning.infrastructure.fs_atomic import (
    atomic_replace_dir,
    atomic_replace_file,
    atomic_write_file,
)
from app.modules.versioning.infrastructure.tree_writer import write_tree_to_dir


def _now() -> datetime:
    return datetime.now(UTC)


class TestStageCMaterializationDomain:
    def test_root_constants(self) -> None:
        assert MATERIALIZATION_ROOT_TESTS == ".onx/tests"
        assert MATERIALIZATION_ROOT_WORKTREES == ".onx/worktrees"
        assert ALLOWED_MATERIALIZATION_ROOTS == (".onx/tests", ".onx/worktrees")

    def test_root_allowlist_acceptance(self) -> None:
        mat_tests = Materialization(
            id="mat-1",
            commit_id="c-1",
            server_id="srv-1",
            revision="rev-1",
            root_path=".onx/tests/run-42",
        )
        assert mat_tests.root_path == ".onx/tests/run-42"
        assert mat_tests.mode == MaterializationMode.READONLY

        mat_worktree = Materialization(
            id="mat-2",
            commit_id="c-2",
            server_id="srv-1",
            revision="rev-2",
            root_path=".onx/worktrees/feat-branch",
        )
        assert mat_worktree.root_path == ".onx/worktrees/feat-branch"
        assert mat_worktree.mode == MaterializationMode.READONLY

    def test_root_allowlist_rejection(self) -> None:
        with pytest.raises(
            ValueError,
            match="^Materialization root_path must be an isolated .onx/tests directory",
        ):
            Materialization(
                id="mat-e1",
                commit_id="c-1",
                server_id="srv-1",
                revision="rev-1",
                root_path="/tmp/arbitrary_dir",
            )

        with pytest.raises(
            ValueError,
            match="^Materialization root_path must be an isolated .onx/tests directory",
        ):
            Materialization(
                id="mat-e2",
                commit_id="c-1",
                server_id="srv-1",
                revision="rev-1",
                root_path=".onx/tests/../escaping",
            )

        with pytest.raises(
            ValueError,
            match="^Materialization root_path must be an isolated .onx/tests directory",
        ):
            Materialization(
                id="mat-e3",
                commit_id="c-1",
                server_id="srv-1",
                revision="rev-1",
                root_path=".onx/worktrees/../../etc/passwd",
            )

        with pytest.raises(
            ValueError,
            match="^Materialization root_path must be an isolated .onx/tests directory",
        ):
            Materialization(
                id="mat-e4",
                commit_id="c-1",
                server_id="srv-1",
                revision="rev-1",
                root_path="live_server_root",
            )

    def test_mode_transitions(self) -> None:
        mat = Materialization(
            id="mat-mode",
            commit_id="c-1",
            server_id="srv-1",
            revision="rev-1",
            root_path=".onx/worktrees/wt-1",
        )
        assert mat.mode == MaterializationMode.READONLY
        mat.mark_ready()
        assert mat.status == MaterializationStatus.READY

        mat.set_mode(MaterializationMode.EDITABLE)
        assert mat.mode == MaterializationMode.EDITABLE

        mat.set_mode(MaterializationMode.READONLY)
        assert mat.mode == MaterializationMode.READONLY

        mat.mark_removed()
        assert mat.status == MaterializationStatus.REMOVED
        with pytest.raises(ValueError, match="Cannot set edit mode on removed materialization"):
            mat.set_mode(MaterializationMode.EDITABLE)

    def test_classification_and_write_path_validation(self) -> None:
        mat = Materialization(
            id="mat-class",
            commit_id="c-1",
            server_id="srv-1",
            revision="rev-1",
            root_path=".onx/worktrees/wt-1",
            path_classification={
                "server.properties": PathClassification.TRACKED,
                "world/level.dat": PathClassification.PERSISTENT,
                "logs/latest.log": PathClassification.GENERATED,
            },
        )
        assert mat.path_classification["server.properties"] == PathClassification.TRACKED
        assert mat.path_classification["world/level.dat"] == PathClassification.PERSISTENT
        assert mat.path_classification["logs/latest.log"] == PathClassification.GENERATED

        # PersistentDataset boundary check
        tree = Tree.from_manifest(
            CommitManifest(
                server_type="paper",
                minecraft_version="1.21.1",
                configs={"server.properties": "motd=Test"},
                mods=[{"filename": "mods/jei.jar"}],
            )
        )
        dataset = PersistentDataset(
            id="ds-1",
            runtime_id="rt-1",
            dataset_root="world",
            server_id="srv-1",
        )
        # Safe mutable dataset path
        dataset.validate_write_path("region/r.0.0.mca", tracked_tree=tree)

        # Overlap with tracked tree config raises ValueError
        with pytest.raises(ValueError, match="overlaps tracked configuration in Tree"):
            dataset.validate_write_path("server.properties", tracked_tree=tree)

        # Overlap with tracked mod raises ValueError
        with pytest.raises(ValueError, match="overlaps tracked mod in Tree"):
            dataset.validate_write_path("mods/jei.jar", tracked_tree=tree)

    def test_import_review_state_machine_terminality(self) -> None:
        # Confirm cycle
        review_confirm = ImportReview(
            id="rev-1",
            server_id="srv-1",
            commit_id="c-1",
            branch_name="master",
            status=ImportReviewStatus.PENDING,
            changes=[{"path": "server.properties"}],
        )
        assert review_confirm.status == ImportReviewStatus.PENDING
        review_confirm.confirm()
        assert review_confirm.status == ImportReviewStatus.CONFIRMED

        with pytest.raises(ValueError, match="Cannot confirm terminal import review"):
            review_confirm.confirm()
        with pytest.raises(ValueError, match="Cannot dismiss terminal import review"):
            review_confirm.dismiss()
        with pytest.raises(ValueError, match="Cannot revert terminal import review"):
            review_confirm.revert("c-rev-0")

        # Dismiss cycle
        review_dismiss = ImportReview(
            id="rev-2",
            server_id="srv-1",
            commit_id="c-2",
            branch_name="master",
        )
        assert review_dismiss.status == ImportReviewStatus.PENDING
        review_dismiss.dismiss()
        assert review_dismiss.status == ImportReviewStatus.DISMISSED

        with pytest.raises(ValueError, match="Cannot confirm terminal import review"):
            review_dismiss.confirm()

        # Revert cycle
        review_revert = ImportReview(
            id="rev-3",
            server_id="srv-1",
            commit_id="c-3",
            branch_name="master",
        )
        assert review_revert.status == ImportReviewStatus.PENDING
        review_revert.revert("c-revert-id")
        assert review_revert.status == ImportReviewStatus.REVERTED
        assert review_revert.revert_commit_id == "c-revert-id"

        with pytest.raises(ValueError, match="Cannot dismiss terminal import review"):
            review_revert.dismiss()


class TestAtomicFsInfrastructure:
    def test_atomic_write_and_replace_file(self, tmp_path: Path) -> None:
        target_file = tmp_path / "test.txt"
        content = b"hello atomic world"
        atomic_write_file(target_file, content)
        assert target_file.read_bytes() == content

        # Overwrite with atomic_replace_file
        src_file = tmp_path / "src.txt"
        new_content = b"updated atomic content"
        atomic_write_file(src_file, new_content)
        atomic_replace_file(src_file, target_file)
        assert target_file.read_bytes() == new_content

    def test_atomic_replace_dir(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "old_file.txt").write_text("old content")

        new_content_dir = tmp_path / "src"
        new_content_dir.mkdir()
        (new_content_dir / "new_file.txt").write_text("new content")

        atomic_replace_dir(new_content_dir, dest_dir)

        assert dest_dir.exists()
        assert not (dest_dir / "old_file.txt").exists()
        assert (dest_dir / "new_file.txt").read_text() == "new content"
        assert not new_content_dir.exists()

    def test_write_tree_to_dir_roundtrip_and_verify(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "worktree"
        tree = Tree.from_manifest(
            CommitManifest(
                server_type="paper",
                minecraft_version="1.21.1",
                configs={
                    "server.properties": "difficulty=hard\npvp=true\n",
                    "config/paper-global.yml": "timings:\n  enabled: true\n",
                },
                mods=[
                    {"filename": "mods/jei.jar", "size": 12345},
                ],
                env_vars={"JAVA_ARGS": "-Xmx4G"},
            )
        )

        write_tree_to_dir(tree, dest_dir)

        assert (dest_dir / "server.properties").read_text() == "difficulty=hard\npvp=true\n"
        assert (dest_dir / "config" / "paper-global.yml").read_text() == (
            "timings:\n  enabled: true\n"
        )

    def test_write_tree_to_dir_path_traversal_rejection(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "worktree_bad"
        bad_tree = Tree.from_manifest(
            CommitManifest(
                server_type="vanilla",
                minecraft_version="1.21.1",
                configs={
                    "../evil.txt": "malicious escape",
                },
            )
        )

        with pytest.raises(ValueError, match="Config path escapes target root"):
            write_tree_to_dir(bad_tree, dest_dir)
        assert not dest_dir.exists()

    def test_write_tree_to_dir_verify_failure_leaves_target_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dest_dir = tmp_path / "worktree_live"
        dest_dir.mkdir(parents=True, exist_ok=True)
        sentinel_file = dest_dir / "live_data.txt"
        sentinel_file.write_text("critical live content")

        tree = Tree.from_manifest(
            CommitManifest(
                server_type="paper",
                minecraft_version="1.21.1",
                configs={
                    "server.properties": "difficulty=hard\n",
                },
                mods=[],
                env_vars={},
            )
        )

        orig_read_text = Path.read_text

        def mock_read_text(path_obj: Path, *args, **kwargs) -> str:
            if path_obj.name == "server.properties":
                return "corrupted content"
            return orig_read_text(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        with pytest.raises(RuntimeError, match="Post-write verify failed: content mismatch"):
            write_tree_to_dir(tree, dest_dir, verify=True)

        assert dest_dir.exists()
        assert sentinel_file.exists()
        assert sentinel_file.read_text() == "critical live content"
