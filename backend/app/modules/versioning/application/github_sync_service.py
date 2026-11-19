"""P5-2 GitHub sync service engine.

Normative contract: ``SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02`` P5, D-A, D-J,
D-K, OD-v8.4-7, OD-v8.6-6, OD-v8.6-7.

The engine keeps GitHub credentials out of ``.git/config``, the isolated
``gitconfig``, command lines, logs, DTOs, domain events, and database error
columns. Every repository mutation runs under :class:`RepoWriteLock` and every
Git subprocess runs in a worker thread through :class:`GitRunner`. Fetch is the
primary sync path; webhook handlers only enqueue durable operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives import serialization
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.event_bus import EventBus
from app.core.exceptions import (
    ConflictError,
    DirtyWorktreeError,
    GitCommandError,
    GitHubAuthFailedError,
    GitHubNotConnectedError,
    GitHubPushRejectedError,
    GitRepositoryStateError,
    GitTimeoutError,
    MCSError,
    NonFastForwardMainError,
    NotFoundError,
    ServerModeVersioningDisabledError,
    ValidationError,
    WebhookSignatureError,
)
from app.core.host_state import HostStateLayout, validate_server_segment
from app.core.persistence.db import database
from app.modules.operations.application.services.operation_service import (
    OperationService,
)
from app.modules.operations.domain.enums import OperationType
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
from app.modules.versioning.domain.entities import ServerCommit
from app.modules.versioning.domain.events import (
    GitHubConnectedEvent,
    GitHubCredentialsRotatedEvent,
    GitHubDisconnectedEvent,
    GitHubPushedEvent,
    GitHubSyncedEvent,
    GitHubWebhookReceivedEvent,
)
from app.modules.versioning.domain.value_objects import CommitManifest
from app.modules.versioning.infrastructure.git_branches import (
    GitBranchService,
    _validate_branch_path_name,
)
from app.modules.versioning.infrastructure.git_repository import (
    MAIN_BRANCH,
    validate_server_root,
)
from app.modules.versioning.infrastructure.git_runner import (
    GitCredentials,
    GitRunner,
    redact_secrets,
    validate_remote_url,
)
from app.modules.versioning.infrastructure.github_sync_repository import (
    SQLGitHubSyncRepository,
)
from app.modules.versioning.infrastructure.github_vault import (
    ALLOWED_AUTH_METHODS,
    AUTH_METHOD_PAT,
    AUTH_METHOD_SSH_DEPLOY_KEY,
    apply_credential_to_connection,
    apply_webhook_secret_to_connection,
    assert_valid_webhook_signature,
    clear_webhook_secret_on_connection,
    compute_ssh_public_key_fingerprint,
    decrypt_connection_credential,
    decrypt_connection_webhook_secret,
    generate_ed25519_deploy_keypair,
    generate_webhook_secret,
)
from app.modules.versioning.infrastructure.models import (
    GitHubWebhookDeliveryModel,
    ServerBranchModel,
    ServerCommitModel,
    ServerGitHubConnectionModel,
)
from app.modules.versioning.infrastructure.repo_write_lock import RepoWriteLock
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.vault_crypto import MasterKek

logger = logging.getLogger(__name__)

REMOTE_NAME = "origin"
REMOTE_FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"
MAX_WEBHOOK_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_DELIVERY_ID_LENGTH = 128
MAX_EVENT_TYPE_LENGTH = 64
MAX_WEBHOOK_REF_LENGTH = 256
WEBHOOK_ENQUEUE_EVENTS: frozenset[str] = frozenset({"push", "create", "delete"})
SYNC_STEP_ID = "fetch_sync"
GITHUB_SYNC_OPERATION = OperationType.GITHUB_SYNC.value

# Exact classifier tokens from the locked brief. Matching is case-insensitive.
_AUTH_MARKERS: tuple[str, ...] = (
    "authentication failed",
    "invalid username or token",
    "invalid username or password",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "http basic: access denied",
    "returned error: 401",
    "returned error: 403",
    "write access to repository not granted",
    "key is read-only",
    "deploy key does not have write access",
    "permission to ",
    "permission denied (publickey)",
    "bad credentials",
    "token has expired",
    "resource not accessible by personal access token",
    "repository not found",
)
_INSUFFICIENT_SCOPE_MARKERS: tuple[str, ...] = (
    "write access to repository not granted",
    "key is read-only",
    "deploy key does not have write access",
    "permission to ",
    "resource not accessible by personal access token",
)
_SSH_KEY_MARKERS: tuple[str, ...] = (
    "permission denied (publickey)",
    "publickey",
)
_PUSH_REJECTION_MARKERS: tuple[str, ...] = (
    "[rejected]",
    "remote rejected",
    "non-fast-forward",
    "fetch first",
    "protected branch",
    "pre-receive hook declined",
    "gh001",
    "large files detected",
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_OID_RE = re.compile(r"\A[0-9a-f]{40,64}\Z")

# ----------------------------------------------------------------------
# Immutable, secret-safe DTOs
# ----------------------------------------------------------------------


def _safe_dataclass_repr(instance: object, redacted: frozenset[str]) -> str:
    parts: list[str] = []
    for field_info in fields(instance):  # type: ignore[arg-type]
        value = getattr(instance, field_info.name)
        if field_info.name in redacted and value is not None:
            value = "***REDACTED***"
        parts.append(f"{field_info.name}={value!r}")
    return f"{type(instance).__name__}({', '.join(parts)})"


@dataclass(frozen=True)
class GeneratedDeployKeyResult:
    """One freshly generated Ed25519 deploy keypair.

    ``private_key_pem`` is returned exactly once so the operator can install
    the key on GitHub; it is redacted from ``repr`` and ``str``.
    """

    server_id: str
    public_key_openssh: str
    private_key_pem: str
    fingerprint_sha256: str

    def __repr__(self) -> str:
        return _safe_dataclass_repr(self, frozenset({"private_key_pem"}))

    def __str__(self) -> str:
        return self.__repr__()


BranchSyncStatus = Literal[
    "synced", "ahead", "behind", "diverged", "local_only", "remote_only"
]
_BRANCH_SYNC_STATUSES: frozenset[str] = frozenset(
    {"synced", "ahead", "behind", "diverged", "local_only", "remote_only"}
)


@dataclass(frozen=True)
class GitHubBranchSyncState:
    """1:1 telemetry for one branch name present locally and/or remotely."""

    branch: str
    status: BranchSyncStatus
    local_sha: str | None = None
    remote_sha: str | None = None
    ahead_count: int = 0
    behind_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "status": self.status,
            "local_sha": self.local_sha,
            "remote_sha": self.remote_sha,
            "ahead_count": self.ahead_count,
            "behind_count": self.behind_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GitHubBranchSyncState:
        raw_status = str(data.get("status", "local_only"))
        status: BranchSyncStatus = (
            raw_status if raw_status in _BRANCH_SYNC_STATUSES else "local_only"
        )  # type: ignore[assignment]
        local_sha = data.get("local_sha")
        remote_sha = data.get("remote_sha")
        return cls(
            branch=str(data.get("branch", ""))[:128],
            status=status,
            local_sha=str(local_sha)[:64] if local_sha else None,
            remote_sha=str(remote_sha)[:64] if remote_sha else None,
            ahead_count=_safe_int(data.get("ahead_count")),
            behind_count=_safe_int(data.get("behind_count")),
        )


def _safe_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


@dataclass(frozen=True)
class GitHubConnectionStatus:
    """Secret-free connection snapshot returned to API callers."""

    server_id: str
    connected: bool
    remote_url: str | None = None
    auth_method: str | None = None
    credential_hint: str | None = None
    deploy_public_key: str | None = None
    webhook_enabled: bool = False
    sync_status: str = "disconnected"
    needs_reauth: bool = False
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_fetch_at: datetime | None = None
    last_push_at: datetime | None = None
    remote_default_branch: str | None = None
    remote_head_sha: str | None = None
    branches: tuple[GitHubBranchSyncState, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None
    generated_webhook_secret: str | None = None

    def __repr__(self) -> str:
        return _safe_dataclass_repr(self, frozenset({"generated_webhook_secret"}))

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class GitHubDisconnectResult:
    server_id: str
    disconnected: bool
    remote_url: str
    local_history_preserved: bool = True
    purged_deliveries: int = 0


@dataclass(frozen=True)
class GitHubSyncResult:
    server_id: str
    sync_status: str
    trigger: str
    main_fast_forwarded: bool
    previous_main_sha: str | None
    main_sha: str | None
    remote_default_branch: str | None
    remote_head_sha: str | None
    branches: tuple[GitHubBranchSyncState, ...]
    fetched_at: datetime


@dataclass(frozen=True)
class GitHubPushResult:
    server_id: str
    branch_name: str
    commit_sha: str
    remote_url: str
    sync_status: str
    branches: tuple[GitHubBranchSyncState, ...]
    pushed_at: datetime


WebhookIngestStatus = Literal["queued", "deduplicated", "ignored"]


@dataclass(frozen=True)
class GitHubWebhookIngestResult:
    server_id: str
    delivery_id: str
    event_type: str
    status: WebhookIngestStatus
    deduplicated: bool = False
    redelivered: bool = False
    redelivery_count: int = 0
    operation_id: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True)
class GitHubWebhookDeliveryRecord:
    """Secret-free delivery ledger row (deliberately omits ``raw_payload``)."""

    id: str
    server_id: str
    delivery_id: str
    event_type: str
    ref: str | None
    before_sha: str | None
    after_sha: str | None
    payload_sha256: str
    signature_valid: bool
    status: str
    operation_id: str | None
    error_message: str | None
    redelivery_count: int
    received_at: datetime
    processed_at: datetime | None


# ----------------------------------------------------------------------
# Pure classifiers and Git output helpers
# ----------------------------------------------------------------------


def _matches(lowered: str, markers: Iterable[str]) -> bool:
    return any(marker in lowered for marker in markers)


def classify_git_remote_error(
    exc: GitCommandError | GitTimeoutError,
    *,
    auth_method: str,
    branch: str | None = None,
    local_sha: str = "",
    remote_sha: str = "",
    extra_secrets: Iterable[str] = (),
) -> MCSError:
    """Map a sanitized Git failure to the correct public MCS error.

    Authentication and authorization failures always fail closed as
    :class:`GitHubAuthFailedError` with ``needs_reauth=True``. Non-fast-forward
    ``main`` updates are rejected with :class:`NonFastForwardMainError`; other
    push rejections use :class:`GitHubPushRejectedError`. Timeouts and other
    Git/network failures are returned unchanged so retry telemetry survives.
    """
    if isinstance(exc, GitTimeoutError):
        return exc

    stderr = redact_secrets(getattr(exc, "stderr", "") or str(exc), extra_secrets)
    lowered = stderr.lower()

    if _matches(lowered, _AUTH_MARKERS) or (
        "publickey" in lowered and "denied" in lowered
    ):
        reason = "auth_rejected"
        if (
            "permission denied (publickey)" in lowered
            or ("publickey" in lowered and "denied" in lowered)
        ):
            reason = "ssh_key_rejected"
        elif _matches(lowered, _INSUFFICIENT_SCOPE_MARKERS):
            reason = "insufficient_scope"
        elif "repository not found" in lowered:
            reason = "repository_not_found_or_unauthorized"
        return GitHubAuthFailedError(
            needs_reauth=True,
            auth_method=auth_method,
            reason=reason,
        )

    if branch == MAIN_BRANCH and (
        (
            "[rejected]" in lowered
            and _matches(
                lowered,
                ("non-fast-forward", "fetch first", "cannot lock ref"),
            )
        )
        or "updates were rejected because the tip of your current branch is behind"
        in lowered
        or "updates were rejected because the remote contains work" in lowered
    ):
        return NonFastForwardMainError(
            local_sha=local_sha,
            remote_sha=remote_sha,
        )

    if branch is not None and _matches(lowered, _PUSH_REJECTION_MARKERS):
        reason = "push_rejected"
        if "protected branch" in lowered:
            reason = "protected_branch"
        elif "gh001" in lowered or "large files detected" in lowered:
            reason = "large_file"
        elif "pre-receive hook declined" in lowered:
            reason = "pre_receive_hook_declined"
        elif "non-fast-forward" in lowered or "fetch first" in lowered:
            reason = "non_fast_forward"
        return GitHubPushRejectedError(branch=branch, reason=reason)

    return exc


def _is_ancestor(runner: GitRunner, ancestor_sha: str, descendant_sha: str) -> bool:
    result = runner.run(
        "merge-base",
        "--is-ancestor",
        ancestor_sha,
        descendant_sha,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitRepositoryStateError(
        "Unable to determine Git commit ancestry",
        details={"stderr": result.stderr[:500]},
    )


def _require_object_id(value: str, kind: str) -> str:
    oid = value.strip()
    if not _OID_RE.match(oid):
        raise GitRepositoryStateError(
            f"Git returned an invalid {kind} object id",
            details={"value": oid[:128]},
        )
    return oid


def _resolve_ref(runner: GitRunner, ref: str) -> str | None:
    result = runner.run(
        "rev-parse",
        "--verify",
        "--quiet",
        f"{ref}^{{commit}}",
        check=False,
    )
    if result.returncode == 0:
        return _require_object_id(result.stdout, "commit")
    if result.returncode == 1:
        return None
    raise GitRepositoryStateError(
        "Unable to resolve Git reference",
        details={"ref": ref[:256], "stderr": result.stderr[:500]},
    )


def _parse_ref_lines(stdout: str, prefix: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line:
            continue
        ref, separator, oid = line.partition("\t")
        if not separator or not ref.startswith(prefix):
            raise GitRepositoryStateError(
                "Git returned an unexpected reference record",
                details={"line": line[:256]},
            )
        name = ref[len(prefix) :]
        if not name:
            continue
        refs[name] = _require_object_id(oid, "commit")
    return refs


def _compute_branch_sync(runner: GitRunner) -> tuple[GitHubBranchSyncState, ...]:
    """Compute 1:1 local/remote tracking state for every branch name."""
    local = _parse_ref_lines(
        runner.run(
            "for-each-ref",
            "--format=%(refname)%09%(objectname)",
            "refs/heads",
        ).stdout,
        "refs/heads/",
    )
    remote = _parse_ref_lines(
        runner.run(
            "for-each-ref",
            "--format=%(refname)%09%(objectname)",
            f"refs/remotes/{REMOTE_NAME}",
        ).stdout,
        f"refs/remotes/{REMOTE_NAME}/",
    )
    remote.pop("HEAD", None)

    states: list[GitHubBranchSyncState] = []
    for name in sorted(set(local) | set(remote), key=lambda item: (item != MAIN_BRANCH, item)):
        local_sha = local.get(name)
        remote_sha = remote.get(name)
        if local_sha is None:
            states.append(
                GitHubBranchSyncState(
                    branch=name,
                    status="remote_only",
                    remote_sha=remote_sha,
                )
            )
            continue
        if remote_sha is None:
            states.append(
                GitHubBranchSyncState(
                    branch=name,
                    status="local_only",
                    local_sha=local_sha,
                )
            )
            continue
        if local_sha == remote_sha:
            states.append(
                GitHubBranchSyncState(
                    branch=name,
                    status="synced",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            )
            continue

        counts = runner.run(
            "rev-list",
            "--left-right",
            "--count",
            f"{local_sha}...{remote_sha}",
        ).stdout.strip()
        parts = counts.split()
        if len(parts) != 2:
            raise GitRepositoryStateError(
                "Git returned an unexpected ahead/behind count",
                details={"branch": name[:128]},
            )
        ahead, behind = _safe_int(parts[0]), _safe_int(parts[1])
        if ahead > 0 and behind == 0:
            status: BranchSyncStatus = "ahead"
        elif ahead == 0 and behind > 0:
            status = "behind"
        elif ahead > 0 and behind > 0:
            status = "diverged"
        else:
            status = "synced"
        states.append(
            GitHubBranchSyncState(
                branch=name,
                status=status,
                local_sha=local_sha,
                remote_sha=remote_sha,
                ahead_count=ahead,
                behind_count=behind,
            )
        )
    return tuple(states)


def _summarize_sync_status(
    branches: Iterable[GitHubBranchSyncState], *, main_conflict: bool = False
) -> str:
    if main_conflict:
        return "conflict"
    states = {branch.status for branch in branches}
    if "diverged" in states:
        return "diverged"
    if states & {"behind", "remote_only"}:
        return "behind"
    if states & {"ahead", "local_only"}:
        return "ahead"
    return "synced"


def _assert_no_plain_jar_blobs(runner: GitRunner, branch_name: str) -> None:
    """Reject any plain ``.jar`` blob in the branch tip or unpushed history."""
    offending: set[str] = set()

    tip = runner.run(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        f"refs/heads/{branch_name}",
    )
    for record in tip.stdout.split("\x00"):
        if not record:
            continue
        meta, separator, path = record.partition("\t")
        if not separator:
            continue
        parts = meta.split()
        if len(parts) < 3:
            continue
        if parts[1] == "blob" and path.lower().endswith(".jar"):
            offending.add(path)

    unpushed = runner.run(
        "rev-list",
        "--objects",
        f"refs/heads/{branch_name}",
        "--not",
        f"--remotes={REMOTE_NAME}",
    )
    for line in unpushed.stdout.splitlines():
        if not line:
            continue
        _oid, separator, path = line.partition(" ")
        if separator and path.lower().endswith(".jar"):
            offending.add(path)

    if offending:
        ordered = sorted(offending)
        raise GitHubPushRejectedError(
            "Plain .jar blobs cannot be pushed to GitHub; "
            "store jars in CAS and track them via onx-jars.lock.json",
            branch=branch_name,
            reason="plain_jar_blob_forbidden",
            details={"forbidden_paths": ordered[:10]},
        )


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class _RemoteContext:
    """Immutable snapshot of a connected repository plus transient credentials."""

    segment: str
    remote_url: str
    auth_method: str
    credentials: GitCredentials
    remote_default_branch: str | None
    remote_head_sha: str | None


def _assert_no_overlap(server_root: Path, repo_dir: Path) -> None:
    root_norm = os.path.normpath(os.path.abspath(server_root))
    repo_norm = os.path.normpath(os.path.abspath(repo_dir))
    try:
        common = os.path.commonpath([root_norm, repo_norm])
    except ValueError as exc:
        raise GitRepositoryStateError(
            "Repository path is not comparable with the server root",
            details={"path": str(repo_dir)[:256], "root": str(server_root)[:256]},
        ) from exc
    if common in (root_norm, repo_norm):
        raise GitRepositoryStateError(
            "Repository storage and server root must not overlap",
            details={"path": str(repo_dir)[:256], "root": str(server_root)[:256]},
        )


class GitHubSyncService:
    """Credential-free GitHub remote management and fetch-first sync engine."""

    def __init__(
        self,
        layout: HostStateLayout,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
        repo_write_lock: RepoWriteLock | None = None,
        branch_service: GitBranchService | None = None,
        operation_service: OperationService | None = None,
        event_bus: EventBus | None = None,
        git_runner_factory: Callable[[Path, Path], GitRunner] | None = None,
        git_executable: str = "git",
        git_timeout: float = 120.0,
        webhook_sync_dispatcher: (
            Callable[[str, str, str], Awaitable[None] | None] | None
        ) = None,
        kek: MasterKek | None = None,
    ) -> None:
        self._layout = layout
        self._session_factory_override = session_factory
        self._sync_session_factory = sync_session_factory
        self._repo_write_lock = repo_write_lock
        self._branch_service = branch_service or GitBranchService(
            layout,
            git_executable=git_executable,
            timeout=git_timeout,
        )
        self._operation_service = operation_service
        self._event_bus = event_bus
        self._git_runner_factory = git_runner_factory
        self._git_executable = git_executable
        self._git_timeout = git_timeout
        self._webhook_sync_dispatcher = webhook_sync_dispatcher
        self._kek = kek

    # ------------------------------------------------------------------
    # Session, lock, and guard plumbing
    # ------------------------------------------------------------------

    def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory_override is not None:
            return self._session_factory_override
        return database.session_factory

    @asynccontextmanager
    async def _read_session(
        self, session: AsyncSession | None = None
    ) -> AsyncIterator[AsyncSession]:
        if session is not None:
            yield session
            return
        async with self._session_factory()() as own_session:
            yield own_session

    @asynccontextmanager
    async def _write_session(
        self, session: AsyncSession | None = None
    ) -> AsyncIterator[AsyncSession]:
        if session is not None:
            yield session
            return
        own_session = self._session_factory()()
        try:
            yield own_session
            await own_session.commit()
        except BaseException:
            await own_session.rollback()
            raise
        finally:
            await own_session.close()

    def _get_repo_write_lock(self) -> RepoWriteLock:
        if self._repo_write_lock is None:
            self._repo_write_lock = RepoWriteLock(
                session_factory=self._session_factory(),
                sync_session_factory=self._sync_session_factory,
                layout=self._layout,
            )
        return self._repo_write_lock

    def _get_operation_service(self) -> OperationService:
        if self._operation_service is None:
            self._operation_service = OperationService(event_bus=self._event_bus)
        return self._operation_service

    @staticmethod
    def _assert_posix() -> None:
        if os.name != "posix":
            raise ServerModeVersioningDisabledError()

    async def _guard(self, server_id: str, session: AsyncSession | None) -> str:
        """POSIX + segment + Advanced-mode guard for every public method."""
        self._assert_posix()
        segment = validate_server_segment(server_id)
        async with self._read_session(session) as active_session:
            await ensure_versioning_allowed(segment, session=active_session)
        return segment

    async def _load_remote_context(
        self, server_id: str, session: AsyncSession | None
    ) -> _RemoteContext:
        self._assert_posix()
        segment = validate_server_segment(server_id)
        remote_url = ""
        auth_method = ""
        default_branch: str | None = None
        head_sha: str | None = None
        credentials: GitCredentials | None = None
        decrypt_failed = False

        async with self._read_session(session) as active_session:
            await ensure_versioning_allowed(segment, session=active_session)
            connection = await SQLGitHubSyncRepository(
                active_session
            ).get_connection(segment)
            if connection is None:
                raise GitHubNotConnectedError(segment)
            remote_url = validate_remote_url(connection.remote_url)
            auth_method = connection.auth_method
            default_branch = connection.remote_default_branch
            head_sha = connection.remote_head_sha
            try:
                credentials = decrypt_connection_credential(
                    connection, kek=self._kek
                )
            except Exception:  # noqa: BLE001 - fail closed without leaking material
                decrypt_failed = True

        if decrypt_failed or credentials is None:
            await self._update_connection_row(
                segment,
                values={
                    "sync_status": "auth_failed",
                    "last_error_code": "GITHUB_AUTH_FAILED",
                    "last_error_message": (
                        "Stored GitHub credential could not be decrypted; "
                        "reconnect or rotate it"
                    ),
                },
            )
            raise GitHubAuthFailedError(auth_method=auth_method)

        return _RemoteContext(
            segment=segment,
            remote_url=remote_url,
            auth_method=auth_method,
            credentials=credentials,
            remote_default_branch=default_branch,
            remote_head_sha=head_sha,
        )

    async def _resolve_server_root(
        self,
        segment: str,
        server_root: str | os.PathLike[str] | None,
        session: AsyncSession | None,
    ) -> Path:
        if server_root is not None:
            return validate_server_root(server_root)

        async with self._read_session(session) as active_session:
            server = await active_session.get(ServerModel, segment)
        if server is None:
            raise NotFoundError(f"Server '{segment}' not found")
        root_path = getattr(server, "root_path", None)
        if not root_path:
            raise GitRepositoryStateError("Server root path is not configured")
        working_directory = getattr(server, "working_directory", None) or "."
        return validate_server_root(
            os.path.abspath(os.path.join(root_path, working_directory))
        )

    def _open_repo_runner(self, segment: str, server_root: Path) -> GitRunner:
        repo_dir = self._layout.repo_dir(segment)
        _assert_no_overlap(server_root, repo_dir)
        repo_git = repo_dir / "repo.git"
        if repo_git.is_symlink() or not repo_git.is_dir():
            raise GitRepositoryStateError(
                "Native Git repository does not exist for this server",
                details={"path": str(repo_git)[:256]},
            )
        if repo_dir.is_symlink() or not repo_dir.is_dir():
            raise GitRepositoryStateError(
                "Repository storage directory is invalid",
                details={"path": str(repo_dir)[:256]},
            )

        if self._git_runner_factory is not None:
            runner = self._git_runner_factory(repo_git, repo_dir / "gitconfig")
        else:
            runner = GitRunner(
                repo_path=repo_git,
                config_path=repo_dir / "gitconfig",
                git_executable=self._git_executable,
                timeout=self._git_timeout,
            )

        bare = runner.run("rev-parse", "--is-bare-repository", check=False)
        if bare.returncode != 0 or bare.stdout.strip() != "true":
            raise GitRepositoryStateError(
                "Repository is not a bare Git repository",
                details={"path": str(repo_git)[:256]},
            )
        if _resolve_ref(runner, f"refs/heads/{MAIN_BRANCH}") is None:
            raise GitRepositoryStateError(
                "Repository has no main branch",
                details={"path": str(repo_git)[:256]},
            )
        return runner

    # ------------------------------------------------------------------
    # Credential-free remote configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_remote_and_auth(remote_url: str, auth_method: str) -> str:
        clean_url = validate_remote_url(remote_url)
        if not isinstance(auth_method, str) or auth_method not in ALLOWED_AUTH_METHODS:
            raise ValidationError(
                "Unsupported GitHub auth method",
                field="auth_method",
                details={"auth_method": str(auth_method)[:32]},
            )
        if auth_method == AUTH_METHOD_PAT and not clean_url.startswith(
            "https://github.com/"
        ):
            raise ValidationError(
                "PAT auth requires an https://github.com/ remote URL",
                field="remote_url",
            )
        if auth_method == AUTH_METHOD_SSH_DEPLOY_KEY and not clean_url.startswith(
            "ssh://git@github.com/"
        ):
            raise ValidationError(
                "Deploy-key auth requires an ssh://git@github.com/ remote URL",
                field="remote_url",
            )
        return clean_url

    @staticmethod
    def _configure_origin_remote(runner: GitRunner, remote_url: str) -> None:
        clean_url = validate_remote_url(remote_url)
        existing = runner.run("remote", "get-url", REMOTE_NAME, check=False)
        if existing.returncode == 0:
            runner.run("remote", "set-url", REMOTE_NAME, clean_url)
        else:
            runner.run("remote", "add", REMOTE_NAME, clean_url)
        runner.run(
            "config",
            "--local",
            f"remote.{REMOTE_NAME}.fetch",
            REMOTE_FETCH_REFSPEC,
        )
        runner.run(
            "config",
            "--local",
            "--unset-all",
            f"remote.{REMOTE_NAME}.pushurl",
            check=False,
        )
        runner.run("config", "--local", "core.filemode", "true")

    @staticmethod
    def _remove_origin_remote(runner: GitRunner) -> None:
        runner.run("remote", "remove", REMOTE_NAME, check=False)

    @staticmethod
    def _parse_ls_remote(stdout: str) -> tuple[str | None, str | None]:
        default_branch: str | None = None
        head_sha: str | None = None
        for line in stdout.splitlines():
            if not line:
                continue
            if line.startswith("ref: "):
                value = line[len("ref: ") :]
                refname, separator, target = value.partition("\t")
                if separator and target == "HEAD" and refname.startswith("refs/heads/"):
                    default_branch = refname[len("refs/heads/") :][:64]
                continue
            oid, separator, target = line.partition("\t")
            if separator and target == "HEAD" and _OID_RE.match(oid.strip()):
                head_sha = oid.strip()
        return default_branch, head_sha

    # ------------------------------------------------------------------
    # SSH key derivation / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_deploy_public_key(
        server_id: str,
        private_key_pem: str,
        deploy_public_key: str | None,
        *,
        comment: str | None = None,
    ) -> str:
        private_bytes = private_key_pem.encode("utf-8")
        private_key: Any = None
        try:
            private_key = serialization.load_ssh_private_key(
                private_bytes, password=None
            )
        except Exception:  # noqa: BLE001 - try the PEM loader next
            try:
                private_key = serialization.load_pem_private_key(
                    private_bytes, password=None
                )
            except Exception as exc:
                raise ValidationError(
                    "SSH deploy key is malformed",
                    field="credential_secret",
                ) from exc

        derived_blob = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ).decode("ascii")
        key_comment = comment or f"onx-manager-{server_id}"
        derived_openssh = f"{derived_blob} {key_comment}"

        if deploy_public_key is None:
            return derived_openssh
        compute_ssh_public_key_fingerprint(deploy_public_key)
        provided_parts = deploy_public_key.strip().split()
        derived_parts = derived_openssh.split()
        if provided_parts[:2] != derived_parts[:2]:
            raise ValidationError(
                "SSH deploy public key does not match the private key",
                field="deploy_public_key",
            )
        return deploy_public_key

    # ------------------------------------------------------------------
    # Status / persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_branch_states(value: Any) -> tuple[GitHubBranchSyncState, ...]:
        if not isinstance(value, list):
            return ()
        states: list[GitHubBranchSyncState] = []
        for item in value:
            if isinstance(item, Mapping):
                states.append(GitHubBranchSyncState.from_dict(item))
        return tuple(states)

    @classmethod
    def _status_from_connection(
        cls,
        connection: ServerGitHubConnectionModel,
        *,
        generated_webhook_secret: str | None = None,
    ) -> GitHubConnectionStatus:
        return GitHubConnectionStatus(
            server_id=connection.server_id,
            connected=True,
            remote_url=connection.remote_url,
            auth_method=connection.auth_method,
            credential_hint=connection.credential_hint,
            deploy_public_key=connection.deploy_public_key,
            webhook_enabled=bool(connection.webhook_enabled),
            sync_status=connection.sync_status or "idle",
            needs_reauth=(
                connection.sync_status == "auth_failed"
                or connection.last_error_code == "GITHUB_AUTH_FAILED"
            ),
            last_error_code=connection.last_error_code,
            last_error_message=connection.last_error_message,
            last_fetch_at=connection.last_fetch_at,
            last_push_at=connection.last_push_at,
            remote_default_branch=connection.remote_default_branch,
            remote_head_sha=connection.remote_head_sha,
            branches=cls._parse_branch_states(connection.branch_sync_json),
            created_at=connection.created_at,
            updated_at=connection.updated_at,
            generated_webhook_secret=generated_webhook_secret,
        )

    async def _update_connection_row(
        self,
        segment: str,
        *,
        values: Mapping[str, Any],
        session: AsyncSession | None = None,
    ) -> None:
        async with self._write_session(session) as active_session:
            repo = SQLGitHubSyncRepository(active_session)
            connection = await repo.get_connection(segment)
            if connection is None:
                return
            for key, value in values.items():
                setattr(connection, key, value)
            await repo.save_connection(connection)

    @staticmethod
    def _safe_error_message(error: MCSError) -> str:
        message = getattr(error, "message", "") or str(error) or error.code
        return redact_secrets(str(message))[:512]

    async def _persist_error(
        self,
        segment: str,
        error: MCSError,
        *,
        sync_status: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if sync_status is None:
            if isinstance(error, GitHubAuthFailedError):
                sync_status = "auth_failed"
            elif isinstance(error, NonFastForwardMainError):
                sync_status = "conflict"
            else:
                sync_status = "error"
        values: dict[str, Any] = {
            "sync_status": sync_status,
            "last_error_code": (getattr(error, "code", "") or "GITHUB_SYNC_FAILED")[
                :64
            ],
            "last_error_message": self._safe_error_message(error),
        }
        if extra:
            values.update(extra)
        await self._update_connection_row(segment, values=values)

    async def _persist_sync_state(
        self,
        segment: str,
        *,
        sync_status: str,
        branches: tuple[GitHubBranchSyncState, ...],
        remote_head_sha: str | None,
        fetched_at: datetime,
        error_code: str | None,
        error_message: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "sync_status": sync_status,
            "branch_sync_json": [branch.to_dict() for branch in branches],
            "remote_head_sha": remote_head_sha,
            "last_fetch_at": fetched_at,
            "last_error_code": error_code,
            "last_error_message": error_message,
        }
        await self._update_connection_row(segment, values=values, session=session)

    async def _publish(self, event: Any) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(event)

    async def _invoke_webhook_dispatcher(
        self, segment: str, operation_id: str, delivery_id: str
    ) -> None:
        if self._webhook_sync_dispatcher is None:
            return
        try:
            outcome = self._webhook_sync_dispatcher(
                segment, operation_id, delivery_id
            )
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:  # noqa: BLE001 - the durable operation is already queued
            logger.exception(
                "GitHub webhook sync dispatcher failed for delivery %s",
                delivery_id,
            )

    # ------------------------------------------------------------------
    # main fast-forward ledger projection
    # ------------------------------------------------------------------

    async def _project_main_commit(
        self,
        segment: str,
        commit_sha: str,
        runner: GitRunner,
        *,
        previous_main_sha: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        log_result = await asyncio.to_thread(
            runner.run,
            "log",
            "-1",
            "--format=%s%n%P",
            commit_sha,
        )
        lines = log_result.stdout.splitlines()
        subject = (lines[0].strip() if lines else "") or "GitHub sync"
        parents = (
            lines[1].split() if len(lines) > 1 and lines[1].strip() else []
        )
        parent_ids = [parent for parent in parents if _OID_RE.match(parent)]

        async with self._write_session(session) as active_session:
            commit_repo = SQLVersioningRepository(active_session)
            existing = await active_session.get(ServerCommitModel, commit_sha)
            branch_row = (
                await active_session.execute(
                    select(ServerBranchModel).where(
                        ServerBranchModel.server_id == segment,
                        ServerBranchModel.name == MAIN_BRANCH,
                    )
                )
            ).scalars().first()

            if existing is None:
                server = await active_session.get(ServerModel, segment)
                manifest = CommitManifest(
                    server_type=getattr(server, "server_type", None) or "vanilla",
                    minecraft_version=(
                        getattr(server, "minecraft_version", None) or "1.21.1"
                    ),
                )
                commit = ServerCommit(
                    id=commit_sha,
                    server_id=segment,
                    message=subject[:255],
                    manifest=manifest,
                    branch_id=branch_row.id if branch_row is not None else None,
                    parent_commit_id=parent_ids[0] if parent_ids else None,
                    parent_commit_ids=list(parent_ids),
                    author_id=None,
                    created_at=datetime.now(UTC),
                )
                with suppress(ConflictError):
                    await commit_repo.save_commit(commit)

            if branch_row is not None:
                expected = branch_row.head_commit_id or previous_main_sha
                advanced = await commit_repo.advance_branch_head_optimistic(
                    branch_row.id, commit_sha, expected
                )
                if not advanced:
                    branch_row.head_commit_id = commit_sha
                    branch_row.status = "active"
                    await active_session.flush()

    # ------------------------------------------------------------------
    # Public connection lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _build_credentials(auth_method: str, secret: str) -> GitCredentials:
        if auth_method == AUTH_METHOD_PAT:
            return GitCredentials(auth_method="pat", token=secret)
        return GitCredentials(auth_method="ssh_deploy_key", ssh_private_key=secret)

    @staticmethod
    def _credential_secrets(credentials: GitCredentials | None) -> tuple[str, ...]:
        if credentials is None:
            return ()
        return tuple(
            value
            for value in (credentials.token, credentials.ssh_private_key)
            if isinstance(value, str) and value
        )

    async def generate_deploy_key(
        self,
        server_id: str,
        *,
        comment: str | None = None,
        session: AsyncSession | None = None,
    ) -> GeneratedDeployKeyResult:
        segment = await self._guard(server_id, session)
        keypair = await asyncio.to_thread(
            generate_ed25519_deploy_keypair, segment, comment=comment
        )
        return GeneratedDeployKeyResult(
            server_id=segment,
            public_key_openssh=keypair.public_key_openssh,
            private_key_pem=keypair.private_key_pem,
            fingerprint_sha256=keypair.fingerprint_sha256,
        )

    async def connect(
        self,
        server_id: str,
        *,
        remote_url: str,
        auth_method: str,
        credential_secret: str,
        deploy_public_key: str | None = None,
        webhook_secret: str | None = None,
        enable_webhook: bool = False,
        server_root: str | os.PathLike[str] | None = None,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubConnectionStatus:
        segment = await self._guard(server_id, session)
        clean_url = self._validate_remote_and_auth(remote_url, auth_method)

        async with self._read_session(session) as active_session:
            existing = await SQLGitHubSyncRepository(active_session).get_connection(
                segment
            )
        if existing is not None:
            raise ConflictError(
                f"Server '{segment}' already has a GitHub connection"
            )

        deploy_key: str | None = None
        if auth_method == AUTH_METHOD_SSH_DEPLOY_KEY:
            deploy_key = self._derive_deploy_public_key(
                segment, credential_secret, deploy_public_key
            )
        credentials = self._build_credentials(auth_method, credential_secret)
        secrets = self._credential_secrets(credentials)

        root = await self._resolve_server_root(segment, server_root, session)
        runner = await asyncio.to_thread(self._open_repo_runner, segment, root)
        try:
            probe = await asyncio.to_thread(
                runner.run,
                "ls-remote",
                "--symref",
                "--",
                clean_url,
                credentials=credentials,
            )
        except (GitCommandError, GitTimeoutError) as exc:
            raise classify_git_remote_error(
                exc,
                auth_method=auth_method,
                extra_secrets=secrets,
            ) from exc

        default_branch, head_sha = self._parse_ls_remote(probe.stdout)
        generated_secret: str | None = None
        conn: ServerGitHubConnectionModel | None = None
        origin_configured = False
        saved = False
        try:
            async with self._get_repo_write_lock().acquire(
                segment, operation="sync"
            ) as lease:
                await lease.assert_valid()
                await asyncio.to_thread(
                    self._configure_origin_remote, runner, clean_url
                )
                origin_configured = True

                conn = ServerGitHubConnectionModel(
                    id=str(uuid.uuid4()),
                    server_id=segment,
                    remote_url=clean_url,
                    auth_method=auth_method,
                    remote_default_branch=default_branch,
                    remote_head_sha=head_sha,
                    sync_status="idle",
                    webhook_enabled=False,
                    wrapped_credential_dek=b"",
                    kek_version=1,
                    credential_nonce=b"",
                    credential_ciphertext=b"",
                )
                apply_credential_to_connection(
                    conn,
                    server_id=segment,
                    auth_method=auth_method,
                    secret=credential_secret,
                    deploy_public_key=deploy_key,
                    kek=self._kek,
                )

                if enable_webhook or webhook_secret is not None:
                    if webhook_secret is None:
                        generated_secret = generate_webhook_secret()
                        webhook_value = generated_secret
                    else:
                        webhook_value = webhook_secret
                    apply_webhook_secret_to_connection(
                        conn,
                        server_id=segment,
                        webhook_secret=webhook_value,
                        kek=self._kek,
                    )
                else:
                    clear_webhook_secret_on_connection(conn)

                async with self._write_session(session) as active_session:
                    repo = SQLGitHubSyncRepository(active_session)
                    if await repo.get_connection(segment) is not None:
                        raise ConflictError(
                            f"Server '{segment}' already has a GitHub connection"
                        )
                    try:
                        await repo.save_connection(conn)
                    except IntegrityError as exc:
                        raise ConflictError(
                            f"Server '{segment}' already has a GitHub connection"
                        ) from exc
                saved = True
        except BaseException:
            if origin_configured and not saved:
                try:
                    await asyncio.to_thread(self._remove_origin_remote, runner)
                except Exception:  # noqa: BLE001 - best-effort rollback
                    logger.warning(
                        "Unable to roll back GitHub origin for server %s", segment
                    )
            raise

        if conn is None:
            raise GitRepositoryStateError("GitHub connection was not created")
        await self._publish(
            GitHubConnectedEvent(
                server_id=segment,
                remote_url=conn.remote_url,
                auth_method=conn.auth_method,
                webhook_enabled=bool(conn.webhook_enabled),
                remote_default_branch=conn.remote_default_branch,
                actor_id=actor_id,
            )
        )
        return self._status_from_connection(
            conn, generated_webhook_secret=generated_secret
        )

    async def rotate_credentials(
        self,
        server_id: str,
        *,
        credential_secret: str | None = None,
        auth_method: str | None = None,
        deploy_public_key: str | None = None,
        webhook_secret: str | None = None,
        enable_webhook: bool | None = None,
        regenerate_webhook_secret: bool = False,
        disable_webhook: bool = False,
        server_root: str | os.PathLike[str] | None = None,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubConnectionStatus:
        segment = await self._guard(server_id, session)
        has_action = (
            credential_secret is not None
            or auth_method is not None
            or deploy_public_key is not None
            or webhook_secret is not None
            or enable_webhook is not None
            or regenerate_webhook_secret
            or disable_webhook
        )
        if not has_action:
            raise ValidationError(
                "At least one GitHub credential or webhook rotation is required",
                field="credential_secret",
            )
        if disable_webhook and (
            webhook_secret is not None
            or regenerate_webhook_secret
            or enable_webhook is True
        ):
            raise ValidationError(
                "disable_webhook cannot be combined with enabling or rotating "
                "a webhook secret",
                field="disable_webhook",
            )

        async with self._read_session(session) as active_session:
            existing = await SQLGitHubSyncRepository(active_session).get_connection(
                segment
            )
            if existing is None:
                raise GitHubNotConnectedError(segment)
            remote_url = existing.remote_url
            current_auth_method = existing.auth_method

        target_auth_method = auth_method or current_auth_method
        clean_url = self._validate_remote_and_auth(remote_url, target_auth_method)
        if (
            auth_method is not None
            and auth_method != current_auth_method
            and credential_secret is None
        ):
            raise ValidationError(
                "Changing auth_method requires credential_secret",
                field="credential_secret",
            )

        credentials: GitCredentials | None = None
        deploy_key: str | None = None
        if credential_secret is not None:
            if target_auth_method == AUTH_METHOD_SSH_DEPLOY_KEY:
                deploy_key = self._derive_deploy_public_key(
                    segment, credential_secret, deploy_public_key
                )
            credentials = self._build_credentials(
                target_auth_method, credential_secret
            )
        elif deploy_public_key is not None:
            if target_auth_method != AUTH_METHOD_SSH_DEPLOY_KEY:
                raise ValidationError(
                    "deploy_public_key is only valid for ssh_deploy_key auth",
                    field="deploy_public_key",
                )
            try:
                current_credentials = decrypt_connection_credential(
                    existing, kek=self._kek
                )
            except Exception:  # noqa: BLE001 - fail closed on decrypt failure
                raise GitHubAuthFailedError(
                    auth_method=target_auth_method
                ) from None
            if current_credentials.ssh_private_key is None:
                raise GitHubAuthFailedError(auth_method=target_auth_method)
            deploy_key = self._derive_deploy_public_key(
                segment,
                current_credentials.ssh_private_key,
                deploy_public_key,
            )

        runner: GitRunner | None = None
        if credentials is not None:
            root = await self._resolve_server_root(segment, server_root, session)
            runner = await asyncio.to_thread(
                self._open_repo_runner, segment, root
            )

        credential_rotated = credential_secret is not None
        webhook_secret_rotated = False
        generated_secret: str | None = None
        conn: ServerGitHubConnectionModel | None = None

        async with self._get_repo_write_lock().acquire(
            segment, operation="sync"
        ) as lease:
            if credentials is not None and runner is not None:
                await lease.assert_valid()
                try:
                    await asyncio.to_thread(
                        runner.run,
                        "ls-remote",
                        "--symref",
                        "--",
                        clean_url,
                        credentials=credentials,
                    )
                except (GitCommandError, GitTimeoutError) as exc:
                    raise classify_git_remote_error(
                        exc,
                        auth_method=target_auth_method,
                        extra_secrets=self._credential_secrets(credentials),
                    ) from exc

            async with self._write_session(session) as active_session:
                repo = SQLGitHubSyncRepository(active_session)
                conn = await repo.get_connection(segment)
                if conn is None:
                    raise GitHubNotConnectedError(segment)

                if credential_rotated and credential_secret is not None:
                    apply_credential_to_connection(
                        conn,
                        server_id=segment,
                        auth_method=target_auth_method,
                        secret=credential_secret,
                        deploy_public_key=deploy_key,
                        kek=self._kek,
                    )
                    if conn.sync_status == "auth_failed":
                        conn.sync_status = "idle"
                    conn.last_error_code = None
                    conn.last_error_message = None
                elif deploy_key is not None:
                    conn.deploy_public_key = deploy_key
                    conn.credential_hint = compute_ssh_public_key_fingerprint(
                        deploy_key
                    )[:64]

                if disable_webhook:
                    clear_webhook_secret_on_connection(conn)
                elif webhook_secret is not None:
                    apply_webhook_secret_to_connection(
                        conn,
                        server_id=segment,
                        webhook_secret=webhook_secret,
                        kek=self._kek,
                    )
                    webhook_secret_rotated = True
                elif regenerate_webhook_secret:
                    generated_secret = generate_webhook_secret()
                    apply_webhook_secret_to_connection(
                        conn,
                        server_id=segment,
                        webhook_secret=generated_secret,
                        kek=self._kek,
                    )
                    webhook_secret_rotated = True
                elif enable_webhook is True:
                    if conn.wrapped_webhook_dek is None:
                        generated_secret = generate_webhook_secret()
                        apply_webhook_secret_to_connection(
                            conn,
                            server_id=segment,
                            webhook_secret=generated_secret,
                            kek=self._kek,
                        )
                        webhook_secret_rotated = True
                    else:
                        conn.webhook_enabled = True
                elif enable_webhook is False:
                    conn.webhook_enabled = False

                await repo.save_connection(conn)

        if conn is None:
            raise GitHubNotConnectedError(segment)
        await self._publish(
            GitHubCredentialsRotatedEvent(
                server_id=segment,
                auth_method=conn.auth_method,
                credential_rotated=credential_rotated,
                webhook_secret_rotated=webhook_secret_rotated,
                webhook_enabled=bool(conn.webhook_enabled),
                actor_id=actor_id,
            )
        )
        return self._status_from_connection(
            conn, generated_webhook_secret=generated_secret
        )

    async def disconnect(
        self,
        server_id: str,
        *,
        purge_deliveries: bool = False,
        server_root: str | os.PathLike[str] | None = None,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubDisconnectResult:
        segment = await self._guard(server_id, session)

        async with self._read_session(session) as active_session:
            existing = await SQLGitHubSyncRepository(active_session).get_connection(
                segment
            )
            if existing is None:
                raise GitHubNotConnectedError(segment)
            remote_url = existing.remote_url

        root = await self._resolve_server_root(segment, server_root, session)
        purged = 0
        async with self._get_repo_write_lock().acquire(
            segment, operation="sync"
        ) as lease:
            await lease.assert_valid()
            runner: GitRunner | None = None
            try:
                runner = await asyncio.to_thread(
                    self._open_repo_runner, segment, root
                )
            except GitRepositoryStateError:
                runner = None
            if runner is not None:
                await asyncio.to_thread(self._remove_origin_remote, runner)

            async with self._write_session(session) as active_session:
                repo = SQLGitHubSyncRepository(active_session)
                if purge_deliveries:
                    purged = await repo.delete_webhook_deliveries(segment)
                if not await repo.delete_connection(segment):
                    raise GitHubNotConnectedError(segment)

        await self._publish(
            GitHubDisconnectedEvent(
                server_id=segment,
                remote_url=remote_url,
                local_history_preserved=True,
                actor_id=actor_id,
            )
        )
        return GitHubDisconnectResult(
            server_id=segment,
            disconnected=True,
            remote_url=remote_url,
            local_history_preserved=True,
            purged_deliveries=purged,
        )

    # ------------------------------------------------------------------
    # Fetch-first sync
    # ------------------------------------------------------------------

    async def fetch_first_sync(
        self,
        server_id: str,
        *,
        trigger: str = "manual",
        server_root: str | os.PathLike[str] | None = None,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubSyncResult:
        segment = await self._guard(server_id, session)
        context = await self._load_remote_context(server_id, session)
        root = await self._resolve_server_root(segment, server_root, session)
        runner = await asyncio.to_thread(self._open_repo_runner, segment, root)
        secrets = self._credential_secrets(context.credentials)
        fetched_at = datetime.now(UTC)

        previous_main_sha: str | None = None
        main_sha: str | None = None
        remote_head_sha: str | None = context.remote_head_sha
        branches: tuple[GitHubBranchSyncState, ...] = ()
        sync_status = "synced"
        fast_forwarded = False
        pending_dirty: DirtyWorktreeError | None = None
        pending_conflict: NonFastForwardMainError | None = None

        async with self._get_repo_write_lock().acquire(
            segment, operation="fetch"
        ) as lease:
            await lease.assert_valid()
            await asyncio.to_thread(
                self._configure_origin_remote, runner, context.remote_url
            )
            try:
                await asyncio.to_thread(
                    runner.run,
                    "fetch",
                    "--prune",
                    "--no-tags",
                    REMOTE_NAME,
                    REMOTE_FETCH_REFSPEC,
                    credentials=context.credentials,
                )
            except (GitCommandError, GitTimeoutError) as exc:
                classified = classify_git_remote_error(
                    exc,
                    auth_method=context.auth_method,
                    extra_secrets=secrets,
                )
                await self._persist_error(segment, classified)
                raise classified from exc

            previous_main_sha = await asyncio.to_thread(
                _resolve_ref, runner, f"refs/heads/{MAIN_BRANCH}"
            )
            remote_main_sha = await asyncio.to_thread(
                _resolve_ref,
                runner,
                f"refs/remotes/{REMOTE_NAME}/{MAIN_BRANCH}",
            )
            if remote_main_sha is not None:
                remote_head_sha = remote_main_sha

            if (
                remote_main_sha is not None
                and previous_main_sha is not None
                and previous_main_sha != remote_main_sha
            ):
                local_is_ancestor = await asyncio.to_thread(
                    _is_ancestor, runner, previous_main_sha, remote_main_sha
                )
                if local_is_ancestor:
                    info = await asyncio.to_thread(
                        self._branch_service.get_branch,
                        segment,
                        root,
                        MAIN_BRANCH,
                    )
                    dirty = info is not None and await asyncio.to_thread(
                        self._branch_service.has_uncommitted_changes,
                        segment,
                        root,
                        MAIN_BRANCH,
                    )
                    if dirty:
                        branches = await asyncio.to_thread(
                            _compute_branch_sync, runner
                        )
                        await self._persist_sync_state(
                            segment,
                            sync_status="behind",
                            branches=branches,
                            remote_head_sha=remote_main_sha,
                            fetched_at=fetched_at,
                            error_code=None,
                            error_message=None,
                        )
                        pending_dirty = DirtyWorktreeError(
                            branch=MAIN_BRANCH,
                            message=(
                                "Main worktree has uncommitted changes; commit or "
                                "discard them before fast-forwarding main from GitHub"
                            ),
                        )
                    else:
                        await lease.assert_valid()
                        await asyncio.to_thread(
                            runner.run,
                            "update-ref",
                            f"refs/heads/{MAIN_BRANCH}",
                            remote_main_sha,
                            previous_main_sha,
                        )
                        if info is not None and info.worktree_path is not None:
                            await asyncio.to_thread(
                                runner.run,
                                "reset",
                                "--hard",
                                remote_main_sha,
                                cwd=info.worktree_path,
                            )
                            head_result = await asyncio.to_thread(
                                runner.run,
                                "rev-parse",
                                "HEAD",
                                cwd=info.worktree_path,
                            )
                            if head_result.stdout.strip() != remote_main_sha:
                                raise GitRepositoryStateError(
                                    "Main worktree did not fast-forward to the "
                                    "remote commit",
                                    details={
                                        "expected": remote_main_sha,
                                        "actual": head_result.stdout.strip()[:64],
                                    },
                                )
                        await self._project_main_commit(
                            segment,
                            remote_main_sha,
                            runner,
                            previous_main_sha=previous_main_sha,
                        )
                        fast_forwarded = True
                else:
                    remote_is_ancestor = await asyncio.to_thread(
                        _is_ancestor, runner, remote_main_sha, previous_main_sha
                    )
                    if not remote_is_ancestor:
                        branches = await asyncio.to_thread(
                            _compute_branch_sync, runner
                        )
                        conflict = NonFastForwardMainError(
                            local_sha=previous_main_sha,
                            remote_sha=remote_main_sha,
                        )
                        await self._persist_sync_state(
                            segment,
                            sync_status="conflict",
                            branches=branches,
                            remote_head_sha=remote_main_sha,
                            fetched_at=fetched_at,
                            error_code=conflict.code,
                            error_message=self._safe_error_message(conflict),
                        )
                        pending_conflict = conflict

            if pending_dirty is None and pending_conflict is None:
                main_sha = await asyncio.to_thread(
                    _resolve_ref, runner, f"refs/heads/{MAIN_BRANCH}"
                )
                branches = await asyncio.to_thread(_compute_branch_sync, runner)
                sync_status = _summarize_sync_status(branches)
                await self._persist_sync_state(
                    segment,
                    sync_status=sync_status,
                    branches=branches,
                    remote_head_sha=remote_head_sha,
                    fetched_at=fetched_at,
                    error_code=None,
                    error_message=None,
                )

        actor_type = "user" if trigger == "manual" else "system"
        if pending_conflict is not None:
            await self._publish(
                GitHubSyncedEvent(
                    server_id=segment,
                    sync_status="conflict",
                    trigger=trigger,
                    main_fast_forwarded=False,
                    previous_main_sha=previous_main_sha,
                    main_sha=previous_main_sha,
                    remote_head_sha=remote_head_sha,
                    branch_name=MAIN_BRANCH,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            )
            raise pending_conflict
        if pending_dirty is not None:
            raise pending_dirty

        await self._publish(
            GitHubSyncedEvent(
                server_id=segment,
                sync_status=sync_status,
                trigger=trigger,
                main_fast_forwarded=fast_forwarded,
                previous_main_sha=previous_main_sha,
                main_sha=main_sha,
                remote_head_sha=remote_head_sha,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        )
        return GitHubSyncResult(
            server_id=segment,
            sync_status=sync_status,
            trigger=trigger,
            main_fast_forwarded=fast_forwarded,
            previous_main_sha=previous_main_sha,
            main_sha=main_sha,
            remote_default_branch=context.remote_default_branch,
            remote_head_sha=remote_head_sha,
            branches=branches,
            fetched_at=fetched_at,
        )

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    async def push_branch(
        self,
        server_id: str,
        branch_name: str,
        *,
        force: bool = False,
        server_root: str | os.PathLike[str] | None = None,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubPushResult:
        segment = await self._guard(server_id, session)
        if force:
            if branch_name == MAIN_BRANCH:
                raise NonFastForwardMainError(
                    "Force-push to main is forbidden",
                    local_sha="",
                    remote_sha="",
                )
            raise GitHubPushRejectedError(
                "Force-push is forbidden",
                branch=branch_name,
                reason="force_push_forbidden",
            )
        _validate_branch_path_name(branch_name)

        context = await self._load_remote_context(server_id, session)
        root = await self._resolve_server_root(segment, server_root, session)
        runner = await asyncio.to_thread(self._open_repo_runner, segment, root)
        await asyncio.to_thread(runner.validate_branch_name, branch_name)

        pushed_at = datetime.now(UTC)
        local_sha = ""
        remote_sha = ""
        branches: tuple[GitHubBranchSyncState, ...] = ()
        sync_status = "synced"
        pending_conflict: NonFastForwardMainError | None = None

        async with self._get_repo_write_lock().acquire(
            segment, operation="push"
        ) as lease:
            await lease.assert_valid()
            await asyncio.to_thread(
                self._configure_origin_remote, runner, context.remote_url
            )
            resolved = await asyncio.to_thread(
                _resolve_ref, runner, f"refs/heads/{branch_name}"
            )
            if resolved is None:
                raise NotFoundError(f"Branch '{branch_name}' not found")
            local_sha = resolved
            existing_remote = await asyncio.to_thread(
                _resolve_ref,
                runner,
                f"refs/remotes/{REMOTE_NAME}/{branch_name}",
            )
            remote_sha = existing_remote or ""

            await asyncio.to_thread(
                _assert_no_plain_jar_blobs, runner, branch_name
            )

            if branch_name == MAIN_BRANCH and existing_remote is not None:
                is_fast_forward = await asyncio.to_thread(
                    _is_ancestor, runner, existing_remote, local_sha
                )
                if not is_fast_forward:
                    conflict = NonFastForwardMainError(
                        local_sha=local_sha, remote_sha=remote_sha
                    )
                    await self._persist_error(segment, conflict)
                    pending_conflict = conflict

            if pending_conflict is None:
                await lease.assert_valid()
                try:
                    await asyncio.to_thread(
                        runner.run,
                        "push",
                        REMOTE_NAME,
                        f"refs/heads/{branch_name}:refs/heads/{branch_name}",
                        credentials=context.credentials,
                    )
                except (GitCommandError, GitTimeoutError) as exc:
                    classified = classify_git_remote_error(
                        exc,
                        auth_method=context.auth_method,
                        branch=branch_name,
                        local_sha=local_sha,
                        remote_sha=remote_sha,
                        extra_secrets=self._credential_secrets(context.credentials),
                    )
                    await self._persist_error(segment, classified)
                    raise classified from exc

                await lease.assert_valid()
                await asyncio.to_thread(
                    runner.run,
                    "update-ref",
                    f"refs/remotes/{REMOTE_NAME}/{branch_name}",
                    local_sha,
                )
                branches = await asyncio.to_thread(_compute_branch_sync, runner)
                sync_status = _summarize_sync_status(branches)
                values: dict[str, Any] = {
                    "sync_status": sync_status,
                    "branch_sync_json": [
                        branch.to_dict() for branch in branches
                    ],
                    "last_push_at": pushed_at,
                    "last_error_code": None,
                    "last_error_message": None,
                }
                if branch_name == MAIN_BRANCH:
                    values["remote_head_sha"] = local_sha
                await self._update_connection_row(segment, values=values)

        if pending_conflict is not None:
            raise pending_conflict

        await self._publish(
            GitHubPushedEvent(
                server_id=segment,
                branch_name=branch_name,
                commit_sha=local_sha,
                remote_url=context.remote_url,
                actor_id=actor_id,
            )
        )
        return GitHubPushResult(
            server_id=segment,
            branch_name=branch_name,
            commit_sha=local_sha,
            remote_url=context.remote_url,
            sync_status=sync_status,
            branches=branches,
            pushed_at=pushed_at,
        )

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    @staticmethod
    def _require_webhook_text(
        value: str | None, field: str, limit: int
    ) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > limit
            or _CONTROL_RE.search(value)
        ):
            raise ValidationError(
                f"Malformed GitHub webhook {field}",
                field=field,
            )
        return value

    async def ingest_webhook(
        self,
        server_id: str,
        *,
        raw_body: bytes,
        signature_header: str | None,
        delivery_id: str | None,
        event_type: str | None,
        session: AsyncSession | None = None,
    ) -> GitHubWebhookIngestResult:
        try:
            self._assert_posix()
            segment = validate_server_segment(server_id)
            secret: str | None = None
            async with self._read_session(session) as active_session:
                await ensure_versioning_allowed(segment, session=active_session)
                connection = await SQLGitHubSyncRepository(
                    active_session
                ).get_connection(segment)
                if connection is None or not connection.webhook_enabled:
                    raise WebhookSignatureError()
                try:
                    secret = decrypt_connection_webhook_secret(
                        connection, kek=self._kek
                    )
                except Exception:  # noqa: BLE001 - fail closed
                    raise WebhookSignatureError() from None
            if not secret:
                raise WebhookSignatureError()
        except WebhookSignatureError:
            raise
        except Exception:  # noqa: BLE001 - never leak server/connection state
            raise WebhookSignatureError() from None

        assert_valid_webhook_signature(secret, raw_body, signature_header)
        if not isinstance(raw_body, (bytes, bytearray)):
            raise WebhookSignatureError()
        body = bytes(raw_body)
        if len(body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise ValidationError(
                "GitHub webhook payload exceeds the 2 MiB limit",
                field="raw_body",
            )

        delivery_value = self._require_webhook_text(
            delivery_id, "delivery_id", MAX_DELIVERY_ID_LENGTH
        )
        event_value = self._require_webhook_text(
            event_type, "event_type", MAX_EVENT_TYPE_LENGTH
        )

        payload_sha256 = hashlib.sha256(body).hexdigest()
        try:
            payload_text = body.decode("utf-8")
            payload = json.loads(payload_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "GitHub webhook payload is not valid JSON",
                field="raw_body",
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                "GitHub webhook payload must be a JSON object",
                field="raw_body",
            )

        raw_ref = payload.get("ref")
        ref = str(raw_ref)[:MAX_WEBHOOK_REF_LENGTH] if isinstance(
            raw_ref, str
        ) and raw_ref else None
        raw_before = payload.get("before")
        before_sha = str(raw_before)[:64] if isinstance(
            raw_before, str
        ) and raw_before else None
        raw_after = payload.get("after")
        after_sha = str(raw_after)[:64] if isinstance(
            raw_after, str
        ) and raw_after else None
        received_at = datetime.now(UTC)

        delivery = GitHubWebhookDeliveryModel(
            id=str(uuid.uuid4()),
            server_id=segment,
            delivery_id=delivery_value,
            event_type=event_value,
            ref=ref,
            before_sha=before_sha,
            after_sha=after_sha,
            payload_sha256=payload_sha256,
            raw_payload=payload_text,
            signature_valid=True,
            status="received",
            redelivery_count=0,
            received_at=received_at,
        )

        operation_id: str | None = None
        deduplicated = False
        status: WebhookIngestStatus
        stored_delivery: GitHubWebhookDeliveryModel | None = None

        async with self._write_session(session) as active_session:
            repo = SQLGitHubSyncRepository(active_session)
            stored_delivery, created = await repo.create_webhook_delivery(delivery)
            if not created:
                deduplicated = True
                status = "deduplicated"
                operation_id = stored_delivery.operation_id
            else:
                if event_value in WEBHOOK_ENQUEUE_EVENTS:
                    operation = await self._get_operation_service().create_operation(
                        GITHUB_SYNC_OPERATION,
                        target_type="server",
                        target_id=segment,
                        idempotency_key=(
                            f"github-webhook:{segment}:{delivery_value}"
                        ),
                        initial_steps=[
                            {
                                "step_id": SYNC_STEP_ID,
                                "sequence": 1,
                                "message_key": "github.sync.fetch",
                                "safe_to_retry": True,
                                "context": {
                                    "delivery_id": delivery_value,
                                    "ref": ref,
                                },
                            }
                        ],
                        session=active_session,
                    )
                    operation_id = operation.id
                    stored_delivery.operation_id = operation_id
                    stored_delivery.status = "queued"
                    await repo.save_webhook_delivery(stored_delivery)
                    status = "queued"
                else:
                    stored_delivery.status = "ignored"
                    stored_delivery.processed_at = received_at
                    await repo.save_webhook_delivery(stored_delivery)
                    status = "ignored"

        if deduplicated:
            await self._publish(
                GitHubWebhookReceivedEvent(
                    server_id=segment,
                    delivery_id=delivery_value,
                    event_type=event_value,
                    ref=ref,
                    deduplicated=True,
                    operation_id=operation_id,
                )
            )
            return GitHubWebhookIngestResult(
                server_id=segment,
                delivery_id=delivery_value,
                event_type=event_value,
                status="deduplicated",
                deduplicated=True,
                operation_id=operation_id,
                received_at=stored_delivery.received_at if stored_delivery else None,
            )

        if status == "queued" and operation_id is not None:
            await self._invoke_webhook_dispatcher(
                segment, operation_id, delivery_value
            )
        await self._publish(
            GitHubWebhookReceivedEvent(
                server_id=segment,
                delivery_id=delivery_value,
                event_type=event_value,
                ref=ref,
                operation_id=operation_id,
            )
        )
        return GitHubWebhookIngestResult(
            server_id=segment,
            delivery_id=delivery_value,
            event_type=event_value,
            status=status,
            operation_id=operation_id,
            received_at=received_at,
        )

    async def redeliver_webhook(
        self,
        server_id: str,
        delivery_id: str,
        *,
        actor_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> GitHubWebhookIngestResult:
        segment = await self._guard(server_id, session)
        received_at = datetime.now(UTC)
        redelivery_count = 0
        operation_id: str | None = None
        event_value = "push"
        delivery_value = delivery_id
        ref: str | None = None

        async with self._write_session(session) as active_session:
            repo = SQLGitHubSyncRepository(active_session)
            connection = await repo.get_connection(segment)
            if connection is None:
                raise GitHubNotConnectedError(segment)
            stored = await repo.get_webhook_delivery_by_ref(segment, delivery_id)
            if stored is None:
                raise NotFoundError(
                    f"GitHub webhook delivery '{delivery_id}' not found"
                )

            stored.redelivery_count = (stored.redelivery_count or 0) + 1
            redelivery_count = stored.redelivery_count
            event_value = stored.event_type
            delivery_value = stored.delivery_id
            ref = stored.ref
            operation = await self._get_operation_service().create_operation(
                GITHUB_SYNC_OPERATION,
                target_type="server",
                target_id=segment,
                actor_id=actor_id,
                idempotency_key=(
                    "github-webhook-redeliver:"
                    f"{segment}:{stored.delivery_id}:{redelivery_count}"
                ),
                initial_steps=[
                    {
                        "step_id": SYNC_STEP_ID,
                        "sequence": 1,
                        "message_key": "github.sync.fetch",
                        "safe_to_retry": True,
                        "context": {
                            "delivery_id": stored.delivery_id,
                            "ref": stored.ref,
                            "redelivery": True,
                        },
                    }
                ],
                session=active_session,
            )
            operation_id = operation.id
            stored.operation_id = operation_id
            stored.status = "queued"
            stored.error_message = None
            stored.processed_at = None
            await repo.save_webhook_delivery(stored)
            received_at = stored.received_at or received_at

        assert operation_id is not None
        await self._invoke_webhook_dispatcher(segment, operation_id, delivery_value)
        await self._publish(
            GitHubWebhookReceivedEvent(
                server_id=segment,
                delivery_id=delivery_value,
                event_type=event_value,
                ref=ref,
                redelivered=True,
                operation_id=operation_id,
                actor_type="user",
                actor_id=actor_id,
            )
        )
        return GitHubWebhookIngestResult(
            server_id=segment,
            delivery_id=delivery_value,
            event_type=event_value,
            status="queued",
            redelivered=True,
            redelivery_count=redelivery_count,
            operation_id=operation_id,
            received_at=received_at,
        )

    async def get_status(
        self,
        server_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> GitHubConnectionStatus:
        segment = await self._guard(server_id, session)
        async with self._read_session(session) as active_session:
            connection = await SQLGitHubSyncRepository(
                active_session
            ).get_connection(segment)
        if connection is None:
            return GitHubConnectionStatus(
                server_id=segment,
                connected=False,
                sync_status="disconnected",
            )
        return self._status_from_connection(connection)

    async def list_deliveries(
        self,
        server_id: str,
        *,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[GitHubWebhookDeliveryRecord]:
        segment = await self._guard(server_id, session)
        async with self._read_session(session) as active_session:
            rows = await SQLGitHubSyncRepository(
                active_session
            ).list_webhook_deliveries(segment, limit=limit)
        records: list[GitHubWebhookDeliveryRecord] = []
        for row in rows:
            records.append(
                GitHubWebhookDeliveryRecord(
                    id=row.id,
                    server_id=row.server_id,
                    delivery_id=row.delivery_id,
                    event_type=row.event_type,
                    ref=row.ref,
                    before_sha=row.before_sha,
                    after_sha=row.after_sha,
                    payload_sha256=row.payload_sha256,
                    signature_valid=bool(row.signature_valid),
                    status=row.status,
                    operation_id=row.operation_id,
                    error_message=row.error_message,
                    redelivery_count=row.redelivery_count or 0,
                    received_at=row.received_at or datetime.now(UTC),
                    processed_at=row.processed_at,
                )
            )
        return records

    # ------------------------------------------------------------------
    # Durable operation worker
    # ------------------------------------------------------------------

    async def run_queued_sync_operation(
        self,
        server_id: str,
        operation_id: str,
        *,
        delivery_id: str | None = None,
        server_root: str | os.PathLike[str] | None = None,
        trigger: str = "webhook",
    ) -> GitHubSyncResult:
        self._assert_posix()
        segment = validate_server_segment(server_id)
        operation_service = self._get_operation_service()

        async with self._read_session() as active_session:
            operation = await operation_service.get_operation(
                operation_id, session=active_session
            )
        if (
            operation.type != GITHUB_SYNC_OPERATION
            or operation.target_type != "server"
            or operation.target_id != segment
        ):
            raise ValidationError(
                "Operation is not a queued GitHub sync for this server",
                field="operation_id",
                details={"operation_id": operation_id},
            )

        async with self._write_session() as active_session:
            await operation_service.start_step(
                operation_id, SYNC_STEP_ID, session=active_session
            )

        try:
            result = await self.fetch_first_sync(
                segment,
                trigger=trigger,
                server_root=server_root,
            )
        except Exception as exc:
            if isinstance(exc, MCSError):
                failure_code = getattr(exc, "code", "") or "GITHUB_SYNC_FAILED"
                safe_message = self._safe_error_message(exc)
            else:
                failure_code = "GITHUB_SYNC_FAILED"
                safe_message = redact_secrets(str(exc))[:512]
            failed_at = datetime.now(UTC)
            async with self._write_session() as active_session:
                if delivery_id:
                    repo = SQLGitHubSyncRepository(active_session)
                    stored = await repo.get_webhook_delivery_by_ref(
                        segment, delivery_id
                    )
                    if stored is not None:
                        stored.status = "failed"
                        stored.error_message = safe_message
                        stored.processed_at = failed_at
                        stored.operation_id = operation_id
                        await repo.save_webhook_delivery(stored)
                await operation_service.fail_step(
                    operation_id,
                    SYNC_STEP_ID,
                    safe_to_retry=True,
                    error=safe_message,
                    session=active_session,
                )
                await operation_service.fail_operation(
                    operation_id,
                    failure_code=failure_code,
                    error_message=safe_message,
                    failed_step_id=SYNC_STEP_ID,
                    session=active_session,
                )
            raise

        processed_at = datetime.now(UTC)
        async with self._write_session() as active_session:
            if delivery_id:
                repo = SQLGitHubSyncRepository(active_session)
                stored = await repo.get_webhook_delivery_by_ref(
                    segment, delivery_id
                )
                if stored is not None:
                    stored.status = "processed"
                    stored.error_message = None
                    stored.processed_at = processed_at
                    stored.operation_id = operation_id
                    await repo.save_webhook_delivery(stored)
            await operation_service.complete_step(
                operation_id,
                SYNC_STEP_ID,
                context={
                    "sync_status": result.sync_status,
                    "main_sha": result.main_sha,
                },
                session=active_session,
            )
            await operation_service.complete_operation(
                operation_id, session=active_session
            )
        return result


__all__ = [
    "BranchSyncStatus",
    "GeneratedDeployKeyResult",
    "GitHubBranchSyncState",
    "GitHubConnectionStatus",
    "GitHubDisconnectResult",
    "GitHubPushResult",
    "GitHubSyncResult",
    "GitHubSyncService",
    "GitHubWebhookDeliveryRecord",
    "GitHubWebhookIngestResult",
    "WebhookIngestStatus",
    "classify_git_remote_error",
]
