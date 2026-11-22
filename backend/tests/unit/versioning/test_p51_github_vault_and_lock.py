"""P5-1 GitHub vault and RepoWriteLock tests."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import (
    ConflictError,
    FencingTokenMismatchError,
    MasterKekVersionMismatchError,
    MCSError,
    ValidationError,
    WebhookSignatureError,
)
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.base import Base
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.repo_lease import RepoLeaseTimeoutError
from app.modules.versioning.infrastructure.github_vault import (
    PURPOSE_PAT,
    PURPOSE_SSH_DEPLOY_KEY,
    PURPOSE_WEBHOOK_SECRET,
    EncryptedSecretEnvelope,
    apply_credential_to_connection,
    apply_webhook_secret_to_connection,
    assert_valid_webhook_signature,
    clear_webhook_secret_on_connection,
    compute_ssh_public_key_fingerprint,
    decrypt_connection_credential,
    decrypt_connection_webhook_secret,
    decrypt_github_secret,
    encrypt_github_secret,
    generate_ed25519_deploy_keypair,
    generate_webhook_secret,
    make_credential_hint,
    verify_github_webhook_signature,
)
from app.modules.versioning.infrastructure.models import ServerGitHubConnectionModel
from app.modules.versioning.infrastructure.repo_write_lock import (
    DEFAULT_TTL_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    RepoWriteLock,
)

KEY = bytes.fromhex("a5" * 32)


def _assert_no_secret_leak(error: MCSError, *forbidden: str) -> None:
    rendered = f"{error.message}\n{error.details!r}\n{error!s}\n{error!r}"
    for value in forbidden:
        assert value not in rendered, "secret material leaked in exception"


def _setup_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    monkeypatch.setenv("ONX_MASTER_KEK", KEY.hex())


def _setup_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_kek(monkeypatch)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    return ensure_host_state_layout(settings)


_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="GitHub secret vault requires a POSIX host; Windows = Simple-only",
)


@pytest.mark.no_isolated_db
@_POSIX_ONLY
def test_vault_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_kek(monkeypatch)
    pat = "ghp_secrettoken1234567890"
    env1 = encrypt_github_secret("srv-1", PURPOSE_PAT, pat)
    env2 = encrypt_github_secret("srv-1", PURPOSE_PAT, pat)
    assert env1.wrapped_dek != env2.wrapped_dek
    assert env1.nonce != env2.nonce
    assert env1.ciphertext != env2.ciphertext
    assert decrypt_github_secret("srv-1", PURPOSE_PAT, env1) == pat

    ssh = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    env_ssh = encrypt_github_secret("srv-1", PURPOSE_SSH_DEPLOY_KEY, ssh)
    assert decrypt_github_secret("srv-1", PURPOSE_SSH_DEPLOY_KEY, env_ssh) == ssh

    secret = "a" * 64
    env_wh = encrypt_github_secret("srv-1", PURPOSE_WEBHOOK_SECRET, secret)
    assert decrypt_github_secret("srv-1", PURPOSE_WEBHOOK_SECRET, env_wh) == secret


@pytest.mark.no_isolated_db
@_POSIX_ONLY
def test_vault_roundtrip_with_kek_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONX_MASTER_KEK", raising=False)
    kek_file = tmp_path / "master.kek"
    kek_file.write_text(KEY.hex() + "\n", encoding="utf-8")
    kek_file.chmod(0o600)
    monkeypatch.setenv("ONX_MASTER_KEK_FILE", str(kek_file))
    assert stat.S_IMODE(kek_file.stat().st_mode) == 0o600

    pat = "ghp_kekfiletoken1234567890"
    env_pat = encrypt_github_secret("srv-1", PURPOSE_PAT, pat)
    assert decrypt_github_secret("srv-1", PURPOSE_PAT, env_pat) == pat

    ssh = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "AAAAB3NzaC1lZDI1NTE5AAAAIKekFileSecretBody\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    env_ssh = encrypt_github_secret("srv-1", PURPOSE_SSH_DEPLOY_KEY, ssh)
    assert decrypt_github_secret("srv-1", PURPOSE_SSH_DEPLOY_KEY, env_ssh) == ssh

    webhook = "b" * 64
    env_webhook = encrypt_github_secret("srv-1", PURPOSE_WEBHOOK_SECRET, webhook)
    assert decrypt_github_secret("srv-1", PURPOSE_WEBHOOK_SECRET, env_webhook) == webhook


@pytest.mark.no_isolated_db
@_POSIX_ONLY
def test_vault_antitransplant(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_kek(monkeypatch)
    pat = "ghp_secrettoken1234567890"
    env = encrypt_github_secret("srv-1", PURPOSE_PAT, pat)
    material = (
        pat,
        env.ciphertext.hex(),
        env.nonce.hex(),
        env.wrapped_dek.hex(),
    )

    with pytest.raises(ValidationError) as wrong_server:
        decrypt_github_secret("srv-2", PURPOSE_PAT, env)
    with pytest.raises(ValidationError) as wrong_purpose:
        decrypt_github_secret("srv-1", PURPOSE_WEBHOOK_SECRET, env)
    for exc_info in (wrong_server, wrong_purpose):
        _assert_no_secret_leak(exc_info.value, *material)
        assert set(exc_info.value.details) == {"field", "purpose"}
        assert exc_info.value.details["field"] == "credential"

    # wrong kek version
    bad = EncryptedSecretEnvelope(
        wrapped_dek=env.wrapped_dek,
        kek_version=env.kek_version + 1,
        nonce=env.nonce,
        ciphertext=env.ciphertext,
    )
    with pytest.raises(MasterKekVersionMismatchError) as wrong_kek:
        decrypt_github_secret("srv-1", PURPOSE_PAT, bad)
    _assert_no_secret_leak(wrong_kek.value, *material)
    assert set(wrong_kek.value.details) == {
        "active_kek_version",
        "stored_kek_version",
    }
    assert wrong_kek.value.details["stored_kek_version"] == env.kek_version + 1
    assert wrong_kek.value.details["active_kek_version"] == env.kek_version

    # tampered ciphertext, nonce, and wrapped DEK must all fail closed
    tampered = {
        "ciphertext": EncryptedSecretEnvelope(
            wrapped_dek=env.wrapped_dek,
            kek_version=env.kek_version,
            nonce=env.nonce,
            ciphertext=env.ciphertext[:-1] + bytes([env.ciphertext[-1] ^ 1]),
        ),
        "nonce": EncryptedSecretEnvelope(
            wrapped_dek=env.wrapped_dek,
            kek_version=env.kek_version,
            nonce=bytes([env.nonce[0] ^ 1]) + env.nonce[1:],
            ciphertext=env.ciphertext,
        ),
        "wrapped_dek": EncryptedSecretEnvelope(
            wrapped_dek=env.wrapped_dek[:-1] + bytes([env.wrapped_dek[-1] ^ 1]),
            kek_version=env.kek_version,
            nonce=env.nonce,
            ciphertext=env.ciphertext,
        ),
    }
    for envelope in tampered.values():
        assert envelope != env
        with pytest.raises(ValidationError) as tamper_exc:
            decrypt_github_secret("srv-1", PURPOSE_PAT, envelope)
        _assert_no_secret_leak(tamper_exc.value, *material)
        assert set(tamper_exc.value.details) == {"field", "purpose"}
        assert tamper_exc.value.details["purpose"] == PURPOSE_PAT


@pytest.mark.no_isolated_db
@_POSIX_ONLY
def test_vault_validation_and_keypair() -> None:
    # invalid purpose
    try:
        encrypt_github_secret("srv-1", "bad-purpose", "x")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError")

    # plaintext validation
    with pytest.raises(ValidationError):
        encrypt_github_secret("srv-1", PURPOSE_PAT, "")
    with pytest.raises(ValidationError):
        encrypt_github_secret("srv-1", PURPOSE_PAT, "a\nb")
    with pytest.raises(ValidationError):
        encrypt_github_secret("srv-1", PURPOSE_SSH_DEPLOY_KEY, "no marker")

    kp = generate_ed25519_deploy_keypair("srv-1")
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in kp.private_key_pem
    assert kp.public_key_openssh.startswith("ssh-ed25519 ")
    assert kp.fingerprint_sha256.startswith("SHA256:")
    assert kp.fingerprint_sha256 == compute_ssh_public_key_fingerprint(kp.public_key_openssh)
    assert "REDACTED" in repr(kp)
    assert kp.private_key_pem not in repr(kp)

    # hint
    token = "github_pat_abcdefghij123456"
    hint = make_credential_hint("pat", token=token)
    assert token not in hint
    assert hint.endswith(token[-4:])
    hint2 = make_credential_hint("ssh_deploy_key", public_key=kp.public_key_openssh)
    assert hint2.startswith("SHA256:")

    # webhook signature
    body = b'{"hello":1}'
    secret = "s" * 32
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    expected_digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_webhook_signature(secret, body, sig) is True
    assert_valid_webhook_signature(secret, body, sig)

    wrong_secret = "t" * 32
    wrong_secret_digest = hmac.new(
        wrong_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    negative_cases: list[tuple[str, bytes, str | None]] = [
        (secret, body, "sha256=" + "0" * 64),  # wrong digest
        (secret, b"x", sig),  # tampered body
        (wrong_secret, body, sig),  # wrong secret
        (secret, body, None),  # missing header
        (secret, body, ""),  # empty header
        (secret, body, "sha1=" + expected_digest),  # wrong prefix
        (secret, body, "SHA256=" + expected_digest),  # wrong-case prefix
        (secret, body, expected_digest),  # missing prefix
        (secret, body, "sha256=" + expected_digest[:-1]),  # short digest
        (secret, body, "sha256=" + expected_digest + "00"),  # long digest
        (secret, body, "sha256=" + "z" * 64),  # non-hex digest
    ]
    failures: list[tuple[str | None, WebhookSignatureError]] = []
    for case_secret, case_body, case_header in negative_cases:
        with pytest.raises(WebhookSignatureError) as exc_info:
            assert_valid_webhook_signature(case_secret, case_body, case_header)
        failures.append((case_header, exc_info.value))
        assert (
            verify_github_webhook_signature(case_secret, case_body, case_header)
            is False
        )
    assert verify_github_webhook_signature(secret, "notbytes", sig) is False  # type: ignore[arg-type]

    for case_header, err in failures:
        assert err.code == "GITHUB_WEBHOOK_SIGNATURE_INVALID"
        assert err.http_status == 401
        assert err.details == {}
        assert "secret" not in err.details
        assert "digest" not in err.details
        _assert_no_secret_leak(
            err,
            secret,
            wrong_secret,
            expected_digest,
            wrong_secret_digest,
            "0" * 64,
            "sha256=",
        )
        if isinstance(case_header, str) and case_header:
            _assert_no_secret_leak(err, case_header)

    # webhook secret generation
    ws = generate_webhook_secret(32)
    assert len(ws) == 64
    with pytest.raises(ValidationError):
        generate_webhook_secret(16)


@pytest.mark.no_isolated_db
@_POSIX_ONLY
def test_vault_orm_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_kek(monkeypatch)
    db_file = tmp_path / "vault-orm.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            ServerModel(id="srv-1", name="srv-1", minecraft_version="1.21", server_type="paper")
        )
        session.add(
            ServerModel(id="srv-2", name="srv-2", minecraft_version="1.21", server_type="paper")
        )
        session.commit()

    with factory() as session:
        conn = ServerGitHubConnectionModel(
            id="conn-1",
            server_id="srv-1",
            remote_url="https://github.com/o/r",
            auth_method="pat",
            wrapped_credential_dek=b"\x00" * 60,
            kek_version=1,
            credential_nonce=b"\x00" * 12,
            credential_ciphertext=b"\x00" * 16,
        )
        apply_credential_to_connection(
            conn, server_id="srv-1", auth_method="pat", secret="ghp_abc1234567890"
        )
        session.add(conn)
        session.commit()
        creds = decrypt_connection_credential(conn)
        assert creds.auth_method == "pat"
        assert creds.token == "ghp_abc1234567890"
        assert "ghp_abc" not in repr(creds)

        # webhook
        apply_webhook_secret_to_connection(conn, server_id="srv-1", webhook_secret="w" * 64)
        session.commit()
        assert decrypt_connection_webhook_secret(conn) == "w" * 64
        clear_webhook_secret_on_connection(conn)
        session.commit()
        assert decrypt_connection_webhook_secret(conn) is None

        # SSH deploy key ORM helper round-trip
        keypair = generate_ed25519_deploy_keypair("srv-2")
        ssh_conn = ServerGitHubConnectionModel(
            id="conn-ssh",
            server_id="srv-2",
            remote_url="ssh://git@github.com/o/r",
            auth_method="ssh_deploy_key",
            wrapped_credential_dek=b"\x00" * 60,
            kek_version=1,
            credential_nonce=b"\x00" * 12,
            credential_ciphertext=b"\x00" * 16,
        )
        apply_credential_to_connection(
            ssh_conn,
            server_id="srv-2",
            auth_method="ssh_deploy_key",
            secret=keypair.private_key_pem,
            deploy_public_key=keypair.public_key_openssh,
        )
        session.add(ssh_conn)
        session.commit()
        ssh_creds = decrypt_connection_credential(ssh_conn)
        assert ssh_creds.auth_method == "ssh_deploy_key"
        assert ssh_creds.ssh_private_key == keypair.private_key_pem
        assert ssh_conn.deploy_public_key == keypair.public_key_openssh
        assert ssh_conn.credential_hint == keypair.fingerprint_sha256
        assert "PRIVATE KEY" not in repr(ssh_creds)
    engine.dispose()


@pytest.fixture
def lock_db(tmp_path: Path):
    db_file = tmp_path / "lock.db"
    from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus

    db_url = f"sqlite+aiosqlite:///{db_file}"
    res = DatabaseReconciler(db_url=db_url).reconcile(auto_upgrade=True)
    assert res.status == ReconcileStatus.RECONCILED
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    yield db_file, engine, factory, async_factory, async_engine
    engine.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_repo_write_lock_async(lock_db) -> None:
    db_file, engine, sync_factory, async_factory, async_engine = lock_db
    lock = RepoWriteLock(
        session_factory=async_factory,
        sync_session_factory=sync_factory,
        ttl_seconds=1.0,
        heartbeat_interval_seconds=0.2,
        wait_timeout_seconds=1.0,
    )
    assert HEARTBEAT_INTERVAL_SECONDS == 10.0
    assert DEFAULT_TTL_SECONDS == 30.0

    with pytest.raises(ValidationError):
        async with lock.acquire("srv-1", operation="nope"):
            pass

    tokens = []
    async with lock.acquire("srv-1", operation="fetch", holder_id="h1") as lease:
        assert lease.operation == "fetch"
        assert lease.server_id == "srv-1"
        tokens.append(lease.fencing_token)
        await lease.assert_valid()

    async with lock.acquire("srv-1", operation="push", holder_id="h2") as lease2:
        tokens.append(lease2.fencing_token)
    assert tokens[1] == tokens[0] + 1

    # contested fail_fast and wait_timeout expiry
    async with lock.acquire("srv-1", operation="gc", holder_id="holder") as held:
        with pytest.raises(RepoLeaseTimeoutError):
            async with lock.acquire("srv-1", operation="fetch", fail_fast=True):
                pass
        started = time.monotonic()
        with pytest.raises(RepoLeaseTimeoutError) as async_timeout:
            async with lock.acquire("srv-1", operation="push", wait_timeout=0.2):
                pass
        elapsed = time.monotonic() - started
        await held.assert_valid()
    assert async_timeout.value.http_status == 409
    assert isinstance(async_timeout.value, ConflictError)
    assert elapsed >= 0.15

    # stale token detection
    async with lock.acquire("srv-1", operation="fetch", holder_id="a") as lease_a:
        token_a = lease_a.fencing_token
    # hijack
    async with lock.acquire("srv-1", operation="fetch", holder_id="b"):
        pass
    # Now token_a is stale: every fencing check must fail closed.
    with pytest.raises(FencingTokenMismatchError):
        await lock.assert_fencing_token("srv-1", token_a)
    with pytest.raises(FencingTokenMismatchError):
        lock.assert_fencing_token_sync("srv-1", token_a)
    with pytest.raises(FencingTokenMismatchError):
        await lease_a.assert_valid()
    with pytest.raises(FencingTokenMismatchError):
        lease_a.assert_valid_sync()
    lock.close()
    await async_engine.dispose()
    engine.dispose()


@pytest.mark.no_isolated_db
def test_repo_write_lock_sync_and_heartbeat(tmp_path: Path) -> None:
    db_file = tmp_path / "lock2.db"
    from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus

    db_url = f"sqlite+aiosqlite:///{db_file}"
    res = DatabaseReconciler(db_url=db_url).reconcile(auto_upgrade=True)
    assert res.status == ReconcileStatus.RECONCILED
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False, "timeout": 30.0}
    )
    sync_factory = sessionmaker(bind=engine, expire_on_commit=False)
    lock = RepoWriteLock(
        sync_session_factory=sync_factory,
        ttl_seconds=1.0,
        heartbeat_interval_seconds=0.2,
        wait_timeout_seconds=1.0,
    )

    def _expires_at() -> datetime:
        with engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT expires_at FROM server_repo_leases "
                    "WHERE server_id = :sid"
                ),
                {"sid": "srv-1"},
            ).scalar_one()
        return datetime.fromisoformat(str(value))

    sync_tokens: list[int] = []
    for operation in ("fetch", "push", "gc"):
        with lock.acquire_sync("srv-1", operation=operation) as lease:
            assert lease.operation == operation
            sync_tokens.append(lease.fencing_token)
            lease.assert_valid_sync()
            lease.fencing_verifier()()
    assert sync_tokens[0] >= 1
    assert sync_tokens[1] == sync_tokens[0] + 1
    assert sync_tokens[2] == sync_tokens[1] + 1
    assert len(set(sync_tokens)) == 3

    # contested fail_fast and wait_timeout expiry
    with lock.acquire_sync("srv-1", operation="fetch", holder_id="h"):
        with (
            pytest.raises(RepoLeaseTimeoutError),
            lock.acquire_sync("srv-1", operation="push", fail_fast=True),
        ):
            pass
        started = time.monotonic()
        with (
            pytest.raises(RepoLeaseTimeoutError) as timeout_exc,
            lock.acquire_sync("srv-1", operation="push", wait_timeout=0.25),
        ):
            pass
        elapsed = time.monotonic() - started
    assert timeout_exc.value.code == "REPO_LEASE_TIMEOUT"
    assert timeout_exc.value.http_status == 409
    assert isinstance(timeout_exc.value, ConflictError)
    assert elapsed >= 0.2

    # The heartbeat must advance the DB expires_at over multiple intervals.
    with lock.acquire_sync("srv-1", operation="gc", ttl_seconds=1.0) as lease:
        time.sleep(0.25)
        first_expiry = _expires_at()
        lease.assert_valid_sync()
        time.sleep(0.6)
        second_expiry = _expires_at()
        lease.assert_valid_sync()
    assert second_expiry > first_expiry
    lock.close()
    engine.dispose()
