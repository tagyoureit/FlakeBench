"""
Autoscale orchestration for multi-node benchmark runs.

Scale-out only (Option A) using host-level guardrails (Option B).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from backend.core import results_store
from backend.core.test_registry import registry
from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoscaleSpec:
    template_id: str
    max_cpu_percent: float
    max_memory_percent: float
    scale_interval_seconds: float = 10.0
    poll_interval_seconds: float = 5.0


@dataclass
class AutoscaleRun:
    parent_run_id: str
    target_node_count: int
    started_nodes: int = 0
    stopped_by_guardrail: bool = False


def _uv_available(uv_bin: str) -> bool:
    return shutil.which(uv_bin) is not None


def _coerce_float(v: Any, *, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _coerce_int(v: Any, *, default: int) -> int:
    try:
        return int(float(v))
    except Exception:
        return int(default)


def _parse_json_variant(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            return dict(json.loads(raw))
        except Exception:
            return {}
    return {}


async def _fetch_latest_resources(parent_run_id: str) -> dict[str, Any]:
    pool = snowflake_pool.get_default_pool()
    query = f"""
    SELECT CUSTOM_METRICS
    FROM {results_store._results_prefix()}.NODE_METRICS_SNAPSHOTS
    WHERE PARENT_RUN_ID = ?
    ORDER BY TIMESTAMP DESC
    LIMIT 1
    """
    rows = await pool.execute_query(query, params=[parent_run_id])
    if not rows or not rows[0]:
        return {}
    metrics = _parse_json_variant(rows[0][0])
    resources = metrics.get("resources")
    return dict(resources) if isinstance(resources, dict) else {}


def _effective_host_cpu_percent(resources: dict[str, Any]) -> float | None:
    if resources.get("cgroup_cpu_percent") is not None:
        return _coerce_float(resources.get("cgroup_cpu_percent"), default=0.0)
    if resources.get("host_cpu_percent") is not None:
        return _coerce_float(resources.get("host_cpu_percent"), default=0.0)
    return None


def _effective_host_memory_percent(resources: dict[str, Any]) -> float | None:
    if resources.get("cgroup_memory_percent") is not None:
        return _coerce_float(resources.get("cgroup_memory_percent"), default=0.0)
    if resources.get("host_memory_percent") is not None:
        return _coerce_float(resources.get("host_memory_percent"), default=0.0)
    return None


async def _guardrails_ok(
    *, parent_run_id: str, max_cpu_percent: float, max_memory_percent: float
) -> bool:
    resources = await _fetch_latest_resources(parent_run_id)
    if not resources:
        return True
    cpu = _effective_host_cpu_percent(resources)
    mem = _effective_host_memory_percent(resources)
    if cpu is not None and cpu >= max_cpu_percent:
        logger.warning(
            "Autoscale guardrail hit: host CPU %.2f >= %.2f", cpu, max_cpu_percent
        )
        return False
    if mem is not None and mem >= max_memory_percent:
        logger.warning(
            "Autoscale guardrail hit: host memory %.2f >= %.2f",
            mem,
            max_memory_percent,
        )
        return False
    return True


def _build_worker_cmd(
    *,
    uv_bin: str,
    template_id: str,
    parent_run_id: str,
    worker_group_id: int,
    worker_group_count: int,
    node_id: str,
    per_node_concurrency: int,
    target_qps: float | None = None,
) -> list[str]:
    cmd = [
        uv_bin,
        "run",
        "python",
        "scripts/run_worker.py",
        "--template-id",
        template_id,
        "--worker-group-id",
        str(worker_group_id),
        "--worker-group-count",
        str(worker_group_count),
        "--parent-run-id",
        parent_run_id,
        "--node-id",
        node_id,
        "--concurrency",
        str(per_node_concurrency),
    ]
    if target_qps is not None:
        cmd.extend(["--target-qps", str(float(target_qps))])
    return cmd


def _load_mode_from_config(cfg: dict[str, Any]) -> str:
    load_mode = str(cfg.get("load_mode") or "CONCURRENCY").strip().upper()
    if load_mode not in {"CONCURRENCY", "QPS", "FIND_MAX_CONCURRENCY"}:
        return "CONCURRENCY"
    return load_mode


def _autoscale_total_target_concurrency(cfg: dict[str, Any]) -> int:
    raw = cfg.get("concurrent_connections")
    return _coerce_int(raw, default=0)


def _autoscale_target_qps(cfg: dict[str, Any]) -> float:
    raw = cfg.get("target_qps")
    return _coerce_float(raw, default=0.0)


async def _fetch_latest_node_metrics(parent_run_id: str) -> list[dict[str, Any]]:
    pool = snowflake_pool.get_default_pool()
    query = f"""
    SELECT WORKER_GROUP_ID, NODE_ID, QPS, TARGET_WORKERS, ACTIVE_CONNECTIONS, TIMESTAMP
    FROM {results_store._results_prefix()}.NODE_METRICS_SNAPSHOTS
    WHERE PARENT_RUN_ID = ?
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY WORKER_GROUP_ID
        ORDER BY TIMESTAMP DESC
    ) = 1
    """
    rows = await pool.execute_query(query, params=[parent_run_id])
    out: list[dict[str, Any]] = []
    for worker_group_id, node_id, qps, target_workers, active_connections, ts in rows:
        out.append(
            {
                "worker_group_id": int(worker_group_id or 0),
                "node_id": str(node_id or ""),
                "qps": _coerce_float(qps, default=0.0),
                "target_workers": _coerce_int(target_workers, default=0),
                "active_connections": _coerce_int(active_connections, default=0),
                "timestamp": ts,
            }
        )
    return out


async def _update_autoscale_state(
    *,
    parent_run_id: str,
    node_count: int,
    target_qps_total: float | None,
    per_node_target_qps: float | None,
) -> None:
    pool = snowflake_pool.get_default_pool()
    rows = await pool.execute_query(
        f"""
        SELECT CUSTOM_METRICS
        FROM {results_store._results_prefix()}.TEST_RESULTS
        WHERE TEST_ID = ?
        """,
        params=[parent_run_id],
    )
    base: dict[str, Any] = {}
    if rows and rows[0]:
        cm = _parse_json_variant(rows[0][0])
        if isinstance(cm, dict):
            base = dict(cm)
    autoscale_state = {
        "node_count": int(max(1, node_count)),
        "target_qps_total": float(target_qps_total)
        if target_qps_total is not None
        else None,
        "target_qps_per_node": float(per_node_target_qps)
        if per_node_target_qps is not None
        else None,
    }
    base["autoscale_state"] = autoscale_state
    await pool.execute_query(
        f"""
        UPDATE {results_store._results_prefix()}.TEST_RESULTS
        SET CUSTOM_METRICS = PARSE_JSON(?),
            UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE TEST_ID = ?
        """,
        params=[json.dumps(base), parent_run_id],
    )


async def _run_autoscale(
    *,
    spec: AutoscaleSpec,
    run: AutoscaleRun,
    per_node_concurrency: int,
    load_mode: str,
    target_qps_total: float | None = None,
    uv_bin: str = "uv",
    node_id_prefix: str = "autoscale",
) -> None:
    if not _uv_available(uv_bin):
        raise RuntimeError("uv not found. Install uv to run autoscale workers.")

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    procs: list[tuple[int, asyncio.subprocess.Process]] = []
    under_target_streak = 0

    async def _start_node(
        *, node_idx: int, node_count: int, target_qps_per_node: float | None
    ) -> None:
        node_id = f"{node_id_prefix}-{node_idx}"
        cmd = _build_worker_cmd(
            uv_bin=uv_bin,
            template_id=spec.template_id,
            parent_run_id=run.parent_run_id,
            worker_group_id=node_idx,
            worker_group_count=node_count,
            node_id=node_id,
            per_node_concurrency=per_node_concurrency,
            target_qps=target_qps_per_node,
        )
        logger.info(
            "Autoscale: starting worker %s/%s node_id=%s",
            node_idx + 1,
            node_count,
            node_id,
        )
        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        procs.append((node_idx, proc))
        run.started_nodes += 1

    if load_mode == "QPS":
        target_qps_total = (
            float(target_qps_total) if target_qps_total is not None else None
        )
        if not target_qps_total or not math.isfinite(target_qps_total):
            raise ValueError("Autoscale QPS requires target_qps > 0.")
        per_node_target = float(target_qps_total)
        await _update_autoscale_state(
            parent_run_id=run.parent_run_id,
            node_count=1,
            target_qps_total=target_qps_total,
            per_node_target_qps=per_node_target,
        )
        await _start_node(node_idx=0, node_count=1, target_qps_per_node=per_node_target)
    else:
        while run.started_nodes < run.target_node_count:
            if run.started_nodes > 0:
                await asyncio.sleep(spec.scale_interval_seconds)
                ok = await _guardrails_ok(
                    parent_run_id=run.parent_run_id,
                    max_cpu_percent=spec.max_cpu_percent,
                    max_memory_percent=spec.max_memory_percent,
                )
                if not ok:
                    run.stopped_by_guardrail = True
                    break

            idx = run.started_nodes
            await _start_node(
                node_idx=idx,
                node_count=run.target_node_count,
                target_qps_per_node=None,
            )

    while True:
        if procs and all(proc.returncode is not None for _, proc in procs):
            break

        await asyncio.sleep(spec.scale_interval_seconds)
        ok = await _guardrails_ok(
            parent_run_id=run.parent_run_id,
            max_cpu_percent=spec.max_cpu_percent,
            max_memory_percent=spec.max_memory_percent,
        )
        if not ok:
            run.stopped_by_guardrail = True
            break

        if load_mode != "QPS":
            continue

        nodes = await _fetch_latest_node_metrics(run.parent_run_id)
        total_qps = sum(float(n.get("qps") or 0.0) for n in nodes)
        all_at_ceiling = (
            bool(nodes)
            and all(
                int(n.get("target_workers") or 0) >= int(per_node_concurrency)
                for n in nodes
            )
            and run.started_nodes == len(nodes)
        )
        if target_qps_total is None:
            break
        target_qps_total_value = float(target_qps_total)
        under_target = total_qps < target_qps_total_value * 0.98
        if under_target and all_at_ceiling:
            under_target_streak += 1
        else:
            under_target_streak = 0

        if under_target_streak >= 2:
            under_target_streak = 0
            next_idx = run.started_nodes
            next_count = run.started_nodes + 1
            run.target_node_count = max(run.target_node_count, next_count)
            per_node_target = float(target_qps_total_value) / float(next_count)
            await _update_autoscale_state(
                parent_run_id=run.parent_run_id,
                node_count=next_count,
                target_qps_total=target_qps_total,
                per_node_target_qps=per_node_target,
            )
            await _start_node(
                node_idx=next_idx,
                node_count=next_count,
                target_qps_per_node=per_node_target,
            )

    exit_code = 0
    for idx, proc in procs:
        rc = await proc.wait()
        if rc != 0:
            logger.error("Autoscale: worker %s exited with %s", idx, rc)
            exit_code = 1

    try:
        await results_store.update_parent_run_aggregate(parent_run_id=run.parent_run_id)
    except Exception as exc:
        logger.error("Autoscale: parent aggregation failed: %s", exc)
        exit_code = 1

    if exit_code == 0:
        logger.info(
            "Autoscale complete parent_run_id=%s nodes_started=%s/%s guardrail=%s",
            run.parent_run_id,
            run.started_nodes,
            run.target_node_count,
            run.stopped_by_guardrail,
        )
    else:
        logger.warning(
            "Autoscale finished with errors parent_run_id=%s nodes_started=%s/%s guardrail=%s",
            run.parent_run_id,
            run.started_nodes,
            run.target_node_count,
            run.stopped_by_guardrail,
        )


async def prepare_autoscale_from_template(
    *, template_id: str, spec: AutoscaleSpec
) -> AutoscaleRun:
    template = await registry._load_template(template_id)
    template_name = template["template_name"]
    template_config = dict(template["config"] or {})

    scenario = registry._scenario_from_template_config(template_name, template_config)
    per_node_concurrency = int(scenario.concurrent_connections)
    load_mode = _load_mode_from_config(template_config)
    if per_node_concurrency < 1:
        if load_mode == "QPS":
            raise ValueError(
                "Autoscale QPS requires max workers (concurrent_connections) >= 1 per node."
            )
        raise ValueError("Autoscale requires concurrent_connections >= 1 per node.")

    target_nodes = 1
    if load_mode != "QPS":
        target_total = _autoscale_total_target_concurrency(template_config)
        if target_total < 1:
            raise ValueError("Autoscale target must be >= 1 (from load mode).")
        target_nodes = max(1, math.ceil(target_total / per_node_concurrency))
    else:
        target_qps = _autoscale_target_qps(template_config)
        if target_qps <= 0:
            raise ValueError("Autoscale QPS requires target_qps > 0.")

    parent_run_id = str(uuid4())
    table_cfg = scenario.table_configs[0] if scenario.table_configs else None
    warehouse = registry._warehouse_from_config(template_config)
    warehouse_snapshot = None
    if warehouse:
        warehouse_snapshot = await results_store.fetch_warehouse_config_snapshot(
            warehouse_name=str(warehouse)
        )

    await results_store.insert_test_prepare(
        test_id=parent_run_id,
        run_id=parent_run_id,
        test_name=str(template_name),
        scenario=scenario,
        table_name=str(table_cfg.name if table_cfg else ""),
        table_type=str(table_cfg.table_type if table_cfg else ""),
        warehouse=warehouse,
        warehouse_size=str(template_config.get("warehouse_size") or ""),
        template_id=str(template_id),
        template_name=str(template_name),
        template_config=template_config,
        warehouse_config_snapshot=warehouse_snapshot,
        query_tag=None,
    )

    run = AutoscaleRun(
        parent_run_id=parent_run_id,
        target_node_count=target_nodes,
    )
    return run


async def start_autoscale_from_test(
    *, test_id: str, spec: AutoscaleSpec
) -> AutoscaleRun:
    pool = snowflake_pool.get_default_pool()
    rows = await pool.execute_query(
        f"""
        SELECT TEST_CONFIG
        FROM {results_store._results_prefix()}.TEST_RESULTS
        WHERE TEST_ID = ?
        """,
        params=[test_id],
    )
    if not rows:
        raise ValueError("Test not found.")

    cfg_raw = rows[0][0]
    cfg = _parse_json_variant(cfg_raw)
    template_id = cfg.get("template_id") if isinstance(cfg, dict) else None
    template_cfg = cfg.get("template_config") if isinstance(cfg, dict) else None
    if not template_id or not isinstance(template_cfg, dict):
        raise ValueError("Missing template context for autoscale.")

    scenario = registry._scenario_from_template_config(
        str(cfg.get("template_name") or "autoscale"), template_cfg
    )
    per_node_concurrency = int(scenario.concurrent_connections)
    load_mode = _load_mode_from_config(template_cfg)
    if per_node_concurrency < 1:
        if load_mode == "QPS":
            raise ValueError(
                "Autoscale QPS requires max workers (concurrent_connections) >= 1 per node."
            )
        raise ValueError("Autoscale requires concurrent_connections >= 1 per node.")

    target_nodes = 1
    target_qps_total: float | None = None
    if load_mode != "QPS":
        target_total = _autoscale_total_target_concurrency(template_cfg)
        if target_total < 1:
            raise ValueError("Autoscale target must be >= 1 (from load mode).")
        target_nodes = max(1, math.ceil(target_total / per_node_concurrency))
    else:
        target_qps_total = _autoscale_target_qps(template_cfg)
        if target_qps_total <= 0:
            raise ValueError("Autoscale QPS requires target_qps > 0.")

    await pool.execute_query(
        f"""
        UPDATE {results_store._results_prefix()}.TEST_RESULTS
        SET STATUS = 'RUNNING',
            START_TIME = COALESCE(START_TIME, CURRENT_TIMESTAMP())
        WHERE TEST_ID = ?
        """,
        params=[test_id],
    )

    run = AutoscaleRun(
        parent_run_id=str(test_id),
        target_node_count=target_nodes,
    )
    asyncio.create_task(
        _run_autoscale(
            spec=spec,
            run=run,
            per_node_concurrency=per_node_concurrency,
            load_mode=load_mode,
            target_qps_total=target_qps_total,
        )
    )
    return run
