"""
Workload Generators for Database Performance Testing

This module provides workload generators that simulate different database access patterns:
- OLTP: Transactional workloads (point lookups, single row inserts/updates)
- OLAP: Analytical workloads (aggregations, scans, joins)
- Mixed: Combined OLTP + OLAP workloads

Each workload type generates specific query patterns and data access characteristics.
"""

from abc import ABC, abstractmethod
from typing import List, Any, Optional
from enum import Enum
import random
from datetime import datetime, UTC

from backend.models.test_config import TableConfig


class WorkloadType(str, Enum):
    """Types of database workloads"""

    READ_ONLY = "READ_ONLY"
    WRITE_ONLY = "WRITE_ONLY"
    READ_HEAVY = "READ_HEAVY"
    WRITE_HEAVY = "WRITE_HEAVY"
    MIXED = "MIXED"
    OLTP = "OLTP"
    OLAP = "OLAP"
    CUSTOM = "CUSTOM"


class Operation:
    """Represents a single database operation to execute"""

    def __init__(
        self,
        operation_type: str,
        query: str,
        params: Optional[List[Any]] = None,
        expected_rows: Optional[int] = None,
        description: Optional[str] = None,
    ):
        self.operation_type = operation_type
        self.query = query
        self.params = params or []
        self.expected_rows = expected_rows
        self.description = description or f"{operation_type} operation"
        self.timestamp = datetime.now(UTC)

    def __repr__(self) -> str:
        return f"Operation(type={self.operation_type}, query={self.query[:50]}...)"


class WorkloadGenerator(ABC):
    """
    Abstract base class for workload generators.

    Each generator creates a sequence of database operations that simulate
    a specific workload pattern.
    """

    def __init__(
        self,
        table_config: TableConfig,
        read_weight: float = 0.5,
        write_weight: float = 0.5,
        seed: Optional[int] = None,
    ):
        self.table_config = table_config
        self.read_weight = read_weight
        self.write_weight = write_weight
        self.random = random.Random(seed)

        database = table_config.database or "UNISTORE_BENCHMARK"
        schema_name = table_config.schema_name or "PUBLIC"
        self.full_table_name = f"{database}.{schema_name}.{table_config.name}"

        self._validate_weights()

    def _validate_weights(self):
        """Validate that read and write weights sum to 1.0"""
        total = self.read_weight + self.write_weight
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Read and write weights must sum to 1.0, got {total}")

    @abstractmethod
    def generate_operation(self) -> Operation:
        """
        Generate a single operation based on workload characteristics.

        Returns:
            Operation: A database operation to execute
        """
        pass

    def should_read(self) -> bool:
        """Determine if next operation should be a read based on weights"""
        return self.random.random() < self.read_weight


class OLTPWorkloadGenerator(WorkloadGenerator):
    """
    OLTP (Online Transaction Processing) workload generator.

    Characteristics:
    - Point lookups (single row reads by primary key)
    - Single row inserts
    - Single row updates
    - Short transactions
    - High concurrency
    """

    def __init__(
        self,
        table_config: TableConfig,
        read_weight: float = 0.7,
        write_weight: float = 0.3,
        row_count: int = 100000,
        seed: Optional[int] = None,
    ):
        super().__init__(table_config, read_weight, write_weight, seed)
        self.row_count = row_count
        self.insert_weight = 0.6
        self.update_weight = 0.3
        self.delete_weight = 0.1

    def generate_operation(self) -> Operation:
        """Generate OLTP-style operation"""
        if self.should_read():
            return self._generate_point_lookup()
        else:
            operation_type = self.random.choices(
                ["insert", "update", "delete"],
                weights=[self.insert_weight, self.update_weight, self.delete_weight],
            )[0]

            if operation_type == "insert":
                return self._generate_insert()
            elif operation_type == "update":
                return self._generate_update()
            else:
                return self._generate_delete()

    def _generate_point_lookup(self) -> Operation:
        """Generate a point lookup query by primary key"""
        row_id = self.random.randint(1, self.row_count)

        query = f"""
        SELECT * FROM {self.full_table_name}
        WHERE id = ?
        """

        return Operation(
            operation_type="READ",
            query=query.strip(),
            params=[row_id],
            expected_rows=1,
            description="Point lookup by primary key",
        )

    def _generate_insert(self) -> Operation:
        """Generate a single row insert"""
        row_id = self.random.randint(self.row_count + 1, self.row_count + 1000000)

        query = f"""
        INSERT INTO {self.full_table_name} (id, customer_id, region, status, amount, created_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP())
        """

        params = [
            row_id,
            self.random.randint(1, 10000),
            self.random.choice(["US-EAST", "US-WEST", "EU", "ASIA"]),
            self.random.choice(["ACTIVE", "PENDING", "COMPLETED"]),
            round(self.random.uniform(10.0, 1000.0), 2),
        ]

        return Operation(
            operation_type="WRITE",
            query=query.strip(),
            params=params,
            description="Single row insert",
        )

    def _generate_update(self) -> Operation:
        """Generate a single row update"""
        row_id = self.random.randint(1, self.row_count)

        query = f"""
        UPDATE {self.full_table_name}
        SET status = ?, amount = ?, updated_at = CURRENT_TIMESTAMP()
        WHERE id = ?
        """

        params = [
            self.random.choice(["ACTIVE", "COMPLETED", "CANCELLED"]),
            round(self.random.uniform(10.0, 1000.0), 2),
            row_id,
        ]

        return Operation(
            operation_type="WRITE",
            query=query.strip(),
            params=params,
            description="Single row update",
        )

    def _generate_delete(self) -> Operation:
        """Generate a single row delete"""
        row_id = self.random.randint(1, self.row_count)

        query = f"""
        DELETE FROM {self.full_table_name}
        WHERE id = ?
        """

        return Operation(
            operation_type="WRITE",
            query=query.strip(),
            params=[row_id],
            description="Single row delete",
        )


class OLAPWorkloadGenerator(WorkloadGenerator):
    """
    OLAP (Online Analytical Processing) workload generator.

    Characteristics:
    - Aggregations (SUM, AVG, COUNT)
    - Range scans
    - Large result sets
    - Complex queries with GROUP BY
    - Fewer concurrent queries but longer duration
    """

    def __init__(
        self,
        table_config: TableConfig,
        read_weight: float = 0.95,
        write_weight: float = 0.05,
        seed: Optional[int] = None,
    ):
        super().__init__(table_config, read_weight, write_weight, seed)

        self.aggregation_weight = 0.4
        self.range_scan_weight = 0.3
        self.join_weight = 0.2
        self.complex_weight = 0.1

    def generate_operation(self) -> Operation:
        """Generate OLAP-style operation"""
        if self.should_read():
            query_type = self.random.choices(
                ["aggregation", "range_scan", "join", "complex"],
                weights=[
                    self.aggregation_weight,
                    self.range_scan_weight,
                    self.join_weight,
                    self.complex_weight,
                ],
            )[0]

            if query_type == "aggregation":
                return self._generate_aggregation()
            elif query_type == "range_scan":
                return self._generate_range_scan()
            elif query_type == "join":
                return self._generate_join()
            else:
                return self._generate_complex_query()
        else:
            return self._generate_bulk_insert()

    def _generate_aggregation(self) -> Operation:
        """Generate aggregation query with GROUP BY"""
        metric = self.random.choice(
            ["SUM(amount)", "AVG(amount)", "COUNT(*)", "COUNT(DISTINCT customer_id)"]
        )
        group_by = self.random.choice(
            ["region", "status", "DATE_TRUNC('day', created_at)"]
        )

        query = f"""
        SELECT {group_by} as dimension,
               {metric} as metric_value,
               COUNT(*) as row_count
        FROM {self.full_table_name}
        WHERE created_at >= DATEADD(day, -30, CURRENT_DATE())
        GROUP BY {group_by}
        ORDER BY metric_value DESC
        LIMIT 100
        """

        return Operation(
            operation_type="READ",
            query=query.strip(),
            expected_rows=100,
            description=f"Aggregation: {metric} by {group_by}",
        )

    def _generate_range_scan(self) -> Operation:
        """Generate range scan query"""
        days_back = self.random.randint(7, 90)

        query = f"""
        SELECT *
        FROM {self.full_table_name}
        WHERE created_at >= DATEADD(day, -{days_back}, CURRENT_DATE())
          AND status IN ('ACTIVE', 'PENDING')
        ORDER BY created_at DESC
        LIMIT 10000
        """

        return Operation(
            operation_type="READ",
            query=query.strip(),
            expected_rows=10000,
            description=f"Range scan: last {days_back} days",
        )

    def _generate_join(self) -> Operation:
        """Generate query with join (simulated with self-join)"""
        query = f"""
        SELECT 
            t1.region,
            COUNT(DISTINCT t1.customer_id) as unique_customers,
            SUM(t1.amount) as total_amount,
            AVG(t1.amount) as avg_amount
        FROM {self.full_table_name} t1
        WHERE t1.created_at >= DATEADD(day, -30, CURRENT_DATE())
        GROUP BY t1.region
        HAVING COUNT(*) > 100
        ORDER BY total_amount DESC
        """

        return Operation(
            operation_type="READ",
            query=query.strip(),
            expected_rows=10,
            description="Join query with aggregation",
        )

    def _generate_complex_query(self) -> Operation:
        """Generate complex analytical query"""
        query = f"""
        WITH daily_stats AS (
            SELECT 
                DATE_TRUNC('day', created_at) as date,
                region,
                status,
                SUM(amount) as daily_amount,
                COUNT(*) as daily_count
            FROM {self.full_table_name}
            WHERE created_at >= DATEADD(day, -90, CURRENT_DATE())
            GROUP BY 1, 2, 3
        )
        SELECT 
            region,
            status,
            AVG(daily_amount) as avg_daily_amount,
            MAX(daily_amount) as max_daily_amount,
            SUM(daily_count) as total_count
        FROM daily_stats
        GROUP BY region, status
        ORDER BY avg_daily_amount DESC
        """

        return Operation(
            operation_type="READ",
            query=query.strip(),
            expected_rows=50,
            description="Complex analytical query with CTE",
        )

    def _generate_bulk_insert(self) -> Operation:
        """Generate bulk insert operation"""
        batch_size = 1000

        query = f"""
        INSERT INTO {self.full_table_name} (id, customer_id, region, status, amount, created_at)
        SELECT 
            SEQ8() + ? as id,
            UNIFORM(1, 10000, RANDOM()) as customer_id,
            ARRAY_CONSTRUCT('US-EAST', 'US-WEST', 'EU', 'ASIA')[UNIFORM(0, 3, RANDOM())] as region,
            ARRAY_CONSTRUCT('ACTIVE', 'PENDING', 'COMPLETED')[UNIFORM(0, 2, RANDOM())] as status,
            UNIFORM(10, 1000, RANDOM()) as amount,
            CURRENT_TIMESTAMP() as created_at
        FROM TABLE(GENERATOR(ROWCOUNT => {batch_size}))
        """

        return Operation(
            operation_type="WRITE",
            query=query.strip(),
            params=[self.random.randint(1000000, 10000000)],
            description=f"Bulk insert {batch_size} rows",
        )


class MixedWorkloadGenerator(WorkloadGenerator):
    """
    Mixed workload generator combining OLTP and OLAP patterns.

    Simulates realistic production workloads with both transactional
    and analytical queries running concurrently.
    """

    def __init__(
        self,
        table_config: TableConfig,
        oltp_weight: float = 0.7,
        olap_weight: float = 0.3,
        seed: Optional[int] = None,
    ):
        self.oltp_weight = oltp_weight
        self.olap_weight = olap_weight

        read_weight = 0.5
        write_weight = 0.5
        super().__init__(table_config, read_weight, write_weight, seed)

        self.oltp_generator = OLTPWorkloadGenerator(
            table_config, read_weight=0.7, write_weight=0.3, seed=seed
        )

        self.olap_generator = OLAPWorkloadGenerator(
            table_config, read_weight=0.95, write_weight=0.05, seed=seed
        )

    def generate_operation(self) -> Operation:
        """Generate mixed OLTP/OLAP operation"""
        if self.random.random() < self.oltp_weight:
            return self.oltp_generator.generate_operation()
        else:
            return self.olap_generator.generate_operation()


def create_workload_generator(
    workload_type: WorkloadType, table_config: TableConfig, **kwargs
) -> WorkloadGenerator:
    """
    Factory function to create appropriate workload generator.

    Args:
        workload_type: Type of workload to generate
        table_config: Table configuration
        **kwargs: Additional arguments for specific generators

    Returns:
        WorkloadGenerator instance
    """
    if workload_type == WorkloadType.OLTP:
        return OLTPWorkloadGenerator(table_config, **kwargs)

    elif workload_type == WorkloadType.OLAP:
        return OLAPWorkloadGenerator(table_config, **kwargs)

    elif workload_type == WorkloadType.MIXED:
        return MixedWorkloadGenerator(table_config, **kwargs)

    elif workload_type == WorkloadType.READ_ONLY:
        return OLTPWorkloadGenerator(
            table_config, read_weight=1.0, write_weight=0.0, **kwargs
        )

    elif workload_type == WorkloadType.WRITE_ONLY:
        return OLTPWorkloadGenerator(
            table_config, read_weight=0.0, write_weight=1.0, **kwargs
        )

    elif workload_type == WorkloadType.READ_HEAVY:
        return MixedWorkloadGenerator(
            table_config, oltp_weight=0.8, olap_weight=0.2, **kwargs
        )

    elif workload_type == WorkloadType.WRITE_HEAVY:
        return OLTPWorkloadGenerator(
            table_config, read_weight=0.2, write_weight=0.8, **kwargs
        )

    else:
        raise ValueError(f"Unknown workload type: {workload_type}")
