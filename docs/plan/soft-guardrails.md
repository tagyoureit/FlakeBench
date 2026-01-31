# Soft Resource Guardrails

**Goal**: Change CPU/memory guardrails from hard fail-fast limits to soft boundaries
that trigger adaptive scaling behavior before failing the entire run.

## Current Behavior (Problem)

The orchestrator currently checks `MAX(CPU_PERCENT)` and `MAX(MEMORY_PERCENT)`
across all worker heartbeats. If **any single worker's host** exceeds the threshold,
the entire run fails immediately with a guardrail violation.

This is problematic because:
- A single overloaded host shouldn't fail a distributed run.
- No opportunity to redistribute load or scale out to relieve pressure.
- Treats soft targets as hard limits.

## Desired Behavior

Resource thresholds should be **soft boundaries** that trigger adaptive responses:

| Condition | Response |
|-----------|----------|
| ONE worker exceeds threshold | Back off that worker, redistribute load |
| SOME workers exceed threshold | Scale out if within bounds |
| ALL workers exceed threshold | Fail the run (true exhaustion) |

**Adaptive Actions (in priority order):**

1. **Back-off**: Reduce `TARGET_CONNECTIONS` for the overloaded worker(s).
2. **Redistribute**: Shift load to workers with headroom (if heterogeneous hosts).
3. **Scale-out**: Add new workers if `scaling.mode` allows and bounds permit.
4. **Graceful degradation**: Continue at reduced capacity with warning.
5. **Fail**: Only if ALL workers exceed thresholds for N consecutive intervals.

## Implementation Tasks

- [ ] **Change orchestrator guardrail logic**: Replace `MAX()` check with per-worker
  analysis:
  - Track which workers are over threshold.
  - Only fail if `over_threshold_count == total_workers` for N intervals.
- [ ] **Add back-off mechanism**: When a worker exceeds threshold:
  - Emit `SCALE_DOWN` control event for that worker.
  - Worker reduces `TARGET_CONNECTIONS` by configurable percentage (default: 20%).
  - Track back-off state in `RUN_STATUS.CUSTOM_METRICS`.
- [ ] **Add scale-out trigger**: When workers are backed off but target not met:
  - If `scaling.mode` is AUTO or BOUNDED and within bounds, spawn new worker.
  - New worker absorbs load that was shed by backed-off workers.
- [ ] **Add patience/hysteresis**: Don't react immediately to threshold crossing:
  - Require N consecutive intervals (default: 3) before taking action.
  - Prevent thrashing from momentary spikes.
- [ ] **Update RUN_STATUS tracking**: Add fields to track soft guardrail state:
  - `workers_over_cpu_threshold`: count
  - `workers_over_memory_threshold`: count
  - `soft_guardrail_actions`: list of actions taken (back-off, scale-out)
- [ ] **Update UI**: Show soft guardrail status in live dashboard:
  - Warning indicator when any worker is over threshold.
  - Show back-off state and actions taken.
  - Only show error state when ALL workers exceed and run is failing.
- [ ] **Update completion reasons**: Add new completion reason:
  - `SOFT_GUARDRAIL_DEGRADED`: Run completed but at reduced capacity.
- [x] **UI Rationalization**: Removed `autoscale_enabled` checkbox and merged into
  `scaling.mode`. Guardrails fields now show for AUTO and BOUNDED modes only.

## Configuration Schema Update

```json
{
  "scaling": {
    "mode": "BOUNDED",
    "min_workers": 2,
    "max_workers": 10,
    "min_connections": 25,
    "max_connections": 500
  },
  "guardrails": {
    "max_cpu_percent": 80,
    "max_memory_percent": 85,
    "mode": "soft",
    "back_off_percent": 20,
    "patience_intervals": 3,
    "fail_threshold": "all"
  }
}
```

**New `guardrails.mode` options:**
- `soft` (default): Adaptive response as described above.
- `hard`: Legacy behavior - fail immediately if ANY worker exceeds.

**New `guardrails.fail_threshold` options:**
- `all` (default): Only fail if ALL workers exceed thresholds.
- `majority`: Fail if >50% of workers exceed thresholds.
- `any`: Legacy behavior - fail if ANY worker exceeds (same as `hard` mode).

## Acceptance Criteria

- Single worker exceeding threshold does NOT fail the run.
- Back-off reduces load on overloaded worker within 2 poll intervals.
- Scale-out is triggered when back-off alone is insufficient.
- Run only fails when ALL workers exceed thresholds for 3+ intervals.
- UI shows warning state (yellow) vs error state (red) appropriately.
- Soft guardrail actions are logged and visible in run history.
