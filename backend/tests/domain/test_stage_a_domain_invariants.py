"""Stage A Domain Invariants and Acceptance Criteria Test Suite.

Verifies the 3 core invariants and acceptance criteria from:
docs/design/testing-system-refactor/01-stage-a-domain-reconstruction-design-spec.md:
- Invariant 1: Runtime Pinning (Runtime -> immutable Commit ID, never mutable Branch)
- Invariant 2: Lock Policy Preserved (DockerTestExecutionRunner per-server execution lock)
- Invariant 3: Persistent Data Isolation (PersistentDataset writes do not mutate Tree)
- Acceptance Criteria for Branch, Commit, Revision, Materialization, Runtime, Run/TestRun
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.modules.versioning.application.commands.create_commit import (
    CreateCommitCommand,
    CreateCommitHandler,
)
from app.modules.versioning.domain.entities import (
    Branch,
    Commit,
    Materialization,
    PersistentDataset,
    Project,
    Repository,
    Run,
    Runtime,
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    TestRun,
)
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
    MaterializationStatus,
    PathClassification,
    Revision,
    TestRunStatus,
    Tree,
)
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
)

# ============================================================================
# Invariant 1: Runtime Pinning
# ============================================================================


def test_invariant_1_runtime_rejects_mutable_branch_reference() -> None:
    """Runtime MUST NOT be constructed binding directly to a mutable branch reference."""
    with pytest.raises(ValueError, match="Runtime cannot bind directly to a mutable branch"):
        Runtime(
            id="rt-1",
            commit_id="branch:main",
            materialization_id="mat-1",
        )

    with pytest.raises(ValueError, match="Runtime cannot bind directly to a mutable branch"):
        Runtime(
            id="rt-2",
            commit_id="refs/heads/feature",
            materialization_id="mat-1",
        )


def test_invariant_1_runtime_commit_id_immutable_after_creation() -> None:
    """Runtime commit_id cannot be changed after instantiation."""
    rt = Runtime(
        id="rt-1",
        commit_id="commit-abc-123",
        materialization_id="mat-1",
    )
    with pytest.raises(ValueError, match="Runtime commit_id is immutable"):
        rt.commit_id = "commit-def-456"


def test_invariant_1_runtime_factory_rejects_removed_materialization() -> None:
    """Runtime.create rejects binding to a removed Materialization."""
    mat = Materialization(
        id="mat-1",
        commit_id="commit-abc-123",
        root_path="/srv/minecraft/.onx/tests/test-1",
        status=MaterializationStatus.REMOVED,
    )
    with pytest.raises(ValueError, match="Runtime cannot reference a removed Materialization"):
        Runtime.create(
            id="rt-1",
            commit_id="commit-abc-123",
            materialization=mat,
        )


def test_invariant_1_runtime_factory_rejects_branch_reference() -> None:
    """Runtime.create rejects branch reference strings."""
    mat = Materialization(
        id="mat-1",
        commit_id="commit-abc-123",
        root_path="/srv/minecraft/.onx/tests/test-1",
        status=MaterializationStatus.READY,
    )
    with pytest.raises(ValueError, match="Runtime cannot bind directly to a mutable branch"):
        Runtime.create(
            id="rt-1",
            commit_id="branch:main",
            materialization=mat,
        )


# ============================================================================
# Invariant 2: Global Admission Policy (Stage D — REWRITTEN, see note)
# ============================================================================
#
# NOTE (Stage D spec §d): the Stage A per-server in-memory lock
# (DockerTestExecutionRunner._server_locks + "already active" ConflictError)
# was intentionally DELETED and subsumed by the global admission gate
# (application/scheduling/admission.admit). The old assertion below proved
# lock presence; it is replaced — not skipped — by assertions proving the
# NEW policy: same-server concurrency admitted under a global cap, denial
# past the cap, and stored RAM/core earmarks on every admitted row.


@pytest.mark.asyncio
@pytest.mark.no_isolated_db
async def test_invariant_2_existing_server_lock_policy_preserved(tmp_path) -> None:
    """Stage D policy: no per-server lock; global admission with earmarks governs."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.persistence.base import Base
    from app.modules.versioning.application.scheduling.admission import admit
    from app.modules.versioning.infrastructure.resource_probe import (
        ResourcePreflightProbe,
    )

    # The lock machinery itself is gone (§d deletion proof).
    runner = DockerTestExecutionRunner()
    assert not hasattr(runner, "_server_locks")
    assert not hasattr(runner, "_get_server_lock")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/inv2.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)

    try:
        exp_ram, exp_cores = ResourcePreflightProbe.calculate_required_resources(
            5, "paper"
        )
        # Three same-server admissions succeed under a cap of 3 (the old lock
        # allowed exactly one per server — this is the behavior change).
        with (
            patch("psutil.virtual_memory", return_value=mem),
            patch("os.cpu_count", return_value=32),
        ):
            for i in range(3):
                res = await admit(
                    server_id="srv-lock-test",
                    commit_id="commit-1",
                    bot_count=5,
                    server_type="paper",
                    engine=engine,
                    max_runs=3,
                )
                assert res.test_run.status == TestRunStatus.PENDING
                assert res.test_run.reserved_ram_mb == exp_ram
                assert res.test_run.reserved_cores == exp_cores
                assert res.occupied_count == i

            # Fourth global admission is denied with 409 (cap), not admitted.
            with pytest.raises(ConflictError, match="Global concurrent test-run cap"):
                await admit(
                    server_id="srv-lock-test",
                    commit_id="commit-1",
                    bot_count=5,
                    server_type="paper",
                    engine=engine,
                    max_runs=3,
                )
    finally:
        await engine.dispose()


# ============================================================================
# Invariant 3: Persistent Data Isolation
# ============================================================================


def test_invariant_3_persistent_dataset_rejects_tracked_config_overwrite() -> None:
    """PersistentDataset write paths cannot overlap tracked configuration in Tree."""
    dataset = PersistentDataset(
        id="ds-1",
        runtime_id="rt-1",
        dataset_root="/srv/data/world",
        server_id="srv-1",
    )
    tree = Tree(
        server_type="paper",
        minecraft_version="1.21.1",
        configs={"server.properties": "motd=Test", "config/paper.yml": "mode=1"},
        mods=[{"filename": "mods/worldedit.jar"}],
    )

    # Valid non-overlapping world write
    dataset.validate_write_path("region/r.0.0.mca", tracked_tree=tree)

    # Invalid write overlapping tracked server.properties
    with pytest.raises(ValueError, match="overlaps tracked configuration in Tree"):
        dataset.validate_write_path("server.properties", tracked_tree=tree)

    # Invalid write overlapping tracked config/paper.yml
    with pytest.raises(ValueError, match="overlaps tracked configuration in Tree"):
        dataset.validate_write_path("config/paper.yml", tracked_tree=tree)

    # Invalid write overlapping tracked mod
    with pytest.raises(ValueError, match="overlaps tracked mod in Tree"):
        dataset.validate_write_path("mods/worldedit.jar", tracked_tree=tree)


# ============================================================================
# Branch Lifecycle & Acceptance Criteria
# ============================================================================


def test_branch_lifecycle_transitions() -> None:
    """Branch transitions: created -> active on head advance -> archived."""
    branch = ServerBranch(id="b-1", server_id="srv-1", name="release")
    assert branch.status == BranchStatus.CREATED
    assert branch.head_commit_id is None

    # First head advance transitions created -> active
    branch.advance_head("commit-1")
    assert branch.status == BranchStatus.ACTIVE
    assert branch.head_commit_id == "commit-1"

    # Explicit archive transitions active -> archived
    branch.archive()
    assert branch.status == BranchStatus.ARCHIVED

    # Cannot advance head of archived branch
    with pytest.raises(ValueError, match="Cannot commit to archived branch"):
        branch.advance_head("commit-2")

    # Cannot activate archived branch
    with pytest.raises(ValueError, match="Cannot activate archived branch"):
        branch.activate()


def test_branch_validation_rejects_empty_fields() -> None:
    """Branch rejects empty server_id or name."""
    with pytest.raises(ValueError, match="Branch server_id cannot be empty"):
        ServerBranch(id="b-1", server_id="", name="main")

    with pytest.raises(ValueError, match="Branch name cannot be empty"):
        ServerBranch(id="b-1", server_id="srv-1", name="")


@pytest.mark.asyncio
async def test_create_commit_rejects_archived_branch() -> None:
    """CreateCommitHandler rejects commits targeting an archived branch."""
    from unittest.mock import AsyncMock

    v_repo = MagicMock()
    s_repo = MagicMock()
    server = MagicMock()
    server.deployment.server_dir = "/tmp/srv"
    s_repo.get = AsyncMock(return_value=server)

    archived_branch = ServerBranch(
        id="b-archived",
        server_id="srv-1",
        name="archived-feature",
        head_commit_id="commit-0",
        status=BranchStatus.ARCHIVED,
    )
    v_repo.get_branch_by_name = AsyncMock(return_value=archived_branch)

    handler = CreateCommitHandler(server_repo=s_repo, versioning_repo=v_repo)
    cmd = CreateCommitCommand(
        server_id="srv-1",
        branch_name="archived-feature",
        message="Attempted commit to archived branch",
    )

    with (
        patch("os.path.exists", return_value=True),
        patch(
            "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
        ),
        pytest.raises(ConflictError, match="Cannot commit to archived branch"),
    ):
        await handler.handle(cmd)


# ============================================================================
# Commit Ancestry, Parent Validation & Immutability
# ============================================================================


def test_commit_validates_parent_ancestry() -> None:
    """Commit validates single-parent existence and rejects cross-server parents."""
    manifest = CommitManifest(server_type="paper", minecraft_version="1.21.1")
    genesis = ServerCommit(
        id="commit-0",
        server_id="srv-1",
        message="genesis",
        manifest=manifest,
        parent_commit_id=None,
    )
    # Genesis commit has no parent to validate
    genesis.validate_parent(None)

    child = ServerCommit(
        id="commit-1",
        server_id="srv-1",
        message="child commit",
        manifest=manifest,
        parent_commit_id="commit-0",
    )
    # Valid parent
    child.validate_parent(genesis)

    # Dangling parent rejected
    with pytest.raises(ValueError, match="Dangling parent_commit_id"):
        child.validate_parent(None)

    # Mismatched parent ID rejected
    wrong_parent = ServerCommit(
        id="commit-wrong",
        server_id="srv-1",
        message="other",
        manifest=manifest,
    )
    with pytest.raises(ValueError, match="Parent commit ID mismatch"):
        child.validate_parent(wrong_parent)

    # Cross-server parent rejected
    cross_server_parent = ServerCommit(
        id="commit-0",
        server_id="srv-OTHER",
        message="cross server",
        manifest=manifest,
    )
    with pytest.raises(ValueError, match="Cross-server parent rejected"):
        child.validate_parent(cross_server_parent)


@pytest.mark.asyncio
async def test_commit_immutability_in_repository() -> None:
    """SQLVersioningRepository rejects updates to already-saved commits."""
    session = MagicMock(spec=AsyncSession)
    repo = SQLVersioningRepository(session)

    # Existing model found in DB
    existing_model = MagicMock()
    session.get.return_value = existing_model

    manifest = CommitManifest(server_type="paper", minecraft_version="1.21.1")
    commit = ServerCommit(
        id="commit-saved-1",
        server_id="srv-1",
        message="attempted mutation",
        manifest=manifest,
    )

    with pytest.raises(ConflictError, match="is immutable and cannot be updated"):
        await repo.save_commit(commit)


# ============================================================================
# Revision Value Object
# ============================================================================


def test_revision_immutability_and_source_binding() -> None:
    """Revision binds immutable commit_id and does not change if branch head moves."""
    rev = Revision.from_commit("c-100", "srv-1")
    assert rev.commit_id == "c-100"
    assert rev.server_id == "srv-1"
    assert rev.resolved_from == "commit:c-100"

    branch = ServerBranch(
        id="b-1",
        server_id="srv-1",
        name="main",
        head_commit_id="c-100",
        status=BranchStatus.ACTIVE,
    )
    branch_rev = Revision.from_branch(
        branch_name=branch.name,
        head_commit_id=branch.head_commit_id,
        branch_server_id=branch.server_id,
        target_server_id="srv-1",
    )
    assert branch_rev.commit_id == "c-100"

    # Moving branch head does NOT change previously resolved Revision
    branch.advance_head("c-200")
    assert branch.head_commit_id == "c-200"
    assert branch_rev.commit_id == "c-100"  # Unchanged!


def test_revision_rejects_cross_server_resolution() -> None:
    """Revision resolution rejects branches belonging to a different server."""
    with pytest.raises(
        ValueError,
        match="Cannot resolve branch 'main' from server 'srv-1' for target server 'srv-2'",
    ):
        Revision.from_branch(
            branch_name="main",
            head_commit_id="c-100",
            branch_server_id="srv-1",
            target_server_id="srv-2",
        )


def test_revision_rejects_empty_fields() -> None:
    """Revision rejects empty commit_id or server_id."""
    with pytest.raises(ValueError, match="Revision commit_id cannot be empty"):
        Revision(commit_id="", server_id="srv-1", resolved_from="explicit")

    with pytest.raises(ValueError, match="Revision server_id cannot be empty"):
        Revision(commit_id="c-1", server_id="", resolved_from="explicit")


# ============================================================================
# Materialization Lifecycle & Root Isolation
# ============================================================================


def test_materialization_lifecycle() -> None:
    """Materialization lifecycle: pending -> ready -> stale -> removed."""
    mat = Materialization(
        id="mat-1",
        commit_id="c-1",
        root_path="/srv/minecraft/.onx/tests/run-1",
    )
    assert mat.status == MaterializationStatus.PENDING

    mat.mark_ready()
    assert mat.status == MaterializationStatus.READY

    mat.mark_stale()
    assert mat.status == MaterializationStatus.STALE

    mat.mark_removed()
    assert mat.status == MaterializationStatus.REMOVED

    # Cannot transition removed materialization back to ready or stale
    with pytest.raises(ValueError, match="Cannot transition removed materialization to ready"):
        mat.mark_ready()

    with pytest.raises(ValueError, match="Cannot transition removed materialization to stale"):
        mat.mark_stale()

    with pytest.raises(ValueError, match="Cannot stage path into removed materialization"):
        mat.stage_path("server.properties", PathClassification.TRACKED)


def test_materialization_root_isolation_and_traversal_rejection() -> None:
    """Materialization root must be under .onx/tests and reject path traversal escapes."""
    # Invalid root outside .onx/tests
    with pytest.raises(
        ValueError,
        match="Materialization root_path must be an isolated .onx/tests directory",
    ):
        Materialization(
            id="mat-bad",
            commit_id="c-1",
            root_path="/etc/passwd",
        )

    # Invalid root with directory traversal escape
    with pytest.raises(
        ValueError,
        match="Materialization root_path must be an isolated .onx/tests directory",
    ):
        Materialization(
            id="mat-traversal",
            commit_id="c-1",
            root_path="/srv/minecraft/.onx/tests/../../etc",
        )

    # Staging path escaping root
    valid_mat = Materialization(
        id="mat-good",
        commit_id="c-1",
        root_path="/srv/minecraft/.onx/tests/run-1",
    )
    with pytest.raises(ValueError, match="Staging path escapes materialization root"):
        valid_mat.stage_path("../escape.txt", PathClassification.TRACKED)

    with pytest.raises(ValueError, match="Staging path escapes materialization root"):
        valid_mat.stage_path("/absolute/path", PathClassification.TRACKED)


# ============================================================================
# Run / TestRun Terminal State Regressions
# ============================================================================


def test_test_run_rejects_terminal_state_regressions() -> None:
    """TestRun terminal states (PASSED/FAILED/CANCELLED) cannot regress to RUNNING."""
    run = ServerTestRun(
        id="tr-1",
        server_id="srv-1",
        commit_id="c-1",
        status=TestRunStatus.PENDING,
    )
    assert not run.is_terminal

    run.mark_running()
    assert run.status == TestRunStatus.RUNNING
    assert not run.is_terminal

    run.mark_passed(log_output="All tests passed")
    assert run.status == TestRunStatus.PASSED
    assert run.is_terminal

    # Regression from PASSED to RUNNING must be rejected
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run.mark_running()

    failed_run = ServerTestRun(
        id="tr-2",
        server_id="srv-1",
        commit_id="c-1",
        status=TestRunStatus.FAILED,
    )
    assert failed_run.is_terminal
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        failed_run.mark_running()

    cancelled_run = ServerTestRun(
        id="tr-3",
        server_id="srv-1",
        commit_id="c-1",
        status=TestRunStatus.CANCELLED,
    )
    assert cancelled_run.is_terminal
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        cancelled_run.mark_running()


# ============================================================================
# Project, Repository & Tree Primitives
# ============================================================================


def test_project_and_repository_primitives() -> None:
    """Project and Repository domain primitives validate identity."""
    project = Project(id="srv-123")
    assert project.id == "srv-123"

    with pytest.raises(ValueError, match="Project id cannot be empty"):
        Project(id="")

    repo = Repository(project_id="srv-123")
    assert repo.project_id == "srv-123"

    with pytest.raises(ValueError, match="Repository project_id cannot be empty"):
        Repository(project_id="")


def test_tree_formalization_from_manifest() -> None:
    """Tree formalizes CommitManifest into version control domain."""
    manifest = CommitManifest(
        server_type="paper",
        minecraft_version="1.21.1",
        configs={"server.properties": "motd=Hello"},
        mods=[{"filename": "mods/test.jar"}],
        env_vars={"EULA": "true"},
        java_args="-Xmx4G",
    )
    tree = Tree.from_manifest(manifest)
    assert tree.server_type == "paper"
    assert tree.minecraft_version == "1.21.1"
    assert tree.configs == {"server.properties": "motd=Hello"}
    assert tree.mods == [{"filename": "mods/test.jar"}]
    assert tree.env_vars == {"EULA": "true"}
    assert tree.java_args == "-Xmx4G"

    roundtrip = tree.to_manifest()
    assert roundtrip.configs == manifest.configs
    assert roundtrip.minecraft_version == manifest.minecraft_version


def test_domain_entity_aliases() -> None:
    """Domain aliases Branch=ServerBranch, Commit=ServerCommit, Run/TestRun=ServerTestRun."""
    assert Branch is ServerBranch
    assert Commit is ServerCommit
    assert Run is ServerTestRun
    assert TestRun is ServerTestRun
