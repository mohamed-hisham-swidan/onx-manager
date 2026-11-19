from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServerActivityLog:
    """Represents a durable audit/activity log entry for a server operation or state change."""

    server_id: str
    event_type: str
    summary: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    actor_type: str = "system"  # user, system, api_key
    actor_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    branch_name: str | None = None
