"""
API routes for persisted test results and running tests.

UI endpoints:
- History: GET /api/tests
- Comparison search: GET /api/tests/search?q=...
- Query executions (drilldown): GET /api/tests/{test_id}/query-executions
- Re-run: POST /api/tests/{test_id}/rerun
- Delete: DELETE /api/tests/{test_id}
- Run template: POST /api/tests/from-template/{template_id}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from backend.config import settings
from backend.connectors import snowflake_pool
from backend.core.test_registry import registry
from backend.api.error_handling import http_exception

router = APIRouter()
logger = logging.getLogger(__name__)


def _prefix() -> str:
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


def _to_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


async def _fetch_sf_execution_latency_summary(
    *, pool: Any, test_id: str
) -> dict[str, Any]:
    """
    Compute server-side SQL execution percentiles from QUERY_EXECUTIONS.

    This uses SF_EXECUTION_MS (INFORMATION_SCHEMA.QUERY_HISTORY.EXECUTION_TIME)
    which excludes client/network overhead.

    NOTE: This will raise if the underlying columns don't exist (e.g. older schema).
    Callers should catch and treat as "not available".
    """
    prefix = _prefix()

    # NOTE: Snowflake does not support FILTER(...) for ordered-set aggregates like
    # PERCENTILE_CONT the way we'd like. Use NULLing expressions (IFF) instead.
    # PERCENTILE_CONT ignores NULLs.

    # Reads are POINT_LOOKUP + RANGE_SCAN; writes are INSERT + UPDATE.
    query = f"""
    SELECT
        COUNT(*) AS SF_LATENCY_SAMPLE_COUNT,

        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY SF_EXECUTION_MS) AS SF_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY SF_EXECUTION_MS) AS SF_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY SF_EXECUTION_MS) AS SF_P99_LATENCY_MS,
        MIN(SF_EXECUTION_MS) AS SF_MIN_LATENCY_MS,
        MAX(SF_EXECUTION_MS) AS SF_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN'), SF_EXECUTION_MS, NULL)
        ) AS SF_READ_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN'), SF_EXECUTION_MS, NULL)
        ) AS SF_READ_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN'), SF_EXECUTION_MS, NULL)
        ) AS SF_READ_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN'), SF_EXECUTION_MS, NULL))
            AS SF_READ_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN'), SF_EXECUTION_MS, NULL))
            AS SF_READ_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('INSERT', 'UPDATE'), SF_EXECUTION_MS, NULL)
        ) AS SF_WRITE_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('INSERT', 'UPDATE'), SF_EXECUTION_MS, NULL)
        ) AS SF_WRITE_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND IN ('INSERT', 'UPDATE'), SF_EXECUTION_MS, NULL)
        ) AS SF_WRITE_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND IN ('INSERT', 'UPDATE'), SF_EXECUTION_MS, NULL))
            AS SF_WRITE_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND IN ('INSERT', 'UPDATE'), SF_EXECUTION_MS, NULL))
            AS SF_WRITE_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'POINT_LOOKUP', SF_EXECUTION_MS, NULL)
        ) AS SF_POINT_LOOKUP_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'POINT_LOOKUP', SF_EXECUTION_MS, NULL)
        ) AS SF_POINT_LOOKUP_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'POINT_LOOKUP', SF_EXECUTION_MS, NULL)
        ) AS SF_POINT_LOOKUP_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND = 'POINT_LOOKUP', SF_EXECUTION_MS, NULL))
            AS SF_POINT_LOOKUP_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND = 'POINT_LOOKUP', SF_EXECUTION_MS, NULL))
            AS SF_POINT_LOOKUP_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'RANGE_SCAN', SF_EXECUTION_MS, NULL)
        ) AS SF_RANGE_SCAN_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'RANGE_SCAN', SF_EXECUTION_MS, NULL)
        ) AS SF_RANGE_SCAN_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'RANGE_SCAN', SF_EXECUTION_MS, NULL)
        ) AS SF_RANGE_SCAN_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND = 'RANGE_SCAN', SF_EXECUTION_MS, NULL))
            AS SF_RANGE_SCAN_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND = 'RANGE_SCAN', SF_EXECUTION_MS, NULL))
            AS SF_RANGE_SCAN_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'INSERT', SF_EXECUTION_MS, NULL)
        ) AS SF_INSERT_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'INSERT', SF_EXECUTION_MS, NULL)
        ) AS SF_INSERT_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'INSERT', SF_EXECUTION_MS, NULL)
        ) AS SF_INSERT_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND = 'INSERT', SF_EXECUTION_MS, NULL)) AS SF_INSERT_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND = 'INSERT', SF_EXECUTION_MS, NULL)) AS SF_INSERT_MAX_LATENCY_MS,

        PERCENTILE_CONT(0.50) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'UPDATE', SF_EXECUTION_MS, NULL)
        ) AS SF_UPDATE_P50_LATENCY_MS,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'UPDATE', SF_EXECUTION_MS, NULL)
        ) AS SF_UPDATE_P95_LATENCY_MS,
        PERCENTILE_CONT(0.99) WITHIN GROUP (
            ORDER BY IFF(QUERY_KIND = 'UPDATE', SF_EXECUTION_MS, NULL)
        ) AS SF_UPDATE_P99_LATENCY_MS,
        MIN(IFF(QUERY_KIND = 'UPDATE', SF_EXECUTION_MS, NULL)) AS SF_UPDATE_MIN_LATENCY_MS,
        MAX(IFF(QUERY_KIND = 'UPDATE', SF_EXECUTION_MS, NULL)) AS SF_UPDATE_MAX_LATENCY_MS
    FROM {prefix}.QUERY_EXECUTIONS
    WHERE TEST_ID = ?
      AND COALESCE(WARMUP, FALSE) = FALSE
      AND SUCCESS = TRUE
      AND SF_EXECUTION_MS IS NOT NULL
    """
    rows = await pool.execute_query(query, params=[test_id])
    if not rows:
        return {
            "sf_latency_available": False,
            "sf_latency_sample_count": 0,
        }

    r = rows[0]
    sample_count = int(r[0] or 0)
    payload = {
        "sf_latency_available": sample_count > 0,
        "sf_latency_sample_count": sample_count,
        "sf_p50_latency_ms": _to_float_or_none(r[1]),
        "sf_p95_latency_ms": _to_float_or_none(r[2]),
        "sf_p99_latency_ms": _to_float_or_none(r[3]),
        "sf_min_latency_ms": _to_float_or_none(r[4]),
        "sf_max_latency_ms": _to_float_or_none(r[5]),
        "sf_read_p50_latency_ms": _to_float_or_none(r[6]),
        "sf_read_p95_latency_ms": _to_float_or_none(r[7]),
        "sf_read_p99_latency_ms": _to_float_or_none(r[8]),
        "sf_read_min_latency_ms": _to_float_or_none(r[9]),
        "sf_read_max_latency_ms": _to_float_or_none(r[10]),
        "sf_write_p50_latency_ms": _to_float_or_none(r[11]),
        "sf_write_p95_latency_ms": _to_float_or_none(r[12]),
        "sf_write_p99_latency_ms": _to_float_or_none(r[13]),
        "sf_write_min_latency_ms": _to_float_or_none(r[14]),
        "sf_write_max_latency_ms": _to_float_or_none(r[15]),
        "sf_point_lookup_p50_latency_ms": _to_float_or_none(r[16]),
        "sf_point_lookup_p95_latency_ms": _to_float_or_none(r[17]),
        "sf_point_lookup_p99_latency_ms": _to_float_or_none(r[18]),
        "sf_point_lookup_min_latency_ms": _to_float_or_none(r[19]),
        "sf_point_lookup_max_latency_ms": _to_float_or_none(r[20]),
        "sf_range_scan_p50_latency_ms": _to_float_or_none(r[21]),
        "sf_range_scan_p95_latency_ms": _to_float_or_none(r[22]),
        "sf_range_scan_p99_latency_ms": _to_float_or_none(r[23]),
        "sf_range_scan_min_latency_ms": _to_float_or_none(r[24]),
        "sf_range_scan_max_latency_ms": _to_float_or_none(r[25]),
        "sf_insert_p50_latency_ms": _to_float_or_none(r[26]),
        "sf_insert_p95_latency_ms": _to_float_or_none(r[27]),
        "sf_insert_p99_latency_ms": _to_float_or_none(r[28]),
        "sf_insert_min_latency_ms": _to_float_or_none(r[29]),
        "sf_insert_max_latency_ms": _to_float_or_none(r[30]),
        "sf_update_p50_latency_ms": _to_float_or_none(r[31]),
        "sf_update_p95_latency_ms": _to_float_or_none(r[32]),
        "sf_update_p99_latency_ms": _to_float_or_none(r[33]),
        "sf_update_min_latency_ms": _to_float_or_none(r[34]),
        "sf_update_max_latency_ms": _to_float_or_none(r[35]),
    }
    return payload


class RunTemplateResponse(BaseModel):
    test_id: str
    dashboard_url: str


@router.post(
    "/from-template/{template_id}",
    response_model=RunTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_from_template(template_id: str) -> RunTemplateResponse:
    try:
        # Prepare only: do not start executing until explicitly started from the dashboard.
        running = await registry.start_from_template(template_id, auto_start=False)
        return RunTemplateResponse(
            test_id=running.test_id, dashboard_url=f"/dashboard/{running.test_id}"
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Template not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise http_exception("start test", e)


@router.post("/{test_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_prepared_test(test_id: str) -> dict[str, Any]:
    try:
        running = await registry.start_prepared(test_id)
        return {"test_id": running.test_id, "status": running.status}
    except KeyError:
        raise HTTPException(status_code=404, detail="Test not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise http_exception("start prepared test", e)


@router.post("/{test_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_test(test_id: str) -> dict[str, Any]:
    try:
        running = await registry.stop(test_id)
        return {"test_id": running.test_id, "status": running.status}
    except KeyError:
        raise HTTPException(status_code=404, detail="Test not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise http_exception("stop test", e)


@router.get("")
async def list_tests(
    page: int = 1,
    page_size: int = 20,
    table_type: str = "",
    warehouse_size: str = "",
    status_filter: str = Query("", alias="status"),
    date_range: str = "all",
) -> dict[str, Any]:
    try:
        pool = snowflake_pool.get_default_pool()

        where_clauses: list[str] = []
        params: list[Any] = []

        if table_type:
            where_clauses.append("TABLE_TYPE = ?")
            params.append(table_type.upper())
        if warehouse_size:
            where_clauses.append("WAREHOUSE_SIZE = ?")
            params.append(warehouse_size.upper())
        if status_filter:
            where_clauses.append("STATUS = ?")
            params.append(status_filter.upper())

        if date_range in {"today", "week", "month"}:
            days = {"today": 1, "week": 7, "month": 30}[date_range]
            where_clauses.append("START_TIME >= DATEADD(day, ?, CURRENT_TIMESTAMP())")
            params.append(-days)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        offset = max(page - 1, 0) * page_size
        query = f"""
        SELECT
            TEST_ID,
            TEST_NAME,
            TABLE_TYPE,
            WAREHOUSE_SIZE,
            START_TIME,
            OPERATIONS_PER_SECOND,
            P95_LATENCY_MS,
            P99_LATENCY_MS,
            ERROR_RATE,
            STATUS,
            CONCURRENT_CONNECTIONS,
            DURATION_SECONDS
        FROM {_prefix()}.TEST_RESULTS
        {where_sql}
        ORDER BY START_TIME DESC
        LIMIT ? OFFSET ?
        """
        rows = await pool.execute_query(query, params=[*params, page_size, offset])

        count_query = f"SELECT COUNT(*) FROM {_prefix()}.TEST_RESULTS {where_sql}"
        count_rows = await pool.execute_query(count_query, params=params)
        total = int(count_rows[0][0]) if count_rows else 0
        total_pages = max((total + page_size - 1) // page_size, 1)

        results = []
        for row in rows:
            (
                test_id,
                test_name,
                table_type_db,
                wh_size,
                created_at,
                ops,
                p95,
                p99,
                err_rate,
                status_db,
                concurrency,
                duration,
            ) = row
            results.append(
                {
                    "test_id": test_id,
                    "test_name": test_name,
                    "table_type": table_type_db,
                    "warehouse_size": wh_size,
                    "created_at": created_at.isoformat()
                    if hasattr(created_at, "isoformat")
                    else str(created_at),
                    "ops_per_sec": float(ops or 0),
                    "p95_latency": float(p95 or 0),
                    "p99_latency": float(p99 or 0),
                    "error_rate": float(err_rate or 0) * 100.0,
                    "status": status_db,
                    "concurrent_connections": int(concurrency or 0),
                    "duration": float(duration or 0),
                }
            )

        return {"results": results, "total_pages": total_pages}

    except Exception as e:
        raise http_exception("list tests", e)


@router.get("/search")
async def search_tests(q: str) -> dict[str, Any]:
    try:
        pool = snowflake_pool.get_default_pool()
        like = f"%{q.lower()}%"
        query = f"""
        SELECT
            TEST_ID,
            TEST_NAME,
            TABLE_TYPE,
            WAREHOUSE_SIZE,
            START_TIME,
            OPERATIONS_PER_SECOND,
            P50_LATENCY_MS,
            P95_LATENCY_MS,
            P99_LATENCY_MS,
            ERROR_RATE
        FROM {_prefix()}.TEST_RESULTS
        WHERE LOWER(TEST_NAME) LIKE ?
        ORDER BY START_TIME DESC
        LIMIT 25
        """
        rows = await pool.execute_query(query, params=[like])
        results = []
        for row in rows:
            (
                test_id,
                test_name,
                table_type_db,
                wh_size,
                created_at,
                ops,
                p50,
                p95,
                p99,
                err_rate,
            ) = row
            results.append(
                {
                    "test_id": test_id,
                    "test_name": test_name,
                    "table_type": table_type_db,
                    "warehouse_size": wh_size,
                    "created_at": created_at.isoformat()
                    if hasattr(created_at, "isoformat")
                    else str(created_at),
                    "ops_per_sec": float(ops or 0),
                    "p50_latency": float(p50 or 0),
                    "p95_latency": float(p95 or 0),
                    "p99_latency": float(p99 or 0),
                    "error_rate": float(err_rate or 0) * 100.0,
                    "duration": 0,
                }
            )
        return {"results": results}
    except Exception as e:
        raise http_exception("search tests", e)


@router.get("/{test_id}")
async def get_test(test_id: str) -> dict[str, Any]:
    try:
        pool = snowflake_pool.get_default_pool()
        # Workload mix helper fields (templates normalize to workload_type=CUSTOM).
        def _coerce_pct(v: Any) -> int:
            try:
                return int(float(v))
            except Exception:
                return 0

        def _pct_from_dict(d: Any, key: str) -> int:
            if not isinstance(d, dict):
                return 0
            return _coerce_pct(d.get(key) or 0)

        def _pct_from_custom_queries(queries: Any) -> dict[str, int]:
            out = {"POINT_LOOKUP": 0, "RANGE_SCAN": 0, "INSERT": 0, "UPDATE": 0}
            if not queries:
                return out

            items = queries if isinstance(queries, list) else [queries]
            for q in items:
                if not isinstance(q, dict):
                    continue
                kind = str(q.get("query_kind") or "").upper()
                if kind in out:
                    out[kind] = _coerce_pct(q.get("weight_pct") or 0)
            return out

        query = f"""
        SELECT
            TEST_ID,
            TEST_NAME,
            SCENARIO_NAME,
            TABLE_NAME,
            TABLE_TYPE,
            WAREHOUSE,
            WAREHOUSE_SIZE,
            STATUS,
            START_TIME,
            END_TIME,
            DURATION_SECONDS,
            CONCURRENT_CONNECTIONS,
            TEST_CONFIG,
            TOTAL_OPERATIONS,
            READ_OPERATIONS,
            WRITE_OPERATIONS,
            FAILED_OPERATIONS,
            OPERATIONS_PER_SECOND,
            READS_PER_SECOND,
            WRITES_PER_SECOND,
            ROWS_READ,
            ROWS_WRITTEN,
            AVG_LATENCY_MS,
            P50_LATENCY_MS,
            P90_LATENCY_MS,
            P95_LATENCY_MS,
            P99_LATENCY_MS,
            MIN_LATENCY_MS,
            MAX_LATENCY_MS,
            READ_P50_LATENCY_MS,
            READ_P95_LATENCY_MS,
            READ_P99_LATENCY_MS,
            READ_MIN_LATENCY_MS,
            READ_MAX_LATENCY_MS,
            WRITE_P50_LATENCY_MS,
            WRITE_P95_LATENCY_MS,
            WRITE_P99_LATENCY_MS,
            WRITE_MIN_LATENCY_MS,
            WRITE_MAX_LATENCY_MS,
            POINT_LOOKUP_P50_LATENCY_MS,
            POINT_LOOKUP_P95_LATENCY_MS,
            POINT_LOOKUP_P99_LATENCY_MS,
            POINT_LOOKUP_MIN_LATENCY_MS,
            POINT_LOOKUP_MAX_LATENCY_MS,
            RANGE_SCAN_P50_LATENCY_MS,
            RANGE_SCAN_P95_LATENCY_MS,
            RANGE_SCAN_P99_LATENCY_MS,
            RANGE_SCAN_MIN_LATENCY_MS,
            RANGE_SCAN_MAX_LATENCY_MS,
            INSERT_P50_LATENCY_MS,
            INSERT_P95_LATENCY_MS,
            INSERT_P99_LATENCY_MS,
            INSERT_MIN_LATENCY_MS,
            INSERT_MAX_LATENCY_MS,
            UPDATE_P50_LATENCY_MS,
            UPDATE_P95_LATENCY_MS,
            UPDATE_P99_LATENCY_MS,
            UPDATE_MIN_LATENCY_MS,
            UPDATE_MAX_LATENCY_MS
        FROM {_prefix()}.TEST_RESULTS
        WHERE TEST_ID = ?
        """
        rows = await pool.execute_query(query, params=[test_id])
        if not rows:
            # Fallback to in-memory registry for freshly prepared tests that
            # haven't been persisted to results tables yet.
            running = await registry.get(test_id)
            if running is not None:
                cfg = running.template_config or {}
                pcts = _pct_from_custom_queries(running.scenario.custom_queries)
                table_full = (
                    f"{cfg.get('database')}.{cfg.get('schema')}.{cfg.get('table_name')}"
                    if cfg.get("database")
                    and cfg.get("schema")
                    and cfg.get("table_name")
                    else running.scenario.table_configs[0].name
                )
                return {
                    "test_id": test_id,
                    "test_name": running.template_name,
                    "template_id": running.template_id,
                    "template_name": running.template_name,
                    "scenario_name": running.scenario.name,
                    "table_type": str(
                        running.scenario.table_configs[0].table_type
                    ).upper(),
                    "table_name": running.scenario.table_configs[0].name,
                    "table_full_name": table_full,
                    "warehouse": cfg.get("warehouse_name"),
                    "warehouse_size": cfg.get("warehouse_size"),
                    "status": running.status,
                    "start_time": running.created_at.isoformat(),
                    "end_time": None,
                    "duration_seconds": float(
                        (running.scenario.duration_seconds or 0)
                        + (running.scenario.warmup_seconds or 0)
                    ),
                    "concurrent_connections": int(
                        running.scenario.concurrent_connections or 0
                    ),
                    "workload_type": str(running.scenario.workload_type),
                    "custom_point_lookup_pct": _pct_from_dict(
                        cfg, "custom_point_lookup_pct"
                    )
                    or pcts["POINT_LOOKUP"],
                    "custom_range_scan_pct": _pct_from_dict(cfg, "custom_range_scan_pct")
                    or pcts["RANGE_SCAN"],
                    "custom_insert_pct": _pct_from_dict(cfg, "custom_insert_pct")
                    or pcts["INSERT"],
                    "custom_update_pct": _pct_from_dict(cfg, "custom_update_pct")
                    or pcts["UPDATE"],
                }
            raise HTTPException(status_code=404, detail="Test not found")

        (
            _,
            test_name,
            scenario_name,
            table_name,
            table_type,
            warehouse,
            warehouse_size,
            status_db,
            start_time,
            end_time,
            duration_seconds,
            concurrency,
            test_config,
            total_operations,
            read_operations,
            write_operations,
            failed_operations,
            operations_per_second,
            reads_per_second,
            writes_per_second,
            rows_read,
            rows_written,
            avg_latency_ms,
            p50_latency_ms,
            p90_latency_ms,
            p95_latency_ms,
            p99_latency_ms,
            min_latency_ms,
            max_latency_ms,
            read_p50_latency_ms,
            read_p95_latency_ms,
            read_p99_latency_ms,
            read_min_latency_ms,
            read_max_latency_ms,
            write_p50_latency_ms,
            write_p95_latency_ms,
            write_p99_latency_ms,
            write_min_latency_ms,
            write_max_latency_ms,
            point_lookup_p50_latency_ms,
            point_lookup_p95_latency_ms,
            point_lookup_p99_latency_ms,
            point_lookup_min_latency_ms,
            point_lookup_max_latency_ms,
            range_scan_p50_latency_ms,
            range_scan_p95_latency_ms,
            range_scan_p99_latency_ms,
            range_scan_min_latency_ms,
            range_scan_max_latency_ms,
            insert_p50_latency_ms,
            insert_p95_latency_ms,
            insert_p99_latency_ms,
            insert_min_latency_ms,
            insert_max_latency_ms,
            update_p50_latency_ms,
            update_p95_latency_ms,
            update_p99_latency_ms,
            update_min_latency_ms,
            update_max_latency_ms,
        ) = rows[0]

        cfg = test_config
        if isinstance(cfg, str):
            cfg = json.loads(cfg)

        template_name = cfg.get("template_name") if isinstance(cfg, dict) else None
        template_id = cfg.get("template_id") if isinstance(cfg, dict) else None
        template_cfg = cfg.get("template_config") if isinstance(cfg, dict) else None
        workload_type = None
        if isinstance(template_cfg, dict):
            workload_type = template_cfg.get("workload_type")

        payload: dict[str, Any] = {
            "test_id": test_id,
            "test_name": test_name,
            "template_id": template_id,
            "template_name": template_name,
            "scenario_name": scenario_name,
            "table_type": table_type,
            "table_name": table_name,
            "table_full_name": (
                f"{template_cfg.get('database')}.{template_cfg.get('schema')}.{template_cfg.get('table_name')}"
                if isinstance(template_cfg, dict)
                else table_name
            ),
            "warehouse": warehouse,
            "warehouse_size": warehouse_size,
            "status": status_db,
            "start_time": start_time.isoformat()
            if hasattr(start_time, "isoformat")
            else str(start_time),
            "end_time": end_time.isoformat()
            if end_time and hasattr(end_time, "isoformat")
            else None,
            "duration_seconds": float(duration_seconds or 0),
            "concurrent_connections": int(concurrency or 0),
            "workload_type": workload_type,
            "custom_point_lookup_pct": _pct_from_dict(
                template_cfg, "custom_point_lookup_pct"
            ),
            "custom_range_scan_pct": _pct_from_dict(
                template_cfg, "custom_range_scan_pct"
            ),
            "custom_insert_pct": _pct_from_dict(template_cfg, "custom_insert_pct"),
            "custom_update_pct": _pct_from_dict(template_cfg, "custom_update_pct"),
            "total_operations": int(total_operations or 0),
            "read_operations": int(read_operations or 0),
            "write_operations": int(write_operations or 0),
            "failed_operations": int(failed_operations or 0),
            "operations_per_second": float(operations_per_second or 0),
            "reads_per_second": float(reads_per_second or 0),
            "writes_per_second": float(writes_per_second or 0),
            "rows_read": int(rows_read or 0),
            "rows_written": int(rows_written or 0),
            "avg_latency_ms": float(avg_latency_ms or 0),
            "p50_latency_ms": float(p50_latency_ms or 0),
            "p90_latency_ms": float(p90_latency_ms or 0),
            "p95_latency_ms": float(p95_latency_ms or 0),
            "p99_latency_ms": float(p99_latency_ms or 0),
            "min_latency_ms": float(min_latency_ms or 0),
            "max_latency_ms": float(max_latency_ms or 0),
            "read_p50_latency_ms": float(read_p50_latency_ms or 0),
            "read_p95_latency_ms": float(read_p95_latency_ms or 0),
            "read_p99_latency_ms": float(read_p99_latency_ms or 0),
            "read_min_latency_ms": float(read_min_latency_ms or 0),
            "read_max_latency_ms": float(read_max_latency_ms or 0),
            "write_p50_latency_ms": float(write_p50_latency_ms or 0),
            "write_p95_latency_ms": float(write_p95_latency_ms or 0),
            "write_p99_latency_ms": float(write_p99_latency_ms or 0),
            "write_min_latency_ms": float(write_min_latency_ms or 0),
            "write_max_latency_ms": float(write_max_latency_ms or 0),
            "point_lookup_p50_latency_ms": float(point_lookup_p50_latency_ms or 0),
            "point_lookup_p95_latency_ms": float(point_lookup_p95_latency_ms or 0),
            "point_lookup_p99_latency_ms": float(point_lookup_p99_latency_ms or 0),
            "point_lookup_min_latency_ms": float(point_lookup_min_latency_ms or 0),
            "point_lookup_max_latency_ms": float(point_lookup_max_latency_ms or 0),
            "range_scan_p50_latency_ms": float(range_scan_p50_latency_ms or 0),
            "range_scan_p95_latency_ms": float(range_scan_p95_latency_ms or 0),
            "range_scan_p99_latency_ms": float(range_scan_p99_latency_ms or 0),
            "range_scan_min_latency_ms": float(range_scan_min_latency_ms or 0),
            "range_scan_max_latency_ms": float(range_scan_max_latency_ms or 0),
            "insert_p50_latency_ms": float(insert_p50_latency_ms or 0),
            "insert_p95_latency_ms": float(insert_p95_latency_ms or 0),
            "insert_p99_latency_ms": float(insert_p99_latency_ms or 0),
            "insert_min_latency_ms": float(insert_min_latency_ms or 0),
            "insert_max_latency_ms": float(insert_max_latency_ms or 0),
            "update_p50_latency_ms": float(update_p50_latency_ms or 0),
            "update_p95_latency_ms": float(update_p95_latency_ms or 0),
            "update_p99_latency_ms": float(update_p99_latency_ms or 0),
            "update_min_latency_ms": float(update_min_latency_ms or 0),
            "update_max_latency_ms": float(update_max_latency_ms or 0),
        }

        # Best-effort SQL-execution latency summaries (may be missing for running tests,
        # cancelled runs, or older schemas without SF_* columns).
        try:
            payload.update(
                await _fetch_sf_execution_latency_summary(pool=pool, test_id=test_id)
            )
        except Exception as e:
            logger.debug(
                "Failed to compute SF execution latency summary for test %s: %s",
                test_id,
                e,
            )
            payload.update(
                {"sf_latency_available": False, "sf_latency_sample_count": 0}
            )

        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("get test", e)


@router.get("/{test_id}/query-executions")
async def list_query_executions(
    test_id: str,
    kinds: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: str = "sf_execution_ms",
    direction: str = "desc",
) -> dict[str, Any]:
    """
    List persisted per-operation query executions for a test.

    Defaults match the percentile calculations:
    - Excludes warmup operations
    - Includes only successful operations

    Query params:
    - kinds: comma-separated QUERY_KIND list (e.g. POINT_LOOKUP,RANGE_SCAN)
    - page, page_size: pagination
    - sort: one of [sf_execution_ms, app_elapsed_ms, start_time]
    - direction: asc|desc
    """
    try:
        pool = snowflake_pool.get_default_pool()
        prefix = _prefix()

        where_clauses: list[str] = [
            "TEST_ID = ?",
            "COALESCE(WARMUP, FALSE) = FALSE",
            "SUCCESS = TRUE",
        ]
        params: list[Any] = [test_id]

        kind_list = [
            k.strip().upper()
            for k in (kinds or "").split(",")
            if k is not None and k.strip()
        ]
        if kind_list:
            where_clauses.append(f"QUERY_KIND IN ({', '.join(['?'] * len(kind_list))})")
            params.extend(kind_list)

        sort_map = {
            "sf_execution_ms": "SF_EXECUTION_MS",
            "app_elapsed_ms": "APP_ELAPSED_MS",
            "start_time": "START_TIME",
        }
        sort_key = (sort or "").strip().lower()
        sort_col = sort_map.get(sort_key)
        if not sort_col:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort '{sort}'. Must be one of {sorted(sort_map.keys())}.",
            )

        dir_key = (direction or "").strip().lower()
        if dir_key not in {"asc", "desc"}:
            raise HTTPException(
                status_code=400, detail="Invalid direction. Must be 'asc' or 'desc'."
            )
        dir_sql = dir_key.upper()

        where_sql = "WHERE " + " AND ".join(where_clauses)
        offset = max(page - 1, 0) * page_size

        query = f"""
        SELECT
            EXECUTION_ID,
            QUERY_ID,
            QUERY_KIND,
            START_TIME,
            END_TIME,
            DURATION_MS,
            APP_ELAPSED_MS,
            SF_EXECUTION_MS,
            ROWS_AFFECTED,
            WAREHOUSE
        FROM {prefix}.QUERY_EXECUTIONS
        {where_sql}
        ORDER BY {sort_col} {dir_sql} NULLS LAST, START_TIME DESC
        LIMIT ? OFFSET ?
        """
        rows = await pool.execute_query(query, params=[*params, page_size, offset])

        count_query = f"SELECT COUNT(*) FROM {prefix}.QUERY_EXECUTIONS {where_sql}"
        count_rows = await pool.execute_query(count_query, params=params)
        total = int(count_rows[0][0]) if count_rows else 0
        total_pages = max((total + page_size - 1) // page_size, 1)

        results: list[dict[str, Any]] = []
        for row in rows:
            (
                execution_id,
                query_id,
                query_kind,
                start_time,
                end_time,
                duration_ms,
                app_elapsed_ms,
                sf_execution_ms,
                rows_affected,
                warehouse,
            ) = row

            results.append(
                {
                    "execution_id": execution_id,
                    "query_id": query_id,
                    "query_kind": query_kind,
                    "start_time": start_time.isoformat()
                    if hasattr(start_time, "isoformat")
                    else str(start_time),
                    "end_time": end_time.isoformat()
                    if hasattr(end_time, "isoformat")
                    else str(end_time),
                    "duration_ms": _to_float_or_none(duration_ms),
                    "app_elapsed_ms": _to_float_or_none(app_elapsed_ms),
                    "sf_execution_ms": _to_float_or_none(sf_execution_ms),
                    "rows_affected": int(rows_affected)
                    if rows_affected is not None
                    else None,
                    "warehouse": warehouse,
                }
            )

        return {"results": results, "total_pages": total_pages}
    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("list query executions", e)


@router.get("/{test_id}/logs")
async def get_test_logs(
    test_id: str,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    Fetch persisted per-test logs (and in-memory logs for running tests).
    """
    try:
        # Prefer in-memory logs for running/prepared tests so refreshes don't lose context.
        running = await registry.get(test_id)
        if running is not None and running.log_buffer:
            logs = list(running.log_buffer)
            logs.sort(key=lambda r: int(r.get("seq") or 0))
            return {"test_id": test_id, "logs": logs[offset : offset + limit]}

        pool = snowflake_pool.get_default_pool()
        query = f"""
        SELECT
            LOG_ID,
            TEST_ID,
            SEQ,
            TIMESTAMP,
            LEVEL,
            LOGGER,
            MESSAGE,
            EXCEPTION
        FROM {_prefix()}.TEST_LOGS
        WHERE TEST_ID = ?
        ORDER BY SEQ ASC
        LIMIT ? OFFSET ?
        """
        rows = await pool.execute_query(query, params=[test_id, limit, offset])

        logs: list[dict[str, Any]] = []
        for row in rows:
            (
                log_id,
                test_id_db,
                seq,
                ts,
                level,
                logger_name,
                message,
                exc,
            ) = row
            logs.append(
                {
                    "kind": "log",
                    "log_id": log_id,
                    "test_id": test_id_db,
                    "seq": int(seq or 0),
                    "timestamp": ts.isoformat()
                    if hasattr(ts, "isoformat")
                    else str(ts),
                    "level": level,
                    "logger": logger_name,
                    "message": message,
                    "exception": exc,
                }
            )

        return {"test_id": test_id, "logs": logs}
    except Exception as e:
        # If logs table isn't present yet, or any query fails, degrade gracefully
        # for the dashboard rather than hard-erroring.
        msg = str(e).lower()
        if "does not exist" in msg or "unknown table" in msg:
            return {"test_id": test_id, "logs": []}
        raise http_exception("get test logs", e)


@router.get("/{test_id}/metrics")
async def get_test_metrics(test_id: str) -> dict[str, Any]:
    """
    Fetch historical time-series metrics snapshots for a completed test.
    This is used to populate charts in the dashboard for historical tests.
    """
    try:
        pool = snowflake_pool.get_default_pool()
        query = f"""
        SELECT
            TIMESTAMP,
            ELAPSED_SECONDS,
            OPERATIONS_PER_SECOND,
            P50_LATENCY_MS,
            P95_LATENCY_MS,
            P99_LATENCY_MS
        FROM {_prefix()}.METRICS_SNAPSHOTS
        WHERE TEST_ID = ?
        ORDER BY TIMESTAMP ASC
        """
        rows = await pool.execute_query(query, params=[test_id])

        snapshots = []
        for row in rows:
            timestamp, elapsed, ops_per_sec, p50, p95, p99 = row
            snapshots.append(
                {
                    "timestamp": timestamp.isoformat()
                    if hasattr(timestamp, "isoformat")
                    else str(timestamp),
                    "elapsed_seconds": float(elapsed or 0),
                    "ops_per_sec": float(ops_per_sec or 0),
                    "p50_latency": float(p50 or 0),
                    "p95_latency": float(p95 or 0),
                    "p99_latency": float(p99 or 0),
                }
            )

        return {"test_id": test_id, "snapshots": snapshots, "count": len(snapshots)}
    except Exception as e:
        raise http_exception("get test metrics", e)


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(test_id: str) -> None:
    try:
        pool = snowflake_pool.get_default_pool()
        await pool.execute_query(
            f"DELETE FROM {_prefix()}.METRICS_SNAPSHOTS WHERE TEST_ID = ?",
            params=[test_id],
        )
        await pool.execute_query(
            f"DELETE FROM {_prefix()}.QUERY_EXECUTIONS WHERE TEST_ID = ?",
            params=[test_id],
        )
        await pool.execute_query(
            f"DELETE FROM {_prefix()}.TEST_RESULTS WHERE TEST_ID = ?",
            params=[test_id],
        )
        return None
    except Exception as e:
        raise http_exception("delete test", e)


@router.post("/{test_id}/rerun")
async def rerun_test(test_id: str) -> dict[str, Any]:
    try:
        pool = snowflake_pool.get_default_pool()
        rows = await pool.execute_query(
            f"SELECT TEST_CONFIG FROM {_prefix()}.TEST_RESULTS WHERE TEST_ID = ?",
            params=[test_id],
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Test not found")

        test_config = rows[0][0]
        if isinstance(test_config, str):
            test_config = json.loads(test_config)

        template_id = test_config.get("template_id") or test_config.get(
            "template", {}
        ).get("template_id")
        if not template_id:
            raise HTTPException(
                status_code=400, detail="Cannot rerun: missing template_id"
            )

        running = await registry.start_from_template(str(template_id))
        return {"new_test_id": running.test_id}
    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("rerun test", e)
