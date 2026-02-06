"""
Helper utilities for WebSocket handlers.
"""

import json
from datetime import UTC, datetime
from typing import Any


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a value to a datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", ""))
        except Exception:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _parse_variant_dict(value: Any) -> dict[str, Any] | None:
    """Parse a variant value (JSON string or dict) to a dictionary."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _to_int(v: Any) -> int:
    """Safely convert a value to int."""
    try:
        return int(v or 0)
    except Exception:
        return 0


def _to_float(v: Any) -> float:
    """Safely convert a value to float."""
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _sum_dicts(dicts: list[dict[str, Any]]) -> dict[str, float]:
    """Sum numeric values across a list of dictionaries."""
    out: dict[str, float] = {}
    for d in dicts:
        for key, value in d.items():
            try:
                out[key] = out.get(key, 0.0) + float(value or 0)
            except Exception:
                continue
    return out


def _avg_dicts(dicts: list[dict[str, Any]]) -> dict[str, float]:
    """Average numeric values across a list of dictionaries."""
    if not dicts:
        return {}
    summed = _sum_dicts(dicts)
    return {key: value / len(dicts) for key, value in summed.items()}


def _health_from(status_value: Any, age_seconds: float | None) -> str:
    """Determine worker health status from heartbeat age."""
    status_upper = str(status_value or "").upper()
    if status_upper == "DEAD":
        return "DEAD"
    if age_seconds is None:
        return "STALE"
    if age_seconds >= 60:
        return "DEAD"
    if age_seconds >= 30:
        return "STALE"
    return "HEALTHY"
