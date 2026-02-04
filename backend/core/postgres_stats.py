"""
PostgreSQL statistics collection for test enrichment.

Captures pg_stat_statements snapshots before/after test execution to compute
aggregate metrics like buffer cache hit ratio, I/O timing, and execution stats.

See docs/plan/postgres-enrichment.md for design details.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class PgCapabilities:
    """PostgreSQL server capabilities for enrichment."""

    pg_stat_statements_available: bool = False
    track_io_timing: bool = False
    track_planning: bool = False
    shared_buffers: Optional[str] = None
    pg_version: Optional[str] = None


@dataclass
class PgStatSnapshot:
    """Snapshot of pg_stat_statements at a point in time."""

    timestamp: datetime
    stats: dict[int, dict[str, Any]] = field(default_factory=dict)  # queryid -> stats
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class PgStatDelta:
    """Delta between two pg_stat_statements snapshots."""

    before_timestamp: datetime
    after_timestamp: datetime
    by_queryid: dict[int, dict[str, Any]] = field(default_factory=dict)
    by_query_kind: dict[str, dict[str, Any]] = field(default_factory=dict)
    totals: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


async def check_pg_stat_statements_available(conn) -> bool:
    """
    Check if pg_stat_statements extension is installed.

    Args:
        conn: asyncpg connection

    Returns:
        True if extension is available and queryable
    """
    try:
        result = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM pg_extension 
                WHERE extname = 'pg_stat_statements'
            )
        """)
        return bool(result)
    except Exception as e:
        logger.warning("Error checking pg_stat_statements availability: %s", e)
        return False


async def get_pg_capabilities(conn) -> PgCapabilities:
    """
    Get PostgreSQL server capabilities for enrichment.

    Args:
        conn: asyncpg connection

    Returns:
        PgCapabilities with feature availability flags
    """
    caps = PgCapabilities()

    try:
        # Check extension
        caps.pg_stat_statements_available = await check_pg_stat_statements_available(
            conn
        )

        # Get settings
        settings_query = """
            SELECT name, setting 
            FROM pg_settings 
            WHERE name IN (
                'track_io_timing', 
                'shared_buffers',
                'server_version'
            )
        """
        rows = await conn.fetch(settings_query)
        settings = {row["name"]: row["setting"] for row in rows}

        caps.track_io_timing = settings.get("track_io_timing", "off") == "on"
        caps.shared_buffers = settings.get("shared_buffers")
        caps.pg_version = settings.get("server_version")

        # Check track_planning (may not exist on older versions)
        if caps.pg_stat_statements_available:
            try:
                track_planning = await conn.fetchval("""
                    SELECT setting FROM pg_settings 
                    WHERE name = 'pg_stat_statements.track_planning'
                """)
                caps.track_planning = track_planning == "on"
            except Exception:
                caps.track_planning = False

    except Exception as e:
        logger.warning("Error getting pg capabilities: %s", e)

    return caps


async def capture_pg_stat_snapshot(
    conn,
    query_filter: Optional[str] = None,
) -> PgStatSnapshot:
    """
    Capture current pg_stat_statements state.

    Args:
        conn: asyncpg connection
        query_filter: Optional SQL LIKE pattern to filter queries (e.g., '%UB_KIND=%')

    Returns:
        PgStatSnapshot with current statistics
    """
    snapshot = PgStatSnapshot(timestamp=datetime.now(UTC))

    try:
        # Get capabilities/settings first
        caps = await get_pg_capabilities(conn)
        snapshot.settings = {
            "pg_stat_statements_available": caps.pg_stat_statements_available,
            "track_io_timing": caps.track_io_timing,
            "track_planning": caps.track_planning,
            "shared_buffers": caps.shared_buffers,
            "pg_version": caps.pg_version,
        }

        if not caps.pg_stat_statements_available:
            logger.warning("pg_stat_statements not available, returning empty snapshot")
            return snapshot

        # Build query - capture all relevant fields
        query = """
            SELECT
                queryid,
                query,
                calls,
                total_exec_time,
                mean_exec_time,
                min_exec_time,
                max_exec_time,
                stddev_exec_time,
                rows,
                shared_blks_hit,
                shared_blks_read,
                shared_blks_dirtied,
                shared_blks_written,
                local_blks_hit,
                local_blks_read,
                temp_blks_read,
                temp_blks_written,
                COALESCE(shared_blk_read_time, 0) as shared_blk_read_time,
                COALESCE(shared_blk_write_time, 0) as shared_blk_write_time,
                COALESCE(wal_records, 0) as wal_records,
                COALESCE(wal_bytes, 0) as wal_bytes,
                COALESCE(total_plan_time, 0) as total_plan_time,
                COALESCE(mean_plan_time, 0) as mean_plan_time
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        """

        if query_filter:
            query += f" AND query LIKE '{query_filter}'"

        rows = await conn.fetch(query)

        for row in rows:
            queryid = row["queryid"]
            snapshot.stats[queryid] = dict(row)

        logger.debug(
            "Captured pg_stat_statements snapshot with %d entries", len(snapshot.stats)
        )

    except Exception as e:
        logger.exception("Error capturing pg_stat_statements snapshot: %s", e)

    return snapshot


def compute_snapshot_delta(
    before: PgStatSnapshot,
    after: PgStatSnapshot,
) -> PgStatDelta:
    """
    Compute delta between two snapshots.

    Args:
        before: Snapshot taken before test/phase
        after: Snapshot taken after test/phase

    Returns:
        PgStatDelta with per-queryid and aggregated deltas
    """
    delta = PgStatDelta(
        before_timestamp=before.timestamp,
        after_timestamp=after.timestamp,
        settings=after.settings,
    )

    # Numeric fields to compute delta for
    delta_fields = [
        "calls",
        "total_exec_time",
        "rows",
        "shared_blks_hit",
        "shared_blks_read",
        "shared_blks_dirtied",
        "shared_blks_written",
        "local_blks_hit",
        "local_blks_read",
        "temp_blks_read",
        "temp_blks_written",
        "shared_blk_read_time",
        "shared_blk_write_time",
        "wal_records",
        "wal_bytes",
        "total_plan_time",
    ]

    # Compute per-queryid delta
    for queryid, after_stats in after.stats.items():
        before_stats = before.stats.get(queryid, {})

        queryid_delta: dict[str, Any] = {
            "query": after_stats.get("query"),
            "query_kind": extract_query_kind(after_stats.get("query", "")),
        }

        for field_name in delta_fields:
            after_val = after_stats.get(field_name, 0) or 0
            before_val = before_stats.get(field_name, 0) or 0
            queryid_delta[field_name] = after_val - before_val

        # Compute mean values from delta (if calls > 0)
        calls_delta = queryid_delta.get("calls", 0)
        if calls_delta > 0:
            queryid_delta["mean_exec_time"] = (
                queryid_delta["total_exec_time"] / calls_delta
            )
            queryid_delta["mean_plan_time"] = (
                queryid_delta["total_plan_time"] / calls_delta
            )
        else:
            queryid_delta["mean_exec_time"] = 0
            queryid_delta["mean_plan_time"] = 0

        # Only include if there were calls during this window
        if calls_delta > 0:
            delta.by_queryid[queryid] = queryid_delta

    # Aggregate by query kind
    delta.by_query_kind = aggregate_by_query_kind(delta.by_queryid)

    # Compute totals
    delta.totals = _compute_totals(delta.by_queryid)

    return delta


def extract_query_kind(query_text: str) -> Optional[str]:
    """
    Extract query kind from query text.

    First checks for explicit UB_KIND marker in comments (e.g., /* UB_KIND=POINT_LOOKUP */).
    If not present, infers the kind from SQL pattern.

    NOTE: PostgreSQL's pg_stat_statements strips comments during query normalization,
    so UB_KIND markers won't be present. We infer the kind from SQL patterns instead.

    Classification logic:
    - SELECT ... WHERE pk = $1 (no ORDER BY) -> POINT_LOOKUP
    - SELECT ... WHERE col >= $1 ORDER BY ... LIMIT -> RANGE_SCAN
    - INSERT INTO ... -> INSERT
    - UPDATE ... WHERE pk = $1 -> UPDATE
    - DELETE ... WHERE pk = $1 -> DELETE
    - Other SELECT -> SELECT_OTHER
    - System queries (pg_stat, pg_settings, etc.) -> SYSTEM

    Args:
        query_text: SQL query text

    Returns:
        Query kind string or None if not found
    """
    if not query_text:
        return None

    # First, check for explicit UB_KIND marker (may be present in direct queries)
    match = re.search(r"UB_KIND=(\w+)", query_text)
    if match:
        return match.group(1)

    # Infer kind from SQL pattern
    query_upper = query_text.upper().strip()

    # Skip system/monitoring queries
    if any(
        sys_table in query_upper
        for sys_table in [
            "PG_STAT_",
            "PG_SETTINGS",
            "PG_DATABASE",
            "PG_ADVISORY",
            "PG_CATALOG",
            "INFORMATION_SCHEMA",
        ]
    ):
        return "SYSTEM"

    # Skip connection management commands
    if query_upper.startswith(("UNLISTEN", "CLOSE ALL", "RESET ALL", "BEGIN", "COMMIT", "ROLLBACK")):
        return "SYSTEM"

    # Check for INSERT
    if query_upper.startswith("INSERT"):
        return "INSERT"

    # Check for UPDATE
    if query_upper.startswith("UPDATE"):
        return "UPDATE"

    # Check for DELETE
    if query_upper.startswith("DELETE"):
        return "DELETE"

    # Check for SELECT patterns
    if query_upper.startswith("SELECT"):
        # Check for RANGE_SCAN pattern: ORDER BY with LIMIT, or >= / <= / BETWEEN
        has_order_by = "ORDER BY" in query_upper
        has_limit = "LIMIT" in query_upper
        has_range_predicate = any(
            op in query_upper for op in [" >= ", " <= ", " > ", " < ", "BETWEEN"]
        )

        if has_order_by and (has_limit or has_range_predicate):
            return "RANGE_SCAN"

        # Check for POINT_LOOKUP pattern: WHERE col = $N (equality on single value, no ORDER BY)
        # Pattern: WHERE followed by column = $N and no ORDER BY
        has_eq_predicate = re.search(r"WHERE\s+\S+\s*=\s*\$\d+", query_upper)
        if has_eq_predicate and not has_order_by:
            return "POINT_LOOKUP"

        # Other SELECT queries
        return "SELECT_OTHER"

    # COPY commands
    if query_upper.startswith("COPY"):
        return "COPY"

    # DDL commands
    if query_upper.startswith(("CREATE", "DROP", "ALTER", "TRUNCATE")):
        return "DDL"

    return None


def aggregate_by_query_kind(
    by_queryid: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Aggregate delta stats by query kind.

    Args:
        by_queryid: Per-queryid delta statistics

    Returns:
        Dict mapping query_kind to aggregated stats
    """
    by_kind: dict[str, dict[str, Any]] = {}

    sum_fields = [
        "calls",
        "total_exec_time",
        "rows",
        "shared_blks_hit",
        "shared_blks_read",
        "shared_blks_dirtied",
        "shared_blks_written",
        "local_blks_hit",
        "local_blks_read",
        "temp_blks_read",
        "temp_blks_written",
        "shared_blk_read_time",
        "shared_blk_write_time",
        "wal_records",
        "wal_bytes",
        "total_plan_time",
    ]

    for queryid_delta in by_queryid.values():
        kind = queryid_delta.get("query_kind") or "UNKNOWN"

        if kind not in by_kind:
            by_kind[kind] = {field: 0 for field in sum_fields}
            by_kind[kind]["query_count"] = 0  # Number of distinct query patterns

        by_kind[kind]["query_count"] += 1

        for field_name in sum_fields:
            by_kind[kind][field_name] += queryid_delta.get(field_name, 0) or 0

    # Compute derived metrics per kind
    for kind, stats in by_kind.items():
        calls = stats.get("calls", 0)
        if calls > 0:
            stats["mean_exec_time"] = stats["total_exec_time"] / calls
            stats["mean_plan_time"] = stats["total_plan_time"] / calls
        else:
            stats["mean_exec_time"] = 0
            stats["mean_plan_time"] = 0

        # Cache hit ratio
        hits = stats.get("shared_blks_hit", 0)
        reads = stats.get("shared_blks_read", 0)
        total_blocks = hits + reads
        stats["cache_hit_ratio"] = hits / total_blocks if total_blocks > 0 else 1.0

    return by_kind


def _compute_totals(by_queryid: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Compute total aggregates across all query patterns.
    
    NOTE: Excludes SYSTEM queries (pg_stat_*, connection management commands, etc.)
    from totals to report only actual benchmark query metrics.
    """
    sum_fields = [
        "calls",
        "total_exec_time",
        "rows",
        "shared_blks_hit",
        "shared_blks_read",
        "shared_blks_dirtied",
        "shared_blks_written",
        "local_blks_hit",
        "local_blks_read",
        "temp_blks_read",
        "temp_blks_written",
        "shared_blk_read_time",
        "shared_blk_write_time",
        "wal_records",
        "wal_bytes",
        "total_plan_time",
    ]

    totals: dict[str, Any] = {field: 0 for field in sum_fields}
    benchmark_query_count = 0

    for queryid_delta in by_queryid.values():
        # Skip SYSTEM queries from totals (they're connection management, not benchmark queries)
        query_kind = queryid_delta.get("query_kind")
        if query_kind == "SYSTEM":
            continue
        
        benchmark_query_count += 1
        for field_name in sum_fields:
            totals[field_name] += queryid_delta.get(field_name, 0) or 0

    totals["query_pattern_count"] = benchmark_query_count

    # Derived metrics
    calls = totals.get("calls", 0)
    if calls > 0:
        totals["mean_exec_time"] = totals["total_exec_time"] / calls
        totals["mean_plan_time"] = totals["total_plan_time"] / calls
    else:
        totals["mean_exec_time"] = 0
        totals["mean_plan_time"] = 0

    # Cache hit ratio
    hits = totals.get("shared_blks_hit", 0)
    reads = totals.get("shared_blks_read", 0)
    total_blocks = hits + reads
    totals["cache_hit_ratio"] = hits / total_blocks if total_blocks > 0 else 1.0

    return totals


def _make_json_serializable(obj: Any) -> Any:
    """Convert non-JSON-serializable types to primitives.
    
    Handles:
    - Decimal -> float
    - datetime -> isoformat string
    - bytes -> hex string
    - other iterables -> recursively processed
    """
    from decimal import Decimal
    from datetime import datetime
    
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return obj.hex()
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    else:
        return obj


def snapshot_to_dict(snapshot: PgStatSnapshot) -> dict[str, Any]:
    """Convert snapshot to JSON-serializable dict for storage."""
    return _make_json_serializable({
        "timestamp": snapshot.timestamp.isoformat(),
        "settings": snapshot.settings,
        "stats": {str(k): v for k, v in snapshot.stats.items()},
    })


def delta_to_dict(delta: PgStatDelta) -> dict[str, Any]:
    """Convert delta to JSON-serializable dict for storage."""
    return _make_json_serializable({
        "before_timestamp": delta.before_timestamp.isoformat(),
        "after_timestamp": delta.after_timestamp.isoformat(),
        "settings": delta.settings,
        "by_queryid": {str(k): v for k, v in delta.by_queryid.items()},
        "by_query_kind": delta.by_query_kind,
        "totals": delta.totals,
    })


def get_capability_warnings(caps: PgCapabilities) -> list[dict[str, str]]:
    """
    Generate user-facing warnings for missing capabilities.

    Args:
        caps: PgCapabilities from get_pg_capabilities()

    Returns:
        List of warning dicts with type, impact, and remediation
    """
    warnings = []

    if not caps.pg_stat_statements_available:
        warnings.append(
            {
                "type": "missing_extension",
                "severity": "warning",
                "extension": "pg_stat_statements",
                "impact": "Server-side statistics unavailable for enrichment. "
                "Cache hit ratio, I/O timing, and execution stats will not be available.",
                "remediation": "CREATE EXTENSION pg_stat_statements; "
                "(requires shared_preload_libraries configuration and server restart)",
            }
        )
    else:
        # Extension available, check settings
        if not caps.track_io_timing:
            warnings.append(
                {
                    "type": "setting_disabled",
                    "severity": "info",
                    "setting": "track_io_timing",
                    "impact": "I/O timing breakdown unavailable. "
                    "Disk read/write times will show as 0.",
                    "remediation": "ALTER SYSTEM SET track_io_timing = on; "
                    "SELECT pg_reload_conf();",
                }
            )

        if not caps.track_planning:
            warnings.append(
                {
                    "type": "setting_disabled",
                    "severity": "info",
                    "setting": "pg_stat_statements.track_planning",
                    "impact": "Planning time breakdown unavailable.",
                    "remediation": "ALTER SYSTEM SET pg_stat_statements.track_planning = on; "
                    "SELECT pg_reload_conf();",
                }
            )

    return warnings
