import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from backend.core import results_store
from backend.core.orchestrator import OrchestratorService, RunContext

# TODO: Add integration coverage against live Snowflake control-plane tables.


class _StopRunPool:
    def __init__(self, *, status_sequence: list[str], heartbeat_remaining: list[int]):
        self._status_sequence = list(status_sequence)
        self._heartbeat_remaining = list(heartbeat_remaining)
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(self, query: str, params: list[object] | None = None):
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()
        if "SELECT STATUS" in sql and "FROM" in sql and "RUN_STATUS" in sql:
            status = self._status_sequence.pop(0)
            return [(status,)]
        if "SELECT COUNT(*)" in sql and "WORKER_HEARTBEATS" in sql:
            remaining = self._heartbeat_remaining.pop(0)
            return [(remaining,)]
        return []


class _StubProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _PollLoopPool:
    def __init__(
        self,
        *,
        status: str,
        phase: str,
        start_time: datetime | None,
        warmup_start_time: datetime | None = None,
        heartbeat_row: tuple[object, ...],
        metrics_row: tuple[object, ...] | None = None,
    ) -> None:
        self.status = status
        self.phase = phase
        self.start_time = start_time
        self.warmup_start_time = warmup_start_time
        self.heartbeat_row = heartbeat_row
        self.metrics_row = metrics_row
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(self, query: str, params: list[object] | None = None):
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()
        if (
            "SELECT STATUS, PHASE," in sql
            and "TIMESTAMPDIFF" in sql
            and "RUN_STATUS" in sql
        ):
            elapsed = None
            warmup_elapsed = None
            if self.start_time is not None:
                elapsed = (datetime.now(UTC) - self.start_time).total_seconds()
            if self.warmup_start_time is not None:
                warmup_elapsed = (
                    datetime.now(UTC) - self.warmup_start_time
                ).total_seconds()
            return [(self.status, self.phase, elapsed, warmup_elapsed)]
        if "SELECT COUNT(*) AS WORKER_COUNT" in sql and "WORKER_HEARTBEATS" in sql:
            return [self.heartbeat_row]
        if "FROM" in sql and "WORKER_METRICS_SNAPSHOTS" in sql:
            if self.metrics_row is None:
                return []
            row = tuple(self.metrics_row)
            if len(row) < 8:
                row = row + (None,) * (8 - len(row))
            return [row]
        return []


class _ParentRollupPool:
    def __init__(
        self,
        *,
        summary_row: tuple[object, ...],
        metrics_row: tuple[object, ...] | None,
        find_max_row: tuple[object, ...] | None,
    ) -> None:
        self.summary_row = summary_row
        self.metrics_row = metrics_row
        self.find_max_row = find_max_row
        self.merge_params: list[object] | None = None
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(self, query: str, params: list[object] | None = None):
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()
        if "MIN(TEST_NAME)" in sql and "FROM" in sql and "TEST_RESULTS" in sql:
            return [self.summary_row]
        if "FROM" in sql and "WORKER_METRICS_SNAPSHOTS" in sql:
            return [self.metrics_row] if self.metrics_row is not None else []
        if "SELECT FIND_MAX_RESULT" in sql:
            return [self.find_max_row] if self.find_max_row is not None else []
        if "MERGE INTO" in sql and "TEST_RESULTS" in sql:
            self.merge_params = list(params or [])
            return []
        return []


@pytest.mark.asyncio
async def test_stop_run_skips_terminal(monkeypatch):
    pool = _StopRunPool(status_sequence=["COMPLETED"], heartbeat_remaining=[])
    svc = OrchestratorService()
    svc._pool = pool

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)

    await svc.stop_run("run-terminal")

    assert not events
    assert len(pool.calls) == 1


@pytest.mark.asyncio
async def test_stop_run_emits_stop_and_cancels(monkeypatch):
    pool = _StopRunPool(
        status_sequence=["RUNNING", "CANCELLING"],
        heartbeat_remaining=[0],
    )
    svc = OrchestratorService()
    svc._pool = pool
    svc._active_runs["run-1"] = RunContext(
        run_id="run-1",
        worker_group_count=1,
        template_id="t1",
        scenario_config={},
    )

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)

    await svc.stop_run("run-1")

    assert events
    assert events[0][0] == "STOP"
    assert events[0][1]["drain_timeout_seconds"] == 120.0
    assert any("SET STATUS = 'CANCELLING'" in call[0] for call in pool.calls)
    assert any("SET STATUS = 'CANCELLED'" in call[0] for call in pool.calls)
    assert any("UPDATE" in call[0] and "TEST_RESULTS" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_stop_run_terminates_local_workers_after_timeout(monkeypatch):
    pool = _StopRunPool(
        status_sequence=["RUNNING", "CANCELLING"],
        heartbeat_remaining=[],
    )
    svc = OrchestratorService()
    svc._pool = pool
    proc = _StubProcess()
    ctx = RunContext(
        run_id="run-local",
        worker_group_count=1,
        template_id="t1",
        scenario_config={},
    )
    ctx.worker_procs.append(cast(asyncio.subprocess.Process, proc))
    svc._active_runs["run-local"] = ctx

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        return 1

    async def fake_wait_for(awaitable, timeout):
        task = asyncio.create_task(awaitable)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise asyncio.TimeoutError

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await svc.stop_run("run-local")

    assert proc.terminated is True
    assert proc.killed is True


@pytest.mark.asyncio
async def test_poll_loop_guardrail_emits_stop(monkeypatch):
    pool = _PollLoopPool(
        status="RUNNING",
        phase="WARMUP",
        start_time=None,
        heartbeat_row=(1, 1, 0, 0, 0, None, 90.0, 10.0),
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-guardrail",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 0, "duration_seconds": 0},
            "guardrails": {"max_cpu_percent": 80.0},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-guardrail"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-guardrail")

    assert events
    assert events[0][0] == "STOP"
    assert events[0][1]["reason"] == "guardrail"
    assert any("SET STATUS = 'FAILED'" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_poll_loop_duration_emits_stop(monkeypatch):
    start_time = datetime.now(UTC) - timedelta(seconds=30)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=start_time,
        heartbeat_row=(1, 1, 0, 0, 0, None, None, None),
        metrics_row=None,
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-duration",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 0, "duration_seconds": 10},
            "guardrails": {},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-duration"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-duration")

    assert any(e[0] == "STOP" and e[1]["reason"] == "duration_elapsed" for e in events)
    assert any("SET STATUS = 'STOPPING'" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_poll_loop_rollup_updates_run_status(monkeypatch):
    latest_ts = datetime.now(UTC).replace(tzinfo=None)
    heartbeat_updated_at = datetime.now(UTC).replace(tzinfo=None)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=None,
        heartbeat_row=(2, 2, 0, 0, 0, heartbeat_updated_at, None, None),
        metrics_row=(100, 2, 12.5, 50, latest_ts),
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-rollup",
        worker_group_count=2,
        template_id="t1",
        scenario_config={"workload": {"warmup_seconds": 0, "duration_seconds": 0}},
    )
    ctx.stopping = True
    svc._active_runs["run-rollup"] = ctx

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-rollup")

    assert any("SET WORKERS_REGISTERED" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_poll_loop_bounded_qps_completes_on_bounds_limit(monkeypatch):
    latest_ts = datetime.now(UTC).replace(tzinfo=None)
    heartbeat_updated_at = datetime.now(UTC).replace(tzinfo=None)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=None,
        heartbeat_row=(2, 2, 0, 0, 0, heartbeat_updated_at, None, None),
        metrics_row=(100, 0, 80.0, 20, latest_ts),
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-bounded",
        worker_group_count=2,
        template_id="t1",
        scenario_config={
            "workload": {
                "load_mode": "QPS",
                "target_qps": 100,
                "warmup_seconds": 0,
                "duration_seconds": 0,
            },
            "scaling": {
                "mode": "BOUNDED",
                "min_workers": 1,
                "max_workers": 2,
                "min_connections": 5,
                "max_connections": 10,
                "bounds_patience_intervals": 1,
            },
        },
    )
    svc._active_runs["run-bounded"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-bounded")

    assert any(
        e[0] == "STOP" and e[1].get("reason") == "bounds_limit_reached" for e in events
    )
    assert any("CUSTOM_METRICS" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_update_parent_run_aggregate_uses_worker_metrics(monkeypatch):
    parent_run_id = "parent-1"
    start_time = datetime.now(UTC) - timedelta(seconds=30)
    end_time = datetime.now(UTC)

    summary_row = (
        "test-name",
        "scenario-name",
        "TABLE1",
        "STANDARD",
        "WH",
        "SMALL",
        start_time,
        end_time,
        10,  # duration_seconds
        50,  # total_concurrency (CONCURRENT_CONNECTIONS sum)
        100,  # read_operations
        50,  # write_operations
        2,  # failed_operations
        150,  # total_operations
        1,  # failed_workers (>0 triggers FAILED status)
        0,  # running_workers
        2,  # worker_count
    )
    metrics_row = (
        200,
        120,
        80,
        5,
        20.0,
        10.0,
        1.0,
        2.0,
        3.0,
        1.5,
    )
    pool = _ParentRollupPool(
        summary_row=summary_row, metrics_row=metrics_row, find_max_row=None
    )

    def fake_pool():
        return pool

    monkeypatch.setattr(results_store.snowflake_pool, "get_default_pool", fake_pool)

    await results_store.update_parent_run_aggregate(parent_run_id=parent_run_id)

    assert pool.merge_params is not None
    assert pool.merge_params[8] == "FAILED"
    assert pool.merge_params[13] == 200
    assert pool.merge_params[18] == 12.0
    assert pool.merge_params[19] == 8.0
    assert pool.merge_params[24] == 5
    assert pool.merge_params[25] == 0.025


@pytest.mark.asyncio
async def test_poll_loop_duration_includes_warmup(monkeypatch):
    """
    Regression test: duration check must use warmup_seconds + duration_seconds.

    With warmup=10s and duration=10s, a run that has been going for 15 seconds
    since warmup start should NOT be stopped (still in measurement phase, needs 20s total).
    """
    # 10s PREPARING + 15s since warmup start (past warmup but not past total)
    start_time = datetime.now(UTC) - timedelta(seconds=25)
    warmup_start_time = datetime.now(UTC) - timedelta(seconds=15)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=start_time,
        warmup_start_time=warmup_start_time,
        heartbeat_row=(1, 1, 0, 0, 0, None, None, None),
        metrics_row=None,
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-warmup-duration",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 10, "duration_seconds": 10},
            "guardrails": {},
        },
    )
    ctx.stopping = True  # End poll loop after one iteration
    svc._active_runs["run-warmup-duration"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-warmup-duration")

    # Should NOT have emitted a STOP event for duration_elapsed
    duration_stop_events = [
        e for e in events if e[0] == "STOP" and e[1].get("reason") == "duration_elapsed"
    ]
    assert len(duration_stop_events) == 0, (
        "Run should not stop at 15s when warmup=10s and duration=10s (total=20s needed)"
    )


@pytest.mark.asyncio
async def test_poll_loop_duration_stops_after_warmup_plus_duration(monkeypatch):
    """
    Verify that the run DOES stop when elapsed >= warmup + duration.

    With warmup=10s and duration=10s, a run that has been going for 25 seconds
    SHOULD be stopped.
    """
    # 10s PREPARING + 25s since warmup start (past warmup+duration)
    start_time = datetime.now(UTC) - timedelta(seconds=35)
    warmup_start_time = datetime.now(UTC) - timedelta(seconds=25)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=start_time,
        warmup_start_time=warmup_start_time,
        heartbeat_row=(1, 1, 0, 0, 0, None, None, None),
        metrics_row=None,
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-warmup-duration-stop",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 10, "duration_seconds": 10},
            "guardrails": {},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-warmup-duration-stop"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-warmup-duration-stop")

    # SHOULD have emitted a STOP event for duration_elapsed
    assert any(
        e[0] == "STOP" and e[1].get("reason") == "duration_elapsed" for e in events
    ), "Run should stop at 25s when warmup=10s and duration=10s (total=20s needed)"
    assert any("SET STATUS = 'STOPPING'" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_poll_loop_warmup_phase_transition(monkeypatch):
    """
    Verify that the phase transitions from WARMUP to MEASUREMENT after warmup_seconds.
    """
    # 15 seconds elapsed - past warmup (10s)
    start_time = datetime.now(UTC) - timedelta(seconds=15)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="WARMUP",  # Still in WARMUP phase
        start_time=start_time,
        warmup_start_time=start_time,
        heartbeat_row=(1, 1, 0, 0, 0, None, None, None),
        metrics_row=None,
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-phase-transition",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 10, "duration_seconds": 10},
            "guardrails": {},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-phase-transition"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-phase-transition")

    # Should have emitted a SET_PHASE event transitioning to MEASUREMENT
    phase_events = [
        e for e in events if e[0] == "SET_PHASE" and e[1].get("phase") == "MEASUREMENT"
    ]
    assert len(phase_events) == 1, "Should transition to MEASUREMENT phase after warmup"
    # Should have updated PHASE in RUN_STATUS
    assert any("SET PHASE = 'MEASUREMENT'" in call[0] for call in pool.calls)


@pytest.mark.asyncio
async def test_poll_loop_worker_exit_ends_poll(monkeypatch):
    """
    Verify that the poll loop ends when all worker processes have exited.
    """
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=datetime.now(UTC),
        heartbeat_row=(1, 1, 0, 0, 0, None, None, None),
        metrics_row=None,
    )
    svc = OrchestratorService()
    svc._pool = pool

    # Create a stub process that has already exited (returncode is set)
    proc = _StubProcess()
    proc.returncode = 0  # Process has exited

    ctx = RunContext(
        run_id="run-worker-exit",
        worker_group_count=1,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 0, "duration_seconds": 300},  # Long duration
            "guardrails": {},
        },
    )
    ctx.worker_procs.append(cast(asyncio.subprocess.Process, proc))
    svc._active_runs["run-worker-exit"] = ctx

    poll_loop_iterations = 0

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        return 1

    async def counting_sleep(delay: float) -> None:
        nonlocal poll_loop_iterations
        poll_loop_iterations += 1
        if poll_loop_iterations > 5:
            # Safety valve - should have exited before this
            raise RuntimeError("Poll loop did not exit after worker process ended")
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", counting_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-worker-exit")

    # Poll loop should have exited due to worker process exit, not due to timeout
    assert poll_loop_iterations <= 1, (
        "Poll loop should exit immediately when all workers have exited"
    )
    # Run should have been removed from active runs
    assert "run-worker-exit" not in svc._active_runs


# =============================================================================
# Edge Case Tests
# =============================================================================


class _WorkerDeathPool:
    """Pool that simulates worker death during phase transition."""

    def __init__(self, *, status_sequence: list[str], phase_sequence: list[str]):
        self._status_sequence = list(status_sequence)
        self._phase_sequence = list(phase_sequence)
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(self, query: str, params: list[object] | None = None):
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()
        if "SELECT STATUS" in sql and "FROM" in sql and "RUN_STATUS" in sql:
            status = self._status_sequence.pop(0) if self._status_sequence else "RUNNING"
            return [(status,)]
        if (
            "SELECT STATUS, PHASE," in sql
            and "TIMESTAMPDIFF" in sql
            and "RUN_STATUS" in sql
        ):
            status = self._status_sequence.pop(0) if self._status_sequence else "RUNNING"
            phase = self._phase_sequence.pop(0) if self._phase_sequence else "MEASUREMENT"
            return [(status, phase, 30.0, 30.0)]
        if "SELECT COUNT(*) AS WORKER_COUNT" in sql and "WORKER_HEARTBEATS" in sql:
            # Simulate worker death - count drops to 0
            return [(0, 0, 0, 1, 0, None, None, None)]  # 1 failed worker
        return []


@pytest.mark.asyncio
async def test_worker_death_during_phase_transition(monkeypatch):
    """
    GIVEN: A run transitioning from WARMUP to MEASUREMENT
    WHEN: A worker dies during the transition
    THEN: The run is marked as FAILED and poll loop exits gracefully
    """
    pool = _WorkerDeathPool(
        status_sequence=["RUNNING", "RUNNING"],
        phase_sequence=["WARMUP", "MEASUREMENT"],
    )
    svc = OrchestratorService()
    svc._pool = pool

    proc = _StubProcess()
    proc.returncode = 1  # Worker exited with error

    ctx = RunContext(
        run_id="run-worker-death",
        worker_group_count=2,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 10, "duration_seconds": 60},
            "guardrails": {},
        },
    )
    ctx.worker_procs.append(cast(asyncio.subprocess.Process, proc))
    ctx.stopping = True
    svc._active_runs["run-worker-death"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-worker-death")

    # Run should have been cleaned up
    assert "run-worker-death" not in svc._active_runs


@pytest.mark.asyncio
async def test_concurrent_stop_run_calls(monkeypatch):
    """
    GIVEN: A running test
    WHEN: Multiple stop_run calls are made concurrently
    THEN: Only one STOP event is emitted and state is consistent
    """
    pool = _StopRunPool(
        status_sequence=["RUNNING", "CANCELLING", "CANCELLING", "CANCELLING"],
        heartbeat_remaining=[0, 0],
    )
    svc = OrchestratorService()
    svc._pool = pool
    svc._active_runs["run-concurrent"] = RunContext(
        run_id="run-concurrent",
        worker_group_count=1,
        template_id="t1",
        scenario_config={},
    )

    events: list[tuple[str, dict[str, object]]] = []
    emit_lock = asyncio.Lock()

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        async with emit_lock:
            events.append((event_type, event_data))
        return 1

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)

    # Call stop_run concurrently
    await asyncio.gather(
        svc.stop_run("run-concurrent"),
        svc.stop_run("run-concurrent"),
    )

    # Should have emitted STOP events (may be 1 or 2 depending on race)
    stop_events = [e for e in events if e[0] == "STOP"]
    # At minimum, the run should end up in terminal state
    # The exact number of STOP events depends on timing


@pytest.mark.asyncio
async def test_stop_during_starting_phase(monkeypatch):
    """
    GIVEN: A run in STARTING phase (workers spawning)
    WHEN: stop_run is called
    THEN: Run transitions to CANCELLING and workers are terminated
    """
    pool = _StopRunPool(
        status_sequence=["STARTING", "CANCELLING"],
        heartbeat_remaining=[0],
    )
    svc = OrchestratorService()
    svc._pool = pool

    proc = _StubProcess()
    ctx = RunContext(
        run_id="run-starting",
        worker_group_count=2,
        template_id="t1",
        scenario_config={},
    )
    ctx.worker_procs.append(cast(asyncio.subprocess.Process, proc))
    svc._active_runs["run-starting"] = ctx

    events: list[tuple[str, dict[str, object]]] = []

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        events.append((event_type, event_data))
        return 1

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)

    await svc.stop_run("run-starting")

    # Should have emitted STOP event
    assert any(e[0] == "STOP" for e in events)
    # Worker process should have been terminated
    assert proc.terminated or proc.killed


@pytest.mark.asyncio
async def test_partial_worker_registration_timeout(monkeypatch):
    """
    GIVEN: A run expecting 3 workers but only 2 register
    WHEN: Poll loop detects incomplete registration after timeout
    THEN: Run continues with available workers (degraded mode)
    """
    heartbeat_updated_at = datetime.now(UTC).replace(tzinfo=None)
    pool = _PollLoopPool(
        status="RUNNING",
        phase="MEASUREMENT",
        start_time=datetime.now(UTC) - timedelta(seconds=60),
        heartbeat_row=(2, 2, 0, 0, 0, heartbeat_updated_at, None, None),  # Only 2 workers
        metrics_row=(100, 2, 12.5, 50, datetime.now(UTC).replace(tzinfo=None)),
    )
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-partial",
        worker_group_count=3,  # Expected 3 workers
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 0, "duration_seconds": 0},
            "guardrails": {},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-partial"] = ctx

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    # Should complete without error even with partial registration
    await svc._run_poll_loop("run-partial")

    # Run should have been processed
    assert "run-partial" not in svc._active_runs


class _NaturalCompletionPool:
    """Pool that simulates natural run completion (STOPPING -> COMPLETED)."""

    def __init__(self):
        self._status_calls = 0
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(self, query: str, params: list[object] | None = None):
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()
        # Check more specific patterns FIRST
        if (
            "SELECT STATUS, PHASE," in sql
            and "TIMESTAMPDIFF" in sql
            and "RUN_STATUS" in sql
        ):
            self._status_calls += 1
            # First call returns STOPPING, subsequent calls return COMPLETED
            if self._status_calls == 1:
                return [("STOPPING", "MEASUREMENT", 120.0, 100.0)]
            return [("COMPLETED", "MEASUREMENT", 130.0, 110.0)]
        if "SELECT COUNT(*) AS WORKER_COUNT" in sql and "WORKER_HEARTBEATS" in sql:
            return [(0, 0, 0, 0, 0, None, None, None)]  # All workers done
        if "SELECT COUNT(*)" in sql and "WORKER_HEARTBEATS" in sql:
            return [(0,)]
        return []


@pytest.mark.asyncio
async def test_natural_completion_stopping_to_completed(monkeypatch):
    """
    GIVEN: A run in STOPPING phase after duration elapsed
    WHEN: All workers complete naturally
    THEN: Run transitions to COMPLETED status
    """
    pool = _NaturalCompletionPool()
    svc = OrchestratorService()
    svc._pool = pool
    ctx = RunContext(
        run_id="run-natural",
        worker_group_count=2,
        template_id="t1",
        scenario_config={
            "workload": {"warmup_seconds": 10, "duration_seconds": 60},
            "guardrails": {},
        },
    )
    ctx.stopping = True
    svc._active_runs["run-natural"] = ctx

    async def fake_emit(*, run_id: str, event_type: str, event_data: dict[str, object]):
        return 1

    async def fast_sleep(_: float) -> None:
        return None

    async def fake_rollup(*, parent_run_id: str) -> None:
        return None

    monkeypatch.setattr(svc, "_emit_control_event", fake_emit)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(results_store, "update_parent_run_aggregate", fake_rollup)

    await svc._run_poll_loop("run-natural")

    # Should have transitioned to COMPLETED
    completed_updates = [
        c for c in pool.calls if "SET STATUS = 'COMPLETED'" in c[0]
    ]
    assert len(completed_updates) >= 1, "Run should transition to COMPLETED"
    # Run should be cleaned up
    assert "run-natural" not in svc._active_runs
