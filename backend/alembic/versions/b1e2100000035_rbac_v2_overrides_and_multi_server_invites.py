"""RBAC v2 permission overrides, all-servers toggle, and multi-server invites.

Revision ID: b1e2100000035
Revises: b1e2100000034
Create Date: 2026-11-26 23:00:00.000000
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000035"
down_revision: str | None = "b1e2100000034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANONICAL_ROLES: dict[str, tuple[str, list[str]]] = {
    "owner": (
        "Instance owner with full host, exposure, and panel access",
        ["admin:full", "global:*"],
    ),
    "admin": (
        "Instance administrator with full fleet, server, and non-owner user management",
        ["admin:full"],
    ),
    "server_admin": (
        "Server administrator restricted to assigned servers and enabled capabilities",
        ["server:read"],
    ),
    "viewer": (
        "Read-only viewer restricted to assigned servers or fleet read access",
        ["server:read", "backup:read", "plugin:read", "server:version:read"],
    ),
}


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _ensure_canonical_roles(conn: sa.Connection) -> dict[str, str]:
    """Seed canonical 4-tier roles and align their permissions JSON cleanly."""
    role_ids: dict[str, str] = {}
    rows = conn.execute(sa.text("SELECT id, name FROM roles")).fetchall()
    existing_by_name = {str(r[1]): str(r[0]) for r in rows}

    for role_name, (description, perms) in _CANONICAL_ROLES.items():
        perms_json = json.dumps(perms)
        if role_name in existing_by_name:
            role_id = existing_by_name[role_name]
            conn.execute(
                sa.text(
                    "UPDATE roles SET permissions = :perms, description = :desc "
                    "WHERE id = :role_id"
                ),
                {"perms": perms_json, "desc": description, "role_id": role_id},
            )
        else:
            role_id = uuid.uuid4().hex
            conn.execute(
                sa.text(
                    "INSERT INTO roles (id, name, description, permissions) "
                    "VALUES (:role_id, :name, :desc, :perms)"
                ),
                {
                    "role_id": role_id,
                    "name": role_name,
                    "desc": description,
                    "perms": perms_json,
                },
            )
        role_ids[role_name] = role_id
    return role_ids


def _migrate_legacy_member_users(
    conn: sa.Connection, role_ids: dict[str, str]
) -> None:
    """Re-map legacy 'member' user_roles to 'server_admin' or 'viewer' safely."""
    member_row = conn.execute(
        sa.text("SELECT id FROM roles WHERE name = 'member'")
    ).fetchone()
    if member_row is None:
        return
    member_role_id = str(member_row[0])

    user_rows = conn.execute(
        sa.text("SELECT user_id FROM user_roles WHERE role_id = :rid"),
        {"rid": member_role_id},
    ).fetchall()

    inspector = sa.inspect(conn)
    has_memberships = inspector.has_table("server_memberships")
    has_servers = inspector.has_table("servers")

    for (user_id,) in user_rows:
        has_admin_membership = False
        owns_server = False

        if has_memberships:
            mem_rows = conn.execute(
                sa.text(
                    "SELECT role FROM server_memberships WHERE user_id = :uid"
                ),
                {"uid": user_id},
            ).fetchall()
            has_admin_membership = any(
                str(r[0]).lower() in {"admin", "server_admin", "dev"}
                for r in mem_rows
            )

        if has_servers:
            srv_cols = {c["name"] for c in inspector.get_columns("servers")}
            if "owner_id" in srv_cols:
                owned_row = conn.execute(
                    sa.text(
                        "SELECT 1 FROM servers WHERE owner_id = :uid LIMIT 1"
                    ),
                    {"uid": user_id},
                ).fetchone()
                owns_server = owned_row is not None

        target_role = (
            "server_admin"
            if (has_admin_membership or owns_server)
            else "viewer"
        )
        target_role_id = role_ids[target_role]

        already_has_target = conn.execute(
            sa.text(
                "SELECT 1 FROM user_roles WHERE user_id = :uid AND role_id = :rid"
            ),
            {"uid": user_id, "rid": target_role_id},
        ).fetchone()
        if already_has_target is not None:
            conn.execute(
                sa.text(
                    "DELETE FROM user_roles WHERE user_id = :uid AND role_id = :rid"
                ),
                {"uid": user_id, "rid": member_role_id},
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE user_roles SET role_id = :target_rid "
                    "WHERE user_id = :uid AND role_id = :member_rid"
                ),
                {
                    "target_rid": target_role_id,
                    "uid": user_id,
                    "member_rid": member_role_id,
                },
            )


def _backfill_invitation_server_ids(conn: sa.Connection) -> None:
    """Populate invitations.server_ids_json from legacy server_id where empty."""
    rows = conn.execute(
        sa.text(
            "SELECT id, server_id, server_ids_json FROM invitations "
            "WHERE server_id IS NOT NULL"
        )
    ).fetchall()
    for inv_id, server_id, raw_ids in rows:
        parsed: list[str] = []
        if isinstance(raw_ids, list):
            parsed = [str(x) for x in raw_ids if x]
        elif isinstance(raw_ids, str):
            try:
                decoded = json.loads(raw_ids)
                if isinstance(decoded, list):
                    parsed = [str(x) for x in decoded if x]
            except json.JSONDecodeError:
                parsed = []
        if not parsed and server_id:
            conn.execute(
                sa.text(
                    "UPDATE invitations SET server_ids_json = :ids WHERE id = :inv_id"
                ),
                {"ids": json.dumps([str(server_id)]), "inv_id": str(inv_id)},
            )


def upgrade() -> None:
    user_cols = _existing_columns("users")
    with op.batch_alter_table("users") as batch_op:
        if "denied_permissions" not in user_cols:
            batch_op.add_column(
                sa.Column(
                    "denied_permissions",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
        if "all_servers_access" not in user_cols:
            batch_op.add_column(
                sa.Column(
                    "all_servers_access",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    invite_cols = _existing_columns("invitations")
    with op.batch_alter_table("invitations") as batch_op:
        if "server_ids_json" not in invite_cols:
            batch_op.add_column(
                sa.Column(
                    "server_ids_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
        if "denied_permissions_json" not in invite_cols:
            batch_op.add_column(
                sa.Column(
                    "denied_permissions_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
        if "all_servers_access" not in invite_cols:
            batch_op.add_column(
                sa.Column(
                    "all_servers_access",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("invitations"):
        _backfill_invitation_server_ids(conn)
    if inspector.has_table("roles") and inspector.has_table("user_roles"):
        role_ids = _ensure_canonical_roles(conn)
        _migrate_legacy_member_users(conn, role_ids)


def downgrade() -> None:
    invite_cols = _existing_columns("invitations")
    if invite_cols:
        with op.batch_alter_table("invitations") as batch_op:
            if "all_servers_access" in invite_cols:
                batch_op.drop_column("all_servers_access")
            if "denied_permissions_json" in invite_cols:
                batch_op.drop_column("denied_permissions_json")
            if "server_ids_json" in invite_cols:
                batch_op.drop_column("server_ids_json")

    user_cols = _existing_columns("users")
    if user_cols:
        with op.batch_alter_table("users") as batch_op:
            if "all_servers_access" in user_cols:
                batch_op.drop_column("all_servers_access")
            if "denied_permissions" in user_cols:
                batch_op.drop_column("denied_permissions")
