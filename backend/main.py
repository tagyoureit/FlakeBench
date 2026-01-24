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
    live_statuses = {"PREPARED", "READY", "PENDING", "RUNNING", "CANCELLING"}
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
from backend.api.routes import tests  # noqa: E402
from backend.api.routes import templates as templates_router  # noqa: E402
from backend.api.routes import warehouses  # noqa: E402
from backend.api.routes import catalog  # noqa: E402
from backend.api.routes import test_results  # noqa: E402

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


async def _is_multi_node_parent(test_id: str) -> bool:
    try:
        pool = snowflake_pool.get_default_pool()
        rows = await pool.execute_query(
            f"""
            SELECT RUN_ID, STATUS
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_RESULTS
            WHERE TEST_ID = ?
            LIMIT 1
            """,
            params=[test_id],
        )
        if not rows:
            return False
        run_id = rows[0][0]
        return bool(run_id) and str(run_id) == str(test_id)
    except Exception:
        return False


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


async def _aggregate_multi_node_metrics(parent_run_id: str) -> dict[str, Any]:
    pool = snowflake_pool.get_default_pool()
    rows = await pool.execute_query(
        f"""
        WITH latest_per_node AS (
            SELECT
                nms.*,
                ROW_NUMBER() OVER (PARTITION BY NODE_ID ORDER BY TIMESTAMP DESC) AS rn
            FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.NODE_METRICS_SNAPSHOTS nms
            WHERE PARENT_RUN_ID = ?
        )
        SELECT
            ELAPSED_SECONDS,
            TOTAL_QUERIES,
            QPS,
            P50_LATENCY_MS,
            P95_LATENCY_MS,
            P99_LATENCY_MS,
            AVG_LATENCY_MS,
            READ_COUNT,
            WRITE_COUNT,
            ERROR_COUNT,
            ACTIVE_CONNECTIONS,
            TARGET_WORKERS,
            CUSTOM_METRICS
        FROM latest_per_node
        WHERE rn = 1
        """,
        params=[parent_run_id],
    )

    if not rows:
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
    target_workers = 0

    app_ops_list: list[dict[str, Any]] = []
    sf_bench_list: list[dict[str, Any]] = []
    warehouse_list: list[dict[str, Any]] = []
    resources_list: list[dict[str, Any]] = []
    find_max_controller: dict[str, Any] | None = None
    qps_controller: dict[str, Any] | None = None
    phases: list[str] = []

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
    ) in rows:
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
        target_workers += _to_int(target_row)

        cm: Any = custom_metrics
        if isinstance(cm, str):
            try:
                cm = json.loads(cm)
            except Exception:
                cm = {}
        if not isinstance(cm, dict):
            cm = {}

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
    p95_latency = sum(p95_vals) / len(p95_vals) if p95_vals else 0.0
    p99_latency = sum(p99_vals) / len(p99_vals) if p99_vals else 0.0
    avg_latency = sum(avg_vals) / len(avg_vals) if avg_vals else 0.0

    custom_metrics_out = {
        "app_ops_breakdown": _sum_dicts(app_ops_list),
        "sf_bench": _sum_dicts(sf_bench_list),
        "warehouse": _sum_dicts(warehouse_list),
        "resources": _avg_dicts(resources_list),
    }
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
        "errors": {
            "count": error_count,
            "rate": float(error_rate),
        },
        "connections": {
            "active": active_connections,
            "target": target_workers,
        },
        "custom_metrics": custom_metrics_out,
    }


async def _stream_multi_node_metrics(websocket: WebSocket, test_id: str) -> None:
    await websocket.send_json(
        {
            "status": "connected",
            "test_id": test_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    poll_interval = 1.0
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

        status = await _get_parent_test_status(test_id)
        if status in {"COMPLETED", "FAILED", "CANCELLED"}:
            await websocket.send_json(
                {
                    "test_id": test_id,
                    "status": status,
                    "phase": status,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            break

        metrics = await _aggregate_multi_node_metrics(test_id)
        if metrics:
            metrics_phase = metrics.pop("phase", None)
            phase = metrics_phase or "RUNNING"
            if status in {"STOPPED", "FAILED", "CANCELLED", "COMPLETED"}:
                phase = status
            payload = {
                "test_id": test_id,
                "status": status or "RUNNING",
                "phase": phase,
                "timestamp": datetime.now(UTC).isoformat(),
                **metrics,
            }
            await websocket.send_json(payload)


@app.websocket("/ws/test/{test_id}")
async def websocket_test_metrics(websocket: WebSocket, test_id: str):
    """
    WebSocket endpoint for real-time test metrics streaming.

    Args:
        websocket: WebSocket connection
        test_id: Unique test identifier
    """
    await websocket.accept()
    logger.info(f"📡 WebSocket connected for test: {test_id}")

    try:
        if await _is_multi_node_parent(test_id):
            logger.info(
                f"📡 Multi-node parent test detected: {test_id}, using polling mode"
            )
            await _stream_multi_node_metrics(websocket, test_id)
            return

        q = await registry.subscribe(test_id)
        try:
            await websocket.send_json(
                {
                    "status": "connected",
                    "test_id": test_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            while True:
                get_payload = asyncio.create_task(q.get())
                recv_ws = asyncio.create_task(websocket.receive())
                done, pending = await asyncio.wait(
                    {get_payload, recv_ws}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()

                if recv_ws in done:
                    msg = recv_ws.result()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    continue

                payload = get_payload.result()
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                await websocket.send_json(payload)
        finally:
            await registry.unsubscribe(test_id, q)

    except KeyError:
        logger.warning(f"📡 Test not found in registry: {test_id}")
        try:
            await websocket.close()
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info(f"📡 WebSocket disconnected for multi-node test: {test_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

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
