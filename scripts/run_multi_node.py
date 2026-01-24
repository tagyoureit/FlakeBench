#!/usr/bin/env python3
"""Run multiple headless workers locally for multi-node orchestration."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from typing import Any
from uuid import uuid4

from backend.core.results_store import update_parent_run_aggregate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run multiple benchmark workers locally."
    )
    parser.add_argument("--template-id", required=True, help="Template ID to run.")
    parser.add_argument(
        "--node-count",
        type=int,
        required=True,
        help="Number of worker processes to launch.",
    )
    parser.add_argument(
        "--parent-run-id",
        default=None,
        help="Parent run id for aggregation (optional).",
    )
    parser.add_argument(
        "--node-id-prefix",
        default="local",
        help="Prefix for node_id values.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Override concurrent_connections per worker.",
    )
    parser.add_argument(
        "--min-concurrency",
        type=int,
        default=None,
        help="Override min_concurrency (QPS mode).",
    )
    parser.add_argument(
        "--start-concurrency",
        type=int,
        default=None,
        help="Override start_concurrency (FIND_MAX_CONCURRENCY).",
    )
    parser.add_argument(
        "--target-qps",
        type=float,
        default=None,
        help="Override target_qps (QPS mode).",
    )
    parser.add_argument(
        "--uv-bin",
        default="uv",
        help="Path to uv executable.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop remaining workers if one fails.",
    )
    return parser


def _uv_available(uv_bin: str) -> bool:
    return shutil.which(uv_bin) is not None


def _build_worker_cmd(
    *,
    uv_bin: str,
    template_id: str,
    parent_run_id: str,
    worker_group_id: int,
    worker_group_count: int,
    node_id: str,
    overrides: dict[str, Any],
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
    ]
    if overrides.get("concurrent_connections") is not None:
        cmd.extend(["--concurrency", str(overrides["concurrent_connections"])])
    if overrides.get("min_concurrency") is not None:
        cmd.extend(["--min-concurrency", str(overrides["min_concurrency"])])
    if overrides.get("start_concurrency") is not None:
        cmd.extend(["--start-concurrency", str(overrides["start_concurrency"])])
    if overrides.get("target_qps") is not None:
        cmd.extend(["--target-qps", str(overrides["target_qps"])])
    return cmd


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not _uv_available(args.uv_bin):
        print("uv not found. Install uv to run local workers.", file=sys.stderr)
        return 1

    node_count = int(args.node_count)
    if node_count <= 0:
        print("--node-count must be > 0", file=sys.stderr)
        return 1

    parent_run_id = str(args.parent_run_id or uuid4())
    print(f"[orchestrator] parent_run_id={parent_run_id}")

    overrides = {}
    if args.concurrency is not None:
        overrides["concurrent_connections"] = int(args.concurrency)
    if args.min_concurrency is not None:
        overrides["min_concurrency"] = int(args.min_concurrency)
    if args.start_concurrency is not None:
        overrides["start_concurrency"] = int(args.start_concurrency)
    if args.target_qps is not None:
        overrides["target_qps"] = float(args.target_qps)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    procs: list[tuple[int, subprocess.Popen[str]]] = []
    for idx in range(node_count):
        node_id = f"{args.node_id_prefix}-{idx}"
        cmd = _build_worker_cmd(
            uv_bin=str(args.uv_bin),
            template_id=str(args.template_id),
            parent_run_id=parent_run_id,
            worker_group_id=idx,
            worker_group_count=node_count,
            node_id=node_id,
            overrides=overrides,
        )
        print(f"[orchestrator] starting worker {idx} node_id={node_id}")
        proc = subprocess.Popen(cmd, env=env, text=True)
        procs.append((idx, proc))

    exit_code = 0
    for idx, proc in procs:
        rc = proc.wait()
        if rc != 0:
            print(f"[orchestrator] worker {idx} exited with {rc}", file=sys.stderr)
            exit_code = 1
            if args.fail_fast:
                break

    if exit_code == 0:
        print("[orchestrator] all workers completed successfully")
    if parent_run_id:
        try:
            asyncio.run(update_parent_run_aggregate(parent_run_id=parent_run_id))
            print("[orchestrator] parent aggregation updated")
        except Exception as exc:
            print(f"[orchestrator] parent aggregation failed: {exc}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
