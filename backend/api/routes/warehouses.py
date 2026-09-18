"""
API routes for Snowflake warehouse information.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from backend.connectors import snowflake_pool
from backend.config import settings
from backend.api.error_handling import http_exception

router = APIRouter()

# SHOW WAREHOUSES column indices (0-based), verified against live account output.
# New adaptive columns (34-36) were added when Adaptive Compute GA'd.
_COL_NAME = 0
_COL_STATE = 1          # STARTED/SUSPENDED/RESIZING (standard) or ENABLED/DISABLED (adaptive)
_COL_TYPE = 2           # STANDARD, ADAPTIVE, SNOWPARK-OPTIMIZED, etc.
_COL_SIZE = 3           # X-Small...6X-Large; NULL for adaptive
_COL_MIN_CLUSTER = 4
_COL_MAX_CLUSTER = 5
_COL_STARTED_CLUSTERS = 6
_COL_RUNNING = 7
_COL_QUEUED = 8
_COL_IS_DEFAULT = 9
_COL_IS_CURRENT = 10
_COL_AUTO_SUSPEND = 11
_COL_AUTO_RESUME = 12
_COL_ENABLE_QAS = 22    # enable_query_acceleration
_COL_QAS_SCALE = 23     # query_acceleration_max_scale_factor
_COL_SCALING_POLICY = 30
_COL_RESOURCE_CONSTRAINT = 32   # STANDARD_GEN_1, STANDARD_GEN_2, or empty
_COL_GENERATION = 33    # '1', '2', or empty. Authoritative; standard warehouses only.
_COL_QUERY_THROUGHPUT_MULTIPLIER = 34   # adaptive only
_COL_MAX_QUERY_PERFORMANCE_LEVEL = 35   # adaptive only
_COL_DISABLED_REASONS = 36             # adaptive only


def _parse_warehouse_row(row: tuple) -> Dict[str, Any]:
    """Parse a single SHOW WAREHOUSES row into a normalized dict."""
    n = len(row)

    def _get(idx: int, default=None):
        return row[idx] if n > idx else default

    wh_type = _get(_COL_TYPE) or ""
    wh_type_upper = wh_type.upper()
    is_adaptive = wh_type_upper == "ADAPTIVE"
    # Interactive warehouses have no generation and no QAS. Per CREATE INTERACTIVE
    # WAREHOUSE, GENERATION/RESOURCE_CONSTRAINT/ENABLE_QUERY_ACCELERATION are not
    # valid properties, and SHOW WAREHOUSES returns empty for those columns.
    is_interactive = wh_type_upper == "INTERACTIVE"

    wh: Dict[str, Any] = {
        "name": _get(_COL_NAME),
        "state": _get(_COL_STATE),
        "type": wh_type,
        "is_adaptive": is_adaptive,
        "is_interactive": is_interactive,
        "running": int(_get(_COL_RUNNING) or 0),
        "queued": int(_get(_COL_QUEUED) or 0),
        "is_default": _get(_COL_IS_DEFAULT) == "Y",
        "is_current": _get(_COL_IS_CURRENT) == "Y",
        "auto_suspend": _get(_COL_AUTO_SUSPEND),
        "auto_resume": str(_get(_COL_AUTO_RESUME) or "").lower() == "true",
    }

    if is_adaptive:
        # Adaptive warehouses: no size/MCW/QAS/Gen — use adaptive-specific properties
        wh.update({
            "size": None,
            "min_cluster_count": None,
            "max_cluster_count": None,
            "started_clusters": None,
            "scaling_policy": None,
            "enable_query_acceleration": None,
            "query_acceleration_max_scale_factor": None,
            "resource_constraint": None,
            "generation": None,
            "max_query_performance_level": _get(_COL_MAX_QUERY_PERFORMANCE_LEVEL),
            "query_throughput_multiplier": (
                int(_get(_COL_QUERY_THROUGHPUT_MULTIPLIER))
                if _get(_COL_QUERY_THROUGHPUT_MULTIPLIER) is not None
                else None
            ),
            "disabled_reasons": _get(_COL_DISABLED_REASONS) or None,
        })
    elif is_interactive:
        # Interactive warehouses: size and clustering apply, but generation and QAS
        # do not. Report those as None rather than inferring a default.
        wh.update({
            "size": _get(_COL_SIZE),
            "min_cluster_count": int(_get(_COL_MIN_CLUSTER) or 1),
            "max_cluster_count": int(_get(_COL_MAX_CLUSTER) or 1),
            "started_clusters": int(_get(_COL_STARTED_CLUSTERS) or 0),
            "scaling_policy": _get(_COL_SCALING_POLICY) or "STANDARD",
            "enable_query_acceleration": None,
            "query_acceleration_max_scale_factor": None,
            "resource_constraint": None,
            "generation": None,
            "max_query_performance_level": None,
            "query_throughput_multiplier": None,
            "disabled_reasons": None,
        })
    else:
        wh.update({
            "size": _get(_COL_SIZE),
            "min_cluster_count": int(_get(_COL_MIN_CLUSTER) or 1),
            "max_cluster_count": int(_get(_COL_MAX_CLUSTER) or 1),
            "started_clusters": int(_get(_COL_STARTED_CLUSTERS) or 0),
            "scaling_policy": _get(_COL_SCALING_POLICY) or "STANDARD",
            "enable_query_acceleration": (
                str(_get(_COL_ENABLE_QAS) or "").lower() == "true"
            ),
            "query_acceleration_max_scale_factor": (
                int(_get(_COL_QAS_SCALE) or 0)
                if _get(_COL_QAS_SCALE) is not None
                else 0
            ),
            # STANDARD_GEN_1, STANDARD_GEN_2, or empty. Empty means the warehouse
            # has no explicit setting -- do NOT infer a generation from it. The
            # account default changed to Gen2 (BCR-2250), so a blank value is not
            # evidence of Gen1.
            "resource_constraint": _get(_COL_RESOURCE_CONSTRAINT) or None,
            # Authoritative generation column ('1' / '2'), empty when unset.
            "generation": (
                str(_get(_COL_GENERATION)).strip()
                if str(_get(_COL_GENERATION) or "").strip()
                else None
            ),
            "max_query_performance_level": None,
            "query_throughput_multiplier": None,
            "disabled_reasons": None,
        })

    return wh


@router.get("/", response_model=List[Dict[str, Any]])
async def list_warehouses(exclude_results: bool = Query(False)):
    """
    List all available warehouses in the Snowflake account.

    Returns:
        List of warehouses with their configuration details
    """
    try:
        pool = snowflake_pool.get_default_pool()
        results = await pool.execute_query("SHOW WAREHOUSES")

        warehouses: list[dict[str, Any]] = []
        results_wh = str(settings.SNOWFLAKE_WAREHOUSE).strip().upper()
        for row in results:
            wh = _parse_warehouse_row(row)
            if exclude_results and str(wh["name"]).strip().upper() == results_wh:
                continue
            warehouses.append(wh)

        return warehouses

    except Exception as e:
        raise http_exception("list warehouses", e)


@router.get("/{warehouse_name}", response_model=Dict[str, Any])
async def get_warehouse_details(warehouse_name: str):
    """
    Get details for a specific warehouse.

    Args:
        warehouse_name: Name of the warehouse

    Returns:
        Warehouse configuration details
    """
    try:
        pool = snowflake_pool.get_default_pool()
        results = await pool.execute_query(
            f"SHOW WAREHOUSES LIKE '{warehouse_name}'"
        )

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Warehouse not found: {warehouse_name}",
            )

        return _parse_warehouse_row(results[0])

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("get warehouse details", e)
