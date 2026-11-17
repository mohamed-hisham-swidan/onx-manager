from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.core.allowlist import classify, validate_canonical_relpath
from app.core.host_state import HostStateLayout, validate_server_segment
from app.modules.versioning.infrastructure.class_c_snapshot import _LedgerRunner, _run_async
from app.modules.versioning.infrastructure.merge_engine import _parse_structured
from app.modules.versioning.infrastructure.models import ServerDynamicClassCModel

DYNAMIC_CLASS_C_EXEMPT_EXACT: frozenset[str] = frozenset(
    {
        "server.properties",
        "bukkit.yml",
        "spigot.yml",
        "pufferfish.yml",
        "purpur.yml",
        "commands.yml",
        "help.yml",
        "permissions.yml",
    }
)

DYNAMIC_CLASS_C_EXEMPT_PAPER_RE = re.compile(r"\Aconfig/paper-[^/]+\.yml\Z")


def is_exempt_from_dynamic_class_c(relpath: str) -> bool:
    if relpath in DYNAMIC_CLASS_C_EXEMPT_EXACT:
        return True
    if DYNAMIC_CLASS_C_EXEMPT_PAPER_RE.match(relpath):  # noqa: SIM103
        return True
    return False


def _canonicalize_ast_node(node: Any) -> Any:
    if isinstance(node, bool):
        return {"__type__": "bool", "v": node}
    if isinstance(node, int):
        return {"__type__": "int", "v": node}
    if isinstance(node, float):
        return {"__type__": "float", "v": node}
    if isinstance(node, str):
        return {"__type__": "str", "v": node}
    if node is None:
        return {"__type__": "null", "v": None}
    if isinstance(node, (datetime, date, time)):
        return {"__type__": "datetime", "v": node.isoformat()}
    if isinstance(node, dict):
        items = sorted((str(k), _canonicalize_ast_node(v)) for k, v in node.items())
        return {"__type__": "dict", "items": items}
    if isinstance(node, (list, tuple)):
        return {"__type__": "list", "items": [_canonicalize_ast_node(x) for x in node]}
    # fallback str
    return {"__type__": "str", "v": str(node)}


def canonical_config_ast_sha256(relpath: str, data: bytes) -> tuple[bool, str | None]:
    lowered = relpath.lower()
    if not (lowered.endswith((".yml", ".yaml", ".toml", ".json", ".properties"))):
        return False, None
    if lowered.endswith((".yml", ".yaml")):
        try:
            docs = list(yaml.safe_load_all(data.decode("utf-8")))
        except (UnicodeDecodeError, yaml.YAMLError):
            return False, None
        if len(docs) <= 1:
            ast = docs[0] if docs else {}
        else:
            ast = {"__type__": "yaml_docs", "docs": [_canonicalize_ast_node(d if d is not None else {}) for d in docs]}  # noqa: E501
        try:
            canon = ast  # already canonical for multi-doc wrapper; canonicalize single
            if not (isinstance(ast, dict) and ast.get("__type__") == "yaml_docs"):
                canon = _canonicalize_ast_node(ast)
            serialized = json.dumps(canon, sort_keys=True, separators=(",", ":"))
        except Exception:
            return False, None
        return True, hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    parsed = _parse_structured(relpath, data)
    if parsed is None:
        return False, None
    ast = parsed[0]
    try:
        canon = _canonicalize_ast_node(ast)
        serialized = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    except Exception:
        return False, None
    return True, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DynamicClassCEntry:
    id: str
    server_id: str
    relpath: str
    reason: str
    baseline_ast_sha256: str | None
    live_ast_sha256: str | None
    promoted_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class DynamicClassCEvaluation:
    relpath: str
    is_dynamic_class_c: bool
    action: str
    baseline_ast_sha256: str | None = None
    live_ast_sha256: str | None = None
    warning: str | None = None


class DynamicClassCService:
    def __init__(
        self,
        layout: HostStateLayout | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        sync_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        if layout is None:
            raise ValueError("HostStateLayout is required")
        self._layout = layout
        self._runner = _LedgerRunner(
            layout, session_factory=session_factory, sync_session_factory=sync_session_factory
        )
        self._is_async = self._runner.mode == "async"

    def close(self) -> None:
        self._runner.close()

    def list_paths(self, server_id: str) -> frozenset[str]:
        validate_server_segment(server_id)

        def _sync():
            with self._runner.sync_session() as session:
                rows = (
                    session.execute(
                        select(ServerDynamicClassCModel.relpath).where(
                            ServerDynamicClassCModel.server_id == server_id
                        )
                    )
                    .scalars()
                    .all()
                )
                return frozenset(rows)

        async def _async():
            async with self._runner.async_factory() as session:
                rows = (
                    await session.execute(
                        select(ServerDynamicClassCModel.relpath).where(
                            ServerDynamicClassCModel.server_id == server_id
                        )
                    )
                )
                rows = rows.scalars().all()
                return frozenset(rows)

        if self._is_async:
            return _run_async(_async)
        return _sync()


    def list_entries(self, server_id: str) -> list[DynamicClassCEntry]:
        validate_server_segment(server_id)

        def _sync():
            with self._runner.sync_session() as session:
                rows = session.execute(
                    select(ServerDynamicClassCModel).where(ServerDynamicClassCModel.server_id == server_id)  # noqa: E501
                ).scalars().all()
                out = []
                for r in rows:
                    out.append(DynamicClassCEntry(
                        id=r.id,
                        server_id=r.server_id,
                        relpath=r.relpath,
                        reason=r.reason,
                        baseline_ast_sha256=r.baseline_ast_sha256,
                        live_ast_sha256=r.live_ast_sha256,
                        promoted_at=r.promoted_at,
                        updated_at=r.updated_at,
                    ))
                return out

        async def _async():
            async with self._runner.async_factory() as session:
                rows = (await session.execute(
                    select(ServerDynamicClassCModel).where(ServerDynamicClassCModel.server_id == server_id)  # noqa: E501
                )).scalars().all()
                out = []
                for r in rows:
                    out.append(DynamicClassCEntry(
                        id=r.id,
                        server_id=r.server_id,
                        relpath=r.relpath,
                        reason=r.reason,
                        baseline_ast_sha256=r.baseline_ast_sha256,
                        live_ast_sha256=r.live_ast_sha256,
                        promoted_at=r.promoted_at,
                        updated_at=r.updated_at,
                    ))
                return out

        if self._is_async:
            return _run_async(_async)
        return _sync()

    def evaluate_file(self, server_id: str, relpath: str, *, live_bytes: bytes, baseline_bytes: bytes) -> DynamicClassCEvaluation:  # noqa: E501
        relpath = validate_canonical_relpath(relpath)

        if is_exempt_from_dynamic_class_c(relpath) or classify(relpath) != "B":
            def _sync():
                with self._runner.sync_session() as session:
                    session.execute(
                        delete(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    )
                    session.commit()

            async def _async():
                async with self._runner.async_factory() as session:
                    await session.execute(
                        delete(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    )
                    await session.commit()

            if self._is_async:
                _run_async(_async)
            else:
                _sync()
            action = "exempt" if is_exempt_from_dynamic_class_c(relpath) else "not_class_b"
            return DynamicClassCEvaluation(relpath=relpath, is_dynamic_class_c=False, action=action, warning=None)  # noqa: E501

        base_ok, base_sha = canonical_config_ast_sha256(relpath, baseline_bytes)
        live_ok, live_sha = canonical_config_ast_sha256(relpath, live_bytes)
        if not base_ok or not live_ok:
            def _sync():
                with self._runner.sync_session() as session:
                    existing = session.execute(
                        select(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    ).scalar_one_or_none()
                    return existing is not None

            async def _async():
                async with self._runner.async_factory() as session:
                    existing = (await session.execute(
                        select(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    )).scalar_one_or_none()
                    return existing is not None

            is_dc = _run_async(_async) if self._is_async else _sync()
            warning = f"'{relpath}' could not be parsed for canonical AST comparison"
            return DynamicClassCEvaluation(
                relpath=relpath,
                is_dynamic_class_c=is_dc,
                action="unparseable",
                baseline_ast_sha256=base_sha,
                live_ast_sha256=live_sha,
                warning=warning,
            )

        if live_sha == base_sha:
            def _sync():
                with self._runner.sync_session() as session:
                    res = session.execute(
                        delete(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    )
                    session.commit()
                    return res.rowcount > 0

            async def _async():
                async with self._runner.async_factory() as session:
                    res = await session.execute(
                        delete(ServerDynamicClassCModel).where(
                            ServerDynamicClassCModel.server_id == server_id,
                            ServerDynamicClassCModel.relpath == relpath,
                        )
                    )
                    await session.commit()
                    return res.rowcount > 0

            removed = _run_async(_async) if self._is_async else _sync()
            action = "auto_returned_to_class_b" if removed else "unchanged_class_b"
            return DynamicClassCEvaluation(
                relpath=relpath,
                is_dynamic_class_c=False,
                action=action,
                baseline_ast_sha256=base_sha,
                live_ast_sha256=live_sha,
                warning=None,
            )

        # diverged -> promote
        def _sync():
            with self._runner.sync_session() as session:
                existing = session.execute(
                    select(ServerDynamicClassCModel).where(
                        ServerDynamicClassCModel.server_id == server_id,
                        ServerDynamicClassCModel.relpath == relpath,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(ServerDynamicClassCModel(
                        id=str(__import__("uuid").uuid4()),
                        server_id=server_id,
                        relpath=relpath,
                        reason="ast_diverged",
                        baseline_ast_sha256=base_sha,
                        live_ast_sha256=live_sha,
                    ))
                else:
                    existing.baseline_ast_sha256 = base_sha
                    existing.live_ast_sha256 = live_sha
                    existing.updated_at = datetime.now(UTC)
                session.commit()

        async def _async():
            async with self._runner.async_factory() as session:
                existing = (await session.execute(
                    select(ServerDynamicClassCModel).where(
                        ServerDynamicClassCModel.server_id == server_id,
                        ServerDynamicClassCModel.relpath == relpath,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    session.add(ServerDynamicClassCModel(
                        id=str(__import__("uuid").uuid4()),
                        server_id=server_id,
                        relpath=relpath,
                        reason="ast_diverged",
                        baseline_ast_sha256=base_sha,
                        live_ast_sha256=live_sha,
                    ))
                else:
                    existing.baseline_ast_sha256 = base_sha
                    existing.live_ast_sha256 = live_sha
                    existing.updated_at = datetime.now(UTC)
                await session.commit()

        if self._is_async:
            _run_async(_async)
        else:
            _sync()
        warning = f"'{relpath}' canonical structure diverged from baseline; promoted to dynamic Class C"  # noqa: E501
        return DynamicClassCEvaluation(
            relpath=relpath,
            is_dynamic_class_c=True,
            action="promoted_to_class_c",
            baseline_ast_sha256=base_sha,
            live_ast_sha256=live_sha,
            warning=warning,
        )

    def reset_to_class_b(self, server_id: str, relpath: str) -> bool:
        relpath = validate_canonical_relpath(relpath)

        def _sync():
            with self._runner.sync_session() as session:
                res = session.execute(
                    delete(ServerDynamicClassCModel).where(
                        ServerDynamicClassCModel.server_id == server_id,
                        ServerDynamicClassCModel.relpath == relpath,
                    )
                )
                session.commit()
                return res.rowcount > 0

        async def _async():
            async with self._runner.async_factory() as session:
                res = await session.execute(
                    delete(ServerDynamicClassCModel).where(
                        ServerDynamicClassCModel.server_id == server_id,
                        ServerDynamicClassCModel.relpath == relpath,
                    )
                )
                await session.commit()
                return res.rowcount > 0

        if self._is_async:
            return _run_async(_async)
        return _sync()
