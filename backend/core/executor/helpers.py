"""
Static helper functions for test executor.
"""

import re
from typing import Any

_SF_SQLSTATE_RE = re.compile(r"\(\s*(\d{5})\s*\)")


def classify_sql_error(exc: Exception) -> str:
    """
    Return a stable, low-cardinality category for an execution-time SQL error.

    These errors are expected under load (locks/timeouts/etc), so we aggregate
    rather than logging each failure.
    """
    msg = str(exc or "")
    msg_l = msg.lower()

    # Common Snowflake lock contention signature (from connector error strings).
    if "number of waiters for this lock exceeds" in msg_l:
        return "SF_LOCK_WAITER_LIMIT"

    # Prefer explicit sqlstate if available on the exception.
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate:
        return f"SF_SQLSTATE_{sqlstate}"

    # Fallback: parse "(57014)" style sqlstate from the message.
    m = _SF_SQLSTATE_RE.search(msg)
    if m:
        return f"SF_SQLSTATE_{m.group(1)}"

    return type(exc).__name__


def is_postgres_pool(pool) -> bool:
    """Check if a pool is a PostgreSQL connection pool."""
    try:
        from backend.connectors.postgres_pool import PostgresConnectionPool

        return isinstance(pool, PostgresConnectionPool)
    except ImportError:
        return False


def quote_column(col: str, pool) -> str:
    """
    Quote a column identifier appropriately for the target database.

    - Snowflake: Always quote with double quotes (case-sensitive, uppercase)
    - PostgreSQL: Use unquoted identifiers (PostgreSQL folds to lowercase)
    """
    if is_postgres_pool(pool):
        return col
    return f'"{col}"'


def annotate_query_for_sf_kind(query: str, query_kind: str) -> str:
    """
    Insert a short SQL comment encoding the benchmark query kind after the first keyword.

    This marker enables server-side stats tracking for both:
    - Snowflake: QUERY_HISTORY filtering by UB_KIND marker
    - PostgreSQL: pg_stat_statements filtering by UB_KIND marker

    NOTE: The marker is placed AFTER the first SQL keyword (SELECT/INSERT/UPDATE/DELETE)
    because Snowflake strips leading comments from QUERY_TEXT in QUERY_HISTORY.
    """
    q = str(query or "")
    kind = str(query_kind or "").strip().upper()
    if not kind:
        return q
    marker = f"/*UB_KIND={kind}*/"
    # Avoid double-tagging if the query already contains the marker.
    if "UB_KIND=" in q:
        return q
    # Insert marker after the first SQL keyword to avoid Snowflake stripping it.
    # Snowflake strips leading comments from QUERY_TEXT in INFORMATION_SCHEMA.QUERY_HISTORY.

    # Match leading whitespace + first keyword (SELECT, INSERT, UPDATE, DELETE, WITH, MERGE)
    match = re.match(
        r"^(\s*)(SELECT|INSERT|UPDATE|DELETE|WITH|MERGE)\b", q, re.IGNORECASE
    )
    if match:
        prefix = match.group(1)  # Leading whitespace
        keyword = match.group(2)  # The SQL keyword
        rest = q[match.end() :]  # Everything after the keyword
        return f"{prefix}{keyword} {marker}{rest}"
    # Fallback: prepend marker (may get stripped but better than nothing)
    return f"{marker} {q}"


def truncate_str_for_log(value: Any, *, max_chars: int = 800) -> str:
    """Truncate a string value for logging."""
    text = str(value if value is not None else "")
    if len(text) > max_chars:
        return text[:max_chars] + "…[truncated]"
    return text


def preview_query_for_log(query: str, *, max_chars: int = 2000) -> str:
    """Preview a query for logging, collapsing whitespace."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if len(q) > max_chars:
        return q[:max_chars] + "…[truncated]"
    return q


def preview_param_value_for_log(value: Any, *, max_chars: int = 200) -> str:
    """Preview a parameter value for logging."""
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return f"<bytes len={len(value)}>"
    except Exception:
        # Best-effort; fall back to repr.
        pass

    try:
        text = repr(value)
    except Exception:
        text = f"<unreprable {type(value).__name__}>"

    if len(text) > max_chars:
        return text[:max_chars] + "…[truncated]"
    return text


def preview_params_for_log(
    params: list[Any] | None,
    *,
    max_items: int = 10,
    max_value_chars: int = 200,
) -> dict[str, Any]:
    """Preview parameters for logging."""
    if not params:
        return {"count": 0, "items": []}
    items = [
        preview_param_value_for_log(v, max_chars=max_value_chars)
        for v in params[:max_items]
    ]
    out: dict[str, Any] = {"count": len(params), "items": items}
    if len(params) > max_items:
        out["truncated"] = True
    return out


def sql_error_meta_for_log(exc: Exception, *, max_chars: int = 500) -> dict[str, Any]:
    """
    Extract common SQL error fields across connectors (asyncpg, Snowflake).
    """
    out: dict[str, Any] = {}
    for key in (
        "sqlstate",
        "constraint_name",
        "schema_name",
        "table_name",
        "column_name",
        "detail",
        "hint",
    ):
        try:
            raw = getattr(exc, key, None)
        except Exception:
            raw = None
        if raw is None:
            continue
        val = str(raw)
        if not val:
            continue
        if len(val) > max_chars:
            val = val[:max_chars] + "…[truncated]"
        out[key] = val
    return out


def build_smooth_weighted_schedule(weights: dict[str, int]) -> list[str]:
    """
    Build a smooth weighted round-robin schedule.

    This yields a stable interleaving that converges to the exact target weights
    over one full cycle (e.g., 100 slots for percentage weights).
    """
    total = int(sum(weights.values()))
    if total <= 0:
        return []
    current: dict[str, int] = {k: 0 for k in weights}
    schedule: list[str] = []
    for _ in range(total):
        for k, w in weights.items():
            current[k] += int(w)
        # Use __getitem__ (not .get) so the key function is guaranteed to return int.
        k_max = max(current, key=current.__getitem__)
        schedule.append(k_max)
        current[k_max] -= total
    return schedule
