"""
Dynamic Table Manager

Manages Snowflake Dynamic Tables.

Dynamic Tables are materialized views with automatic incremental refresh.
They are READ-ONLY from a user perspective - data is populated via the
defining SELECT query and cannot be directly inserted/updated/deleted.

IMPORTANT: Dynamic Tables are NOT Interactive Tables.
- Interactive Tables (Unistore/HTAP) = CREATE INTERACTIVE TABLE + Interactive Warehouse
- Dynamic Tables = CREATE DYNAMIC TABLE (materialized views with auto-refresh)
"""

import logging

from backend.core.table_managers.standard import StandardTableManager

logger = logging.getLogger(__name__)


class DynamicTableManager(StandardTableManager):
    """
    Manages Snowflake Dynamic Tables.

    Dynamic Tables are materialized views that automatically refresh from
    their source tables. They support only read operations in benchmarks.
    This manager inherits from StandardTableManager for read operations.

    Key characteristics:
    - Created with CREATE DYNAMIC TABLE ... AS SELECT
    - Automatic incremental refresh based on target_lag
    - READ-ONLY: No INSERT/UPDATE/DELETE allowed
    - Can have CLUSTER BY for optimized queries
    - Supports search optimization
    """

    def __init__(self, config):
        super().__init__(config)
        logger.info(
            "DynamicTableManager initialized. Dynamic Tables are read-only "
            "materialized views - only read operations are supported."
        )
