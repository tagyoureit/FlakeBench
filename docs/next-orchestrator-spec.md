# OrchestratorService Specification

## Overview

The `OrchestratorService` replaces the in-memory `TestRegistry` as the
central control plane for benchmark runs. It is responsible for:

1. **State Management**: Persisting run lifecycle to Snowflake (`RUN_STATUS`).
2. **Worker Coordination**: Issuing commands via `RUN_CONTROL_EVENTS`.
3. **Aggregation**: Computing global metrics from worker snapshots in `WORKER_METRICS_SNAPSHOTS`.
4. **Liveness**: Monitoring `WORKER_HEARTBEATS` to detect failures.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **SEQUENCE_ID**: Monotonic counter for event ordering within a run

## Interface

```python
class OrchestratorService:
    async def create_run(self, template_id: str, config: RunConfig) -> str:
        """
        Creates a new parent run in PREPARED state.
        Writes to RUN_STATUS.
        Returns run_id.
        """

    async def start_run(self, run_id: str) -> None:
        """
        Transitions run to RUNNING.
        Spawns worker processes (local) or services (SPCS).
        """

    async def stop_run(self, run_id: str) -> None:
        """
        Writes STOP event to RUN_CONTROL_EVENTS.
        Updates RUN_STATUS to CANCELLING.
        """

    async def get_run_status(self, run_id: str) -> RunStatus:
        """
        Reads authoritative state from RUN_STATUS.
        """
```

## Architecture

### 1. State Persistence (Snowflake Hybrid Tables)

All state is authoritative in Snowflake. The Orchestrator is stateless between
ticks.

- **`RUN_STATUS`**: The "single source of truth" for the UI.
- **`RUN_CONTROL_EVENTS`**: The command bus.
- **`WORKER_HEARTBEATS`**: Worker liveness and status for control-plane decisions.

### 1a. Control Event Ordering and Scoping

- `RUN_CONTROL_EVENTS.SEQUENCE_ID` is monotonic per `RUN_ID`.
- Workers track the last seen sequence and process events in order.
- `EVENT_DATA.scope` is `RUN`, `WORKER_GROUP`, or `WORKER`.
- Per-worker target updates use `scope=WORKER` and include explicit targets.

### 1b. SEQUENCE_ID Generation

The orchestrator generates SEQUENCE_IDs atomically using `RUN_STATUS.NEXT_SEQUENCE_ID`:

```python
async def emit_control_event(
    run_id: str,
    event_type: str,
    event_data: dict
) -> int:
    """
    Emit a control event with atomic sequence assignment.
    Returns the assigned SEQUENCE_ID.
    """
    # Atomic increment and fetch
    result = await execute("""
        UPDATE RUN_STATUS
        SET NEXT_SEQUENCE_ID = NEXT_SEQUENCE_ID + 1,
            UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE RUN_ID = :run_id
        RETURNING NEXT_SEQUENCE_ID - 1 AS SEQUENCE_ID
    """, run_id=run_id)
    
    sequence_id = result['SEQUENCE_ID']
    
    # Insert the event
    await execute("""
        INSERT INTO RUN_CONTROL_EVENTS (
            EVENT_ID, RUN_ID, EVENT_TYPE, EVENT_DATA, SEQUENCE_ID, CREATED_AT
        ) VALUES (
            :event_id, :run_id, :event_type, PARSE_JSON(:event_data),
            :sequence_id, CURRENT_TIMESTAMP()
        )
    """, event_id=str(uuid.uuid4()), run_id=run_id,
       event_type=event_type, event_data=json.dumps(event_data),
       sequence_id=sequence_id)
    
    return sequence_id
```

**Key properties:**
- `RUN_STATUS.NEXT_SEQUENCE_ID` starts at 1 on run creation
- Atomic UPDATE + RETURNING ensures no duplicate SEQUENCE_IDs
- Events can be processed in strict order by workers

### 2. Worker Identity & Registration ("Pull" Model)

Workers are ignorant of the Orchestrator's location. They know only the
Snowflake coordinates.

1. **Spawn**: Orchestrator launches worker with CLI args
   (`--run-id`, `--worker-id`, `--worker-group-id`, `--worker-group-count`).
2. **Register**: Worker starts up and performs an `UPSERT` to
   `WORKER_HEARTBEATS` with status `STARTING`.
3. **Poll**: Worker checks `RUN_STATUS.STATUS`; if `RUNNING`, starts immediately.
   Otherwise polls `RUN_CONTROL_EVENTS` for `START` signal.

### 2.1 WorkerSpawner Abstraction (Local + SPCS)

To keep orchestration logic stable across environments, `OrchestratorService`
delegates process/service launch to a `WorkerSpawner` interface.

```python
class WorkerSpawner:
    async def spawn_worker(
        self,
        *,
        run_id: str,
        worker_id: str,
        worker_group_id: int,
        worker_group_count: int
    ) -> None: ...
```

**Local implementation**:

- Prefer `uv run python` when `uv` is available.
- Fallback to `python` when `uv` is not installed.
- Both paths invoke `scripts/run_worker.py` with the same CLI args.

**SPCS implementation**:

- Uses Snowflake service execution (`SYSTEM$EXECUTE_SERVICE`) with the same
  run/worker identifiers passed via env vars or args.

### 2a. Start Sequence (Orchestrator)

The orchestrator follows this exact sequence in `start_run()`:

```python
async def start_run(self, run_id: str) -> None:
    """
    Start a prepared run.
    
    Sequence:
    1. Spawn workers (they will wait for START or RUNNING status)
    2. Wait for workers to register (fail-fast if incomplete)
    3. Update RUN_STATUS to RUNNING
    4. Emit START event (for observability; workers may already see RUNNING)
    5. Start poll loop
    """
    config = await self.get_run_config(run_id)
    expected_workers = config['scaling']['worker_group_count']
    
    # 1. Spawn workers
    for i in range(expected_workers):
        await self.spawner.spawn_worker(
            run_id=run_id,
            worker_id=f"worker-{i}",
            worker_group_id=i,
            worker_group_count=expected_workers
        )
    
    # 2. Wait for registration (fail-fast)
    if not await self._wait_for_registration(run_id, expected_workers, timeout=60):
        await self._fail_run(run_id, "Worker registration timeout")
        return
    
    # 3. Update status to RUNNING (workers may start immediately)
    await self._update_run_status(run_id, status='RUNNING', phase='WARMUP')
    
    # 4. Emit START event (for audit trail)
    await self.emit_control_event(run_id, 'START', {
        'scope': 'RUN',
        'expected_workers': expected_workers
    })
    
    # 5. Start poll loop
    self._start_poll_loop(run_id)
```

### 2b. Worker Registration Validation

```python
async def _wait_for_registration(
    self,
    run_id: str,
    expected: int,
    timeout: int = 60
) -> bool:
    """
    Wait for all expected workers to register.
    Returns False if timeout (fail-fast).
    """
    start = time.time()
    while time.time() - start < timeout:
        count = await self._count_registered_workers(run_id)
        if count >= expected:
            return True
        await asyncio.sleep(1.0)
    
    # Log which workers are missing
    registered = await self._get_registered_worker_ids(run_id)
    expected_ids = {f"worker-{i}" for i in range(expected)}
    missing = expected_ids - set(registered)
    log.error(f"Registration timeout. Missing workers: {missing}")
    
    return False
```

### 3. The Orchestration Loop

The Orchestrator runs a background task (e.g., every 1s):

1. **Check Heartbeats**: Scan `WORKER_HEARTBEATS` for the current run. If
   `last_heartbeat < NOW - 30s`, mark worker as `STALE`. If > 60s, mark as `DEAD`.
2. **Fail-Fast Check**: If **any** worker is marked `DEAD`, immediately issue `STOP`
   with `reason="worker_failure"` and transition `RUN_STATUS` to `FAILED`.
   (Policy: 1+ dead workers = failed run).
3. **Aggregate Metrics**: Query `WORKER_METRICS_SNAPSHOTS` (latest per worker)
   to sum `total_ops`, `error_count`, `qps`, then update `RUN_STATUS` only when
   new snapshots or worker state changes arrive.
4. **Phase Transition**: If `elapsed > warmup_seconds` and phase is WARMUP,
   write `SET_PHASE(MEASUREMENT)`. If `elapsed > duration`, write `STOP`.

### 3a. Warmup-to-Measurement Transition

Warmup is a **run-level** concept to prime Snowflake compute. The orchestrator
controls the single warmup-to-measurement transition:

```python
async def _check_phase_transitions(self, run_id: str) -> None:
    """Check if phase should transition."""
    run = await self.get_run_status(run_id)
    
    if run['phase'] == 'WARMUP':
        elapsed = (now() - run['start_time']).total_seconds()
        warmup_seconds = run['scenario_config']['workload']['warmup_seconds']
        
        if elapsed >= warmup_seconds:
            # Transition entire run to MEASUREMENT
            await self._update_run_status(
                run_id,
                phase='MEASUREMENT',
                warmup_end_time=now()
            )
            await self.emit_control_event(run_id, 'SET_PHASE', {
                'scope': 'RUN',
                'phase': 'MEASUREMENT'
            })
            log.info(f"Run {run_id} transitioned to MEASUREMENT after {elapsed}s warmup")
```

**Note**: Workers joining after this transition inherit MEASUREMENT phase directly.

### 3b. Find Max (Step-Load) Controller

The orchestrator owns the step controller for `FIND_MAX_CONCURRENCY` runs.

1. **Step Targets**: Compute per-worker TARGET_CONNECTIONS for the current step
   and emit per-worker `SET_WORKER_TARGET` events into `RUN_CONTROL_EVENTS`.
   `event_data` includes `step_id`, `worker_id`, `target_connections`,
   `effective_at`, `ramp_seconds`, and optional `reason`.
2. **Worker Behavior**: Workers poll control events and apply target changes.
   Workers never decide step transitions; they only report metrics.
3. **Step Evaluation**: Aggregate metrics across workers for the current step
   window, use controller-owned warehouse poller data to detect queueing, then
   decide: advance step, hold, or stop with reason.
4. **UI State**: Persist live state in `RUN_STATUS.FIND_MAX_STATE` (new VARIANT
   column), append step history to `FIND_MAX_STEP_HISTORY`, and store final
   summary in `TEST_RESULTS.FIND_MAX_RESULT`.

### 3c. Find Max Step Advance Criteria

The orchestrator advances to the next step when ALL of the following are true:

```python
async def _should_advance_step(self, run_id: str, step_number: int) -> bool:
    """
    Check if current step is stable and should advance.
    
    Criteria (all must be true):
    1. step_duration_seconds has elapsed since step start
    2. QPS is within qps_stability_pct of prior step (or first step)
    3. P95 latency is within latency_stability_pct of baseline (step 1)
    4. Error rate is below max_error_rate_pct
    5. No Snowflake queue detected
    """
    step = await self._get_current_step(run_id)
    config = step['find_max_config']
    
    # 1. Duration check
    elapsed = (now() - step['start_time']).total_seconds()
    if elapsed < config['step_duration_seconds']:
        return False
    
    # 2-5. Stability checks
    metrics = await self._get_step_aggregate_metrics(run_id, step_number)
    
    # Compare P95 to baseline (step 1)
    baseline_p95 = step.get('baseline_p95_ms') or metrics['p95_latency_ms']
    p95_increase_pct = ((metrics['p95_latency_ms'] - baseline_p95) / baseline_p95) * 100
    
    if p95_increase_pct > config['latency_stability_pct']:
        return False  # Latency degraded
    
    if metrics['error_rate'] > config['max_error_rate_pct'] / 100:
        return False  # Too many errors
    
    if metrics['queue_detected']:
        return False  # Snowflake queueing
    
    return True  # All checks passed, advance
```

**Baseline**: Step 1's P95 latency is the baseline for all subsequent steps.

### 4. Transition from TestRegistry

| Feature | `TestRegistry` (Old) | `OrchestratorService` (New) |
| :--- | :--- | :--- |
| Run State | In-memory `dict[id, RunningTest]` | `RUN_STATUS` table |
| Metrics | In-memory queue | Polled from `WORKER_METRICS_SNAPSHOTS` |
| Stopping | `task.cancel()` (local only) | `RUN_CONTROL_EVENTS (STOP)` |
| Logs | `deque` buffer | Persisted to `TEST_LOGS` table directly by workers |
| WebSockets | Subscribes to memory queue | Polls `RUN_STATUS` table updates |

Note: `WORKER_METRICS_SNAPSHOTS` stores per-worker snapshots.

### 5. Orphaned Run Recovery

If the orchestrator crashes, active runs become orphaned. Detection and recovery:

**Trigger:** The `OrchestratorService` performs this check **once on startup** (during initialization).

**Detection (external health check or restart):**
```sql
-- Find runs where orchestrator hasn't updated in 2 minutes
SELECT RUN_ID
FROM RUN_STATUS
WHERE STATUS = 'RUNNING'
  AND TIMESTAMPDIFF('second', UPDATED_AT, CURRENT_TIMESTAMP()) > 120;
```

**Recovery options:**
1. **Mark as FAILED**: Set `STATUS='FAILED'`, `END_TIME=NOW()` with reason
   "orchestrator crash detected"
2. **Resume** (future): A new orchestrator instance picks up the run

Workers self-terminate after 60s of failed connection attempts, ensuring no
zombie workers even if the orchestrator dies.

### 6. Emitting SET_WORKER_TARGET with Fallback

When the orchestrator changes worker targets, it updates both the event log and
the fallback column:

```python
async def set_worker_targets(
    self,
    run_id: str,
    targets: dict[str, int],  # worker_id -> target_connections
    reason: str = "orchestrator_request"
) -> None:
    """
    Set TARGET_CONNECTIONS for multiple workers.
    Updates both RUN_CONTROL_EVENTS and RUN_STATUS.WORKER_TARGETS.
    """
    # Update fallback column atomically
    await execute("""
        UPDATE RUN_STATUS
        SET WORKER_TARGETS = OBJECT_INSERT(
            COALESCE(WORKER_TARGETS, OBJECT_CONSTRUCT()),
            :updates
        ),
        UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE RUN_ID = :run_id
    """, run_id=run_id, updates=targets)
    
    # Emit per-worker events
    for worker_id, target in targets.items():
        await self.emit_control_event(run_id, 'SET_WORKER_TARGET', {
            'scope': 'WORKER',
            'worker_id': worker_id,
            'target_connections': target,
            'reason': reason
        })
```

## Local Development (N=1)

To satisfy the constraint "No separate path for N=1":

1. User clicks "Start Test".
2. Orchestrator creates `RUN_STATUS` row.
3. Orchestrator spawns **1 subprocess** via
   `python scripts/run_worker.py --run-id=...`.
4. Worker connects to Snowflake, registers, and polls for start.
5. Orchestrator sees registration, writes `START` event.
6. Worker sees `START`, begins load gen.

This ensures the exact same code path is used for N=1 (Local) and N=100
(SPCS).

## SPCS Implementation

For SPCS, `start_run` changes only in *how* it spawns workers:

- **Local**: `subprocess.Popen(...)`
- **SPCS**: `snowflake.execute("CALL SYSTEM$EXECUTE_SERVICE(...)")`

The rest of the logic (polling, heartbeats, events) remains identical.
