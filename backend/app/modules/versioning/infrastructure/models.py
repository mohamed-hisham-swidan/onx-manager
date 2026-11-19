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
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
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

    port_set_json = Column(JSON, nullable=True)
    runtime_status = Column(String(32), nullable=False, default="stopped", server_default="stopped")
    active_runtime_id = Column(String(64), nullable=True)
    active_commit_sha = Column(String(64), nullable=True)
    active_data_template_id = Column(String(36), nullable=True)

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
    # P4
    branch_name = Column(String(64), nullable=True)
    data_template_id = Column(String(36), nullable=True)
    port_set_json = Column(JSON, nullable=True)


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

    # P4
    branch_name = Column(String(64), nullable=True)
    data_template_id = Column(String(36), nullable=True)
    port_set_json = Column(JSON, nullable=True)
    allow_public_test_join = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    export_path = Column(String(512), nullable=True)

    __table_args__ = (Index("ix_server_runtimes_server_branch", "server_id", "branch_name"),)


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


class ServerRepoLeaseModel(Base):
    """Per-server lease guarding repo refresh/rollback mutations (P2-5)."""

    __tablename__ = "server_repo_leases"

    server_id = Column(String(36), primary_key=True)
    holder = Column(String(128), nullable=True)
    fencing_token = Column(BigInteger, nullable=False, default=0)
    previous_tree_retention = Column(String(32), nullable=False, default="until_health_gate")
    acquired_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RefreshJournalModel(Base):
    """Durable journal for atomic refresh/rollback with one active row per server."""

    __tablename__ = "refresh_journals"

    journal_id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    export_id = Column(String(36), nullable=True)
    fencing_token = Column(BigInteger, nullable=False)
    phase = Column(String(64), nullable=False, index=True)
    terminal = Column(Boolean, nullable=False, default=False)
    previous_main_sha = Column(String(64), nullable=True)
    target_main_sha = Column(String(64), nullable=True)
    pre_upgrade_backup_id = Column(String(36), nullable=True)
    class_c_snapshot_id = Column(String(36), nullable=True)
    live_path = Column(Text, nullable=False)
    staging_path = Column(Text, nullable=False)
    previous_path = Column(Text, nullable=True)
    used_exchange = Column(Boolean, nullable=False, default=False)
    carried_entries_json = Column(Text, nullable=False, default="[]")
    retention_policy = Column(String(32), nullable=False, default="until_health_gate")
    previous_tree_retained = Column(Boolean, nullable=False, default=False)
    previous_tree_expires_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index(
            "ix_refresh_journals_server_active",
            "server_id",
            unique=True,
            sqlite_where=text("terminal = 0"),
            postgresql_where=text("terminal = false"),
        ),
    )


class ClassCSnapshotModel(Base):
    """Encrypted Class-C snapshot ledger (P3-3, FORMAT_VERSION = 2)."""

    __tablename__ = "class_c_snapshots"

    snapshot_id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    manifest_sha256 = Column(String(64), nullable=False)
    kek_version = Column(Integer, nullable=False, server_default=text("1"))
    file_count = Column(Integer, nullable=False, server_default=text("0"))
    total_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    pinned = Column(Boolean, nullable=False, server_default=text("0"))
    status = Column(String(16), nullable=False, server_default="active")

    __table_args__ = (
        Index("ix_class_c_snapshots_server_id", "server_id"),
        Index(
            "ix_class_c_snapshots_server_created_at",
            "server_id",
            "created_at",
        ),
    )


class ServerSecretModel(Base):
    """Per-record encrypted ``${ONX_SECRET_*}`` value (P3-3, H3)."""

    __tablename__ = "server_secrets"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    key_name = Column(String(128), nullable=False)
    wrapped_dek = Column(LargeBinary, nullable=False)
    kek_version = Column(Integer, nullable=False, server_default=text("1"))
    nonce = Column(LargeBinary(12), nullable=False)
    ciphertext = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "server_id", "key_name", name="uq_server_secrets_server_key"
        ),
        Index("ix_server_secrets_server_id", "server_id"),
    )


class ServerDynamicClassCModel(Base):
    """Per-server dynamic Class-C promotion registry (P3-2, D-D / OD-v8.4-4)."""

    __tablename__ = "server_dynamic_class_c"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    relpath = Column(String(512), nullable=False)
    reason = Column(String(128), nullable=False, server_default="ast_diverged")
    baseline_ast_sha256 = Column(String(64), nullable=True)
    live_ast_sha256 = Column(String(64), nullable=True)
    promoted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("server_id", "relpath", name="uq_server_dynamic_class_c_path"),
        Index("ix_server_dynamic_class_c_server_id", "server_id"),
    )


class ServerDataTemplateModel(Base):
    __tablename__ = "server_data_templates"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False, default="", server_default="")
    source_branch_name = Column(String(64), nullable=True)
    source_commit_sha = Column(String(64), nullable=True)
    storage_path = Column(String(512), nullable=False)
    file_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    total_bytes = Column(BigInteger, nullable=False, default=0, server_default=text("0"))
    status = Column(String(32), nullable=False, default="ready", server_default="ready")
    operation_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_server_data_template_name"),
        Index("ix_server_data_templates_server_id", "server_id"),
    )


class ServerGitHubConnectionModel(Base):
    """Per-server GitHub remote connection with encrypted credentials (P5)."""

    __tablename__ = "server_github_connections"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    remote_url = Column(String(512), nullable=False)
    auth_method = Column(String(32), nullable=False)
    wrapped_credential_dek = Column(LargeBinary, nullable=False)
    kek_version = Column(Integer, nullable=False, server_default=text("1"))
    credential_nonce = Column(LargeBinary(12), nullable=False)
    credential_ciphertext = Column(LargeBinary, nullable=False)
    credential_hint = Column(String(64), nullable=True)
    deploy_public_key = Column(Text, nullable=True)
    wrapped_webhook_dek = Column(LargeBinary, nullable=True)
    webhook_kek_version = Column(Integer, nullable=True)
    webhook_nonce = Column(LargeBinary(12), nullable=True)
    webhook_ciphertext = Column(LargeBinary, nullable=True)
    webhook_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    sync_status = Column(
        String(32), nullable=False, default="idle", server_default="idle"
    )
    last_error_code = Column(String(64), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    last_fetch_at = Column(DateTime(timezone=True), nullable=True)
    last_push_at = Column(DateTime(timezone=True), nullable=True)
    remote_default_branch = Column(String(64), nullable=True)
    remote_head_sha = Column(String(64), nullable=True)
    branch_sync_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "server_id", name="uq_server_github_connections_server_id"
        ),
        Index("ix_server_github_connections_server_id", "server_id"),
    )


class GitHubWebhookDeliveryModel(Base):
    """Durable ledger of received GitHub webhook deliveries (P5)."""

    __tablename__ = "github_webhook_deliveries"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    delivery_id = Column(String(128), nullable=False)
    event_type = Column(String(64), nullable=False)
    ref = Column(String(256), nullable=True)
    before_sha = Column(String(64), nullable=True)
    after_sha = Column(String(64), nullable=True)
    payload_sha256 = Column(String(64), nullable=False)
    raw_payload = Column(Text, nullable=False)
    signature_valid = Column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    status = Column(
        String(32), nullable=False, default="received", server_default="received"
    )
    operation_id = Column(String(36), nullable=True)
    error_message = Column(String(512), nullable=True)
    redelivery_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    received_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "delivery_id",
            name="uq_github_webhook_deliveries_server_delivery",
        ),
        Index("ix_github_webhook_deliveries_server_id", "server_id"),
        Index(
            "ix_github_webhook_deliveries_server_received",
            "server_id",
            "received_at",
        ),
    )
