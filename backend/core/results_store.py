"""
Snowflake Results Store

Persists test runs, test results, and time-series metrics snapshots into
UNISTORE_BENCHMARK.TEST_RESULTS.* tables.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from backend.config import settings
from backend.connectors import snowflake_pool
from backend.models import Metrics, TestResult, TestScenario


def _results_prefix() -> str:
    # Keep identifiers fully-qualified so we don't rely on session USE DATABASE/SCHEMA.
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


async def insert_test_start(
    *,
    test_id: str,
    test_name: str,
    scenario: TestScenario,
    table_name: str,
    table_type: str,
    warehouse: Optional[str],
    warehouse_size: Optional[str],
    template_id: str,
    template_name: str,
    template_config: dict[str, Any],
) -> None:
    pool = snowflake_pool.get_default_pool()
    now = datetime.now(UTC).isoformat()

    payload = {
        "template_id": template_id,
        "template_name": template_name,
        "template_config": template_config,
        "scenario": scenario.model_dump(mode="json"),
    }

    query = f"""
    INSERT INTO {_results_prefix()}.TEST_RESULTS (
        TEST_ID,
        RUN_ID,
        TEST_NAME,
        SCENARIO_NAME,
        TABLE_NAME,
        TABLE_TYPE,
        WAREHOUSE,
        WAREHOUSE_SIZE,
        STATUS,
        START_TIME,
        CONCURRENT_CONNECTIONS,
        TEST_CONFIG
    )
    SELECT
        ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?)
    """

    params = [
        test_id,
        test_name,
        scenario.name,
        table_name,
        table_type,
        warehouse,
        warehouse_size,
        "RUNNING",
        now,
        scenario.concurrent_connections,
        json.dumps(payload),
    ]

    await pool.execute_query(query, params=params)


async def insert_metrics_snapshot(*, test_id: str, metrics: Metrics) -> None:
    pool = snowflake_pool.get_default_pool()
    snapshot_id = str(uuid4())

    snapshot_query = f"""
    INSERT INTO {_results_prefix()}.METRICS_SNAPSHOTS (
        SNAPSHOT_ID,
        TEST_ID,
        TIMESTAMP,
        ELAPSED_SECONDS,
        TOTAL_OPERATIONS,
        OPERATIONS_PER_SECOND,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        AVG_LATENCY_MS,
        READ_COUNT,
        WRITE_COUNT,
        ERROR_COUNT,
        BYTES_PER_SECOND,
        ROWS_PER_SECOND,
        ACTIVE_CONNECTIONS,
        CUSTOM_METRICS
    )
    SELECT
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?)
    """

    params = [
        snapshot_id,
        test_id,
        metrics.timestamp.isoformat(),
        metrics.elapsed_seconds,
        metrics.total_operations,
        metrics.current_ops_per_second,
        metrics.overall_latency.p50,
        metrics.overall_latency.p95,
        metrics.overall_latency.p99,
        metrics.overall_latency.avg,
        metrics.read_metrics.count,
        metrics.write_metrics.count,
        metrics.failed_operations,
        metrics.bytes_per_second,
        metrics.rows_per_second,
        metrics.active_connections,
        json.dumps(metrics.custom_metrics or {}),
    ]

    await pool.execute_query(snapshot_query, params=params)


async def insert_query_executions(
    *,
    test_id: str,
    rows: list[dict[str, Any]],
    chunk_size: int = 500,
) -> None:
    """
    Bulk insert per-operation rows into TEST_RESULTS.QUERY_EXECUTIONS.

    Notes:
    - This is best-effort and should not fail the test if it can't persist.
    - `rows` can include warmup operations (WARMUP flag).
    """
    if not rows:
        return

    pool = snowflake_pool.get_default_pool()

    cols = [
        "EXECUTION_ID",
        "TEST_ID",
        "QUERY_ID",
        "QUERY_TEXT",
        "START_TIME",
        "END_TIME",
        "DURATION_MS",
        "ROWS_AFFECTED",
        "BYTES_SCANNED",
        "WAREHOUSE",
        "SUCCESS",
        "ERROR",
        "CONNECTION_ID",
        "CUSTOM_METADATA",
        "QUERY_KIND",
        "WORKER_ID",
        "WARMUP",
        "APP_ELAPSED_MS",
        # DML row counters (derived deterministically from QUERY_KIND + ROWS_AFFECTED).
        # These are NOT reliably available via INFORMATION_SCHEMA.QUERY_HISTORY.
        "SF_ROWS_INSERTED",
        "SF_ROWS_UPDATED",
        "SF_ROWS_DELETED",
    ]

    # NOTE: Snowflake does not accept PARSE_JSON(?) inside a VALUES clause for this
    # connector/paramstyle combination. Use INSERT ... SELECT ... FROM VALUES, and
    # apply TRY_PARSE_JSON() in the SELECT projection.
    #
    # This keeps the bulk insert best-effort and avoids failing runs due to
    # CUSTOM_METADATA (VARIANT) binding.
    custom_idx_1based = cols.index("CUSTOM_METADATA") + 1
    select_exprs: list[str] = []
    for i, col in enumerate(cols, start=1):
        if i == custom_idx_1based:
            select_exprs.append(f"TRY_PARSE_JSON(COLUMN{i}) AS {col}")
        else:
            select_exprs.append(f"COLUMN{i} AS {col}")

    insert_prefix = f"""
    INSERT INTO {_results_prefix()}.QUERY_EXECUTIONS (
        {", ".join(cols)}
    )
    SELECT
        {", ".join(select_exprs)}
    FROM VALUES
    """

    def _row_params(r: dict[str, Any]) -> list[Any]:
        query_kind = (r.get("query_kind") or "").strip().upper()
        rows_affected = r.get("rows_affected")
        sf_rows_inserted = rows_affected if query_kind == "INSERT" else None
        sf_rows_updated = rows_affected if query_kind == "UPDATE" else None
        # We don't execute deletes today; keep null unless we add DELETE operations.
        sf_rows_deleted = rows_affected if query_kind == "DELETE" else None

        return [
            r.get("execution_id"),
            test_id,
            r.get("query_id"),
            r.get("query_text"),
            r.get("start_time"),
            r.get("end_time"),
            r.get("duration_ms"),
            rows_affected,
            r.get("bytes_scanned"),
            r.get("warehouse"),
            bool(r.get("success")),
            r.get("error"),
            r.get("connection_id"),
            json.dumps(r.get("custom_metadata") or {}),
            r.get("query_kind"),
            r.get("worker_id"),
            bool(r.get("warmup")),
            r.get("app_elapsed_ms"),
            sf_rows_inserted,
            sf_rows_updated,
            sf_rows_deleted,
        ]

    i = 0
    while i < len(rows):
        batch = rows[i : i + chunk_size]
        row_tpl = "(" + ", ".join(["?"] * len(cols)) + ")"
        values_sql = ",\n".join([row_tpl] * len(batch))
        query = insert_prefix + values_sql
        params: list[Any] = []
        for r in batch:
            params.extend(_row_params(r))
        await pool.execute_query(query, params=params)
        i += chunk_size


async def insert_test_logs(
    *, rows: list[dict[str, Any]], chunk_size: int = 500
) -> None:
    """
    Bulk insert log rows into TEST_RESULTS.TEST_LOGS.

    Expected keys per row:
    - log_id, test_id, seq, timestamp, level, logger, message, exception
    """
    if not rows:
        return

    pool = snowflake_pool.get_default_pool()
    cols = [
        "LOG_ID",
        "TEST_ID",
        "SEQ",
        "TIMESTAMP",
        "LEVEL",
        "LOGGER",
        "MESSAGE",
        "EXCEPTION",
    ]
    insert_prefix = (
        f"INSERT INTO {_results_prefix()}.TEST_LOGS ({', '.join(cols)}) VALUES\n"
    )

    def _row_params(r: dict[str, Any]) -> list[Any]:
        return [
            r.get("log_id"),
            r.get("test_id"),
            r.get("seq"),
            r.get("timestamp"),
            r.get("level"),
            r.get("logger"),
            r.get("message"),
            r.get("exception"),
        ]

    i = 0
    while i < len(rows):
        batch = rows[i : i + chunk_size]
        row_tpl = "(" + ", ".join(["?"] * len(cols)) + ")"
        values_sql = ",\n".join([row_tpl] * len(batch))
        query = insert_prefix + values_sql
        params: list[Any] = []
        for r in batch:
            params.extend(_row_params(r))
        await pool.execute_query(query, params=params)
        i += chunk_size


async def update_test_result_final(*, test_id: str, result: TestResult) -> None:
    pool = snowflake_pool.get_default_pool()

    end_time = result.end_time.isoformat() if result.end_time else None

    query = f"""
    UPDATE {_results_prefix()}.TEST_RESULTS
    SET
        STATUS = ?,
        END_TIME = ?,
        DURATION_SECONDS = ?,
        TOTAL_OPERATIONS = ?,
        READ_OPERATIONS = ?,
        WRITE_OPERATIONS = ?,
        FAILED_OPERATIONS = ?,
        OPERATIONS_PER_SECOND = ?,
        READS_PER_SECOND = ?,
        WRITES_PER_SECOND = ?,
        AVG_LATENCY_MS = ?,
        P50_LATENCY_MS = ?,
        P90_LATENCY_MS = ?,
        P95_LATENCY_MS = ?,
        P99_LATENCY_MS = ?,
        MIN_LATENCY_MS = ?,
        MAX_LATENCY_MS = ?,
        ERROR_COUNT = ?,
        ERROR_RATE = ?,
        ROWS_READ = ?,
        ROWS_WRITTEN = ?,
        READ_P50_LATENCY_MS = ?,
        READ_P95_LATENCY_MS = ?,
        READ_P99_LATENCY_MS = ?,
        READ_MIN_LATENCY_MS = ?,
        READ_MAX_LATENCY_MS = ?,
        WRITE_P50_LATENCY_MS = ?,
        WRITE_P95_LATENCY_MS = ?,
        WRITE_P99_LATENCY_MS = ?,
        WRITE_MIN_LATENCY_MS = ?,
        WRITE_MAX_LATENCY_MS = ?,
        POINT_LOOKUP_P50_LATENCY_MS = ?,
        POINT_LOOKUP_P95_LATENCY_MS = ?,
        POINT_LOOKUP_P99_LATENCY_MS = ?,
        POINT_LOOKUP_MIN_LATENCY_MS = ?,
        POINT_LOOKUP_MAX_LATENCY_MS = ?,
        RANGE_SCAN_P50_LATENCY_MS = ?,
        RANGE_SCAN_P95_LATENCY_MS = ?,
        RANGE_SCAN_P99_LATENCY_MS = ?,
        RANGE_SCAN_MIN_LATENCY_MS = ?,
        RANGE_SCAN_MAX_LATENCY_MS = ?,
        INSERT_P50_LATENCY_MS = ?,
        INSERT_P95_LATENCY_MS = ?,
        INSERT_P99_LATENCY_MS = ?,
        INSERT_MIN_LATENCY_MS = ?,
        INSERT_MAX_LATENCY_MS = ?,
        UPDATE_P50_LATENCY_MS = ?,
        UPDATE_P95_LATENCY_MS = ?,
        UPDATE_P99_LATENCY_MS = ?,
        UPDATE_MIN_LATENCY_MS = ?,
        UPDATE_MAX_LATENCY_MS = ?,
        APP_OVERHEAD_P50_MS = ?,
        APP_OVERHEAD_P95_MS = ?,
        APP_OVERHEAD_P99_MS = ?,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE TEST_ID = ?
    """

    error_rate = 0.0
    if result.total_operations > 0:
        error_rate = result.failed_operations / result.total_operations

    params = [
        str(result.status).upper(),
        end_time,
        result.duration_seconds,
        result.total_operations,
        result.read_operations,
        result.write_operations,
        result.failed_operations,
        result.operations_per_second,
        result.reads_per_second,
        result.writes_per_second,
        result.avg_latency_ms,
        result.p50_latency_ms,
        result.p90_latency_ms,
        result.p95_latency_ms,
        result.p99_latency_ms,
        result.min_latency_ms,
        result.max_latency_ms,
        result.error_count,
        error_rate,
        result.rows_read,
        result.rows_written,
        result.read_p50_latency_ms,
        result.read_p95_latency_ms,
        result.read_p99_latency_ms,
        result.read_min_latency_ms,
        result.read_max_latency_ms,
        result.write_p50_latency_ms,
        result.write_p95_latency_ms,
        result.write_p99_latency_ms,
        result.write_min_latency_ms,
        result.write_max_latency_ms,
        result.point_lookup_p50_latency_ms,
        result.point_lookup_p95_latency_ms,
        result.point_lookup_p99_latency_ms,
        result.point_lookup_min_latency_ms,
        result.point_lookup_max_latency_ms,
        result.range_scan_p50_latency_ms,
        result.range_scan_p95_latency_ms,
        result.range_scan_p99_latency_ms,
        result.range_scan_min_latency_ms,
        result.range_scan_max_latency_ms,
        result.insert_p50_latency_ms,
        result.insert_p95_latency_ms,
        result.insert_p99_latency_ms,
        result.insert_min_latency_ms,
        result.insert_max_latency_ms,
        result.update_p50_latency_ms,
        result.update_p95_latency_ms,
        result.update_p99_latency_ms,
        result.update_min_latency_ms,
        result.update_max_latency_ms,
        result.app_overhead_p50_ms,
        result.app_overhead_p95_ms,
        result.app_overhead_p99_ms,
        test_id,
    ]

    await pool.execute_query(query, params=params)


async def enrich_query_executions_from_query_history(*, test_id: str) -> None:
    """
    Enrich QUERY_EXECUTIONS rows for a test using INFORMATION_SCHEMA.QUERY_HISTORY.

    We join by captured QUERY_ID (Snowflake query id) and populate Snowflake-side
    timing fields + derived APP_OVERHEAD_MS.
    """
    pool = snowflake_pool.get_default_pool()

    prefix = _results_prefix()

    # NOTE: INFORMATION_SCHEMA.QUERY_HISTORY requires constant (or parameter)
    # arguments for END_TIME_RANGE_* (subqueries are rejected). So we look up the
    # test window first, then bind the timestamps into the table function call.
    #
    # Also note TEST_RESULTS timestamps are stored as TIMESTAMP_NTZ; we treat them
    # as UTC (the app writes ISO timestamps in UTC).
    tr_rows = await pool.execute_query(
        f"""
        SELECT START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP())
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID = ?
        """,
        params=[test_id],
    )
    if not tr_rows:
        return

    start_ntz, end_ntz = tr_rows[0][0], tr_rows[0][1]
    # Snowflake connector may return datetime objects; accept both.
    if isinstance(start_ntz, str):
        start_dt = datetime.fromisoformat(start_ntz)
    else:
        start_dt = start_ntz
    if isinstance(end_ntz, str):
        end_dt = datetime.fromisoformat(end_ntz)
    else:
        end_dt = end_ntz

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)

    start_buf = (start_dt - timedelta(minutes=5)).isoformat()
    end_buf = (end_dt + timedelta(minutes=5)).isoformat()

    # NOTE: Keep RESULT_LIMIT at max allowable (10k) and restrict by query_tag to
    # avoid pulling unrelated queries.
    query = f"""
    MERGE INTO {prefix}.QUERY_EXECUTIONS tgt
    USING (
        SELECT
            QUERY_ID,
            TOTAL_ELAPSED_TIME::FLOAT AS SF_TOTAL_ELAPSED_MS,
            EXECUTION_TIME::FLOAT AS SF_EXECUTION_MS,
            COMPILATION_TIME::FLOAT AS SF_COMPILATION_MS,
            QUEUED_OVERLOAD_TIME::FLOAT AS SF_QUEUED_OVERLOAD_MS,
            QUEUED_PROVISIONING_TIME::FLOAT AS SF_QUEUED_PROVISIONING_MS,
            TRANSACTION_BLOCKED_TIME::FLOAT AS SF_TX_BLOCKED_MS,
            BYTES_SCANNED::BIGINT AS SF_BYTES_SCANNED,
            ROWS_PRODUCED::BIGINT AS SF_ROWS_PRODUCED
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
            END_TIME_RANGE_START=>TO_TIMESTAMP_LTZ(?),
            END_TIME_RANGE_END=>TO_TIMESTAMP_LTZ(?),
            RESULT_LIMIT=>10000
        ))
        WHERE QUERY_TAG = 'unistore_benchmark'
    ) src
    ON tgt.QUERY_ID = src.QUERY_ID
    AND tgt.TEST_ID = ?
    WHEN MATCHED THEN UPDATE SET
        SF_TOTAL_ELAPSED_MS = src.SF_TOTAL_ELAPSED_MS,
        SF_EXECUTION_MS = src.SF_EXECUTION_MS,
        SF_COMPILATION_MS = src.SF_COMPILATION_MS,
        SF_QUEUED_OVERLOAD_MS = src.SF_QUEUED_OVERLOAD_MS,
        SF_QUEUED_PROVISIONING_MS = src.SF_QUEUED_PROVISIONING_MS,
        SF_TX_BLOCKED_MS = src.SF_TX_BLOCKED_MS,
        SF_BYTES_SCANNED = src.SF_BYTES_SCANNED,
        SF_ROWS_PRODUCED = src.SF_ROWS_PRODUCED,
        APP_OVERHEAD_MS = IFF(
            tgt.APP_ELAPSED_MS IS NULL OR src.SF_TOTAL_ELAPSED_MS IS NULL,
            NULL,
            tgt.APP_ELAPSED_MS - src.SF_TOTAL_ELAPSED_MS
        );
    """

    await pool.execute_query(query, params=[start_buf, end_buf, test_id])


async def update_test_overhead_percentiles(*, test_id: str) -> None:
    """
    Compute overhead percentiles from QUERY_EXECUTIONS.APP_OVERHEAD_MS and store
    them on TEST_RESULTS (one-row summary table).
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()

    # NOTE: Snowflake does not support CTE + UPDATE in the way we need here.
    # Use scalar subqueries instead (still set-based, easy to reason about).
    query = f"""
    UPDATE {prefix}.TEST_RESULTS
    SET
        APP_OVERHEAD_P50_MS = (
            SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_OVERHEAD_MS)
            FROM {prefix}.QUERY_EXECUTIONS
            WHERE TEST_ID = ?
              AND APP_OVERHEAD_MS IS NOT NULL
        ),
        APP_OVERHEAD_P95_MS = (
            SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_OVERHEAD_MS)
            FROM {prefix}.QUERY_EXECUTIONS
            WHERE TEST_ID = ?
              AND APP_OVERHEAD_MS IS NOT NULL
        ),
        APP_OVERHEAD_P99_MS = (
            SELECT PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_OVERHEAD_MS)
            FROM {prefix}.QUERY_EXECUTIONS
            WHERE TEST_ID = ?
              AND APP_OVERHEAD_MS IS NOT NULL
        ),
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHERE TEST_ID = ?;
    """

    await pool.execute_query(query, params=[test_id, test_id, test_id, test_id])
