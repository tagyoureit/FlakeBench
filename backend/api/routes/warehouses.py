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
            # SHOW WAREHOUSES column indices (0-based):
            # 0=name, 1=state, 2=type, 3=size, 4=min_cluster_count, 5=max_cluster_count
            # 6=started_clusters, 7=running, 8=queued, 9=is_default, 10=is_current
            # 11=is_interactive, 12=auto_suspend, 13=auto_resume
            # 23=enable_query_acceleration, 24=query_acceleration_max_scale_factor
            # 31=scaling_policy, 33=resource_constraint (Gen1/Gen2)
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
                "auto_suspend": row[12],
                "auto_resume": row[13] == "true" if row[13] else False,
                "scaling_policy": row[31] if len(row) > 31 and row[31] else "STANDARD",
                # QAS (Query Acceleration Service)
                "enable_query_acceleration": row[23] == "true"
                if len(row) > 23 and row[23]
                else False,
                "query_acceleration_max_scale_factor": row[24]
                if len(row) > 24 and row[24]
                else 0,
                # Warehouse generation: STANDARD_GEN_1, STANDARD_GEN_2, or NULL (Gen 1)
                "resource_constraint": row[33] if len(row) > 33 else None,
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
        # SHOW WAREHOUSES column indices (0-based):
        # 0=name, 1=state, 2=type, 3=size, 4=min_cluster_count, 5=max_cluster_count
        # 6=started_clusters, 7=running, 8=queued, 9=is_default, 10=is_current
        # 11=is_interactive, 12=auto_suspend, 13=auto_resume
        # 23=enable_query_acceleration, 24=query_acceleration_max_scale_factor
        # 31=scaling_policy, 33=resource_constraint (Gen1/Gen2)
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
            "auto_suspend": row[12],
            "auto_resume": row[13] == "true" if row[13] else False,
            "scaling_policy": row[31] if len(row) > 31 and row[31] else "STANDARD",
            # QAS (Query Acceleration Service)
            "enable_query_acceleration": row[23] == "true"
            if len(row) > 23 and row[23]
            else False,
            "query_acceleration_max_scale_factor": row[24]
            if len(row) > 24 and row[24]
            else 0,
            # Warehouse generation: STANDARD_GEN_1, STANDARD_GEN_2, or NULL (Gen 1)
            "resource_constraint": row[33] if len(row) > 33 else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("get warehouse details", e)
