"""
Test Executor Package

This package contains the test execution engine, split into logical modules
for better maintainability and AI-tool friendliness.

Modules:
- models: Data classes (TableRuntimeState, QueryExecutionRecord)
- utils: Utility functions (error classification, query annotation, etc.)
- warehouse_manager: Warehouse state management mixin
- metrics_collector: Real-time metrics collection mixin
- workers: Worker lifecycle management mixin

The main TestExecutor class is imported from the parent module for
backward compatibility.
"""

from backend.core.test_executor_modules.models import (
    TableRuntimeState,
    QueryExecutionRecord,
)
from backend.core.test_executor_modules.utils import (
    classify_sql_error,
    is_critical_config_error,
    is_postgres_pool,
    quote_column,
    annotate_query_for_sf_kind,
    truncate_str_for_log,
    preview_query_for_log,
    preview_params_for_log,
    sql_error_meta_for_log,
    build_smooth_weighted_schedule,
)
from backend.core.test_executor_modules.warehouse_manager import WarehouseManagerMixin
from backend.core.test_executor_modules.metrics_collector import MetricsCollectorMixin
from backend.core.test_executor_modules.workers import WorkerMixin

# Re-export for backward compatibility - the main TestExecutor class
# remains in the parent module but uses these extracted components
__all__ = [
    # Models
    "TableRuntimeState",
    "QueryExecutionRecord",
    # Utility functions
    "classify_sql_error",
    "is_critical_config_error",
    "is_postgres_pool",
    "quote_column",
    "annotate_query_for_sf_kind",
    "truncate_str_for_log",
    "preview_query_for_log",
    "preview_params_for_log",
    "sql_error_meta_for_log",
    "build_smooth_weighted_schedule",
    # Mixins
    "WarehouseManagerMixin",
    "MetricsCollectorMixin",
    "WorkerMixin",
]
