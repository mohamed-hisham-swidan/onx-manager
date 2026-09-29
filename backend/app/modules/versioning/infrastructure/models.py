from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.persistence.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ServerBranchModel(Base):
    __tablename__ = "server_branches"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    head_commit_id = Column(String(36), nullable=True)
    status = Column(String(32), nullable=False, default="created")
    is_protected = Column(Boolean, nullable=False, default=False)
    protection_policy = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_server_branch_name"),)


class ServerTagModel(Base):
    __tablename__ = "server_tags"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    commit_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_server_tag_name"),)


class ServerCommitParentModel(Base):
    __tablename__ = "server_commit_parents"

    commit_id = Column(String(36), primary_key=True, index=True)
    parent_commit_id = Column(String(36), primary_key=True, index=True)
    parent_index = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("commit_id", "parent_index", name="uq_commit_parent_index"),
    )


class ServerWorldSnapshotModel(Base):
    __tablename__ = "server_world_snapshots"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    storage_path = Column(String(512), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ServerCommitModel(Base):
    __tablename__ = "server_commits"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    branch_id = Column(String(36), nullable=True, index=True)
    parent_commit_id = Column(String(36), nullable=True, index=True)
    author_id = Column(String(36), nullable=True)
    message = Column(String(255), nullable=False)
    manifest_json = Column(JSON, nullable=False)
    world_snapshot_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ServerTestRunModel(Base):
    __tablename__ = "server_test_runs"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    commit_id = Column(String(36), nullable=False, index=True)
    node_id = Column(String(64), nullable=False, default="local")
    status = Column(String(32), nullable=False, default="PENDING")
    ephemeral_port = Column(Integer, nullable=True)
    log_output = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    bot_count = Column(Integer, nullable=False, default=10)
    duration_minutes = Column(Integer, nullable=False, default=15)
    placement_mode = Column(String(32), nullable=False, default="sidecar")
    bot_tech = Column(String(32), nullable=False, default="auto")
    # Stage D admission earmarks (nullable for pre-b1e2100000017 rows).
    reserved_ram_mb = Column(Integer, nullable=True)
    reserved_cores = Column(Integer, nullable=True)
    # Stage F: Runtime entity & TestDefinition links, evidence bundle & retention
    runtime_id = Column(
        String(64), ForeignKey("server_runtimes.id", ondelete="SET NULL"), nullable=True
    )
    test_definition_id = Column(
        String(64), ForeignKey("server_test_definitions.id", ondelete="SET NULL"), nullable=True
    )
    evidence_bundle = Column(JSON, nullable=True)
    artifacts_purged = Column(Boolean, nullable=False, default=False)
    # Stage B: Operation linkage
    operation_id = Column(String(36), nullable=True, index=True)


class ServerTestDefinitionModel(Base):
    __tablename__ = "server_test_definitions"

    id = Column(String(64), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False, default="")
    server_type = Column(String(32), nullable=False, default="vanilla")
    bot_technology = Column(String(32), nullable=False, default="mineflayer")
    bot_count = Column(Integer, nullable=False, default=5)
    duration_seconds = Column(Integer, nullable=False, default=60)
    join_stagger_seconds = Column(Float, nullable=False, default=1.0)
    connect_grace_seconds = Column(Integer, nullable=False, default=20)
    placement_mode = Column(String(32), nullable=False, default="sidecar")
    assertion_rules = Column(JSON, nullable=False, default=dict)
    timeout_seconds = Column(Integer, nullable=False, default=300)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ServerRuntimeModel(Base):
    __tablename__ = "server_runtimes"

    id = Column(String(64), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commit_id = Column(String(64), ForeignKey("server_commits.id"), nullable=False)
    materialization_id = Column(String(64), nullable=True)
    provider_type = Column(String(32), nullable=False, default="docker")
    container_id = Column(String(255), nullable=True)
    pid = Column(Integer, nullable=True)
    port = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="starting")
    exit_code = Column(Integer, nullable=True)
    oom_killed = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ServerAdmissionLeaseModel(Base):
    """Single-row cross-process mutex for test-run admission (Stage D).

    Exactly one row (id=1) exists; admission claims it inside its transaction
    (SELECT ... FOR UPDATE on Postgres-family, BEGIN IMMEDIATE ordering on
    SQLite) so reap-read-check-earmark serializes across worker processes.
    """

    __tablename__ = "server_admission_lease"

    id = Column(Integer, primary_key=True)
    holder = Column(String(128), nullable=False, default="")
    acquired_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (CheckConstraint("id = 1", name="ck_admission_lease_singleton"),)


class ServerMaterializationModel(Base):
    __tablename__ = "server_materializations"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    commit_id = Column(String(36), nullable=False, index=True)
    root_path = Column(String(512), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    mode = Column(String(32), nullable=False, default="readonly")
    revision = Column(String(255), nullable=False, default="")
    path_classification = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ServerImportReviewModel(Base):
    __tablename__ = "server_import_reviews"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    commit_id = Column(String(36), nullable=False, index=True)
    parent_commit_id = Column(String(36), nullable=True, index=True)
    branch_name = Column(String(64), nullable=False, default="main")
    status = Column(String(32), nullable=False, default="pending")
    changes = Column(JSON, nullable=False, default=list)
    revert_commit_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

