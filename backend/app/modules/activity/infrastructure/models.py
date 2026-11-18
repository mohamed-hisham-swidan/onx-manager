from __future__ import annotations

import json
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Index,
    String,
    Text,
)

from app.core.persistence.base import Base


class ServerActivityLogModel(Base):
    __tablename__ = "server_activity_logs"

    id = Column(String(64), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    timestamp = Column(Float, nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    actor_type = Column(String(32), nullable=False, default="system")
    actor_id = Column(String(64), nullable=True)
    summary = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)
    branch_name = Column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index("ix_activity_server_timestamp", "server_id", "timestamp"),
        Index("ix_activity_server_branch_timestamp", "server_id", "branch_name", "timestamp"),
    )

    def to_details_dict(self) -> dict[str, Any]:
        if not self.details_json:
            return {}
        try:
            return json.loads(self.details_json)
        except Exception:
            return {}
