"""Username-only auth (nullable email) and local zero-login system_state flag.

Revision ID: b1e2100000033
Revises: b1e2100000032
Create Date: 2026-11-22 23:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b1e2100000033"
down_revision = "b1e2100000032"
branch_labels = None
depends_on = None

USERS_TABLE = "users"
USERS_USERNAME_COL = "username"
USERS_USERNAME_INDEX = "ix_users_username"
SYSTEM_STATE_TABLE = "system_state"
PASSWORD_CONFIGURED_COL = "password_configured"


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {str(idx["name"]) for idx in inspector.get_indexes(table_name) if idx.get("name")}


def _backfill_usernames() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, email, display_name, username FROM users ORDER BY created_at, id")
    ).fetchall()
    seen_lower: set[str] = set()
    for _row_id, _email, _display_name, existing_username in rows:
        if isinstance(existing_username, str) and existing_username.strip():
            seen_lower.add(existing_username.strip().lower())

    for row_id, email, display_name, existing_username in rows:
        if isinstance(existing_username, str) and existing_username.strip():
            continue
        base = ""
        if isinstance(email, str) and email.strip():
            base = email.strip()
        elif isinstance(display_name, str) and display_name.strip():
            base = display_name.strip().replace(" ", "_")
        else:
            base = str(row_id)
        candidate = base[:128]
        if candidate.lower() in seen_lower:
            suffix = f"_{str(row_id)[:8]}"
            candidate = f"{base[: 128 - len(suffix)]}{suffix}"
        seen_lower.add(candidate.lower())
        bind.execute(
            sa.text("UPDATE users SET username = :u WHERE id = :id"),
            {"u": candidate, "id": row_id},
        )


def upgrade() -> None:
    user_cols = _existing_columns(USERS_TABLE)
    if user_cols:
        if USERS_USERNAME_COL not in user_cols:
            with op.batch_alter_table(USERS_TABLE) as batch_op:
                batch_op.add_column(
                    sa.Column(USERS_USERNAME_COL, sa.String(length=128), nullable=True)
                )

        _backfill_usernames()

        with op.batch_alter_table(USERS_TABLE) as batch_op:
            batch_op.alter_column(
                "email",
                existing_type=sa.String(length=255),
                nullable=True,
            )
            batch_op.alter_column(
                USERS_USERNAME_COL,
                existing_type=sa.String(length=128),
                nullable=False,
            )

        user_indexes = _existing_indexes(USERS_TABLE)
        if USERS_USERNAME_INDEX not in user_indexes:
            op.create_index(
                USERS_USERNAME_INDEX,
                USERS_TABLE,
                [USERS_USERNAME_COL],
                unique=True,
            )

    sys_cols = _existing_columns(SYSTEM_STATE_TABLE)
    if sys_cols and PASSWORD_CONFIGURED_COL not in sys_cols:
        with op.batch_alter_table(SYSTEM_STATE_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    PASSWORD_CONFIGURED_COL,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
        bind = op.get_bind()
        bind.execute(
            sa.text("UPDATE system_state SET password_configured = 0 WHERE initialized = 0")
        )


def downgrade() -> None:
    sys_cols = _existing_columns(SYSTEM_STATE_TABLE)
    if sys_cols and PASSWORD_CONFIGURED_COL in sys_cols:
        with op.batch_alter_table(SYSTEM_STATE_TABLE) as batch_op:
            batch_op.drop_column(PASSWORD_CONFIGURED_COL)

    user_cols = _existing_columns(USERS_TABLE)
    if user_cols:
        user_indexes = _existing_indexes(USERS_TABLE)
        if USERS_USERNAME_INDEX in user_indexes:
            op.drop_index(USERS_USERNAME_INDEX, table_name=USERS_TABLE)

        if USERS_USERNAME_COL in user_cols:
            bind = op.get_bind()
            bind.execute(
                sa.text(
                    "UPDATE users SET email = username || '@local.invalid' "
                    "WHERE email IS NULL OR email = ''"
                )
            )
            with op.batch_alter_table(USERS_TABLE) as batch_op:
                batch_op.alter_column(
                    "email",
                    existing_type=sa.String(length=255),
                    nullable=False,
                )
                batch_op.drop_column(USERS_USERNAME_COL)
