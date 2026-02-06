"""
Constants and default values for template management.
"""

import re

_IDENT_RE = re.compile(r"^[A-Z0-9_]+$")

_CUSTOM_QUERY_FIELDS: tuple[str, str, str, str] = (
    "custom_point_lookup_query",
    "custom_range_scan_query",
    "custom_insert_query",
    "custom_update_query",
)
_CUSTOM_PCT_FIELDS: tuple[str, str, str, str] = (
    "custom_point_lookup_pct",
    "custom_range_scan_pct",
    "custom_insert_pct",
    "custom_update_pct",
)

# Canonical SQL templates for saved CUSTOM workloads.
#
# These are intentionally generic starting points (phantom table) and are stored per-template.
# Execution substitutes `{table}` with the fully-qualified table name.
#
# IMPORTANT: Postgres templates must store Postgres SQL; Snowflake templates must store Snowflake SQL.
# Note: Range scan uses BETWEEN without LIMIT - the offset (100) constrains row count,
# avoiding LIMIT-based early termination optimization which can skew benchmark results.
_DEFAULT_CUSTOM_QUERIES_SNOWFLAKE: dict[str, str] = {
    "custom_point_lookup_query": "SELECT * FROM {table} WHERE id = ?",
    "custom_range_scan_query": ("SELECT * FROM {table} WHERE id BETWEEN ? AND ? + 100"),
    "custom_insert_query": (
        "INSERT INTO {table} (id, data, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)"
    ),
    "custom_update_query": (
        "UPDATE {table} SET data = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?"
    ),
}

_DEFAULT_CUSTOM_QUERIES_POSTGRES: dict[str, str] = {
    "custom_point_lookup_query": "SELECT * FROM {table} WHERE id = $1",
    "custom_range_scan_query": "SELECT * FROM {table} WHERE id BETWEEN $1 AND $2 LIMIT 100",
    # Prefer fully parameterized inserts/updates so executors can generate values.
    "custom_insert_query": "INSERT INTO {table} (id, data, timestamp) VALUES ($1, $2, $3)",
    "custom_update_query": "UPDATE {table} SET data = $1, timestamp = $2 WHERE id = $3",
}

_PRESET_PCTS: dict[str, dict[str, int]] = {
    # READ_ONLY: 50/50 point vs range, 0 writes
    "READ_ONLY": {
        "custom_point_lookup_pct": 50,
        "custom_range_scan_pct": 50,
        "custom_insert_pct": 0,
        "custom_update_pct": 0,
    },
    # WRITE_ONLY: 70/30 insert vs update, 0 reads
    "WRITE_ONLY": {
        "custom_point_lookup_pct": 0,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 70,
        "custom_update_pct": 30,
    },
    # READ_HEAVY: 80% reads (40/40), 20% writes (15/5)
    "READ_HEAVY": {
        "custom_point_lookup_pct": 40,
        "custom_range_scan_pct": 40,
        "custom_insert_pct": 15,
        "custom_update_pct": 5,
    },
    # WRITE_HEAVY: 80% writes (60/20), 20% reads (10/10)
    "WRITE_HEAVY": {
        "custom_point_lookup_pct": 10,
        "custom_range_scan_pct": 10,
        "custom_insert_pct": 60,
        "custom_update_pct": 20,
    },
    # MIXED: 50% reads (25/25), 50% writes (35/15)
    "MIXED": {
        "custom_point_lookup_pct": 25,
        "custom_range_scan_pct": 25,
        "custom_insert_pct": 35,
        "custom_update_pct": 15,
    },
}
