"""add unique constraints to previous_hash on event_store and audit_log

Revision ID: b1e2100000011
Revises: b1e2100000010
Create Date: 2026-09-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b1e2100000011"
down_revision: str | None = "b1e2100000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("event_store", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_event_store_previous_hash", ["previous_hash"])

    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_audit_log_previous_hash", ["previous_hash"])


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_constraint("uq_audit_log_previous_hash", type_="unique")

    with op.batch_alter_table("event_store", schema=None) as batch_op:
        batch_op.drop_constraint("uq_event_store_previous_hash", type_="unique")
