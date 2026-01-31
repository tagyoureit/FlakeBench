"""
Unistore Benchmark - Main Application Entry Point

FastAPI application with real-time WebSocket support for database performance benchmarking.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import asyncio
import json
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
import logging

from backend.config import settings
from backend.core import results_store
from backend.core.test_registry import registry
from backend.connectors import snowflake_pool

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE)
        if settings.LOG_FILE
        else logging.NullHandler(),
    ],
)

# Suppress verbose Snowflake connector internal logging (connection handshake details)
logging.getLogger("snowflake.connector.connection").setLevel(logging.WARNING)
logging.getLogger("snowflake.connector.network").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Snowsight link support (derived from Snowflake session context).
_snowsight_org_account_path: str | None = None
_snowsight_org_account_lock = asyncio.Lock()


async def _get_snowsight_org_account_path() -> str:
    """
    Resolve the Snowsight URL path segment: "<ORG>/<ACCOUNT>".

    This is fetched from Snowflake once per process (cached) using:
      SELECT CURRENT_ORGANIZATION_NAME() || '/' || CURRENT_ACCOUNT_NAME();
    """
    global _snowsight_org_account_path

    if _snowsight_org_account_path is not None:
        return _snowsight_org_account_path

    async with _snowsight_org_account_lock:
        if _snowsight_org_account_path is not None:
            return _snowsight_org_account_path

        try:
            from backend.connectors import snowflake_pool

            pool = snowflake_pool.get_default_pool()
            rows = await pool.execute_query(
                "SELECT CURRENT_ORGANIZATION_NAME() || '/' || CURRENT_ACCOUNT_NAME()"
            )
            value = str(rows[0][0]).strip() if rows and rows[0] and rows[0][0] else ""
            _snowsight_org_account_path = value
        except Exception as e:
            logger.debug("Failed to resolve Snowsight org/account: %s", e)
            _snowsight_org_account_path = ""

        return _snowsight_org_account_path


# Base directory for templates and static files
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - handles startup and shutdown events.
    """
    # Startup
    logger.info("🚀 Unistore Benchmark starting up...")
    logger.info(f"📁 Templates directory: {TEMPLATES_DIR}")
    logger.info(f"📁 Static files directory: {STATIC_DIR}")
    logger.info(
        f"🔧 Environment: {'Development' if settings.APP_DEBUG else 'Production'}"
    )

    # Initialize database connection pools
    try:
        from backend.connectors import snowflake_pool, postgres_pool

        logger.info("📊 Initializing Snowflake connection pool...")
        sf_pool = snowflake_pool.get_default_pool()
        await sf_pool.initialize()
        logger.info("✅ Snowflake pool initialized")

        if settings.ENABLE_POSTGRES and settings.POSTGRES_CONNECT_ON_STARTUP:
            logger.info("🐘 Initializing Postgres connection pool...")
            pg_pool = postgres_pool.get_default_pool()
            await pg_pool.initialize()
            logger.info("✅ Postgres pool initialized")
        elif settings.ENABLE_POSTGRES:
            logger.info(
                "🐘 Postgres enabled but not connecting on startup "
                "(set POSTGRES_CONNECT_ON_STARTUP=true to initialize at boot)"
            )

    except Exception as e:
        logger.error(f"❌ Failed to initialize connection pools: {e}")
        logger.warning("⚠️  Application starting without database connections")

    # TODO: Load test templates from config

    yield

    # Shutdown
    logger.info("🛑 Unistore Benchmark shutting down...")

    # Cancel in-flight benchmark tasks (important for `--reload`)
    try:
        await registry.shutdown(timeout_seconds=5.0)
    except Exception as e:
        logger.warning("Registry shutdown encountered an error: %s", e)

    # Close database connections
    try:
        from backend.connectors import snowflake_pool, postgres_pool

        logger.info("Closing database connection pools...")
        await snowflake_pool.close_telemetry_pool()
        await snowflake_pool.close_default_pool()
        await postgres_pool.close_all_pools()
        logger.info("✅ All connection pools closed")

    except Exception as e:
        logger.error(f"Error closing connection pools: {e}")

    # TODO: Clean up temporary files


# Initialize FastAPI application
app = FastAPI(
    title="Unistore Benchmark",
    description="Performance benchmarking tool for Snowflake and Postgres - 3DMark for databases",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure CORS for local development
if settings.APP_DEBUG:
    app.add_middleware(
        cast(Any, CORSMiddleware),
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"🔓 CORS enabled for origins: {settings.CORS_ORIGINS}")

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Initialize Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Add custom template filters/functions
templates.env.globals.update(
    {
        "app_name": "Unistore Benchmark",
        "app_version": "0.1.0",
    }
)


# ============================================================================
# Health Check & Info Endpoints
# ============================================================================


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(request: Request):
    """
    Root endpoint - renders templates page (tests are run from templates).
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/templates.html" if not is_htmx else "pages/templates.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx}
    )


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """
    Dashboard page - real-time test metrics and control.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/dashboard.html" if not is_htmx else "pages/dashboard.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx}
    )


@app.get("/dashboard/{test_id}", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_test(request: Request, test_id: str):
    """
    Dashboard page for a specific test - real-time test metrics and control.
    """
    # For terminal runs, prefer the read-only analysis view which includes the
    # final (post-processed) metrics. But do NOT redirect prepared/running tests,
    # since this route is used to start/monitor runs.
    history_url = f"/dashboard/history/{test_id}"
    running = await registry.get(test_id)

    # If not in memory, check database for PREPARED status (autoscale tests are
    # persisted to DB but not registered in memory until started).
    if running is None:
        try:
            pool = snowflake_pool.get_default_pool()
            rows = await pool.execute_query(
                f"""
                SELECT STATUS
                FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS
                WHERE TEST_ID = ?
                LIMIT 1
                """,
                params=[test_id],
            )
            if rows:
                db_status = str(rows[0][0] or "").upper()
                if db_status in {
                    "PREPARED",
                    "READY",
                    "PENDING",
                    "RUNNING",
                    "CANCELLING",
                }:
                    # Test exists in DB with a live status - serve live dashboard
                    is_htmx = request.headers.get("HX-Request") == "true"
                    template = "pages/dashboard.html"
                    return templates.TemplateResponse(
                        template,
                        {"request": request, "is_htmx": is_htmx, "test_id": test_id},
                    )
        except Exception:
            # Fall through to redirect on any DB error
            pass
        return RedirectResponse(url=history_url, status_code=302)

    status = str(getattr(running, "status", "") or "").upper()
    live_statuses = {"PREPARED", "READY", "PENDING", "RUNNING", "CANCELLING", "STARTING"}
    if status not in live_statuses:
        if request.headers.get("HX-Request") == "true":
            resp = HTMLResponse("")
            resp.headers["HX-Redirect"] = history_url
            return resp
        return RedirectResponse(url=history_url, status_code=302)

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/dashboard.html" if not is_htmx else "pages/dashboard.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx, "test_id": test_id}
    )


@app.get(
    "/dashboard/history/{test_id}", response_class=HTMLResponse, include_in_schema=False
)
async def dashboard_history_test(request: Request, test_id: str):
    """
    History dashboard page for a specific test - read-only analysis view.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = (
        "pages/dashboard_history.html"
        if not is_htmx
        else "pages/dashboard_history.html"
    )
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx, "test_id": test_id}
    )


@app.get(
    "/dashboard/history/{test_id}/data",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def dashboard_history_data(request: Request, test_id: str):
    """
    Drilldown page for persisted per-operation query executions.

    Query params:
    - kinds: comma-separated QUERY_KIND list (e.g. POINT_LOOKUP,RANGE_SCAN)
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    kinds = request.query_params.get("kinds", "") or ""
    snowsight_org_account_path = await _get_snowsight_org_account_path()
    template = (
        "pages/dashboard_history_data.html"
        if not is_htmx
        else "pages/dashboard_history_data.html"
    )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "is_htmx": is_htmx,
            "test_id": test_id,
            "kinds": kinds,
            "snowsight_org_account_path": snowsight_org_account_path,
        },
    )


@app.get("/configure", response_class=HTMLResponse, include_in_schema=False)
async def configure(request: Request):
    """
    Test configuration page - design custom performance tests.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/configure.html" if not is_htmx else "pages/configure.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx}
    )


@app.get("/comparison", response_class=HTMLResponse, include_in_schema=False)
async def comparison(request: Request):
    """
    Deprecated: comparison is now part of /history.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        # HTMX doesn't always push the redirected URL the way we want; tell it to
        # navigate directly to the new location.
        return HTMLResponse("", headers={"HX-Redirect": "/history"})
    return RedirectResponse(url="/history", status_code=303)


@app.get("/history", response_class=HTMLResponse, include_in_schema=False)
async def history(request: Request):
    """
    Test history page - browse and manage previous test results.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/history.html" if not is_htmx else "pages/history.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx}
    )


@app.get("/history/compare", response_class=HTMLResponse, include_in_schema=False)
async def history_compare(request: Request):
    """
    Deep comparison view for two tests.

    Query params:
    - ids: comma-separated two TEST_ID values (UUIDs)
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    ids_raw = (request.query_params.get("ids") or "").strip()
    ids_list = [p.strip() for p in ids_raw.split(",") if p and p.strip()]
    error = None
    if len(ids_list) != 2:
        error = "Provide exactly 2 test ids via ?ids=<id1>,<id2>."

    template = (
        "pages/history_compare.html" if not is_htmx else "pages/history_compare.html"
    )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "is_htmx": is_htmx,
            "ids_raw": ids_raw,
            "ids": ids_list,
            "error": error,
        },
    )


@app.get("/templates", response_class=HTMLResponse, include_in_schema=False)
async def templates_page(request: Request):
    """
    Templates page - manage and reuse test configuration templates.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "pages/templates.html" if not is_htmx else "pages/templates.html"
    return templates.TemplateResponse(
        template, {"request": request, "is_htmx": is_htmx}
    )


@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        dict: Service health status and version information
    """
    health_status: dict[str, Any] = {
        "status": "healthy",
        "service": "unistore-benchmark",
        "version": "0.1.0",
        "environment": "development" if settings.APP_DEBUG else "production",
        "checks": {},
    }

    # Check Snowflake connection
    try:
        from backend.connectors import snowflake_pool

        sf_pool = snowflake_pool.get_default_pool()
        stats = await sf_pool.get_pool_stats()
        health_status["checks"]["snowflake"] = {
            "status": "healthy" if stats["initialized"] else "not_initialized",
            "pool": stats,
        }
    except Exception as e:
        health_status["checks"]["snowflake"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "degraded"

    # Check Postgres connection (if enabled)
    if settings.ENABLE_POSTGRES:
        try:
            from backend.connectors import postgres_pool

            pg_pool = postgres_pool.get_default_pool()
            stats = await pg_pool.get_pool_stats()
            is_healthy = await pg_pool.is_healthy()
            health_status["checks"]["postgres"] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "pool": stats,
            }
        except Exception as e:
            health_status["checks"]["postgres"] = {
                "status": "unhealthy",
                "error": str(e),
            }

    return health_status


@app.get("/api/info")
async def api_info():
    """
    API information endpoint.

    Returns:
        dict: Application configuration and capabilities
    """
    return {
        "name": "Unistore Benchmark",
        "version": "0.1.0",
        "description": "Performance benchmarking tool for Snowflake and Postgres",
        "results_warehouse": settings.SNOWFLAKE_WAREHOUSE,
        "features": {
            "table_types": ["standard", "hybrid", "interactive", "postgres"],
            "real_time_metrics": True,
            "max_comparisons": 5,
            "websocket_support": True,
        },
        "endpoints": {
            "api_docs": "/api/docs",
            "health": "/health",
            "dashboard": "/dashboard",
            "configure": "/configure",
            "history": "/history",
        },
    }


# ============================================================================
# Import API Routes (will be created in next steps)
# ============================================================================

# Import and include API routers
from backend.api.routes import runs  # noqa: E402
from backend.api.routes import tests  # noqa: E402
from backend.api.routes import templates as templates_router  # noqa: E402
from backend.api.routes import warehouses  # noqa: E402
from backend.api.routes import catalog  # noqa: E402
from backend.api.routes import test_results  # noqa: E402

app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(tests.router, prefix="/api/test", tags=["tests"])
app.include_router(templates_router.router, prefix="/api/templates", tags=["templates"])
app.include_router(warehouses.router, prefix="/api/warehouses", tags=["warehouses"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(test_results.router, prefix="/api/tests", tags=["test_results"])

# TODO: Import additional routers as they're created
# from backend.api.routes import comparison, history
# app.include_router(comparison.router, prefix="/comparison", tags=["comparison"])
# app.include_router(history.router, prefix="/history", tags=["history"])


# ============================================================================
# WebSocket endpoint (placeholder)
# ============================================================================


async def _get_parent_test_status(test_id: str) -> str | None:
    try:
        pool = snowflake_pool.get_default_pool()
        rows = await pool.execute_query(
            f"""
            SELECT STATUS
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS
            WHERE TEST_ID = ?
            LIMIT 1
            """,
            params=[test_id],
        )
        if rows:
            return str(rows[0][0] or "").upper()
        return None
    except Exception:
        return None


def _coerce_datetime(value: Any) -> datetime | None:
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


def _build_aggregate_metrics(
    *,
    ops: dict[str, Any] | None,
    latency: dict[str, Any] | None,
    errors: dict[str, Any] | None,
    connections: dict[str, Any] | None,
    operations: dict[str, Any] | None,
) -> dict[str, Any]:
    ops_payload = ops or {}
    latency_payload = latency or {}
    errors_payload = errors or {}
    connections_payload = connections or {}
    operations_payload = operations or {}
    total_ops = int(ops_payload.get("total") or 0)
    return {
        "total_ops": total_ops,
        "qps": float(ops_payload.get("current_per_sec") or 0),
        "p50_latency_ms": float(latency_payload.get("p50") or 0),
        "p95_latency_ms": float(latency_payload.get("p95") or 0),
        "p99_latency_ms": float(latency_payload.get("p99") or 0),
        "avg_latency_ms": float(latency_payload.get("avg") or 0),
        "error_rate": float(errors_payload.get("rate") or 0),
        "total_errors": int(errors_payload.get("count") or 0),
        "active_connections": int(connections_payload.get("active") or 0),
        "target_connections": int(connections_payload.get("target") or 0),
        "read_count": int(operations_payload.get("reads") or 0),
        "write_count": int(operations_payload.get("writes") or 0),
    }


def _build_run_snapshot(
    *,
    run_id: str,
    status: str | None,
    phase: str | None,
    elapsed_seconds: float | None,
    worker_count: int,
    aggregate_metrics: dict[str, Any],
    run_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_payload: dict[str, Any] = {
        "run_id": run_id,
        "status": status or "RUNNING",
        "phase": phase or status or "RUNNING",
        "worker_count": worker_count,
        "elapsed_seconds": float(elapsed_seconds or 0),
        "aggregate_metrics": aggregate_metrics,
    }
    if run_status:
        run_payload["workers_expected"] = run_status.get("total_workers_expected")
        run_payload["workers_registered"] = run_status.get("workers_registered")
        run_payload["workers_active"] = run_status.get("workers_active")
        run_payload["workers_completed"] = run_status.get("workers_completed")
        start_time = _coerce_datetime(run_status.get("start_time"))
        end_time = _coerce_datetime(run_status.get("end_time"))
        run_payload["start_time"] = (
            start_time.isoformat() if start_time is not None else None
        )
        run_payload["end_time"] = end_time.isoformat() if end_time is not None else None
    return run_payload


async def _fetch_run_status(run_id: str) -> dict[str, Any] | None:
    try:
        pool = snowflake_pool.get_default_pool()
        rows = await pool.execute_query(
            f"""
            SELECT
                rs.STATUS,
                rs.PHASE,
                rs.START_TIME,
                rs.END_TIME,
                rs.WARMUP_END_TIME,
                rs.TOTAL_WORKERS_EXPECTED,
                rs.WORKERS_REGISTERED,
                rs.WORKERS_ACTIVE,
                rs.WORKERS_COMPLETED,
                rs.FIND_MAX_STATE,
                rs.CANCELLATION_REASON,
                CASE
                    WHEN rs.STATUS IN ('COMPLETED', 'FAILED', 'CANCELLED', 'STOPPED') THEN
                        COALESCE(
                            NULLIF(tr.DURATION_SECONDS, 0),
                            TIMESTAMPDIFF(SECOND, rs.START_TIME, rs.END_TIME)
                        )
                    ELSE
                        TIMESTAMPDIFF(
                            SECOND,
                            rs.START_TIME,
                            CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
                        )
                END AS ELAPSED_SECONDS
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.RUN_STATUS rs
            LEFT JOIN {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS tr
                ON tr.TEST_ID = rs.RUN_ID
            WHERE rs.RUN_ID = ?
            LIMIT 1
            """,
            params=[run_id],
        )
        if not rows:
            return None
        (
            status,
            phase,
            start_time,
            end_time,
            warmup_end_time,
            total_workers_expected,
            workers_registered,
            workers_active,
            workers_completed,
            find_max_state,
            cancellation_reason,
            elapsed_seconds,
        ) = rows[0]
        return {
            "status": str(status or "").upper(),
            "phase": str(phase or "").upper(),
            "start_time": start_time,
            "end_time": end_time,
            "warmup_end_time": warmup_end_time,
            "total_workers_expected": total_workers_expected,
            "workers_registered": workers_registered,
            "workers_active": workers_active,
            "workers_completed": workers_completed,
            "find_max_state": find_max_state,
            "cancellation_reason": str(cancellation_reason) if cancellation_reason else None,
            "elapsed_seconds": float(elapsed_seconds)
            if elapsed_seconds is not None
            else None,
        }
    except Exception:
        return None


async def _fetch_parent_enrichment_status(run_id: str) -> str | None:
    """Fetch enrichment status for a test run.
    
    Enrichment is done centrally by the orchestrator and updates ONLY the parent
    row (where TEST_ID = RUN_ID). So we check the parent row first - it's the
    authoritative source. This matches the HTTP /enrichment-status endpoint logic.
    """
    try:
        pool = snowflake_pool.get_default_pool()
        # Always check the parent row first - enrichment status is updated here
        parent_rows = await pool.execute_query(
            f"""
            SELECT ENRICHMENT_STATUS
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS
            WHERE TEST_ID = ?
            """,
            params=[run_id],
        )
        if parent_rows and parent_rows[0] and parent_rows[0][0]:
            parent_status = str(parent_rows[0][0]).strip().upper()
            # If parent has a definitive status, return it
            if parent_status in ("COMPLETED", "FAILED", "SKIPPED"):
                return parent_status
            # If parent is PENDING, also check child rows (for multi-worker tests)
            # in case they have a more specific status
            if parent_status == "PENDING":
                child_rows = await pool.execute_query(
                    f"""
                    SELECT ENRICHMENT_STATUS
                    FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS
                    WHERE RUN_ID = ?
                      AND TEST_ID <> ?
                    """,
                    params=[run_id, run_id],
                )
                child_statuses = [
                    str(row[0] or "").strip().upper()
                    for row in child_rows or []
                    if row and row[0]
                ]
                # If any child has a terminal status, use the worst case
                if "FAILED" in child_statuses:
                    return "FAILED"
                # Otherwise return parent's PENDING status
                return "PENDING"
            return parent_status
        return None
    except Exception:
        return None


async def _aggregate_multi_worker_metrics(parent_run_id: str) -> dict[str, Any]:
    pool = snowflake_pool.get_default_pool()
    rows = await pool.execute_query(
        f"""
        WITH latest_per_worker AS (
            SELECT
                wms.*,
                ROW_NUMBER() OVER (PARTITION BY WORKER_ID ORDER BY TIMESTAMP DESC) AS rn
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.WORKER_METRICS_SNAPSHOTS wms
            WHERE RUN_ID = ?
        )
        SELECT
            wms.ELAPSED_SECONDS,
            wms.TOTAL_QUERIES,
            wms.QPS,
            wms.P50_LATENCY_MS,
            wms.P95_LATENCY_MS,
            wms.P99_LATENCY_MS,
            wms.AVG_LATENCY_MS,
            wms.READ_COUNT,
            wms.WRITE_COUNT,
            wms.ERROR_COUNT,
            wms.ACTIVE_CONNECTIONS,
            wms.TARGET_CONNECTIONS,
            wms.CUSTOM_METRICS,
            wms.PHASE,
            wms.WORKER_ID,
            wms.WORKER_GROUP_ID
        FROM latest_per_worker wms
        WHERE wms.rn = 1
        """,
        params=[parent_run_id],
    )
    heartbeat_rows = await pool.execute_query(
        f"""
        SELECT
            WORKER_ID,
            WORKER_GROUP_ID,
            STATUS,
            PHASE,
            LAST_HEARTBEAT,
            ACTIVE_CONNECTIONS,
            TARGET_CONNECTIONS,
            QUERIES_PROCESSED,
            ERROR_COUNT
        FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.WORKER_HEARTBEATS
        WHERE RUN_ID = ?
        """,
        params=[parent_run_id],
    )

    if not rows and not heartbeat_rows:
        return {}

    def _to_int(v: Any) -> int:
        try:
            return int(v or 0)
        except Exception:
            return 0

    def _to_float(v: Any) -> float:
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    def _sum_dicts(dicts: list[dict[str, Any]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for d in dicts:
            for key, value in d.items():
                try:
                    out[key] = out.get(key, 0.0) + float(value or 0)
                except Exception:
                    continue
        return out

    def _avg_dicts(dicts: list[dict[str, Any]]) -> dict[str, float]:
        if not dicts:
            return {}
        summed = _sum_dicts(dicts)
        return {key: value / len(dicts) for key, value in summed.items()}

    def _health_from(status_value: Any, age_seconds: float | None) -> str:
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

    elapsed_seconds = 0.0
    total_ops = 0
    qps = 0.0
    p50_vals: list[float] = []
    p95_vals: list[float] = []
    p99_vals: list[float] = []
    avg_vals: list[float] = []
    read_count = 0
    write_count = 0
    error_count = 0
    active_connections = 0
    target_connections = 0

    app_ops_list: list[dict[str, Any]] = []
    sf_bench_list: list[dict[str, Any]] = []
    warehouse_list: list[dict[str, Any]] = []
    resources_list: list[dict[str, Any]] = []
    find_max_controller: dict[str, Any] | None = None
    qps_controller: dict[str, Any] | None = None
    phases: list[str] = []
    snapshot_by_worker: dict[str, dict[str, Any]] = {}

    for (
        elapsed,
        total_queries,
        qps_row,
        p50,
        p95,
        p99,
        avg_latency,
        read_row,
        write_row,
        error_row,
        active_row,
        target_row,
        custom_metrics,
        phase,
        _worker_id,
        worker_group_id,
    ) in rows:
        worker_id = str(_worker_id or "")
        snapshot_by_worker[worker_id] = {
            "worker_id": worker_id,
            "worker_group_id": int(worker_group_id or 0),
            "elapsed_seconds": float(elapsed or 0),
            "total_queries": _to_int(total_queries),
            "qps": _to_float(qps_row),
            "p50_latency_ms": _to_float(p50),
            "p95_latency_ms": _to_float(p95),
            "p99_latency_ms": _to_float(p99),
            "avg_latency_ms": _to_float(avg_latency),
            "read_count": _to_int(read_row),
            "write_count": _to_int(write_row),
            "error_count": _to_int(error_row),
            "active_connections": _to_int(active_row),
            "target_connections": _to_int(target_row),
            "phase": str(phase or ""),
        }
        phase_value = str(phase or "").strip().upper()
        if phase_value:
            phases.append(phase_value)

        heartbeat_status = None
        for hb in heartbeat_rows:
            if str(hb[0] or "") == worker_id:
                heartbeat_status = hb[2]
                break
        status_upper = str(heartbeat_status or "").upper()
        # Include both WARMUP and MEASUREMENT phase metrics for real-time streaming.
        # Excluding WARMUP caused ~45s delay before metrics appeared on dashboard.
        include_for_metrics = (
            not phase_value or phase_value in ("WARMUP", "MEASUREMENT")
        ) and status_upper != "DEAD"
        if include_for_metrics:
            elapsed_seconds = max(float(elapsed or 0), elapsed_seconds)
            total_ops += _to_int(total_queries)
            qps += _to_float(qps_row)
            p50_vals.append(_to_float(p50))
            p95_vals.append(_to_float(p95))
            p99_vals.append(_to_float(p99))
            avg_vals.append(_to_float(avg_latency))
            read_count += _to_int(read_row)
            write_count += _to_int(write_row)
            error_count += _to_int(error_row)
            active_connections += _to_int(active_row)
            target_connections += _to_int(target_row)

        cm: Any = custom_metrics
        if isinstance(cm, str):
            try:
                cm = json.loads(cm)
            except Exception:
                cm = {}
        if not isinstance(cm, dict):
            cm = {}

        if not phase_value:
            phase_val = cm.get("phase")
            if isinstance(phase_val, str) and phase_val.strip():
                phases.append(phase_val.strip().upper())

        app_ops = cm.get("app_ops_breakdown")
        if isinstance(app_ops, dict):
            app_ops_list.append(app_ops)
        sf_bench = cm.get("sf_bench")
        if isinstance(sf_bench, dict):
            sf_bench_list.append(sf_bench)
        warehouse = cm.get("warehouse")
        if isinstance(warehouse, dict):
            warehouse_list.append(warehouse)
        resources = cm.get("resources")
        if isinstance(resources, dict):
            resources_list.append(resources)
        if find_max_controller is None and isinstance(
            cm.get("find_max_controller"), dict
        ):
            find_max_controller = cm.get("find_max_controller")
        if qps_controller is None and isinstance(cm.get("qps_controller"), dict):
            qps_controller = cm.get("qps_controller")

    error_rate = (error_count / total_ops) if total_ops > 0 else 0.0
    p50_latency = sum(p50_vals) / len(p50_vals) if p50_vals else 0.0
    p95_latency = max(p95_vals) if p95_vals else 0.0
    p99_latency = max(p99_vals) if p99_vals else 0.0
    avg_latency = sum(avg_vals) / len(avg_vals) if avg_vals else 0.0

    custom_metrics_out = {
        "app_ops_breakdown": _sum_dicts(app_ops_list),
        "sf_bench": _sum_dicts(sf_bench_list),
        "resources": _avg_dicts(resources_list),
    }
    poller_snapshot = await results_store.fetch_latest_warehouse_poll_snapshot(
        run_id=parent_run_id
    )
    if poller_snapshot is not None:
        custom_metrics_out["warehouse"] = poller_snapshot
    else:
        custom_metrics_out["warehouse"] = _sum_dicts(warehouse_list)
    if find_max_controller is not None:
        custom_metrics_out["find_max_controller"] = find_max_controller
    if qps_controller is not None:
        custom_metrics_out["qps_controller"] = qps_controller

    phase_order = {
        "PREPARING": 0,
        "WARMUP": 1,
        "RUNNING": 2,
        "PROCESSING": 3,
        "COMPLETED": 4,
    }
    phase_priority = {
        "FAILED": -1,
        "CANCELLED": -1,
        "STOPPED": -1,
    }
    resolved_phase = None
    for phase in phases:
        if phase in phase_priority:
            resolved_phase = phase
            break
    if resolved_phase is None and phases:
        resolved_phase = min(phases, key=lambda p: phase_order.get(p, 99))

    heartbeat_by_worker: dict[str, dict[str, Any]] = {}
    now = datetime.now(UTC)
    for (
        worker_id,
        worker_group_id,
        status_value,
        phase_value,
        last_heartbeat,
        active_connections,
        target_connections,
        queries_processed,
        error_count_value,
    ) in heartbeat_rows:
        worker_id_str = str(worker_id or "")
        last_dt = _coerce_datetime(last_heartbeat)
        age_seconds = (now - last_dt).total_seconds() if last_dt is not None else None
        heartbeat_by_worker[worker_id_str] = {
            "worker_id": worker_id_str,
            "worker_group_id": int(worker_group_id or 0),
            "status": str(status_value or "").upper(),
            "phase": str(phase_value or "").upper(),
            "last_heartbeat": last_dt,
            "last_heartbeat_ago_s": age_seconds,
            "active_connections": _to_int(active_connections),
            "target_connections": _to_int(target_connections),
            "queries_processed": _to_int(queries_processed),
            "error_count": _to_int(error_count_value),
        }

    workers_out: list[dict[str, Any]] = []
    for worker_id, hb in heartbeat_by_worker.items():
        snapshot = snapshot_by_worker.get(worker_id, {})
        last_dt = hb.get("last_heartbeat")
        workers_out.append(
            {
                "worker_id": worker_id,
                "worker_group_id": hb.get("worker_group_id", 0),
                "status": hb.get("status"),
                "phase": hb.get("phase") or snapshot.get("phase"),
                "health": _health_from(
                    hb.get("status"), hb.get("last_heartbeat_ago_s")
                ),
                "last_heartbeat": (
                    last_dt.isoformat() if isinstance(last_dt, datetime) else None
                ),
                "last_heartbeat_ago_s": hb.get("last_heartbeat_ago_s"),
                "metrics": {
                    "qps": snapshot.get("qps") or 0.0,
                    "p50_latency_ms": snapshot.get("p50_latency_ms") or 0.0,
                    "p95_latency_ms": snapshot.get("p95_latency_ms") or 0.0,
                    "p99_latency_ms": snapshot.get("p99_latency_ms") or 0.0,
                    "avg_latency_ms": snapshot.get("avg_latency_ms") or 0.0,
                    "error_count": snapshot.get("error_count")
                    if snapshot
                    else hb.get("error_count", 0),
                    "active_connections": snapshot.get("active_connections")
                    if snapshot
                    else hb.get("active_connections", 0),
                    "target_connections": snapshot.get("target_connections")
                    if snapshot
                    else hb.get("target_connections", 0),
                },
            }
        )
    for worker_id, snapshot in snapshot_by_worker.items():
        if worker_id in heartbeat_by_worker:
            continue
        workers_out.append(
            {
                "worker_id": worker_id,
                "worker_group_id": snapshot.get("worker_group_id", 0),
                "status": "UNKNOWN",
                "phase": snapshot.get("phase") or None,
                "health": "STALE",
                "last_heartbeat": None,
                "last_heartbeat_ago_s": None,
                "metrics": {
                    "qps": snapshot.get("qps") or 0.0,
                    "p50_latency_ms": snapshot.get("p50_latency_ms") or 0.0,
                    "p95_latency_ms": snapshot.get("p95_latency_ms") or 0.0,
                    "p99_latency_ms": snapshot.get("p99_latency_ms") or 0.0,
                    "avg_latency_ms": snapshot.get("avg_latency_ms") or 0.0,
                    "error_count": snapshot.get("error_count") or 0,
                    "active_connections": snapshot.get("active_connections") or 0,
                    "target_connections": snapshot.get("target_connections") or 0,
                },
            }
        )
    workers_out.sort(
        key=lambda w: (
            int(w.get("worker_group_id") or 0),
            str(w.get("worker_id") or ""),
        )
    )

    return {
        "phase": resolved_phase,
        "elapsed": float(elapsed_seconds),
        "ops": {
            "total": total_ops,
            "current_per_sec": float(qps),
        },
        "operations": {
            "reads": read_count,
            "writes": write_count,
        },
        "latency": {
            "p50": float(p50_latency),
            "p95": float(p95_latency),
            "p99": float(p99_latency),
            "avg": float(avg_latency),
        },
        "latency_aggregation_method": "slowest_worker_approximation",
        "errors": {
            "count": error_count,
            "rate": float(error_rate),
        },
        "connections": {
            "active": active_connections,
            "target": target_connections,
        },
        "custom_metrics": custom_metrics_out,
        "workers": workers_out,
    }


async def _fetch_logs_since_seq(test_id: str, since_seq: int, limit: int = 100) -> list[dict[str, Any]]:
    """
    Fetch logs from TEST_LOGS table for a given test since a sequence number.
    Returns logs ordered by sequence ascending.
    """
    try:
        pool = snowflake_pool.get_default_pool()
        prefix = f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"
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
        FROM {prefix}.TEST_LOGS
        WHERE TEST_ID = ?
          AND SEQ > ?
        ORDER BY SEQ ASC
        LIMIT ?
        """
        rows = await pool.execute_query(query, params=[test_id, since_seq, limit])
        logs = []
        for row in rows:
            log_id, tid, seq, ts, level, logger_name, message, exception = row
            logs.append({
                "kind": "log",
                "log_id": str(log_id) if log_id else None,
                "test_id": str(tid) if tid else test_id,
                "seq": int(seq) if seq is not None else 0,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
                "level": str(level) if level else "INFO",
                "logger": str(logger_name) if logger_name else "",
                "message": str(message) if message else "",
                "exception": str(exception) if exception else None,
            })
        return logs
    except Exception as e:
        logger.debug(f"Failed to fetch logs for test {test_id}: {e}")
        return []


async def _stream_run_metrics(websocket: WebSocket, test_id: str) -> None:
    await websocket.send_json(
        {
            "status": "connected",
            "test_id": test_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    poll_interval = 1.0
    last_sent_phase: str | None = None  # Track phase to ensure PROCESSING is shown
    last_log_seq: int = 0  # Track last log sequence to fetch only new logs
    while True:
        recv_task = asyncio.create_task(websocket.receive())
        sleep_task = asyncio.create_task(asyncio.sleep(poll_interval))
        done, pending = await asyncio.wait(
            {recv_task, sleep_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

        if recv_task in done:
            msg = recv_task.result()
            if msg.get("type") == "websocket.disconnect":
                break
            continue

        if websocket.client_state != WebSocketState.CONNECTED:
            break

        run_status = await _fetch_run_status(test_id)
        status = run_status.get("status") if run_status else None
        status = status or await _get_parent_test_status(test_id) or "RUNNING"
        status_upper = str(status or "").upper()
        metrics = await _aggregate_multi_worker_metrics(test_id)
        metrics = metrics or {}
        workers = metrics.pop("workers", [])
        metrics_phase = metrics.pop("phase", None)
        phase = (
            run_status.get("phase")
            if run_status and run_status.get("phase")
            else metrics_phase
        )
        if not phase:
            phase = status_upper
        if status_upper in {"STOPPED", "FAILED", "CANCELLED", "COMPLETED"}:
            phase = status_upper
        # Show PROCESSING phase during worker draining (STOPPING) and enrichment
        if status_upper == "STOPPING":
            phase = "PROCESSING"
        if status_upper == "COMPLETED":
            enrichment_status = await _fetch_parent_enrichment_status(test_id)
            # Treat None as PENDING to handle race condition where RUN_STATUS is
            # updated before TEST_RESULTS.ENRICHMENT_STATUS is set
            if enrichment_status in ("PENDING", None):
                phase = "PROCESSING"
            elif last_sent_phase not in {"PROCESSING", "COMPLETED"}:
                # Ensure PROCESSING is shown at least once before COMPLETED
                # even if enrichment finished before we polled
                phase = "PROCESSING"

        elapsed_seconds = None
        if run_status:
            elapsed_raw = run_status.get("elapsed_seconds")
            if isinstance(elapsed_raw, (int, float)):
                elapsed_seconds = float(elapsed_raw)
        if elapsed_seconds is None:
            elapsed_raw = metrics.get("elapsed")
            if isinstance(elapsed_raw, (int, float)):
                elapsed_seconds = float(elapsed_raw)

        ops = metrics.get("ops")
        latency = metrics.get("latency")
        errors = metrics.get("errors")
        connections = metrics.get("connections")
        operations = metrics.get("operations")
        aggregate_metrics = _build_aggregate_metrics(
            ops=ops,
            latency=latency,
            errors=errors,
            connections=connections,
            operations=operations,
        )
        run_snapshot = _build_run_snapshot(
            run_id=test_id,
            status=status_upper,
            phase=phase,
            elapsed_seconds=elapsed_seconds,
            worker_count=len(workers),
            aggregate_metrics=aggregate_metrics,
            run_status=run_status,
        )
        payload = {
            "test_id": test_id,
            "status": status_upper,
            "phase": phase,
            "timestamp": datetime.now(UTC).isoformat(),
            "run": run_snapshot,
            "workers": workers,
            **metrics,
        }
        if run_status and run_status.get("cancellation_reason"):
            payload["cancellation_reason"] = run_status.get("cancellation_reason")
        custom_metrics = metrics.get("custom_metrics")
        if isinstance(custom_metrics, dict):
            warehouse = custom_metrics.get("warehouse")
            if isinstance(warehouse, dict):
                payload["warehouse"] = warehouse
        if elapsed_seconds is not None:
            payload["elapsed"] = float(elapsed_seconds)
            timing = {"elapsed_display_seconds": round(float(elapsed_seconds), 1)}
            run_snapshot["timing"] = timing
            payload["timing"] = timing
        find_max_state = (
            _parse_variant_dict(run_status.get("find_max_state"))
            if run_status
            else None
        )
        if find_max_state is not None:
            payload["find_max"] = find_max_state
        
        # Fetch new logs since last sequence
        new_logs = await _fetch_logs_since_seq(test_id, last_log_seq, limit=100)
        if new_logs:
            payload["logs"] = new_logs
            # Update last_log_seq to the highest seq we received
            last_log_seq = max(log.get("seq", 0) for log in new_logs)
        
        await websocket.send_json({"event": "RUN_UPDATE", "data": payload})
        last_sent_phase = phase  # Track what we sent
        # Only break when phase reaches COMPLETED (cleanup finished).
        # For FAILED/CANCELLED: orchestrator continues through PROCESSING phase
        # to drain workers, flush logs, and run enrichment before setting phase=COMPLETED.
        if phase == "COMPLETED":
            # Grace period to ensure frontend receives final message before socket closes
            await asyncio.sleep(0.5)
            break


@app.websocket("/ws/test/{test_id}")
async def websocket_test_metrics(websocket: WebSocket, test_id: str):
    """
    WebSocket endpoint for real-time test metrics streaming.

    All runs now use the unified orchestrator-based streaming which polls
    RUN_STATUS and WORKER_METRICS_SNAPSHOTS for metrics.

    Args:
        websocket: WebSocket connection
        test_id: Unique test identifier (run_id)
    """
    await websocket.accept()
    logger.info(f"📡 WebSocket connected for test: {test_id}")

    try:
        await _stream_run_metrics(websocket, test_id)
    except WebSocketDisconnect:
        logger.info(f"📡 WebSocket disconnected for test: {test_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )
