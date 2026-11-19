"""P5-1 Alembic b1e2100000030 schema + models + exceptions tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command as alembic_command
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    GitHubAuthFailedError,
    GitHubNotConnectedError,
    GitHubPushRejectedError,
    NonFastForwardMainError,
    WebhookSignatureError,
)
from app.core.persistence.base import Base
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerGitHubConnectionModel,
)

PRIOR_HEAD = "b1e2100000029"
P5_REVISION = "b1e2100000030"


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _tables(db_url: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(db_url: str, table: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _unique_constraints(
    db_url: str, table: str
) -> set[tuple[str | None, tuple[str, ...]]]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspect(engine).get_unique_constraints(table)
        }
    finally:
        engine.dispose()


def _column_default(column: dict) -> str | None:
    # SQLite reflection reports server defaults through ``default``; other
    # dialects report them through ``server_default``.
    raw = column.get("server_default")
    if raw is None:
        raw = column.get("default")
    if raw is None:
        return None
    return str(raw).strip("'\"")


def _create_sqlite_engine(db_file: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    return engine


def _add_server(sync_url: str, server_id: str) -> None:
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO servers (id, name, minecraft_version, server_type) "
                    "VALUES (:id, :name, :mv, :st)"
                ),
                {"id": server_id, "name": server_id, "mv": "1.21", "st": "paper"},
            )
    finally:
        engine.dispose()


@pytest.mark.no_isolated_db
def test_p51_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p51-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    cfg = reconciler.get_alembic_config()

    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]
    assert script.get_heads() == ["b1e2100000030"]
    assert script.get_heads() == [RELEASE_MINIMUM_DB_REVISION]
    assert script.get_revision(P5_REVISION).down_revision == PRIOR_HEAD

    assert "server_github_connections" in _tables(db_url)
    assert "github_webhook_deliveries" in _tables(db_url)

    conn_cols = _columns(db_url, "server_github_connections")
    expected_conn = {
        "id",
        "server_id",
        "remote_url",
        "auth_method",
        "wrapped_credential_dek",
        "kek_version",
        "credential_nonce",
        "credential_ciphertext",
        "credential_hint",
        "deploy_public_key",
        "wrapped_webhook_dek",
        "webhook_kek_version",
        "webhook_nonce",
        "webhook_ciphertext",
        "webhook_enabled",
        "sync_status",
        "last_error_code",
        "last_error_message",
        "last_fetch_at",
        "last_push_at",
        "remote_default_branch",
        "remote_head_sha",
        "branch_sync_json",
        "created_at",
        "updated_at",
    }
    assert set(conn_cols) == expected_conn
    assert {
        name for name, column in conn_cols.items() if column["nullable"]
    } == {
        "credential_hint",
        "deploy_public_key",
        "wrapped_webhook_dek",
        "webhook_kek_version",
        "webhook_nonce",
        "webhook_ciphertext",
        "last_error_code",
        "last_error_message",
        "last_fetch_at",
        "last_push_at",
        "remote_default_branch",
        "remote_head_sha",
        "branch_sync_json",
    }
    assert {
        name: _column_default(column)
        for name, column in conn_cols.items()
        if _column_default(column) is not None
    } == {
        "kek_version": "1",
        "webhook_enabled": "0",
        "sync_status": "idle",
    }
    assert _unique_constraints(db_url, "server_github_connections") == {
        ("uq_server_github_connections_server_id", ("server_id",))
    }

    delivery_cols = _columns(db_url, "github_webhook_deliveries")
    expected_delivery = {
        "id",
        "server_id",
        "delivery_id",
        "event_type",
        "ref",
        "before_sha",
        "after_sha",
        "payload_sha256",
        "raw_payload",
        "signature_valid",
        "status",
        "operation_id",
        "error_message",
        "redelivery_count",
        "received_at",
        "processed_at",
    }
    assert set(delivery_cols) == expected_delivery
    assert {
        name for name, column in delivery_cols.items() if column["nullable"]
    } == {
        "ref",
        "before_sha",
        "after_sha",
        "operation_id",
        "error_message",
        "processed_at",
    }
    assert {
        name: _column_default(column)
        for name, column in delivery_cols.items()
        if _column_default(column) is not None
    } == {
        "signature_valid": "0",
        "status": "received",
        "redelivery_count": "0",
    }
    assert _unique_constraints(db_url, "github_webhook_deliveries") == {
        ("uq_github_webhook_deliveries_server_delivery", ("server_id", "delivery_id"))
    }

    assert "ix_server_github_connections_server_id" in _indexes(db_url, "server_github_connections")
    assert "ix_github_webhook_deliveries_server_id" in _indexes(db_url, "github_webhook_deliveries")
    assert "ix_github_webhook_deliveries_server_received" in _indexes(
        db_url, "github_webhook_deliveries"
    )

    # Unique constraint enforcement
    sync_url = _sync_url(db_url)
    _add_server(sync_url, "srv-1")
    _add_server(sync_url, "srv-2")
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO server_github_connections (id, server_id, remote_url, auth_method, "
                "wrapped_credential_dek, kek_version, credential_nonce, credential_ciphertext, "
                "created_at, updated_at) VALUES (:id, :sid, :url, :am, :wdek, 1, :nonce, :ct, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": "c1",
                "sid": "srv-1",
                "url": "https://github.com/o/r",
                "am": "pat",
                "wdek": b"\x00" * 60,
                "nonce": b"\x00" * 12,
                "ct": b"\x00" * 16,
            },
        )
    # duplicate server_id raises
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO server_github_connections (id, server_id, remote_url, auth_method, "
                "wrapped_credential_dek, kek_version, credential_nonce, credential_ciphertext, "
                "created_at, updated_at) VALUES (:id, :sid, :url, :am, :wdek, 1, :nonce, :ct, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": "c2",
                "sid": "srv-1",
                "url": "https://github.com/o/r",
                "am": "pat",
                "wdek": b"\x00" * 60,
                "nonce": b"\x00" * 12,
                "ct": b"\x00" * 16,
            },
        )
    engine.dispose()

    # webhook deliveries unique (server_id, delivery_id)
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO github_webhook_deliveries (id, server_id, delivery_id, event_type, "
                "payload_sha256, raw_payload, received_at) VALUES (:id, :sid, :did, :et, :ps, :rp, "
                "CURRENT_TIMESTAMP)"
            ),
            {"id": "d1", "sid": "srv-1", "did": "del-1", "et": "push", "ps": "0" * 64, "rp": "{}"},
        )
        conn.execute(
            text(
                "INSERT INTO github_webhook_deliveries (id, server_id, delivery_id, event_type, "
                "payload_sha256, raw_payload, received_at) VALUES (:id, :sid, :did, :et, :ps, :rp, "
                "CURRENT_TIMESTAMP)"
            ),
            {"id": "d2", "sid": "srv-2", "did": "del-1", "et": "push", "ps": "0" * 64, "rp": "{}"},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO github_webhook_deliveries (id, server_id, delivery_id, event_type, "
                "payload_sha256, raw_payload, received_at) VALUES (:id, :sid, :did, :et, :ps, :rp, "
                "CURRENT_TIMESTAMP)"
            ),
            {"id": "d3", "sid": "srv-1", "did": "del-1", "et": "push", "ps": "0" * 64, "rp": "{}"},
        )
    engine.dispose()

    # downgrade
    alembic_command.downgrade(cfg, PRIOR_HEAD)
    remaining = _tables(db_url)
    assert "server_github_connections" not in remaining
    assert "github_webhook_deliveries" not in remaining

    alembic_command.upgrade(cfg, P5_REVISION)
    assert "server_github_connections" in _tables(db_url)
    assert "github_webhook_deliveries" in _tables(db_url)


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_p51_orm_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "p51-orm.db"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            session.add(
                ServerModel(id="srv-1", name="srv-1", minecraft_version="1.21", server_type="paper")
            )
            await session.commit()

        async with factory() as session:
            conn_row = ServerGitHubConnectionModel(
                id="conn-1",
                server_id="srv-1",
                remote_url="https://github.com/o/r",
                auth_method="pat",
                wrapped_credential_dek=b"\x01" * 60,
                kek_version=1,
                credential_nonce=b"\x02" * 12,
                credential_ciphertext=b"\x03" * 16,
            )
            session.add(conn_row)
            await session.commit()

        async with factory() as session:
            loaded = await session.get(ServerGitHubConnectionModel, "conn-1")
            assert loaded is not None
            assert loaded.server_id == "srv-1"
            assert loaded.auth_method == "pat"

        async with factory() as session:
            delivery = GitHubWebhookDeliveryModel(
                id="del-1",
                server_id="srv-1",
                delivery_id="delivery-1",
                event_type="push",
                payload_sha256="a" * 64,
                raw_payload="{}",
            )
            session.add(delivery)
            await session.commit()

        async with factory() as session:
            loaded = await session.get(GitHubWebhookDeliveryModel, "del-1")
            assert loaded is not None
            assert loaded.status == "received"
            assert loaded.signature_valid is False
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
def test_p51_exceptions() -> None:
    err = NonFastForwardMainError(local_sha="abc", remote_sha="def")
    assert err.code == "GITHUB_NON_FAST_FORWARD_MAIN"
    assert err.http_status == 409
    assert isinstance(err, ConflictError)
    assert err.details.get("branch") == "main"
    assert err.local_sha == "abc"
    assert err.remote_sha == "def"

    err2 = GitHubNotConnectedError(server_id="srv-1")
    assert err2.code == "GITHUB_NOT_CONNECTED"
    assert err2.http_status == 409
    assert isinstance(err2, ConflictError)
    assert "srv-1" in str(err2)
    assert err2.details.get("server_id") == "srv-1"

    err3 = GitHubAuthFailedError(needs_reauth=True, auth_method="pat", reason="bad")
    assert err3.code == "GITHUB_AUTH_FAILED"
    assert err3.http_status == 409
    assert isinstance(err3, ConflictError)
    assert err3.needs_reauth is True
    assert err3.details.get("needs_reauth") is True
    assert err3.details.get("auth_method") == "pat"

    err4 = WebhookSignatureError()
    assert err4.code == "GITHUB_WEBHOOK_SIGNATURE_INVALID"
    assert err4.http_status == 401
    assert isinstance(err4, AuthenticationError)
    assert err4.details == {}

    err5 = GitHubPushRejectedError(branch="main", reason="rejected")
    assert err5.code == "GITHUB_PUSH_REJECTED"
    assert err5.http_status == 409
    assert isinstance(err5, ConflictError)
    assert err5.details.get("branch") == "main"
    assert err5.details.get("reason") == "rejected"


@pytest.mark.no_isolated_db
def test_p51_exception_details_are_bounded_and_secret_free() -> None:
    long_sha = "c" * 200
    truncated_sha = NonFastForwardMainError(local_sha=long_sha, remote_sha=long_sha)
    assert truncated_sha.details["local_sha"] == long_sha[:64]
    assert truncated_sha.details["remote_sha"] == long_sha[:64]
    assert long_sha not in repr(truncated_sha.details)

    long_server = "srv-" + "x" * 200
    truncated_server = GitHubNotConnectedError(server_id=long_server)
    assert truncated_server.details["server_id"] == long_server[:64]
    assert long_server not in repr(truncated_server.details)

    truncated_auth = GitHubAuthFailedError(
        auth_method="m" * 100,
        reason="r" * 500,
    )
    assert truncated_auth.details["auth_method"] == "m" * 32
    assert truncated_auth.details["reason"] == "r" * 256

    truncated_push = GitHubPushRejectedError(
        branch="b" * 300,
        reason="q" * 500,
    )
    assert truncated_push.details["branch"] == "b" * 128
    assert truncated_push.details["reason"] == "q" * 256

    no_signature = WebhookSignatureError()
    assert no_signature.details == {}

    secretish_keys = {
        "authorization",
        "credential",
        "digest",
        "password",
        "pat",
        "private_key",
        "secret",
        "signature",
        "token",
    }
    expected_detail_keys = {
        "GITHUB_NON_FAST_FORWARD_MAIN": {"branch", "local_sha", "remote_sha"},
        "GITHUB_NOT_CONNECTED": {"server_id"},
        "GITHUB_AUTH_FAILED": {"auth_method", "needs_reauth", "reason"},
        "GITHUB_WEBHOOK_SIGNATURE_INVALID": set(),
        "GITHUB_PUSH_REJECTED": {"branch", "reason"},
    }
    exceptions = (
        truncated_sha,
        truncated_server,
        truncated_auth,
        no_signature,
        truncated_push,
    )
    for exc in exceptions:
        assert set(exc.details) == expected_detail_keys[exc.code]
        assert not (set(exc.details) & secretish_keys)
        rendered = f"{exc.message}\n{exc.details!r}\n{exc!s}\n{exc!r}"
        assert "ghp_" not in rendered
        assert "github_pat_" not in rendered
        assert "PRIVATE KEY" not in rendered
        assert "sha256=" not in rendered
