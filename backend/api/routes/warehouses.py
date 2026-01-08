"""
API routes for Snowflake warehouse information.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from backend.connectors import snowflake_pool
from backend.config import settings
from backend.api.error_handling import http_exception

router = APIRouter()


@router.get("/", response_model=List[Dict[str, Any]])
async def list_warehouses(exclude_results: bool = Query(False)):
    """
    List all available warehouses in the Snowflake account.

    Returns:
        List of warehouses with their configuration details
    """
    try:
        pool = snowflake_pool.get_default_pool()

        query = """
        SHOW WAREHOUSES
        """

        results = await pool.execute_query(query)

        warehouses: list[dict[str, Any]] = []
        results_wh = str(settings.SNOWFLAKE_WAREHOUSE).strip().upper()
        for row in results:
            # SHOW WAREHOUSES returns many columns, scaling_policy is at index 30
            wh = {
                "name": row[0],
                "state": row[1],
                "type": row[2],
                "size": row[3],
                "min_cluster_count": row[4] if row[4] else 1,
                "max_cluster_count": row[5] if row[5] else 1,
                "started_clusters": row[6] if row[6] else 0,
                "running": row[7] if row[7] else 0,
                "queued": row[8] if row[8] else 0,
                "is_default": row[9] == "Y" if row[9] else False,
                "is_current": row[10] == "Y" if row[10] else False,
                "auto_suspend": row[11],
                "auto_resume": row[12] == "true" if row[12] else False,
                "scaling_policy": row[30] if len(row) > 30 and row[30] else "STANDARD",
            }
            wh_name = str(wh["name"]).strip().upper()
            if exclude_results and wh_name == results_wh:
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

        query = f"""
        SHOW WAREHOUSES LIKE '{warehouse_name}'
        """

        results = await pool.execute_query(query)

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Warehouse not found: {warehouse_name}",
            )

        row = results[0]
        return {
            "name": row[0],
            "state": row[1],
            "type": row[2],
            "size": row[3],
            "min_cluster_count": row[4] if row[4] else 1,
            "max_cluster_count": row[5] if row[5] else 1,
            "started_clusters": row[6] if row[6] else 0,
            "running": row[7] if row[7] else 0,
            "queued": row[8] if row[8] else 0,
            "is_default": row[9] == "Y" if row[9] else False,
            "is_current": row[10] == "Y" if row[10] else False,
            "auto_suspend": row[11],
            "auto_resume": row[12] == "true" if row[12] else False,
            "scaling_policy": row[30] if len(row) > 30 and row[30] else "STANDARD",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("get warehouse details", e)
