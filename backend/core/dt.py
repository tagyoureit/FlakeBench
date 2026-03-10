from datetime import datetime, timezone


def utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
