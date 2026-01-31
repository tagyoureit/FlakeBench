# Worker Implementation Specification

This document provides **complete implementation details** for workers in the
multi-worker architecture. It consolidates and resolves ambiguities from other
docs.

## Overview

A worker is an independent process that:

1. Connects to Snowflake
2. Registers with the control plane
3. Waits for START signal
4. Executes workload queries
5. Emits metrics and heartbeats
6. Responds to control events (STOP, SET_PHASE, SET_WORKER_TARGET)
7. Persists query execution records with ENRICHMENT_STATUS='PENDING'
8. Exits cleanly

**Important**: Workers do NOT run enrichment. Enrichment is handled exclusively
by the orchestrator as a background task after workers complete.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries this worker should maintain
- **Warmup Phase**: Run-level phase to prime Snowflake compute; only the first
  workers experience true warmup. Workers joining after warmup ends start
  immediately in MEASUREMENT phase.

---

## 1. Startup Configuration

### 1.1 Required CLI Arguments

```bash
python scripts/run_worker.py \
  --run-id <uuid>           # Parent run ID (required)
  --worker-id <string>      # Unique worker identifier (required)
  --worker-group-id <int>   # Zero-based group index for sharding (required)
  --worker-group-count <int> # Total worker count for sharding (required)
```

### 1.2 Required Environment Variables

```bash
# Snowflake Connection (standard connector env vars)
SNOWFLAKE_ACCOUNT=<account>
SNOWFLAKE_USER=<user>
SNOWFLAKE_PASSWORD=<password>        # Or use SNOWFLAKE_PRIVATE_KEY_PATH
SNOWFLAKE_WAREHOUSE=<warehouse>
SNOWFLAKE_DATABASE=UNISTORE_BENCHMARK
SNOWFLAKE_SCHEMA=TEST_RESULTS

# Optional overrides
SNOWFLAKE_ROLE=<role>                # Default: user's default role
```

### 1.3 Configuration Resolution

Workers retrieve their workload configuration from `RUN_STATUS.SCENARIO_CONFIG`:

```sql
SELECT SCENARIO_CONFIG
FROM RUN_STATUS
WHERE RUN_ID = :run_id;
```

The `SCENARIO_CONFIG` VARIANT contains all workload parameters. Workers do NOT
receive template IDs directly; all config is resolved by the orchestrator before
workers start.

---

## 2. Worker State Machine

```text
┌─────────────┐
│  STARTING   │ ← Initial state after process launch
└──────┬──────┘
       │ Upsert heartbeat, poll for START
       ▼
┌─────────────┐
│   WAITING   │ ← Polling RUN_STATUS and RUN_CONTROL_EVENTS for START
└──────┬──────┘
       │ RUN_STATUS.STATUS = RUNNING or START event received
       ▼
┌─────────────┐
│   RUNNING   │ ← Executing workload, emitting metrics
└──────┬──────┘
       │ STOP event or RUN_STATUS terminal or connection failure
       ▼
┌─────────────┐
│  DRAINING   │ ← Graceful shutdown, completing in-flight queries
└──────┬──────┘
       │ All in-flight queries complete or drain timeout
       ▼
┌─────────────┐
│  COMPLETED  │ ← Final state, process exits
└─────────────┘
```

### State Definitions

| State | Description | Heartbeat Status |
|-------|-------------|------------------|
| STARTING | Process launched, connecting to Snowflake | `STARTING` |
| WAITING | Connected, polling for START signal | `WAITING` |
| RUNNING | Executing workload queries | `RUNNING` |
| DRAINING | Completing in-flight queries before exit | `DRAINING` |
| COMPLETED | Clean exit | `COMPLETED` |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Clean completion (normal end or STOP received) |
| 1 | Configuration error (invalid args, missing config) |
| 2 | Connection failure (60s no-connection timeout) |
| 3 | Startup timeout (120s waiting for START) |
| 4 | Fatal workload error (unrecoverable) |

---

## 3. Table Schemas (Worker-Relevant)

### 3.1 WORKER_HEARTBEATS (Hybrid Table)

Workers write to this table for control-plane liveness detection.

```sql
CREATE HYBRID TABLE IF NOT EXISTS WORKER_HEARTBEATS (
    RUN_ID VARCHAR(36) NOT NULL,
    WORKER_ID VARCHAR(100) NOT NULL,
    WORKER_GROUP_ID INTEGER NOT NULL,
    
    -- Status tracking
    STATUS VARCHAR(50) NOT NULL,   -- STARTING, WAITING, RUNNING, DRAINING, etc.
    PHASE VARCHAR(50),             -- WARMUP, MEASUREMENT, COOLDOWN
    
    -- Liveness
    LAST_HEARTBEAT TIMESTAMP_NTZ NOT NULL,
    HEARTBEAT_COUNT INTEGER DEFAULT 0,
    
    -- Connection info
    ACTIVE_CONNECTIONS INTEGER DEFAULT 0,
    TARGET_CONNECTIONS INTEGER DEFAULT 0,
    
    -- Error tracking
    LAST_ERROR TEXT,
    ERROR_COUNT INTEGER DEFAULT 0,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Primary key for row-level locking
    PRIMARY KEY (RUN_ID, WORKER_ID)
);
```

### 3.2 WORKER_METRICS_SNAPSHOTS (Standard Table)

Workers write periodic metric snapshots here. The orchestrator aggregates these.

```sql
-- Required columns (verify presence via DESCRIBE TABLE)
CREATE TABLE IF NOT EXISTS WORKER_METRICS_SNAPSHOTS (
    SNAPSHOT_ID VARCHAR(36) NOT NULL,
    
    -- Identity
    RUN_ID VARCHAR(36) NOT NULL,         -- The parent RUN_ID
    TEST_ID VARCHAR(36) NOT NULL,        -- Worker's own TEST_ID (child run)
    WORKER_ID VARCHAR(100) NOT NULL,     -- Unique worker identifier
    WORKER_GROUP_ID INTEGER NOT NULL,
    WORKER_GROUP_COUNT INTEGER NOT NULL,
    
    -- Timing
    TIMESTAMP TIMESTAMP_NTZ NOT NULL,
    ELAPSED_SECONDS FLOAT,               -- Seconds since worker started
    
    -- Phase (for aggregation filtering)
    PHASE VARCHAR(50),                   -- WARMUP, MEASUREMENT, COOLDOWN
    
    -- Counts (cumulative since MEASUREMENT start; 0 during WARMUP)
    TOTAL_QUERIES INTEGER DEFAULT 0,
    READ_COUNT INTEGER DEFAULT 0,
    WRITE_COUNT INTEGER DEFAULT 0,
    ERROR_COUNT INTEGER DEFAULT 0,
    
    -- Throughput (queries per second in the last interval)
    QPS FLOAT DEFAULT 0,
    
    -- Latency (milliseconds, computed over last interval)
    P50_LATENCY_MS FLOAT,
    P95_LATENCY_MS FLOAT,
    P99_LATENCY_MS FLOAT,
    AVG_LATENCY_MS FLOAT,
    MIN_LATENCY_MS FLOAT,
    MAX_LATENCY_MS FLOAT,
    
    -- Connections
    ACTIVE_CONNECTIONS INTEGER DEFAULT 0,   -- Currently executing queries
    TARGET_CONNECTIONS INTEGER DEFAULT 0,   -- Orchestrator-assigned target
    
    -- Resources (optional)
    CPU_PERCENT FLOAT,
    MEMORY_PERCENT FLOAT,
    
    -- Custom metrics (VARIANT for extensibility)
    CUSTOM_METRICS VARIANT,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

**Column Definitions:**
- `TOTAL_QUERIES`: Cumulative count since MEASUREMENT phase start. Reset to 0 when
  transitioning from WARMUP to MEASUREMENT.
- `QPS`: Queries per second computed over the last 1-second interval.
- `ACTIVE_CONNECTIONS`: Number of connections currently executing a query.
- `TARGET_CONNECTIONS`: The orchestrator-assigned target for this worker.

### 3.3 RUN_CONTROL_EVENTS (Hybrid Table) - Read Only

Workers poll this table for control events.

```sql
-- Schema for reference (workers read only)
CREATE HYBRID TABLE IF NOT EXISTS RUN_CONTROL_EVENTS (
    EVENT_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    EVENT_TYPE VARCHAR(50) NOT NULL,    -- START, STOP, SET_PHASE, SET_WORKER_TARGET
    EVENT_DATA VARIANT NOT NULL,        -- Event-specific payload
    
    SEQUENCE_ID INTEGER NOT NULL,       -- Monotonic per RUN_ID
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    PRIMARY KEY (EVENT_ID)
);

-- Index for efficient polling
CREATE INDEX IF NOT EXISTS IDX_CONTROL_EVENTS_POLL 
ON RUN_CONTROL_EVENTS (RUN_ID, SEQUENCE_ID);
```

### 3.4 RUN_STATUS (Hybrid Table) - Read Only

Workers read this for initial state and terminal detection.

```sql
-- Key columns workers need (subset)
-- STATUS: PREPARED, RUNNING, CANCELLING, COMPLETED, FAILED, CANCELLED
-- PHASE: PREPARING, WARMUP, MEASUREMENT, COOLDOWN, PROCESSING

### 3.5 TEST_LOGS (Standard Table)

Workers write application logs here for centralized troubleshooting.

```sql
CREATE TABLE IF NOT EXISTS TEST_LOGS (
    LOG_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36),
    WORKER_ID VARCHAR(100),
    
    LEVEL VARCHAR(20) NOT NULL,       -- INFO, WARNING, ERROR
    MESSAGE TEXT NOT NULL,
    DETAILS VARIANT,                  -- Optional context (stack trace, etc.)
    
    TIMESTAMP TIMESTAMP_NTZ NOT NULL,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

---

## 4. Heartbeat and Snapshot Strategy

### Resolution: Heartbeats vs Snapshots

Workers write to **BOTH** tables with different purposes:

| Table | Purpose | Frequency | Content |
|-------|---------|-----------|---------|
| `WORKER_HEARTBEATS` | Liveness detection | 1s | Status, connections |
| `WORKER_METRICS_SNAPSHOTS` | Aggregation | 1s | Full interval metrics |

**Rationale**: `WORKER_HEARTBEATS` is a Hybrid Table optimized for point updates
(status changes). `WORKER_METRICS_SNAPSHOTS` is a Standard Table for append-only
time-series data that the orchestrator aggregates.

### 4.1 Heartbeat Write (Every 1s)

```sql
MERGE INTO WORKER_HEARTBEATS AS target
USING (SELECT
    :run_id AS RUN_ID,
    :worker_id AS WORKER_ID,
    :worker_group_id AS WORKER_GROUP_ID,
    :status AS STATUS,
    :phase AS PHASE,
    CURRENT_TIMESTAMP() AS LAST_HEARTBEAT,
    :heartbeat_count AS HEARTBEAT_COUNT,
    :active_connections AS ACTIVE_CONNECTIONS,
    :target_connections AS TARGET_CONNECTIONS,
    :last_error AS LAST_ERROR,
    :error_count AS ERROR_COUNT,
    CURRENT_TIMESTAMP() AS UPDATED_AT
) AS source
ON target.RUN_ID = source.RUN_ID AND target.WORKER_ID = source.WORKER_ID
WHEN MATCHED THEN UPDATE SET
    STATUS = source.STATUS,
    PHASE = source.PHASE,
    LAST_HEARTBEAT = source.LAST_HEARTBEAT,
    HEARTBEAT_COUNT = source.HEARTBEAT_COUNT,
    ACTIVE_CONNECTIONS = source.ACTIVE_CONNECTIONS,
    TARGET_CONNECTIONS = source.TARGET_CONNECTIONS,
    LAST_ERROR = source.LAST_ERROR,
    ERROR_COUNT = source.ERROR_COUNT,
    UPDATED_AT = source.UPDATED_AT
WHEN NOT MATCHED THEN INSERT (
    RUN_ID, WORKER_ID, WORKER_GROUP_ID, STATUS, PHASE,
    LAST_HEARTBEAT, HEARTBEAT_COUNT, ACTIVE_CONNECTIONS, TARGET_CONNECTIONS,
    LAST_ERROR, ERROR_COUNT, CREATED_AT, UPDATED_AT
) VALUES (
    source.RUN_ID, source.WORKER_ID, source.WORKER_GROUP_ID, source.STATUS, source.PHASE,
    source.LAST_HEARTBEAT, source.HEARTBEAT_COUNT, source.ACTIVE_CONNECTIONS, source.TARGET_CONNECTIONS,
    source.LAST_ERROR, source.ERROR_COUNT, CURRENT_TIMESTAMP(), source.UPDATED_AT
);
```

### 4.2 Snapshot Write (Every 1s)

```sql
INSERT INTO WORKER_METRICS_SNAPSHOTS (
    SNAPSHOT_ID,
    RUN_ID, TEST_ID, WORKER_ID, WORKER_GROUP_ID, WORKER_GROUP_COUNT,
    TIMESTAMP, ELAPSED_SECONDS, PHASE,
    TOTAL_QUERIES, READ_COUNT, WRITE_COUNT, ERROR_COUNT, QPS,
    P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS,
    AVG_LATENCY_MS, MIN_LATENCY_MS, MAX_LATENCY_MS,
    ACTIVE_CONNECTIONS, TARGET_CONNECTIONS,
    CPU_PERCENT, MEMORY_PERCENT,
    CUSTOM_METRICS
) VALUES (
    :snapshot_id,
    :run_id, :test_id, :worker_id, :worker_group_id, :worker_group_count,
    CURRENT_TIMESTAMP(), :elapsed_seconds, :phase,
    :total_queries, :read_count, :write_count, :error_count, :qps,
    :p50_latency_ms, :p95_latency_ms, :p99_latency_ms,
    :avg_latency_ms, :min_latency_ms, :max_latency_ms,
    :active_connections, :target_connections,
    :cpu_percent, :memory_percent,
    PARSE_JSON(:custom_metrics_json)
);
```

---

## 5. Control Event Polling

### 5.1 Initial State

On startup, workers initialize:

```python
last_seen_sequence = 0  # Start from beginning; events are monotonic per RUN_ID
```

### 5.2 Event Poll Query (Every 1s)

Poll for ALL event types in one query. **Loop until caught up** to handle
backlogs:

```sql
SELECT
    EVENT_ID,
    EVENT_TYPE,
    EVENT_DATA,
    SEQUENCE_ID,
    CREATED_AT
FROM RUN_CONTROL_EVENTS
WHERE RUN_ID = :run_id
  AND SEQUENCE_ID > :last_seen_sequence
ORDER BY SEQUENCE_ID ASC
LIMIT 100;  -- Process up to 100 events per batch
```

```python
async def poll_and_process_all_events() -> None:
    """Poll events until fully caught up."""
    while True:
        events = await poll_control_events(last_seen_sequence, limit=100)
        if not events:
            break  # Fully caught up
        
        for event in events:
            await process_event(event)
            last_seen_sequence = event['SEQUENCE_ID']
        
        if len(events) < 100:
            break  # No more events
```

### 5.3 Event Processing Logic

```python
def process_events(events: list[dict]) -> None:
    """Process events in sequence order."""
    for event in events:
        seq = event['SEQUENCE_ID']
        if seq <= last_seen_sequence:
            continue  # Already processed
        
        event_type = event['EVENT_TYPE']
        event_data = event['EVENT_DATA']
        
        # Check scope
        scope = event_data.get('scope', 'RUN')
        if not event_applies_to_me(scope, event_data):
            last_seen_sequence = seq
            continue
        
        # Process by type
        if event_type == 'START':
            handle_start(event_data)
        elif event_type == 'STOP':
            handle_stop(event_data)
        elif event_type == 'SET_PHASE':
            handle_set_phase(event_data)
        elif event_type == 'SET_WORKER_TARGET':
            handle_set_worker_target(event_data)
        
        last_seen_sequence = seq


def event_applies_to_me(scope: str, event_data: dict) -> bool:
    """Check if event applies to this worker."""
    if scope == 'RUN':
        return True
    elif scope == 'WORKER_GROUP':
        return event_data.get('worker_group_id') == my_worker_group_id
    elif scope == 'WORKER':
        return event_data.get('worker_id') == my_worker_id
    return False
```

### 5.4 START Gate Logic

**IMPORTANT**: The `wait_for_start()` function must only update `last_seen_sequence` for
START events. Other events (SET_PHASE, SET_WORKER_TARGET) must remain visible to the main
event loop for processing after startup completes.

```python
async def wait_for_start(timeout_seconds: int = 120) -> bool:
    """
    Wait for START signal. Returns True if started, False if timeout.
    
    Logic:
    1. Load SCENARIO_CONFIG first (needed for workload setup)
    2. Check RUN_STATUS - if already RUNNING, start immediately
    3. Otherwise poll for START event
    
    CRITICAL: Only update last_seen_sequence for START events, not other event types.
    This ensures SET_PHASE events are not skipped by the main event loop.
    """
    start_time = time.time()
    
    # Load configuration first (always needed)
    scenario_config = await load_scenario_config()
    initial_target = compute_initial_target(scenario_config)
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            return False  # Timeout - exit with code 3
        
        # Check 1: Is run already RUNNING?
        run_state = await query_run_status()
        if run_state['status'] == 'RUNNING':
            log.info("RUN_STATUS is RUNNING, starting immediately")
            return True
        
        # Check 2: Is run terminal? (shouldn't happen, but handle it)
        if run_state['status'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
            log.warning(f"Run is already terminal: {run_state['status']}")
            return False
        
        # Check 3: Poll for START event
        # NOTE: Only update last_seen_sequence for START events
        events = await poll_control_events()
        for event in events:
            seq = event['SEQUENCE_ID']
            if seq <= last_seen_sequence:
                continue
            if event['EVENT_TYPE'] == 'START':
                last_seen_sequence = seq  # Only update for START
                log.info("Received START event")
                return True
            # Other events (SET_PHASE, etc.) will be processed by main loop
        
        await asyncio.sleep(1.0)


def compute_initial_target(scenario_config: dict) -> int:
    """
    Compute initial TARGET_CONNECTIONS for this worker.
    
    Resolution order:
    1. If SCENARIO_CONFIG.scaling.per_worker_connections is set, use it
    2. Otherwise: total_connections / worker_group_count
    """
    scaling = scenario_config.get('scaling', {})
    
    # Explicit per-worker setting takes precedence
    if 'per_worker_connections' in scaling:
        return scaling['per_worker_connections']
    
    # Fall back to even distribution
    total = scenario_config['workload']['concurrent_connections']
    worker_count = scaling.get('worker_group_count', 1)
    
    # Even distribution with remainder to lower group IDs
    base = total // worker_count
    remainder = total % worker_count
    
    if my_worker_group_id < remainder:
        return base + 1
    return base
```

### 5.5 RUN_STATUS Fallback for Phase and Target

If a worker misses a `SET_PHASE` or `SET_WORKER_TARGET` event (e.g., network
blip), it should periodically check `RUN_STATUS` as a fallback:

```python
async def reconcile_state() -> None:
    """
    Reconcile local state with authoritative RUN_STATUS.
    Called every 5 seconds as a fallback.
    """
    result = await query_scalar("""
        SELECT PHASE, WORKER_TARGETS
        FROM RUN_STATUS
        WHERE RUN_ID = :run_id
    """, run_id=my_run_id)
    
    # Reconcile phase
    authoritative_phase = result['PHASE']
    if authoritative_phase != my_current_phase:
        log.warning(
            f"Phase mismatch: local={my_current_phase}, "
            f"authoritative={authoritative_phase}. Reconciling."
        )
        transition_to_phase(authoritative_phase)
    
    # Reconcile target connections
    worker_targets = result.get('WORKER_TARGETS', {})
    if my_worker_id in worker_targets:
        authoritative_target = worker_targets[my_worker_id]['target_connections']
        if authoritative_target != my_target_connections:
            log.warning(
                f"Target mismatch: local={my_target_connections}, "
                f"authoritative={authoritative_target}. Reconciling."
            )
            apply_target(authoritative_target)
```

**Reconciliation frequency**: Every 5 seconds (not every tick, to reduce load).

**Note**: `RUN_STATUS.WORKER_TARGETS` is a VARIANT column that stores the current
target for each worker. The orchestrator updates this column whenever it emits
`SET_WORKER_TARGET` events, providing a fallback for missed events.

---

## 6. Phase Transitions

### 6.1 Phase Definitions

| Phase | Description | Metrics Counted? |
|-------|-------------|------------------|
| WARMUP | Run-level phase to prime Snowflake compute | No |
| MEASUREMENT | Main test period | Yes |
| COOLDOWN | Draining before finalization | No |

**Important**: Warmup is a **run-level** concept, not per-worker. The orchestrator
controls when warmup ends for the entire run. Workers that start after warmup has
ended (e.g., during QPS scale-out) begin directly in MEASUREMENT phase.

### 6.2 Initial Phase on Worker Start

When a worker receives START or sees `RUN_STATUS.STATUS=RUNNING`:

```python
def determine_initial_phase() -> str:
    """Determine initial phase based on run state."""
    run_phase = query_run_status_phase()
    
    if run_phase == 'WARMUP':
        # Run is still warming up; participate in warmup
        return 'WARMUP'
    elif run_phase == 'MEASUREMENT':
        # Run has already transitioned; skip warmup
        log.info("Run already in MEASUREMENT, skipping worker warmup")
        return 'MEASUREMENT'
    else:
        # PREPARING, COOLDOWN, PROCESSING - shouldn't happen at worker start
        log.warning(f"Unexpected run phase at worker start: {run_phase}")
        return run_phase
```

### 6.3 Metrics Reset on MEASUREMENT Start

When transitioning to MEASUREMENT phase, reset **measurement counters**:

```python
def transition_to_measurement() -> None:
    """Reset metrics for measurement period."""
    # Reset measurement counters (start fresh for measurement)
    measurement_start_time = time.time()
    measurement_total_queries = 0
    measurement_read_count = 0
    measurement_write_count = 0
    measurement_error_count = 0
    
    # Reset latency tracking (start fresh percentiles)
    latency_histogram.reset()
    
    my_current_phase = 'MEASUREMENT'
    log.info("Transitioned to MEASUREMENT phase, metrics reset")
```

### 6.3 SET_PHASE Event Handler

```python
def handle_set_phase(event_data: dict) -> None:
    """Handle SET_PHASE control event."""
    new_phase = event_data['phase']
    effective_at = event_data.get('effective_at')  # Optional
    
    if effective_at:
        # Future transition (rare, but supported)
        schedule_phase_transition(new_phase, effective_at)
    else:
        # Immediate transition
        if new_phase == 'MEASUREMENT' and my_current_phase == 'WARMUP':
            transition_to_measurement()
        elif new_phase == 'COOLDOWN' and my_current_phase == 'MEASUREMENT':
            transition_to_cooldown()
        else:
            my_current_phase = new_phase
```

---

## 7. Concurrency Target Changes

### 7.1 SET_WORKER_TARGET Event Handler

```python
def handle_set_worker_target(event_data: dict) -> None:
    """Handle SET_WORKER_TARGET control event."""
    new_target = event_data['target_connections']
    ramp_seconds = event_data.get('ramp_seconds', 0)
    step_id = event_data.get('step_id')  # For logging/debugging
    reason = event_data.get('reason', 'orchestrator_request')
    
    log.info(
        f"Target change: {my_target_connections} -> {new_target} "
        f"(ramp={ramp_seconds}s, reason={reason})"
    )
    
    if ramp_seconds > 0:
        start_ramp(new_target, ramp_seconds)
    else:
        apply_target_immediately(new_target)
```

### 7.2 Ramp Logic

Linear ramp over `ramp_seconds`:

```python
class ConnectionRamp:
    """Manages gradual connection count changes."""
    
    def __init__(self):
        self.ramp_start_time = None
        self.ramp_start_value = None
        self.ramp_end_value = None
        self.ramp_duration = None
    
    def start_ramp(self, target: int, duration_seconds: float) -> None:
        self.ramp_start_time = time.time()
        self.ramp_start_value = current_connections
        self.ramp_end_value = target
        self.ramp_duration = duration_seconds
    
    def get_current_target(self) -> int:
        """Get interpolated target for current time."""
        if self.ramp_start_time is None:
            return my_target_connections
        
        elapsed = time.time() - self.ramp_start_time
        if elapsed >= self.ramp_duration:
            # Ramp complete
            self.ramp_start_time = None
            return self.ramp_end_value
        
        # Linear interpolation
        progress = elapsed / self.ramp_duration
        delta = self.ramp_end_value - self.ramp_start_value
        return int(self.ramp_start_value + (delta * progress))
```

### 7.3 Applying Target Changes

```python
def apply_target(new_target: int) -> None:
    """Apply connection target change."""
    current = len(active_connections)
    
    if new_target > current:
        # Scale up: add connections
        to_add = new_target - current
        for _ in range(to_add):
            add_connection()
    
    elif new_target < current:
        # Scale down: mark connections for graceful close
        to_remove = current - new_target
        mark_connections_for_close(to_remove)
        # Connections close after their current query completes
    
    my_target_connections = new_target
```

### 7.4 min_connections Enforcement

The **orchestrator** enforces `min_connections`. Workers apply whatever target
they receive. If the orchestrator sends `target_connections: 5` and
`min_connections` is 10, that's an orchestrator bug.

Workers should log a warning but still apply the target:

```python
if new_target < MIN_REASONABLE_CONNECTIONS:  # e.g., 1
    log.warning(f"Received very low target: {new_target}")
```

---

## 8. Stop Handling

### 8.1 STOP Event Handler

```python
def handle_stop(event_data: dict) -> None:
    """Handle STOP control event."""
    reason = event_data.get('reason', 'orchestrator_request')
    drain_timeout = event_data.get('drain_timeout_seconds', 120)
    
    log.info(f"STOP received: reason={reason}, drain_timeout={drain_timeout}s")
    
    # Transition to DRAINING state
    my_state = 'DRAINING'
    stop_accepting_new_work()
    
    # Start drain timer
    asyncio.create_task(drain_with_timeout(drain_timeout))
```

### 8.2 Graceful Drain Sequence

```python
async def drain_with_timeout(timeout_seconds: int) -> None:
    """
    Drain in-flight queries with timeout.
    
    Steps:
    1. Stop starting new queries and cancel metrics collection immediately
    2. Wait for in-flight queries to complete
    3. Persist query execution records to QUERY_EXECUTIONS table
    4. Exit cleanly (or force exit on timeout)
    
    IMPORTANT: Metrics are stopped immediately when queries finish, not in
    finally block. Worker does NOT set ENRICHMENT_STATUS - the orchestrator
    owns that lifecycle and sets it in _mark_run_completed().
    """
    drain_start = time.time()
    
    # Cancel metrics collection immediately after stopping queries
    metrics_collector.cancel()
    
    while True:
        elapsed = time.time() - drain_start
        
        # Check if all queries complete
        if in_flight_query_count == 0:
            log.info("All queries drained, persisting records")
            
            # Persist query execution records to QUERY_EXECUTIONS table
            await persist_query_executions()
            
            log.info("Records persisted, exiting cleanly")
            await final_heartbeat('COMPLETED')
            sys.exit(0)
        
        # Check timeout
        if elapsed > timeout_seconds:
            log.warning(
                f"Drain timeout after {timeout_seconds}s, "
                f"{in_flight_query_count} queries still in-flight"
            )
            await persist_query_executions()
            await final_heartbeat('COMPLETED')  # Still mark as completed
            sys.exit(0)
        
        # Continue waiting
        await asyncio.sleep(0.5)


def stop_accepting_new_work() -> None:
    """Stop starting new queries."""
    global accepting_new_work
    accepting_new_work = False
    
    # Close idle connections (ones not currently executing a query)
    close_idle_connections()
```

### 8.3 "In-Flight" Tracking

```python
in_flight_queries: set[str] = set()  # Query IDs currently executing

async def execute_query(query: str) -> QueryResult:
    """Execute a single query with in-flight tracking."""
    query_id = str(uuid.uuid4())
    
    if not accepting_new_work:
        raise WorkerDrainingError("Worker is draining, not accepting new work")
    
    in_flight_queries.add(query_id)
    try:
        result = await connection.execute(query)
        return result
    finally:
        in_flight_queries.discard(query_id)

@property
def in_flight_query_count() -> int:
    return len(in_flight_queries)
```

---

## 9. Connection Failure and Self-Termination

### 9.1 Timing Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `HEARTBEAT_INTERVAL` | 1 second | Time between heartbeat writes |
| `STALENESS_THRESHOLD` | 30 seconds | Orchestrator marks worker STALE |
| `DEAD_THRESHOLD` | 60 seconds | Orchestrator marks worker DEAD |
| `NO_CONNECTION_TIMEOUT` | 60 seconds | Worker self-terminates |
| `START_TIMEOUT` | 120 seconds | Max wait for START signal |
| `DRAIN_TIMEOUT` | 120 seconds | Max time for graceful drain |

### 9.2 Backoff Parameters

```python
class ExponentialBackoff:
    """Exponential backoff for transient failures."""
    
    INITIAL_BACKOFF = 1.0      # 1 second
    MAX_BACKOFF = 30.0         # 30 seconds
    MULTIPLIER = 2.0           # Double each retry
    MAX_RETRIES = 10           # Then give up on this operation
    
    def __init__(self):
        self.current_backoff = self.INITIAL_BACKOFF
        self.retry_count = 0
    
    def next_backoff(self) -> float:
        """Get next backoff duration, or raise if max retries exceeded."""
        if self.retry_count >= self.MAX_RETRIES:
            raise MaxRetriesExceeded()
        
        backoff = self.current_backoff
        self.current_backoff = min(
            self.current_backoff * self.MULTIPLIER,
            self.MAX_BACKOFF
        )
        self.retry_count += 1
        return backoff
    
    def reset(self) -> None:
        """Reset after successful operation."""
        self.current_backoff = self.INITIAL_BACKOFF
        self.retry_count = 0
```

### 9.3 Connection Health Tracking

```python
class ConnectionHealthTracker:
    """Track connection health for self-termination."""
    
    def __init__(self, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds
        self.last_successful_operation = time.time()
    
    def record_success(self) -> None:
        """Record a successful Snowflake operation."""
        self.last_successful_operation = time.time()
    
    def check_health(self) -> bool:
        """
        Check if we should self-terminate.
        Returns False if we've exceeded the no-connection timeout.
        """
        elapsed = time.time() - self.last_successful_operation
        if elapsed > self.timeout_seconds:
            log.error(
                f"No successful Snowflake operation for {elapsed:.1f}s "
                f"(threshold: {self.timeout_seconds}s). Self-terminating."
            )
            return False
        return True
```

### 9.4 "No Connection" Definition

The 60-second timeout applies to **any successful Snowflake operation**:
- Heartbeat write
- Snapshot write
- Control event poll
- Query execution
- RUN_STATUS read

If **all** operations fail for 60 seconds, the worker self-terminates.

---

## 10. Main Loop Pseudocode

```python
async def worker_main():
    """Main worker entry point."""
    # Parse configuration
    args = parse_args()
    config = WorkerConfig(
        run_id=args.run_id,
        worker_id=args.worker_id,
        worker_group_id=args.worker_group_id,
        worker_group_count=args.worker_group_count,
    )
    
    # Initialize state
    state = WorkerState.STARTING
    last_seen_sequence = 0
    health_tracker = ConnectionHealthTracker(timeout_seconds=60)
    
    try:
        # Connect to Snowflake
        await connect_to_snowflake()
        
        # Initial heartbeat
        await write_heartbeat(status='STARTING')
        health_tracker.record_success()
        
        # Load scenario config from RUN_STATUS
        scenario_config = await load_scenario_config(config.run_id)
        
        # Transition to WAITING
        state = WorkerState.WAITING
        await write_heartbeat(status='WAITING')
        
        # Wait for START
        if not await wait_for_start(timeout_seconds=120):
            log.error("Timeout waiting for START")
            sys.exit(3)
        
        # Transition to RUNNING
        state = WorkerState.RUNNING
        current_phase = 'WARMUP'
        
        # Initialize workload executor
        executor = WorkloadExecutor(scenario_config)
        await executor.initialize()
        
        # Main loop
        last_heartbeat = time.time()
        last_reconcile = time.time()
        
        while state == WorkerState.RUNNING:
            now = time.time()
            
            # Check connection health
            if not health_tracker.check_health():
                sys.exit(2)
            
            # Heartbeat + snapshot (every 1s)
            # Note: Metrics collection runs until STOP event received, then
            # immediately cancelled - no publishing in finally block
            if now - last_heartbeat >= 1.0:
                try:
                    await write_heartbeat(status='RUNNING', phase=current_phase)
                    await write_snapshot(executor.get_metrics(), phase=current_phase)
                    health_tracker.record_success()
                except SnowflakeError as e:
                    log.warning(f"Heartbeat/snapshot failed: {e}")
                last_heartbeat = now
            
            # Poll control events (every 1s)
            try:
                events = await poll_control_events(last_seen_sequence)
                for event in events:
                    last_seen_sequence = max(last_seen_sequence, event['SEQUENCE_ID'])
                    await process_event(event)
                health_tracker.record_success()
            except SnowflakeError as e:
                log.warning(f"Event poll failed: {e}")
            
            # Phase reconciliation (every 5s)
            if now - last_reconcile >= 5.0:
                await reconcile_phase()
                last_reconcile = now
            
            # Check for terminal RUN_STATUS
            run_status = await check_run_status()
            if run_status in ('COMPLETED', 'FAILED', 'CANCELLED'):
                log.info(f"Run is terminal: {run_status}")
                break
            
            # Execute workload (non-blocking)
            await executor.tick()
            
            # Small sleep to prevent tight loop
            await asyncio.sleep(0.01)
        
        # Drain and exit
        state = WorkerState.DRAINING
        await drain_with_timeout(120)
        
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        await write_heartbeat(status='DEAD', last_error=str(e))
        sys.exit(4)
    
    finally:
        await write_heartbeat(status='COMPLETED')
        await close_connections()
    
    sys.exit(0)
```

---

## 11. Error Reporting and Logging

### 11.1 Heartbeat Error Field

Workers report the last error in `WORKER_HEARTBEATS.LAST_ERROR` for immediate
control-plane visibility:

```python
async def write_heartbeat(
    status: str,
    phase: str = None,
    last_error: str = None
) -> None:
    """Write heartbeat with optional error."""
    # Truncate error to prevent oversized writes
    if last_error and len(last_error) > 1000:
        last_error = last_error[:1000] + "...(truncated)"
    
    await execute_merge(...)
```

### 11.2 Centralized Logging (TEST_LOGS)

For debugging history, workers write logs to `TEST_LOGS`.

**Buffer Strategy:**
- **INFO**: Buffer and flush every 5 seconds (or with metrics snapshot).
- **WARNING/ERROR**: Flush immediately.

```python
async def log_to_snowflake(level: str, message: str, details: dict = None) -> None:
    """Write log entry to TEST_LOGS."""
    await execute("""
        INSERT INTO TEST_LOGS (
            LOG_ID, RUN_ID, TEST_ID, WORKER_ID, LEVEL, MESSAGE, DETAILS, TIMESTAMP
        ) VALUES (
            :log_id, :run_id, :test_id, :worker_id, :level, :message, 
            PARSE_JSON(:details), CURRENT_TIMESTAMP()
        )
    """, 
    log_id=str(uuid.uuid4()),
    run_id=my_run_id,
    test_id=my_test_id,
    worker_id=my_worker_id,
    level=level,
    message=message,
    details=json.dumps(details) if details else None
    )
```

### 11.3 Error Categories

Workers should categorize errors for debugging:

| Category | Example | Handling |
|----------|---------|----------|
| `CONNECTION` | Socket timeout | Retry with backoff |
| `QUERY_TIMEOUT` | Query exceeded timeout | Log and continue |
| `SNOWFLAKE_ERROR` | Snowflake error code | Log and continue |
| `CONFIGURATION` | Invalid config | Fatal, exit |
| `FATAL` | OOM, unrecoverable | Exit |

---

## 12. Sharding and Data Generation

### 12.1 When Sharding Applies

Sharding is used when:
1. The workload involves data generation (e.g., inserts)
2. The template specifies partitioned data access

Sharding is **not** used when:
1. All workers access the same data (e.g., point lookups on existing data)
2. The template doesn't specify partitioning

### 12.2 Shard Calculation

```python
def get_my_shard(total_partitions: int) -> int:
    """
    Get this worker's shard for partitioned data access.
    
    Args:
        total_partitions: Total partitions in the target table
    
    Returns:
        Shard index this worker is responsible for
    """
    return my_worker_group_id % total_partitions


def get_my_key_range(total_keys: int) -> tuple[int, int]:
    """
    Get this worker's key range for data generation.
    
    Returns:
        (start_key, end_key) exclusive range
    """
    keys_per_worker = total_keys // my_worker_group_count
    start_key = my_worker_group_id * keys_per_worker
    end_key = start_key + keys_per_worker
    
    # Last worker gets remainder
    if my_worker_group_id == my_worker_group_count - 1:
        end_key = total_keys
    
    return (start_key, end_key)
```

### 12.3 Configuration Source

Sharding parameters come from `SCENARIO_CONFIG`:

```json
{
  "sharding": {
    "enabled": true,
    "total_partitions": 100,
    "key_column": "CUSTOMER_ID",
    "key_range": [1, 1000000]
  }
}
```

If `sharding.enabled` is false or missing, workers operate on the full dataset
without partitioning.

---

## 13. Connection Pool Configuration

### 13.1 Pool Sizing

Workers maintain two connection pools:

| Pool | Purpose | Recommended Size |
|------|---------|------------------|
| Control | Heartbeats, events, status | 2-3 connections |
| Workload | Query execution | `target_connections` |

### 13.2 Control Pool Configuration

```python
CONTROL_POOL_CONFIG = {
    'min_connections': 2,
    'max_connections': 3,
    'connection_timeout': 30,
    'idle_timeout': 300,
    'validation_interval': 60,
}
```

### 13.3 Workload Pool Configuration

```python
def get_workload_pool_config(target_connections: int) -> dict:
    return {
        'min_connections': 1,
        'max_connections': target_connections,
        'connection_timeout': 30,
        'idle_timeout': 300,
        'validation_interval': 60,
    }
```

---

---

## 14. Child TEST_RESULTS Row

Each worker creates a child `TEST_RESULTS` row to store its final metrics.

### 14.1 When to Create

Create the child row **after** receiving START but **before** beginning load
generation:

```python
async def create_child_test_row() -> str:
    """
    Create child TEST_RESULTS row for this worker.
    Returns the child TEST_ID.
    """
    child_test_id = str(uuid.uuid4())
    
    await execute("""
        INSERT INTO TEST_RESULTS (
            TEST_ID,
            RUN_ID,
            WORKER_ID,
            WORKER_GROUP_ID,
            TEMPLATE_ID,
            STATUS,
            CREATED_AT
        ) VALUES (
            :test_id,
            :run_id,
            :worker_id,
            :worker_group_id,
            :template_id,
            'RUNNING',
            CURRENT_TIMESTAMP()
        )
    """, test_id=child_test_id, run_id=my_run_id, ...)
    
    return child_test_id
```

### 14.2 Final Update

On clean exit, update the child row with final metrics:

```python
async def finalize_child_test_row() -> None:
    """Update child TEST_RESULTS with final metrics."""
    await execute("""
        UPDATE TEST_RESULTS SET
            STATUS = 'COMPLETED',
            END_TIME = CURRENT_TIMESTAMP(),
            TOTAL_OPERATIONS = :total_ops,
            READ_OPERATIONS = :reads,
            WRITE_OPERATIONS = :writes,
            FAILED_OPERATIONS = :errors,
            P50_LATENCY_MS = :p50,
            P95_LATENCY_MS = :p95,
            P99_LATENCY_MS = :p99,
            AVG_LATENCY_MS = :avg
        WHERE TEST_ID = :test_id
    """, ...)
```

---

## 15. Error Handling During Drain

Queries that error during DRAINING are:
- Counted toward `ERROR_COUNT` in the final snapshot
- Included in final aggregates
- Logged with the error message

The drain completes when in-flight count reaches 0, regardless of success/failure.

---

## Reiterated Constraints

- Workers do NOT execute DDL at runtime.
- Workers write to Standard Tables (`WORKER_METRICS_SNAPSHOTS`, `QUERY_EXECUTIONS`)
  and Hybrid Tables (`WORKER_HEARTBEATS`).
- Workers read from Hybrid Tables (`RUN_CONTROL_EVENTS`, `RUN_STATUS`).
- All workload configuration comes from `RUN_STATUS.SCENARIO_CONFIG`.
- Workers never decide phase transitions or step changes; they only apply
  orchestrator commands.
- Warmup is a run-level concept; workers joining after warmup start in MEASUREMENT.
