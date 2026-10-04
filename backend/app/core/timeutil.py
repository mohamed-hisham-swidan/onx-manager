from __future__ import annotations

import re
from datetime import UTC, datetime

NAIVE_ISO_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$")


def is_timestamp_field(name: str | None) -> bool:
    """Check if a field name indicates a timestamp."""
    if not name:
        return False
    lower = name.lower()
    return (
        lower.endswith(("_at", "_timestamp"))
        or lower.startswith("expires")
        or lower in {"timestamp", "date_modified", "date_published"}
    )


def format_datetime_utc(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with 'Z' suffix.

    Naive datetimes are assumed to be UTC. Aware datetimes with any timezone
    offset are converted to UTC via astimezone(UTC).
    """
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalize_iso_timestamp(val: str) -> str:
    """Normalize a naive or space-separated ISO timestamp string to UTC ISO-8601 with 'Z'."""
    if NAIVE_ISO_REGEX.match(val):
        return val.replace(" ", "T") + "Z"
    return val
