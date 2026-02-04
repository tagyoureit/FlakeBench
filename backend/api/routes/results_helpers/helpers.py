"""
Helper functions for test results routes.

Utility functions for error normalization, data aggregation, and common queries.
"""

import re
from typing import Any

from backend.config import settings

_TXN_RE = re.compile(r"\btransaction\s+\d+\b", re.IGNORECASE)
_SF_QUERY_ID_PREFIX_RE = re.compile(
    r"(\(\s*\d{5}\s*\)\s*:)\s*[0-9a-zA-Z-]{12,}\s*:",
    re.IGNORECASE,
)
_SF_ERROR_PREFIX_RE = re.compile(r"^\s*(\d+)\s*\(\s*(\d{5})\s*\)", re.IGNORECASE)
_ABORTED_BECAUSE_RE = re.compile(
    r"\bwas\s+aborted\s+because\b\s*(.*?)(?:\.|$)", re.IGNORECASE
)
_SQL_COMPILATION_RE = re.compile(
    r"\bsql\s+compilation\s+error\b\s*:\s*(.*?)(?:\.|$)", re.IGNORECASE
)

LATENCY_AGGREGATION_METHOD = "slowest_worker_approximation"


def get_prefix() -> str:
    """Get the database.schema prefix for queries."""
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


def error_reason(msg: str) -> str:
    """
    Extract a short, human-readable reason for UI summaries.

    Keep this low-cardinality and derived from the normalized message.
    """
    s = str(msg or "").strip()
    if not s:
        return ""

    m = _ABORTED_BECAUSE_RE.search(s)
    if m:
        return str(m.group(1) or "").strip()

    m = _SQL_COMPILATION_RE.search(s)
    if m:
        detail = str(m.group(1) or "").strip()
        return f"SQL compilation error: {detail}" if detail else "SQL compilation error"

    return ""


def normalize_error_message(msg: Any) -> str:
    """
    Normalize error messages to reduce high-cardinality IDs in grouping.

    Example: lock errors often embed statement IDs and transaction numbers that would
    otherwise explode group counts.
    """
    s = str(msg or "").strip()
    if not s:
        return ""

    s = _SF_QUERY_ID_PREFIX_RE.sub(r"\1 <query_id>:", s)
    s = re.sub(
        r"Statement\s+'[^']+'", "Statement '<statement_id>'", s, flags=re.IGNORECASE
    )
    s = re.sub(
        r"Your statement\s+'[^']+'",
        "Your statement '<statement_id>'",
        s,
        flags=re.IGNORECASE,
    )
    s = _TXN_RE.sub("transaction <txn>", s)
    s = " ".join(s.split())
    return s


def to_float_or_none(v: Any) -> float | None:
    """Convert value to float or return None."""
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


async def fetch_run_status(pool: Any, run_id: str) -> dict[str, Any] | None:
    """Fetch run status from RUN_STATUS table."""
    prefix = get_prefix()
    rows = await pool.execute_query(
        f"""
        SELECT RUN_ID, STATUS, PHASE, START_TIME, END_TIME, FIND_MAX_STATE, CANCELLATION_REASON,
               TIMESTAMPDIFF(SECOND, START_TIME, CURRENT_TIMESTAMP()) AS ELAPSED_SECONDS
        FROM {prefix}.RUN_STATUS
        WHERE RUN_ID = ?
        """,
        params=[run_id],
    )
    if not rows:
        return None
    (
        run_id_val,
        status,
        phase,
        start_time,
        end_time,
        find_max_state,
        cancellation_reason,
        elapsed_secs,
    ) = rows[0]
    return {
        "run_id": str(run_id_val or ""),
        "status": str(status or "").upper() or None,
        "phase": str(phase or "").upper() or None,
        "start_time": start_time,
        "end_time": end_time,
        "find_max_state": find_max_state,
        "cancellation_reason": str(cancellation_reason)
        if cancellation_reason
        else None,
        "elapsed_seconds": float(elapsed_secs) if elapsed_secs is not None else None,
    }


async def aggregate_parent_enrichment_status(
    *, pool: Any, run_id: str
) -> tuple[str | None, str | None]:
    """Aggregate ENRICHMENT_STATUS, checking parent first (authoritative), then workers."""
    prefix = get_prefix()

    parent_rows = await pool.execute_query(
        f"""
        SELECT ENRICHMENT_STATUS, ENRICHMENT_ERROR
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID = ?
        """,
        params=[run_id],
    )
    if parent_rows and parent_rows[0][0]:
        parent_status = str(parent_rows[0][0]).strip().upper()
        parent_error = parent_rows[0][1]
        if parent_status in ("COMPLETED", "FAILED", "SKIPPED"):
            return parent_status, str(parent_error) if parent_error else None

    worker_rows = await pool.execute_query(
        f"""
        SELECT ENRICHMENT_STATUS, ENRICHMENT_ERROR
        FROM {prefix}.TEST_RESULTS
        WHERE RUN_ID = ?
          AND TEST_ID <> ?
        """,
        params=[run_id, run_id],
    )
    statuses: list[str] = []
    errors: list[str] = []
    for status_value, error in worker_rows or []:
        status_val = str(status_value or "").strip().upper()
        if status_val:
            statuses.append(status_val)
        if error:
            errors.append(str(error))
    if not statuses:
        if parent_rows and parent_rows[0][0]:
            parent_status = str(parent_rows[0][0]).strip().upper()
            parent_error = parent_rows[0][1]
            return parent_status, str(parent_error) if parent_error else None
        return None, None
    if "PENDING" in statuses:
        return "PENDING", None
    if "FAILED" in statuses:
        error_out = next((err for err in errors if err), None)
        return "FAILED", error_out
    if "COMPLETED" in statuses:
        return "COMPLETED", None
    if "SKIPPED" in statuses:
        return "SKIPPED", None
    return statuses[0], None


async def aggregate_parent_enrichment_stats(
    *, pool: Any, run_id: str
) -> tuple[int, int, float]:
    """Aggregate enrichment statistics for a run."""
    prefix = get_prefix()
    rows = await pool.execute_query(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(SF_CLUSTER_NUMBER) AS enriched
        FROM {prefix}.QUERY_EXECUTIONS qe
        JOIN {prefix}.TEST_RESULTS tr
          ON qe.TEST_ID = tr.TEST_ID
        WHERE tr.RUN_ID = ?
          AND tr.TEST_ID <> ?
        """,
        params=[run_id, run_id],
    )
    total = int(rows[0][0] or 0) if rows else 0
    enriched = int(rows[0][1] or 0) if rows else 0
    ratio = enriched / total if total > 0 else 0.0
    return total, enriched, ratio


def compute_aggregated_find_max(worker_results: list[dict]) -> dict:
    """
    Compute true aggregate metrics across all workers' find_max_result.

    For each concurrency level (step), aggregates:
    - Total QPS (sum across workers)
    - Max P95/P99 latencies (worst case)
    - Number of active workers at each step
    """
    if not worker_results:
        return {}

    steps_by_concurrency: dict[int, dict[int, dict]] = {}
    all_baselines_p95 = []
    all_baselines_p99 = []

    for worker in worker_results:
        fmr = worker.get("find_max_result", {})
        if not fmr:
            continue

        worker_idx = worker.get("worker_index", 0)
        if fmr.get("baseline_p95_latency_ms"):
            all_baselines_p95.append(fmr["baseline_p95_latency_ms"])
        if fmr.get("baseline_p99_latency_ms"):
            all_baselines_p99.append(fmr["baseline_p99_latency_ms"])

        step_history = fmr.get("step_history", [])
        for step in step_history:
            cc = step.get("concurrency")
            if cc is not None:
                if cc not in steps_by_concurrency:
                    steps_by_concurrency[cc] = {}
                if worker_idx not in steps_by_concurrency[cc]:
                    steps_by_concurrency[cc][worker_idx] = {
                        "worker_index": worker_idx,
                        **step,
                    }

    aggregated_steps = []
    total_workers = len(worker_results)

    for cc in sorted(steps_by_concurrency.keys()):
        worker_steps = list(steps_by_concurrency[cc].values())
        active_workers = len(worker_steps)

        total_qps = sum(s.get("qps", 0) or 0 for s in worker_steps)
        max_p95 = max((s.get("p95_latency_ms") or 0 for s in worker_steps), default=0)
        max_p99 = max((s.get("p99_latency_ms") or 0 for s in worker_steps), default=0)
        avg_p95 = (
            sum(s.get("p95_latency_ms") or 0 for s in worker_steps) / active_workers
            if active_workers > 0
            else 0
        )
        avg_p99 = (
            sum(s.get("p99_latency_ms") or 0 for s in worker_steps) / active_workers
            if active_workers > 0
            else 0
        )

        any_degraded = any(s.get("degraded") for s in worker_steps)
        reasons = [
            s.get("degrade_reason") for s in worker_steps if s.get("degrade_reason")
        ]

        aggregated_steps.append(
            {
                "concurrency": cc,
                "total_concurrency": cc * active_workers,
                "qps": round(total_qps, 2),
                "p95_latency_ms": round(max_p95, 2),
                "p99_latency_ms": round(max_p99, 2),
                "avg_p95_latency_ms": round(avg_p95, 2),
                "avg_p99_latency_ms": round(avg_p99, 2),
                "active_workers": active_workers,
                "total_workers": total_workers,
                "degraded": any_degraded,
                "degrade_reasons": reasons if reasons else None,
            }
        )

    best_step = None
    for step in aggregated_steps:
        if step["active_workers"] == total_workers and not step["degraded"]:
            if best_step is None or step["qps"] > best_step["qps"]:
                best_step = step

    if best_step is None and aggregated_steps:
        non_degraded = [s for s in aggregated_steps if not s["degraded"]]
        if non_degraded:
            best_step = max(non_degraded, key=lambda s: s["qps"])
        else:
            best_step = aggregated_steps[0]

    return {
        "step_history": aggregated_steps,
        "baseline_p95_latency_ms": max(all_baselines_p95)
        if all_baselines_p95
        else None,
        "baseline_p99_latency_ms": max(all_baselines_p99)
        if all_baselines_p99
        else None,
        "final_best_concurrency": best_step["concurrency"] if best_step else None,
        "final_best_qps": best_step["qps"] if best_step else None,
        "total_workers": total_workers,
        "is_aggregate": True,
    }
