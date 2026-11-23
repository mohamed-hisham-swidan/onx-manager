from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import (
    ConfigFactory,
    get_active_panel_bind,
    local_panel_ingress_target,
    panel_ingress_target,
)
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, NotFoundError, ValidationError
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.local_auth import require_password_configured_for_exposure
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.domain.aggregate import AccessMode
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository
from app.modules.exposure.domain.aggregate import (
    DENY_LIST_PORTS,
    HostPlayitAgent,
    PanelExposure,
    ServerExposure,
    ServerExposureTarget,
    _coerce_protocol,
    _coerce_service_type,
)
from app.modules.exposure.domain.exceptions import (
    ClaimActiveError,
    InvalidServiceTypeError,
    MethodProtocolIncompatibleError,
    NoTargetsError,
    PortAlreadyRegisteredError,
    UnregisteredPortError,
    WarningNotAcknowledgedError,
)
from app.modules.exposure.domain.repository import (
    HostAgentRepository,
    PanelExposureRepository,
    ServerExposureRepository,
)
from app.modules.exposure.domain.value_objects import (
    AgentProcessStatus,
    DesiredState,
    ExposureMethod,
    ExposureStatus,
    PanelExposureMethod,
    ServiceType,
    TargetProtocol,
    aggregate_precedence,
    exposure_status_to_process_status,
)
from app.modules.exposure.infrastructure.cloudflare import (
    CloudflareApiError,
    CloudflareAuthError,
    CloudflareClient,
)
from app.modules.exposure.infrastructure.cloudflared import (
    CloudflaredSupervisor,
    get_cloudflared_supervisor,
    get_server_cloudflared_supervisor,
)
from app.modules.exposure.infrastructure.models import ServerRegisteredPortModel
from app.modules.exposure.infrastructure.playit_agent import (
    generate_playit_claim_code,
    get_playit_supervisor,
)
from app.modules.exposure.infrastructure.playit_api import (
    PlayitAllocationFullError,
    PlayitApiClient,
    PlayitAuthError,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
    SQLServerRegisteredPortRepository,
)
from app.modules.exposure.infrastructure.upnp import AsyncUPnPService
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.storage.encryption import build_backup_encryption

CLAIM_TTL_MINUTES = 10
logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure")


async def compute_desired_agent_running(session: AsyncSession) -> bool:
    """Authoritative computation of host playit agent desired running state."""
    server_repo = SQLServerExposureRepository(session)
    panel_repo = SQLPanelExposureRepository(session)

    playit_servers = await server_repo.list_playit_enabled()
    panel = await panel_repo.get()

    panel_playit_enabled = (
        panel.method == PanelExposureMethod.PLAYIT_HTTP
        and panel.desired_state == DesiredState.ENABLED
    )
    return len(playit_servers) > 0 or panel_playit_enabled


async def _attempt_server_upnp_mapping(
    server_id: str,
    target: ServerExposureTarget,
    *,
    external_port: int | None = None,
    subdomain_host: str | None = None,
) -> None:
    upnp = AsyncUPnPService()
    req_ext = external_port if external_port is not None else target.local_port
    result = await upnp.attempt_mapping(
        internal_port=target.local_port,
        requested_external_port=req_ext,
        description=f"ONX-Server-{server_id[:8]}-{target.service_type.value}",
        protocol=target.protocol.value.upper(),
    )
    if result.success:
        mapped_port = result.external_port or req_ext
        addr = (
            f"{subdomain_host}:{mapped_port}"
            if subdomain_host
            else f"{result.external_ip}:{mapped_port}"
        )
        target.mark_active(addr)
    else:
        target.mark_error(code=result.error_code, message=result.error_message)


def _exposure_supervisor_key(server_id: str, branch_name: str = "main") -> str:
    b = (branch_name or "main").strip() or "main"
    return server_id if b == "main" else f"{server_id}:{b}"


async def resolve_server_branch_exposure_context(
    session: AsyncSession,
    server: Any,
    branch_name: str | None,
) -> dict[str, Any]:
    """Resolve isolated game port & runtime state for a server or branch."""
    from sqlalchemy import select as _select

    from app.modules.versioning.infrastructure.models import (
        ServerBranchModel,
        ServerRuntimeModel,
    )

    eff = (branch_name or "main").strip() or "main"
    raw_mode = getattr(server, "mode", "simple")
    mode_val = getattr(raw_mode, "value", raw_mode)
    if eff == "main" or mode_val != "advanced":
        return {
            "branch_name": "main",
            "is_branch": False,
            "game_port": server.properties.port.value,
            "branch_runtime_status": server.status.value.lower(),
            "allocated_port_set": None,
        }

    br_res = await session.execute(
        _select(ServerBranchModel).where(
            ServerBranchModel.server_id == str(server.id),
            ServerBranchModel.name == eff,
        )
    )
    br_row = br_res.scalars().first()
    if br_row is None:
        # Check Git branches directly if DB row hasn't synced yet.
        root_path = getattr(getattr(server, "deployment", None), "root_path", None)
        if root_path:
            from app.core.host_state import resolve_host_state_layout
            from app.modules.versioning.infrastructure.git_branches import GitBranchService

            git_info = GitBranchService(resolve_host_state_layout()).get_branch(
                str(server.id), root_path, eff
            )
            if git_info is None:
                raise NotFoundError(f"Branch '{eff}' not found on server '{server.id}'")
        else:
            raise NotFoundError(f"Branch '{eff}' not found on server '{server.id}'")

    rt_res = await session.execute(
        _select(ServerRuntimeModel)
        .where(
            ServerRuntimeModel.server_id == str(server.id),
            ServerRuntimeModel.branch_name == eff,
            ServerRuntimeModel.status.in_(("starting", "running", "stopped")),
        )
        .order_by(ServerRuntimeModel.started_at.desc())
    )
    rt_row = rt_res.scalars().first()

    port_set_dict = None
    if rt_row is not None and isinstance(getattr(rt_row, "port_set_json", None), dict):
        port_set_dict = dict(rt_row.port_set_json)
    elif br_row is not None and isinstance(getattr(br_row, "port_set_json", None), dict):
        port_set_dict = dict(br_row.port_set_json)

    game_port = None
    if isinstance(port_set_dict, dict) and port_set_dict.get("game_port") is not None:
        game_port = int(port_set_dict["game_port"])

    if rt_row is not None and rt_row.status in ("starting", "running"):
        rt_status = "running"
    elif rt_row is not None and rt_row.status == "stopped":
        rt_status = "stopped"
    else:
        rt_status = "unprovisioned"

    return {
        "branch_name": eff,
        "is_branch": True,
        "game_port": game_port,
        "branch_runtime_status": rt_status,
        "allocated_port_set": port_set_dict,
    }


async def teardown_branch_exposure(server_id: str, branch_name: str) -> None:
    """Tear down any active cloudflared / UPnP exposure on branch stop or destroy."""
    b = (branch_name or "main").strip() or "main"
    if b == "main":
        return

    sup_key = _exposure_supervisor_key(server_id, b)
    supervisor = get_server_cloudflared_supervisor(sup_key)
    try:
        if supervisor.is_running:
            await supervisor.stop()
    except Exception:
        logger.warning("Failed to stop branch cloudflared supervisor for %s", sup_key)

    from app.modules.exposure.domain.events import BranchExposureDisabledEvent

    try:
        async with UnitOfWork() as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(server_id, branch_name=b)
            if exposure is None or exposure.desired_state == DesiredState.DISABLED:
                return
            upnp_ports: list[tuple[int, str]] = []
            if exposure.method == ExposureMethod.PORT_FORWARD:
                for target in exposure.targets:
                    upnp_ports.append(
                        (_extract_target_external_port(target), target.protocol.value.upper())
                    )
            exposure.disable()
            for target in exposure.targets:
                target.mark_disabled()
            _fold_aggregate(exposure)
            await repo.save(exposure)
            uow.add_event(BranchExposureDisabledEvent(server_id=server_id, branch_name=b))
            await uow.commit()

        for port, proto in upnp_ports:
            try:
                await AsyncUPnPService().delete_mapping(port, protocol=proto)
            except Exception:
                logger.warning(
                    "Failed deleting UPnP mapping port %s/%s for %s:%s", port, proto, server_id, b
                )
    except Exception:
        logger.exception("Failed tearing down branch exposure for %s:%s", server_id, b)


async def _sync_server_playit_targets(
    server_id: str,
    exposure: ServerExposure,
    secret_bytes: bytes,
) -> None:
    """Discover or create real playit.gg tunnels for server exposure targets."""
    secret_hex = secret_bytes.decode("utf-8")
    api_client = PlayitApiClient()
    rundata = None
    try:
        rundata = await api_client.get_rundata(secret_hex)
    except Exception as exc:
        logger.warning("Failed to query playit rundata for server %s: %s", server_id, exc)

    existing_tunnels = rundata.tunnels if rundata else []

    for target in exposure.targets:
        # 1. Match existing tunnel
        matched = None

        for t in existing_tunnels:
            if (
                t.local_port == target.local_port
                and t.port_type in (target.protocol.value, "both")
                and not t.is_disabled
            ):
                matched = t
                break

        if matched is not None and matched.display_address:
            target.playit_tunnel_id = matched.id
            target.mark_active(matched.display_address)
        else:
            # 2. Attempt creation via API
            try:
                tunnel_type = (
                    "minecraft-java"
                    if target.service_type == ServiceType.JAVA
                    else (
                        "minecraft-bedrock" if target.service_type == ServiceType.BEDROCK else None
                    )
                )
                new_t = await api_client.create_tunnel(
                    secret=secret_hex,
                    name=f"{IDENTITY.temp_prefix_new}{server_id[:6]}-{target.service_type.value[:8]}",
                    local_ip="127.0.0.1",
                    local_port=target.local_port,
                    port_type=target.protocol.value,
                    tunnel_type=tunnel_type,
                )
                if new_t.display_address:
                    target.playit_tunnel_id = new_t.id
                    target.mark_active(new_t.display_address)
                else:
                    target.mark_starting()
                    target.set_error(
                        "PLAYIT_TUNNEL_CREATION_PENDING",
                        "Tunnel creation pending on playit.gg. "
                        "The panel will auto-detect it once created.",
                    )
            except PlayitAllocationFullError:
                target.mark_starting()
                target.set_error(
                    "PLAYIT_ALLOCATION_FULL",
                    "playit.gg tunnel allocation limit reached. Manage tunnels on playit.gg.",
                )
            except Exception as exc:
                logger.warning(
                    "Auto playit tunnel creation failed for server target %s: %s", target.id, exc
                )
                target.mark_starting()
                target.set_error(
                    "PLAYIT_TUNNEL_CREATION_PENDING",
                    "Tunnel creation pending on playit.gg. "
                    "The panel will auto-detect it once created.",
                )


def _extract_target_external_port(target: ServerExposureTarget) -> int:
    if target.public_address and ":" in target.public_address:
        try:
            return int(target.public_address.split(":")[-1])
        except (ValueError, IndexError):
            pass
    return target.local_port


class SetServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    method: str
    desired_state: str
    cloudflare_mode: str | None = None
    cloudflare_token: str = ""
    hostname: str = ""
    subdomain_prefix: str | None = None
    base_domain: str | None = None
    srv_record_enabled: bool = False
    external_port: int | None = None
    acknowledged_warning: bool = False
    actor_id: str = ""


class SetServerExposureHandler(CommandHandler[SetServerExposureCommand]):
    """Create or update the exposure for a server or branch."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetServerExposureCommand) -> CommandResult:
        from app.core.exceptions import ConflictError

        server_id = ServerId(command.server_id)
        raw_method = command.method.lower()
        # `none` / `host_port` disable external tunnels and revert to direct host port binding.
        if raw_method in ("none", "host_port"):
            effective_desired = DesiredState.DISABLED
            method = ExposureMethod.PORT_FORWARD
        else:
            method = ExposureMethod(raw_method)
            effective_desired = DesiredState(command.desired_state.upper())

        desired = effective_desired
        post_commit: list[Callable[[], Awaitable[None]]] = []

        # Server-side warning enforcement: must run before any Cloudflare API calls or DB writes
        if (
            method == ExposureMethod.CLOUDFLARE_TCP
            and desired == DesiredState.ENABLED
            and command.cloudflare_mode != "quick"
            and not command.acknowledged_warning
        ):
            raise WarningNotAcknowledgedError()

        ctx_info: dict[str, Any] = {}
        async with UnitOfWork(self._event_bus) as uow:
            if desired == DesiredState.ENABLED:
                await require_password_configured_for_exposure(
                    uow.session, action=f"server_exposure:{method.value}"
                )

            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            ctx_info = await resolve_server_branch_exposure_context(
                uow.session, server, command.branch_name
            )
            eff_branch = ctx_info["branch_name"]
            target_game_port = ctx_info["game_port"]
            sup_key = _exposure_supervisor_key(command.server_id, eff_branch)

            exposure = await repo.get(command.server_id, branch_name=eff_branch)
            prev_method = exposure.method if exposure else None
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    branch_name=eff_branch,
                    method=method,
                    id=str(uuid.uuid4().hex),
                )
            else:
                exposure.set_method(method)

            if desired == DesiredState.ENABLED:
                if ctx_info["is_branch"] and target_game_port is None:
                    raise ConflictError(
                        f"Branch '{eff_branch}' container is not provisioned yet. "
                        "Create and start the branch container to allocate an isolated "
                        "port before enabling external tunnels.",
                        code="BRANCH_CONTAINER_NOT_PROVISIONED",
                    )
                assert target_game_port is not None

                # Update branch target ports if branch runtime port changed cleanly
                if ctx_info["is_branch"]:
                    stale_targets = [
                        t
                        for t in exposure.targets
                        if t.service_type == ServiceType.JAVA and t.local_port != target_game_port
                    ]
                    for st in stale_targets:
                        exposure.remove_target(st.id or "")

                if not exposure.targets:
                    exposure.enable(
                        server_port=target_game_port,
                        target_id=str(uuid.uuid4().hex),
                    )
                if not exposure.targets:
                    raise NoTargetsError()
                ports_repo = SQLServerRegisteredPortRepository(uow.session)
                for target in exposure.targets:
                    reg_port = None
                    if target.service_type != ServiceType.JAVA:
                        reg_model = await ports_repo.get_by_service_type(
                            command.server_id, target.service_type.value
                        )
                        reg_port = reg_model.port if reg_model else None
                    exposure.validate_target_port(
                        local_port=target.local_port,
                        server_port=target_game_port,
                        service_type=target.service_type,
                        registered_port=reg_port,
                    )
                exposure.set_desired_state(DesiredState.ENABLED)

                sub_prefix = command.subdomain_prefix.strip() if command.subdomain_prefix else None
                base_dom = command.base_domain.strip() if command.base_domain else None
                cf_mode = command.cloudflare_mode

                if method == ExposureMethod.PORT_FORWARD:
                    if prev_method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(get_server_cloudflared_supervisor(sup_key).stop)
                    exposure.set_branch_routing(
                        cloudflare_mode=None,
                        subdomain_prefix=sub_prefix,
                        base_domain=base_dom,
                        srv_record_enabled=bool(command.srv_record_enabled),
                        ephemeral=False,
                    )
                    for target in exposure.targets:
                        target.mark_starting()

                    ext_port_req = command.external_port
                    sub_fqdn = f"{sub_prefix}.{base_dom}" if (sub_prefix and base_dom) else None

                    async def _run_server_upnp(
                        exp_ref=exposure,
                        ep_req=ext_port_req,
                        fqdn=sub_fqdn,
                        sid=command.server_id,
                    ):
                        for target in exp_ref.targets:
                            await _attempt_server_upnp_mapping(
                                sid,
                                target,
                                external_port=ep_req,
                                subdomain_host=fqdn,
                            )
                        _fold_aggregate(exp_ref)
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLServerExposureRepository(post_uow.session)
                            await p_repo.save(exp_ref)
                            await post_uow.commit()

                    post_commit.append(_run_server_upnp)
                elif method == ExposureMethod.PLAYIT:
                    if prev_method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    if prev_method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(get_server_cloudflared_supervisor(sup_key).stop)

                    exposure.set_branch_routing(
                        cloudflare_mode=None,
                        subdomain_prefix=sub_prefix,
                        base_domain=base_dom,
                        srv_record_enabled=False,
                        ephemeral=False,
                    )
                    agent = await agent_repo.get()
                    supervisor = get_playit_supervisor()
                    if agent.is_claimed and agent.secret_ciphertext:
                        agent.set_desired_agent_running(True)
                        await agent_repo.save(agent)
                        try:
                            secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                            for target in exposure.targets:
                                target.mark_starting()

                            async def _run_server_playit(
                                s=secret_bytes, exp_ref=exposure, sid=command.server_id
                            ):
                                await _sync_server_playit_targets(sid, exp_ref, s)
                                _fold_aggregate(exp_ref)
                                async with UnitOfWork() as post_uow:
                                    p_repo = SQLServerExposureRepository(post_uow.session)
                                    await p_repo.save(exp_ref)
                                    await post_uow.commit()
                                await supervisor.start(
                                    s,
                                    on_status=_persist_playit_status,
                                    on_reconcile=_reconcile_playit_tunnels,
                                )

                            post_commit.append(_run_server_playit)
                        except Exception:
                            for target in exposure.targets:
                                target.mark_reclaim_required(
                                    code="RECLAIM_REQUIRED",
                                    message="Stored playit agent secret cannot be decrypted",
                                )
                    else:
                        for target in exposure.targets:
                            target._transition_to(ExposureStatus.CLAIM_REQUIRED)
                            target.set_error(
                                "CLAIM_REQUIRED",
                                "playit.gg host agent claim required before tunnel activation",
                            )
                        post_commit.append(
                            lambda: supervisor.start(None, on_status=_persist_playit_status)
                        )

                elif method == ExposureMethod.CLOUDFLARE_TCP:
                    if prev_method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    exposure.set_branch_routing(
                        cloudflare_mode=cf_mode,
                        subdomain_prefix=sub_prefix,
                        base_domain=base_dom,
                        srv_record_enabled=False,
                        ephemeral=(cf_mode == "quick"),
                    )
                    await self._enable_server_cloudflare_tcp(
                        exposure=exposure,
                        command=command,
                        post_commit=post_commit,
                    )
            else:
                exposure.set_desired_state(DesiredState.DISABLED)
                exposure.set_branch_routing(
                    cloudflare_mode=None,
                    subdomain_prefix=exposure.subdomain_prefix,
                    base_domain=exposure.base_domain,
                    srv_record_enabled=exposure.srv_record_enabled,
                    ephemeral=False,
                )
                if (
                    prev_method == ExposureMethod.PORT_FORWARD
                    or method == ExposureMethod.PORT_FORWARD
                ):
                    for target in exposure.targets:
                        p = _extract_target_external_port(target)
                        proto = target.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                port, protocol=pr
                            )
                        )
                if (
                    prev_method == ExposureMethod.CLOUDFLARE_TCP
                    or method == ExposureMethod.CLOUDFLARE_TCP
                ):
                    post_commit.append(get_server_cloudflared_supervisor(sup_key).stop)

                for target in exposure.targets:
                    target.mark_disabled()

            _fold_aggregate(exposure)
            await repo.save(exposure)

            agent = await agent_repo.get()
            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(
            success=True,
            data=_exposure_payload(exposure, branch_context=ctx_info),
        )

    async def _start_server_supervisor(
        self,
        supervisor: CloudflaredSupervisor,
        token: bytes,
        on_status: Callable[[ExposureStatus], Awaitable[None]],
    ) -> None:
        if supervisor.is_running:
            await supervisor.stop()
        await supervisor.start(token, on_status=on_status)

    async def _enable_server_cloudflare_tcp(
        self,
        exposure: ServerExposure,
        command: SetServerExposureCommand | EnableServerExposureCommand,
        post_commit: list[Callable[[], Awaitable[None]]],
    ) -> None:
        for target in exposure.targets:
            if target.protocol == TargetProtocol.UDP:
                raise MethodProtocolIncompatibleError(
                    "Cloudflare TCP exposure does not support UDP targets (Bedrock / Voice Chat). "
                    "Use playit.gg or Port Forwarding instead."
                )

        token = command.cloudflare_token.strip()
        hostname = command.hostname.strip()
        if not hostname and getattr(command, "subdomain_prefix", None) and getattr(
            command, "base_domain", None
        ):
            hostname = f"{command.subdomain_prefix.strip()}.{command.base_domain.strip()}"

        sup_key = _exposure_supervisor_key(exposure.server_id, exposure.branch_name)
        supervisor = get_server_cloudflared_supervisor(sup_key)
        on_status = _make_persist_server_cloudflare_status(
            exposure.server_id, branch_name=exposure.branch_name
        )

        # Case 0: Ephemeral Cloudflare Quick Tunnel (branch preview)
        if getattr(command, "cloudflare_mode", None) == "quick":
            target_port = exposure.targets[0].local_port
            if not CloudflaredSupervisor.is_installed():
                for target in exposure.targets:
                    target.mark_error(
                        code="CLOUDFLARED_NOT_FOUND",
                        message="cloudflared binary is not installed on this host.",
                    )
                return

            exposure.set_branch_routing(
                cloudflare_mode="quick",
                subdomain_prefix=None,
                base_domain=None,
                srv_record_enabled=False,
                ephemeral=True,
            )
            for target in exposure.targets:
                target.mark_starting()

            async def _run_branch_quick(p=target_port, sup=supervisor, cb=on_status):
                async def _on_quick_url(url: str) -> None:
                    async with UnitOfWork() as uow:
                        r = SQLServerExposureRepository(uow.session)
                        exp = await r.get(exposure.server_id, branch_name=exposure.branch_name)
                        if exp is not None:
                            for t in exp.targets:
                                t.mark_active(url)
                            _fold_aggregate(exp)
                            await r.save(exp)
                            await uow.commit()

                await sup.start_quick(
                    f"http://127.0.0.1:{p}",
                    on_status=cb,
                    on_url=_on_quick_url,
                )

            post_commit.append(_run_branch_quick)
            return

        # Case 1: Token provided
        if token:
            # Subcase 1a: Tunnel already exists -> Token Rotation
            if exposure.cloudflare_tunnel_id:
                fallback = exposure.targets[0].public_address if exposure.targets else ""
                resolved_hostname = hostname or fallback
                if not resolved_hostname:
                    raise ValidationError(
                        "Hostname is required for Cloudflare TCP exposure",
                        field="hostname",
                    )
                ciphertext = _panel_encryption().encrypt(token.encode("utf-8"))
                exposure.set_cloudflare_credentials(exposure.cloudflare_tunnel_id, ciphertext)
                for target in exposure.targets:
                    target.mark_starting()
                    target.set_public_address(target.public_address or resolved_hostname)
                token_bytes = token.encode("utf-8")
                post_commit.append(
                    lambda t=token_bytes: self._start_server_supervisor(supervisor, t, on_status)
                )
                return

            # Subcase 1b: Fresh setup
            if not hostname:
                raise ValidationError(
                    "Hostname is required for Cloudflare TCP exposure",
                    field="hostname",
                )

            for target in exposure.targets:
                target.mark_starting()
                target.set_public_address(target.public_address or hostname)

            async def _run_fresh_cloudflare(tok=token, host=hostname):
                client = CloudflareClient(tok)
                ingress_rules: list[dict[str, str]] = []
                for target in exposure.targets:
                    target_host = target.public_address or host
                    ingress_rules.append(
                        {"hostname": target_host, "service": f"tcp://127.0.0.1:{target.local_port}"}
                    )
                ingress_rules.append({"service": "http_status:404"})

                try:
                    tunnel_name = f"{IDENTITY.temp_prefix_new}srv-{exposure.server_id[:8]}"
                    provisioned = await client.create_named_tunnel(name=tunnel_name)
                    await client.configure_ingress(provisioned.tunnel_id, ingress_rules)
                    for target in exposure.targets:
                        target_host = target.public_address or host
                        await client.create_cname(target_host, provisioned.tunnel_id)
                except CloudflareAuthError as exc:
                    for target in exposure.targets:
                        target.mark_reclaim_required(code="RECLAIM_REQUIRED", message=str(exc))
                    exposure.clear_cloudflare_credentials()
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()
                    return
                except CloudflareApiError as exc:
                    for target in exposure.targets:
                        target.mark_error(code="CLOUDFLARE_API_ERROR", message=str(exc))
                    exposure.clear_cloudflare_credentials()
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()
                    return

                ciphertext = _panel_encryption().encrypt(provisioned.token.encode("utf-8"))
                exposure.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
                for target in exposure.targets:
                    target.mark_starting()
                    target.set_public_address(target.public_address or host)

                _fold_aggregate(exposure)
                async with UnitOfWork() as post_uow:
                    p_repo = SQLServerExposureRepository(post_uow.session)
                    await p_repo.save(exposure)
                    await post_uow.commit()

                token_bytes = provisioned.token.encode("utf-8")
                await self._start_server_supervisor(supervisor, token_bytes, on_status)

            post_commit.append(_run_fresh_cloudflare)
            return

        # Case 2: No token provided (reuse existing stored credentials)
        if exposure.has_cloudflare_credentials and exposure.cloudflare_token_ciphertext:
            for target in exposure.targets:
                target.mark_starting()
                if not target.public_address and hostname:
                    target.set_public_address(hostname)
            try:
                plaintext = _panel_encryption().decrypt(exposure.cloudflare_token_ciphertext)
                post_commit.append(
                    lambda t=plaintext: self._start_server_supervisor(supervisor, t, on_status)
                )
            except Exception:
                for target in exposure.targets:
                    target.mark_reclaim_required(
                        code="RECLAIM_REQUIRED",
                        message="Stored Cloudflare credentials cannot be decrypted",
                    )
                exposure.clear_cloudflare_credentials()
            return

        # Case 3: No token and no existing credentials
        raise ValidationError(
            "Cloudflare API token is required for Cloudflare TCP exposure",
            field="cloudflare_token",
        )


class EnableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    cloudflare_token: str = ""
    hostname: str = ""
    acknowledged_warning: bool = False
    actor_id: str = ""
    desired_state: str = "ENABLED"


class EnableServerExposureHandler(CommandHandler[EnableServerExposureCommand]):
    """Enable exposure (route #11). Auto-creates java/tcp target from game port."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: EnableServerExposureCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            await require_password_configured_for_exposure(
                uow.session, action="server_exposure:enable"
            )

            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            exposure = await repo.get(command.server_id, branch_name=command.branch_name)
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    branch_name=command.branch_name,
                    method=ExposureMethod.PLAYIT,
                    id=str(uuid.uuid4().hex),
                )

            # Warning check if method is CLOUDFLARE_TCP
            if (
                exposure.method == ExposureMethod.CLOUDFLARE_TCP
                and not command.acknowledged_warning
            ):
                raise WarningNotAcknowledgedError()

            game_port = server.properties.port.value
            exposure.enable(
                server_port=game_port,
                target_id=str(uuid.uuid4().hex),
            )

            agent = await agent_repo.get()
            supervisor = get_playit_supervisor()

            if exposure.method == ExposureMethod.PORT_FORWARD:
                for t in exposure.targets:
                    t.mark_starting()

                async def _run_enable_upnp():
                    for t in exposure.targets:
                        await _attempt_server_upnp_mapping(command.server_id, t)
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()

                post_commit.append(_run_enable_upnp)
            elif exposure.method == ExposureMethod.PLAYIT:
                if agent.is_claimed and agent.secret_ciphertext:
                    agent.set_desired_agent_running(True)
                    await agent_repo.save(agent)
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        for t in exposure.targets:
                            t.mark_starting()

                        async def _run_enable_playit(s=secret_bytes):
                            await _sync_server_playit_targets(command.server_id, exposure, s)
                            _fold_aggregate(exposure)
                            async with UnitOfWork() as post_uow:
                                p_repo = SQLServerExposureRepository(post_uow.session)
                                await p_repo.save(exposure)
                                await post_uow.commit()
                            await supervisor.start(
                                s,
                                on_status=_persist_playit_status,
                                on_reconcile=_reconcile_playit_tunnels,
                            )

                        post_commit.append(_run_enable_playit)

                    except Exception:
                        for t in exposure.targets:
                            t.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="Stored playit agent secret cannot be decrypted",
                            )
                else:
                    for t in exposure.targets:
                        t._transition_to(ExposureStatus.CLAIM_REQUIRED)
                        t.set_error(
                            "CLAIM_REQUIRED",
                            "playit.gg host agent claim required before tunnel activation",
                        )
                    post_commit.append(
                        lambda: supervisor.start(None, on_status=_persist_playit_status)
                    )

            elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                handler = SetServerExposureHandler(self._event_bus)
                set_cmd = SetServerExposureCommand(
                    server_id=command.server_id,
                    method=ExposureMethod.CLOUDFLARE_TCP.value,
                    desired_state="ENABLED",
                    cloudflare_token=command.cloudflare_token,
                    hostname=command.hostname,
                    acknowledged_warning=command.acknowledged_warning,
                )
                await handler._enable_server_cloudflare_tcp(
                    exposure=exposure,
                    command=set_cmd,
                    post_commit=post_commit,
                )

            _fold_aggregate(exposure)
            await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        payload = _exposure_payload(exposure)
        payload["target"] = payload["targets"][-1] if payload["targets"] else None
        return CommandResult(success=True, data=payload)


class DisableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    actor_id: str = ""


class DisableServerExposureHandler(CommandHandler[DisableServerExposureCommand]):
    """Disable exposure (route #11)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DisableServerExposureCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposure = await repo.get(command.server_id, branch_name=command.branch_name)
            if exposure is None:
                raise NotFoundError(f"Exposure not found for server {command.server_id}")
            sup_key = _exposure_supervisor_key(command.server_id, exposure.branch_name)
            if exposure.desired_state == DesiredState.ENABLED:
                if exposure.method == ExposureMethod.PORT_FORWARD:
                    for target in exposure.targets:
                        p = _extract_target_external_port(target)
                        proto = target.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                port, protocol=pr
                            )
                        )
                elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                    post_commit.append(get_server_cloudflared_supervisor(sup_key).stop)
                elif (
                    exposure.method == ExposureMethod.PLAYIT
                    and agent.is_claimed
                    and agent.secret_ciphertext
                ):
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        secret_hex = secret_bytes.decode("utf-8")
                        api_client = PlayitApiClient()
                        for target in exposure.targets:
                            if target.playit_tunnel_id:
                                post_commit.append(
                                    lambda s=secret_hex, tid=target.playit_tunnel_id: (
                                        api_client.delete_tunnel(s, tid)
                                    )
                                )
                    except Exception as exc:
                        logger.warning(
                            "Could not queue playit tunnel deletion on server disable: %s", exc
                        )
                exposure.disable()
                for target in exposure.targets:
                    target.mark_disabled()
            _fold_aggregate(exposure)
            await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(success=True, data=_exposure_payload(exposure))


class RemoveServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    actor_id: str = ""


class RemoveServerExposureHandler(CommandHandler[RemoveServerExposureCommand]):
    """Remove exposure config entirely (route #12, idempotent 204)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RemoveServerExposureCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposure = await repo.get(command.server_id, branch_name=command.branch_name)
            if exposure is None:
                return CommandResult(success=True, data={"removed": False})
            sup_key = _exposure_supervisor_key(command.server_id, exposure.branch_name)

            if exposure.method == ExposureMethod.PORT_FORWARD:
                for target in exposure.targets:
                    p = _extract_target_external_port(target)
                    proto = target.protocol.value.upper()
                    post_commit.append(
                        lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                            port, protocol=pr
                        )
                    )
            elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                post_commit.append(get_server_cloudflared_supervisor(sup_key).stop)
            elif (
                exposure.method == ExposureMethod.PLAYIT
                and agent.is_claimed
                and agent.secret_ciphertext
            ):
                try:
                    secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                    secret_hex = secret_bytes.decode("utf-8")
                    api_client = PlayitApiClient()
                    for target in exposure.targets:
                        if target.playit_tunnel_id:
                            post_commit.append(
                                lambda s=secret_hex, tid=target.playit_tunnel_id: (
                                    api_client.delete_tunnel(s, tid)
                                )
                            )
                except Exception as exc:
                    logger.warning(
                        "Could not queue playit tunnel deletion on server remove: %s", exc
                    )
            exposure.mark_deleted()
            await repo.delete(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(success=True, data={"removed": True})


class CreateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    service_type: str = "java"
    protocol: str | None = None
    local_port: int | None = None
    public_address: str | None = None
    actor_id: str = ""


class CreateExposureTargetHandler(CommandHandler[CreateExposureTargetCommand]):
    """Create a target for a server exposure (route #14). Validates port + deny-list."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateExposureTargetCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(ServerId(command.server_id))
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            exposure = await repo.get(command.server_id, branch_name=command.branch_name)
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    branch_name=command.branch_name,
                    method=ExposureMethod.PLAYIT,
                    id=str(uuid.uuid4().hex),
                )

            st = _coerce_service_type(command.service_type)

            if st == ServiceType.JAVA:
                proto = TargetProtocol.TCP
                if command.protocol and _coerce_protocol(command.protocol) != proto:
                    raise InvalidValueError(
                        field="protocol",
                        value=command.protocol,
                        reason="Java target requires TCP protocol",
                    )
                port = server.properties.port.value
                if command.local_port is not None and command.local_port != port:
                    raise InvalidValueError(
                        field="local_port",
                        value=command.local_port,
                        reason=f"Java target port must equal server game port ({port})",
                    )
                registered_port = None
            else:
                registered = await ports_repo.get_by_service_type(command.server_id, st.value)
                if registered is None:
                    raise UnregisteredPortError(
                        f"Service type {st.value} has no registered port "
                        f"for server {command.server_id}"
                    )
                registered_port = registered.port
                port = command.local_port if command.local_port is not None else registered.port
                proto = (
                    _coerce_protocol(command.protocol)
                    if command.protocol
                    else _coerce_protocol(registered.protocol)
                )

            # Fail-fast check if method is CLOUDFLARE_TCP and protocol is UDP
            if exposure.method == ExposureMethod.CLOUDFLARE_TCP and proto == TargetProtocol.UDP:
                raise MethodProtocolIncompatibleError()

            target = exposure.create_target(
                local_port=port,
                server_port=server.properties.port.value,
                target_id=str(uuid.uuid4().hex),
                service_type=st,
                protocol=proto,
                registered_port=registered_port,
            )
            if command.public_address:
                val = command.public_address.strip()
                if not re.match(r"^[a-zA-Z0-9.-]+(:\d{1,5})?$", val):
                    raise ValidationError("Invalid public address format")
                target.set_public_address(val)

            if (
                exposure.desired_state == DesiredState.ENABLED
                and exposure.method == ExposureMethod.PORT_FORWARD
            ):
                await _attempt_server_upnp_mapping(command.server_id, target)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_target_payload(target))


class UpdateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    branch_name: str = "main"
    target_id: str
    public_address: str | None = None
    actor_id: str = ""


class UpdateExposureTargetHandler(CommandHandler[UpdateExposureTargetCommand]):
    """Update an existing exposure target (e.g. manual public_address entry)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateExposureTargetCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(command.server_id, branch_name=command.branch_name)
            if exposure is None:
                raise NotFoundError(f"Exposure for server {command.server_id} not found")

            target = next((t for t in exposure.targets if t.id == command.target_id), None)
            if target is None:
                raise NotFoundError(
                    f"Target {command.target_id} not found on server {command.server_id}"
                )

            if command.public_address:
                val = command.public_address.strip()
                if not re.match(r"^[a-zA-Z0-9.-]+(:\d{1,5})?$", val):
                    raise ValidationError("Invalid public address format")
                target.set_public_address(val)
            else:
                target.set_public_address(None)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_target_payload(target))


class RegisterServerPortCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    service_type: str
    protocol: str
    port: int
    name: str | None = None
    actor_id: str = ""


class RegisterServerPortHandler(CommandHandler[RegisterServerPortCommand]):
    """Register a companion service port for a server."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RegisterServerPortCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(ServerId(command.server_id))
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            st = _coerce_service_type(command.service_type)
            if st == ServiceType.JAVA:
                raise InvalidServiceTypeError(
                    "Java primary port cannot be registered in server_registered_ports "
                    "(managed via ServerModel.port)"
                )

            proto = _coerce_protocol(command.protocol)

            affinity_map = {
                ServiceType.BEDROCK: TargetProtocol.UDP,
                ServiceType.VOICE: TargetProtocol.UDP,
                ServiceType.BLUEMAP: TargetProtocol.TCP,
            }
            expected_proto = affinity_map.get(st, TargetProtocol.TCP)
            if expected_proto != proto:
                raise InvalidValueError(
                    field="protocol",
                    value=proto.value,
                    reason=f"Service type {st.value} requires protocol {expected_proto.value}",
                )

            if command.port < 1 or command.port > 65535:
                raise InvalidValueError(
                    field="port",
                    value=command.port,
                    reason="Port must be between 1 and 65535",
                )

            if command.port in DENY_LIST_PORTS:
                raise InvalidValueError(
                    field="port",
                    value=command.port,
                    reason="Port is on the deny-list (management/RCON/DB/metrics)",
                )

            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            existing_type = await ports_repo.get_by_service_type(command.server_id, st.value)
            if existing_type is not None:
                raise PortAlreadyRegisteredError(
                    f"A port for service type {st.value} is already registered on this server"
                )

            existing_port = await ports_repo.get_by_port_protocol(
                command.server_id, command.port, proto.value
            )
            if existing_port is not None:
                raise PortAlreadyRegisteredError(
                    f"Port {command.port}/{proto.value} is already registered on this server"
                )

            model = ServerRegisteredPortModel(
                id=uuid.uuid4().hex,
                server_id=command.server_id,
                service_type=st.value,
                protocol=proto.value,
                port=command.port,
                name=command.name,
            )
            await ports_repo.save(model)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "id": model.id,
                "server_id": model.server_id,
                "service_type": model.service_type,
                "protocol": model.protocol,
                "port": model.port,
                "name": model.name,
                "created_at": model.created_at.isoformat() if model.created_at else None,
                "updated_at": model.updated_at.isoformat() if model.updated_at else None,
            },
        )


class DeleteServerPortCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    port_id: str
    actor_id: str = ""


class DeleteServerPortHandler(CommandHandler[DeleteServerPortCommand]):
    """Delete a registered companion port and clean up associated exposure target."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteServerPortCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            port_model = await ports_repo.get(command.port_id)
            if port_model is None or port_model.server_id != command.server_id:
                raise NotFoundError(
                    f"Registered port {command.port_id} not found on server {command.server_id}"
                )

            st = port_model.service_type
            await ports_repo.delete(command.port_id)

            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(command.server_id)
            if exposure:
                target_to_remove = next(
                    (t for t in exposure.targets if t.service_type.value == st), None
                )
                if target_to_remove:
                    if (
                        exposure.desired_state == DesiredState.ENABLED
                        and exposure.method == ExposureMethod.PORT_FORWARD
                    ):
                        p = _extract_target_external_port(target_to_remove)
                        pr = target_to_remove.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, proto=pr: AsyncUPnPService().delete_mapping(
                                port, protocol=proto
                            )
                        )
                    elif (
                        exposure.method == ExposureMethod.PLAYIT
                        and target_to_remove.playit_tunnel_id
                    ):
                        agent_repo = SQLHostAgentRepository(uow.session)
                        agent = await agent_repo.get()
                        if agent.is_claimed and agent.secret_ciphertext:
                            try:
                                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                                secret_hex = secret_bytes.decode("utf-8")
                                api_client = PlayitApiClient()
                                post_commit.append(
                                    lambda s=secret_hex, tid=target_to_remove.playit_tunnel_id: (
                                        api_client.delete_tunnel(s, tid)
                                    )
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Could not queue playit tunnel deletion on port delete: %s", exc
                                )
                    exposure.remove_target(target_to_remove.id)
                    _fold_aggregate(exposure)
                    await repo.save(exposure)

            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit registered port cleanup failed")

        return CommandResult(success=True, data={"deleted": True})


class StopAllExposuresCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class StopAllExposuresHandler(CommandHandler[StopAllExposuresCommand]):
    """Disable all exposures, keep credentials (route #5)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: StopAllExposuresCommand) -> CommandResult:
        count = 0
        post_commit: list[Callable[[], Awaitable[None]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposures = await repo.list()
            for exposure in exposures:
                if exposure.desired_state == DesiredState.ENABLED:
                    if exposure.method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(
                            get_server_cloudflared_supervisor(exposure.server_id).stop
                        )
                    exposure.disable()
                    for target in exposure.targets:
                        target.mark_disabled()
                    _fold_aggregate(exposure)
                    await repo.save(exposure)
                    for event in exposure.collect_events():
                        uow.add_event(event)
                    count += 1

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit playit stop failed")

        return CommandResult(success=True, data={"disabled_count": count})


class GenerateClaimCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""
    claim_code: str = ""
    claim_url: str = ""
    force: bool = False


class GenerateClaimHandler(CommandHandler[GenerateClaimCommand]):
    """Generate a playit agent claim (route #2). 409 if active claim."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: GenerateClaimCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            await require_password_configured_for_exposure(
                uow.session, action="exposure_agent_claim"
            )

            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()

            if agent.has_active_claim and not command.force:
                raise ClaimActiveError()

            if command.claim_code:
                claim_code = command.claim_code
                claim_url = command.claim_url or f"https://playit.gg/claim/{claim_code}"
            else:
                claim_code, claim_url = await generate_playit_claim_code()

            expires_at = datetime.now(UTC) + timedelta(minutes=CLAIM_TTL_MINUTES)
            agent.generate_claim(claim_code, expires_at)
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        # Start supervisor in background claim exchange mode with the real claim code
        supervisor = get_playit_supervisor()
        try:
            await supervisor.start(
                claim_code=claim_code,
                on_secret=_handle_playit_claimed_secret,
            )
        except Exception:
            logger.warning(
                "Failed to start playit supervisor in claim exchange mode", exc_info=True
            )

        return CommandResult(
            success=True,
            data={
                "claim_code": claim_code,
                "claim_url": claim_url,
                "expires_at": expires_at.isoformat(),
            },
        )


class ResetAgentCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class ResetAgentHandler(CommandHandler[ResetAgentCommand]):
    """Reset the host agent (route #3). Clears secret; targets → CLAIM_REQUIRED."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ResetAgentCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[Any]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.reset()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        post_commit.append(get_playit_supervisor().stop)
        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.warning("Error executing post-commit action", exc_info=True)

        return CommandResult(success=True, data=_agent_payload(agent))


class RemoveCredentialsCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class RemoveCredentialsHandler(CommandHandler[RemoveCredentialsCommand]):
    """Wipe agent credentials (route #6)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: RemoveCredentialsCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[Any]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.remove_credentials()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        post_commit.append(get_playit_supervisor().stop)
        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.warning("Error executing post-commit action", exc_info=True)

        return CommandResult(success=True, data={"success": True})


class SetPanelExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    method: str
    desired_state: str
    cloudflare_mode: str | None = None
    cloudflare_token: str = ""
    hostname: str = ""
    external_port: int | None = None
    actor_id: str = ""


def _panel_encryption():
    settings = ConfigFactory.global_settings()
    return build_backup_encryption(settings.backup_encryption_key_path or None)


def _is_loopback_bind_host(host: str) -> bool:
    """Return True if *host* represents a loopback-only bind address."""
    normalized = (host or "").strip().lower()
    return normalized in ("127.0.0.1", "localhost", "::1") or normalized.startswith("127.")


def _restore_loopback_panel_bind() -> None:
    """Restore ``panel_bind_host`` to ``127.0.0.1`` when leaving port forwarding.

    Cloudflare Tunnel and playit.gg agents run locally and connect to loopback
    without exposing the panel directly on LAN/WAN interfaces (security invariant).
    Only persists when currently set to ``0.0.0.0`` so unit tests with default
    config do not rewrite disk settings unnecessarily.
    """
    from app.core.settings_store import get_live_settings
    from app.core.settings_store import update_settings as update_settings_store

    live = get_live_settings()
    if (live.panel_bind_host or "").strip() == "0.0.0.0":
        update_settings_store({"panel_bind_host": "127.0.0.1"})


def _looks_like_tunnel_token(token: str) -> bool:
    """Return True if *token* matches a Cloudflare Tunnel connector JWT (eyJ...)."""
    clean = token.strip()
    return clean.startswith("eyJ") and len(clean) >= 32 and not any(c.isspace() for c in clean)


class SetPanelExposureHandler(CommandHandler[SetPanelExposureCommand]):
    """Set panel exposure method + desired_state (route #8).

    Supports:
      - ``cloudflare_tunnel``: Permanent Mode (Tunnel Token via ``TUNNEL_TOKEN`` env),
        Quick Preview Mode (ephemeral ``trycloudflare.com`` URL), or legacy named tunnel API.
      - ``playit_http``: HTTP edge tunnel via PlayitAgentSupervisor.
      - ``port_forward``: Local IGD port mapping via AsyncUPnPService with CGNAT detection.
      - ``none``: Disables and tears down any active panel exposure and restores 127.0.0.1 bind.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetPanelExposureCommand) -> CommandResult:
        method = PanelExposureMethod(command.method.lower())
        desired = DesiredState(command.desired_state.upper())
        requested_cf_mode = (command.cloudflare_mode or "").strip().lower() or None
        if requested_cf_mode is not None and requested_cf_mode not in ("token", "quick"):
            raise ValidationError("cloudflare_mode must be 'token' or 'quick'")

        post_commit: list[callable] = []

        async with UnitOfWork(self._event_bus) as uow:
            if desired == DesiredState.ENABLED and method != PanelExposureMethod.NONE:
                await require_password_configured_for_exposure(
                    uow.session, action=f"panel_exposure:{method.value}"
                )

            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            state_repo = SQLSystemStateRepository(uow.session)
            panel = await repo.get()
            system_state = await state_repo.get()
            access_mode = system_state.access_mode

            # Evaluate idempotency while allowing retries from ERROR/STOPPED,
            # RECLAIM_REQUIRED credential rotation, port changes, and Cloudflare mode switches.
            if panel.method == method and panel.desired_state == desired:
                is_reclaim_rotation = (
                    method == PanelExposureMethod.CLOUDFLARE_TUNNEL
                    and desired == DesiredState.ENABLED
                    and panel.status == ExposureStatus.RECLAIM_REQUIRED
                    and bool((command.cloudflare_token or "").strip())
                )
                is_error_retry = desired == DesiredState.ENABLED and panel.status in (
                    ExposureStatus.ERROR,
                    ExposureStatus.STOPPED,
                    ExposureStatus.DISABLED,
                )
                is_port_change = (
                    method == PanelExposureMethod.PORT_FORWARD
                    and desired == DesiredState.ENABLED
                    and command.external_port is not None
                    and command.external_port != panel.external_port
                )
                current_cf_mode = (
                    "quick" if panel.cloudflare_tunnel_id == "quick" else "token"
                )
                is_cf_mode_switch = (
                    method == PanelExposureMethod.CLOUDFLARE_TUNNEL
                    and desired == DesiredState.ENABLED
                    and (
                        (requested_cf_mode is not None and requested_cf_mode != current_cf_mode)
                        or requested_cf_mode == "quick"
                        or (
                            requested_cf_mode == "token"
                            and (
                                bool((command.cloudflare_token or "").strip())
                                or not get_cloudflared_supervisor().is_running
                            )
                        )
                    )
                )
                if not (
                    is_reclaim_rotation
                    or is_error_retry
                    or is_port_change
                    or is_cf_mode_switch
                ):
                    return CommandResult(
                        success=True, data=_panel_payload(panel, access_mode=access_mode)
                    )

            prev_method = panel.method
            prev_ext_port = panel.external_port
            prev_playit_tunnel_id = panel.playit_tunnel_id

            # Tear down previous active method runtime process or router mapping on switch.
            if prev_method != method and method != PanelExposureMethod.NONE:
                await self._teardown_previous_panel_method(
                    uow=uow,
                    panel=panel,
                    prev_method=prev_method,
                    prev_ext_port=prev_ext_port,
                    prev_playit_tunnel_id=prev_playit_tunnel_id,
                    target_method=method,
                    post_commit=post_commit,
                )

            if method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
                if desired == DesiredState.ENABLED:
                    await self._enable_cloudflare(
                        uow, repo, panel, command, requested_cf_mode, post_commit
                    )
                else:
                    await self._disable_cloudflare(uow, repo, panel, post_commit)
            elif method == PanelExposureMethod.PLAYIT_HTTP:
                if desired == DesiredState.ENABLED:
                    await self._enable_playit_http(uow, repo, panel, post_commit)
                else:
                    await self._disable_playit_http(uow, repo, panel, post_commit)
            elif method == PanelExposureMethod.PORT_FORWARD:
                if desired == DesiredState.ENABLED:
                    await self._enable_port_forward(uow, repo, panel, command, post_commit)
                else:
                    await self._disable_port_forward(uow, repo, panel, post_commit)
            else:
                await self._disable_all_panel_methods(uow, repo, panel, post_commit)

            await repo.save(panel)
            for event in panel.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("post-commit exposure action failed")

        # Refresh panel entity if post-commit callbacks mutated it asynchronously in DB.
        if post_commit:
            async with UnitOfWork() as check_uow:
                panel = await SQLPanelExposureRepository(check_uow.session).get()

        return CommandResult(success=True, data=_panel_payload(panel, access_mode=access_mode))

    async def _teardown_previous_panel_method(
        self,
        *,
        uow: UnitOfWork,
        panel: PanelExposure,
        prev_method: PanelExposureMethod,
        prev_ext_port: int | None,
        prev_playit_tunnel_id: str | None,
        target_method: PanelExposureMethod,
        post_commit: list[callable],
    ) -> None:
        """Stop processes and router mappings left behind by the previously active method."""
        if prev_method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
            post_commit.append(self._stop_supervisor)
            panel.clear_cloudflare_credentials()
        elif prev_method == PanelExposureMethod.PORT_FORWARD:
            if prev_ext_port:
                post_commit.append(lambda p=prev_ext_port: AsyncUPnPService().delete_mapping(p))
            panel.clear_port_forward_details()
            if target_method != PanelExposureMethod.PORT_FORWARD:
                _restore_loopback_panel_bind()
        elif prev_method == PanelExposureMethod.PLAYIT_HTTP:
            agent_repo = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            if prev_playit_tunnel_id and agent.is_claimed and agent.secret_ciphertext:
                try:
                    secret_hex = _panel_encryption().decrypt(agent.secret_ciphertext).decode(
                        "utf-8"
                    )
                    api_client = PlayitApiClient()
                    post_commit.append(
                        lambda s=secret_hex, tid=prev_playit_tunnel_id: api_client.delete_tunnel(
                            s, tid
                        )
                    )
                except Exception as exc:
                    logger.warning("Could not delete previous playit panel tunnel: %s", exc)
            panel.clear_playit_credentials()
            # Ensure panel method reflects departure before checking desired agent running state.
            panel.update(target_method, DesiredState.DISABLED)
            await SQLPanelExposureRepository(uow.session).save(panel)
            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(self._stop_playit_supervisor)

    async def _enable_cloudflare(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        command: SetPanelExposureCommand,
        cloudflare_mode: str | None,
        post_commit: list[callable],
    ) -> None:
        raw_token = (command.cloudflare_token or "").strip()
        hostname = (command.hostname or "").strip().lower()

        _restore_loopback_panel_bind()
        panel.clear_playit_credentials()
        panel.clear_port_forward_details()

        # Mode 2: Quick Preview (Temporary *.trycloudflare.com URL — zero inputs)
        if cloudflare_mode == "quick":
            local_target = local_panel_ingress_target()
            panel.clear_cloudflare_credentials()
            panel.set_cloudflare_quick_mode()
            panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
            panel.set_public_address(None)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_error(None)

            async def _run_quick_cf(target=local_target) -> None:
                sup = get_cloudflared_supervisor()
                await sup.stop()
                if hasattr(sup, "start_quick"):
                    await sup.start_quick(
                        target,
                        on_status=_persist_panel_status,
                        on_url=_persist_panel_quick_url,
                    )
                else:
                    return

                # Wait briefly for immediate URL capture or missing-binary error.
                for _ in range(60):
                    if (
                        getattr(sup, "quick_url", None)
                        or sup.status == ExposureStatus.ERROR
                        or not sup.is_running
                    ):
                        break
                    await asyncio.sleep(0.05)

                if getattr(sup, "quick_url", None):
                    await _persist_panel_quick_url(sup.quick_url)
                elif sup.status == ExposureStatus.ERROR:
                    await _persist_panel_status(ExposureStatus.ERROR)

            post_commit.append(_run_quick_cf)
            return

        # RECLAIM_REQUIRED recovery (legacy named tunnel or token mode rotation)
        if (
            panel.status == ExposureStatus.RECLAIM_REQUIRED
            and panel.cloudflare_tunnel_id
            and panel.cloudflare_tunnel_id != "quick"
        ):
            if not raw_token:
                raise ValidationError(
                    "cloudflare_token is required to replace an invalidated tunnel token"
                )
            await self._rotate_cloudflare_token(panel, raw_token, hostname, post_commit)
            return

        # Mode 1: Permanent Mode via Tunnel Token (TUNNEL_TOKEN env var — no API DNS calls)
        use_token_mode = cloudflare_mode == "token" or (
            cloudflare_mode is None and not hostname and _looks_like_tunnel_token(raw_token)
        )
        if use_token_mode:
            token_str = raw_token
            if token_str:
                if len(token_str) < 12 or any(ch.isspace() for ch in token_str):
                    raise ValidationError(
                        "A valid Cloudflare Tunnel Token is required (no spaces or line breaks)."
                    )
            elif panel.cloudflare_token_ciphertext and panel.cloudflare_tunnel_id != "quick":
                try:
                    token_str = (
                        _panel_encryption().decrypt(panel.cloudflare_token_ciphertext).decode("utf-8")
                    )
                except Exception as exc:
                    raise ValidationError(
                        "Stored Cloudflare Tunnel Token could not be decrypted; "
                        "please enter a fresh token."
                    ) from exc
            else:
                raise ValidationError(
                    "cloudflare_token is required to enable Cloudflare Tunnel Token mode"
                )

            local_panel_ingress_target()  # enforce loopback/wildcard invariant
            token_bytes = token_str.encode("utf-8")
            ciphertext = _panel_encryption().encrypt(token_bytes)
            tunnel_id = (
                panel.cloudflare_tunnel_id
                if (panel.cloudflare_tunnel_id and panel.cloudflare_tunnel_id != "quick")
                else "token"
            )
            panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
            panel.set_cloudflare_credentials(tunnel_id, ciphertext)
            panel.set_public_address(hostname or None)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_error(None)

            async def _run_token_cf(tok_bytes=token_bytes) -> None:
                sup = get_cloudflared_supervisor()
                if sup.is_running:
                    await sup.stop()
                if hasattr(sup, "start_token"):
                    await sup.start_token(tok_bytes, on_status=_persist_panel_status)
                else:
                    await sup.start(tok_bytes, on_status=_persist_panel_status)

                for _ in range(10):
                    if sup.status != ExposureStatus.STARTING or not sup.is_running:
                        break
                    await asyncio.sleep(0.05)

                if sup.status in (
                    ExposureStatus.ERROR,
                    ExposureStatus.RECLAIM_REQUIRED,
                    ExposureStatus.ACTIVE,
                ):
                    await _persist_panel_status(sup.status)

            post_commit.append(_run_token_cf)
            return

        # Legacy API flow (cloudflare_token API token + hostname required)
        if not raw_token:
            raise ValidationError("cloudflare_token is required to enable cloudflare_tunnel")
        if not hostname:
            raise ValidationError("hostname is required to enable cloudflare_tunnel")

        ingress = panel_ingress_target()
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
        panel.set_public_address(hostname)
        panel.set_status(ExposureStatus.STARTING)
        panel.set_error(None)

        async def _run_panel_cf(tok=raw_token, host=hostname, ing=ingress):
            client = CloudflareClient(tok)
            try:
                provisioned = await client.create_named_tunnel(
                    name=f"{IDENTITY.temp_prefix_new}panel-{host}"
                )
                await client.configure_ingress(
                    provisioned.tunnel_id,
                    [
                        {"hostname": host, "service": ing},
                        {"service": "http_status:404"},
                    ],
                )
                await client.create_cname(host, provisioned.tunnel_id)
            except CloudflareAuthError as exc:
                panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                panel.set_public_address(None)
                panel.set_error("RECLAIM_REQUIRED", str(exc))
                panel.clear_cloudflare_credentials()
                async with UnitOfWork() as post_uow:
                    p_repo = SQLPanelExposureRepository(post_uow.session)
                    await p_repo.save(panel)
                    await post_uow.commit()
                return
            except CloudflareApiError as exc:
                panel.set_status(ExposureStatus.ERROR)
                panel.set_public_address(None)
                panel.set_error("CLOUDFLARE_API_ERROR", str(exc))
                panel.clear_cloudflare_credentials()
                async with UnitOfWork() as post_uow:
                    p_repo = SQLPanelExposureRepository(post_uow.session)
                    await p_repo.save(panel)
                    await post_uow.commit()
                return

            ciphertext = _panel_encryption().encrypt(provisioned.token.encode("utf-8"))
            panel.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
            panel.set_public_address(host)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_error(None)

            async with UnitOfWork() as post_uow:
                p_repo = SQLPanelExposureRepository(post_uow.session)
                await p_repo.save(panel)
                await post_uow.commit()

            token_bytes = provisioned.token.encode("utf-8")
            await self._start_supervisor(token_bytes)

        post_commit.append(_run_panel_cf)

    async def _rotate_cloudflare_token(
        self,
        panel: PanelExposure,
        token: str,
        hostname: str,
        post_commit: list[callable],
    ) -> None:
        """RECLAIM_REQUIRED recovery: replace the tunnel token in place."""
        is_token_mode = panel.cloudflare_tunnel_id == "token"
        resolved_hostname = hostname or panel.public_address or ""
        if not resolved_hostname and not is_token_mode:
            raise ValidationError("hostname is required to enable cloudflare_tunnel")
        ciphertext = _panel_encryption().encrypt(token.encode("utf-8"))
        panel.set_cloudflare_credentials(panel.cloudflare_tunnel_id, ciphertext)
        panel.set_public_address(resolved_hostname or None)
        panel.set_status(ExposureStatus.STARTING)
        panel.set_error(None)
        token_bytes = token.encode("utf-8")
        if is_token_mode:
            async def _restart_tok(t=token_bytes):
                sup = get_cloudflared_supervisor()
                if sup.is_running:
                    await sup.stop()
                if hasattr(sup, "start_token"):
                    await sup.start_token(t, on_status=_persist_panel_status)
                else:
                    await sup.start(t, on_status=_persist_panel_status)

            post_commit.append(_restart_tok)
        else:
            post_commit.append(lambda t=token_bytes: self._restart_supervisor(t))

    async def _disable_cloudflare(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_cloudflare_credentials()
        post_commit.append(self._stop_supervisor)

    async def _enable_playit_http(
        self,
        uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        agent_repo = SQLHostAgentRepository(uow.session)
        agent = await agent_repo.get()

        panel.clear_cloudflare_credentials()
        panel.clear_port_forward_details()

        if agent.is_claimed and agent.secret_ciphertext:
            agent.set_desired_agent_running(True)
            await agent_repo.save(agent)
            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
            except Exception:
                panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
                panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                panel.set_public_address(None)
                panel.set_error(
                    "RECLAIM_REQUIRED",
                    "Stored playit agent secret cannot be decrypted",
                )
                return

            _active_host, internal_port = get_active_panel_bind()
            panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_public_address(None)
            panel.set_error(None)

            async def _run_panel_playit(s_hex=secret_hex, port=internal_port):
                api_client = PlayitApiClient()
                tunnel_obj = None

                # 1. Idempotency list-first check
                try:
                    rundata = await api_client.get_rundata(s_hex)
                    for t in rundata.tunnels:
                        if (
                            t.local_port == port
                            and t.port_type in ("tcp", "both")
                            and not t.is_disabled
                        ):
                            tunnel_obj = t
                            break
                except Exception as exc:
                    logger.warning("Failed to query playit rundata on panel enable: %s", exc)

                # 2. Attempt creation if not found
                if tunnel_obj is None:
                    try:
                        tunnel_obj = await api_client.create_tunnel(
                            secret=s_hex,
                            name=f"{IDENTITY.temp_prefix_new}panel-{panel.id[:6]}",
                            local_ip="127.0.0.1",
                            local_port=port,
                            port_type="tcp",
                        )
                    except PlayitAuthError:
                        panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                        panel.set_public_address(None)
                        panel.set_error(
                            "RECLAIM_REQUIRED",
                            "playit.gg reported an invalid or revoked agent secret",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return
                    except PlayitAllocationFullError:
                        panel.set_status(ExposureStatus.STARTING)
                        panel.set_public_address(None)
                        panel.set_error(
                            "PLAYIT_ALLOCATION_FULL",
                            "playit.gg tunnel allocation limit reached. "
                            "Manage tunnels in playit.gg dashboard.",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return
                    except Exception as exc:
                        logger.warning("Automatic playit tunnel creation failed: %s", exc)
                        panel.set_status(ExposureStatus.STARTING)
                        panel.set_public_address(None)
                        panel.set_error(
                            "PLAYIT_TUNNEL_CREATION_PENDING",
                            "Tunnel creation pending on playit.gg. "
                            "The panel will auto-detect it once created.",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return

                if tunnel_obj is not None and tunnel_obj.display_address:
                    addr = tunnel_obj.display_address
                    address = f"http://{addr}" if not addr.startswith("http") else addr
                    panel.set_playit_tunnel(tunnel_obj.id)
                    panel.set_public_address(address)
                    panel.set_status(ExposureStatus.ACTIVE)
                    panel.set_error(None)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLPanelExposureRepository(post_uow.session)
                        await p_repo.save(panel)
                        await post_uow.commit()

            post_commit.append(lambda s=secret_bytes: self._start_playit_supervisor(s))
            post_commit.append(_run_panel_playit)
        else:
            panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.CLAIM_REQUIRED)
            panel.set_public_address(None)
            panel.set_error(
                "CLAIM_REQUIRED",
                "playit.gg host agent claim required before panel tunnel activation",
            )
            post_commit.append(lambda: self._start_playit_supervisor(None))

    async def _disable_playit_http(
        self,
        uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        agent_repo = SQLHostAgentRepository(uow.session)
        agent = await agent_repo.get()

        tunnel_id = panel.playit_tunnel_id
        if tunnel_id and agent.is_claimed and agent.secret_ciphertext:
            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
                api_client = PlayitApiClient()
                post_commit.append(
                    lambda s=secret_hex, tid=tunnel_id: api_client.delete_tunnel(s, tid)
                )
            except Exception as exc:
                logger.warning("Could not queue playit tunnel deletion on disable: %s", exc)

        panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_playit_credentials()

        desired_running = await compute_desired_agent_running(uow.session)
        if desired_running != agent.desired_agent_running:
            agent.set_desired_agent_running(desired_running)
            await agent_repo.save(agent)
            if not desired_running:
                post_commit.append(self._stop_playit_supervisor)

    async def _enable_port_forward(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        command: SetPanelExposureCommand,
        _post_commit: list[callable],
    ) -> None:
        active_bind_host, internal_port = get_active_panel_bind()
        requested_port = command.external_port or internal_port

        panel.clear_cloudflare_credentials()
        panel.clear_playit_credentials()

        normalized_host = active_bind_host.strip().lower()
        if normalized_host in ("127.0.0.1", "localhost", "::1") or normalized_host.startswith(
            "127."
        ):
            from app.core.settings_store import update_settings as update_settings_store

            update_settings_store({"panel_bind_host": "0.0.0.0"})
            panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error(
                "BIND_MISMATCH",
                f"Panel is bound to loopback ({active_bind_host}). Bind address was automatically "
                "updated to 0.0.0.0 in config/settings.yaml. Restart the panel for this to "
                "take effect, then port forwarding will activate.",
            )
            panel.set_port_forward_details(requested_port, "BIND_MISMATCH", datetime.now(UTC))
            return

        valid, err_code, err_msg = AsyncUPnPService.validate_external_port(requested_port)
        if not valid:
            panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error(err_code, err_msg)
            panel.set_port_forward_details(requested_port, err_code, datetime.now(UTC))
            return

        panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
        panel.set_status(ExposureStatus.STARTING)

        async def _run_panel_upnp(in_port=internal_port, req_port=requested_port):
            upnp = AsyncUPnPService()
            result = await upnp.attempt_mapping(
                internal_port=in_port,
                requested_external_port=req_port,
                description="ONX-Manager-Panel",
            )
            if result.success:
                panel.set_public_address(f"http://{result.external_ip}:{result.external_port}")
                panel.set_port_forward_details(result.external_port, "SUCCEEDED", datetime.now(UTC))
                panel.set_status(ExposureStatus.ACTIVE)
                panel.set_error(None)
            else:
                panel.set_public_address(None)
                panel.set_port_forward_details(req_port, result.error_code, datetime.now(UTC))
                panel.set_status(ExposureStatus.ERROR)
                panel.set_error(result.error_code, result.error_message)

            async with UnitOfWork() as post_uow:
                p_repo = SQLPanelExposureRepository(post_uow.session)
                await p_repo.save(panel)
                await post_uow.commit()

        _post_commit.append(_run_panel_upnp)

    async def _disable_port_forward(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        ext_port = panel.external_port
        panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_port_forward_details()
        _restore_loopback_panel_bind()
        if ext_port:
            post_commit.append(lambda p=ext_port: AsyncUPnPService().delete_mapping(p))

    async def _disable_all_panel_methods(
        self,
        uow: UnitOfWork,
        repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        prev_method = panel.method
        if prev_method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
            await self._disable_cloudflare(uow, repo, panel, post_commit)
        elif prev_method == PanelExposureMethod.PLAYIT_HTTP:
            await self._disable_playit_http(uow, repo, panel, post_commit)
        elif prev_method == PanelExposureMethod.PORT_FORWARD:
            await self._disable_port_forward(uow, repo, panel, post_commit)
        else:
            post_commit.append(self._stop_supervisor)
            _restore_loopback_panel_bind()

        panel.update(PanelExposureMethod.NONE, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_cloudflare_credentials()
        panel.clear_playit_credentials()
        panel.clear_port_forward_details()

    async def _start_supervisor(self, token: bytes) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _restart_supervisor(self, token: bytes) -> None:
        supervisor = get_cloudflared_supervisor()
        if supervisor.is_running:
            await supervisor.stop()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _stop_supervisor(self) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.stop()

    async def _start_playit_supervisor(self, secret: bytes | None) -> None:
        supervisor = get_playit_supervisor()
        await supervisor.start(
            secret,
            on_status=_persist_playit_status,
            on_reconcile=_reconcile_playit_tunnels,
        )

    async def _stop_playit_supervisor(self) -> None:
        supervisor = get_playit_supervisor()
        await supervisor.stop()


async def _reconcile_playit_tunnels() -> None:
    """Periodically check playit.gg for pending tunnels and auto-adopt discovered ones."""
    try:
        async with UnitOfWork() as uow:
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            if not agent.is_claimed or not agent.secret_ciphertext:
                return

            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
            except Exception:
                return

            api_client = PlayitApiClient()
            rundata = await api_client.get_rundata(secret_hex)

            # Reconcile Panel Exposure
            panel_repo = SQLPanelExposureRepository(uow.session)
            panel = await panel_repo.get()
            if (
                panel.method == PanelExposureMethod.PLAYIT_HTTP
                and panel.desired_state == DesiredState.ENABLED
                and (panel.status != ExposureStatus.ACTIVE or not panel.playit_tunnel_id)
            ):
                _active_host, internal_port = get_active_panel_bind()
                for t in rundata.tunnels:
                    if (
                        t.local_port == internal_port
                        and t.port_type in ("tcp", "both")
                        and not t.is_disabled
                    ):
                        addr = t.display_address
                        address = f"http://{addr}" if not addr.startswith("http") else addr
                        panel.set_playit_tunnel(t.id)
                        panel.set_public_address(address)
                        panel.set_status(ExposureStatus.ACTIVE)
                        panel.set_error(None)
                        await panel_repo.save(panel)
                        break

            # Reconcile Server Exposures
            server_repo = SQLServerExposureRepository(uow.session)
            exposures = await server_repo.list_playit_enabled()
            for exposure in exposures:
                changed = False
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED and (
                        target.status != ExposureStatus.ACTIVE or not target.playit_tunnel_id
                    ):
                        for t in rundata.tunnels:
                            if (
                                t.local_port == target.local_port
                                and t.port_type in (target.protocol.value, "both")
                                and not t.is_disabled
                            ):
                                target.playit_tunnel_id = t.id
                                target.mark_active(t.display_address)
                                changed = True

                                break
                if changed:
                    _fold_aggregate(exposure)
                    await server_repo.save(exposure)

            await uow.commit()
    except Exception as exc:
        logger.debug("Playit background tunnel reconciliation skipped/failed: %s", exc)


async def _persist_panel_status(status: ExposureStatus) -> None:
    try:
        sup = get_cloudflared_supervisor()
        async with UnitOfWork() as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await repo.get()
            if panel.desired_state == DesiredState.DISABLED:
                return
            panel.set_status(status)
            if status == ExposureStatus.RECLAIM_REQUIRED:
                panel.set_error(
                    "RECLAIM_REQUIRED",
                    getattr(sup, "error_message", None)
                    or "cloudflared reported an invalid/revoked tunnel token",
                )
            elif status == ExposureStatus.ERROR:
                panel.set_error(
                    getattr(sup, "error_code", None) or "CLOUDFLARED_ERROR",
                    getattr(sup, "error_message", None)
                    or "cloudflared exited unexpectedly or failed health check",
                )
            elif status == ExposureStatus.ACTIVE:
                panel.set_error(None)
            await repo.save(panel)
            await uow.commit()
    except Exception:
        logger.exception("Failed to persist panel status %s", status.value)


async def _persist_panel_quick_url(url: str) -> None:
    """Persist ephemeral Quick Tunnel HTTPS URL once parsed from cloudflared output."""
    try:
        async with UnitOfWork() as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await repo.get()
            if (
                panel.desired_state == DesiredState.DISABLED
                or panel.method != PanelExposureMethod.CLOUDFLARE_TUNNEL
            ):
                return
            panel.set_public_address(url)
            panel.set_status(ExposureStatus.ACTIVE)
            panel.set_error(None)
            await repo.save(panel)
            await uow.commit()
    except Exception:
        logger.exception("Failed to persist panel quick tunnel URL %s", url)


def _make_persist_server_cloudflare_status(
    server_id: str,
    branch_name: str = "main",
) -> Callable[[ExposureStatus], Awaitable[None]]:
    async def _persist_status(status: ExposureStatus) -> None:
        try:
            async with UnitOfWork() as uow:
                repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
                exposure = await repo.get(server_id, branch_name=branch_name)
                if exposure is None or exposure.desired_state == DesiredState.DISABLED:
                    return
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED:
                        if status == ExposureStatus.ACTIVE:
                            target.mark_active(target.public_address or "")
                        elif status == ExposureStatus.RECLAIM_REQUIRED:
                            target.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="cloudflared reported an invalid/revoked tunnel token",
                            )
                        elif status == ExposureStatus.DEGRADED:
                            target.mark_degraded()
                        elif status == ExposureStatus.ERROR:
                            target.mark_error(
                                code="CLOUDFLARED_CRASHED",
                                message="cloudflared process crashed or failed health check",
                            )
                        elif status == ExposureStatus.STARTING:
                            target.mark_starting()
                        elif status == ExposureStatus.STOPPED:
                            target.mark_stopped()
                _fold_aggregate(exposure)
                await repo.save(exposure)
                await uow.commit()
        except Exception:
            logger.exception(
                "Failed to persist server %s cloudflare status %s",
                server_id,
                status.value,
            )

    return _persist_status


async def _persist_playit_status(status: ExposureStatus) -> None:
    try:
        async with UnitOfWork() as uow:
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            agent.set_process_status(exposure_status_to_process_status(status))
            await agent_repo.save(agent)

            server_repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposures = await server_repo.list_playit_enabled()
            for exposure in exposures:
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED:
                        if status == ExposureStatus.ACTIVE:
                            target.mark_active(target.public_address or "")
                        elif status == ExposureStatus.RECLAIM_REQUIRED:
                            target.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="playit.gg reported an invalid or revoked agent secret",
                            )
                        elif status == ExposureStatus.DEGRADED:
                            target.mark_degraded()
                        elif status == ExposureStatus.ERROR:
                            target.mark_error(
                                code="AGENT_CRASHED",
                                message="playit agent process crashed",
                            )
                        elif status == ExposureStatus.CLAIM_REQUIRED:
                            target._transition_to(ExposureStatus.CLAIM_REQUIRED)
                            target.set_error(
                                "CLAIM_REQUIRED",
                                "playit.gg host agent claim required before tunnel activation",
                            )
                        elif status == ExposureStatus.STOPPED:
                            target.mark_stopped()
                _fold_aggregate(exposure)
                await server_repo.save(exposure)

            panel_repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await panel_repo.get()
            if (
                panel.method == PanelExposureMethod.PLAYIT_HTTP
                and panel.desired_state == DesiredState.ENABLED
            ):
                panel.set_status(status)
                if status == ExposureStatus.RECLAIM_REQUIRED:
                    panel.set_error(
                        "RECLAIM_REQUIRED",
                        "playit.gg reported an invalid or revoked agent secret",
                    )
                await panel_repo.save(panel)

            await uow.commit()
    except Exception:
        logger.exception("Failed to persist playit status %s", status.value)


async def _handle_playit_claimed_secret(secret: str) -> None:
    """Invoked when PlayitAgentSupervisor captures the secret key from claim exchange."""
    try:
        secret_bytes = secret.strip().encode("utf-8")
        ciphertext = _panel_encryption().encrypt(secret_bytes)

        from app.api.deps import get_event_bus

        event_bus = None
        try:
            event_bus = await get_event_bus()
        except RuntimeError:
            event_bus = None

        async with UnitOfWork(event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.store_secret(ciphertext)
            agent.set_process_status(AgentProcessStatus.STARTING)
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        logger.info("Host playit agent secret encrypted and persisted to database")

        # Now start the daemon with the newly encrypted secret
        supervisor = get_playit_supervisor()
        await supervisor.restart(
            secret=secret_bytes,
            on_status=_persist_playit_status,
        )
    except Exception as exc:
        logger.exception("Failed to handle playit claimed secret: %s", exc)


class ReconcileExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    scope: str = "server"
    actor_id: str = ""


class ReconcileExposureHandler(CommandHandler[ReconcileExposureCommand]):
    """Manual reconciliation trigger (route #4). Recomputes derived state."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ReconcileExposureCommand) -> CommandResult:
        post_commit: list[callable] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposures = await repo.list()
            for exposure in exposures:
                if (
                    exposure.desired_state == DesiredState.ENABLED
                    and exposure.method == ExposureMethod.PORT_FORWARD
                ):
                    def _make_reconcile_upnp(exp=exposure):
                        async def _act():
                            for target in exp.targets:
                                await _attempt_server_upnp_mapping(exp.server_id, target)
                            _fold_aggregate(exp)
                            async with UnitOfWork() as post_uow:
                                p_repo = SQLServerExposureRepository(post_uow.session)
                                await p_repo.save(exp)
                                await post_uow.commit()
                        return _act

                    post_commit.append(_make_reconcile_upnp())
                elif (
                    exposure.desired_state == DesiredState.ENABLED
                    and exposure.method == ExposureMethod.CLOUDFLARE_TCP
                    and exposure.has_cloudflare_credentials
                ):
                    srv_supervisor = get_server_cloudflared_supervisor(exposure.server_id)
                    should_start = (
                        exposure.aggregate_status != ExposureStatus.RECLAIM_REQUIRED
                        and not srv_supervisor.is_running
                    )
                    if should_start:
                        # ISS-069: move decryption out of the transaction into post_commit
                        def _make_reconcile_cf(
                            sid=exposure.server_id,
                            ctext=exposure.cloudflare_token_ciphertext,
                        ):
                            async def _act():
                                sup = get_server_cloudflared_supervisor(sid)
                                if sup.is_running:
                                    return
                                try:
                                    plaintext = _panel_encryption().decrypt(ctext)
                                    on_status = _make_persist_server_cloudflare_status(sid)
                                    await sup.start(plaintext, on_status=on_status)
                                except Exception:
                                    logger.exception(
                                        "Failed to decrypt server cloudflare token on reconcile"
                                    )
                            return _act

                        post_commit.append(_make_reconcile_cf())
                elif (
                    exposure.desired_state == DesiredState.DISABLED
                    and exposure.method == ExposureMethod.CLOUDFLARE_TCP
                ):
                    srv_supervisor = get_server_cloudflared_supervisor(exposure.server_id)
                    if srv_supervisor.is_running:
                        post_commit.append(srv_supervisor.stop)
                _fold_aggregate(exposure)
                await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)

            supervisor = get_playit_supervisor()
            if (
                desired_running
                and agent.is_claimed
                and agent.secret_ciphertext
                and not supervisor.is_running
            ):
                def _make_reconcile_playit(ctext=agent.secret_ciphertext):
                    async def _act():
                        sup = get_playit_supervisor()
                        if sup.is_running:
                            return
                        try:
                            secret_bytes = _panel_encryption().decrypt(ctext)
                            await sup.start(secret_bytes, on_status=_persist_playit_status)
                        except Exception:
                            logger.exception("Failed to decrypt secret on reconcile")
                    return _act

                post_commit.append(_make_reconcile_playit())
            elif not desired_running and supervisor.is_running:
                post_commit.append(supervisor.stop)

            await self._reconcile_panel(uow, post_commit)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit reconcile action failed")

        return CommandResult(success=True, data={"reconciled": True})

    async def _reconcile_panel(self, uow: UnitOfWork, post_commit: list[callable]) -> None:
        """Restore the panel exposure runtime state from the persisted desired state.

        Uses only the stored aggregate (desired_state, method, credentials):
          - ENABLED + cloudflare_tunnel (quick) -> restart ephemeral quick tunnel.
          - ENABLED + cloudflare_tunnel (token/legacy) + stored credentials
            -> restart the supervised child.
          - ENABLED + port_forward -> verify bind & restore UPnP port mapping if
            bound on a non-loopback address (clears BIND_MISMATCH after restart).
          - RECLAIM_REQUIRED -> leave it; the owner must provide a new token.
          - DISABLED -> ensure the child is stopped.
        """
        repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
        panel = await repo.get()
        supervisor = get_cloudflared_supervisor()

        if (
            panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
            and panel.desired_state == DesiredState.ENABLED
        ):
            if panel.status == ExposureStatus.RECLAIM_REQUIRED:
                return
            if supervisor.is_running:
                return
            if panel.cloudflare_tunnel_id == "quick":
                local_target = local_panel_ingress_target()

                def _make_panel_quick(target=local_target):
                    async def _act():
                        sup = get_cloudflared_supervisor()
                        if sup.is_running:
                            return
                        if hasattr(sup, "start_quick"):
                            await sup.start_quick(
                                target,
                                on_status=_persist_panel_status,
                                on_url=_persist_panel_quick_url,
                            )

                    return _act

                post_commit.append(_make_panel_quick())
            elif panel.has_cloudflare_credentials:
                is_token_mode = panel.cloudflare_tunnel_id == "token"

                def _make_panel_cf(
                    ctext=panel.cloudflare_token_ciphertext,
                    tok_mode=is_token_mode,
                ):
                    async def _act():
                        sup = get_cloudflared_supervisor()
                        if sup.is_running:
                            return
                        try:
                            plaintext = _panel_encryption().decrypt(ctext)
                            if tok_mode and hasattr(sup, "start_token"):
                                await sup.start_token(plaintext, on_status=_persist_panel_status)
                            else:
                                await sup.start(plaintext, on_status=_persist_panel_status)
                        except Exception:
                            logger.exception(
                                "Failed to decrypt panel cloudflare token on reconcile"
                            )

                    return _act

                post_commit.append(_make_panel_cf())
        elif (
            panel.method == PanelExposureMethod.PORT_FORWARD
            and panel.desired_state == DesiredState.ENABLED
        ):
            active_host, _ = get_active_panel_bind()
            if not _is_loopback_bind_host(active_host):
                ext_port = panel.external_port
                eb = self._event_bus

                def _make_panel_upnp(port=ext_port, bus=eb):
                    async def _act():
                        await SetPanelExposureHandler(bus).handle(
                            SetPanelExposureCommand(
                                method="port_forward",
                                desired_state="ENABLED",
                                external_port=port,
                            )
                        )

                    return _act

                post_commit.append(_make_panel_upnp())
        elif (
            panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
            and panel.desired_state == DesiredState.DISABLED
        ):
            post_commit.append(supervisor.stop)


async def reconcile_panel_exposure_on_startup(event_bus: EventBus) -> None:
    """Reconcile persisted Panel Exposure state on backend startup.

    Ensures:
      - ``port_forward`` left in ``BIND_MISMATCH`` clears automatically once the
        backend restarts bound to ``0.0.0.0`` (or re-validates UPnP mapping).
      - ``cloudflare_tunnel`` resumes automatically in Permanent Token or Quick
        Preview mode when ``desired_state == ENABLED``.
    """
    async with UnitOfWork() as uow:
        repo = SQLPanelExposureRepository(uow.session)
        panel = await repo.get()

    if panel.desired_state != DesiredState.ENABLED:
        return

    if panel.method == PanelExposureMethod.PORT_FORWARD:
        active_host, _ = get_active_panel_bind()
        if not _is_loopback_bind_host(active_host):
            await SetPanelExposureHandler(event_bus).handle(
                SetPanelExposureCommand(
                    method="port_forward",
                    desired_state="ENABLED",
                    external_port=panel.external_port,
                )
            )
    elif (
        panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
        and panel.status != ExposureStatus.RECLAIM_REQUIRED
    ):
        supervisor = get_cloudflared_supervisor()
        if supervisor.is_running:
            return
        if panel.cloudflare_tunnel_id == "quick":
            await supervisor.start_quick(
                local_panel_ingress_target(),
                on_status=_persist_panel_status,
                on_url=_persist_panel_quick_url,
            )
        elif panel.has_cloudflare_credentials and panel.cloudflare_token_ciphertext:
            plaintext = _panel_encryption().decrypt(panel.cloudflare_token_ciphertext)
            if panel.cloudflare_tunnel_id == "token":
                await supervisor.start_token(plaintext, on_status=_persist_panel_status)
            else:
                await supervisor.start(plaintext, on_status=_persist_panel_status)


def _fold_aggregate(exposure: ServerExposure) -> None:
    """Recompute the derived aggregate_status cache.

    desired_state=DISABLED overrides every target status (§4.3). For an
    ENABLED exposure the approved precedence applies; NO_TARGETS for an
    enabled exposure is rejected at the API layer, so an enabled fold always
    sees one or more targets.
    """
    if exposure.desired_state == DesiredState.DISABLED:
        exposure.set_aggregate_status(ExposureStatus.DISABLED)
        return
    statuses = [t.status for t in exposure.targets]
    folded = aggregate_precedence(statuses)
    exposure.set_aggregate_status(folded)


def _agent_payload(agent: HostPlayitAgent) -> dict:
    return {
        "claimed": agent.is_claimed,
        "process_status": agent.process_status.value,
        "desired_agent_running": agent.desired_agent_running,
        "last_health_at": agent.last_health_at.isoformat() if agent.last_health_at else None,
        "claim_active": agent.has_active_claim,
        "claim_expires_at": agent.claim_expires_at.isoformat() if agent.claim_expires_at else None,
    }


def _panel_payload(
    panel: PanelExposure,
    access_mode: AccessMode | str = AccessMode.LOCAL,
) -> dict:
    is_port_forward = panel.method == PanelExposureMethod.PORT_FORWARD
    is_playit = panel.method == PanelExposureMethod.PLAYIT_HTTP
    is_enabled = panel.desired_state == DesiredState.ENABLED
    sec_advisory = None
    mode_str = access_mode.value if isinstance(access_mode, AccessMode) else str(access_mode)

    if is_port_forward and is_enabled:
        if mode_str.upper() == "LOCAL":
            sec_advisory = (
                "Port forwarding exposes the panel over unencrypted HTTP while Access Mode "
                "is LOCAL. Open self-registration is exposed to the public Internet! Switch to "
                "GLOBAL (Invite-Only) mode in Settings -> Access to secure the instance."
            )
        else:
            sec_advisory = (
                "Port forwarding exposes the panel over unencrypted HTTP. "
                "Ensure credentials are not transmitted across untrusted public networks."
            )
    elif is_playit and is_enabled:
        sec_advisory = (
            "Playit.gg free tier exposes the panel over raw TCP (HTTP). Credentials are "
            "transmitted without TLS encryption. For encrypted HTTPS access, switch to "
            "Cloudflare Tunnel or upgrade to Playit Premium."
        )

    fix_hint = None
    auto_fixed = False
    if panel.error_code == "BIND_MISMATCH":
        auto_fixed = True
        fix_hint = (
            "Panel bind address updated to 0.0.0.0 in config/settings.yaml. "
            "Restart the panel for this to take effect, then port forwarding will activate."
        )
    elif panel.error_code in ("CGNAT_DETECTED", "DOUBLE_NAT_DETECTED"):
        fix_hint = (
            "Your ISP or upstream router uses CGNAT / Double-NAT (non-public WAN IP). "
            "Switch to Cloudflare Tunnel or playit.gg instead."
        )
    elif panel.error_code in ("UPNP_UNSUPPORTED", "UPNP_TIMEOUT"):
        fix_hint = (
            "Enable UPnP in your router settings, forward the port manually, "
            "or switch to Cloudflare Tunnel / playit.gg."
        )
    elif panel.error_code == "CLOUDFLARED_NOT_FOUND":
        fix_hint = (
            "Install the cloudflared binary on this host and retry."
        )
    elif panel.error_code in ("DENY_LIST_VIOLATION", "INVALID_PORT"):
        fix_hint = (
            "Choose an unreserved port between 1024 and 65535 "
            "(or leave blank to default to the panel port)."
        )

    return {
        "method": panel.method.value,
        "desired_state": panel.desired_state.value,
        "status": panel.status.value,
        "public_address": panel.public_address,
        "tls": not (is_port_forward or is_playit),
        "protocol": "http" if (is_port_forward or is_playit) else "https",
        "external_port": panel.external_port,
        "cloudflare_tunnel_id": panel.cloudflare_tunnel_id,
        "has_cloudflare_credentials": bool(panel.cloudflare_token_ciphertext),
        "ephemeral": bool(
            panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
            and panel.cloudflare_tunnel_id == "quick"
        ),
        "playit_tunnel_id": panel.playit_tunnel_id,
        "upnp_last_result": panel.upnp_last_result,
        "error_code": panel.error_code,
        "error_message": panel.error_message,
        "fix_hint": fix_hint,
        "auto_fixed": auto_fixed,
        "security_advisory": sec_advisory,
    }


def _target_payload(target: ServerExposureTarget) -> dict:
    dashboard_url = None
    setup_instructions = None
    if (
        target.status in (ExposureStatus.STARTING, ExposureStatus.ACTIVE)
        and not target.public_address
    ):
        dashboard_url = "https://playit.gg/manage"
        st_name = target.service_type.value.capitalize()
        proto_name = target.protocol.value.upper()
        setup_instructions = (
            f"Add a {st_name} ({proto_name}) tunnel on playit.gg pointing to local address "
            f"127.0.0.1:{target.local_port}."
        )
    return {
        "id": target.id,
        "exposure_id": target.exposure_id,
        "protocol": target.protocol.value,
        "service_type": target.service_type.value,
        "local_port": target.local_port,
        "public_address": target.public_address,
        "dashboard_url": dashboard_url,
        "setup_instructions": setup_instructions,
        "status": target.status.value,
        "error_code": target.error_code,
        "error_message": target.error_message,
    }


def _exposure_payload(
    exposure: ServerExposure,
    *,
    branch_context: dict[str, Any] | None = None,
) -> dict:
    ctx = branch_context or {}
    allocated_port = ctx.get("game_port")
    if allocated_port is None and exposure.targets:
        allocated_port = exposure.targets[0].local_port

    upnp_status = None
    detected_wan_ip = None
    error_code = None
    error_message = None
    for t in exposure.targets:
        if t.error_code:
            error_code = t.error_code
            error_message = t.error_message
            if t.error_code == "CGNAT_DETECTED":
                upnp_status = "CGNAT_DETECTED"
                import re as _re

                m = _re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", t.error_message or "")
                if m:
                    detected_wan_ip = m.group(0)
            break
    if upnp_status is None and exposure.method == ExposureMethod.PORT_FORWARD:
        if exposure.aggregate_status == ExposureStatus.ACTIVE:
            upnp_status = "ACTIVE"
        elif exposure.aggregate_status == ExposureStatus.ERROR:
            upnp_status = "ERROR"
        else:
            upnp_status = "IDLE"

    srv_hint = None
    if (
        exposure.subdomain_prefix
        and exposure.base_domain
        and (allocated_port is not None)
    ):
        ext_port = allocated_port
        if exposure.targets:
            ext_port = _extract_target_external_port(exposure.targets[0])
        fqdn = f"{exposure.subdomain_prefix}.{exposure.base_domain}"
        srv_hint = f"_minecraft._tcp.{fqdn} 300 IN SRV 0 5 {ext_port} {fqdn}"

    return {
        "server_id": exposure.server_id,
        "branch_name": exposure.branch_name,
        "branch_runtime_status": ctx.get("branch_runtime_status"),
        "allocated_game_port": allocated_port,
        "allocated_port_set": ctx.get("allocated_port_set"),
        "method": exposure.method.value,
        "desired_state": exposure.desired_state.value,
        "aggregate_status": exposure.aggregate_status.value,
        "error_code": error_code,
        "error_message": error_message,
        "cloudflare_tunnel_id": exposure.cloudflare_tunnel_id,
        "has_cloudflare_credentials": exposure.has_cloudflare_credentials,
        "cloudflare_mode": exposure.cloudflare_mode,
        "subdomain_prefix": exposure.subdomain_prefix,
        "base_domain": exposure.base_domain,
        "srv_record_enabled": exposure.srv_record_enabled,
        "srv_record_hint": srv_hint,
        "ephemeral": exposure.ephemeral,
        "upnp_status": upnp_status,
        "detected_wan_ip": detected_wan_ip,
        "targets": [_target_payload(t) for t in exposure.targets],
    }
