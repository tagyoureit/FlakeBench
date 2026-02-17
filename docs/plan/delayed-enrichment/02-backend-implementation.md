# Delayed Enrichment - Backend Implementation

**Document Version:** 0.2 (Review Pass 1)  
**Parent:** [00-overview.md](00-overview.md)

---

## 1. Module Structure

### 1.1 New Files

```
backend/
├── core/
│   ├── delayed_enrichment.py          # NEW: Main processor and enrichment functions
│   ├── delayed_enrichment_queries.py  # NEW: SQL queries for ACCOUNT_USAGE views
│   └── results_store.py               # MODIFY: Add queue management, status updates
├── api/
│   └── routes/
│       └── test_results.py            # MODIFY: Add delayed enrichment endpoints
├── websocket/
│   ├── streaming.py                   # MODIFY: Add delayed enrichment status streaming
│   └── queries.py                     # MODIFY: Add delayed enrichment status queries
└── main.py                            # MODIFY: Start delayed enrichment processor
```

### 1.2 File Responsibilities

| File | Responsibility |
|------|---------------|
| `delayed_enrichment.py` | Background processor, orchestrates all delayed enrichment |
| `delayed_enrichment_queries.py` | Raw SQL queries against ACCOUNT_USAGE views |
| `results_store.py` | Queue management, status updates, test metadata |
| `test_results.py` | API endpoints for delayed enrichment status/retry |
| `streaming.py` | WebSocket events for delayed enrichment updates |

---

## 2. Core Implementation

### 2.1 delayed_enrichment.py

```python
# backend/core/delayed_enrichment.py
"""
Delayed Enrichment Processor

Background task that enriches test results from Snowflake ACCOUNT_USAGE views
after the 45-minute to 3-hour latency window.

ACCOUNT_USAGE Views Used:
- QUERY_HISTORY: Partition/spill stats (45 min latency)
- AGGREGATE_QUERY_HISTORY: Hybrid table percentiles (3 hour latency)
- LOCK_WAIT_HISTORY: Row-level lock contention (3 hour latency)
- HYBRID_TABLE_USAGE_HISTORY: Serverless credits (3 hour latency)
- QUERY_INSIGHTS: Optimization suggestions (90 min latency)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from backend.config import settings
from backend.connectors import snowflake_pool
from backend.core.delayed_enrichment_queries import (
    query_account_usage_query_history,
    query_aggregate_query_history,
    query_hybrid_table_usage_history,
    query_lock_wait_history,
    query_query_insights,
)

logger = logging.getLogger(__name__)


class EnrichmentType(str, Enum):
    """Types of delayed enrichment available."""
    QUERY_HISTORY = "QUERY_HISTORY"           # 45 min latency
    AGGREGATE = "AGGREGATE"                    # 3 hour latency
    LOCK_CONTENTION = "LOCK_CONTENTION"       # 3 hour latency
    HYBRID_CREDITS = "HYBRID_CREDITS"         # 3 hour latency
    QUERY_INSIGHTS = "QUERY_INSIGHTS"         # 90 min latency


# Latency buffers (add safety margin to documented latencies)
ENRICHMENT_LATENCIES = {
    EnrichmentType.QUERY_HISTORY: timedelta(minutes=50),    # 45 min + 5 min buffer
    EnrichmentType.AGGREGATE: timedelta(hours=3, minutes=15),
    EnrichmentType.LOCK_CONTENTION: timedelta(hours=3, minutes=15),
    EnrichmentType.HYBRID_CREDITS: timedelta(hours=3, minutes=15),
    EnrichmentType.QUERY_INSIGHTS: timedelta(minutes=100),  # 90 min + 10 min buffer
}


@dataclass
class EnrichmentJob:
    """Represents a pending delayed enrichment job."""
    job_id: str
    test_id: str
    run_id: str
    table_type: str
    test_end_time: datetime
    enrichment_types: list[EnrichmentType]
    status: str = "PENDING"
    attempts: int = 0
    last_error: str | None = None


@dataclass
class EnrichmentResult:
    """Result of a single enrichment operation."""
    enrichment_type: EnrichmentType
    success: bool
    rows_enriched: int = 0
    error: str | None = None
    duration_ms: float = 0


def _results_prefix() -> str:
    """Get fully-qualified prefix for results tables."""
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


def get_enrichment_types_for_table_type(table_type: str) -> list[EnrichmentType]:
    """
    Determine which enrichment types are applicable for a table type.
    
    Args:
        table_type: HYBRID, STANDARD, INTERACTIVE, DYNAMIC, POSTGRES
        
    Returns:
        List of applicable enrichment types
    """
    table_type_upper = (table_type or "").strip().upper()
    
    if table_type_upper == "POSTGRES":
        # Postgres uses pg_stat_statements, not Snowflake ACCOUNT_USAGE
        return []
    
    # All Snowflake table types get QUERY_HISTORY and QUERY_INSIGHTS
    types = [EnrichmentType.QUERY_HISTORY, EnrichmentType.QUERY_INSIGHTS]
    
    if table_type_upper in ("HYBRID", "UNISTORE"):
        # Hybrid tables get all enrichment types
        types.extend([
            EnrichmentType.AGGREGATE,
            EnrichmentType.LOCK_CONTENTION,
            EnrichmentType.HYBRID_CREDITS,
        ])
    else:
        # Standard/Interactive/Dynamic tables get AGGREGATE for percentiles
        # but not LOCK_CONTENTION or HYBRID_CREDITS
        types.append(EnrichmentType.AGGREGATE)
    
    return types


def calculate_earliest_enrichment_time(
    test_end_time: datetime,
    enrichment_types: list[EnrichmentType],
) -> datetime:
    """
    Calculate when all requested enrichment types will be available.
    
    Returns the maximum latency across all types (conservative).
    """
    if not enrichment_types:
        return test_end_time
    
    max_latency = max(ENRICHMENT_LATENCIES.get(t, timedelta(hours=3)) for t in enrichment_types)
    return test_end_time + max_latency


async def create_delayed_enrichment_job(
    *,
    test_id: str,
    run_id: str,
    table_type: str,
    test_end_time: datetime,
) -> str | None:
    """
    Create a delayed enrichment job in the queue.
    
    Args:
        test_id: Test ID to enrich
        run_id: Run ID (same as test_id for parent rows)
        table_type: Table type (affects which enrichments apply)
        test_end_time: When the test completed
        
    Returns:
        Job ID if created, None if no enrichments applicable
    """
    enrichment_types = get_enrichment_types_for_table_type(table_type)
    if not enrichment_types:
        logger.info(
            "No delayed enrichment applicable for table_type=%s, test_id=%s",
            table_type, test_id
        )
        return None
    
    job_id = str(uuid4())
    earliest_time = calculate_earliest_enrichment_time(test_end_time, enrichment_types)
    
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()
    
    await pool.execute_query(
        f"""
        INSERT INTO {prefix}.DELAYED_ENRICHMENT_QUEUE (
            JOB_ID, TEST_ID, RUN_ID, TABLE_TYPE,
            TEST_END_TIME, EARLIEST_ENRICHMENT_TIME,
            ENRICHMENT_TYPES, STATUS
        )
        SELECT ?, ?, ?, ?, ?, ?, PARSE_JSON(?), 'PENDING'
        """,
        params=[
            job_id, test_id, run_id, table_type.upper(),
            test_end_time.isoformat(), earliest_time.isoformat(),
            json.dumps([t.value for t in enrichment_types]),
        ],
    )
    
    # Update TEST_RESULTS with pending status
    await pool.execute_query(
        f"""
        UPDATE {prefix}.TEST_RESULTS
        SET DELAYED_ENRICHMENT_STATUS = 'PENDING',
            UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE TEST_ID = ? AND RUN_ID = ?
        """,
        params=[test_id, run_id],
    )
    
    logger.info(
        "Created delayed enrichment job %s for test %s (types=%s, earliest=%s)",
        job_id, test_id, [t.value for t in enrichment_types], earliest_time
    )
    
    return job_id


class DelayedEnrichmentProcessor:
    """
    Background processor for delayed enrichment jobs.
    
    Polls the DELAYED_ENRICHMENT_QUEUE table for eligible jobs and
    executes enrichment against ACCOUNT_USAGE views.
    """
    
    # Connection pool: Uses the shared snowflake_pool from backend.connectors.
    # The pool is configured in backend/config.py with max_connections and idle_timeout.
    # All ACCOUNT_USAGE queries go through the SNOWFLAKE database, which requires
    # IMPORTED PRIVILEGES grant on the service account's role.
    
    def __init__(
        self,
        poll_interval_seconds: int = 300,  # 5 minutes
        max_concurrent_jobs: int = 3,
        max_retries: int = 3,
    ):
        self.poll_interval = poll_interval_seconds
        self.max_concurrent = max_concurrent_jobs
        self.max_retries = max_retries
        self._running = False
        self._task: asyncio.Task | None = None
        self._pool = snowflake_pool.get_default_pool()
        # v0.2: Unique worker ID for atomic job claiming
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
    
    async def start(self) -> None:
        """Start the background processor."""
        if self._running:
            logger.warning("DelayedEnrichmentProcessor already running")
            return
        
        # v0.2 (D9): Verify ACCOUNT_USAGE access on startup
        has_access = await self._check_account_usage_access()
        if not has_access:
            # v0.3: Log at CRITICAL per D9 decision, but still start in degraded mode
            # so the queue doesn't grow unbounded. Jobs will fail individually with clear errors.
            logger.critical(
                "ACCOUNT_USAGE access check FAILED. Processor starting in degraded mode. "
                "All enrichment jobs will fail until IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE is granted."
            )
        
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="delayed-enrichment-processor"
        )
        logger.info(
            "DelayedEnrichmentProcessor started (poll_interval=%ds, max_concurrent=%d, worker_id=%s)",
            self.poll_interval, self.max_concurrent, self.worker_id
        )
    
    async def _check_account_usage_access(self) -> bool:
        """v0.2 (D9): Probe query to verify ACCOUNT_USAGE access on startup."""
        try:
            await self._pool.execute_query(
                "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 0"
            )
            logger.info("ACCOUNT_USAGE access verified")
            return True
        except Exception as e:
            logger.error("ACCOUNT_USAGE access check failed: %s", e)
            return False
    
    async def stop(self, timeout_seconds: int = 30) -> None:
        """Stop the background processor gracefully."""
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=timeout_seconds)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        # v0.2: Recover orphaned IN_PROGRESS jobs from this worker
        await self._recover_orphaned_jobs()
        logger.info("DelayedEnrichmentProcessor stopped")
    
    async def _recover_orphaned_jobs(self) -> None:
        """Reset any IN_PROGRESS jobs claimed by this worker back to PENDING."""
        prefix = _results_prefix()
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.DELAYED_ENRICHMENT_QUEUE
            SET STATUS = 'PENDING', CLAIMED_BY = NULL, CLAIMED_AT = NULL,
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE STATUS = 'IN_PROGRESS' AND CLAIMED_BY = ?
            """,
            params=[self.worker_id],
        )
    
    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._process_eligible_jobs()
            except Exception as e:
                logger.error("Error in delayed enrichment poll loop: %s", e)
            
            await asyncio.sleep(self.poll_interval)
    
    async def _process_eligible_jobs(self) -> None:
        """Find and process eligible delayed enrichment jobs."""
        prefix = _results_prefix()
        
        # v0.2: Atomic claim pattern to prevent race conditions with multiple workers
        # Uses UPDATE...RETURNING to atomically claim a job
        for _ in range(self.max_concurrent):
            rows = await self._pool.execute_query(
                f"""
                UPDATE {prefix}.DELAYED_ENRICHMENT_QUEUE
                SET STATUS = 'IN_PROGRESS',
                    CLAIMED_BY = ?,
                    CLAIMED_AT = CURRENT_TIMESTAMP(),
                    LAST_ATTEMPT_AT = CURRENT_TIMESTAMP(),
                    ATTEMPTS = ATTEMPTS + 1,
                    UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE JOB_ID = (
                    SELECT JOB_ID
                    FROM {prefix}.DELAYED_ENRICHMENT_QUEUE
                    WHERE STATUS = 'PENDING'
                      AND EARLIEST_ENRICHMENT_TIME <= CURRENT_TIMESTAMP()
                      AND ATTEMPTS < ?
                    ORDER BY EARLIEST_ENRICHMENT_TIME ASC
                    LIMIT 1
                )
                  AND STATUS = 'PENDING'  -- v0.3: Double-check prevents race where two workers claim same JOB_ID
                RETURNING JOB_ID, TEST_ID, RUN_ID, TABLE_TYPE,
                          TEST_END_TIME, ENRICHMENT_TYPES, ATTEMPTS
                """,
                params=[self.worker_id, self.max_retries],
            )
            
            if not rows:
                logger.debug("No more eligible delayed enrichment jobs found")
                break
            
            row = rows[0]
            job_id, test_id, run_id, table_type, test_end_time, enrichment_types_raw, attempts = row
            
            logger.info("Claimed delayed enrichment job %s for test %s", job_id, test_id)
            
            # Parse enrichment types
            if isinstance(enrichment_types_raw, str):
                enrichment_types = [EnrichmentType(t) for t in json.loads(enrichment_types_raw)]
            elif isinstance(enrichment_types_raw, list):
                enrichment_types = [EnrichmentType(t) for t in enrichment_types_raw]
            else:
                enrichment_types = []
            
            job = EnrichmentJob(
                job_id=job_id,
                test_id=test_id,
                run_id=run_id,
                table_type=table_type,
                test_end_time=test_end_time if isinstance(test_end_time, datetime) else datetime.fromisoformat(str(test_end_time)),
                enrichment_types=enrichment_types,
                attempts=int(attempts or 0),
            )
            
            await self._process_job(job)
    
    async def _process_job(self, job: EnrichmentJob) -> None:
        """Process a single delayed enrichment job."""
        prefix = _results_prefix()
        
        logger.info(
            "Processing delayed enrichment job %s for test %s (attempt %d)",
            job.job_id, job.test_id, job.attempts
        )
        
        # v0.2: Job already marked IN_PROGRESS by atomic claim in _process_eligible_jobs
        # Update TEST_RESULTS status
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS
            SET DELAYED_ENRICHMENT_STATUS = 'IN_PROGRESS',
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[job.test_id, job.run_id],
        )
        
        # Get test metadata for enrichment
        test_meta = await self._get_test_metadata(job.test_id)
        if not test_meta:
            await self._mark_job_failed(job, "Test metadata not found")
            return
        
        # Execute each enrichment type
        results: list[EnrichmentResult] = []
        completed_types: list[str] = []
        
        for enrichment_type in job.enrichment_types:
            try:
                result = await self._execute_enrichment(
                    enrichment_type=enrichment_type,
                    job=job,
                    test_meta=test_meta,
                )
                results.append(result)
                if result.success:
                    completed_types.append(enrichment_type.value)
            except Exception as e:
                logger.error(
                    "Enrichment %s failed for test %s: %s",
                    enrichment_type.value, job.test_id, e
                )
                results.append(EnrichmentResult(
                    enrichment_type=enrichment_type,
                    success=False,
                    error=str(e),
                ))
        
        # Determine overall success
        all_success = all(r.success for r in results)
        any_success = any(r.success for r in results)
        errors = [r.error for r in results if r.error]
        
        if all_success:
            await self._mark_job_completed(job, completed_types)
        elif any_success and job.attempts >= self.max_retries:
            # Partial success on final attempt - mark as completed with note
            await self._mark_job_completed(job, completed_types, partial=True, errors=errors)
        elif job.attempts >= self.max_retries:
            await self._mark_job_failed(job, "; ".join(errors) if errors else "Unknown error")
        else:
            # Reset to pending for retry
            await self._pool.execute_query(
                f"""
                UPDATE {prefix}.DELAYED_ENRICHMENT_QUEUE
                SET STATUS = 'PENDING',
                    LAST_ERROR = ?,
                    COMPLETED_TYPES = PARSE_JSON(?),
                    UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE JOB_ID = ?
                """,
                params=[
                    "; ".join(errors) if errors else None,
                    json.dumps(completed_types),
                    job.job_id,
                ],
            )
    
    async def _get_test_metadata(self, test_id: str) -> dict[str, Any] | None:
        """Fetch test metadata needed for enrichment queries."""
        prefix = _results_prefix()
        
        rows = await self._pool.execute_query(
            f"""
            SELECT
                TEST_ID, RUN_ID, QUERY_TAG,
                START_TIME, END_TIME,
                TABLE_NAME, TABLE_TYPE,
                TEST_CONFIG:target:database::VARCHAR AS DATABASE_NAME,
                TEST_CONFIG:target:schema::VARCHAR AS SCHEMA_NAME
            FROM {prefix}.TEST_RESULTS
            WHERE TEST_ID = ?
            LIMIT 1
            """,
            params=[test_id],
        )
        
        if not rows:
            return None
        
        row = rows[0]
        return {
            "test_id": row[0],
            "run_id": row[1],
            "query_tag": row[2],
            "start_time": row[3],
            "end_time": row[4],
            "table_name": row[5],
            "table_type": row[6],
            "database_name": row[7],
            "schema_name": row[8],
        }
    
    async def _execute_enrichment(
        self,
        *,
        enrichment_type: EnrichmentType,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> EnrichmentResult:
        """Execute a single enrichment type."""
        start = datetime.now(UTC)
        
        try:
            if enrichment_type == EnrichmentType.QUERY_HISTORY:
                rows_enriched = await self._enrich_from_account_usage_query_history(job, test_meta)
            elif enrichment_type == EnrichmentType.AGGREGATE:
                rows_enriched = await self._enrich_from_aggregate_query_history(job, test_meta)
            elif enrichment_type == EnrichmentType.LOCK_CONTENTION:
                rows_enriched = await self._enrich_from_lock_wait_history(job, test_meta)
            elif enrichment_type == EnrichmentType.HYBRID_CREDITS:
                rows_enriched = await self._enrich_from_hybrid_table_usage(job, test_meta)
            elif enrichment_type == EnrichmentType.QUERY_INSIGHTS:
                rows_enriched = await self._enrich_from_query_insights(job, test_meta)
            else:
                raise ValueError(f"Unknown enrichment type: {enrichment_type}")
            
            duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            
            logger.info(
                "Enrichment %s completed for test %s: %d rows in %.1fms",
                enrichment_type.value, job.test_id, rows_enriched, duration_ms
            )
            
            return EnrichmentResult(
                enrichment_type=enrichment_type,
                success=True,
                rows_enriched=rows_enriched,
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            logger.error(
                "Enrichment %s failed for test %s after %.1fms: %s",
                enrichment_type.value, job.test_id, duration_ms, e
            )
            return EnrichmentResult(
                enrichment_type=enrichment_type,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def _enrich_from_account_usage_query_history(
        self,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> int:
        """
        Enrich QUERY_EXECUTIONS with partition/spill stats from ACCOUNT_USAGE.QUERY_HISTORY.
        
        This fills columns that INFORMATION_SCHEMA.QUERY_HISTORY doesn't provide:
        - sf_partitions_scanned
        - sf_partitions_total
        - sf_bytes_spilled_local
        - sf_bytes_spilled_remote
        """
        prefix = _results_prefix()
        query_tag = test_meta.get("query_tag") or ""
        
        # Strip phase suffix for broader matching
        if ":phase=" in query_tag:
            query_tag = query_tag.split(":phase=")[0]
        query_tag_like = f"{query_tag}%"
        
        start_time = test_meta["start_time"]
        end_time = test_meta["end_time"]
        
        # Add buffer to time range
        start_buf = (start_time - timedelta(minutes=5)).isoformat() if start_time else None
        end_buf = (end_time + timedelta(minutes=5)).isoformat() if end_time else None
        
        if not start_buf or not end_buf:
            return 0
        
        # MERGE to update QUERY_EXECUTIONS with partition/spill stats
        merge_query = f"""
        MERGE INTO {prefix}.QUERY_EXECUTIONS tgt
        USING (
            SELECT
                QUERY_ID,
                PARTITIONS_SCANNED::BIGINT AS PARTITIONS_SCANNED,
                PARTITIONS_TOTAL::BIGINT AS PARTITIONS_TOTAL,
                BYTES_SPILLED_TO_LOCAL_STORAGE::BIGINT AS BYTES_SPILLED_LOCAL,
                BYTES_SPILLED_TO_REMOTE_STORAGE::BIGINT AS BYTES_SPILLED_REMOTE,
                QUERY_PARAMETERIZED_HASH
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE QUERY_TAG LIKE ?
              AND START_TIME >= TO_TIMESTAMP_LTZ(?)
              AND START_TIME <= TO_TIMESTAMP_LTZ(?)
        ) src
        ON tgt.QUERY_ID = src.QUERY_ID
        WHEN MATCHED THEN UPDATE SET
            SF_PARTITIONS_SCANNED = src.PARTITIONS_SCANNED,
            SF_PARTITIONS_TOTAL = src.PARTITIONS_TOTAL,
            SF_BYTES_SPILLED_LOCAL = src.BYTES_SPILLED_LOCAL,
            SF_BYTES_SPILLED_REMOTE = src.BYTES_SPILLED_REMOTE,
            QUERY_PARAMETERIZED_HASH = src.QUERY_PARAMETERIZED_HASH
        """
        
        # v0.2: 120s timeout for ACCOUNT_USAGE queries
        result = await self._pool.execute_query(
            merge_query,
            params=[query_tag_like, start_buf, end_buf],
        )
        
        # v0.2: Parse merge result for actual row count
        rows_affected = result[0][0] if result and result[0] else 0
        return rows_affected
    
    async def _enrich_from_aggregate_query_history(
        self,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> int:
        """
        Enrich from AGGREGATE_QUERY_HISTORY.
        
        Inserts rows into AGGREGATE_QUERY_METRICS with server-side percentiles.
        This is the PRIMARY enrichment for hybrid tables since individual queries
        are often skipped from QUERY_HISTORY.
        """
        prefix = _results_prefix()
        query_tag = test_meta.get("query_tag") or ""
        
        # Strip phase suffix
        if ":phase=" in query_tag:
            query_tag = query_tag.split(":phase=")[0]
        
        # Build query_tag pattern for run_id matching
        run_id = job.run_id
        query_tag_like = f"flakebench:run_id={run_id}%"
        
        start_time = test_meta["start_time"]
        end_time = test_meta["end_time"]
        
        start_buf = (start_time - timedelta(minutes=5)).isoformat() if start_time else None
        end_buf = (end_time + timedelta(minutes=10)).isoformat() if end_time else None
        
        if not start_buf or not end_buf:
            return 0
        
        # v0.2: DELETE-then-INSERT for idempotency (D8)
        await self._pool.execute_query(
            f"DELETE FROM {prefix}.AGGREGATE_QUERY_METRICS WHERE TEST_ID = ? AND RUN_ID = ?",
            params=[job.test_id, job.run_id],
        )
        
        # v0.2: 120s timeout for ACCOUNT_USAGE queries
        # Query AGGREGATE_QUERY_HISTORY and insert into AGGREGATE_QUERY_METRICS
        insert_query = f"""
        INSERT INTO {prefix}.AGGREGATE_QUERY_METRICS (
            METRIC_ID, TEST_ID, RUN_ID,
            QUERY_PARAMETERIZED_HASH, QUERY_TAG,
            INTERVAL_START, INTERVAL_END, INTERVAL_COUNT,
            QUERY_COUNT, ERRORS_COUNT,
            EXEC_SUM_MS, EXEC_AVG_MS, EXEC_STDDEV_MS,
            EXEC_MIN_MS, EXEC_MEDIAN_MS, EXEC_P90_MS, EXEC_P95_MS, EXEC_P99_MS, EXEC_P999_MS, EXEC_MAX_MS,
            COMPILE_SUM_MS, COMPILE_AVG_MS, COMPILE_MIN_MS, COMPILE_MEDIAN_MS,
            COMPILE_P90_MS, COMPILE_P99_MS, COMPILE_MAX_MS,
            ELAPSED_SUM_MS, ELAPSED_AVG_MS, ELAPSED_MIN_MS, ELAPSED_MEDIAN_MS,
            ELAPSED_P90_MS, ELAPSED_P99_MS, ELAPSED_MAX_MS,
            QUEUED_OVERLOAD_SUM_MS, QUEUED_OVERLOAD_AVG_MS, QUEUED_OVERLOAD_MAX_MS,
            QUEUED_PROVISIONING_SUM_MS, QUEUED_PROVISIONING_AVG_MS, QUEUED_PROVISIONING_MAX_MS,
            HYBRID_REQUESTS_THROTTLED_COUNT,
            BYTES_SCANNED_SUM, BYTES_SCANNED_AVG, BYTES_SCANNED_MAX,
            ROWS_PRODUCED_SUM, ROWS_PRODUCED_AVG, ROWS_PRODUCED_MAX,
            ERRORS_BREAKDOWN
        )
        SELECT
            UUID_STRING() AS METRIC_ID,
            ? AS TEST_ID,
            ? AS RUN_ID,
            QUERY_PARAMETERIZED_HASH,
            QUERY_TAG,
            MIN(INTERVAL_START_TIME) AS INTERVAL_START,
            MAX(INTERVAL_END_TIME) AS INTERVAL_END,
            COUNT(*) AS INTERVAL_COUNT,
            SUM(QUERY_COUNT) AS QUERY_COUNT,
            SUM(ARRAY_SIZE(COALESCE(ERRORS, ARRAY_CONSTRUCT()))) AS ERRORS_COUNT,
            -- Execution time
            SUM(EXECUTION_TIME:sum::FLOAT) AS EXEC_SUM_MS,
            AVG(EXECUTION_TIME:avg::FLOAT) AS EXEC_AVG_MS,
            AVG(EXECUTION_TIME:stddev::FLOAT) AS EXEC_STDDEV_MS,
            MIN(EXECUTION_TIME:min::FLOAT) AS EXEC_MIN_MS,
            AVG(EXECUTION_TIME:median::FLOAT) AS EXEC_MEDIAN_MS,
            MAX(EXECUTION_TIME:p90::FLOAT) AS EXEC_P90_MS,
            -- v0.3: P95 interpolated as midpoint of P90 and P99 (AGGREGATE_QUERY_HISTORY has no native P95)
            (MAX(EXECUTION_TIME:p90::FLOAT) + MAX(EXECUTION_TIME:p99::FLOAT)) / 2.0 AS EXEC_P95_MS,
            MAX(EXECUTION_TIME:p99::FLOAT) AS EXEC_P99_MS,
            MAX(EXECUTION_TIME:"p99.9"::FLOAT) AS EXEC_P999_MS,
            MAX(EXECUTION_TIME:max::FLOAT) AS EXEC_MAX_MS,
            -- Compilation time
            SUM(COMPILATION_TIME:sum::FLOAT) AS COMPILE_SUM_MS,
            AVG(COMPILATION_TIME:avg::FLOAT) AS COMPILE_AVG_MS,
            MIN(COMPILATION_TIME:min::FLOAT) AS COMPILE_MIN_MS,
            AVG(COMPILATION_TIME:median::FLOAT) AS COMPILE_MEDIAN_MS,
            MAX(COMPILATION_TIME:p90::FLOAT) AS COMPILE_P90_MS,
            MAX(COMPILATION_TIME:p99::FLOAT) AS COMPILE_P99_MS,
            MAX(COMPILATION_TIME:max::FLOAT) AS COMPILE_MAX_MS,
            -- Total elapsed time
            SUM(TOTAL_ELAPSED_TIME:sum::FLOAT) AS ELAPSED_SUM_MS,
            AVG(TOTAL_ELAPSED_TIME:avg::FLOAT) AS ELAPSED_AVG_MS,
            MIN(TOTAL_ELAPSED_TIME:min::FLOAT) AS ELAPSED_MIN_MS,
            AVG(TOTAL_ELAPSED_TIME:median::FLOAT) AS ELAPSED_MEDIAN_MS,
            MAX(TOTAL_ELAPSED_TIME:p90::FLOAT) AS ELAPSED_P90_MS,
            MAX(TOTAL_ELAPSED_TIME:p99::FLOAT) AS ELAPSED_P99_MS,
            MAX(TOTAL_ELAPSED_TIME:max::FLOAT) AS ELAPSED_MAX_MS,
            -- Queue time
            SUM(QUEUED_OVERLOAD_TIME:sum::FLOAT) AS QUEUED_OVERLOAD_SUM_MS,
            AVG(QUEUED_OVERLOAD_TIME:avg::FLOAT) AS QUEUED_OVERLOAD_AVG_MS,
            MAX(QUEUED_OVERLOAD_TIME:max::FLOAT) AS QUEUED_OVERLOAD_MAX_MS,
            SUM(QUEUED_PROVISIONING_TIME:sum::FLOAT) AS QUEUED_PROVISIONING_SUM_MS,
            AVG(QUEUED_PROVISIONING_TIME:avg::FLOAT) AS QUEUED_PROVISIONING_AVG_MS,
            MAX(QUEUED_PROVISIONING_TIME:max::FLOAT) AS QUEUED_PROVISIONING_MAX_MS,
            -- Hybrid table throttling
            SUM(HYBRID_TABLE_REQUESTS_THROTTLED_COUNT) AS HYBRID_REQUESTS_THROTTLED_COUNT,
            -- Bytes scanned
            SUM(BYTES_SCANNED:sum::BIGINT) AS BYTES_SCANNED_SUM,
            AVG(BYTES_SCANNED:avg::BIGINT) AS BYTES_SCANNED_AVG,
            MAX(BYTES_SCANNED:max::BIGINT) AS BYTES_SCANNED_MAX,
            -- Rows produced
            SUM(ROWS_PRODUCED:sum::BIGINT) AS ROWS_PRODUCED_SUM,
            AVG(ROWS_PRODUCED:avg::BIGINT) AS ROWS_PRODUCED_AVG,
            MAX(ROWS_PRODUCED:max::BIGINT) AS ROWS_PRODUCED_MAX,
            -- Errors
            ARRAY_AGG(ERRORS) AS ERRORS_BREAKDOWN
        FROM SNOWFLAKE.ACCOUNT_USAGE.AGGREGATE_QUERY_HISTORY
        WHERE QUERY_TAG LIKE ?
          AND INTERVAL_START_TIME >= TO_TIMESTAMP_LTZ(?)
          AND INTERVAL_END_TIME <= TO_TIMESTAMP_LTZ(?)
        GROUP BY QUERY_PARAMETERIZED_HASH, QUERY_TAG
        """
        
        result = await self._pool.execute_query(
            insert_query,
            params=[job.test_id, job.run_id, query_tag_like, start_buf, end_buf],
        )
        
        # Update TEST_RESULTS with aggregate summary
        await self._update_test_aggregate_summary(job.test_id, job.run_id)
        
        # v0.2: Parse result for actual row count
        rows_affected = result[0][0] if result and result[0] else 0
        return rows_affected
    
    async def _update_test_aggregate_summary(self, test_id: str, run_id: str) -> None:
        """Update TEST_RESULTS with summary from AGGREGATE_QUERY_METRICS."""
        prefix = _results_prefix()
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS tr
            SET
                AGGREGATE_ENRICHMENT_STATUS = 'COMPLETED',
                THROTTLED_QUERY_COUNT = (
                    SELECT COALESCE(SUM(HYBRID_REQUESTS_THROTTLED_COUNT), 0)
                    FROM {prefix}.AGGREGATE_QUERY_METRICS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[test_id, run_id],
        )
    
    async def _enrich_from_lock_wait_history(
        self,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> int:
        """
        Enrich from LOCK_WAIT_HISTORY.
        
        Inserts rows into LOCK_CONTENTION_EVENTS for row-level lock waits on hybrid tables.
        """
        prefix = _results_prefix()
        table_name = test_meta.get("table_name") or ""
        database_name = test_meta.get("database_name") or ""
        schema_name = test_meta.get("schema_name") or ""
        
        start_time = test_meta["start_time"]
        end_time = test_meta["end_time"]
        
        if not start_time or not end_time:
            return 0
        
        # v0.2: DELETE-then-INSERT for idempotency (D8)
        await self._pool.execute_query(
            f"DELETE FROM {prefix}.LOCK_CONTENTION_EVENTS WHERE TEST_ID = ? AND RUN_ID = ?",
            params=[job.test_id, job.run_id],
        )
        
        # v0.2: 120s timeout for ACCOUNT_USAGE queries
        # Query LOCK_WAIT_HISTORY and insert into LOCK_CONTENTION_EVENTS
        insert_query = f"""
        INSERT INTO {prefix}.LOCK_CONTENTION_EVENTS (
            EVENT_ID, TEST_ID, RUN_ID,
            LOCK_TRANSACTION_ID, BLOCKING_TRANSACTION_ID,
            REQUESTED_AT, LOCK_ACQUIRED_AT, WAIT_DURATION_MS,
            LOCK_TYPE, OBJECT_ID, OBJECT_NAME, SCHEMA_NAME, DATABASE_NAME,
            QUERY_ID, BLOCKING_QUERY_ID,
            RAW_EVENT
        )
        SELECT
            UUID_STRING() AS EVENT_ID,
            ? AS TEST_ID,
            ? AS RUN_ID,
            LOCK_TRANSACTION_ID,
            BLOCKING_TRANSACTION_ID,
            REQUESTED_AT,
            LOCK_ACQUIRED_AT,
            TIMESTAMPDIFF('millisecond', REQUESTED_AT, LOCK_ACQUIRED_AT) AS WAIT_DURATION_MS,
            LOCK_TYPE,
            OBJECT_ID,
            OBJECT_NAME,
            SCHEMA_NAME,
            DATABASE_NAME,
            QUERY_ID,
            BLOCKING_QUERY_ID,
            OBJECT_CONSTRUCT(*) AS RAW_EVENT
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY
        WHERE OBJECT_NAME = ?
          AND LOCK_TYPE = 'ROW'
          AND REQUESTED_AT >= ?
          AND REQUESTED_AT <= ?
        """
        
        result = await self._pool.execute_query(
            insert_query,
            params=[
                job.test_id, job.run_id,
                table_name.upper(),
                start_time.isoformat(), end_time.isoformat(),
            ],
        )
        
        # Update TEST_RESULTS with lock contention summary
        await self._update_test_lock_summary(job.test_id, job.run_id)
        
        # v0.2: Parse result for actual row count
        rows_affected = result[0][0] if result and result[0] else 0
        return rows_affected
    
    async def _update_test_lock_summary(self, test_id: str, run_id: str) -> None:
        """Update TEST_RESULTS with summary from LOCK_CONTENTION_EVENTS."""
        prefix = _results_prefix()
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS tr
            SET
                LOCK_WAIT_COUNT = (
                    SELECT COUNT(*)
                    FROM {prefix}.LOCK_CONTENTION_EVENTS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                LOCK_WAIT_TOTAL_MS = (
                    SELECT COALESCE(SUM(WAIT_DURATION_MS), 0)
                    FROM {prefix}.LOCK_CONTENTION_EVENTS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                LOCK_WAIT_MAX_MS = (
                    SELECT MAX(WAIT_DURATION_MS)
                    FROM {prefix}.LOCK_CONTENTION_EVENTS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[test_id, run_id],
        )
    
    async def _enrich_from_hybrid_table_usage(
        self,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> int:
        """
        Enrich from HYBRID_TABLE_USAGE_HISTORY.
        
        Inserts rows into HYBRID_TABLE_CREDITS and updates TEST_RESULTS with credit totals.
        """
        prefix = _results_prefix()
        table_name = test_meta.get("table_name") or ""
        
        start_time = test_meta["start_time"]
        end_time = test_meta["end_time"]
        
        if not start_time or not end_time:
            return 0
        
        # v0.2: DELETE-then-INSERT for idempotency (D8)
        await self._pool.execute_query(
            f"DELETE FROM {prefix}.HYBRID_TABLE_CREDITS WHERE TEST_ID = ? AND RUN_ID = ?",
            params=[job.test_id, job.run_id],
        )
        
        # v0.2: 120s timeout for ACCOUNT_USAGE queries
        # Query HYBRID_TABLE_USAGE_HISTORY and insert into HYBRID_TABLE_CREDITS
        insert_query = f"""
        INSERT INTO {prefix}.HYBRID_TABLE_CREDITS (
            CREDIT_ID, TEST_ID, RUN_ID,
            TABLE_ID, TABLE_NAME, SCHEMA_NAME, DATABASE_NAME,
            START_TIME, END_TIME,
            CREDITS_USED, REQUESTS_COUNT
        )
        SELECT
            UUID_STRING() AS CREDIT_ID,
            ? AS TEST_ID,
            ? AS RUN_ID,
            TABLE_ID,
            TABLE_NAME,
            SCHEMA_NAME,
            DATABASE_NAME,
            MIN(START_TIME) AS START_TIME,
            MAX(END_TIME) AS END_TIME,
            SUM(CREDITS_USED) AS CREDITS_USED,
            SUM(REQUESTS) AS REQUESTS_COUNT
        FROM SNOWFLAKE.ACCOUNT_USAGE.HYBRID_TABLE_USAGE_HISTORY
        WHERE TABLE_NAME = ?
          AND START_TIME >= ?
          AND END_TIME <= ?
        GROUP BY TABLE_ID, TABLE_NAME, SCHEMA_NAME, DATABASE_NAME
        """
        
        result = await self._pool.execute_query(
            insert_query,
            params=[
                job.test_id, job.run_id,
                table_name.upper(),
                start_time.isoformat(), end_time.isoformat(),
            ],
        )
        
        # Update TEST_RESULTS with credit totals
        await self._update_test_credits_summary(job.test_id, job.run_id)
        
        # v0.2: Parse result for actual row count
        rows_affected = result[0][0] if result and result[0] else 0
        return rows_affected
    
    async def _update_test_credits_summary(self, test_id: str, run_id: str) -> None:
        """Update TEST_RESULTS with summary from HYBRID_TABLE_CREDITS."""
        prefix = _results_prefix()
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS tr
            SET
                HYBRID_CREDITS_USED = (
                    SELECT COALESCE(SUM(CREDITS_USED), 0)
                    FROM {prefix}.HYBRID_TABLE_CREDITS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                HYBRID_CREDITS_REQUESTS = (
                    SELECT COALESCE(SUM(REQUESTS_COUNT), 0)
                    FROM {prefix}.HYBRID_TABLE_CREDITS
                    WHERE TEST_ID = tr.TEST_ID
                ),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[test_id, run_id],
        )
    
    async def _enrich_from_query_insights(
        self,
        job: EnrichmentJob,
        test_meta: dict[str, Any],
    ) -> int:
        """
        Enrich from QUERY_INSIGHTS.
        
        Inserts rows into QUERY_INSIGHTS_CACHE with optimization recommendations.
        """
        prefix = _results_prefix()
        query_tag = test_meta.get("query_tag") or ""
        
        if ":phase=" in query_tag:
            query_tag = query_tag.split(":phase=")[0]
        query_tag_like = f"{query_tag}%"
        
        start_time = test_meta["start_time"]
        end_time = test_meta["end_time"]
        
        if not start_time or not end_time:
            return 0
        
        # v0.2: DELETE-then-INSERT for idempotency (D8)
        await self._pool.execute_query(
            f"DELETE FROM {prefix}.QUERY_INSIGHTS_CACHE WHERE TEST_ID = ? AND RUN_ID = ?",
            params=[job.test_id, job.run_id],
        )
        
        # v0.2: 120s timeout for ACCOUNT_USAGE queries
        # Query QUERY_INSIGHTS and insert into QUERY_INSIGHTS_CACHE
        # Note: QUERY_INSIGHTS view structure may vary - adjust columns as needed
        insert_query = f"""
        INSERT INTO {prefix}.QUERY_INSIGHTS_CACHE (
            INSIGHT_ID, TEST_ID, RUN_ID,
            QUERY_ID, QUERY_PARAMETERIZED_HASH, QUERY_TEXT,
            INSIGHT_TYPE, INSIGHT_CATEGORY, INSIGHT_SEVERITY,
            RECOMMENDATION, RECOMMENDATION_DETAILS,
            ESTIMATED_IMPROVEMENT_PCT, AFFECTED_QUERY_COUNT,
            EXPIRES_AT
        )
        SELECT
            UUID_STRING() AS INSIGHT_ID,
            ? AS TEST_ID,
            ? AS RUN_ID,
            QUERY_ID,
            QUERY_HASH,
            QUERY_TEXT,
            INSIGHT_NAME AS INSIGHT_TYPE,
            'OPTIMIZATION' AS INSIGHT_CATEGORY,
            'MEDIUM' AS INSIGHT_SEVERITY,
            RECOMMENDATION,
            OBJECT_CONSTRUCT(
                'insight_name', INSIGHT_NAME,
                'query_count', QUERY_COUNT
            ) AS RECOMMENDATION_DETAILS,
            NULL AS ESTIMATED_IMPROVEMENT_PCT,
            QUERY_COUNT AS AFFECTED_QUERY_COUNT,
            DATEADD('day', 30, CURRENT_TIMESTAMP()) AS EXPIRES_AT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_INSIGHTS
        WHERE QUERY_TAG LIKE ?
          AND START_TIME >= ?
          AND START_TIME <= ?
        """
        
        try:
            result = await self._pool.execute_query(
                insert_query,
                params=[
                    job.test_id, job.run_id,
                    query_tag_like,
                    start_time.isoformat(), end_time.isoformat(),
                ],
            )
        except Exception as e:
            # QUERY_INSIGHTS may not be available in all accounts
            logger.warning("QUERY_INSIGHTS enrichment failed (may not be available): %s", e)
            return 0
        
        # Update TEST_RESULTS with insights summary
        await self._update_test_insights_summary(job.test_id, job.run_id)
        
        # v0.2: Parse result for actual row count
        rows_affected = result[0][0] if result and result[0] else 0
        return rows_affected
    
    async def _update_test_insights_summary(self, test_id: str, run_id: str) -> None:
        """Update TEST_RESULTS with summary from QUERY_INSIGHTS_CACHE."""
        prefix = _results_prefix()
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS tr
            SET
                QUERY_INSIGHTS_COUNT = (
                    SELECT COUNT(*)
                    FROM {prefix}.QUERY_INSIGHTS_CACHE
                    WHERE TEST_ID = tr.TEST_ID
                ),
                QUERY_INSIGHTS_HIGH_SEVERITY_COUNT = (
                    SELECT COUNT(*)
                    FROM {prefix}.QUERY_INSIGHTS_CACHE
                    WHERE TEST_ID = tr.TEST_ID
                    AND INSIGHT_SEVERITY = 'HIGH'
                ),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[test_id, run_id],
        )
    
    async def _mark_job_completed(
        self,
        job: EnrichmentJob,
        completed_types: list[str],
        partial: bool = False,
        errors: list[str] | None = None,
    ) -> None:
        """Mark a job as completed."""
        prefix = _results_prefix()
        
        status = "COMPLETED"
        error_msg = None
        if partial and errors:
            # v0.3: Use COMPLETED (not undocumented "PARTIAL") — partial success is still COMPLETED
            # with error context preserved in LAST_ERROR for diagnostics
            status = "COMPLETED"
            error_msg = f"Partial success: {'; '.join(errors)}"
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.DELAYED_ENRICHMENT_QUEUE
            SET STATUS = ?,
                COMPLETED_TYPES = PARSE_JSON(?),
                COMPLETED_AT = CURRENT_TIMESTAMP(),
                LAST_ERROR = ?,
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE JOB_ID = ?
            """,
            params=[
                status,
                json.dumps(completed_types),
                error_msg,
                job.job_id,
            ],
        )
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS
            SET DELAYED_ENRICHMENT_STATUS = ?,
                DELAYED_ENRICHMENT_ERROR = ?,
                DELAYED_ENRICHMENT_COMPLETED_AT = CURRENT_TIMESTAMP(),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[status, error_msg, job.test_id, job.run_id],
        )
        
        logger.info(
            "Delayed enrichment job %s completed for test %s (types=%s, partial=%s)",
            job.job_id, job.test_id, completed_types, partial
        )
    
    async def _mark_job_failed(self, job: EnrichmentJob, error: str) -> None:
        """Mark a job as failed after max retries."""
        prefix = _results_prefix()
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.DELAYED_ENRICHMENT_QUEUE
            SET STATUS = 'FAILED',
                LAST_ERROR = ?,
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE JOB_ID = ?
            """,
            params=[error, job.job_id],
        )
        
        await self._pool.execute_query(
            f"""
            UPDATE {prefix}.TEST_RESULTS
            SET DELAYED_ENRICHMENT_STATUS = 'FAILED',
                DELAYED_ENRICHMENT_ERROR = ?,
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHERE TEST_ID = ? AND RUN_ID = ?
            """,
            params=[error, job.test_id, job.run_id],
        )
        
        logger.error(
            "Delayed enrichment job %s failed for test %s: %s",
            job.job_id, job.test_id, error
        )


# Singleton instance
_processor: DelayedEnrichmentProcessor | None = None


def get_delayed_enrichment_processor() -> DelayedEnrichmentProcessor:
    """Get or create the singleton processor instance."""
    global _processor
    if _processor is None:
        _processor = DelayedEnrichmentProcessor()
    return _processor
```

---

## 3. Integration Points

### 3.1 Orchestrator Integration

Modify `backend/core/orchestrator.py` to create delayed enrichment jobs after immediate enrichment:

```python
# In _run_enrichment() function, after immediate enrichment completes:

async def _run_enrichment(test_id: str) -> None:
    """Run enrichment in background after test completion."""
    # ... existing immediate enrichment code ...
    
    # Create delayed enrichment job AFTER immediate enrichment
    from backend.core.delayed_enrichment import create_delayed_enrichment_job
    
    try:
        job_id = await create_delayed_enrichment_job(
            test_id=test_id,
            run_id=test_id,  # Parent row
            table_type=table_type_str,
            test_end_time=datetime.now(UTC),
        )
        if job_id:
            logger.info(
                "Created delayed enrichment job %s for test %s",
                job_id, test_id
            )
    except Exception as e:
        logger.warning(
            "Failed to create delayed enrichment job for %s: %s",
            test_id, e
        )
    
    # ... rest of existing code ...
```

### 3.2 Main App Integration

Modify `backend/main.py` to start/stop the processor:

```python
# In lifespan context manager:

from backend.core.delayed_enrichment import get_delayed_enrichment_processor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # ... existing startup code ...
    
    # Start delayed enrichment processor
    processor = get_delayed_enrichment_processor()
    await processor.start()
    
    yield
    
    # Shutdown
    # Stop delayed enrichment processor
    await processor.stop()
    
    # ... existing shutdown code ...
```

### 3.3 API Endpoints

Add to `backend/api/routes/test_results.py`:

```python
@router.get("/{test_id}/delayed-enrichment-status")
async def get_delayed_enrichment_status(test_id: str) -> dict[str, Any]:
    """
    Get delayed enrichment status for a test.
    
    Returns status, estimated completion time, and completed enrichment types.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()
    
    # Get job status from queue
    rows = await pool.execute_query(
        f"""
        SELECT
            q.JOB_ID,
            q.STATUS,
            q.EARLIEST_ENRICHMENT_TIME,
            q.ENRICHMENT_TYPES,
            q.COMPLETED_TYPES,
            q.LAST_ERROR,
            q.ATTEMPTS,
            tr.DELAYED_ENRICHMENT_STATUS,
            tr.DELAYED_ENRICHMENT_COMPLETED_AT
        FROM {prefix}.TEST_RESULTS tr
        LEFT JOIN {prefix}.DELAYED_ENRICHMENT_QUEUE q ON tr.TEST_ID = q.TEST_ID
        WHERE tr.TEST_ID = ?
        LIMIT 1
        """,
        params=[test_id],
    )
    
    if not rows:
        raise HTTPException(status_code=404, detail="Test not found")
    
    row = rows[0]
    job_id, queue_status, earliest_time, enrichment_types, completed_types, last_error, attempts, status, completed_at = row
    
    # Calculate time remaining
    minutes_remaining = None
    if earliest_time and queue_status == "PENDING":
        now = datetime.now(UTC)
        if isinstance(earliest_time, str):
            earliest_time = datetime.fromisoformat(earliest_time)
        if earliest_time.tzinfo is None:
            earliest_time = earliest_time.replace(tzinfo=UTC)
        minutes_remaining = max(0, (earliest_time - now).total_seconds() / 60)
    
    return {
        "test_id": test_id,
        "status": status or queue_status or "NOT_APPLICABLE",
        "queue_status": queue_status,
        "earliest_enrichment_time": earliest_time.isoformat() if earliest_time else None,
        "minutes_remaining": minutes_remaining,
        "enrichment_types": enrichment_types,
        "completed_types": completed_types,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "last_error": last_error,
        "attempts": attempts or 0,
    }


@router.post("/{test_id}/retry-delayed-enrichment")
async def retry_delayed_enrichment(test_id: str) -> dict[str, Any]:
    """
    Retry failed delayed enrichment for a test.
    
    Only allowed for tests with delayed_enrichment_status=FAILED.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()
    
    # Check current status
    rows = await pool.execute_query(
        f"""
        SELECT DELAYED_ENRICHMENT_STATUS, TABLE_TYPE, END_TIME
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID = ? AND RUN_ID = ?
        LIMIT 1
        """,
        params=[test_id, test_id],
    )
    
    if not rows:
        raise HTTPException(status_code=404, detail="Test not found")
    
    status, table_type, end_time = rows[0]
    
    if str(status or "").upper() != "FAILED":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry: status is {status}, must be FAILED"
        )
    
    # Create new job
    from backend.core.delayed_enrichment import create_delayed_enrichment_job
    
    job_id = await create_delayed_enrichment_job(
        test_id=test_id,
        run_id=test_id,
        table_type=table_type or "STANDARD",
        test_end_time=end_time or datetime.now(UTC) - timedelta(hours=4),
    )
    
    return {
        "test_id": test_id,
        "job_id": job_id,
        "status": "PENDING",
        "message": "Delayed enrichment retry queued",
    }
```

---

## 4. WebSocket Updates

### 4.1 Streaming Integration

Modify `backend/websocket/streaming.py` to include delayed enrichment status:

```python
# Add to _stream_run_metrics() or equivalent:

async def fetch_delayed_enrichment_status(test_id: str) -> dict[str, Any] | None:
    """Fetch delayed enrichment status for WebSocket streaming."""
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()
    
    rows = await pool.execute_query(
        f"""
        SELECT
            DELAYED_ENRICHMENT_STATUS,
            DELAYED_ENRICHMENT_COMPLETED_AT,
            AGGREGATE_ENRICHMENT_STATUS,
            THROTTLED_QUERY_COUNT,
            HYBRID_CREDITS_USED,
            LOCK_WAIT_COUNT
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID = ?
        LIMIT 1
        """,
        params=[test_id],
    )
    
    if not rows:
        return None
    
    row = rows[0]
    return {
        "delayed_enrichment_status": row[0],
        "delayed_enrichment_completed_at": row[1].isoformat() if row[1] else None,
        "aggregate_enrichment_status": row[2],
        "throttled_query_count": row[3],
        "hybrid_credits_used": row[4],
        "lock_wait_count": row[5],
    }
```

---

## 5. Error Handling

### 5.1 Permission Errors

ACCOUNT_USAGE requires specific roles. Handle gracefully:

```python
async def check_account_usage_access() -> dict[str, bool]:
    """Check which ACCOUNT_USAGE views are accessible."""
    pool = snowflake_pool.get_default_pool()
    access = {}
    
    views = [
        ("QUERY_HISTORY", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1"),
        ("AGGREGATE_QUERY_HISTORY", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.AGGREGATE_QUERY_HISTORY LIMIT 1"),
        ("LOCK_WAIT_HISTORY", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY LIMIT 1"),
        ("HYBRID_TABLE_USAGE_HISTORY", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.HYBRID_TABLE_USAGE_HISTORY LIMIT 1"),
        ("QUERY_INSIGHTS", "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_INSIGHTS LIMIT 1"),
    ]
    
    for view_name, query in views:
        try:
            await pool.execute_query(query)
            access[view_name] = True
        except Exception:
            access[view_name] = False
            logger.warning("No access to ACCOUNT_USAGE.%s", view_name)
    
    return access
```

### 5.2 Idempotency

All enrichment operations use MERGE or INSERT with conflict handling to be idempotent:

```python
# Example: AGGREGATE_QUERY_METRICS uses INSERT with unique METRIC_ID
# If re-run, duplicates are handled by checking existing rows:

async def _enrich_from_aggregate_query_history(...) -> int:
    # Delete existing metrics for this test before re-inserting
    await self._pool.execute_query(
        f"DELETE FROM {prefix}.AGGREGATE_QUERY_METRICS WHERE TEST_ID = ?",
        params=[job.test_id],
    )
    # Then insert fresh data
    # ...
```

---

## 6. Configuration

Add to `backend/config.py`:

```python
# Delayed Enrichment Settings
DELAYED_ENRICHMENT_ENABLED: bool = True
DELAYED_ENRICHMENT_POLL_INTERVAL_SECONDS: int = 300  # 5 minutes
DELAYED_ENRICHMENT_MAX_CONCURRENT_JOBS: int = 3
DELAYED_ENRICHMENT_MAX_RETRIES: int = 3
```

---

**Next:** [03-frontend-design.md](03-frontend-design.md) - UI changes and progressive disclosure
