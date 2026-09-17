from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
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
