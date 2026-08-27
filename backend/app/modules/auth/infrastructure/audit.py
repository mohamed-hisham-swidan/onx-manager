from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.base import Base


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(255), nullable=False)
    action = Column(String(128), nullable=False)
    resource_type = Column(String(128), nullable=False)
    resource_id = Column(String(255), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    outcome = Column(String(32), nullable=False)
    correlation_id = Column(String(64), nullable=False)
    previous_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False, unique=True)


def _fmt_ts(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(ts, str):
        ts = ts.strip().replace(" ", "T")
        if "+" in ts:
            ts = ts.split("+")[0]
        if not ts.endswith("Z"):
            ts += "Z"
        return ts
    return str(ts)


def _build_hash_input(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, default=str).encode()


class AuditLogger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        action: str,
        actor_type: str,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        correlation_id: str = "",
        old_value: str | None = None,
        new_value: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        import uuid

        cid = correlation_id or uuid.uuid4().hex
        previous_hash = await self._get_latest_hash()
        timestamp = datetime.now(UTC)

        row_data = {
            "timestamp": _fmt_ts(timestamp),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "outcome": outcome,
            "correlation_id": cid,
            "previous_hash": previous_hash,
        }
        current_hash = hashlib.sha256(_build_hash_input(row_data)).hexdigest()

        entry = AuditLogModel(
            timestamp=timestamp,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            user_agent=user_agent,
            outcome=outcome,
            correlation_id=cid,
            previous_hash=previous_hash,
            hash=current_hash,
        )
        self._session.add(entry)
        await self._session.flush()

    async def verify_chain(self, from_id: int = 0, to_id: int = 0) -> dict:
        stmt = text("SELECT * FROM audit_log ORDER BY id ASC")
        result = await self._session.execute(stmt)
        rows = result.fetchall()

        if not rows:
            return {"valid": True, "checked": 0, "errors": []}

        errors: list[dict] = []
        previous_hash = "0" * 64
        checked = 0

        for row in rows:
            row_dict = dict(row._mapping)
            row_id = row_dict.get("id", 0)

            if from_id > 0 and row_id < from_id:
                previous_hash = row_dict.get("hash", "0" * 64)
                continue

            stored_hash = row_dict.get("hash", "")

            row_data = {
                "timestamp": _fmt_ts(row_dict.get("timestamp", "")),
                "actor_type": row_dict.get("actor_type", ""),
                "actor_id": row_dict.get("actor_id", ""),
                "action": row_dict.get("action", ""),
                "resource_type": row_dict.get("resource_type", ""),
                "resource_id": row_dict.get("resource_id", ""),
                "old_value": row_dict.get("old_value"),
                "new_value": row_dict.get("new_value"),
                "ip_address": row_dict.get("ip_address"),
                "user_agent": row_dict.get("user_agent"),
                "outcome": row_dict.get("outcome", ""),
                "correlation_id": row_dict.get("correlation_id", ""),
                "previous_hash": previous_hash,
            }
            computed = hashlib.sha256(_build_hash_input(row_data)).hexdigest()

            if row_dict.get("previous_hash", "") != previous_hash:
                errors.append(
                    {
                        "id": row_id,
                        "error": "previous_hash_mismatch",
                        "expected": previous_hash,
                        "got": row_dict.get("previous_hash", ""),
                    }
                )

            if computed != stored_hash:
                errors.append(
                    {
                        "id": row_id,
                        "error": "hash_mismatch",
                        "expected": computed,
                        "got": stored_hash,
                    }
                )

            previous_hash = stored_hash
            checked += 1

            if to_id > 0 and row_id >= to_id:
                break

        return {"valid": len(errors) == 0, "checked": checked, "errors": errors}

    async def _get_latest_hash(self) -> str:
        stmt = text("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            return "0" * 64
        return row[0]
