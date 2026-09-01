"""
Pre-flight warnings for test configurations.

Checks for configurations that are likely to hit Snowflake limits.

This module is the single implementation of pre-flight warning generation.
``Orchestrator.generate_preflight_warnings`` delegates here.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from backend.core.warehouse_info import (
    INTERACTIVE_STATEMENT_TIMEOUT_SECONDS,
    PROACTIVE_WARMING_TABLE_LIMIT,
    WarehouseInfo,
    get_warehouse_info,
)

logger = logging.getLogger(__name__)

# Snowflake limit: 20 statements may wait for a table lock before erroring.
LOCK_WAITER_LIMIT = 20


class PreflightConfig(NamedTuple):
    """Normalized view of the values pre-flight checks depend on.

    ``SCENARIO_CONFIG`` nests runtime values under ``target`` and ``workload``
    (see ``Orchestrator.create_run``). Older persisted rows stored some of these
    at the top level, so each field falls back to the flat key.
    """

    table_type: str
    table_name: str
    warehouse: str
    total_threads: int
    write_pct: float
    custom_sql: tuple[str, ...] = ()

    @property
    def expected_concurrent_writes(self) -> float:
        """Approximate number of threads attempting writes simultaneously."""
        return self.total_threads * self.write_pct


def _coerce_int(value: Any, default: int) -> int:
    """Best-effort int conversion that tolerates strings, floats and None."""
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _calculate_write_pct(custom_queries: Any) -> float:
    """Sum the weight of write operations across CUSTOM query templates.

    Args:
        custom_queries: The ``workload.custom_queries`` list, or any value if
            the config is malformed.

    Returns:
        Fraction of the workload that performs writes, clamped to 0.0-1.0.
    """
    if not isinstance(custom_queries, list):
        return 0.0

    write_pct = 0.0
    for query in custom_queries:
        if not isinstance(query, dict):
            continue
        # Runtime is CUSTOM-only, but tolerate legacy key names in old rows.
        kind = str(query.get("query_kind") or query.get("kind") or "").upper()
        raw_weight = query.get("weight_pct", query.get("weight", 0))
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 0.0
        # weight_pct is stored as percentage points (0.00-100.00).
        normalized_weight = max(0.0, min(weight / 100.0, 1.0))
        operation_type = str(query.get("operation_type") or "").upper()
        is_write = kind in ("INSERT", "UPDATE", "DELETE") or (
            kind == "GENERIC_SQL" and operation_type == "WRITE"
        )
        if is_write and normalized_weight > 0:
            write_pct += normalized_weight

    return max(0.0, min(write_pct, 1.0))


def _extract_custom_sql(custom_queries: Any) -> tuple[str, ...]:
    """Collect the SQL text of every CUSTOM query template."""
    if not isinstance(custom_queries, list):
        return ()
    statements: list[str] = []
    for query in custom_queries:
        if not isinstance(query, dict):
            continue
        raw = query.get("sql") or query.get("query") or query.get("query_text") or ""
        text = str(raw).strip()
        if text:
            statements.append(text)
    return tuple(statements)


def extract_preflight_config(scenario_config: dict[str, Any]) -> PreflightConfig:
    """Read the pre-flight inputs out of a scenario config.

    Args:
        scenario_config: The full scenario configuration dict, as persisted in
            ``RUN_STATUS.SCENARIO_CONFIG``.

    Returns:
        Normalized config values with defaults applied.
    """
    target_cfg = scenario_config.get("target") or {}
    workload_cfg = scenario_config.get("workload") or {}

    table_type = str(
        target_cfg.get("table_type") or scenario_config.get("table_type") or "standard"
    ).lower()
    table_name = str(
        target_cfg.get("table_name") or scenario_config.get("table_name") or ""
    )
    warehouse = str(
        target_cfg.get("warehouse") or scenario_config.get("warehouse") or ""
    )
    total_threads = _coerce_int(
        workload_cfg.get("concurrent_connections"),
        _coerce_int(scenario_config.get("total_threads"), 10),
    )

    return PreflightConfig(
        table_type=table_type,
        table_name=table_name,
        warehouse=warehouse,
        total_threads=total_threads,
        write_pct=_calculate_write_pct(workload_cfg.get("custom_queries", [])),
        custom_sql=_extract_custom_sql(workload_cfg.get("custom_queries", [])),
    )


def _lock_contention_details(cfg: PreflightConfig) -> dict[str, Any]:
    """Build the shared ``details`` payload for lock contention warnings."""
    return {
        "table_type": cfg.table_type,
        "table_name": cfg.table_name,
        "total_threads": cfg.total_threads,
        "write_percentage": round(cfg.write_pct * 100, 1),
        "expected_concurrent_writes": round(cfg.expected_concurrent_writes, 1),
        "lock_waiter_limit": LOCK_WAITER_LIMIT,
    }


def _check_lock_contention(cfg: PreflightConfig) -> list[dict[str, Any]]:
    """Warn when concurrent writes on a standard table risk the waiter limit."""
    if cfg.table_type != "standard":
        return []

    expected = cfg.expected_concurrent_writes
    if expected > LOCK_WAITER_LIMIT:
        safe_threads = (
            int(LOCK_WAITER_LIMIT / cfg.write_pct)
            if cfg.write_pct > 0
            else cfg.total_threads
        )
        return [
            {
                "severity": "high",
                "title": "Lock Contention Risk",
                "message": (
                    f"Standard tables use TABLE-LEVEL LOCKING for writes. "
                    f"With {cfg.total_threads} threads and ~{cfg.write_pct * 100:.0f}% writes, "
                    f"you may have ~{expected:.0f} concurrent write attempts. "
                    f"Snowflake's lock waiter limit is {LOCK_WAITER_LIMIT} statements. "
                    f"If any write takes >1 second, you WILL hit SF_LOCK_WAITER_LIMIT errors."
                ),
                "recommendations": [
                    "Use a HYBRID table for concurrent write workloads (row-level locking)",
                    f"Reduce concurrency to ≤{safe_threads} threads",
                    "For read-only benchmarking, keep CUSTOM and set all WRITE operations to 0%",
                ],
                "details": _lock_contention_details(cfg),
            }
        ]

    if expected > LOCK_WAITER_LIMIT * 0.5:
        # Warning for approaching the limit (>50% of limit)
        return [
            {
                "severity": "medium",
                "title": "Potential Lock Contention",
                "message": (
                    f"With {cfg.total_threads} threads and ~{cfg.write_pct * 100:.0f}% writes "
                    f"on a STANDARD table, you may have ~{expected:.0f} concurrent write "
                    f"attempts. This approaches Snowflake's {LOCK_WAITER_LIMIT}-waiter limit. "
                    f"Slow writes could trigger SF_LOCK_WAITER_LIMIT errors."
                ),
                "recommendations": [
                    "Monitor for SF_LOCK_WAITER_LIMIT errors during the run",
                    "Consider using a HYBRID table for better write concurrency",
                ],
                "details": _lock_contention_details(cfg),
            }
        ]

    return []


def _check_warehouse_type_mismatch(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Warn when an interactive table is not paired with an interactive warehouse."""
    if cfg.table_type != "interactive" or warehouse is None:
        return []
    if warehouse.is_interactive:
        return []

    return [
        {
            "severity": "high",
            "title": "Warehouse Type Mismatch",
            "message": (
                f"Table type is INTERACTIVE but warehouse '{warehouse.name}' is type "
                f"'{warehouse.warehouse_type}'. Interactive tables deliver their "
                f"latency benefit only when queried through an interactive warehouse. "
                f"Results will reflect standard warehouse performance."
            ),
            "recommendations": [
                "Select an interactive warehouse for this scenario",
                "Or change the table type to STANDARD to benchmark the standard path",
            ],
            "details": {
                "table_type": cfg.table_type,
                "warehouse": warehouse.name,
                "warehouse_type": warehouse.warehouse_type,
            },
        }
    ]


def _check_interactive_timeout_exposure(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Warn about the fixed 5-second timeout on interactive warehouses."""
    if warehouse is None or not warehouse.is_interactive:
        return []

    return [
        {
            "severity": "high",
            "title": "Interactive Warehouse Query Timeout",
            "message": (
                f"Interactive warehouses cap STATEMENT_TIMEOUT_IN_SECONDS at "
                f"{INTERACTIVE_STATEMENT_TIMEOUT_SECONDS} seconds. Any query "
                f"exceeding it is cancelled, or transparently retried on a fallback "
                f"warehouse if one is configured. Without a fallback warehouse, slow "
                f"queries surface as errors and will skew this benchmark."
            ),
            "recommendations": [
                (
                    f"Set a fallback warehouse: ALTER WAREHOUSE {warehouse.name} "
                    f"SET FALLBACK_WAREHOUSE = <standard_warehouse>"
                ),
                "Keep query shapes selective so they complete within the timeout",
                "Treat timeout errors as a signal the workload is not interactive-suited",
            ],
            "details": {
                "warehouse": warehouse.name,
                "statement_timeout_seconds": INTERACTIVE_STATEMENT_TIMEOUT_SECONDS,
            },
        }
    ]


def _check_writes_on_interactive(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Warn when a write workload targets an interactive table or warehouse."""
    if cfg.write_pct <= 0:
        return []
    is_interactive_target = cfg.table_type == "interactive" or (
        warehouse is not None and warehouse.is_interactive
    )
    if not is_interactive_target:
        return []

    return [
        {
            "severity": "medium",
            "title": "Writes on Interactive Path",
            "message": (
                f"This workload is ~{cfg.write_pct * 100:.0f}% writes. Interactive "
                f"tables do not support UPDATE or DELETE (INSERT OVERWRITE only), and "
                f"interactive warehouses are optimized for read serving. Write results "
                f"here are not representative."
            ),
            "recommendations": [
                "Set write operations to 0% to benchmark the read serving path",
                (
                    "Apply DML to the source table and use an auto-refresh "
                    "(TARGET_LAG) interactive table instead"
                ),
            ],
            "details": {
                "table_type": cfg.table_type,
                "write_percentage": round(cfg.write_pct * 100, 1),
                "warehouse_type": warehouse.warehouse_type if warehouse else None,
            },
        }
    ]


def _check_unsupported_interactive_sql(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Warn about SQL constructs interactive warehouses cannot execute."""
    if warehouse is None or not warehouse.is_interactive:
        return []

    offenders: list[str] = []
    for statement in cfg.custom_sql:
        upper = statement.upper()
        if upper.startswith("CALL ") or " CALL " in upper:
            offenders.append("CALL (stored procedures)")
        if "->>" in statement:
            offenders.append("->> pipe operator")
    if not offenders:
        return []

    unique_offenders = sorted(set(offenders))
    return [
        {
            "severity": "medium",
            "title": "Unsupported SQL on Interactive Warehouse",
            "message": (
                f"Interactive warehouses cannot run: {', '.join(unique_offenders)}. "
                f"The ->> operator is unsupported because it uses stored procedures "
                f"internally. These queries will fail during the run."
            ),
            "recommendations": [
                "Rewrite the affected queries as plain SELECT statements",
                "Move procedure-based logic to a standard warehouse scenario",
            ],
            "details": {
                "warehouse": warehouse.name,
                "unsupported_constructs": unique_offenders,
            },
        }
    ]


def _check_zero_copy_opportunity(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Inform that a standard table on an interactive warehouse is zero-copy."""
    if warehouse is None or not warehouse.is_interactive:
        return []
    if cfg.table_type == "interactive":
        return []

    attached = warehouse.has_table_attached(cfg.table_name) if cfg.table_name else False
    recommendations = [
        (
            "No conversion needed — standard tables perform comparably to "
            "interactive tables on an interactive warehouse"
        ),
    ]
    if not attached:
        recommendations.append(
            f"For proactive cache warming, attach the table: ALTER WAREHOUSE "
            f"{warehouse.name} ADD TABLES ({cfg.table_name or '<table>'}) "
            f"— requires MANAGE ATTACHED TABLES or MODIFY on the warehouse"
        )
        recommendations.append(
            f"Proactive warming is limited to {PROACTIVE_WARMING_TABLE_LIMIT} tables "
            f"per warehouse; unattached tables are still queryable and cache on demand"
        )
    else:
        recommendations.append(
            "Table is already attached, so it is proactively kept in cache"
        )

    return [
        {
            "severity": "info",
            "title": "Zero-Copy Interactive Analytics",
            "message": (
                f"Table type is {cfg.table_type.upper()} and warehouse "
                f"'{warehouse.name}' is INTERACTIVE. Snowflake queries this directly "
                f"with no copy or conversion (public preview). Cache state strongly "
                f"affects results: an interactive warehouse warms at roughly "
                f"300-400 MB/s on X-Small and is slow until warm."
            ),
            "recommendations": recommendations,
            "details": {
                "table_type": cfg.table_type,
                "table_name": cfg.table_name,
                "warehouse": warehouse.name,
                "warehouse_size": warehouse.size,
                "table_attached": attached,
                "attached_table_count": len(warehouse.attached_tables),
            },
        }
    ]


def _check_interactive_billing_model(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> list[dict[str, Any]]:
    """Inform that interactive warehouse cost is provisioned, not per-run."""
    if warehouse is None or not warehouse.is_interactive:
        return []

    return [
        {
            "severity": "info",
            "title": "Interactive Warehouse Billing Model",
            "message": (
                "Interactive warehouses are designed to run continuously, with a "
                "one-hour minimum billable period and a 24-hour minimum auto-suspend. "
                "Resuming a suspended interactive warehouse starts a new minimum "
                "billable hour. The measured cost of this run is therefore not "
                "directly comparable to a standard warehouse spun up per workload."
            ),
            "recommendations": [
                "Compare provisioned 24-hour cost, not per-run cost",
                (
                    "Use the reported break-even hours to judge against your own "
                    "standard warehouse uptime"
                ),
                "Avoid repeated suspend/resume cycles during benchmarking",
            ],
            "details": {
                "warehouse": warehouse.name,
                "warehouse_size": warehouse.size,
                "warehouse_state": warehouse.state,
            },
        }
    ]


async def _resolve_warehouse(
    cfg: PreflightConfig, warehouse_info: WarehouseInfo | None
) -> WarehouseInfo | None:
    """Return injected warehouse metadata, else look it up via the default pool."""
    if warehouse_info is not None:
        return warehouse_info
    if not cfg.warehouse:
        return None

    try:
        from backend.connectors import snowflake_pool

        return await get_warehouse_info(
            snowflake_pool.get_default_pool(), cfg.warehouse
        )
    except Exception as exc:
        # Warehouse type is advisory for these checks; never block a run on it.
        logger.debug("Warehouse lookup unavailable for %s: %s", cfg.warehouse, exc)
        return None


def _check_missing_clustering_key(
    cfg: PreflightConfig,
    warehouse: WarehouseInfo | None,
    clustering_key: str | None,
) -> list[dict[str, Any]]:
    """Warn when a table on an interactive warehouse has no clustering key.

    Interactive tables always have one (CLUSTER BY is required at creation), so
    this targets the zero-copy case: a standard table with no clustering key
    cannot prune partitions, making the 5-second timeout likely.
    """
    if warehouse is None or not warehouse.is_interactive:
        return []
    if clustering_key:
        return []

    return [
        {
            "severity": "high",
            "title": "No Clustering Key for Interactive Queries",
            "message": (
                f"'{cfg.table_name or 'The target table'}' has no clustering key. "
                f"Interactive warehouses cap queries at "
                f"{INTERACTIVE_STATEMENT_TIMEOUT_SECONDS} seconds, and without "
                f"partition pruning a selective WHERE clause still scans broadly. "
                f"Expect timeouts or fallback retries rather than sub-second latency."
            ),
            "recommendations": [
                "Cluster the table on the columns used in your WHERE clauses",
                "Or benchmark an interactive table, where CLUSTER BY is required",
                "Keep probe queries selective on the clustering columns",
            ],
            "details": {
                "table_name": cfg.table_name,
                "table_type": cfg.table_type,
                "warehouse": warehouse.name,
                "clustering_key": None,
            },
        }
    ]


async def _resolve_clustering_key(
    cfg: PreflightConfig, warehouse: WarehouseInfo | None
) -> str | None:
    """Look up the target table's clustering key, or None if unavailable."""
    if warehouse is None or not warehouse.is_interactive:
        return None

    parts = [p for p in cfg.table_name.split(".") if p]
    if len(parts) != 3:
        return None
    database, schema, table = parts

    try:
        from backend.connectors import snowflake_pool

        rows = await snowflake_pool.get_default_pool().execute_query(
            f"""
            SELECT CLUSTERING_KEY
            FROM {database}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{schema}'
              AND TABLE_NAME = '{table}'
            """
        )
    except Exception as exc:
        logger.debug("Clustering key lookup failed for %s: %s", cfg.table_name, exc)
        return None

    if not rows or not rows[0]:
        return None
    value = rows[0][0]
    return str(value).strip() or None if value else None


async def generate_preflight_warnings(
    scenario_config: dict[str, Any],
    *,
    warehouse_info: WarehouseInfo | None = None,
    clustering_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Generate pre-flight warnings for a test configuration.

    Checks for configurations that are likely to hit Snowflake limits, including
    the 20-waiter lock limit on standard tables and the constraints of
    interactive warehouses.

    Args:
        scenario_config: The full scenario configuration dict
        warehouse_info: Pre-resolved warehouse metadata. When omitted, it is
            looked up from the default connection pool. Warehouse-dependent
            checks are skipped when the type cannot be determined.
        clustering_key: Pre-resolved clustering key for the target table. When
            omitted, it is looked up for interactive warehouse scenarios only.

    Returns:
        List of warning dicts with keys: severity, title, message,
        recommendations, details
    """
    cfg = extract_preflight_config(scenario_config)
    warehouse = await _resolve_warehouse(cfg, warehouse_info)
    if clustering_key is None:
        clustering_key = await _resolve_clustering_key(cfg, warehouse)

    warnings: list[dict[str, Any]] = []
    warnings.extend(_check_lock_contention(cfg))
    warnings.extend(_check_warehouse_type_mismatch(cfg, warehouse))
    warnings.extend(_check_interactive_timeout_exposure(cfg, warehouse))
    warnings.extend(_check_missing_clustering_key(cfg, warehouse, clustering_key))
    warnings.extend(_check_writes_on_interactive(cfg, warehouse))
    warnings.extend(_check_unsupported_interactive_sql(cfg, warehouse))
    warnings.extend(_check_zero_copy_opportunity(cfg, warehouse))
    warnings.extend(_check_interactive_billing_model(cfg, warehouse))
    return warnings
