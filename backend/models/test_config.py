"""
Test Configuration Models

Defines Pydantic models for test configurations including:
- Table configurations (types, indexes, clustering)
- Warehouse configurations (size, scaling)
- Test scenarios (duration, concurrency, workload)
"""

from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field, field_validator, model_validator


class TableType(str, Enum):
    """Supported table types."""

    STANDARD = "standard"
    HYBRID = "hybrid"
    INTERACTIVE = "interactive"
    POSTGRES = "postgres"
    SNOWFLAKE_POSTGRES = "snowflake_postgres"
    CRUNCHYDATA = "crunchydata"


class IndexType(str, Enum):
    """Postgres/Hybrid table index types."""

    BTREE = "btree"
    HASH = "hash"
    GIN = "gin"
    GIST = "gist"


class TableConfig(BaseModel):
    """
    Configuration for a table to be tested.

    Supports different table types with type-specific settings.
    """

    name: str = Field(..., description="Table name")
    table_type: TableType = Field(..., description="Type of table")

    # Standard table settings
    clustering_keys: Optional[List[str]] = Field(
        None, description="Clustering keys for standard tables"
    )
    data_retention_days: Optional[int] = Field(
        1, description="Data retention days for time travel"
    )

    # Hybrid table settings
    primary_key: Optional[List[str]] = Field(
        None, description="Primary key columns (required for hybrid tables)"
    )
    indexes: Optional[List[Dict[str, Any]]] = Field(
        None, description="Secondary indexes for hybrid tables"
    )
    foreign_keys: Optional[List[Dict[str, Any]]] = Field(
        None, description="Foreign key constraints"
    )

    # Interactive table settings
    cluster_by: Optional[List[str]] = Field(
        None, description="CLUSTER BY columns (required for interactive tables)"
    )
    cache_warming_enabled: bool = Field(
        False, description="Enable cache warming for interactive tables"
    )

    # Postgres-specific settings
    postgres_indexes: Optional[List[Dict[str, Any]]] = Field(
        None, description="Postgres-specific indexes"
    )

    # Schema definition
    columns: Dict[str, str] = Field(
        ..., description="Column definitions (name -> type)"
    )

    # Table size and data
    initial_row_count: int = Field(
        0, ge=0, description="Initial number of rows to populate"
    )

    # Database/schema location
    database: Optional[str] = Field(None, description="Database name")
    schema_name: Optional[str] = Field(None, description="Schema name")

    @model_validator(mode="after")
    def validate_table_requirements(self):
        """Validate table type-specific requirements."""
        # Hybrid tables require primary keys
        if self.table_type == TableType.HYBRID and not self.primary_key:
            raise ValueError("Hybrid tables require a primary key")

        # Interactive tables require CLUSTER BY
        if self.table_type == TableType.INTERACTIVE and not self.cluster_by:
            raise ValueError("Interactive tables require CLUSTER BY columns")

        return self

    class Config:
        use_enum_values = True


class WarehouseSize(str, Enum):
    """Snowflake warehouse sizes."""

    XSMALL = "X-Small"
    SMALL = "Small"
    MEDIUM = "Medium"
    LARGE = "Large"
    XLARGE = "X-Large"
    XXLARGE = "2X-Large"
    XXXLARGE = "3X-Large"
    X4LARGE = "4X-Large"
    X5LARGE = "5X-Large"
    X6LARGE = "6X-Large"


class ScalingPolicy(str, Enum):
    """Warehouse scaling policies."""

    STANDARD = "STANDARD"
    ECONOMY = "ECONOMY"


class WarehouseConfig(BaseModel):
    """
    Configuration for a Snowflake warehouse.
    """

    name: str = Field(..., description="Warehouse name")
    size: WarehouseSize = Field(..., description="Warehouse size")

    # Multi-cluster settings
    min_cluster_count: int = Field(1, ge=1, le=10, description="Min clusters")
    max_cluster_count: int = Field(1, ge=1, le=10, description="Max clusters")
    scaling_policy: ScalingPolicy = Field(
        ScalingPolicy.STANDARD, description="Scaling policy"
    )

    # Auto-suspend/resume
    auto_suspend_seconds: int = Field(
        600, ge=0, description="Auto-suspend after N seconds (0=never)"
    )
    auto_resume: bool = Field(True, description="Auto-resume on query")

    # Resource monitor
    resource_monitor: Optional[str] = Field(None, description="Resource monitor name")

    @field_validator("max_cluster_count")
    @classmethod
    def validate_cluster_count(cls, v, info):
        """Validate max >= min cluster count."""
        min_count = info.data.get("min_cluster_count", 1)
        if v < min_count:
            raise ValueError("max_cluster_count must be >= min_cluster_count")
        return v

    class Config:
        use_enum_values = True


class WorkloadType(str, Enum):
    """Types of workloads to execute."""

    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_HEAVY = "read_heavy"  # 80% read, 20% write
    WRITE_HEAVY = "write_heavy"  # 20% read, 80% write
    MIXED = "mixed"  # 50/50 read/write
    CUSTOM = "custom"  # User-defined queries


class TestScenario(BaseModel):
    """
    Configuration for a performance test scenario.
    """

    name: str = Field(..., description="Scenario name")
    description: Optional[str] = Field(None, description="Scenario description")

    # Test execution settings
    duration_seconds: int = Field(60, ge=1, description="Test duration in seconds")
    warmup_seconds: int = Field(
        10, ge=0, description="Warmup period before collecting metrics"
    )

    # Concurrency settings
    concurrent_connections: int = Field(
        10, ge=1, le=1000, description="Number of concurrent connections"
    )
    operations_per_connection: Optional[int] = Field(
        None, description="Ops per connection (None=unlimited until duration)"
    )

    # Workload configuration
    workload_type: WorkloadType = Field(..., description="Type of workload")

    # Read workload settings
    read_query_templates: Optional[List[str]] = Field(
        None, description="Read query templates with placeholders"
    )
    read_batch_size: int = Field(
        100, ge=1, description="Number of rows to read per query"
    )
    point_lookup_ratio: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Ratio of point lookups vs range scans in reads (0.0-1.0)",
    )

    # Write workload settings
    write_batch_size: int = Field(
        10, ge=1, description="Number of rows to insert per batch"
    )
    update_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="Ratio of updates vs inserts (0.0-1.0)"
    )
    delete_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of deletes in write operations (0.0-1.0)",
    )

    # Custom queries
    custom_queries: Optional[List[Dict[str, Any]]] = Field(
        None, description="Custom queries with weights and parameters"
    )

    # Rate limiting
    target_ops_per_second: Optional[int] = Field(
        None, description="Target operations per second (None=unlimited)"
    )

    # Think time
    think_time_ms: int = Field(
        0, ge=0, description="Think time between operations (milliseconds)"
    )

    # Data generation
    use_realistic_data: bool = Field(
        False, description="Generate realistic data vs random"
    )
    data_distribution: Optional[str] = Field(
        "uniform", description="Data distribution (uniform, normal, zipfian)"
    )

    # Metrics collection
    metrics_interval_seconds: float = Field(
        1.0, ge=0.1, le=60.0, description="Metrics collection interval"
    )
    collect_query_history: bool = Field(
        False, description="Collect detailed query history"
    )

    # Test targets
    table_configs: List[TableConfig] = Field(..., description="Tables to test")
    warehouse_configs: Optional[List[WarehouseConfig]] = Field(
        None, description="Warehouses to use (Snowflake only)"
    )

    # Tags and metadata
    tags: Optional[Dict[str, str]] = Field(
        None, description="Custom tags for categorization"
    )

    @model_validator(mode="after")
    def validate_custom_queries_requirement(self):
        """Validate custom queries when workload type is CUSTOM."""
        if self.workload_type == WorkloadType.CUSTOM and not self.custom_queries:
            raise ValueError("CUSTOM workload requires custom_queries")
        return self

    class Config:
        use_enum_values = True
